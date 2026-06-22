# codeviz

Python Tutor-style **step-through execution visualization**, fully local — for
**Python, JavaScript/TypeScript, C/C++, Java, and x86-64 assembly**. Produces a
single self-contained HTML page with a code highlight, stack frames, heap
objects, and reference arrows (and a dedicated registers/flags/stack view for
assembly). No internet at runtime; no cloud.

## Install

No clone to keep around — install straight from GitHub with
[uv](https://docs.astral.sh/uv/):

```bash
uv tool install git+https://github.com/manzoid/codeviz
codeviz install-extension      # optional: the VS Code extension
```

(`pipx install git+https://github.com/manzoid/codeviz` works too.) Or from a
clone, `git clone … && cd codeviz && ./install.sh`.

**Prerequisites:** Python 3.9+ (required). **Node 18+** for JavaScript/TypeScript
and **Docker** for C/C++/Java/asm are optional — those languages activate only
when present (TypeScript fetches its compiler on first use; the Docker images
pull prebuilt from GHCR). Run `codeviz doctor` anytime to see what's ready and
how to enable the rest.

In VS Code: **Cmd+Alt+V** on a file opens the visualization beside your editor
(it follows the active file and re-traces on save).

## Quick start

```bash
codeviz examples/demo.py --open        # Python
codeviz examples/demo.ts --open        # TypeScript
codeviz examples/count_down.s --open   # x86-64 assembly (Docker)
codeviz langs                           # what's supported / ready
codeviz doctor                          # audit env + per-language fixes
```

(No install? `python3 codeviz.py <file>` works the same from the repo.)

## How it works

Every language is traced into the **same Online Python Tutor (OPT) trace JSON**;
one language-agnostic renderer (`viewer_template.html`) draws it. A *backend*
turns source into that trace:

| Language | Backend | Runs | Notes |
|----------|---------|------|-------|
| Python | vendored OPT `pg_logger` | locally | pure stdlib |
| JavaScript | `tracers/js/trace.js` (V8 Inspector) | locally (Node 18+) | original tracer |
| TypeScript | same tracer, transpiled w/ source maps | locally (Node 18+) | needs `typescript`; lines map back to the original `.ts` |
| C / C++ | **our own** GDB Python-API tracer | Docker (`codeviz/c-cpp:1`) | native arm64; `codeviz setup c` |
| Java | **our own** JDI tracer | Docker (`codeviz/java:1`) | native arm64, MIT-clean; `codeviz setup java` |
| x86-64 asm | **our own** GDB + qemu-user tracer | Docker (`codeviz/asm-x86:1`) | dedicated registers/flags/stack view; `codeviz setup asm` |

Python and JS are 100% local. TypeScript is local too — it's transpiled with
source maps so highlighted lines point at the original `.ts` statements. C/C++,
Java, and assembly run in **our own** modern, self-contained Docker images (no
OPT legacy Valgrind / java_jail). The C/C++ and Java images are native arm64;
the assembly image is native too — it cross-assembles the x86-64 program and
runs *just that* under qemu-user's gdb stub (so x86-64 is faithfully emulated
without emulating the whole container, and without ptrace). On first use the
images are **pulled prebuilt from GHCR** (multi-arch), falling back to a local
build from the contexts under [`docker/`](codeviz/docker/README.md) if a pull isn't
available.

Assembly gets its own view: the current instruction, a **registers** panel that
highlights whichever register just changed, a **flags** strip (ZF/SF/CF/OF/…),
and a **stack** window — so loops like `count_up.s` vs `count_down.s` make the
compare-flag vs zero-flag branch logic visible.

## Fluid workflow in VS Code (live reload)

```bash
python3 codeviz.py path/to/file --serve     # http://localhost:8930
```

`Cmd+Shift+P` → **Simple Browser: Show** → `http://localhost:8930`, drag it
beside your editor. Edit + **save** → the page re-traces and reloads at step 1.
Step with **← / →**, the slider, or **Run ⏩** to jump to the end. A VS Code task
(`.vscode/tasks.json`) serves whatever file is active.

## What it shows

- Current line (blue = about to run, yellow = returned/raised)
- **Frames**: global frame + call stack, locals in order
- **Objects**: heap boxes for lists/arrays, dicts/objects, sets, instances, functions
- **Arrows** from each variable to the object it references — aliasing (`b = a`)
  is one shared object with two arrows
- Program output and uncaught exceptions

## Adding a language later (Ruby, Dart, …)

1. Add `codeviz/backends/<lang>_backend.py` with a `Backend` subclass
   (`name`, `extensions`, `trace()`; override `check()` for toolchains).
2. Register it in `codeviz/backends/__init__.py`.

Nothing else changes — the renderer and CLI are language-agnostic. For a
containerized language, model it on `c_cpp_backend.py` and add a build context
under `codeviz/docker/` (see [`docker/README.md`](codeviz/docker/README.md)).

## Layout

All runtime data lives inside the `codeviz/` package, so installs are
self-contained (no clone needed):

```
codeviz.py                  dev entry point (`python3 codeviz.py …`)
codeviz/                    the package (pip/uv-installable)
  cli, core, render, server
  backends/                 base.py + one file per language (extension point)
  viewer_template.html      the renderer
  vendor/                   OPT Python tracer (MIT), patched for 3.12
  tracers/js/trace.js       V8-Inspector JS/TS tracer (original); TS via source maps
  docker/{c_cpp,java,asm}/  our container tracers (GDB / JDI / qemu-user)
  editor/codeviz.vsix       bundled VS Code extension (codeviz install-extension)
editor/vscode/              extension source
examples/                   demo.py/.js/.ts/.c, Demo.java, hello.s, count_*.s
```

## Limits

Best for teaching-sized snippets. The Python and JS tracers capture full state
per step (slow for huge/deeply-recursive programs); object identity for JS is
tracked via an injected WeakMap so aliasing is preserved. C/C++/Java run in
locked-down containers (`--net=none`, dropped capabilities, memory/pid limits).
The C/C++ tracer is teaching-grade (no uninitialized-memory detection). See
`NOTICE` for attribution/licensing.
