#!/usr/bin/env python3
"""codeviz C/C++ tracer — driven by GDB's Python API.

Run as:  gdb -q -batch -x tracer.py --args <program>
with these env vars set:
    CODEVIZ_SRC      path to the ORIGINAL source file (used only for line counts)
    CODEVIZ_OUT      path to write the OPT trace JSON ({code, trace, lang})
    CODEVIZ_LANG     "c" or "cpp"
    CODEVIZ_STDOUT   path to a file the inferior's stdout is redirected to
    CODEVIZ_CODE     the original source string (so we don't depend on file IO)

This is our OWN modern tracer (replaces OPT's legacy Valgrind image).  It
single-steps the user program one source line at a time and, at each stop,
captures the call stack, each frame's locals/args, globals, and the heap of
objects reachable by following pointers.  Object identity is the runtime
*address*, so two pointers to the same object share one ["REF", id].

LIMITATION (teaching-grade v1): unlike OPT's patched Valgrind, this does NOT
detect reads of uninitialized memory or out-of-bounds access; it renders
whatever the debugger reports for the declared variables.
"""
import os
import sys
import json

import gdb  # provided by the gdb Python runtime

MAX_STEPS = 1000

SRC = os.environ["CODEVIZ_SRC"]
OUT = os.environ["CODEVIZ_OUT"]
LANG = os.environ.get("CODEVIZ_LANG", "c")
STDOUT_FILE = os.environ.get("CODEVIZ_STDOUT", "")
CODE = os.environ.get("CODEVIZ_CODE", "")

# basename of the source as gdb reports it (e.g. "prog.c")
SRC_BASE = os.path.basename(SRC)


# --------------------------------------------------------------------------
# stdout capture: the inferior writes to STDOUT_FILE (set up by the launcher
# via the program being started with its fd 1 redirected).  We read the whole
# file each step and report the accumulated prefix.
# --------------------------------------------------------------------------
def read_stdout():
    if not STDOUT_FILE:
        return ""
    try:
        with open(STDOUT_FILE, "r", errors="replace") as f:
            return f.read()
    except OSError:
        return ""


# --------------------------------------------------------------------------
# value encoding
# --------------------------------------------------------------------------
class Encoder:
    """Encodes gdb.Value trees into OPT encoded-values, building a heap keyed
    by address so aliasing renders correctly."""

    def __init__(self):
        self.heap = {}          # str(id) -> encoded-object
        self.seen = set()       # addresses already queued/encoded

    def _heap_id(self, addr):
        return str(int(addr))

    def encode(self, val):
        """Return an OPT encoded-value for a gdb.Value (scalars inline, objects
        as ["REF", id] with the object placed in self.heap)."""
        try:
            return self._encode(val)
        except gdb.error:
            return ["JS_TOKEN", "<unavailable>"]
        except Exception:
            return ["JS_TOKEN", "<error>"]

    def _strip(self, t):
        return t.strip_typedefs()

    def _encode(self, val):
        t = self._strip(val.type)
        code = t.code

        if code == gdb.TYPE_CODE_REF or getattr(gdb, "TYPE_CODE_RVALUE_REF", None) == code:
            # C++ reference: encode the referent (follow through).
            try:
                return self._encode(val.referenced_value())
            except gdb.error:
                return ["JS_TOKEN", "<ref>"]

        if code == gdb.TYPE_CODE_INT:
            tname = str(t)
            # render char types as their integer value's character where sane
            if t.name in ("char", "signed char", "unsigned char") or tname in (
                "char", "signed char", "unsigned char"):
                iv = int(val)
                ch = chr(iv & 0xFF) if 0 <= (iv & 0xFF) < 256 else ""
                if 32 <= (iv & 0xFF) < 127:
                    return "'%s' (%d)" % (ch, iv)
                return "%d" % iv
            if t.name == "bool" or tname == "bool":
                return bool(int(val))
            return int(val)

        if code == gdb.TYPE_CODE_BOOL:
            return bool(int(val))

        if code == gdb.TYPE_CODE_FLT:
            f = float(val)
            return f

        if code == gdb.TYPE_CODE_ENUM:
            return str(val)

        if code == gdb.TYPE_CODE_PTR:
            return self._encode_ptr(val, t)

        if code == gdb.TYPE_CODE_ARRAY:
            return self._encode_array_ref(val, t)

        if code in (gdb.TYPE_CODE_STRUCT, gdb.TYPE_CODE_UNION):
            return self._encode_struct_ref(val, t)

        # fallback: stringify
        try:
            return str(val)
        except gdb.error:
            return ["JS_TOKEN", "<unavailable>"]

    # -- pointers --------------------------------------------------------
    def _encode_ptr(self, val, t):
        target = self._strip(t.target())
        # char* -> render as a string value (not a heap object)
        if target.code == gdb.TYPE_CODE_INT and target.name in (
            "char", "signed char", "unsigned char"):
            addr = int(val)
            if addr == 0:
                return ["JS_TOKEN", "NULL"]
            try:
                s = val.string(errors="replace")
                return json_str_safe(s)
            except gdb.error:
                return ["JS_TOKEN", "0x%x" % addr]

        addr = int(val)
        if addr == 0:
            return ["JS_TOKEN", "NULL"]

        # function pointer
        if target.code == gdb.TYPE_CODE_FUNC:
            return ["JS_TOKEN", "0x%x" % addr]

        # Follow the pointer: the pointed-to object lives on the heap keyed by
        # its address, so two pointers to the same object share one REF.
        try:
            pointee = val.dereference()
        except gdb.error:
            return ["JS_TOKEN", "0x%x" % addr]
        return self._place(addr, pointee, self._strip(pointee.type))

    # -- arrays ----------------------------------------------------------
    def _encode_array_ref(self, val, t):
        # arrays are placed on the heap by their address so a pointer into the
        # same storage can alias them.
        try:
            addr = int(val.address)
        except (gdb.error, TypeError):
            # no address (e.g. a register-resident temp); inline it
            return self._encode_array_inline(val, t)
        return self._place(addr, val, t)

    def _encode_array_inline(self, val, t):
        out = ["LIST"]
        for elem in self._array_elems(val, t):
            out.append(self._encode(elem))
        return out

    def _array_elems(self, val, t):
        rng = t.range()
        lo, hi = rng[0], rng[1]
        if hi < lo:
            return
        n = hi - lo + 1
        if n > 1000:
            n = 1000
        for i in range(n):
            yield val[lo + i]

    # -- structs ---------------------------------------------------------
    def _encode_struct_ref(self, val, t):
        try:
            addr = int(val.address)
        except (gdb.error, TypeError):
            return self._encode_struct_inline(val, t)
        return self._place(addr, val, t)

    def _encode_struct_inline(self, val, t):
        name = struct_name(t)
        out = ["INSTANCE", name]
        for field in fields_of(t):
            try:
                fv = val[field.name]
            except (gdb.error, KeyError):
                continue
            out.append([field.name, self._encode(fv)])
        return out

    # -- heap placement --------------------------------------------------
    def _place(self, addr, val, t):
        hid = self._heap_id(addr)
        if hid not in self.seen:
            self.seen.add(hid)
            # reserve the slot, then fill (handles self-referential structs)
            self.heap[hid] = ["INSTANCE", "..."]
            self.heap[hid] = self._encode_object(val, t)
        return ["REF", int(addr)]

    def _encode_object(self, val, t):
        if t.code == gdb.TYPE_CODE_ARRAY:
            return self._encode_array_inline(val, t)
        if t.code in (gdb.TYPE_CODE_STRUCT, gdb.TYPE_CODE_UNION):
            return self._encode_struct_inline(val, t)
        # a pointer pointed at a scalar (e.g. int*): wrap the scalar so it is a
        # visible heap cell that other pointers can alias.
        return ["INSTANCE", scalar_type_name(t), ["*", self._encode(val)]]


def scalar_type_name(t):
    try:
        return str(t)
    except gdb.error:
        return "value"


def struct_name(t):
    n = t.name
    if n:
        return n
    tag = getattr(t, "tag", None)
    if tag:
        return tag
    return "struct"


def fields_of(t):
    out = []
    try:
        for f in t.fields():
            if f.name is None:
                continue
            if getattr(f, "is_base_class", False):
                continue
            if getattr(f, "artificial", False):
                continue
            out.append(f)
    except (gdb.error, TypeError):
        pass
    return out


def json_str_safe(s):
    # ensure the string is JSON-serializable; replace bad bytes
    if isinstance(s, bytes):
        return s.decode("utf-8", "replace")
    return s


# --------------------------------------------------------------------------
# frame -> variables
# --------------------------------------------------------------------------
def frame_func_name(frame):
    name = frame.name()
    if name is None:
        return "??"
    return name


def collect_frame_vars(frame, enc):
    """Return (encoded_locals dict, ordered_varnames list) for one frame.

    Walks the frame's block (and enclosing lexical blocks within the same
    function) gathering SYMBOL_LOC variables and arguments.
    """
    locals_map = {}
    order = []
    try:
        block = frame.block()
    except RuntimeError:
        return locals_map, order

    seen = set()
    # The line currently about to execute in this frame.  A variable declared
    # on line D is only initialized once line D has run, i.e. once cur > D.
    cur = current_line(frame)
    # walk from innermost block outward, but stop at the function block so we
    # don't pick up globals.
    b = block
    while b is not None:
        for sym in b:
            if not (sym.is_variable or sym.is_argument):
                continue
            nm = sym.name
            if nm in seen:
                continue
            # Hide a local before its declaration line has executed.  Otherwise
            # gdb happily reads the uninitialized stack bytes — and for a
            # pointer we would follow that garbage address and show junk like
            # "*: -456917232".  Arguments are valid from frame entry, so they
            # are never gated.
            if not sym.is_argument:
                try:
                    decl = sym.line
                except Exception:
                    decl = 0
                if decl and cur and decl >= cur:
                    continue
            try:
                val = sym.value(frame)
            except gdb.error:
                continue
            seen.add(nm)
            order.append(nm)
            locals_map[nm] = enc.encode(val)
        if b.function is not None:
            break
        b = b.superblock
    return locals_map, order


def collect_globals(enc):
    """Best-effort file-scope globals of the user's source.

    We enumerate symbols from the global block of the current frame and keep
    variables that live in the user's source file.
    """
    gmap = {}
    order = []
    try:
        frame = gdb.selected_frame()
        block = frame.block()
    except (gdb.error, RuntimeError):
        return gmap, order
    # climb to the global block
    gb = block
    while gb is not None and not gb.is_global:
        gb = gb.superblock
    if gb is None:
        return gmap, order
    for sym in gb:
        if not sym.is_variable:
            continue
        # only globals declared in the user's file
        fname = getattr(sym.symtab, "filename", "") if sym.symtab else ""
        if os.path.basename(fname) != SRC_BASE:
            continue
        nm = sym.name
        try:
            val = sym.value()
        except gdb.error:
            continue
        order.append(nm)
        gmap[nm] = enc.encode(val)
    return gmap, order


def user_frames():
    """Return frames (newest first) that belong to the user's source file,
    plus a flag list marking whether each is in the user file."""
    frames = []
    f = gdb.newest_frame()
    while f is not None:
        frames.append(f)
        f = f.older()
    return frames


def in_user_file(frame):
    try:
        sal = frame.find_sal()
    except gdb.error:
        return False
    if sal is None or sal.symtab is None:
        return False
    return os.path.basename(sal.symtab.filename) == SRC_BASE


def current_line(frame):
    try:
        sal = frame.find_sal()
    except gdb.error:
        return 0
    if sal is None:
        return 0
    return sal.line or 0


# --------------------------------------------------------------------------
# build one OPT step
# --------------------------------------------------------------------------
def build_step(event="step_line", exception_msg=None):
    enc = Encoder()
    all_frames = user_frames()
    # keep only frames within the user's source file (drop libc / crt0)
    uframes = [f for f in all_frames if in_user_file(f)]
    if not uframes:
        return None

    top = uframes[0]
    line = current_line(top)

    # The bottom-most user frame is main -> its locals are the "globals" frame
    # in the OPT layout (the persistent bottom panel).  True file-scope globals
    # are merged in too.
    bottom = uframes[-1]
    above = uframes[:-1]  # frames above main (callees), newest first

    # globals = file-scope globals + main's locals
    gmap, gorder = collect_globals(enc)
    try:
        gdb.selected_frame()  # ensure a frame is selected for value reads
    except gdb.error:
        pass
    main_locals, main_order = collect_frame_vars(bottom, enc)
    for nm in main_order:
        if nm not in gmap:
            gorder.append(nm)
        gmap[nm] = main_locals[nm]

    stack_to_render = []
    if not above:
        # we are at top level of main; render main itself as a frame too so the
        # user sees the active function, mirroring OPT's <module> + frame model.
        pass

    # Build a frame for every user frame ABOVE main (callees).  These are the
    # ones drawn in the stack panel.
    for i, fr in enumerate(above):
        fl, forder = collect_frame_vars(fr, enc)
        stack_to_render.append({
            "func_name": frame_func_name(fr),
            "is_highlighted": i == 0,
            "is_parent": False,
            "is_zombie": False,
            "parent_frame_id_list": [],
            "unique_hash": "%s_%d" % (frame_func_name(fr), len(above) - i),
            "frame_id": len(above) - i,
            "encoded_locals": fl,
            "ordered_varnames": forder,
        })

    func_name = frame_func_name(top) if above else "<module>"
    # when execution is inside main itself, OPT convention: func_name "<module>"
    if top is bottom:
        func_name = "<module>"

    step = {
        "event": event,
        "line": line,
        "func_name": func_name,
        "globals": gmap,
        "ordered_globals": gorder,
        "stack_to_render": stack_to_render,
        "heap": enc.heap,
        "stdout": read_stdout(),
    }
    if exception_msg is not None:
        step["event"] = "exception"
        step["exception_msg"] = exception_msg
    return step


# --------------------------------------------------------------------------
# driver
# --------------------------------------------------------------------------
def _same_state(a, b):
    """True if two steps represent the same observable program state (ignoring
    stdout, which may still be filling its buffer)."""
    return (
        a.get("event") == b.get("event")
        and a.get("line") == b.get("line")
        and a.get("func_name") == b.get("func_name")
        and a.get("globals") == b.get("globals")
        and a.get("ordered_globals") == b.get("ordered_globals")
        and a.get("stack_to_render") == b.get("stack_to_render")
        and a.get("heap") == b.get("heap")
    )


def write_out(trace):
    # reflect complete program output on the final step
    final_stdout = read_stdout()
    if trace:
        trace[-1]["stdout"] = final_stdout
    with open(OUT, "w") as f:
        json.dump({"code": CODE, "trace": trace, "lang": LANG}, f)


def main():
    trace = []

    gdb.execute("set pagination off")
    gdb.execute("set print pretty off")
    gdb.execute("set print repeats 0")
    gdb.execute("set print elements 1000")
    gdb.execute("set width 0")
    gdb.execute("set height 0")
    gdb.execute("set confirm off")

    # Stop at the user's main so we begin stepping in user code.
    try:
        gdb.execute("break main")
    except gdb.error:
        pass

    # Redirect the inferior's stdout to a file so we can read accumulated
    # program output at each step.  gdb's "run > FILE" sets up the redirection
    # for the child process only (line-buffering is forced unbuffered below via
    # the C runtime in the launched program when possible).
    run_cmd = "run"
    if STDOUT_FILE:
        run_cmd = "run > %s 2>&1" % STDOUT_FILE
    try:
        gdb.execute(run_cmd)
    except gdb.error as e:
        # program failed to start
        write_out([{
            "event": "exception",
            "line": 0,
            "func_name": "<module>",
            "globals": {}, "ordered_globals": [],
            "stack_to_render": [], "heap": {},
            "stdout": read_stdout(),
            "exception_msg": str(e).split("\n")[0],
        }])
        return

    steps = 0
    last_line = None
    last_depth = None
    while steps < MAX_STEPS:
        # record the current state
        try:
            inferior_alive = len(gdb.inferiors()[0].threads()) > 0
        except Exception:
            inferior_alive = False
        if not inferior_alive:
            break

        step = build_step()
        if step is not None:
            # Collapse runs of identical consecutive steps (same line, frames,
            # locals, globals and heap) that arise when `step` repeatedly lands
            # on the same user line while executing inlined library code (e.g. a
            # C++ std::vector constructor).  stdout is ignored for the compare so
            # output-only changes still register.
            if not trace or not _same_state(trace[-1], step):
                trace.append(step)
                steps += 1

        # advance one source line, stepping INTO calls
        try:
            gdb.execute("step")
        except gdb.error as e:
            msg = str(e).split("\n")[0]
            # a signal (e.g. SIGSEGV) surfaces here
            sig = current_signal()
            if sig:
                ex = build_step(event="exception", exception_msg=sig)
                if ex:
                    trace.append(ex)
            elif "not being run" not in msg.lower():
                pass
            break

        # detect inferior exit / signals after the step
        if not inferior_running():
            break
        sig = current_signal()
        if sig:
            ex = build_step(event="exception", exception_msg=sig)
            if ex:
                trace.append(ex)
            break

    write_out(trace)


def inferior_running():
    try:
        inf = gdb.inferiors()[0]
        return any(t.is_valid() for t in inf.threads())
    except Exception:
        return False


def current_signal():
    """If the inferior stopped on a fatal signal, return a one-line message."""
    try:
        # gdb sets $_siginfo and the stop reason; query convenience var
        out = gdb.execute("info program", to_string=True)
    except gdb.error:
        return None
    # Look for "It stopped with signal SIGSEGV" style text
    for line in out.splitlines():
        low = line.lower()
        if "signal" in low and ("sigsegv" in low or "sigabrt" in low or
                                "sigfpe" in low or "sigbus" in low or
                                "sigill" in low):
            return line.strip().rstrip(".")
    return None


try:
    main()
except Exception as e:  # pragma: no cover - last-resort safety net
    try:
        with open(OUT, "w") as f:
            json.dump({
                "code": CODE,
                "trace": [{
                    "event": "exception", "line": 0, "func_name": "<module>",
                    "globals": {}, "ordered_globals": [],
                    "stack_to_render": [], "heap": {},
                    "stdout": read_stdout(),
                    "exception_msg": ("tracer error: " + str(e)).split("\n")[0],
                }],
                "lang": LANG,
            }, f)
    except Exception:
        pass
finally:
    try:
        gdb.execute("quit")
    except Exception:
        pass
