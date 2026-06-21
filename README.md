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
| JavaScript / TypeScript | `tracers/js/trace.js` (V8 Inspector) | locally (Node 18+) | original; TS needs `typescript` |
| C / C++ | OPT Valgrind backend | Docker | `codeviz setup c` |
| Java | OPT java_jail | Docker | `codeviz setup java` (AGPL image) |

Python and JS/TS are 100% local. C/C++ and Java use prebuilt Docker images you
build once on demand — see [`docker/README.md`](docker/README.md).

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

Nothing else changes — the renderer and CLI are language-agnostic. OPT already
ships a Ruby backend that would slot in as a Docker backend.

## Layout

```
codeviz.py              entry point
codeviz/                package: cli, core, render, server, backends/
  backends/             base.py + one file per language (the extension point)
tracers/js/trace.js     V8-Inspector JavaScript/TypeScript tracer (original)
vendor/                 OPT Python tracer (MIT), patched for 3.12
viewer_template.html    the renderer
docker/README.md        building the C/C++/Java images
examples/               demo.py / .js / .ts / .c / Demo.java
```

## Limits

Best for teaching-sized snippets. The Python and JS tracers capture full state
per step (slow for huge/deeply-recursive programs); object identity for JS is
tracked via an injected WeakMap so aliasing is preserved. C/C++/Java inherit
OPT's container limits. See `NOTICE` for attribution/licensing.
