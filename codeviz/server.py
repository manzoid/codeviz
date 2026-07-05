"""Live-reload server: re-trace a file on every save; the page auto-reloads.

Also hosts an on-demand trace API (`serve_api`) for embedding codeviz in another
app (e.g. the warmups web app): POST a snippet, get back the viewer HTML.
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .core import build_page


def serve(path: str, port: int = 8930, open_browser: bool = False):
    state = {"html": b"", "version": 0, "mtime": None}

    def rebuild() -> int:
        html, n, lang = build_page(path)
        state["html"] = html.encode("utf-8")
        state["version"] += 1
        return n

    try:
        n = rebuild()
        print(f"traced {os.path.basename(path)} ({n} steps)")
    except Exception as e:
        print(f"initial trace failed: {e}", file=sys.stderr)
        # serve a minimal error page so the tab shows *something*
        state["html"] = f"<pre>trace error:\n{e}</pre>".encode("utf-8")

    state["mtime"] = os.path.getmtime(path)

    def watch():
        while True:
            time.sleep(0.4)
            try:
                m = os.path.getmtime(path)
            except OSError:
                continue
            if m != state["mtime"]:
                state["mtime"] = m
                try:
                    print(f"reloaded ({rebuild()} steps)")
                except Exception as e:  # keep serving last good page
                    print(f"trace error: {e}", file=sys.stderr)

    threading.Thread(target=watch, daemon=True).start()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            if self.path in ("/", "/index.html"):
                body, ctype = state["html"], "text/html; charset=utf-8"
            elif self.path.startswith("/version"):
                body, ctype = str(state["version"]).encode(), "text/plain"
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = f"http://localhost:{port}/"
    print(f"\n  serving {url}")
    print(f"  VS Code: Cmd+Shift+P -> Simple Browser: Show -> {url}")
    print("  edit + save the source and the page reloads.  Ctrl+C to stop.\n")
    if open_browser:
        import webbrowser
        webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("stopped.")


# Language names an embedder might send, mapped to the extension the backends key
# off. Bare extensions (".py") and dotted names pass through _ext() unchanged.
_LANG_ALIASES = {
    "python": ".py", "py": ".py",
    "javascript": ".js", "js": ".js",
    "typescript": ".ts", "ts": ".ts",
    "c": ".c", "cpp": ".cpp", "c++": ".cpp", "java": ".java", "asm": ".s",
}


def _ext(lang: str) -> str:
    lang = (lang or ".py").strip()
    if lang.startswith("."):
        return lang
    return _LANG_ALIASES.get(lang.lower(), "." + lang)


def serve_api(port: int = 8930, open_browser: bool = False):
    """On-demand trace API for embedding codeviz in a browser app.

        POST /trace  {"code": "...", "lang": ".py"|".js"|".ts"|"python"|...}
             -> 200 text/html : the self-contained viewer page for that snippet
             -> 400 application/json {"error": ...} : unsupported/unavailable language
                or bad request; 500 on an internal trace failure.
        GET  /health -> 200 {"ok": true, "service": "codeviz"}

    CORS is open (Access-Control-Allow-Origin: *) so a static browser app on any
    origin can call it. Binds to 127.0.0.1 only. It runs code locally, exactly like
    the CLI, so only point it at code you trust (a single-user local tool).
    """
    from .core import trace_code, UnsupportedLanguage
    from .render import render_html

    def _cors(h):
        h.send_header("Access-Control-Allow-Origin", "*")
        h.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        h.send_header("Access-Control-Allow-Headers", "Content-Type")

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _json(self, status, obj):
            body = json.dumps(obj).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            _cors(self)
            self.end_headers()
            self.wfile.write(body)

        def do_OPTIONS(self):
            self.send_response(204)
            _cors(self)
            self.end_headers()

        def do_GET(self):
            if self.path.startswith("/health"):
                self._json(200, {"ok": True, "service": "codeviz"})
            else:
                self._json(404, {"error": "not found"})

        def do_POST(self):
            if not self.path.startswith("/trace"):
                self._json(404, {"error": "not found"})
                return
            try:
                n = int(self.headers.get("Content-Length", 0) or 0)
                payload = json.loads(self.rfile.read(n) or b"{}")
            except Exception as e:
                self._json(400, {"error": f"bad request body: {e}"})
                return
            code = payload.get("code")
            if not isinstance(code, str) or not code.strip():
                self._json(400, {"error": "missing 'code'"})
                return
            try:
                data, backend = trace_code(code, _ext(payload.get("lang", ".py")))
            except (UnsupportedLanguage, RuntimeError) as e:
                self._json(400, {"error": str(e)})
                return
            except Exception as e:  # a genuine internal failure
                self._json(500, {"error": f"trace failed: {e}"})
                return
            html = render_html(data, "snippet", backend.name).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(html)))
            self.send_header("Cache-Control", "no-store")
            _cors(self)
            self.end_headers()
            self.wfile.write(html)

    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{port}/"
    print(f"\n  codeviz trace API on {url}")
    print('  POST /trace  {"code": "...", "lang": ".py|.js|.ts|.c|.java"}  -> viewer HTML')
    print("  GET  /health -> ok.   Ctrl+C to stop.\n")
    if open_browser:
        import webbrowser
        webbrowser.open(url + "health")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("stopped.")
