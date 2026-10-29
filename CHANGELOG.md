# ReadO — Changelog

<input type="radio" name="xall" id="xo" checked style="display:none">
<input type="radio" name="xall" id="xc" style="display:none">
<style>
/* ═══ 1. 제목 위계 ═══════════════════════════════════════
   좌측 막대는 h2 전용. 챕터(h1)는 옅은 밴드 + 번호 배지(.num), 소제목(h3)은 옅은 배지(.n3), 문서 제목은 밑줄.
   <a id> 앵커는 <p>로 감싸져 "a + h1" 이 안 걸리므로 :first-of-type 로 구분. */
h1 { font-size: 1.3em; font-weight: 800; color: #2f3640; background: #eef1f4;
     border-radius: 6px; padding: 9px 13px 9px 10px; margin: 2.2em 0 1em }
/* 챕터 번호 배지 — 제목 앞 <span class="num">N</span> (부록은 A) */
.num { display: inline-block; min-width: 1.55em; text-align: center; background: #3f4650; color: #fff;
       border-radius: 6px; padding: 2px 8px; margin-right: 10px; font-size: .9em; line-height: 1.35; vertical-align: 2px }
h1:first-of-type { font-size: 1.5em; color: #212529; background: none; border-radius: 0;
     border-bottom: 3px solid #343a40; padding: 0 0 7px; margin: 1.8em 0 .8em }
h2 { font-size: 1.2em; font-weight: 700; color: #343a40;
     border-left: 6px solid #343a40; padding: 2px 0 2px 11px; margin: 1.5em 0 .6em }
h2:first-of-type { border-left: 0; padding-left: 0 }                          /* 목차 */
details h2:first-of-type { border-left: 6px solid #343a40; padding-left: 11px } /* 부록 A.1 */
h3 { font-size: 1.02em; font-weight: 700; color: #343a40; margin: 1.9em 0 .8em }   /* 항목 안 단락 경계 — 막대 없이 번호 배지로 */
.n3 { display: inline-block; background: #f1f3f5; color: #5b6168; border: 1px solid #dfe3e7;   /* 소제목 배지 N.M.k — 항목 배지보다 한 단 옅게 */
      border-radius: 4px; padding: 0 6px; margin-right: 8px; font-size: .82em; font-weight: 800; vertical-align: 1px }
/* 본문 문단 간격 — 소제목→문단(.8em)보다 문단↔문단(.5em)이 작아야 "소제목이 문단을 거느린다"로 읽힌다. 넓으면 빈 줄이 들어간 듯 보인다(실제 지적) */
.ib p { margin: .3em 0 .5em }
h4 { font-size: .96em; font-weight: 700; color: #6c757d; margin: 1.5em 0 .5em }
h4::before { content: "▸ "; color: #adb5bd }
/* 제목 줄 우측 컨트롤 (float 이라 .hctl 이 든 heading 에만 걸린다) */
.hctl { float: right; font-weight: 400; white-space: nowrap; margin-left: 14px }
h1 .hctl { font-size: .6em; padding-top: .35em }
h1 .hctl a { color: #0969da }
h2 .hctl { font-size: .72em; padding-top: .18em }
/* 부록 헤더(summary.apx) — 챕터 밴드와 같은 모양, 펼침 삼각형 없이 */
summary.apx { list-style: none; cursor: pointer; font-size: 1.3em; font-weight: 800; color: #2f3640;
     background: #eef1f4; border-radius: 6px; padding: 9px 13px 9px 10px; margin: 2.2em 0 1em }
summary.apx::-webkit-details-marker { display: none }  summary.apx::marker { content: "" }
summary.apx .hctl { font-size: .6em; padding-top: .35em }
summary.apx .hctl a { color: #0969da }
/* ═══ 2. 접히는 항목(.it) — 체크박스 방식 ══════════════════
   native details 는 닫힌 내용을 shadow slot에서 숨겨 CSS로 못 되살린다
   → '전체 접기' 뒤 개별 펼치기가 불가. 그래서 체크박스로 상태를 직접 가진다.
   (CSS 주석에 꺾쇠 태그 리터럴을 쓰지 말 것 — 태그 균형 검사에 잡힌다)
   모드별 체크박스 2개(.ca 펼침모드 / .cb 접기모드) → 모드 전환 시 반전 없음.
   ★ .it 는 라디오의 직계 형제 → 모든 규칙에 "~ .it" 와 "~ * .it" 를 함께 쓴다. */
.it { margin: 1.1em 0 1.5em }
.it + .it { border-top: 1px dashed #e3e7ea; padding-top: .9em }   /* 항목 "사이"에만 점선 → 마지막 항목엔 선 없음 */
.it > .ib { padding-left: 14px }                                    /* 본문 들여쓰기 — 헤더와 왼쪽 선이 같으면 소속이 안 보임 */
.it > .ih { display: block; font-size: 1.02em; font-weight: 700; color: #2f3640;
     padding: 4px 0; margin-bottom: .9em; cursor: pointer; user-select: none }
.it > .ih:hover { color: #0969da }
.it > .ih::after { content: "▼"; float: right; color: #adb5bd; font-size: .85em; padding-top: 2px }  /* 펼침 표시 = 우측 */
.ih .n { display: inline-block; background: #e9edf1; color: #3f4650; border-radius: 5px;             /* 옅은 번호 배지 */
         padding: 1px 7px; margin-right: 9px; font-size: .86em; font-weight: 800; vertical-align: 1px }
.ih .sub { color: #6c757d; font-weight: 500; margin-left: 6px; font-size: .92em }                    /* 회색 부제 */
/* 모드에 맞는 라벨 하나만 */
#xo:checked ~ .it > .lb, #xo:checked ~ * .it > .lb,
#xc:checked ~ .it > .la, #xc:checked ~ * .it > .la { display: none }
/* 펼침 모드: 체크 = 사용자가 닫음 */
#xo:checked ~ .it > .ca:checked ~ .ib,        #xo:checked ~ * .it > .ca:checked ~ .ib { display: none }
#xo:checked ~ .it > .ca:checked ~ .la::after,  #xo:checked ~ * .it > .ca:checked ~ .la::after  { content: "▶" }
/* 접기 모드: 체크 = 사용자가 열음 */
#xc:checked ~ .it > .cb:not(:checked) ~ .ib,        #xc:checked ~ * .it > .cb:not(:checked) ~ .ib { display: none }
#xc:checked ~ .it > .cb:not(:checked) ~ .lb::after,  #xc:checked ~ * .it > .cb:not(:checked) ~ .lb::after  { content: "▶" }
/* 목차의 전체 펼치기/접기 라벨 — 현재 모드를 굵게 */
#xo:checked ~ * label[for="xo"], #xc:checked ~ * label[for="xc"] { font-weight: 700 }
/* ═══ 3. 콜아웃 — 막대 없이 둥근 박스 + 라벨 ═════════════════ */
blockquote, .warn, .tip { border: 1px solid; border-radius: 7px;
     margin: .9em 0 1.4em; padding: 9px 12px; color: #333 }
blockquote { border-color: #cfe2f7; background: #f5f9fe }
blockquote > p:first-child { margin-top: 0 }  blockquote > p:last-child { margin-bottom: 0 }
h1 + blockquote, h2 + blockquote, h3 + blockquote { border: 0; background: none; border-radius: 0;   /* 제목 직후 > = 도입문(박스 아님) */
     padding: 0 0 0 2px; margin: -.2em 0 1.3em; font-size: 1.02em; color: #5b6168 }
.warn { border-color: #f0d9ac; background: #fffaf2 }
.warn::before { content: "⚠️ 주의"; display: inline-block; font-weight: 800; font-size: .82em;
     color: #a35d00; background: #fbeccc; border-radius: 20px; padding: 1px 9px; margin-right: 7px }
.tip { border-color: #b9e5c9; background: #f2fbf5 }
.tip::before { content: "💡 쉽게 말하면"; display: inline-block; font-weight: 800; font-size: .82em;
     color: #0b6b39; background: #d8f2e2; border-radius: 20px; padding: 1px 9px; margin-right: 7px }
/* ═══ 4. 표 · 코드 · 구분선 ════════════════════════════════
   표는 좁은 화면에서 표 안에서만 가로 스크롤. th 배경 없으면 본문 zebra보다 약해 보임. */
table { margin: .5em 0 1.5em !important; display: block; width: max-content;
        max-width: 100%; overflow-x: auto; border-collapse: collapse }
th, td { border: 1px solid #e4e7eb; padding: 6px 10px; text-align: left; vertical-align: top }
th { background: #e9edf1; color: #2f3640; font-weight: 700; text-align: center;   /* 배경으로 구분 → 테두리 없이 · 가운데 정렬 (실제 지적) */
     border: 0; white-space: nowrap }
pre { margin: .6em 0 1.5em !important; overflow-x: auto }
code { background: #f1f3f5; padding: 1px 5px; border-radius: 3px; font-size: .92em }
.cap { font-size: .86em; color: #868e96; margin: .3em 0 1.5em; padding-left: 2px }
table + .cap, pre + .cap { margin-top: -1.1em }        /* 표·코드 아래 캡션만 붙인다 — 도표 뒤에 음수면 겹친다(실제 사례) */
div[style*="Noto Sans KR"] { margin: .7em 0 1.5em }      /* 카드 흐름도 컨테이너 하단 여백 */
ul, ol { margin: .6em 0 1em }
hr { border: 0; margin: 2.2em 0 }   /* 선 없이 여백만 — 챕터 구분은 h1 밴드가 함 */
/* ═══ 5. 흐름 카드 — nowrap + 가로 스크롤 (wrap이면 좁은 화면에서 세로로 쌓임) ═══ */
.lay { display: flex; flex-wrap: nowrap; gap: 8px; margin: .7em 0 1.6em;
       align-items: stretch; overflow-x: auto; padding-bottom: 6px }
.cd { flex: 0 0 200px; border: 1px solid #e4e7eb; border-top-width: 4px; border-radius: 7px;
      padding: 8px 10px; background: #fff; font-size: 12px; line-height: 1.5 }
.cd > b { display: block; font-size: 12.5px; margin-bottom: 2px }
.cd .k { font-family: ui-monospace, Consolas, monospace; font-size: 11px; color: #495057 }
.cd .s { display: block; margin-top: 4px; color: #6c757d; font-size: 11px }
.ar { align-self: center; color: #adb5bd; font-weight: 800; font-size: 16px; flex: 0 0 auto }
.tg { display: inline-block; font-size: 10.5px; font-weight: 700; border-radius: 20px;
      padding: 1px 8px; margin-right: 4px }
</style>

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

### Theme

- **Light, Dark or System** (the shared xO scheme). System is the default and follows the Windows setting as soon as
  it changes. The toolbar button shows the current mode (icon + name) and steps Light → Dark → System; the View menu
  has **Theme › Light / Dark / System**. A theme chosen before stays as it was.
- The saved mode is applied before the page first paints, and the window behind it (main window and diff windows)
  takes the matching colour, so there is no white flash in the dark theme — also in System mode.

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
