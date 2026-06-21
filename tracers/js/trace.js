#!/usr/bin/env node
// codeviz JavaScript/TypeScript tracer.
//
// Drives the V8 Inspector Protocol to single-step user code and emit an
// Online Python Tutor (OPT) trace JSON ({code, trace:[...]}) on stdout.
// Original work for modern Node (18+); OPT's jslogger.js only runs on Node 6.
//
// Usage:  node trace.js --name foo.js [--typescript]   (source on stdin)

const fs = require('fs');
const os = require('os');
const path = require('path');
const { spawn } = require('child_process');

const MAX_STEPS = 1000;
const WATCHDOG_MS = 20000;
const LOCAL_SCOPE_TYPES = new Set(['local', 'block', 'catch', 'eval']);
const DEBUG = !!process.env.CODEVIZ_DEBUG;
const dbg = (...a) => { if (DEBUG) process.stderr.write('[dbg] ' + a.join(' ') + '\n'); };

function parseArgs(argv) {
  const o = { name: 'snippet.js', typescript: false };
  for (let i = 0; i < argv.length; i++) {
    if (argv[i] === '--name') o.name = argv[++i];
    else if (argv[i] === '--typescript') o.typescript = true;
  }
  return o;
}

function compileTypeScript(src) {
  let ts;
  try {
    ts = require('typescript');
  } catch (e) {
    throw new Error(
      "TypeScript support needs the 'typescript' package. Install it near codeviz " +
      "(npm i -g typescript, or npm i typescript in tracers/js).");
  }
  // Strip types but keep line numbers stable (no downleveling).
  const out = ts.transpileModule(src, {
    compilerOptions: { target: ts.ScriptTarget.ESNext, module: ts.ModuleKind.CommonJS,
                       removeComments: false, sourceMap: false },
  });
  return out.outputText;
}

// ---- minimal CDP client over the inspector WebSocket ----
class CDP {
  constructor(ws) {
    this.ws = ws;
    this.id = 1;
    this.pending = new Map();
    this.handlers = new Map();
    ws.addEventListener('message', (ev) => {
      const msg = JSON.parse(ev.data);
      if (msg.id !== undefined) {
        const p = this.pending.get(msg.id);
        if (!p) return;
        this.pending.delete(msg.id);
        msg.error ? p.reject(new Error(msg.error.message)) : p.resolve(msg.result);
      } else {
        const h = this.handlers.get(msg.method);
        if (h) h(msg.params);
      }
    });
  }
  send(method, params = {}) {
    const id = this.id++;
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      this.ws.send(JSON.stringify({ id, method, params }));
    });
  }
  on(method, fn) { this.handlers.set(method, fn); }
}

async function main() {
  const opts = parseArgs(process.argv.slice(2));
  let code = fs.readFileSync(0, 'utf8');     // original source (shown in UI)
  let runCode = code;
  if (opts.typescript) runCode = compileTypeScript(code);

  const stamp = `${process.pid}-${Date.now()}`;
  const tmp = path.join(os.tmpdir(), `codeviz-${stamp}.js`);
  // Run the user file directly (so Break-on-start lands in user code), but
  // append a `debugger;` sentinel: the debuggee never exits on its own while
  // the inspector is attached, so a pause *past the user's last line* is our
  // unambiguous "program finished" signal.
  const origLineCount = runCode.split('\n').length;
  fs.writeFileSync(tmp, runCode + '\n;debugger;\n');

  const child = spawn(process.execPath, ['--inspect-brk=0', tmp],
    { stdio: ['ignore', 'pipe', 'pipe'] });

  // The ws URL is printed to stderr: "Debugger listening on ws://127.0.0.1:PORT/UUID"
  const wsUrl = await new Promise((resolve, reject) => {
    let buf = '';
    const onErr = (d) => {
      buf += d.toString();
      const m = buf.match(/ws:\/\/[^\s]+/);
      if (m) { child.stderr.off('data', onErr); resolve(m[0]); }
    };
    child.stderr.on('data', onErr);
    child.on('exit', () => reject(new Error('node exited before debugger came up:\n' + buf)));
    setTimeout(() => reject(new Error('timed out waiting for inspector')), 10000);
  });

  const ws = new WebSocket(wsUrl);
  await new Promise((res, rej) => { ws.addEventListener('open', res); ws.addEventListener('error', rej); });
  const cdp = new CDP(ws);

  const scripts = new Map();       // scriptId -> url
  let userScriptId = null;
  const userBase = path.basename(tmp);
  let stdout = '';
  const trace = [];
  let pendingException = null;

  cdp.on('Debugger.scriptParsed', (p) => {
    scripts.set(p.scriptId, p.url);
    if (p.url.endsWith(userBase)) userScriptId = p.scriptId;
  });
  cdp.on('Runtime.consoleAPICalled', (p) => {
    const parts = (p.args || []).map(renderConsoleArg);
    stdout += parts.join(' ') + '\n';
  });

  await cdp.send('Runtime.enable');
  await cdp.send('Debugger.enable');
  await cdp.send('Debugger.setPauseOnExceptions', { state: 'uncaught' });
  await cdp.send('Debugger.setBlackboxPatterns', { patterns: ['^node:', '/internal/', 'node:internal'] });

  const done = new Promise((resolve) => {
    let finished = false;
    const finish = (why) => { if (!finished) { finished = true; dbg('finish:', why); resolve(); } };
    child.on('exit', () => finish('child-exit'));
    ws.addEventListener('close', () => finish('ws-close'));
    // .unref() so a pending timer never keeps this process alive after we finish.
    setTimeout(() => finish('watchdog'), WATCHDOG_MS).unref();
    const finishSoon = () => setTimeout(() => finish('post-exception'), 500).unref();

    cdp.on('Debugger.paused', async (params) => {
      try {
        const top = params.callFrames[0];
        const topId = top && top.location.scriptId;
        const topLine = top ? top.location.lineNumber + 1 : 0;
        dbg('paused reason=', params.reason, 'topId=', String(topId),
            'user=', String(userScriptId), 'line=', topLine, 'steps=', trace.length);

        if (params.reason === 'exception' || params.reason === 'promiseRejection') {
          const d = params.data || {};
          const raw = d.description || (d.value && d.value.description) ||
                      (d.className ? d.className : 'Error');
          pendingException = String(raw).split('\n')[0];   // first line only
          const step = await buildStep(cdp, params, userScriptId, scripts, stdout, pendingException);
          if (step) trace.push(step);
          await cdp.send('Debugger.resume').catch(() => {});
          finishSoon();
          return;
        }

        // In library / Node internals (not user code) -> climb back out.
        if (topId !== userScriptId) {
          await cdp.send('Debugger.stepOut').catch(() => cdp.send('Debugger.resume').catch(() => {}));
          return;
        }

        // Reached the appended `debugger;` sentinel past the user's last line = done.
        if (topLine > origLineCount) { finish('sentinel'); return; }

        // In user code -> record a step and advance.
        const step = await buildStep(cdp, params, userScriptId, scripts, stdout, pendingException);
        if (step) trace.push(step);
        if (trace.length >= MAX_STEPS) { await cdp.send('Debugger.resume').catch(() => {}); finish('max-steps'); return; }
        await cdp.send('Debugger.stepInto').catch(() => cdp.send('Debugger.resume').catch(() => {}));
      } catch (e) {
        dbg('paused handler error:', e && e.message);
        await cdp.send('Debugger.stepInto').catch(() => cdp.send('Debugger.resume').catch(() => {}));
      }
    });
  });

  await cdp.send('Runtime.runIfWaitingForDebugger');
  await done;
  try { ws.close(); } catch (_) {}
  try { child.kill('SIGKILL'); } catch (_) {}   // release the "waiting for debugger" child
  try { fs.unlinkSync(tmp); } catch (_) {}

  // Output from the last statement (e.g. a final console.log) lands after the
  // last recorded step — reflect the complete program output on that step.
  if (trace.length) trace[trace.length - 1].stdout = stdout;

  process.stdout.write(JSON.stringify({ code, trace, lang: 'javascript' }));
  process.exit(0);
}

function renderConsoleArg(a) {
  if (a.type === 'string') return a.value;
  if (a.type === 'number' || a.type === 'boolean') return String(a.value);
  if (a.type === 'undefined') return 'undefined';
  if (a.subtype === 'null') return 'null';
  if (a.value !== undefined) return String(a.value);
  return a.description || a.className || '[object]';
}

// Inject a WeakMap-backed id assigner into the debuggee so the SAME object
// gets the SAME heap id within a step and across steps (preserves aliasing).
let _helperReady = false;
async function ensureHelper(cdp) {
  if (_helperReady) return;
  await cdp.send('Runtime.evaluate', {
    expression:
      "globalThis.__cvid||(globalThis.__cvid=(function(){var m=new WeakMap(),n=0;" +
      "return function(o){if(!m.has(o))m.set(o,++n);return m.get(o);};})())",
  });
  _helperReady = true;
}

async function stableId(cdp, ro) {
  const r = await cdp.send('Runtime.callFunctionOn', {
    objectId: ro.objectId,
    functionDeclaration: 'function(){return globalThis.__cvid(this);}',
    returnByValue: true,
  });
  return r.result.value;
}

// ---- build one OPT step from a Debugger.paused event ----
async function buildStep(cdp, params, userScriptId, scripts, stdout, exceptionMsg) {
  // keep only frames in the user script (drop Node internals)
  const userFrames = params.callFrames.filter((f) => f.location.scriptId === userScriptId);
  if (userFrames.length === 0) return null;  // inside library; skip
  await ensureHelper(cdp);

  const ctx = { cdp, heap: {}, seen: new Set(), queue: [] };
  const topLine = userFrames[0].location.lineNumber + 1;
  const event = exceptionMsg ? 'exception' : 'step_line';

  // bottom (module) frame -> globals; the rest -> stack_to_render (top first)
  const bottom = userFrames[userFrames.length - 1];
  const aboveBottom = userFrames.slice(0, userFrames.length - 1);

  const globalsScope = await readFrameVars(ctx, bottom, true);
  const stack_to_render = [];
  for (let i = 0; i < aboveBottom.length; i++) {
    const fr = aboveBottom[i];
    const vars = await readFrameVars(ctx, fr, false);
    stack_to_render.push({
      func_name: fr.functionName || '<anonymous>',
      is_highlighted: i === 0,
      is_parent: false,
      is_zombie: false,
      parent_frame_id_list: [],
      unique_hash: (fr.functionName || 'anon') + '_' + i,
      frame_id: aboveBottom.length - i,
      encoded_locals: vars.locals,
      ordered_varnames: vars.order,
    });
  }

  await expandHeap(ctx);   // BFS over referenced objects

  const step = {
    event,
    line: topLine,
    func_name: aboveBottom.length ? (aboveBottom[0].functionName || '<anonymous>') : '<module>',
    globals: globalsScope.locals,
    ordered_globals: globalsScope.order,
    stack_to_render,
    heap: ctx.heap,
    stdout,
  };
  if (exceptionMsg) step.exception_msg = exceptionMsg;
  return step;
}

async function readFrameVars(ctx, frame, isModule) {
  const locals = {};
  const order = [];
  const seen = new Set();
  for (const sc of (frame.scopeChain || [])) {
    const take = LOCAL_SCOPE_TYPES.has(sc.type) ||
                 (isModule && (sc.type === 'script' || sc.type === 'module' || sc.type === 'closure'));
    if (!take || sc.type === 'global') continue;
    if (!sc.object || !sc.object.objectId) continue;
    let props;
    try {
      props = await ctx.cdp.send('Runtime.getProperties',
        { objectId: sc.object.objectId, ownProperties: true, generatePreview: false });
    } catch (_) { continue; }
    for (const pr of (props.result || [])) {
      if (seen.has(pr.name)) continue;
      if (['this', 'exports', 'require', 'module', '__dirname', '__filename'].includes(pr.name)) continue;
      if (!pr.value) continue;            // skip accessors / uninitialized
      seen.add(pr.name);
      order.push(pr.name);
      locals[pr.name] = await encodeValue(ctx, pr.value);
    }
  }
  return { locals, order };
}

async function encodeValue(ctx, ro) {
  switch (ro.type) {
    case 'undefined': return ['JS_TOKEN', 'undefined'];
    case 'string': return ro.value;
    case 'boolean': return ro.value;
    case 'number':
      return (ro.unserializableValue !== undefined) ? ['JS_TOKEN', ro.unserializableValue] : ro.value;
    case 'bigint': return ['JS_TOKEN', ro.unserializableValue || (ro.description || 'bigint')];
    case 'symbol': return ['JS_TOKEN', ro.description || 'Symbol()'];
    case 'function': return await refFor(ctx, ro);
    case 'object':
      if (ro.subtype === 'null') return ['JS_TOKEN', 'null'];
      return await refFor(ctx, ro);
    default:
      return ['JS_TOKEN', String(ro.value !== undefined ? ro.value : (ro.description || ro.type))];
  }
}

async function refFor(ctx, ro) {
  if (!ro.objectId) return ['JS_TOKEN', ro.description || '[object]'];
  const id = await stableId(ctx.cdp, ro);
  if (!ctx.seen.has(id)) {
    ctx.seen.add(id);
    ctx.queue.push({ id, ro });
  }
  return ['REF', id];
}

async function expandHeap(ctx) {
  while (ctx.queue.length) {
    const { id, ro } = ctx.queue.shift();
    if (ctx.heap[id]) continue;
    ctx.heap[id] = await encodeObject(ctx, ro);
  }
}

async function encodeObject(ctx, ro) {
  if (ro.type === 'function') {
    return ['FUNCTION', (ro.description || 'function').split('\n')[0].trim()];
  }
  const sub = ro.subtype;
  let props;
  try {
    props = await ctx.cdp.send('Runtime.getProperties',
      { objectId: ro.objectId, ownProperties: true, generatePreview: false });
  } catch (_) {
    return ['INSTANCE', ro.className || 'object'];
  }
  const own = (props.result || []).filter((p) => p.enumerable && p.value);
  const internal = props.internalProperties || [];

  if (sub === 'array') {
    const out = ['LIST'];
    const len = own.find((p) => p.name === 'length');
    const n = len && len.value ? len.value.value : own.length;
    for (let i = 0; i < n; i++) {
      const cell = own.find((p) => p.name === String(i));
      out.push(cell ? await encodeValue(ctx, cell.value) : ['JS_TOKEN', 'empty']);
    }
    return out;
  }
  if (sub === 'map' || sub === 'set') {
    const entries = internal.find((p) => p.name === '[[Entries]]');
    const out = [sub === 'map' ? 'DICT' : 'SET'];
    if (entries && entries.value && entries.value.objectId) {
      const er = await ctx.cdp.send('Runtime.getProperties',
        { objectId: entries.value.objectId, ownProperties: true });
      for (const e of (er.result || [])) {
        if (!e.value || !e.value.objectId) continue;
        const kv = await ctx.cdp.send('Runtime.getProperties',
          { objectId: e.value.objectId, ownProperties: true });
        const get = (nm) => (kv.result.find((x) => x.name === nm) || {}).value;
        if (sub === 'map') {
          out.push([await encodeValue(ctx, get('key')), await encodeValue(ctx, get('value'))]);
        } else {
          out.push(await encodeValue(ctx, get('value') || get('0')));
        }
      }
    }
    return out;
  }

  // plain object vs class instance
  const cls = ro.className || 'Object';
  const pairs = [];
  for (const p of own) {
    if (p.name === '__proto__') continue;
    pairs.push([p.name, await encodeValue(ctx, p.value)]);
  }
  if (cls === 'Object') return ['DICT', ...pairs];
  return ['INSTANCE', cls, ...pairs];
}

main().catch((e) => {
  process.stderr.write((DEBUG ? String(e && e.stack || e) : String(e && e.message || e)) + '\n');
  process.exit(1);
});
