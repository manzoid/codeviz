"""C and C++ backends — codeviz's OWN modern, containerized gdb tracer.

This replaces OPT's legacy Valgrind image (ubuntu 14.04 / x86_64) with a
self-contained, NATIVE image (``codeviz/c-cpp:1``, built FROM ubuntu:24.04)
that ships gcc/g++, gdb, and our tracer (``docker/c_cpp/tracer.py``).

The tracer compiles the user's source with ``-g -O0`` and drives gdb via its
Python API to single-step the program one source line at a time, capturing the
call stack, each frame's locals/args, file-scope globals, and the heap of
objects reachable by following pointers.  Object identity is the runtime
address, so two pointers to the same object share one ``["REF", id]``.

LIMITATION (teaching-grade v1): unlike OPT's patched Valgrind, this does not
detect reads of uninitialized memory or out-of-bounds accesses.

The image builds itself on first use (no separate ``codeviz setup`` step).  We
run the container natively for the host architecture (arm64 on Apple Silicon);
we deliberately do NOT pass ``--platform linux/amd64`` — modern Ubuntu has a
native arm64 base image, so emulation is unnecessary.
"""
from __future__ import annotations

import json
import os
import subprocess

from . import _docker
from .base import Availability, Backend, Execution

IMAGE = "codeviz/c-cpp:2"
GHCR = "ghcr.io/manzoid/codeviz-c-cpp:2"

_PKG = os.path.dirname(os.path.dirname(__file__))  # the codeviz package dir
_BUILD_CONTEXT = os.path.join(_PKG, "docker", "c_cpp")


def _ensure_image() -> None:
    """Pull the prebuilt image from GHCR if possible, else build locally."""
    _docker.ensure_image(IMAGE, GHCR, _BUILD_CONTEXT, "C/C++")


def _run_container(lang: str, code: str, timeout: int = 120) -> subprocess.CompletedProcess:
    """Run the tracer container natively, feeding the source on stdin.

    We invoke docker directly (rather than ``_docker.run_in_container``) so we
    can run on the host's native architecture instead of forcing amd64.
    """
    docker = _docker.docker_path()
    cmd = [
        docker, "run", "--rm", "-i",
        "--net=none", "--cap-drop", "all",
        # generous but bounded resources for a teaching snippet
        "--pids-limit", "256",
        "--memory", "512m",
        IMAGE, lang,
    ]
    return subprocess.run(cmd, input=code, capture_output=True, text=True, timeout=timeout)


class _CFamilyBackend(Backend):
    requires_docker = True
    execution = Execution.CONTAINER
    lang = "c"  # "c" or "cpp"

    def check(self) -> Availability:
        if not _docker.docker_path():
            return Availability(False, "Docker not found on PATH. Install Docker Desktop and start it.")
        info = subprocess.run([_docker.docker_path(), "info"], capture_output=True, text=True)
        if info.returncode != 0:
            return Availability(False, "Docker is installed but the daemon isn't running. Start Docker Desktop.")
        # The image is built lazily on first trace(); availability only needs a
        # working daemon.
        return Availability(True)

    def status(self) -> tuple:
        if not _docker.docker_path():
            return ("unavailable", "Docker not found on PATH. Install Docker Desktop.")
        info = subprocess.run([_docker.docker_path(), "info"], capture_output=True, text=True)
        if info.returncode != 0:
            return ("unavailable", "Docker daemon not running — start Docker Desktop.")
        if not _docker.image_exists(IMAGE):
            return ("build", f"first run fetches the image (or builds it); pre-fetch: codeviz setup {self.name}")
        return ("ready", "")

    def ensure_image(self) -> None:
        _ensure_image()

    def trace(self, code: str, filename: str) -> dict:
        _ensure_image()
        proc = _run_container(self.lang, code)
        if proc.returncode != 0:
            raise RuntimeError(
                "%s backend failed: %s" % (self.label, (proc.stderr or "").strip()[:800])
            )
        out = proc.stdout.strip()
        try:
            data = json.loads(out)
        except json.JSONDecodeError as e:
            raise RuntimeError(
                "%s backend produced invalid JSON: %s\n%s" % (self.label, e, out[:800])
            )
        if "trace" not in data:
            data = {"code": code, "trace": data}
        data.setdefault("code", code)
        data.setdefault("lang", self.lang)
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
