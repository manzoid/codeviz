"""Backend interface.

A *backend* turns source code in one language into an Online Python Tutor
(OPT) execution trace: ``{"code": <str>, "trace": [<step>, ...]}``.  The
renderer is language-agnostic and consumes that format directly, so adding a
new language means implementing exactly one ``Backend`` subclass and
registering it (see ``codeviz/backends/__init__.py``).
"""
from __future__ import annotations

import abc
from typing import NamedTuple


class Availability(NamedTuple):
    ok: bool
    reason: str = ""  # human-readable explanation when ok is False


class Execution:
    """The (locked) set of execution models a backend may use.

    A language picks exactly ONE of these — there is no host auto-detection or
    fallback between models.  See ARCHITECTURE.md for the rationale.

    * ``LOCAL``      — runs on the host runtime.  Reserved for languages whose
      runtime is near-universal AND exposes a rock-solid tracing API
      (Python: ``sys.settrace`` via the vendored pg_logger; JavaScript: the
      V8 Inspector Protocol).
    * ``CONTAINER``  — runs inside a codeviz-provided, version-pinned Docker
      image (C, C++, Java today; future Ruby/Dart/Go).  Guarantees a known
      toolchain regardless of what the host has installed.
    * ``TRANSPILE``  — has no runtime of its own: compile with a pinned
      compiler and hand the output to an existing backend's target
      (TypeScript -> JavaScript).
    """

    LOCAL = "local"
    CONTAINER = "container"
    TRANSPILE = "transpile"

    #: all valid values, for validation / iteration
    ALL = ("local", "container", "transpile")


class Backend(abc.ABC):
    """Base class for a language backend.

    Subclasses set ``name`` and ``extensions`` and implement ``trace``.
    Override ``check`` if the backend needs an external toolchain (node,
    docker, a compiler, ...) so the CLI can fail with a helpful message
    instead of a stack trace.
    """

    #: short language id, e.g. "python", "javascript"
    name: str = ""
    #: file extensions this backend handles, lowercase incl. dot, e.g. (".py",)
    extensions: tuple[str, ...] = ()
    #: human label for UI / messages
    label: str = ""
    #: whether this backend shells out to Docker (affects setup + messaging)
    requires_docker: bool = False
    #: which execution model this backend uses (one of ``Execution.ALL``).
    #: LOCKED per-language — see ARCHITECTURE.md.  Default "local".
    execution: str = Execution.LOCAL

    def check(self) -> Availability:
        """Report whether this backend can run right now.

        Default: always available (pure-Python backends).  Override to probe
        for node/docker/compilers and return ``Availability(False, why)``.
        """
        return Availability(True)

    @abc.abstractmethod
    def trace(self, code: str, filename: str) -> dict:
        """Execute ``code`` and return an OPT trace dict.

        Must return ``{"code": code, "trace": [...]}``.  Each step follows the
        OPT schema (event, line, stack_to_render, heap, globals, stdout, ...).
        Exceptions in the *user's* code should be captured as a trailing
        ``event == "exception"`` step, not raised.
        """
        raise NotImplementedError
