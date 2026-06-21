"""Core glue: pick a backend for a file, trace it, render HTML."""
from __future__ import annotations

import os

from . import backends
from .render import render_html


class UnsupportedLanguage(Exception):
    pass


def trace_file(path: str):
    """Return (data, backend) for a source file."""
    backend = backends.for_file(path)
    if backend is None:
        exts = ", ".join(backends.supported_extensions())
        raise UnsupportedLanguage(
            f"no backend for '{os.path.basename(path)}'. Supported: {exts}"
        )
    avail = backend.check()
    if not avail.ok:
        raise RuntimeError(f"{backend.label} backend unavailable: {avail.reason}")
    with open(path, encoding="utf-8") as f:
        code = f.read()
    return backend.trace(code, path), backend


def trace_code(code: str, lang_ext: str):
    """Trace an inline snippet given a language extension like '.py'."""
    backend = backends.for_extension(lang_ext)
    if backend is None:
        raise UnsupportedLanguage(f"no backend for extension '{lang_ext}'")
    avail = backend.check()
    if not avail.ok:
        raise RuntimeError(f"{backend.label} backend unavailable: {avail.reason}")
    return backend.trace(code, "snippet" + lang_ext), backend


def build_page(path: str) -> tuple[str, int, str]:
    """Trace a file and return (html, n_steps, lang_name)."""
    data, backend = trace_file(path)
    html = render_html(data, os.path.basename(path), backend.name)
    return html, len(data.get("trace", [])), backend.name
