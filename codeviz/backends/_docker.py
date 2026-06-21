"""Shared helpers for Docker-based backends (C/C++, Java).

These backends run OPT's heavyweight tracers inside containers.  The images are
legacy (ubuntu 14.04, x86_64) and are built on demand via ``codeviz setup
<lang>`` rather than bundled — see ``docker/`` and the project README.
"""
from __future__ import annotations

import shutil
import subprocess

from .base import Availability


def docker_path() -> str | None:
    return shutil.which("docker")


def image_exists(tag: str) -> bool:
    docker = docker_path()
    if not docker:
        return False
    r = subprocess.run([docker, "image", "inspect", tag],
                       capture_output=True, text=True)
    return r.returncode == 0


def check_docker(image: str, setup_hint: str) -> Availability:
    if not docker_path():
        return Availability(False, "Docker not found on PATH. Install Docker Desktop and start it.")
    # Is the daemon up?
    info = subprocess.run([docker_path(), "info"], capture_output=True, text=True)
    if info.returncode != 0:
        return Availability(False, "Docker is installed but the daemon isn't running. Start Docker Desktop.")
    if not image_exists(image):
        return Availability(False, f"image '{image}' not built yet. Run: {setup_hint}")
    return Availability(True)


def run_in_container(image: str, argv: list[str], *, platform: str = "linux/amd64",
                     timeout: int = 90) -> subprocess.CompletedProcess:
    """Run argv inside a locked-down container, return the CompletedProcess."""
    cmd = [
        docker_path(), "run", "--rm",
        "--platform", platform,
        "--net=none", "--cap-drop", "all",
        image, *argv,
    ]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
