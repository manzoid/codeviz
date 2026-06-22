# codeviz

Python Tutor-style **step-through execution visualization**, fully local — for
**Python, JavaScript/TypeScript, C/C++, Java, and x86-64 assembly**. Produces a
single self-contained HTML page with a code highlight, stack frames, heap
objects, and reference arrows (and a dedicated registers/flags/stack view for
assembly). No internet at runtime; no cloud.

## Install

```bash
git clone https://github.com/manzoid/codeviz
cd codeviz
./install.sh
```

`install.sh` installs the `codeviz` command, the JS/TS tracer deps, and the VS
Code extension (and is safe to re-run). **Prerequisites:** Python 3.9+ (required);
**Node 18+** for JavaScript/TypeScript and **Docker** for C/C++/Java/asm are
optional — those languages activate only when present. Run `codeviz doctor`
anytime to see what's ready and how to enable the rest.

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
without emulating the whole container, and without ptrace). The images build
once on demand from the build contexts under [`docker/`](docker/README.md).

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
under `docker/` (see [`docker/README.md`](docker/README.md)).

## Layout

```
codeviz.py              entry point
codeviz/                package: cli, core, render, server, backends/
  backends/             base.py + one file per language (the extension point)
tracers/js/trace.js     V8-Inspector JS/TS tracer (original); TS via source maps
vendor/                 OPT Python tracer (MIT), patched for 3.12
viewer_template.html    the renderer
docker/c_cpp/           our C/C++ image (GDB Python-API tracer)
docker/java/            our Java image (JDI tracer)
docker/asm/             our x86-64 asm image (qemu-user + gdb-multiarch tracer)
docker/README.md        building the C/C++/Java/asm images
examples/               demo.py/.js/.ts/.c, Demo.java, hello.s,
                        count_up.s, count_down.s, count_down_print.s
```

## Limits

Best for teaching-sized snippets. The Python and JS tracers capture full state
per step (slow for huge/deeply-recursive programs); object identity for JS is
tracked via an injected WeakMap so aliasing is preserved. C/C++/Java run in
locked-down containers (`--net=none`, dropped capabilities, memory/pid limits).
The C/C++ tracer is teaching-grade (no uninitialized-memory detection). See
`NOTICE` for attribution/licensing.
