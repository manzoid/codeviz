"""Live-reload server: re-trace a file on every save; the page auto-reloads."""
from __future__ import annotations

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
