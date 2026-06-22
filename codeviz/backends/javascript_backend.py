"""JavaScript / TypeScript backends.

These shell out to a Node tracer (``tracers/js/trace.js``) that drives the V8
Inspector Protocol to single-step the user's code and emit an OPT trace.  This
is an original tracer for modern Node (18+); OPT's bundled ``jslogger.js`` only
runs on Node 6 and is not used.

TypeScript is compiled to JS first (via a local ``typescript`` if available),
then traced like JS.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys

from .base import Availability, Backend, Execution

_PKG = os.path.dirname(os.path.dirname(__file__))  # the codeviz package dir
_TRACER = os.path.join(_PKG, "tracers", "js", "trace.js")

# Node deps for the TypeScript path (typescript compiler + source-map) are NOT
# shipped in the wheel; they're fetched into a user cache on first TS use.
_TS_CACHE = os.path.join(os.path.expanduser("~"), ".cache", "codeviz", "js")


def _ts_node_modules() -> str:
    return os.path.join(_TS_CACHE, "node_modules")


def _ts_deps_present() -> bool:
    nm = _ts_node_modules()
    return os.path.isdir(os.path.join(nm, "typescript")) and os.path.isdir(os.path.join(nm, "source-map"))


def _ensure_ts_deps() -> str:
    """Fetch typescript + source-map into the user cache once; return node_modules."""
    if _ts_deps_present():
        return _ts_node_modules()
    if not shutil.which("npm"):
        raise RuntimeError("TypeScript needs npm (from Node) to fetch the TypeScript compiler.")
    os.makedirs(_TS_CACHE, exist_ok=True)
    pkg = os.path.join(_TS_CACHE, "package.json")
    if not os.path.exists(pkg):
        with open(pkg, "w") as f:
            f.write('{"name":"codeviz-js-deps","private":true}\n')
    print("codeviz: fetching the TypeScript compiler (one-time) …", file=sys.stderr, flush=True)
    proc = subprocess.run(["npm", "install", "--silent", "--no-audit", "--no-fund",
                           "typescript", "source-map"],
                          cwd=_TS_CACHE, stdout=sys.stderr, stderr=sys.stderr)
    if proc.returncode != 0 or not _ts_deps_present():
        raise RuntimeError("failed to fetch TypeScript deps (npm install failed)")
    return _ts_node_modules()


class JavaScriptBackend(Backend):
    name = "javascript"
    label = "JavaScript"
    extensions = (".js", ".mjs")
    execution = Execution.LOCAL

    def check(self) -> Availability:
        node = shutil.which("node")
        if not node:
            return Availability(False, "Node.js not found on PATH (need node 18+).")
        try:
            out = subprocess.run([node, "--version"], capture_output=True, text=True, timeout=10)
            major = int(out.stdout.strip().lstrip("v").split(".")[0])
            if major < 18:
                return Availability(False, f"Node {out.stdout.strip()} found; need 18+.")
        except Exception as e:  # pragma: no cover - defensive
            return Availability(False, f"could not determine node version: {e}")
        return Availability(True)

    def _run_tracer(self, code: str, filename: str) -> dict:
        proc = subprocess.run(
            ["node", _TRACER, "--name", os.path.basename(filename)],
            input=code, capture_output=True, text=True, timeout=60,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"js tracer failed: {proc.stderr.strip()}")
        return json.loads(proc.stdout)

    def trace(self, code: str, filename: str) -> dict:
        return self._run_tracer(code, filename)


class TypeScriptBackend(JavaScriptBackend):
    name = "typescript"
    label = "TypeScript"
    extensions = (".ts",)
    execution = Execution.TRANSPILE

    def check(self) -> Availability:
        base = super().check()
        if not base.ok:
            return base
        # tsc is resolved at trace time (local node_modules or global); just
        # confirm node here so we still give a useful message if it's missing.
        return base

    def status(self) -> tuple:
        base = super().status()  # node present + version ok?
        if base[0] != "ready":
            return base
        if _ts_deps_present():
            return ("ready", "")
        if not shutil.which("npm"):
            return ("unavailable", "TypeScript needs npm (Node) to fetch the compiler.")
        return ("build", "first run fetches the TypeScript compiler (one-time)")

    def trace(self, code: str, filename: str) -> dict:
        node_modules = _ensure_ts_deps()
        env = dict(os.environ)
        env["NODE_PATH"] = node_modules + (os.pathsep + env["NODE_PATH"] if env.get("NODE_PATH") else "")
        proc = subprocess.run(
            ["node", _TRACER, "--name", os.path.basename(filename), "--typescript"],
            input=code, capture_output=True, text=True, timeout=120, env=env,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"ts tracer failed: {proc.stderr.strip()}")
        return json.loads(proc.stdout)
