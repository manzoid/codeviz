"""Backend registry.

To add a language (e.g. Ruby, Dart): create ``<lang>_backend.py`` with a
``Backend`` subclass, import it here, and add an instance to ``_BACKENDS``.
Nothing else in the codebase needs to change.
"""
from __future__ import annotations

from .asm_backend import AsmBackend
from .base import Availability, Backend, Execution
from .c_cpp_backend import CBackend, CppBackend
from .java_backend import JavaBackend
from .javascript_backend import JavaScriptBackend, TypeScriptBackend
from .python_backend import PythonBackend

# Order matters only for display; lookup is by extension.
_BACKENDS: list[Backend] = [
    PythonBackend(),
    JavaScriptBackend(),
    TypeScriptBackend(),
    CBackend(),
    CppBackend(),
    JavaBackend(),
    AsmBackend(),
]

_BY_EXT: dict[str, Backend] = {
    ext: b for b in _BACKENDS for ext in b.extensions
}


def all_backends() -> list[Backend]:
    return list(_BACKENDS)


def for_extension(ext: str) -> Backend | None:
    return _BY_EXT.get(ext.lower())


def for_file(path: str) -> Backend | None:
    import os
    return for_extension(os.path.splitext(path)[1])


def supported_extensions() -> list[str]:
    return sorted(_BY_EXT)


__all__ = [
    "Availability",
    "Backend",
    "Execution",
    "all_backends",
    "for_extension",
    "for_file",
    "supported_extensions",
]
