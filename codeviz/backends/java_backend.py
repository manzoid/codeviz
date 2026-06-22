"""Java backend — our OWN JDI tracer in a slim, native-arch Docker image.

Unlike the C/C++ backend (which orchestrates OPT's prebuilt amd64 image), this
backend builds and runs ``codeviz/java:1`` — a self-contained image that bakes
in an original JDI-based tracer (``docker/java/Tracer.java``).  JDI is just the
standard JDK debugging API (``com.sun.jdi``); none of OPT's AGPL java_jail /
traceprinter is vendored, so this backend is MIT-clean.

The image is built NATIVELY for the host architecture (arm64 on Apple Silicon,
amd64 on x86_64) — ``eclipse-temurin:17-jdk`` ships native arm64, so there is no
emulation and builds are fast.  The backend builds the image on first use if it
is missing.

At trace time the user's Java source is handed to the container as a single
base64-encoded argument; the container discovers the public class name,
compiles with ``-g`` (so the tracer can read named locals), runs the tracer, and
prints the OPT trace JSON to stdout.
"""
from __future__ import annotations

import base64
import json
import os
import subprocess

from . import _docker
from .base import Availability, Backend, Execution

IMAGE = "codeviz/java:1"
GHCR = "ghcr.io/manzoid/codeviz-java:1"

# Build context ships inside the package (codeviz/docker/java).
_PKG = os.path.dirname(os.path.dirname(__file__))
_BUILD_CONTEXT = os.path.join(_PKG, "docker", "java")


class JavaBackend(Backend):
    name = "java"
    label = "Java"
    extensions = (".java",)
    requires_docker = True
    execution = Execution.CONTAINER

    def check(self) -> Availability:
        # Docker present + daemon up?  (Image is built on demand in trace().)
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
            return ("build", "first run fetches the image (or builds it); pre-fetch: codeviz setup java")
        return ("ready", "")

    def ensure_image(self) -> None:
        """Pull the prebuilt image from GHCR if possible, else build locally."""
        _docker.ensure_image(IMAGE, GHCR, _BUILD_CONTEXT, "Java")

    _ensure_image = ensure_image  # backward-compatible alias

    def trace(self, code: str, filename: str) -> dict:
        self._ensure_image()
        docker = _docker.docker_path()
        encoded = base64.b64encode(code.encode("utf-8")).decode("ascii")
        # Locked-down run; native platform (no --platform).  The tracer launches
        # a child JVM via JDI, so we do NOT drop all caps the way the valgrind
        # image does, but we still isolate the network.
        cmd = [
            docker, "run", "--rm",
            "--net=none",
            IMAGE, encoded,
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if proc.returncode != 0:
            raise RuntimeError(f"Java backend failed: {proc.stderr.strip()[-800:]}")
        data = json.loads(proc.stdout)
        if "trace" not in data:
            data = {"code": code, "trace": data}
        data.setdefault("code", code)
        return data
