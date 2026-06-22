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

from . import _docker
from .base import Availability, Backend, Execution

IMAGE = "codeviz/asm-x86:1"
GHCR = "ghcr.io/manzoid/codeviz-asm-x86:1"

_PKG = os.path.dirname(os.path.dirname(__file__))  # the codeviz package dir
_BUILD_CONTEXT = os.path.join(_PKG, "docker", "asm")


def _ensure_image() -> None:
    """Pull the prebuilt image from GHCR if possible, else build locally."""
    _docker.ensure_image(IMAGE, GHCR, _BUILD_CONTEXT, "x86-64 asm")


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
            return ("build", "first run fetches the image (or builds it); pre-fetch: codeviz setup asm")
        return ("ready", "")

    def ensure_image(self) -> None:
        _ensure_image()

    def trace(self, code: str, filename: str) -> dict:
        _ensure_image()
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
