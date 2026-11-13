# ReadO — Changelog

All notable changes to ReadO. Versions follow [semantic versioning](https://semver.org/); the version shown in
**Help → About** comes from `VERSION` in `server.py`.

<a id="toc"></a>

## 목차

- [**Unreleased**](#unreleased)
- [**0.2.0 (proposed) — 2026-10-26**](#v020)
- [**0.1.0 — first release**](#v010)

---

<a id="unreleased"></a>

## Unreleased

- Find File (`Ctrl+P`): files named exactly like what you typed (any case) come first — `items.vue` lists every
  `Items.vue` / `items.vue` before `ItemsSidebar.vue` and other loose matches from the recent files. The order is:
  exact names you opened before, other exact names, other recent files, the rest. A query with a path (`/`) keeps
  the old order.
- Dark theme: easier on the eyes, every text color at least 4.5:1 (WCAG) and nothing pure red / green / magenta.
  SQL strings were pure red (#ff0000) and SQL functions magenta — Monaco's built-in SQL / HTML / YAML rules won over
  One Dark's; One Dark now names them. Diffs (compare, the Git diff window) use a faint coral / green tint per line
  and a slightly stronger one for the characters that changed, instead of solid red / green. Secondary text
  (breadcrumb, hints, line numbers, comments, Git columns) is lighter, primary buttons have dark text on blue, file
  badges get a calmer twin of their color, bracket pairs and gutter markers use the One Dark colors. The light
  theme is unchanged. `scripts/contrast_check.py` checks the dark palette (themes in `ui/themes.js`, shared by
  the main window and the diff windows).
- Double-click the file name on an editor tab or at the end of the breadcrumb: the source gets the whole width (the
  sidebar and the Git tool window go away); double-click again and they come back as they were (sidebar width and
  panel kept). Single clicks, dragging and closing tabs work as before.
- `scripts/swap_dist.py` waits up to 90 s (was 30 s) for a running ReadO to close: an app left open for hours took
  over 30 s to exit after its window closed, and the swap stopped with nothing changed.
- Find File no longer answers "no results" after a chooser was closed without a pick (several files for a link
  or a component, then Esc): the chooser's mode stayed behind and Ctrl+P filtered its old list. Folders with copies
  of the same files (git worktrees such as `_wt\…`) made such choosers frequent.
- Recent files and recent folders that are gone (deleted, or their folder removed) leave the lists — Find File's
  recent files, the start screen and the saved state. One check for all of them at start, when a folder opens and
  when Find File opens (at most every 30 s); opening a recent file that is gone drops it at once. A drive that does
  not answer in time (network share) is left alone: nothing is hidden or dropped for it.
- Find in Files: **file mask and exclude are edited in their own dialog**. The option bar shows what is in use
  (`mask: *.vue · exclude: 12`); click it to edit both lists, one pattern per line or comma-separated, with the
  pattern rules under each box. Ctrl+Enter or Apply applies, Esc or Cancel leaves them as they were.
  The exclude list is the whole list: it starts with the default patterns (the search-ignored folders from Settings
  plus `.idea`, `.vs`, minified / bundled js and css, source maps, lock files, `shelved.patch` …) and is kept between
  runs; **Defaults** puts the default patterns back (it was an on / off switch for a list you could not see, next to
  a grey hint `.idea/**, *.patch, dist/**` that looked like a value). Saved options carry over: with Defaults on,
  the list gets the defaults plus your own patterns.
- The saved theme is applied before the page first paints (no light flash when ReadO starts in the dark theme).
- Fixed: the toolbar theme button (icon only: moon in the light theme, sun in the dark one) showed the previous
  theme's icon right after a switch. It now changes with the theme and has an aria-label naming the current one.
- Faster: Find in Files and go to definition no longer run the whole search a second time without ripgrep when
  ripgrep could not read a few files (e.g. `.gradle/*.lock` held by a running Gradle or IDE). A no-hit search over a
  15-repository folder took 22–103 s, now about 1.7 s; the results are the same.
- Find in Files while typing: an older search stops as soon as a newer one starts, also while it has found nothing
  yet, and a search waits up to 1 s for a free slot instead of failing at once with "search capacity reached" (the
  last word typed could come back as that error and no results).
- Fixed: Find File (`Ctrl+P`) could keep showing nothing (or an older list) after you stopped typing, until the next
  key: what was typed while a request was still running was dropped. A new query now replaces the running request.
- Faster: the first symbol index (Symbols `#`, go to definition) of a large folder is built by up to 4 ctags runs at
  once (23.5k files: 145 s → 76 s); the symbols and their order are the same.
- Git window: the **repository menu** looks like the branch menu (theme colours instead of the white system list).
  It has a filter box, ✓ on the selected repository and a badge with each repository's number of changed files
  (red when it has conflicts). ↑ / ↓, Enter and Esc work in it.
- Git window: **Local Changes of several repositories at once**. Tick repositories in the repository menu (or
  **All repositories**) and press **Show**. Local Changes then groups the files by repository, with the branch,
  any merge / rebase in progress and a file count on each group, and each group folds. Clicking a file shows its
  diff from its own repository. Commit / Rollback / Resolve (AgentO) work on the files of one repository at a time.
  Branch, Pull, Fetch, Log, History and Stash ask you to choose one repository; **Show Only &lt;name&gt;** on a file
  does that. The choice is kept between runs. Clicking a name in the menu shows that repository alone, as before.
- Release: `python scripts/swap_dist.py --apply --expect <hash> --restart` starts the new `dist\reado.exe` after
  the swap (your normal settings, last folder restored) and waits until its window is up (exit code 3 if it does
  not come up). The running ReadO it closes first is also found by the PID in `%APPDATA%\ReadO\instance.json`;
  it still gets only a normal close, and unsaved edits stop the swap.

---

<a id="v020"></a>

## 0.2.0 (proposed) — 2026-10-26

Proposed number, not tagged yet: the app still says 0.1.0 (`server.py` `VERSION`, README) until it is confirmed.

### Search

- **Find File and Find in Files are one dialog frame**: same place, size, input and rows, with tabs (Files · In Files ·
  Commands · Symbols). `Tab`, `Ctrl+P` / `Ctrl+Shift+F` or a tab click switch between them and keep the typed text;
  `%` in Find File moves the rest to Find in Files.
- Find in Files: results grouped by file like Find File rows (badge, name, dim folder, count), option bar (match case,
  words, regex, file mask, scope, context, Replace) kept between runs, `Alt+C` / `Alt+W` / `Alt+X`, recent searches when
  the box is empty, **show more** past the result cap (up to 20,000), `Ctrl+Enter` / `Ctrl+click` opens beside.
- The title-bar search box names Find File and Find in Files and shortens its label on narrow windows.
- The find dialog (Files · In Files · Commands · Symbols) has a **✕** at the right of its tab row. ✕, `Esc` (now
  also from the mask / exclude boxes), a click outside and — in Find in Files — `Ctrl+Shift+F` again close it and
  give the keyboard back to the editor.
- **Find in Files searches the sources, not the build output and noise**:
  - **Defaults** toggle (on): the folders from Settings (build, dist, target, out, bin, obj, coverage …), `.idea`
    (with IntelliJ's shelf, `.idea/shelf/…/shelved.patch`), `.vs`, minified / bundled js and css, source maps
    (`*.map`), TypeScript build info (`*.tsbuildinfo`), lock files and `shelved.patch` files elsewhere are left out. Off: they are searched too. Hidden names
    from Settings and binary files always stay out; `.gitignore` rules count when **Hide .gitignore'd Files** is on
    (Settings or the Preferences menu).
  - **exclude** box next to the file mask (placeholder `.idea/**, *.patch, dist/**`): comma-separated globs,
    matched at any depth like VS Code's — `.idea/**` also inside each project of a folder holding several; a
    leading `/` starts at the open folder (`/web/dist`). `!pattern` in the file mask excludes as well
    (`*.java, !*Test.java`). Patterns that could leave the folder or read as a ripgrep option (`..`, drive letters,
    a leading `-`) are refused.
  - The option row wraps on narrow windows, so the mask, exclude box and Defaults stay visible.
  - **⊘ folder** on a result file (on hover) adds that folder (`/path/**`) to the excludes and searches again.
  - Both are kept between runs and also apply to Replace in Files. Find File (`Ctrl+P`) keeps the folder rules it
    already shared with search but not the file patterns, so `package-lock.json` or a `.map` can still be opened by
    name.

### Toolbar and Git

- Git toolbar group follows the active file's repository: branch, ahead / behind and **Pull** (`git fetch` +
  fast-forward merge, with a confirmation; the one git write ReadO runs). Commit / Push hand the request to AgentO.
- **Get the latest sources without AgentO**: Pull, Fetch and branch checkout run in ReadO.
  - Pull (fast-forward only) from the toolbar, the Git window, the branch popup or the Git menu. When it cannot
    fast-forward, local changes are in the way, credentials are missing or a merge / rebase is in progress, a dialog
    says why with git's message (nothing is merged, rebased, forced or discarded) and offers Stash (AgentO) / Console.
  - Fetch (`git fetch --prune`) shows the new ↑ahead ↓behind.
  - Clicking the toolbar branch chip opens the branch popup (right-click: Log): current branch with ↑↓, a filter box,
    Local and Remote branches; picking one checks it out — a remote-only branch through a new local tracking branch.
    Unsaved edits are saved first or the checkout is cancelled; when git refuses because of local changes its message
    is shown with a stash hint.
  - Afterwards the file tree, open files (unedited ones re-read, edited ones kept and flagged, deleted ones marked),
    the symbol index, the Git window and the status bar show the new sources.
- **Line-ending-only changes are passed over**: files whose only difference from HEAD is CRLF ↔ LF are hidden in
  Local Changes, the counts and the tree colours (toggle **Show line-ending-only changes**). Diffs have **Ignore line
  endings** (on by default; off draws CR as ␍) and name differing line endings in the header. When such a file blocks
  a pull or checkout, the dialog says so and how to clear it — ReadO changes neither the file nor `core.autocrlf` /
  `.gitattributes`.
- **Changelists in Local Changes** (as in IntelliJ): the changes are grouped by changelist — the default **Changes**
  plus lists you make (right-click → **New Changelist…**, name + description; **Edit Changelist…**, **Delete
  Changelist** (its files go back to Changes; Changes itself stays), **Set Active Changelist** — new changes go to the
  active list). Move files with **Move to Changelist…** or by dragging them onto a list; Ctrl / Shift + click selects
  several. Untracked files can be filed in a list too. A list's checkbox ticks all of it; **Commit… / Rollback…
  (AgentO)** on a list hand just its files to AgentO, the list's name and description as the message draft. With one
  list the window looks as before. The lists live in `%APPDATA%\ReadO\changelists.json` per repository; git, the index
  and the files are never touched, and committed or rolled-back files drop out by themselves.
- The breadcrumb shows the repository folder as a chip; the settings gear moved to the bottom of the tool strip.
- Fixed: the Git icon on the tool strip did nothing when the open folder holds repositories but is not one itself;
  it now opens the Git tool window like the Git menu.
- Fixed: the commit message under Log / History could not be selected, copied or searched in the desktop app
  (its WebView turns text selection off page-wide). It now selects with the mouse, copies with `Ctrl+C`, and has a
  right-click menu (Copy · Copy Commit Message · Copy Revision Number · Select All · Find…) and a `Ctrl+F` find bar
  that highlights matches and follows the selected commit. The same for the Console (which no longer redraws, and
  drops the selection, every 2 seconds) and the diff headers (Copy Path / Revision / Description); Blame and Stash
  menus gain Copy Commit Message / Copy Message. The Log text filter already searched message bodies (`git log --grep`).

### Editor

- No more false red squiggles in TypeScript / JavaScript: Monaco's checker sees one file without the project
  (tsconfig, `node_modules`, `@/` paths), so its diagnostics are off. Settings → **Show language diagnostics** turns
  them back on.

### Markdown

- Fenced code blocks in the preview are highlighted (` ```js `, ` ```python `, ` ```sql ` … — any language the
  editor knows, by name, alias or file extension), in the editor's colours for the light and dark theme.
- Relative images (`![](img/shot.png)`, `<img src="../logo.png">`) show in the preview. They are served only from the
  open folder (or a file opened from outside it); a path that climbs out of it shows no image.
- A relative link that climbs out of the open folder is ignored instead of opening a file at the folder root.
- The preview's HTML clean-up is unchanged: only a small list of tags and attributes is kept, no scripts, styles,
  frames, SVG or remote images.

### Start-up

- Fixed: ReadO could hang at start without ever showing its window, using CPU in the background (seen when it was
  launched several times within a minute). Likely cause: a WMI query from Python's `platform` module (asked by
  pywebview on every start) that never got an answer. ReadO now makes no WMI queries; `platform` uses its non-WMI
  fallback.
- If the window still has not appeared after 20 seconds, ReadO writes `%APPDATA%\ReadO\startup.log` (what it was
  doing, every thread's stack) and exits instead of hanging invisibly.
- A second launch no longer hands its files to an instance that never showed a window: it waits for that instance's
  window (up to 25 seconds), then ends it (only that ReadO process — it has no unsaved edits) and starts on its own.
- When a second launch (or AgentO's **Open in ReadO**) hands a file to the running window, a maximized window stays
  maximized: only a minimized window is restored before it comes to the front.

### Tests

- The headless editor suite is in the repository: `python tests/verify_editor.py`.
- `python tests/exe_startup.py dist\reado.exe`: the start-up watchdog and the second launch past a stuck instance,
  on the built exe.

### Development

- `source.html` and `server.py` are split by feature, with no change in behaviour: the page's style and script live
  in `ui/*.css` / `ui/*.js` (put back in place when the page is served, so the browser gets the same single page),
  the server's feature blocks in `srv_search.py`, `srv_goto.py`, `srv_links.py`, `srv_tags.py`, `srv_fileops.py`.
  Dead code left from the old search panel is gone.
- `python scripts/build_test.py` builds `dist-next` and runs every automated suite, one at a time;
  `python scripts/swap_dist.py` puts a tested build into `dist` (old one to `dist-prev`, SHA256 checked) — a dry run
  unless `--apply`; a running ReadO only gets a normal close, and unsaved edits stop the swap. Steps:
  `docs/RELEASE.md`.

---

<a id="v010"></a>

## 0.1.0 — first release

The first tagged version: a standalone Windows source viewer and editor (`dist\reado.exe`, one file, works offline).

### Editor

- Edit and save text files in place (`Ctrl+S`, save all, unsaved-change prompts, encodings and line endings kept,
  reopen with another encoding), external changes detected and reloaded.
- Find in files with replace preview, Quick Open (`Ctrl+P`), command palette (`Ctrl+Shift+P`) on one command registry
  shared by menus, toolbar and palette; keymap presets **VS Code** and **IntelliJ IDEA**.
- File operations in the tree: new file / folder, rename, delete to the Recycle Bin, copy path, reveal in Explorer;
  optional `.gitignore` filter; file-type badges.
- Diff side by side: with the saved file, with git HEAD, or with another file; changed lines against HEAD in the gutter.

### Navigation

- Jump to components and definitions (ctags index, `F12` / `Ctrl+click`, links on hover without `Ctrl`): imports,
  aliases (`@/`, tsconfig / vite paths), members, across JS/TS/Vue, Java, Python, Go, C/C++, PHP, Rust, C#, Ruby.
- Usage count on declarations, back / forward history.

### Layout and window

- Split panes (up to 4, presets, tab drag between panes, a definition opens in the opposite pane).
- Tool window strip on the left (Files, Outline, Git; `Alt+1` / `Alt+2`), folding sidebar, state kept in `state.json`.
- Own title bar with menus and native behaviour (snap, Win+arrows, resize edges); the window background follows the
  theme. Fixed: a white window when maximizing, and when moving a maximized window to another monitor. Fixed: the page
  could scroll as a whole under a tall Git panel.
- Dark and light themes, toolbar grouped with an overflow menu for narrow windows.

### Git views (read-only)

- Git tool window: Local Changes, Log (graph, filters, columns, multiple selection, commit details), History, Stash,
  Console; blame in the editor; diff windows. Write actions are handed to AgentO, never run by ReadO.

### Performance and security

- Local server bound to `127.0.0.1` with CSRF-guarded write APIs and path checks; git runs with hooks and external
  tools disabled.
- Background file index, ripgrep search, cached link resolution; 3rd-party assets vendored for offline use.
