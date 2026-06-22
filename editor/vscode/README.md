# codeviz — VS Code extension

Step-through execution visualization for the file you're editing, in a webview
beside your editor. No localhost server, no Simple Browser, no ports.

## Use

1. Open a supported file (`.py .js .ts .c .cpp .java .s .asm`).
2. **Cmd+Alt+V** (or **Cmd+Shift+P → "codeviz: Visualize Current File"**).
3. A panel opens beside the editor with the visualization. **Save** to
   re-trace; **switch files** and it follows you (auto-follow is on by default).

Step with **← / → / Space** (or the on-screen buttons / slider).

## Settings

- `codeviz.scriptPath` — absolute path to `codeviz.py` (set this).
- `codeviz.pythonPath` — Python interpreter (default `python3`).
- `codeviz.autoFollow` — re-trace when you switch files (default `true`;
  toggle with **"codeviz: Toggle Auto-Follow Active Editor"**).

## Install

Packaged: `code --install-extension codeviz-0.1.0.vsix`
(or **Extensions → … → Install from VSIX…**).

From source (dev): open this folder in VS Code and press **F5**.
