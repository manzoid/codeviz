#!/bin/bash
# codeviz x86-64 assembly entrypoint.
#
# Reads GNU-assembler (AT&T) source on stdin, cross-assembles + links a
# freestanding static x86-64 binary (entry `_start`, no libc), runs it under
# qemu-user with its gdb stub, and traces it one instruction at a time via
# gdb-multiarch. The OPT-style trace JSON goes to /work/trace.json -> stdout.
set -u
mkdir -p /work
cat > /work/prog.s

AS=x86_64-linux-gnu-as
LD=x86_64-linux-gnu-ld
PORT=1234

emit_error() {
    python3 - "$1" <<'PY'
import json, sys
raw = sys.argv[1].strip().splitlines()
msg = raw[0] if raw else "assemble/link failed"
try:
    code = open("/work/prog.s").read()
except Exception:
    code = ""
print(json.dumps({"code": code, "lang": "asm", "trace": [{
    "event": "exception", "line": 1, "pc": "", "instruction": "",
    "registers": {}, "flags": {}, "stack": [], "stdout": "",
    "exception_msg": msg}]}))
PY
}

# -g: emit DWARF line info so the tracer can map pc -> source line.
if ! $AS --64 -g -o /work/prog.o /work/prog.s 2>/work/asm.err; then
    emit_error "$(cat /work/asm.err)"; exit 0
fi
if ! $LD -o /work/prog /work/prog.o 2>/work/link.err; then
    emit_error "$(cat /work/link.err)"; exit 0
fi

# Launch under qemu-user; -g makes qemu wait for gdb on PORT before running.
# Program stdout -> /work/prog.out. qemu's gdb stub does the stepping (no ptrace).
qemu-x86_64 -g "$PORT" /work/prog >/work/prog.out 2>/work/qemu.err &
QPID=$!
sleep 0.3   # let the stub start listening before gdb connects

CODEVIZ_GDB_PORT="$PORT" gdb-multiarch --batch-silent -nx -x /asm/tracer.py /work/prog 2>/work/gdb.err || true
kill "$QPID" 2>/dev/null || true

if [ -f /work/trace.json ]; then
    cat /work/trace.json
else
    emit_error "tracer failed: $(cat /work/gdb.err 2>/dev/null; cat /work/qemu.err 2>/dev/null)"
fi
