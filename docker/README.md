# Docker-based backends (C/C++, Java)

Unlike Python and JavaScript/TypeScript (which trace locally), the C/C++ and
Java backends run **our own** tracers inside containers. These are modern,
self-contained, MIT-clean images we build ourselves — **not** Online Python
Tutor's legacy Valgrind / java_jail images:

- **C/C++** — `codeviz/c-cpp:1`, `FROM ubuntu:24.04`. A GDB Python-API tracer
  (`docker/c_cpp/tracer.py`) compiles with `-g -O0` and single-steps each
  source line, following pointers to build the heap (shared pointers share one
  `REF`). Native arm64.
- **Java** — `codeviz/java:1`, `FROM eclipse-temurin:17-jdk`. An original
  `com.sun.jdi` tracer (`docker/java/Tracer.java`) launches the user's class in
  a child JVM, single-steps line-by-line, and BFS-encodes the referenced heap.
  Native arm64.
- **x86-64 assembly** — `codeviz/asm-x86:1`, `FROM ubuntu:24.04` (native arch).
  Cross-assembles the user's `.s` (entry `_start`, no libc) with
  `binutils-x86-64-linux-gnu`, runs the program under **qemu-user** (whose gdb
  stub does the instruction stepping — no ptrace), and traces it with
  `gdb-multiarch` (`docker/asm/tracer.py`). Emits an assembly-shaped trace
  (registers, decoded flags, stack window, current instruction) that the
  renderer shows in a dedicated view. Run **without** `--net=none` (the qemu
  stub needs loopback inside the container's own netns); still `--rm`,
  caps-dropped, memory/pid-limited, no published ports.

The build contexts live in this repo under `docker/c_cpp/` and `docker/java/`.

## Building

Each backend builds its image **lazily on first use** if it's missing, so you
usually don't have to do anything. To pre-build explicitly:

```bash
codeviz setup c       # or: cpp, java  — builds codeviz/c-cpp:1 / codeviz/java:1
```

`setup` runs `docker build` on the in-repo build context — natively for the
host architecture (no `--platform`), so on Apple Silicon you get a native arm64
image with no emulation.

## Runtime sandboxing

Containers run with `--net=none`, dropped capabilities, and memory/pid limits.

## Caveats

- **C/C++ is teaching-grade:** no uninitialized-memory detection. Consecutive
  identical states are collapsed (this cuts C++ `std::vector` constructor churn
  dramatically).
- **Licensing:** both tracers are our own work (MIT-clean). No OPT backend
  source is vendored or shipped.

## Adding another containerized language later (e.g. Ruby)

Create `codeviz/backends/ruby_backend.py` modeled on `c_cpp_backend.py` (lazy
image build + sandboxed container run), add a build context under `docker/`, a
`setup` target in `codeviz/cli.py`, and register the backend in
`codeviz/backends/__init__.py`.
