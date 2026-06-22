#!/usr/bin/env bash
# codeviz Java backend container entrypoint.
#
# Receives the user's Java source as a single base64-encoded argument (avoids
# all shell-quoting hazards), discovers the public class name, compiles the
# source with debug info, and runs the JDI Tracer, which prints the OPT trace
# JSON to stdout.
#
#   entrypoint.sh <base64-source>
#
# All diagnostics go to stderr so stdout carries only the trace JSON.
set -euo pipefail

if [ "$#" -lt 1 ]; then
  echo "usage: entrypoint.sh <base64-source>" >&2
  exit 2
fi

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

# Decode the source.
printf '%s' "$1" | base64 -d > "$WORK/source.java"

# Determine the entry class name.  Prefer the public top-level class; fall back
# to the first class declaration if none is public.
CLASS="$(grep -oE 'public[[:space:]]+(final[[:space:]]+|abstract[[:space:]]+)?class[[:space:]]+[A-Za-z_][A-Za-z0-9_]*' "$WORK/source.java" \
          | head -n1 | awk '{print $NF}')"
if [ -z "${CLASS:-}" ]; then
  CLASS="$(grep -oE 'class[[:space:]]+[A-Za-z_][A-Za-z0-9_]*' "$WORK/source.java" \
            | head -n1 | awk '{print $NF}')"
fi
if [ -z "${CLASS:-}" ]; then
  echo "could not find a class declaration in the source" >&2
  exit 1
fi

# Java requires the file name to match the public class name.
SRC="$WORK/$CLASS.java"
mv "$WORK/source.java" "$SRC"

mkdir -p "$WORK/classes"
# -g: emit the local variable table so the tracer can read named locals.
if ! javac -g -d "$WORK/classes" "$SRC" 2> "$WORK/javac.err"; then
  # Surface a compile error as a single-step exception trace so the UI shows it.
  ERR="$(head -n1 "$WORK/javac.err")"
  python3 - "$SRC" "$ERR" <<'PY'
import json, sys
src = open(sys.argv[1], encoding="utf-8").read()
msg = sys.argv[2] if len(sys.argv) > 2 else "compile error"
step = {
    "event": "exception", "line": 1, "func_name": "<module>",
    "globals": {}, "ordered_globals": [], "stack_to_render": [],
    "heap": {}, "stdout": "", "exception_msg": msg,
}
print(json.dumps({"code": src, "trace": [step], "lang": "java"}))
PY
  exit 0
fi

exec java -cp "/opt/codeviz:$WORK/classes" Tracer "$CLASS" "$WORK/classes" "$SRC"
