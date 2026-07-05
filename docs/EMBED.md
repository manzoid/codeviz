# Embedding the Python visualizer in a browser

This describes how a downstream browser app (for example, a Pyodide-based
exercise runner) can produce a codeviz visualization entirely client-side, with
no server round-trip. Today this path is **Python-only** (see the limitation at
the end).

## Get the assets

Run:

```
codeviz web-assets <outdir>
```

This copies three self-contained files plus an attribution notice into
`<outdir>`:

- `viewer_template.html` — the renderer/UI. Inline CSS + JS, no network fetches.
  Has two placeholders: `__TITLE__` and `__TRACE_JSON__`.
- `pg_logger.py` — the Python tracer (vendored from Online Python Tutor).
- `pg_encoder.py` — the heap encoder it uses.
- `NOTICE.txt` — MIT attribution for the above. Ship it alongside the assets.

`pg_logger.py` and `pg_encoder.py` are pure-Python stdlib and Pyodide-safe. The
tracer's `resource.setrlimit` sandboxing is skipped because the entry point below
passes `disable_security_checks=True` internally, and `import resource` is
already wrapped in try/except.

## Step 1: trace the code in Pyodide

Load Pyodide, then write the two tracer files into the Pyodide virtual
filesystem so they can be imported. Then call `exec_script_str_local`, whose
signature is:

```
exec_script_str_local(script_str, raw_input_lst_json, cumulative_mode,
                       heap_primitives, finalizer_func)
```

The finalizer receives `(input_code_str, trace_list)`. Capture them as
`{"code": ..., "trace": ...}` and JSON-encode the result. Example driver run in
Pyodide:

```python
import sys
sys.path.insert(0, "/codeviz")   # wherever you wrote pg_logger.py / pg_encoder.py
import json, pg_logger

def trace_to_json(code):
    captured = {}
    def finalizer(input_code, output_trace):
        captured["data"] = {"code": input_code, "trace": output_trace}
        return ""
    pg_logger.exec_script_str_local(
        code,
        None,    # raw_input_lst_json
        False,   # cumulative_mode
        False,   # heap_primitives
        finalizer,
    )
    return json.dumps(captured["data"])
```

From JavaScript with Pyodide:

```js
const pyodide = await loadPyodide();
// write pg_logger.py + pg_encoder.py into the FS first, e.g.:
pyodide.FS.mkdir("/codeviz");
pyodide.FS.writeFile("/codeviz/pg_logger.py", pgLoggerSource);
pyodide.FS.writeFile("/codeviz/pg_encoder.py", pgEncoderSource);
// then define trace_to_json (the Python above) once, and call it:
const traceJson = pyodide.globals.get("trace_to_json")(userCode);
```

Notes:

- `pg_logger` prints an internal traceback to **stderr** when the *user's* code
  raises. That exception is already captured in the trace, so you can route or
  ignore that stderr noise. In Python the CLI does this with
  `contextlib.redirect_stderr(io.StringIO())`; in Pyodide, set
  `stderr` handling on `loadPyodide` or ignore it.
- The trace shape is the Online Python Tutor (OPT) format:
  `{"code": <src str>, "trace": [ {line, event, func_name, globals,
  ordered_globals, stack_to_render, heap, stdout, ...}, ... ]}`.

## Step 2: render into the viewer

The viewer template expects the trace JSON with a top-level `"lang"` key added,
and with `</` escaped to `<\/` (so a `</script>` inside a string literal cannot
break out of the inline `<script>` block). Reproduce exactly what
`render.py::render_html` does:

```js
function renderViewer(traceJson, title) {
  // traceJson is the JSON string from step 1 (an object {code, trace}).
  const payload = JSON.parse(traceJson);
  payload.lang = "python";
  let blob = JSON.stringify(payload).replaceAll("</", "<\\/");
  return viewerTemplateHtml
    .replaceAll("__TRACE_JSON__", blob)
    .replaceAll("__TITLE__", title);
}
```

Then drop the resulting HTML string into a sandboxed iframe:

```js
const html = renderViewer(traceJson, "My exercise");
const iframe = document.createElement("iframe");
iframe.setAttribute("sandbox", "allow-scripts"); // scripts only, no same-origin
iframe.srcdoc = html;
container.appendChild(iframe);
```

`sandbox="allow-scripts"` is enough: the page is fully self-contained (all CSS
and JS are inline; the only `http://` reference is the SVG XML namespace URI,
which is an identifier, not a fetch). Do **not** add `allow-same-origin` unless
you have a reason to — the viewer does not need it.

## Limitation: Python only

This in-browser path works for Python because the tracer (`pg_logger`) is pure
Python and runs under Pyodide.

The JavaScript/TypeScript tracer (`codeviz/tracers/js/trace.js`) drives Node's
V8 Inspector Protocol and does **not** run in-browser. There is currently no
in-browser JS tracer; adding one is a future addition. Likewise the C/C++/Java
tracers run in Docker containers and are not browser-embeddable. Downstream apps
that need JS/TS stepping in the browser will need a separate tracer that emits
the same OPT trace format, which the same `viewer_template.html` can then render.
