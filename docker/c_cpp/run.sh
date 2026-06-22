#!/bin/sh
# codeviz C/C++ container entrypoint.
#
# Usage:  run.sh <c|cpp>      (user source on stdin)
# Emits the OPT trace JSON ({code, trace, lang}) on stdout.
set -eu

LANG_ARG="${1:-c}"

WORK="$(mktemp -d)"
if [ "$LANG_ARG" = "cpp" ]; then
    SRC="$WORK/prog.cpp"
    CC="g++"
    STD="-std=c++17"
else
    SRC="$WORK/prog.c"
    CC="gcc"
    STD="-std=c11"
fi

# Read the user's source from stdin.
cat > "$SRC"

BIN="$WORK/prog"
STDOUT_FILE="$WORK/stdout.txt"
OUT="$WORK/trace.json"
: > "$STDOUT_FILE"

# Compile with debug info and no optimization so locals/lines map cleanly.
# -fno-omit-frame-pointer keeps the stack walkable.
if ! COMPILE_ERR="$($CC $STD -g -O0 -fno-omit-frame-pointer -o "$BIN" "$SRC" 2>&1)"; then
    # Emit a trace with a single exception step describing the compile error.
    CODE="$(cat "$SRC")" \
    ERR="$COMPILE_ERR" \
    LANG_ARG="$LANG_ARG" \
    python3 - <<'PY'
import json, os
err = os.environ.get("ERR", "compilation failed").splitlines()
first = err[0] if err else "compilation failed"
print(json.dumps({
    "code": os.environ.get("CODE", ""),
    "trace": [{
        "event": "exception", "line": 0, "func_name": "<module>",
        "globals": {}, "ordered_globals": [],
        "stack_to_render": [], "heap": {}, "stdout": "",
        "exception_msg": first,
    }],
    "lang": os.environ.get("LANG_ARG", "c"),
}))
PY
    exit 0
fi

# Drive gdb with our tracer.  Pass everything via env so we don't fight quoting.
CODEVIZ_SRC="$SRC" \
CODEVIZ_OUT="$OUT" \
CODEVIZ_LANG="$LANG_ARG" \
CODEVIZ_STDOUT="$STDOUT_FILE" \
CODEVIZ_CODE="$(cat "$SRC")" \
gdb -q -nx -batch -x /opt/codeviz/tracer.py --args "$BIN" >/dev/null 2>&1 || true

if [ -f "$OUT" ]; then
    cat "$OUT"
else
    # gdb produced nothing usable; fall back to a minimal error trace.
    CODE="$(cat "$SRC")" LANG_ARG="$LANG_ARG" python3 - <<'PY'
import json, os
print(json.dumps({
    "code": os.environ.get("CODE", ""),
    "trace": [{
        "event": "exception", "line": 0, "func_name": "<module>",
        "globals": {}, "ordered_globals": [],
        "stack_to_render": [], "heap": {}, "stdout": "",
        "exception_msg": "tracer produced no output",
    }],
    "lang": os.environ.get("LANG_ARG", "c"),
}))
PY
fi
