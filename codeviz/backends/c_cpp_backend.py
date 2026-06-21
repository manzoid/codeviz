"""C and C++ backends — run OPT's Valgrind-based tracer in a Docker container.

Image: ``pgbovine/opt-cpp-backend:v1`` (built via ``codeviz setup c``).
Container entrypoint, per OPT's Makefile:

    python /tmp/opt-cpp-backend/run_cpp_backend.py "<source>" <c|cpp> --prettydump

which prints an OPT trace as JSON to stdout.
"""
from __future__ import annotations

import json

from . import _docker
from .base import Availability, Backend

IMAGE = "pgbovine/opt-cpp-backend:v1"
_RUNNER = "/tmp/opt-cpp-backend/run_cpp_backend.py"


class _CFamilyBackend(Backend):
    requires_docker = True
    lang = "c"  # or "cpp"

    def check(self) -> Availability:
        return _docker.check_docker(IMAGE, f"codeviz setup {self.name}")

    def trace(self, code: str, filename: str) -> dict:
        proc = _docker.run_in_container(
            IMAGE, ["python", _RUNNER, code, self.lang], timeout=120,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"{self.label} backend failed: {proc.stderr.strip()[:800]}")
        data = json.loads(proc.stdout)
        # run_cpp_backend emits {"code":..., "trace":[...]}; normalize defensively.
        if "trace" not in data:
            data = {"code": code, "trace": data}
        data.setdefault("code", code)
        return data


class CBackend(_CFamilyBackend):
    name = "c"
    label = "C"
    extensions = (".c", ".h")
    lang = "c"


class CppBackend(_CFamilyBackend):
    name = "cpp"
    label = "C++"
    extensions = (".cpp", ".cc", ".cxx", ".hpp")
    lang = "cpp"
