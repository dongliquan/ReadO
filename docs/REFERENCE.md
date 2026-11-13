# ReadO

**Version 0.1.0** · changes: [CHANGELOG.md](../CHANGELOG.md)

A lightweight desktop **source viewer & editor**: the essentials of VS Code / IntelliJ for reading, navigating and
quickly editing code — open any folder, jump to classes and functions, edit text files in place. No IDE install,
no project setup, works offline.

<a id="toc"></a>

## 목차

- [**Features**](#s1)
- [**Quick Start**](#s2)
- [**Offline assets (`vendor/`)**](#s3)
- [**Configuration · files ReadO writes · port**](#s4)
- [**Keyboard Shortcuts**](#s5)
- [**Architecture**](#s6)
- [**License**](#s7)

---

<a id="s1"></a>

## Features

- **Open anything** — a folder (start screen, 📁 button in the top bar, recent folders) or single files from anywhere
  (`Ctrl+O`, drag and drop, command line `reado.exe file.txt`, Windows "Open with"). A second launch hands its files to
  the running window.
- **Text files open editable** — any text file (`.txt .sh .toml .log`, `Dockerfile`, `.env`, …) is detected by content,
  not by an extension list; known binary formats are listed dimmed and not opened. Files over 2 MB open read-only
  (first 2 MB, with a banner).
- **Editing** — Monaco editor, `Ctrl+S` save, unsaved markers, conflict check when the file changed on disk
  (overwrite / reload), original encoding (UTF-8 · BOM · CP949 · UTF-16) and line endings kept, find/replace,
  external changes picked up automatically, new file (`Alt+Insert`), replace in files with preview.
- **Component navigation**
  - Go to definition: `F12` / `Ctrl+B` / Ctrl+click; several candidates open a peek list; `Alt+F12` peeks
  - Find usages: `Shift+F12` / `Alt+F7`
  - Symbol search across the folder: `Ctrl+T` (classes / methods / fields filter, prefix and CamelHumps)
  - Outline: sidebar **outline** tab and `Ctrl+Shift+O`
  - **Component tags** (`.vue .jsx .tsx .svelte .astro`): click `<ItemTop>` / `<item-top>` (or F12 / Ctrl+click) to open
    `ItemTop.vue` in the other split pane — resolved from the file's imports (relative, tsconfig / vite aliases, `@/`),
    then by file name (incl. `ItemTop/index.vue`, Nuxt `components/` prefixes), nearest first.
  - **Imports and includes are links**: an import path (anywhere in the string) opens the file; an imported
    name — on the import line or where it is used — opens the file at its export (named, default, `export … from`
    and `export *` chains), `obj.member()` of an imported object at the member.
  - **Links without Ctrl**: hovering anything that resolves — a component tag, an import path or name, a symbol the
    index knows a declaration for — underlines it (pointer cursor, resolved `file:line` in the tooltip); a plain click
    opens it beside. Words that resolve to nothing are not links, so clicking there just places the cursor;
    `Alt`+click on a link places the cursor, a double-click selects the word, a drag selects text. Setting "Open links
    without Ctrl" (on by default); Ctrl+click / F12 always work. Packages and missing files get a toast, several targets a chooser.

    | Language | Opens the file | Goes to the symbol |
    |---|---|---|
    | JS / TS / Vue / Svelte / Astro | `import`, `export … from`, `import()`, `require()`, `<script src>`, `<style src>`, `src=` / `href=` | named / default / re-exported names, `obj.member` |
    | CSS / SCSS / Less | `@import`, `@use`, `url()` | — |
    | Java / Kotlin / Scala | `import a.b.C` (package folders, or the class file with that `package`), `a.b.*` → list | `C.member`, same-package classes |
    | Python | `from .x import y`, `import a.b` (relative and absolute) | imported names, `module.func` |
    | Go | import paths inside the module (`go.mod`) → package files | `pkg.Func` |
    | C / C++ | `#include "…"` (next to the file, else anywhere in the folder) | — |
    | PHP | `require` / `include`, `use A\B\C` (composer PSR-4) | the class |
    | Rust | `mod x;`, `use crate:: / super:: / self::` | the item |
    | C# · Ruby | `using A.B` (file declaring the namespace) · `require_relative`, `require` | — |

    Paths: relative, tsconfig / jsconfig `paths`, vite aliases, package.json `imports`, else `@/` `~/` as `src/`;
    extensions may be left out (`.ts .tsx .js .vue .json …`, `index.*`). Packages (`vue`, `java.util`, `os`, …) are not opened.
    Everything else (and SQL etc.) uses the symbol index.
  - **Jumps open in the next pane**: every jump into another file (definition, import, component, a pick from a
    peek list) opens in the next pane — a single pane is split to the right, a tab already open there is reused.
    `Ctrl+Alt`+click / `Ctrl+Alt+F12` jumps in the same pane; a setting turns this off. `Alt+←` returns to the
    pane and line the jump started from
  - Back / forward: `Alt+←` / `Alt+→`
  - Backed by a **Universal Ctags** symbol index built in the background (incremental afterwards); without it,
    or while it is being built, definitions fall back to search + per-language declaration patterns
- **Search** — Find in Files (`Ctrl+Shift+F`, bundled ripgrep): case / whole word / regex, files-to-include globs,
  scope (whole folder, the current file's folder, a subfolder), preview pane, recent searches
- **Go to File** (`Ctrl+P`), **recent files** (`Ctrl+E`), **Go to Line** (`Ctrl+G`)
- **Files in the tree** — right-click a file or folder (or select it and press `F2` / `Delete`): new file / folder,
  rename (open tabs follow), delete (Recycle Bin first, always asked; open tabs close), copy path, reveal in Explorer,
  collapse all. File-type badges in the tree and on tabs
- **Optional .gitignore filter** (settings / palette) — hides what .gitignore excludes from the tree, Quick Open,
  the symbol index and Find in Files
- **Keymaps** — VS Code (default) or IntelliJ IDEA (`Ctrl+N` class, `Ctrl+Shift+N` file, `Ctrl+F12` structure,
  `Ctrl+Shift+A` actions, `Alt+F7` usages, `Shift+F6` rename …); settings / palette, checked for key conflicts
- **Diff** — compare with the saved file, with git HEAD, or with another file (side by side)
- **Git tool window (read-only)** — `Alt+9` (IntelliJ) / `Ctrl+Shift+G` (VS Code) or the **Git** menu / toolbar button.
  ReadO *shows* repositories; commands that change one (commit, push, pull, checkout, merge, rebase, stash …)
  become an instruction for **AgentO** instead (copied to the clipboard, AgentO brought up; or a terminal opens in
  the repository). Uses the git installed on the PC (2.24+); without it the Git views stay off with a notice.
  - **Local Changes** — changed / staged / unversioned / conflicted files as a folder tree with counts, merge /
    rebase banner; split like IntelliJ: the tree on the left, the selected file's diff on the right (click or ↑ / ↓
    to change it; previous / next change, side by side / unified, whitespace option; drag the bar between them).
    Double-click, Enter or right-click → Show Diff in Window opens a floating diff window
  - **Click a file** (a commit's or stash's files; Local Changes: double-click; a History row: double-click) — the diff opens in a
    diff window — a separate OS window (its own Windows title bar, movable anywhere, other monitors too; the main
    window stays uncovered and usable). One window per file + revision (up to 8, the oldest closes); clicking the same
    one again brings it to the front; all close with the main window; size and place are remembered. Inside: path and
    commit hash, ↑ / ↓ file (Alt+↑ / ↓ in the diff), previous / next change (F7), side by side / unified, whitespace
    option, Open in Editor (the main window opens the file and comes forward), Esc closes it. In browser mode
    (`python server.py`) the same view opens as a panel inside the page. Local files are compared with HEAD (the live editor buffer when the file is open)
  - **Log** — commit graph, branch labels, author, date; branch tree (HEAD / Local / Remote / Tags, click = filter);
    filters: text or hash (regex, match case), Branch, User, Date, Paths; commit details with the changed-files tree
    (+/− lines) and the full message; pages of 300–500 commits load while scrolling, only visible rows are drawn
  - **History** of a file (follows renames), **Stash** list (read only), **Console** (every git command ReadO ran)
  - In the editor: **Annotate with Git Blame** (editor or gutter right-click, Git menu): an IntelliJ-style column left of the line
    numbers ("M/D/YYYY author" on every line, each commit's lines shaded, newer = darker) in the
    gutter, hover → hash / author / date / message, click → that commit's changes in a diff window (gutter right-click:
    Show Commit in Git Log, Copy Revision Number, Close Annotations). Optional (Settings / Git menu, off by default):
    the current line's commit faintly at the line end. Click a gutter change
    marker → diff at that line, conflict markers highlighted. In the tree: changed / new / conflicted files coloured,
    folders with changes marked. Status bar: branch, ahead / behind, MERGING …; click → branches
  - Safe on any repository: only read-only git sub-commands run, the repository's own config cannot make git start
    programs (fsmonitor, filter drivers, external diff / textconv are switched off), revisions and paths are checked,
    no index locks are taken, every call times out. Design: `docs/GIT-DESIGN.md`
- **View** — minimap and whitespace toggles, reopen with another encoding, limits (file size, search results) in settings
- **Title bar and menus as in AgentO** — one row with the app icon, File / Edit / View / Go / Window / Help menus,
  a search box (Ctrl+P · Ctrl+Shift+P) and the window buttons. The window has no Windows caption but keeps the native
  behaviour: drag the bar to move (Aero Snap to screen edges, Win+arrows), double-click to maximize, drag an edge or
  corner to resize; closing with unsaved files still asks first
- **Tool strip** (left edge, IntelliJ style) — Files, Outline and Git icons: click opens the tool, clicking the active one
  folds it (the editor gets the width); the Git icon is greyed out outside a git repository. Folded state, sidebar
  width and the active tool are kept in state.json
- **Command palette** (`Ctrl+Shift+P`, or `>` in Ctrl+P) — every command with its key, fuzzy search, recently run
  first. Menus, palette and keys run the same command registry
- **Tabs, up to 4 editor panes** — layouts from the ▥ button (single · two / three columns · two rows · 2×2 grid),
  split right / down (`Ctrl+\` / `Ctrl+Alt+\`), drag the borders to resize; each pane has its own tabs, the same file
  in several panes shares one buffer. Drag a tab to another pane (Ctrl: copy) or right-click it (split / move / copy)
- Markdown preview (sanitized), light / dark theme, status bar
- **Session restore** — open tabs, pane layout and sizes, cursor, theme, recent files / folders / searches
- **Fully offline** — Monaco, marked, webfonts, ripgrep and ctags are bundled

<a id="s2"></a>

## Quick Start

### 1) Dev mode (requires Python 3.10+)
```bash
pip install -r requirements.txt
python fetch-vendor.py     # once: Monaco / marked / fonts / ripgrep / ctags into vendor\
python reado.py [file ...]
```

### 2) Standalone .exe (Windows)
```bash
pip install -r requirements.txt
build.bat                  # runs fetch-vendor.py automatically if vendor\ is incomplete
# → dist\reado.exe  (one file, no Python and no network required at runtime)
```

Releasing a new build (build into `dist-next`, test, swap into `dist`, cut the version): [docs/RELEASE.md](RELEASE.md).

<a id="s3"></a>

## Offline assets (`vendor/`)

The built-in HTTP server serves Monaco Editor, marked and the webfonts at `/vendor/`; `rg.exe` and `ctags.exe` are run
as child processes (never served). These ~22 MB are **not committed**. Recreate them with:

```bash
python fetch-vendor.py            # fetches only what is missing
python fetch-vendor.py --force    # refetch (e.g. after a version bump)
```

Pinned versions (and SHA-256 for the two executables) live at the top of `fetch-vendor.py`: `MONACO_VERSION`,
`MARKED_VERSION`, `PRETENDARD_TAG`, `RIPGREP_VERSION`, `CTAGS_VERSION`. `vendor/fonts.css` is hand-written source and
**is** tracked.

<a id="s4"></a>

## Configuration · files ReadO writes · port

Settings (⚙ button):

- **Working folder** — also set from the start screen or the 📁 button; empty until you open one
- **Hidden everywhere** — names or globs; default `.git .svn .hg node_modules __pycache__ .venv venv`
  (other dot files such as `.env` and `.gitignore` are shown)
- **Shown in the tree, left out of search / Quick Open / symbols** — default `build dist target out bin obj coverage`
- **Windows "Open with"** — add / remove ReadO in Explorer's "Open with" (current user, no admin rights)
- `max_file_bytes` (2 MB) and `search_max_results` (500) can be changed in `config.json`

Files (next to `config.json`):

| File | Location | Contents |
|---|---|---|
| `config.json` | exe: `%APPDATA%\ReadO\` · source: the repo folder | settings; configs from older versions are migrated once (changed values kept) |
| `state.json` | same folder | UI state (tabs, theme, recent files / folders / searches) and the outside files you opened |
| `instance.json` | same folder, while running | port + secrets so a second launch can hand over its files; removed on exit |

Port: `127.0.0.1:8766`, or any free port when 8766 is taken (loopback only). The page is protected by Host / Origin
checks and a per-process token on every write request.

<a id="s5"></a>

## Keyboard Shortcuts

| Key | Action |
|---|---|
| `Ctrl+P` / `Ctrl+Shift+N` | Go to file — fuzzy, recent files first; type `>` commands · `#` symbols · `@` in file · `:` line |
| `Ctrl+Shift+P` | Command palette (all commands, with their keys) |
| `Alt+1` · `Alt+2` | Files · Outline in the sidebar; the same key again folds the sidebar away (also the « button and the left tool strip) |
| `F2` / `Delete` (tree) | Rename / delete the selected file or folder (IntelliJ keymap: `Shift+F6` rename) |
| `Ctrl+E` | Recent files |
| `Ctrl+T` / `Ctrl+Alt+Shift+N` | Go to symbol in folder |
| `Ctrl+Shift+O` | Go to symbol in file (outline) |
| `F12` / `Ctrl+B` / Ctrl+click | Go to definition |
| `Alt+F12` | Peek definition |
| click / `F12` on `<ItemTop>` | Open the component file in the other pane (plain click: setting, on by default) |
| `Ctrl+Alt`+click / `Ctrl+Alt+F12` on `<ItemTop>` | Open the component file in the same pane |
| `Ctrl+Enter` in `Ctrl+P` / `Ctrl+T` | Open the file / symbol in the other pane |
| `Shift+F12` / `Alt+F7` | Find usages |
| `Alt+←` / `Alt+→` | Back / forward |
| `Ctrl+G` | Go to line |
| `Ctrl+Shift+F` / `Ctrl+Shift+H` | Find in files / replace in files |
| `Ctrl+F` / `Ctrl+H` | Find / replace in the current file |
| `Ctrl+S` | Save |
| `Ctrl+O` | Open file (anywhere) |
| `Alt+Insert` / `Ctrl+N` | New file |
| `Ctrl+Shift+E` | Toggle editing (on at start) |
| `Ctrl+W` · `Ctrl+Tab` / `Ctrl+Shift+Tab` | Close tab · next / previous tab |
| `Ctrl+\` / `Ctrl+Alt+\` | Split the pane right / down (max 4; ▥ button: layout presets) |
| `Ctrl+1` … `Ctrl+4` | Focus pane 1–4 |
| `Ctrl+Alt+←/→/↑/↓` | Focus the neighbouring pane (↑/↓ add a cursor when there is no pane that way) |
| `Ctrl+Alt+PgDn` / `Ctrl+Alt+PgUp` | Move the tab to the next / previous pane |
| `Alt+Z` · `Ctrl+=` / `Ctrl+-` / `Ctrl+0` | Word wrap · font size |
| `Ctrl+Shift+G` (IntelliJ: `Alt+9`) · IntelliJ `Alt+0` | Git tool window · Local Changes |
| IntelliJ `Ctrl+K` / `Ctrl+Shift+K` | Commit / push — as an instruction for AgentO (nothing runs in ReadO) |

<a id="s6"></a>

## Architecture

- `server.py` — loopback HTTP server: file tree / content / save, search (ripgrep, Python fallback), symbol index
  (Universal Ctags), go to definition / usages, settings and UI state, `/vendor/` assets; every write goes through
  the `@write_api` guard. Feature blocks live in `srv_search.py` (Find in Files), `srv_goto.py` (go to definition /
  usages), `srv_links.py` (component tags, import links), `srv_tags.py` (ctags index), `srv_fileops.py` (replace in
  files, tree file operations); each reads the core's globals as `server.NAME` at call time
- `source.html` — single-page UI (Monaco + Pretendard / D2Coding fonts): markup plus `<!--#include ui/...-->` lines;
  the server puts the `ui/*.css` / `ui/*.js` files in their place when it serves the page, so the browser still
  gets one style and one script (a new file needs its include line; order = run order)
- `gitview.py` — read-only git views behind `/api/git/*` (guarded git runner, status, log sessions, blame …);
  `git.js` / `git.css` — the Git tool window, served next to `source.html`
- `tests/` — `test_git.py` (headless API tests on fixture repositories, `git_fixture.py`), `ui_git_smoke.py` (browser);
  `verify_editor.py` — the headless editor suite: `python tests/verify_editor.py` (needs `pip install playwright` +
  `playwright install chromium`; fixtures in `%TEMP%\reado-headless`, or set `READO_TEST_WORK`);
  `exe_startup.py` — start-up guards of a built exe: `python tests/exe_startup.py dist\reado.exe`
- `reado.py` — pywebview launcher: starts the server, opens the native window, open dialog, drag and drop,
  command-line files, single instance, quit prompt for unsaved changes, "Open with" registration;
  `startguard.py` — start-up watchdog (no window in 20 s: `startup.log` + exit) and the checks a second launch makes
  on a running instance; `nowmi.py` — keeps WMI queries out of the process (also a PyInstaller runtime hook)
- `fetch-vendor.py` — downloads the bundled 3rd-party assets into `vendor/` (stdlib only, versions pinned)
- `build.bat` — PyInstaller one-file build (`build.bat dist-next` builds next to a running `dist\reado.exe`)
- `scripts/` — `build_test.py` (build `dist-next` + every automated suite), `swap_dist.py` (tested build into
  `dist`, old one to `dist-prev`; dry run unless `--apply`; `--restart` starts the new exe) — the release steps
  are in `docs/RELEASE.md`
- `docs/` — feature list and gap analysis (`FEATURES.md`), performance report (`PERF.md`), design review (`DESIGN-REVIEW.md`)

<a id="s7"></a>

## License

MIT (ReadO). Bundled tools keep their own licenses: ripgrep (MIT / Unlicense, `vendor/rg/`), Universal Ctags
(GPL-2.0, `vendor/ctags/COPYING`; run as a separate program), Monaco (MIT), marked (MIT), Pretendard / D2Coding (OFL).
git is not bundled. Projects used as references for the Git views are listed in `../NOTICE`.

## Manual checks (things the automated tests cannot do)

Run these on a real desktop after a new build (`dist-next\reado.exe`); the automated suites cover the rest.

1. **Drag and drop from Explorer** — drag one file, then three files at once, from Explorer onto the editor area and onto
   the tree: each opens as a tab; a file outside the working folder opens too (its tab path is absolute) and can be saved.
2. **Open with** — Settings → "Windows Open with" → register. In Explorer right-click a `.java` / `.md` file → Open with →
   ReadO: with ReadO closed it starts with that file; with ReadO running the file opens as a new tab in the same window
   (no second window). Unregister afterwards and check the entry is gone.
3. **Title bar** — drag the bar to move the window; drag it to the top edge (maximizes) and the left / right edge
   (snaps to half); Win+← / Win+→ / Win+↑; double-click the bar; drag each edge and corner to resize; minimize /
   maximize / close buttons; close with an unsaved tab asks first.
4. **Delete to the Recycle Bin** — delete a file from the tree, then restore it from the Recycle Bin.
5. **Paste from the Edit menu** — copy text elsewhere, Edit → Paste into the editor.
6. **Changelists (Git → Local Changes)** — in a repository with a few changed files: right-click → New Changelist…;
   Ctrl+click two files and Move to Changelist…; drag a file onto another list with the real mouse (the desktop
   WebView); Set Active, change a file, ⟳ — it lands in the active list; restart ReadO and switch branch — the lists
   stay; Commit… on a list copies an AgentO instruction with only its files and its name as the message.
7. **Repository menu (Git window header)** — in a folder with many repositories, in the light and the dark theme:
   the menu looks like the branch menu (no white system list), badges fill in, the filter and ↑ / ↓ Enter Esc work.
   Tick two repositories → Show: Local Changes groups them; fold one; click files of both (each diff from its own
   repository); Pull / Fetch are greyed; All repositories with a few dozen repositories stays responsive while the
   groups fill in; restart ReadO — the same set is shown; click one name — back to one repository.
