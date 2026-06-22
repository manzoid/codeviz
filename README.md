# codeviz

Python Tutor-style **step-through execution visualization**, fully local — for
**Python, JavaScript/TypeScript, C/C++, and Java**. Produces a single
self-contained HTML page with a code highlight, stack frames, heap objects, and
reference arrows. No internet at runtime; no cloud.

```bash
python3 codeviz.py examples/demo.py --open        # Python
python3 codeviz.py examples/demo.js --open        # JavaScript
python3 codeviz.py examples/demo.ts --open        # TypeScript (needs `npm i -g typescript`)
python3 codeviz.py --code 'a=[1,2]; b=a; b.append(3)' --lang .py
python3 codeviz.py langs                           # what's supported / ready
```

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

Python and JS are 100% local. TypeScript is local too — it's transpiled with
source maps so highlighted lines point at the original `.ts` statements. C/C++
and Java run in **our own** modern, self-contained Docker images (no OPT legacy
Valgrind / java_jail). The images build once on demand from the build contexts
under [`docker/`](docker/README.md) — natively for the host arch (arm64 on
Apple Silicon), no amd64 emulation.

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
docker/README.md        building the C/C++/Java images
examples/               demo.py / .js / .ts / .c / Demo.java
```

## Limits

Best for teaching-sized snippets. The Python and JS tracers capture full state
per step (slow for huge/deeply-recursive programs); object identity for JS is
tracked via an injected WeakMap so aliasing is preserved. C/C++/Java run in
locked-down containers (`--net=none`, dropped capabilities, memory/pid limits).
The C/C++ tracer is teaching-grade (no uninitialized-memory detection). See
`NOTICE` for attribution/licensing.
