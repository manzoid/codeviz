"""Java backend — runs David Pritchard's java_jail traceprinter in Docker.

Image: ``pgbovine/cokapi-java:v1`` (built via ``codeviz setup java``).
Per OPT's cokapi, the container is invoked as:

    /tmp/run-java-backend.sh '<inputJSON>'

where inputJSON carries the user's source; the trace is printed as JSON to
stdout.

NOTE: java_jail / traceprinter is AGPL-licensed.  codeviz only *orchestrates*
the prebuilt image (no AGPL code is vendored into this repo), but anyone
redistributing the image should preserve that license.  See docker/README.
"""
from __future__ import annotations

import json

from . import _docker
from .base import Availability, Backend

IMAGE = "pgbovine/cokapi-java:v1"
_RUNNER = "/tmp/run-java-backend.sh"


class JavaBackend(Backend):
    name = "java"
    label = "Java"
    extensions = (".java",)
    requires_docker = True

    def check(self) -> Availability:
        return _docker.check_docker(IMAGE, "codeviz setup java")

    def trace(self, code: str, filename: str) -> dict:
        input_obj = json.dumps({
            "usercode": code,
            "options": {"cumulative_mode": False, "heap_primitives": False},
            "args": [],
            "stdin": "",
        })
        proc = _docker.run_in_container(
            IMAGE, [_RUNNER, input_obj], timeout=120,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"Java backend failed: {proc.stderr.strip()[:800]}")
        data = json.loads(proc.stdout)
        if "trace" not in data:
            data = {"code": code, "trace": data}
        data.setdefault("code", code)
        return data
