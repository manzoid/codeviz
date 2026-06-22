# codeviz architecture (LOCKED)

This document records the **locked execution-model architecture** of codeviz.
The categories below are intentional and stable; new languages slot into one of
them. Do not add host auto-detection or per-language fallbacks between models.

## Core principle

> A language runs on the **host** ONLY if its runtime is **near-universal** AND
> exposes a **rock-solid tracing API**. Everything else runs in a
> codeviz-provided, **version-pinned Docker image**. Languages with no runtime
> of their own are **transpiled** to a target an existing backend already
> handles.

Two languages clear the host bar today:

- **Python** — `sys.settrace` via the vendored Online Python Tutor `pg_logger`.
- **JavaScript** — the V8 Inspector Protocol (driven by `tracers/js/trace.js`).

Both APIs are stable, present everywhere the runtime is, and give us complete
per-step state (frames, heap, stable object identity).

## Rationale

codeviz is meant to produce identical, correct visualizations for **other
people on machines we cannot see**. That goal drives every choice here:

- **Reliability + reproducibility.** A pinned container yields the same trace on
  every host regardless of which compiler/JDK/interpreter versions happen to be
  installed. We never depend on "whatever the host has."
- **One execution path per language.** Each backend declares exactly one
  execution model (`Backend.execution`). There is **no host auto-detection** and
  no silent fallback from container to host (or vice versa). This keeps behavior
  predictable and bug reports reproducible.
- **No drive-by toolchain assumptions.** Host runtimes are admitted only when
  they are effectively guaranteed to exist and behave identically (Python 3, a
  modern Node). Anything with version- or platform-sensitive tracing goes in a
  container.

## The three categories

The `Backend.execution` attribute (see `codeviz/backends/base.py`, class
`Execution`) is one of:

### 1. Blessed host runtimes — `Execution.LOCAL`

Run directly on the host. Reserved for near-universal runtimes with a
rock-solid tracing API.

| Language | Tracing mechanism | Backend |
|----------|-------------------|---------|
| Python | `sys.settrace` (vendored OPT `pg_logger`) | `PythonBackend` |
| JavaScript | V8 Inspector Protocol (`tracers/js/trace.js`, Node 18+) | `JavaScriptBackend` |

### 2. Containerized runtimes — `Execution.CONTAINER`

Run inside a codeviz-provided, version-pinned Docker image. The host needs only
Docker; the toolchain lives in the image. This is the default home for any
language whose tracing is version- or platform-sensitive.

All images below are **our own**, built from contexts in `docker/` (MIT-clean;
no OPT legacy Valgrind / java_jail is vendored or shipped).

| Language | Image | Mechanism | Backend |
|----------|-------|-----------|---------|
| C | `codeviz/c-cpp:1` | our GDB Python-API tracer (native arm64) | `CBackend` |
| C++ | `codeviz/c-cpp:1` | our GDB Python-API tracer (native arm64) | `CppBackend` |
| Java | `codeviz/java:1` | our `com.sun.jdi` tracer (native arm64) | `JavaBackend` |
| x86-64 asm | `codeviz/asm-x86:1` | cross-assemble + qemu-user gdb stub + `gdb-multiarch` | `AsmBackend` |
| _future:_ Ruby | (pinned image) | `TracePoint` in-container | — |
| _future:_ Dart | (pinned image) | VM Service in-container | — |
| _future:_ Go | (pinned image) | (TBD in-container) | — |

Assembly is the one place x86-64 is emulated (the subject matter requires it),
but only the *traced program* runs under qemu-user — the container itself is
native, and qemu's gdb stub provides stepping without ptrace.

**Release-time TODO** (not needed for local/solo use): publish multi-arch images
to GHCR and switch container backends to *pull-first, build-fallback*, and pin
apt package versions, so other users get identical, fast, reliable images
without a local build.

### 3. Transpiled-to-a-target — `Execution.TRANSPILE`

The language has **no runtime of its own**. Compile it with a **pinned
compiler**, then hand the output to an existing backend's target.

| Language | Pinned compiler | Target backend | Backend |
|----------|-----------------|----------------|---------|
| TypeScript | `typescript` (`tsc`) | JavaScript (V8 Inspector) | `TypeScriptBackend` |

A transpile backend is responsible for mapping trace line numbers back to the
**original** source shown in the UI (see the trace contract: `line` is always
1-based in the original source).

## How to add a language later

Adding a language is **one backend file + one pinned image (or a transpile
shim)**, registered in `codeviz/backends/__init__.py`. Nothing else in the
codebase changes — the renderer and CLI are language-agnostic.

1. **Pick the category** by the core principle above:
   - Near-universal runtime + rock-solid tracing API → `LOCAL` (rare; the bar is
     high — today only Python and JavaScript qualify).
   - Has a real runtime but version/platform-sensitive tracing → `CONTAINER`.
   - No runtime of its own → `TRANSPILE` to an existing target.
2. **Create `codeviz/backends/<lang>_backend.py`** with a `Backend` subclass:
   set `name`, `label`, `extensions`, `execution`, and (for containers)
   `requires_docker = True`; implement `trace()` and override `check()` to probe
   for the required toolchain/image.
3. **For `CONTAINER`:** build/pin a Docker image (`docker/`) and have `check()`
   verify it via `_docker.check_docker(IMAGE, "codeviz setup <lang>")`.
4. **For `TRANSPILE`:** invoke a pinned compiler, then delegate to the target
   backend; preserve original-source line numbers.
5. **Register** the backend instance in `codeviz/backends/__init__.py`
   (`_BACKENDS`).

### Worked examples

- **Ruby → `CONTAINER`.** Ruby's `TracePoint` API is excellent, but Ruby is not
  near-universal across hosts and versions vary. Ship a pinned image that runs a
  `TracePoint`-based tracer and emits the trace contract JSON.
- **Dart → `CONTAINER`.** Use the Dart VM Service protocol inside a pinned image
  to single-step and read frames/heap, then emit the trace contract JSON.

## Appendix: codeviz trace contract

This is the format every backend must emit (verbatim).

```
codeviz trace contract — every backend returns: {"code": <source str>, "trace": [<step>...], "lang": <name>}

Each <step> is an object:
  event: "step_line" | "call" | "return" | "exception"
  line: 1-based line number in the ORIGINAL source (the code shown in the UI)
  func_name: current function name ("<module>" at top level)
  stack_to_render: array (top frame first) of:
      { func_name, is_highlighted(bool, true for top), is_parent:false, is_zombie:false,
        parent_frame_id_list:[], unique_hash:str, frame_id:int,
        encoded_locals: { name: <encoded-value> }, ordered_varnames: [name,...] }
  globals: { name: <encoded-value> }       // the bottom/global frame's vars
  ordered_globals: [name, ...]
  heap: { "<id>": <encoded-object> }        // referenced objects, stable ids
  stdout: string (accumulated program output up to this step)
  exception_msg: string (only on event "exception"; FIRST LINE only, no stack dump)

<encoded-value>:
  primitives inline: numbers, true/false, strings (as JSON strings)
  reference to a heap object: ["REF", <id>]
  language tokens that aren't JSON primitives: ["JS_TOKEN", "<text>"] (e.g. "null","undefined","nil") —
    the renderer prints token text verbatim; reuse "JS_TOKEN" for any language's null/nil/None-like tokens.

<encoded-object> (heap values):
  ["LIST", v0, v1, ...]                     // arrays/lists; v_i are encoded-values
  ["TUPLE", ...]  ["SET", ...]
  ["DICT", [k0,v0], [k1,v1], ...]           // maps/plain objects; k,v encoded-values
  ["INSTANCE", "<ClassName>", [field, value], ...]   // class instances/structs
  ["FUNCTION", "<signature string>"]

CRITICAL: object identity must be stable so aliasing renders correctly — if two variables
reference the same object, both must encode to ["REF", <same id>]. (The JS tracer does this via
an injected WeakMap; pick the equivalent for your language: gdb=address, JDI=uniqueID().)

Test acceptance for every backend (write a sample, run it, assert in the trace JSON):
  1. aliasing: two vars pointing at one array/object share one ["REF", id] and ONE heap entry
  2. a function call produces a stack_to_render frame with its locals
  3. an uncaught error/exception yields a trailing event:"exception" step with exception_msg (first line only)
  4. program stdout appears in the final step's stdout
```
