"""Python backend — wraps the vendored Online Python Tutor tracer (pg_logger)."""
from __future__ import annotations

import contextlib
import io
import os
import sys

from .base import Backend, Execution

# vendor/ ships inside the codeviz package (codeviz/vendor).
_VENDOR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "vendor")


class PythonBackend(Backend):
    name = "python"
    label = "Python"
    extensions = (".py",)
    execution = Execution.LOCAL

    def trace(self, code: str, filename: str) -> dict:
        if _VENDOR not in sys.path:
            sys.path.insert(0, _VENDOR)
        import pg_logger  # vendored; imported lazily so other backends don't pay for it

        captured: dict = {}

        def finalizer(input_code, output_trace):
            captured["data"] = {"code": input_code, "trace": output_trace}
            return ""

        # pg_logger prints an internal traceback to stderr when the *user's*
        # code raises; that exception is already captured in the trace.
        with contextlib.redirect_stderr(io.StringIO()):
            pg_logger.exec_script_str_local(
                code,
                None,    # raw_input_lst_json
                False,   # cumulative_mode
                False,   # heap_primitives
                finalizer,
            )
        return captured["data"]
