"""Shared helpers for the Docker-based backends (C/C++, Java, asm).

These backends run codeviz's own tracers inside containers.  Images are
obtained pull-first (from GHCR) with a local-build fallback — see
``ensure_image`` and ``docker/``.
"""
from __future__ import annotations

import shutil
import subprocess
import sys

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


def ensure_image(local_tag: str, ghcr_ref: str, context: str, label: str) -> None:
    """Make ``local_tag`` available, preferring a fast pull over a local build.

    1. If ``local_tag`` already exists locally, do nothing.
    2. Else try ``docker pull ghcr_ref`` (a prebuilt, multi-arch image) and
       retag it to ``local_tag`` — fast and reproducible for end users.
    3. Else build locally from ``context`` (works offline / for contributors
       who edited the Dockerfile).

    Progress streams to stderr so neither step ever looks like a hang.
    """
    docker = docker_path()
    if not docker:
        raise RuntimeError("Docker not found on PATH.")
    if image_exists(local_tag):
        return

    if ghcr_ref:
        print(f"codeviz: fetching {label} image  ({ghcr_ref}) …", file=sys.stderr, flush=True)
        pull = subprocess.run([docker, "pull", ghcr_ref], stdout=sys.stderr, stderr=sys.stderr)
        if pull.returncode == 0:
            subprocess.run([docker, "tag", ghcr_ref, local_tag],
                           capture_output=True, text=True)
            print(f"codeviz: pulled {label} image.", file=sys.stderr, flush=True)
            return
        print(f"codeviz: pull unavailable — building {label} locally (one-time, ~2 min) …",
              file=sys.stderr, flush=True)
    else:
        print(f"codeviz: building {label} image locally (one-time, ~2 min) …",
              file=sys.stderr, flush=True)

    build = subprocess.run([docker, "build", "-t", local_tag, context], stdout=sys.stderr)
    if build.returncode != 0:
        raise RuntimeError(f"failed to obtain the {label} image (pull and local build both failed)")
    print(f"codeviz: built {label} image.", file=sys.stderr, flush=True)


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
