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


_STATE_MARK = {"ready": "[ ready ]", "build": "[ build ]", "unavailable": "[   x   ]"}


def _cmd_langs(args) -> int:
    print("Supported languages:\n")
    for b in backends.all_backends():
        state, detail = b.status()
        line = f"  {_STATE_MARK[state]} {b.label:<12} {' '.join(b.extensions)}"
        if detail:
            line += f"   — {detail}"
        print(line)
    print("\n  ready = usable now · build = builds on first use · x = unavailable (see note)")
    return 0


def _cmd_doctor(args) -> int:
    """Audit the environment and print actionable next steps per language."""
    import platform
    import shutil
    import subprocess

    print("codeviz doctor — environment\n")

    print(f"  python      {platform.python_version()}  (ok)")

    node = shutil.which("node")
    if not node:
        print("  node        not found      → JavaScript/TypeScript need Node 18+  (https://nodejs.org)")
    else:
        v = subprocess.run([node, "--version"], capture_output=True, text=True).stdout.strip()
        try:
            ok = int(v.lstrip("v").split(".")[0]) >= 18
        except Exception:
            ok = False
        print(f"  node        {v}  ({'ok' if ok else 'need 18+'})   → JavaScript/TypeScript")

    from .backends.javascript_backend import _ts_deps_present
    if _ts_deps_present():
        print("  typescript  ready          → TypeScript")
    elif shutil.which("npm"):
        print("  typescript  on first use   → TypeScript (fetched once via npm)")
    else:
        print("  typescript  needs npm      → TypeScript: install Node (includes npm)")

    docker = shutil.which("docker")
    if not docker:
        print("  docker      not found      → C/C++/Java need Docker Desktop  (https://docker.com)")
    else:
        info = subprocess.run([docker, "info"], capture_output=True, text=True)
        if info.returncode != 0:
            print("  docker      not running    → start Docker Desktop (needed for C/C++/Java)")
        else:
            print("  docker      running        → C/C++/Java")

    print("\nLanguages:")
    nice = {"ready": "ready", "build": "first-run build", "unavailable": "unavailable"}
    for b in backends.all_backends():
        state, detail = b.status()
        print(f"  {nice[state]:<16} {b.label:<12} {' '.join(b.extensions)}")
        if detail:
            print(f"       → {detail}")
    return 0


def _cmd_setup(args) -> int:
    """Pre-fetch a container backend's image (pull from GHCR, else build).

    Backends do this lazily on first trace() too, so `setup` is just an eager,
    explicit fetch — handy before a class/demo so the first trace is instant.
    """
    valid = {"c", "cpp", "java", "asm"}
    if args.lang not in valid:
        print(f"setup target must be one of: {', '.join(sorted(valid))}", file=sys.stderr)
        return 2
    backend = next((b for b in backends.all_backends() if b.name == args.lang), None)
    if backend is None or not hasattr(backend, "ensure_image"):
        print(f"no container backend named '{args.lang}'", file=sys.stderr)
        return 1
    avail = backend.check()
    if not avail.ok:
        print(f"error: {avail.reason}", file=sys.stderr)
        return 1
    try:
        backend.ensure_image()
    except Exception as e:
        print(f"setup failed: {e}", file=sys.stderr)
        return 1
    print(f"{backend.label} image ready.")
    return 0


def _cmd_install_extension(args) -> int:
    """Install the bundled VS Code extension via the `code` CLI."""
    import shutil
    import subprocess
    code = shutil.which("code")
    if not code:
        print("VS Code 'code' CLI not found. In VS Code: Cmd+Shift+P → "
              "'Shell Command: Install code command in PATH', then re-run.", file=sys.stderr)
        return 1
    vsix = os.path.join(os.path.dirname(os.path.abspath(__file__)), "editor", "codeviz.vsix")
    if not os.path.exists(vsix):
        print(f"bundled extension not found at {vsix}", file=sys.stderr)
        return 1
    rc = subprocess.call([code, "--install-extension", vsix, "--force"])
    if rc == 0:
        print("codeviz VS Code extension installed. Reload VS Code, then Cmd+Alt+V on a file.")
    return rc


def _output_path(args, source) -> str:
    """Where to write the HTML. With -o, exactly there. Otherwise a temp dir
    (so codeviz never litters your source folders); the path is printed, and
    --open opens it from there."""
    if args.out:
        return args.out
    import tempfile
    name = os.path.splitext(os.path.basename(source))[0] or "codeviz"
    out_dir = os.path.join(tempfile.gettempdir(), "codeviz")
    os.makedirs(out_dir, exist_ok=True)
    return os.path.join(out_dir, name + ".viz.html")


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
        out = _output_path(args, "snippet")
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
    out = _output_path(args, args.file)
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
        epilog="subcommands: langs (list languages + readiness) · doctor (audit "
               "env + fixes) · setup <c|cpp|java|asm> (pre-fetch an image) · "
               "install-extension (install the VS Code extension).",
    )
    p.add_argument("file", nargs="?", help="source file to visualize")
    p.add_argument("--code", help="inline source instead of a file")
    p.add_argument("--lang", default=".py",
                   help="language extension for --code (default .py), e.g. .js .ts .c")
    p.add_argument("-o", "--out", help="output HTML path (default: a temp dir, not next to your source)")
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
    if argv and argv[0] == "doctor":
        return _cmd_doctor(None)
    if argv and argv[0] == "install-extension":
        return _cmd_install_extension(None)
    if argv and argv[0] == "setup":
        sp = argparse.ArgumentParser(prog="codeviz setup")
        sp.add_argument("lang", help="c | cpp | java")
        return _cmd_setup(sp.parse_args(argv[1:]))
    args = build_parser().parse_args(argv)
    return _cmd_default(args)


if __name__ == "__main__":
    sys.exit(main())
