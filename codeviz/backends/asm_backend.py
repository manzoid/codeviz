"""x86-64 assembly backend — codeviz's own GDB/qemu-user tracer in a container.

The image (``codeviz/asm-x86:1``) is built NATIVELY for the host arch; inside
it we cross-assemble the user's x86-64 source and run *just that program* under
qemu-user, whose gdb stub drives instruction stepping (so no ptrace, which is
unavailable when a whole container is emulated).  See docker/asm/.

The tracer emits an assembly-shaped OPT trace (``lang == "asm"``): each step
carries registers, decoded flags, a stack window, and the current instruction,
which the renderer shows in a dedicated registers/flags/stack view.

Unlike the C/C++ and Java backends, the container is run WITHOUT ``--net=none``:
the qemu gdb stub talks to gdb over loopback TCP inside the container's network
namespace.  It still runs ``--rm`` with dropped capabilities and memory/pid
limits, and publishes no ports, so it stays isolated from the host.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

from . import _docker
from .base import Availability, Backend, Execution

IMAGE = "codeviz/asm-x86:1"

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
_BUILD_CONTEXT = os.path.join(_ROOT, "docker", "asm")


def _build_image() -> None:
    docker = _docker.docker_path()
    if not docker:
        raise RuntimeError("Docker not found on PATH.")
    print(f"codeviz: building {IMAGE} (one-time, ~2 min) — first use of assembly ...",
          file=sys.stderr, flush=True)
    proc = subprocess.run([docker, "build", "-t", IMAGE, _BUILD_CONTEXT],
                          stdout=sys.stderr, timeout=1200)
    if proc.returncode != 0:
        raise RuntimeError(f"failed to build {IMAGE} (see docker output above)")
    print(f"codeviz: built {IMAGE}.", file=sys.stderr, flush=True)


class AsmBackend(Backend):
    name = "asm"
    label = "x86-64 asm"
    extensions = (".s", ".asm")
    requires_docker = True
    execution = Execution.CONTAINER

    def check(self) -> Availability:
        if not _docker.docker_path():
            return Availability(False, "Docker not found on PATH. Install Docker Desktop and start it.")
        info = subprocess.run([_docker.docker_path(), "info"], capture_output=True, text=True)
        if info.returncode != 0:
            return Availability(False, "Docker is installed but the daemon isn't running. Start Docker Desktop.")
        return Availability(True)

    def status(self) -> tuple:
        if not _docker.docker_path():
            return ("unavailable", "Docker not found on PATH. Install Docker Desktop.")
        info = subprocess.run([_docker.docker_path(), "info"], capture_output=True, text=True)
        if info.returncode != 0:
            return ("unavailable", "Docker daemon not running — start Docker Desktop.")
        if not _docker.image_exists(IMAGE):
            return ("build", f"first run builds {IMAGE} (~2 min); pre-build: codeviz setup asm")
        return ("ready", "")

    def trace(self, code: str, filename: str) -> dict:
        if not _docker.image_exists(IMAGE):
            _build_image()
        docker = _docker.docker_path()
        # No --net=none: the qemu gdb stub uses loopback TCP inside the
        # container's own netns. Still isolated (own netns, no published ports).
        cmd = [
            docker, "run", "--rm", "-i",
            "--cap-drop", "all",
            "--pids-limit", "256",
            "--memory", "512m",
            IMAGE,
        ]
        proc = subprocess.run(cmd, input=code, capture_output=True, text=True, timeout=120)
        if proc.returncode != 0:
            raise RuntimeError(f"assembly backend failed: {(proc.stderr or '').strip()[:800]}")
        out = proc.stdout.strip()
        try:
            data = json.loads(out)
        except json.JSONDecodeError as e:
            raise RuntimeError(f"assembly backend produced invalid JSON: {e}\n{out[:800]}")
        data.setdefault("code", code)
        data.setdefault("lang", "asm")
        return data
