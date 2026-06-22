# codeviz x86-64 assembly tracer — runs inside gdb (--batch-silent).
#
# Single-steps the inferior one machine instruction at a time and records, per
# step: all general-purpose registers, rip/rsp, decoded RFLAGS, a window of the
# stack, the disassembled current instruction, the source line, and program
# output so far.  Writes an OPT-style trace to /work/trace.json.
#
# It must NOT print to stdout (gdb's fd 1 is the inferior's stdout, captured to
# /work/prog.out); all output goes to the JSON file.
import json
import os
import struct

import gdb

REGS = ["rax", "rbx", "rcx", "rdx", "rsi", "rdi", "rbp", "rsp",
        "r8", "r9", "r10", "r11", "r12", "r13", "r14", "r15", "rip"]
FLAG_BITS = {"CF": 0, "PF": 2, "AF": 4, "ZF": 6, "SF": 7, "DF": 10, "OF": 11}
MAX_STEPS = 2000
STACK_WORDS = 12

exited = {"done": False, "code": None}
signalled = {"sig": None}


def _on_exit(ev):
    exited["done"] = True
    exited["code"] = getattr(ev, "exit_code", None)


def _on_stop(ev):
    # A SignalEvent (e.g. SIGSEGV) means the program faulted.
    if isinstance(ev, gdb.SignalEvent):
        signalled["sig"] = ev.stop_signal


gdb.events.exited.connect(_on_exit)
gdb.events.stop.connect(_on_stop)


def u64(v):
    return int(v) & 0xFFFFFFFFFFFFFFFF


def decode_flags(val):
    return {name: (val >> bit) & 1 for name, bit in FLAG_BITS.items()}


def read_prog_out():
    try:
        with open("/work/prog.out", "r", errors="replace") as f:
            return f.read()
    except OSError:
        return ""


def capture():
    frame = gdb.selected_frame()
    regs = {}
    for r in REGS:
        try:
            regs[r] = u64(frame.read_register(r))
        except Exception:
            pass
    pc = regs.get("rip", 0)

    try:
        flags = decode_flags(int(frame.read_register("eflags")))
    except Exception:
        flags = {}

    arch = frame.architecture()
    try:
        insn = arch.disassemble(pc)[0]["asm"]
    except Exception:
        insn = ""

    try:
        sal = frame.find_sal()
        line = sal.line if (sal and sal.line) else 0
    except Exception:
        line = 0

    stack = []
    rsp = regs.get("rsp", 0)
    inf = gdb.selected_inferior()
    for i in range(STACK_WORDS):
        a = rsp + i * 8
        try:
            raw = bytes(inf.read_memory(a, 8))
            stack.append({"addr": hex(a), "value": hex(struct.unpack("<Q", raw)[0])})
        except Exception:
            break

    return {
        "event": "step_line",
        "line": line,
        "pc": hex(pc),
        "instruction": insn,
        "registers": {k: hex(v) for k, v in regs.items()},
        "flags": flags,
        "stack": stack,
        "stdout": read_prog_out(),
    }


def main():
    gdb.execute("set pagination off")
    gdb.execute("set confirm off")
    # The x86-64 program runs under qemu-user; connect to qemu's gdb stub.
    # qemu stops the program at its entry point until we connect, so we are
    # positioned at the first instruction with no extra command needed.
    port = os.environ.get("CODEVIZ_GDB_PORT", "1234")
    gdb.execute("set architecture i386:x86-64")
    last_err = None
    for _ in range(50):  # stub may need a moment to start listening
        try:
            gdb.execute("target remote localhost:%s" % port)
            last_err = None
            break
        except gdb.error as e:
            last_err = e
            gdb.execute("shell sleep 0.1")
    if last_err is not None:
        raise last_err

    trace = []
    while not exited["done"] and len(trace) < MAX_STEPS:
        try:
            step = capture()
        except Exception:
            break
        if signalled["sig"]:
            step["event"] = "exception"
            step["exception_msg"] = "Program received signal %s" % signalled["sig"]
            trace.append(step)
            break
        trace.append(step)
        try:
            gdb.execute("stepi")
        except gdb.error:
            break

    final_out = read_prog_out()
    if trace:
        trace[-1]["stdout"] = final_out
        if exited["done"] and trace[-1].get("event") == "step_line":
            trace[-1]["event"] = "return"

    try:
        code = open("/work/prog.s").read()
    except OSError:
        code = ""

    with open("/work/trace.json", "w") as f:
        json.dump({"code": code, "lang": "asm", "trace": trace}, f)


main()
