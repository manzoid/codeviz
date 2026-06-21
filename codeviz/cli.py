"""codeviz command-line interface."""
from __future__ import annotations

import argparse
import os
import sys
import webbrowser

from . import backends
from .core import build_page, trace_code, UnsupportedLanguage
from .render import render_html
from .server import serve


def _cmd_langs(args) -> int:
    print("Supported languages:\n")
    for b in backends.all_backends():
        avail = b.check()
        mark = "ok " if avail.ok else "-- "
        exts = " ".join(b.extensions)
        line = f"  [{mark}] {b.label:<12} {exts}"
        if not avail.ok:
            line += f"   ({avail.reason})"
        print(line)
    return 0


def _cmd_setup(args) -> int:
    """Build the Docker image for a heavyweight backend.

    The C/C++/Java build contexts (custom Valgrind, bundled JDK) are large and
    legacy, so we don't vendor them.  Instead we shallow-clone OPT's mirror into
    a cache and build the relevant subdirectory on demand.
    """
    import subprocess
    # (image tag, subdir within the OPT mirror)
    targets = {
        "c": ("pgbovine/opt-cpp-backend:v1", "v4-cokapi/backends/c_cpp"),
        "cpp": ("pgbovine/opt-cpp-backend:v1", "v4-cokapi/backends/c_cpp"),
        "java": ("pgbovine/cokapi-java:v1", "v4-cokapi/backends/java"),
    }
    if args.lang not in targets:
        print(f"setup target must be one of: {', '.join(sorted(targets))}", file=sys.stderr)
        return 2
    tag, subdir = targets[args.lang]

    cache = os.path.expanduser("~/.cache/codeviz/opt-mirror")
    mirror = "https://github.com/forkcodeaiyc/OnlinePythonTutor2"
    if not os.path.isdir(os.path.join(cache, ".git")):
        os.makedirs(os.path.dirname(cache), exist_ok=True)
        print(f"cloning OPT backend mirror into {cache} (one-time, large) ...")
        rc = subprocess.call(["git", "clone", "--depth", "1", mirror, cache])
        if rc != 0:
            print("clone failed.", file=sys.stderr)
            return rc

    ctx = os.path.join(cache, subdir)
    if not os.path.isdir(ctx):
        print(f"context not found in mirror: {ctx}", file=sys.stderr)
        return 1
    cmd = ["docker", "build", "--platform", "linux/amd64", "-t", tag, ctx]
    print("running:", " ".join(cmd))
    print("(legacy ubuntu:14.04 image built under amd64 emulation — this is slow)")
    return subprocess.call(cmd)


def _output_path(args, default_base: str) -> str:
    if args.out:
        return args.out
    return default_base + ".viz.html"


def _cmd_default(args) -> int:
    # serve mode
    if args.serve:
        if not args.file:
            print("--serve requires a FILE", file=sys.stderr)
            return 2
        serve(args.file, args.port, open_browser=args.open)
        return 0

    # inline snippet
    if args.code is not None:
        ext = args.lang if args.lang.startswith(".") else "." + args.lang
        try:
            data, backend = trace_code(args.code, ext)
        except (UnsupportedLanguage, RuntimeError) as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        html = render_html(data, "snippet", backend.name)
        out = _output_path(args, os.path.join(os.getcwd(), "snippet"))
        with open(out, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"wrote {out}  ({len(data.get('trace', []))} steps, {backend.label})")
        if args.open:
            webbrowser.open("file://" + os.path.abspath(out))
        return 0

    # file -> static HTML
    if not args.file:
        print("nothing to do: pass a FILE, --code, or --serve. See --help.", file=sys.stderr)
        return 2
    try:
        html, n, lang = build_page(args.file)
    except (UnsupportedLanguage, RuntimeError, FileNotFoundError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    out = _output_path(args, os.path.splitext(args.file)[0])
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"wrote {out}  ({n} steps, {lang})")
    if args.open:
        webbrowser.open("file://" + os.path.abspath(out))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="codeviz",
        description="Python Tutor-style step visualization, fully local. "
                    "Supports Python, JavaScript/TypeScript, C/C++, and Java.",
        epilog="subcommands: 'codeviz langs' lists languages; "
               "'codeviz setup <c|cpp|java>' builds a backend's Docker image.",
    )
    p.add_argument("file", nargs="?", help="source file to visualize")
    p.add_argument("--code", help="inline source instead of a file")
    p.add_argument("--lang", default=".py",
                   help="language extension for --code (default .py), e.g. .js .ts .c")
    p.add_argument("-o", "--out", help="output HTML path")
    p.add_argument("--open", action="store_true", help="open the result when done")
    p.add_argument("--serve", action="store_true",
                   help="live-reload server: re-trace on save (requires FILE)")
    p.add_argument("--port", type=int, default=8930, help="port for --serve (default 8930)")
    return p


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    # Dispatch subcommands manually so they don't collide with the FILE positional.
    if argv and argv[0] == "langs":
        return _cmd_langs(None)
    if argv and argv[0] == "setup":
        sp = argparse.ArgumentParser(prog="codeviz setup")
        sp.add_argument("lang", help="c | cpp | java")
        return _cmd_setup(sp.parse_args(argv[1:]))
    args = build_parser().parse_args(argv)
    return _cmd_default(args)


if __name__ == "__main__":
    sys.exit(main())
