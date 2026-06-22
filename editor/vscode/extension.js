// codeviz VS Code extension.
//
// Runs codeviz on the active file and shows the resulting self-contained HTML
// in a webview beside the editor — no localhost server, no Simple Browser, no
// ports. Re-traces on save, and (optionally) follows whichever supported file
// you switch to.
const vscode = require("vscode");
const cp = require("child_process");
const fs = require("fs");
const os = require("os");
const path = require("path");

const SUPPORTED = new Set([
  ".py", ".js", ".mjs", ".ts", ".c", ".h",
  ".cpp", ".cc", ".cxx", ".hpp", ".java", ".s", ".asm",
]);

let panel = null;
let currentFile = null;
let tracing = false;

function cfg() {
  return vscode.workspace.getConfiguration("codeviz");
}

function isSupported(doc) {
  return !!doc && SUPPORTED.has(path.extname(doc.fileName).toLowerCase());
}

function escapeHtml(s) {
  return String(s).replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
}

function placeholder(msg) {
  return `<!DOCTYPE html><body style="font:14px -apple-system,sans-serif;color:#444;padding:24px">${msg}</body>`;
}

// Run codeviz on `file`, returning the generated HTML. Uses the `codeviz`
// command on PATH by default; if codeviz.scriptPath is set, runs that with
// codeviz.pythonPath instead.
function runCodeviz(file) {
  return new Promise((resolve, reject) => {
    const out = path.join(os.tmpdir(), "codeviz-vscode-view.html");
    const script = cfg().get("scriptPath");
    let cmd, args;
    if (script) {
      cmd = cfg().get("pythonPath") || "python3";
      args = [script, file, "-o", out];
    } else {
      cmd = cfg().get("command") || "codeviz";
      args = [file, "-o", out];
    }
    cp.execFile(cmd, args, { timeout: 120000 }, (err, _stdout, stderr) => {
      if (err) {
        if (err.code === "ENOENT") {
          return reject(new Error(
            `'${cmd}' not found on PATH. Install codeviz (run ./install.sh in the repo) ` +
            `or set codeviz.scriptPath to your codeviz.py.`));
        }
        return reject(new Error((stderr || err.message || "").trim()));
      }
      fs.readFile(out, "utf8", (e, html) => (e ? reject(e) : resolve(html)));
    });
  });
}

async function showFile(file) {
  if (!panel) {
    panel = vscode.window.createWebviewPanel(
      "codeviz", "codeviz", vscode.ViewColumn.Beside,
      { enableScripts: true, retainContextWhenHidden: true }
    );
    panel.onDidDispose(() => { panel = null; currentFile = null; });
  }
  currentFile = file;
  panel.title = "codeviz: " + path.basename(file);
  if (!tracing) panel.webview.html = placeholder(`tracing <b>${escapeHtml(path.basename(file))}</b> …`);
  tracing = true;
  try {
    let html = await runCodeviz(file);
    // Each (re)trace should start at step 1: clear the page's saved step before
    // its script reads it. (The HTTP live-reload poller no-ops off http.)
    html = html.replace("<head>", '<head><script>try{sessionStorage.clear()}catch(e){}</script>');
    if (panel) panel.webview.html = html;
  } catch (e) {
    if (panel) panel.webview.html = placeholder(
      `<div style="color:#b91c1c"><b>codeviz error</b><pre style="white-space:pre-wrap;font:12px monospace">${escapeHtml(String(e.message || e))}</pre></div>`
    );
  } finally {
    tracing = false;
  }
}

function activate(context) {
  context.subscriptions.push(
    vscode.commands.registerCommand("codeviz.show", () => {
      const ed = vscode.window.activeTextEditor;
      if (!ed || !isSupported(ed.document)) {
        vscode.window.showWarningMessage("codeviz: open a supported source file first (.py .js .ts .c .cpp .java .s).");
        return;
      }
      showFile(ed.document.fileName);
    }),

    vscode.commands.registerCommand("codeviz.toggleFollow", async () => {
      const c = cfg();
      const v = !c.get("autoFollow");
      await c.update("autoFollow", v, vscode.ConfigurationTarget.Global);
      vscode.window.showInformationMessage("codeviz auto-follow " + (v ? "ON" : "OFF"));
    }),

    // Re-trace on save (the shown file, or any supported file when following).
    vscode.workspace.onDidSaveTextDocument((doc) => {
      if (!panel) return;
      if (doc.fileName === currentFile || (cfg().get("autoFollow") && isSupported(doc))) {
        showFile(doc.fileName);
      }
    }),

    // Follow the active editor.
    vscode.window.onDidChangeActiveTextEditor((ed) => {
      if (!panel || !cfg().get("autoFollow")) return;
      if (ed && isSupported(ed.document) && ed.document.fileName !== currentFile) {
        showFile(ed.document.fileName);
      }
    })
  );
}

function deactivate() {}

module.exports = { activate, deactivate };
