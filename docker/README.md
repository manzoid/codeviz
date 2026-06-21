# Docker-based backends (C/C++, Java)

Unlike Python and JavaScript (which trace locally), the C/C++ and Java backends
run Online Python Tutor's heavyweight tracers inside containers:

- **C/C++** — a custom-patched **Valgrind 3.11** (`pgbovine/opt-cpp-backend:v1`)
- **Java** — David Pritchard's **java_jail** traceprinter (`pgbovine/cokapi-java:v1`)

These build contexts are large (custom Valgrind source; a bundled JDK) and
legacy (Ubuntu 14.04, x86_64), so this repo does **not** vendor them. Instead:

```bash
codeviz setup c       # or: cpp, java
```

`setup` shallow-clones OPT's backend mirror into `~/.cache/codeviz/opt-mirror`
and runs `docker build` on the relevant subdirectory.

## Caveats

- **Apple Silicon / arm64:** the images are x86_64 and build/run under amd64
  emulation (`--platform linux/amd64`). Builds are slow; runtime tracing is
  noticeably slower than the local Python/JS backends.
- **Ubuntu 14.04 is EOL.** apt mirrors for it occasionally break; if a build
  fails on `apt-get`, that's why. Modernizing these Dockerfiles is a known
  follow-up.
- **Licensing:** the Java traceprinter (java_jail) is **AGPL-3.0**. codeviz only
  orchestrates the prebuilt image and vendors none of its source. If you
  redistribute the image, preserve that license.

## Adding another containerized language later (e.g. Ruby)

OPT also ships a Ruby backend (`v4-cokapi/backends/ruby`). To add it: create
`codeviz/backends/ruby_backend.py` modeled on `c_cpp_backend.py`, add a `setup`
target here, and register it in `codeviz/backends/__init__.py`.
