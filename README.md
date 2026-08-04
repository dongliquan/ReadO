# ReadO

A lightweight desktop **source code viewer** with VS Code-style editing experience and IntelliJ-style navigation.
No installation of a heavy IDE required — just point it at your source directory and read/search.

## Features

- **Monaco Editor** (the same engine that powers VS Code) — syntax highlighting for 30+ languages, line numbers, code folding
- **Find in Files** (Ctrl+Shift+F) — modal-style cross-file search with:
  - Case sensitive · whole word · regex · file glob (`*.java,*.kt`)
  - Per-project scope dropdown
  - Side-by-side **preview pane** with context lines
  - Recent search history (last 15)
- **Go to File** (Ctrl+P / Ctrl+Shift+N) — substring file name matching, scroll-loads in pages of 50
- **Go to Line** (Ctrl+G), **Go to Symbol in File** (Ctrl+Shift+O), **Go to Definition** (Ctrl+B / F12)
- **Tabs + Split editor** (Ctrl+\\) — open two files side-by-side, each pane with its own tabs
- **Auto-reveal** — opened files automatically expanded in the tree
- **Light / Dark theme** (Atom One palette) — toggle with 🌙 button
- **D2Coding font** for clean Korean + monospace rendering
- **Pywebview** native desktop window (no browser tab clutter)

## Quick Start

### 1) Dev mode (requires Python 3.10+)
```bash
pip install -r requirements.txt
python reado.py
```

### 2) Standalone .exe (Windows)
```bash
pip install -r requirements.txt
build.bat
# → dist\reado.exe  (~30 MB, no Python required at runtime)
```

## Configuration

On first run a `config.json` is created next to the .exe / script. Edit via the ⚙ settings button:

- **Base Directory** — root folder of your source code
- **Ignored folders** — exact name match, with `*` glob support (e.g. `.*` hides all dot folders)
- **File extensions to include** — only files with these extensions are indexed/searchable

## Keyboard Shortcuts

| Key | Action |
|---|---|
| `Ctrl+P` / `Ctrl+Shift+N` | Go to File |
| `Ctrl+Shift+F` | Find in Files |
| `Ctrl+G` | Go to Line |
| `Ctrl+Shift+O` | Go to Symbol in File |
| `Ctrl+B` / `F12` | Go to Definition |
| `Ctrl+F` | Find in current file (Monaco) |
| `Ctrl+\\` | Toggle split editor |
| `Ctrl+W` | Close active tab |
| `Ctrl+Tab` / `Ctrl+Shift+Tab` | Next / previous tab |

## Architecture

- `server.py` — HTTP server (port 8766): file tree, content, search, settings APIs
- `source.html` — single-page UI with Monaco editor + Pretendard + D2Coding fonts
- `reado.py` — Pywebview launcher that starts the server in a thread and opens a native window
- `build.bat` — PyInstaller one-file build script

## License

MIT
