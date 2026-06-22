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

from .base import Availability, Backend, Execution

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
_TRACER = os.path.join(_ROOT, "tracers", "js", "trace.js")


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

    def trace(self, code: str, filename: str) -> dict:
        # Compile TS -> JS via the bundled tracer's TypeScript support.
        proc = subprocess.run(
            ["node", _TRACER, "--name", os.path.basename(filename), "--typescript"],
            input=code, capture_output=True, text=True, timeout=90,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"ts tracer failed: {proc.stderr.strip()}")
        return json.loads(proc.stdout)
