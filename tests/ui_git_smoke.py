"""
Browser smoke test of the Git tool window (Playwright, headless Chromium).

    python tests/ui_git_smoke.py <fixture dir from git_fixture.py> [<screenshot dir>]

Starts the ReadO server on a free port with the fixture folder open (config and
state in a temp folder, so the user's ReadO settings are not touched), then
drives the page: tool window, Local Changes, Log (graph, filters, paging,
details), History, Stash, Console, blame, AgentO dialog, tree colours, keymaps.
"""
import os
import re
import sys
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import server  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

FAILS = []


def check(cond, what):
    print(("  ok   " if cond else "  FAIL ") + what)
    if not cond:
        FAILS.append(what)


def strip_git_click(pg, where):
    """The Git icon at the bottom of the left tool strip: a real click opens and
    closes the tool window, like Git → Git Tool Window (same command, same state)."""
    btn = "#toolStrip .tsb[data-tool=git]"
    pg.wait_for_function("_gitAvail !== null", timeout=10000)  # /api/git/info answered (refreshGitAvail)
    check(pg.evaluate(f"(() => {{ const b = document.querySelector('{btn}'); return !b.disabled && !b.classList.contains('dim'); }})()"),
          f"{where}: strip Git icon enabled")
    if pg.evaluate("!!(STATE.git && STATE.git.open)"):
        pg.evaluate("GitUI.toggleWindow(false)")
    pg.click(btn)
    pg.wait_for_selector("#gitWin.show", timeout=5000)
    check(pg.evaluate(f"STATE.git.open && document.querySelector('{btn}').classList.contains('active') && CMD.get('git.toolwin').checked()"),
          f"{where}: strip Git click opens the tool window (icon active, menu item checked)")
    pg.click(btn)
    pg.wait_for_function("!document.querySelector('#gitWin').classList.contains('show')", timeout=5000)
    check(pg.evaluate(f"!STATE.git.open && !document.querySelector('{btn}').classList.contains('active') && !CMD.get('git.toolwin').checked()"),
          f"{where}: strip Git click again closes it")
    pg.evaluate("runCommand('git.toolwin')")
    check(pg.evaluate(f"STATE.git.open && document.querySelector('{btn}').classList.contains('active')"), f"{where}: menu command → strip icon active")
    pg.evaluate("runCommand('git.toolwin')")
    check(pg.evaluate(f"!STATE.git.open && !document.querySelector('{btn}').classList.contains('active')"), f"{where}: menu command again → icon inactive")


def _g(cwd, *args):
    import subprocess
    r = subprocess.run(["git", "-c", "user.name=T", "-c", "user.email=t@example.com", "-c", "init.defaultBranch=main",
                        "-c", "core.autocrlf=false"] + list(args), cwd=cwd, capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(f"git {' '.join(args)}: {r.stderr}")
    return r.stdout.strip()


def _put(cwd, name, text):
    with open(os.path.join(cwd, name), "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def checkout_ui_tests(pg, ev, shot, toast, A, UP):
    """Branch popup (toolbar chip / Git window), checkout of local + remote-only branches, Fetch, Pull in the Git window."""
    branch = lambda: _g(A, "rev-parse", "--abbrev-ref", "HEAD")
    dlg_title = lambda: ev("document.getElementById('dlgTitle').textContent")
    _g(A, "config", "core.autocrlf", "false")  # ReadO's git and _g() write the same line endings
    _g(UP, "checkout", "-q", "-b", "featx")
    _put(UP, "feature.txt", "feature\n")
    _put(UP, "f.txt", "feature edit\n")
    _g(UP, "add", "-A"); _g(UP, "commit", "-q", "-m", "feature x"); _g(UP, "push", "-q", "origin", "featx")
    _g(UP, "checkout", "-q", "main")

    print("== Git window: Fetch")
    ev("GitUI.toggleWindow(true)")
    pg.wait_for_function("!!document.querySelector('#gitWin [data-a=fetch]')", timeout=5000)
    pg.click("#gitWin [data-a=fetch]")
    pg.wait_for_function("document.getElementById('toast').textContent.startsWith('fetched')", timeout=20000)
    check("refs/remotes/origin/featx" in _g(A, "for-each-ref", "--format=%(refname)", "refs/remotes") and branch() == "topic",
          f"Fetch: new remote branch known, working tree untouched ({toast()})")

    print("== toolbar: branch popup")
    ev("openFile('my-repo/f.txt')")
    pg.wait_for_function("document.querySelector('#gtbBranch .nm').textContent === 'topic'", timeout=10000)
    pg.click("#gtbBranch")
    pg.wait_for_selector("#gitPick .it", timeout=8000)
    pop = ev("""(() => { const p = document.getElementById('gitPick');
      return {hd: [...p.querySelectorAll('.hd')].map(x => x.textContent), it: [...p.querySelectorAll('.it')].map(x => x.textContent),
              cur: (p.querySelector('.it.cur .nm') || {}).textContent, q: !!p.querySelector('input.q')}; })()""")
    check(pop["hd"][0].startswith("Current: topic (no upstream)") and "Local" in pop["hd"] and "Remote" in pop["hd"] and pop["q"],
          f"popup: current branch, Local / Remote, filter box ({pop['hd']})")
    check(pop["cur"] == "topic" and any(t.startswith("main") for t in pop["it"]) and any(t.startswith("origin/featx") and "new local branch" in t for t in pop["it"])
          and any(t.startswith("origin/main") and "local main" in t for t in pop["it"]),
          "popup: current marked, remote branches say which local branch tracks them")
    check(any(t.startswith("Pull") for t in pop["it"]) and any(t.startswith("Fetch") for t in pop["it"]), "popup: Pull and Fetch")
    shot("t4-branch-popup")
    pg.fill("#gitPick input.q", "featx")
    its = ev("[...document.querySelectorAll('#gitPick .it')].map(x => x.textContent)")
    check(len(its) == 1 and its[0].startswith("origin/featx"), f"filter: only origin/featx ({its})")

    print("== checkout: remote-only branch")
    pg.click("#gitPick .it")
    pg.wait_for_function("document.getElementById('toast').textContent.startsWith('switched to featx')", timeout=20000)
    check(branch() == "featx" and _g(A, "rev-parse", "--abbrev-ref", "featx@{upstream}") == "origin/featx",
          f"remote branch: local featx tracking origin/featx ({toast()})")
    pg.wait_for_function("document.querySelector('#gtbBranch .nm').textContent === 'featx'", timeout=10000)
    pg.wait_for_function("!!document.querySelector('#tree .node[data-path=\"my-repo/feature.txt\"]')", timeout=10000)
    pg.wait_for_function("monaco.editor.getModels().some(m => m.uri.path.endsWith('my-repo/f.txt') && m.getValue() === 'feature edit\\n')", timeout=10000)
    pg.wait_for_function("document.getElementById('sbBranch').textContent.includes('featx')", timeout=10000)
    pg.wait_for_function("document.querySelector('#gitWin [data-a=branch] .nm').textContent.startsWith('featx')", timeout=10000)
    check(True, "after checkout: chip, status bar, tree (new file) and the open file show the branch")
    shot("t5-checked-out")

    print("== checkout: local branch, deleted file tab")
    ev("openFile('my-repo/feature.txt')")
    pg.wait_for_function("docs.has('my-repo/feature.txt')", timeout=10000)
    pg.click("#gtbBranch")
    pg.wait_for_selector("#gitPick .it", timeout=8000)
    pg.fill("#gitPick input.q", "main")
    pg.click("#gitPick .it:has(.nm:text-is('main'))")
    pg.wait_for_function("document.getElementById('toast').textContent.startsWith('switched to main') || document.getElementById('toast').textContent.startsWith('deleted on disk')", timeout=20000)
    check(branch() == "main", f"local branch: on main ({toast()})")
    pg.wait_for_function("docs.get('my-repo/feature.txt') && docs.get('my-repo/feature.txt').gone", timeout=10000)
    pg.wait_for_function("!document.querySelector('#tree .node[data-path=\"my-repo/feature.txt\"]')", timeout=10000)
    check(True, "file not on main: its tab is marked deleted, tree entry gone")

    print("== checkout: unsaved edits / local changes")
    ev("openFile('my-repo/f.txt')")
    pg.wait_for_function("currentPath === 'my-repo/f.txt'", timeout=10000)
    ev("currentDoc().model.setValue('unsaved edit\\n')")
    pg.wait_for_function("currentDoc().dirty", timeout=5000)
    pg.click("#gtbBranch")
    pg.wait_for_selector("#gitPick .it", timeout=8000)
    pg.fill("#gitPick input.q", "featx")
    pg.click("#gitPick .it:has(.nm:text-is('featx'))")
    pg.wait_for_function("document.getElementById('dlgTitle').textContent.startsWith('Unsaved edits')", timeout=10000)
    check("my-repo/f.txt" in ev("document.getElementById('dlgMsg').textContent"), "unsaved edits: warned before the checkout, file named")
    pg.click("#dlgBtns button:has-text('cancel')")
    time.sleep(0.5)
    check(branch() == "main" and ev("currentDoc().dirty"), "cancel: no checkout, edit kept")
    pg.click("#gtbBranch")
    pg.wait_for_selector("#gitPick .it", timeout=8000)
    pg.fill("#gitPick input.q", "featx")
    pg.click("#gitPick .it:has(.nm:text-is('featx'))")
    pg.wait_for_function("document.getElementById('dlgTitle').textContent.startsWith('Unsaved edits')", timeout=10000)
    pg.click("#dlgBtns button.primary")
    pg.wait_for_function("document.getElementById('dlgTitle').textContent.startsWith('Checkout of featx refused')", timeout=20000)
    msg = ev("document.getElementById('dlgMsg').textContent")
    with open(os.path.join(A, "f.txt"), encoding="utf-8") as f:
        kept = f.read() == "unsaved edit\n"
    check("would be overwritten" in msg and "stash" in msg.lower() and branch() == "main" and kept,
          f"saved, then git refuses: its message + stash hint shown, nothing forced ({msg[:80]})")
    check("Stash Changes… (AgentO)" in ev("document.getElementById('dlgBtns').textContent"), "refused checkout: Stash (AgentO) offered")
    shot("t6-checkout-refused")
    pg.click("#dlgBtns button.primary")
    _g(A, "checkout", "-q", "--", "f.txt")

    print("== Git window: branch button, Pull")
    pg.wait_for_function("(document.querySelector('#gitWin [data-a=branch] .nm') || {}).textContent.startsWith('main')", timeout=15000)
    pg.click("#gitWin [data-a=branch]")
    pg.wait_for_selector("#gitPick .it", timeout=8000)
    check(ev("document.querySelector('#gitPick .hd').textContent").startswith("Current: main → origin/main"), "Git window: branch popup for its repository")
    pg.keyboard.press("Escape")
    pg.click("#gitWin [data-a=pull]")
    pg.wait_for_function("document.getElementById('dlgTitle').textContent === 'Pull main'", timeout=10000)
    pg.click("#dlgBtns button.primary")
    pg.wait_for_function("document.getElementById('toast').textContent === 'pull: already up to date'", timeout=20000)
    check(True, "Git window Pull: already up to date")
    ev("GitUI.toggleWindow(false)")
    _g(A, "checkout", "-q", "topic")


def eol_ui_tests(pg, ev, shot, toast, base):
    """Line-ending-only changes: hidden in Local Changes (toggle), diff "Ignore line endings", pull / checkout
    messages, and the editor keeping a file's CRLF / LF when saving."""
    rb = os.path.join(base, "eolremote.git")
    _g(base, "init", "-q", "--bare", "eolremote.git")
    up = os.path.join(base, "eolup")
    _g(base, "clone", "-q", rb, "eolup")
    for name in ("lf.txt", "real.txt", "touched.txt"):
        _put(up, name, "one\ntwo\n")
    _put(up, "crlf.txt", "one\r\ntwo\r\n")
    _put(up, "mixed.txt", "one\r\ntwo\nthree\r\n")
    _g(up, "add", "-A"); _g(up, "commit", "-q", "-m", "first"); _g(up, "push", "-q", "origin", "HEAD:main")
    _g(base, "clone", "-q", "-c", "core.autocrlf=false", "-b", "main", rb, "eolrepo")
    E = os.path.join(base, "eolrepo")
    crlf = lambda name, text: open(os.path.join(E, name), "wb").write(text.replace("\n", "\r\n").encode())
    crlf("lf.txt", "one\ntwo\n"); crlf("touched.txt", "one\ntwo\n"); crlf("real.txt", "one\nchanged\n")
    root = os.path.realpath(E).replace("\\", "/")
    rows = lambda: ev("[...document.querySelectorAll('#gitWin [data-page=changes] .gt-row[data-id^=\"changes|\"]')].map(r => r.dataset.id.slice(8) + (r.classList.contains('k-eol') ? ':eol' : ''))")
    SUM = "document.querySelector('#gitWin [data-page=changes] .gw-bar .sum').textContent"

    print("== line endings: Local Changes")
    ev(f"GitUI.toggleWindow(true); GitUI.selectRepo({root!r}).then(() => GitUI.setTab('changes'))")
    pg.wait_for_function(SUM + ".includes('line-ending-only hidden')", timeout=20000)
    check(rows() == ["real.txt"] and ev(SUM).startswith("1 file · 2 line-ending-only hidden"),
          f"CRLF-only files hidden, counted apart ({rows()} | {ev(SUM)[:50]})")
    btn = "#gitWin [data-page=changes] [data-a=eol]"
    check(ev(f"document.querySelector('{btn}').textContent") == "Show line-ending-only changes", "toggle: Show line-ending-only changes")
    shot("t7-eol-hidden")
    pg.click(btn)
    pg.wait_for_function(SUM + ".includes('line-ending-only shown')", timeout=5000)
    r = rows()
    check(sorted(r) == ["lf.txt:eol", "real.txt", "touched.txt:eol"] and ev("GitUI.S.showEol") is True,
          f"toggle on: shown dimmed, setting kept ({r})")
    check("line endings only" in ev("document.querySelector('#gitWin [data-page=changes] .gt-row[data-id=\"changes|lf.txt\"]').textContent"),
          "row tagged 'line endings only'")

    print("== line endings: diff")
    pg.click("#gitWin [data-page=changes] .gt-row[data-id=\"changes|lf.txt\"]")
    pg.wait_for_function("(document.querySelector('#gitWin .lc-diff .gdm-sub') || {}).textContent.includes('line endings LF → CRLF')", timeout=10000)
    time.sleep(0.6)
    pane = "#gitWin .lc-diff"
    lc = "(() => { const v = GitUI.DV.find(x => x.bg.closest('.lc-diff')); return v && v.ed ? (v.ed.getLineChanges() || []).length : -1; })()"
    n_on = ev(lc)
    check(ev(f"document.querySelector('{pane} [data-a=eol]').textContent") == "Ignore line endings" and ev("GitUI.S.ignoreEol") is True and n_on == 0,
          f"diff: Ignore line endings on by default, no changed lines, header names LF → CRLF ({n_on})")
    pg.click(f"{pane} [data-a=eol]")
    pg.wait_for_function(lc + " > 0", timeout=10000)
    check(ev(f"document.querySelector('{pane} [data-a=eol]').textContent") == "Show line endings" and ev("GitUI.S.ignoreEol") is False
          and "␍" in ev("GitUI.DV.find(x => x.bg.closest('.lc-diff')).ed.getModel().modified.getValue()"),
          "off: CR drawn as ␍, the lines show as changed, setting kept")
    shot("t8-eol-shown")
    pg.click(f"{pane} [data-a=eol]")
    pg.wait_for_function("GitUI.S.ignoreEol === true", timeout=5000)
    pg.click(btn)
    pg.wait_for_function(SUM + ".includes('line-ending-only hidden')", timeout=5000)

    print("== line endings: pull / checkout messages")
    _put(up, "touched.txt", "one\ntwo\nthree\n"); _g(up, "commit", "-q", "-am", "remote"); _g(up, "push", "-q", "origin", "HEAD:main")
    head = _g(E, "rev-parse", "HEAD")
    ev("document.getElementById('dlgTitle').textContent = ''")
    pg.click("#gitWin [data-a=pull]")
    pg.wait_for_function("document.getElementById('dlgTitle').textContent === 'Pull main'", timeout=10000)
    msg = ev("document.getElementById('dlgMsg').textContent")
    check("eolrepo" in msg and "2 only in line endings" in msg, f"pull confirmation counts eol-only changes apart ({msg[-80:]!r})")
    ev("document.getElementById('dlgTitle').textContent = ''")
    pg.click("#dlgBtns button.primary")
    pg.wait_for_function("document.getElementById('dlgTitle').textContent.startsWith('Pull stopped')", timeout=20000)
    msg = ev("document.getElementById('dlgMsg').textContent")
    with open(os.path.join(E, "touched.txt"), "rb") as f:
        kept = f.read() == b"one\r\ntwo\r\n"
    check("only in line endings" in msg and "touched.txt" in msg and "core.autocrlf (here: false)" in msg and "does not restore" in msg
          and _g(E, "rev-parse", "HEAD") == head and kept and _g(E, "config", "--get", "core.autocrlf") == "false",
          f"pull refused: says the file in the way differs only in line endings, how to fix; nothing changed ({msg[:60]})")
    shot("t9-eol-pull")
    pg.click("#dlgBtns button.primary")
    _g(E, "fetch", "-q"); _g(E, "branch", "-q", "other", "origin/main")
    pg.click("#gitWin [data-a=branch]")
    pg.wait_for_selector("#gitPick .it", timeout=8000)
    pg.fill("#gitPick input.q", "other")
    ev("document.getElementById('dlgTitle').textContent = ''")
    pg.click("#gitPick .it:has(.nm:text-is('other'))")
    pg.wait_for_function("document.getElementById('dlgTitle').textContent.startsWith('Checkout of other refused')", timeout=20000)
    msg = ev("document.getElementById('dlgMsg').textContent")
    check("only in line endings" in msg and "touched.txt" in msg and _g(E, "rev-parse", "--abbrev-ref", "HEAD") == "main",
          "checkout refused: the same line-ending explanation")
    pg.click("#dlgBtns button.primary")

    print("== editor: saving keeps the file's line endings")
    out = {}
    for name in ("crlf.txt", "lf.txt", "mixed.txt"):
        key = "eolrepo/" + name
        ev(f"openFile({key!r})")
        pg.wait_for_function(f"currentPath === {key!r}", timeout=10000)
        ev("(() => { const m = currentDoc().model; m.pushEditOperations([], [{ range: new monaco.Range(1, 1, 1, 1), text: 'x' }], () => null); })()")
        ev("saveDoc(currentDoc())")
        pg.wait_for_function("!currentDoc().dirty", timeout=10000)
        with open(os.path.join(E, name), "rb") as f:
            out[name] = f.read()
    check(out["crlf.txt"] == b"xone\r\ntwo\r\n", f"CRLF file saved with CRLF ({out['crlf.txt']!r})")
    check(out["lf.txt"] == b"xone\r\ntwo\r\n", f"file opened as CRLF (its disk form) saved as CRLF ({out['lf.txt']!r})")
    print(f"  info: mixed file saved as {out['mixed.txt']!r} (was b'one\\r\\ntwo\\nthree\\r\\n')")
    ev("GitUI.toggleWindow(false)")


def changelist_ui_tests(pg, ev, shot, toast, base):
    """Changelists in Local Changes: groups, New / Edit / Delete / Set Active, Move (menu, several files, drag and drop),
    Commit / Rollback of one list for AgentO; git itself untouched."""
    R = os.path.join(base, "clrepo")
    os.makedirs(R)
    _g(R, "init", "-q"); _g(R, "config", "core.autocrlf", "false")
    for n in ("a.txt", "b.txt", "c.txt", "d.txt"):
        _put(R, n, n + "\n")
    _g(R, "add", "-A"); _g(R, "commit", "-q", "-m", "first")
    _put(R, "a.txt", "A\n"); _put(R, "b.txt", "B\n"); _put(R, "u.txt", "untracked\n")
    root = os.path.realpath(R).replace("\\", "/")
    head, P = _g(R, "rev-parse", "HEAD"), "#gitWin [data-page=changes] "
    groups = lambda: ev(f"[...document.querySelectorAll('{P}.gt-row.group')].map(r => r.querySelector('.nm').textContent + (r.classList.contains('active') ? '*' : '') + ':' + r.querySelector('.cnt').textContent)")
    files = lambda: ev(f"[...document.querySelectorAll('{P}.gt-row:not(.group)[data-id*=\"|\"]')].filter(r => !r.dataset.id.includes('|d:')).map(r => r.dataset.id)")
    gid = lambda name: ev(f"(() => {{ const r = [...document.querySelectorAll('{P}.gt-row.group')].find(r => r.querySelector('.nm').textContent === {name!r}); return r && r.dataset.id; }})()")
    menu = lambda: ev("[...document.querySelectorAll('#ctxMenu .ctx-item')].map(i => i.dataset.label + (i.classList.contains('disabled') ? '-' : ''))")
    item = lambda label: pg.click(f"#ctxMenu .ctx-item[data-label={label!r}]")
    row = lambda i: f"{P}.gt-row[data-id={i!r}]"
    clip = lambda: ev("document.querySelector('.gx-bg textarea') ? document.querySelector('.gx-bg textarea').value : ''")

    print("== changelists: one list looks as before")
    ev(f"GitUI.toggleWindow(true); GitUI.selectRepo({root!r}).then(() => GitUI.setTab('changes'))")
    pg.wait_for_function(f"document.querySelector('{P}.gt-row[data-id=\"changes|a.txt\"]')", timeout=20000)
    check(groups() == ["Changes:2 files", "Unversioned Files:1 file"] and not ev(f"!!document.querySelector('{P}.tag.act')"),
          f"Changes + Unversioned Files, no 'active' tag ({groups()})")
    pg.click(row("g:changes"), button="right")
    m = menu()
    check(m[:3] == ["Commit… (AgentO)", "Rollback… (AgentO)", "Show Diff"] and "Move to Changelist…" in m and "New Changelist…" in m
          and "Edit Changelist…" in m and "Delete Changelist-" in m and "Set Active Changelist-" in m and m[-1] == "Refresh",
          f"group menu: Commit / Rollback / Show Diff / Move / New / Edit; Delete + Set Active greyed ({m})")

    print("== changelists: New Changelist")
    item("New Changelist…")
    pg.wait_for_selector(".gcl-dlg", timeout=5000)
    pg.fill(".gcl-dlg .nm", "Feature")
    pg.fill(".gcl-dlg .ds", "detail line")
    shot("t10-new-changelist")
    pg.click(".gcl-dlg [data-a=go]")
    pg.wait_for_function("!document.querySelector('.gcl-dlg')", timeout=5000)
    F = gid("Feature")
    check(F and F.startswith("g:cl:") and groups() == ["Changes*:2 files", "Feature:0 files", "Unversioned Files:1 file"],
          f"new empty list shown; Changes marked active ({groups()})")
    pg.click(row("g:changes"), button="right")
    item("New Changelist…")
    pg.fill(".gcl-dlg .nm", "feature")
    pg.click(".gcl-dlg [data-a=go]")
    pg.wait_for_function("document.querySelector('.gcl-dlg .err').textContent.includes('already exists')", timeout=5000)
    check(True, "duplicate name: the dialog says so and stays open")
    pg.keyboard.press("Escape")

    print("== changelists: move several files (menu), drag and drop")
    pg.click(row("changes|a.txt"))
    pg.click(row("changes|b.txt"), modifiers=["Control"])
    check(ev(f"document.querySelectorAll('{P}.gt-row.sel').length") == 2, "Ctrl+click: two files selected")
    pg.click(row("changes|b.txt"), button="right")
    item("Move to Changelist…")
    pg.wait_for_selector("#gitPick .it", timeout=5000)
    labels = ev("[...document.querySelectorAll('#gitPick .it .nm')].map(x => x.textContent)")
    check(labels == ["Changes", "Feature", "New Changelist…"], f"move picker: the lists + New Changelist… ({labels})")
    pg.click("#gitPick .it:has(.nm:text-is('Feature'))")
    cid = F[2:]
    pg.wait_for_function(f"document.querySelector('{P}.gt-row[data-id=\"{cid}|a.txt\"]') && document.querySelector('{P}.gt-row[data-id=\"{cid}|b.txt\"]')", timeout=5000)
    check(groups() == ["Changes*:0 files", "Feature:2 files", "Unversioned Files:1 file"], f"both files moved ({groups()})")
    pg.drag_and_drop(row("unversioned|u.txt"), row(F))
    pg.wait_for_function(f"document.querySelector('{P}.gt-row[data-id=\"{cid}|u.txt\"]')", timeout=5000)
    check(groups() == ["Changes*:0 files", "Feature:3 files"], f"untracked file dragged into Feature ({groups()})")

    print("== changelists: Set Active, new changes")
    pg.click(row(F), button="right")
    item("Set Active Changelist")
    pg.wait_for_function(f"document.querySelector('{P}.gt-row[data-id=\"{F}\"]').classList.contains('active')", timeout=5000)
    _put(R, "c.txt", "C\n")
    pg.click(P + "[data-a=refresh]")
    pg.wait_for_function(f"document.querySelector('{P}.gt-row[data-id=\"{cid}|c.txt\"]')", timeout=10000)
    check(groups()[1] == "Feature*:4 files", f"a newly changed file goes to the active list ({groups()})")
    shot("t11-changelists")

    print("== changelists: Commit / Rollback of one list (AgentO)")
    pg.click(row(F), button="right")
    item("Commit… (AgentO)")
    pg.wait_for_selector(".gx-bg textarea", timeout=5000)
    t = clip()
    check(all("- " + n in t for n in ("a.txt", "b.txt", "c.txt", "u.txt")) and "커밋 메시지(초안): Feature" in t and "본문(초안):\ndetail line" in t,
          f"Commit: the list's files, its name + description as the message draft ({t[-120:]!r})")
    pg.click(".gx-bg [data-a=cancel]")
    pg.click(row(F), button="right")
    item("Rollback… (AgentO)")
    pg.wait_for_selector(".gx-bg textarea", timeout=5000)
    t = clip()
    check("되돌려" in t and "- a.txt" in t and "확인을 받아" in t, "Rollback: the list's files, the usual confirm-first instruction")
    pg.click(".gx-bg [data-a=cancel]")
    pg.click(f"{row(F)} input[type=checkbox]")
    check(ev(f"[...document.querySelectorAll('{P}.gt-row[data-id^=\"{cid}|\"] input')].every(x => !x.checked)"), "list checkbox unticks the whole list")
    pg.click(f"{row(F)} input[type=checkbox]")

    print("== changelists: kept across a repository switch, Edit, Delete")
    ev("GitUI.selectRepo(GitUI.G.repos.find(r => !r.root.endsWith('/clrepo')).root).then(() => GitUI.setTab('changes'))")
    time.sleep(0.8)
    ev(f"GitUI.selectRepo({root!r}).then(() => GitUI.setTab('changes'))")
    pg.wait_for_function(f"document.querySelector('{P}.gt-row[data-id=\"{F}\"]')", timeout=10000)
    check(groups()[1] == "Feature*:4 files", "back in the repository: changelists and the active one kept")
    pg.click(row(F), button="right")
    item("Edit Changelist…")
    pg.wait_for_selector(".gcl-dlg", timeout=5000)
    check(ev("document.querySelector('.gcl-dlg .nm').value") == "Feature" and ev("document.querySelector('.gcl-dlg .ds').value") == "detail line", "Edit: current name + description")
    pg.fill(".gcl-dlg .nm", "Feature 2")
    pg.keyboard.press("Enter")
    pg.wait_for_function(f"document.querySelector('{P}.gt-row[data-id=\"{F}\"] .nm').textContent === 'Feature 2'", timeout=5000)
    pg.click(row(F), button="right")
    check("Delete Changelist" in menu(), "Delete enabled for a user list")
    ev("document.getElementById('dlgTitle').textContent = ''")
    item("Delete Changelist")
    pg.wait_for_function("document.getElementById('dlgTitle').textContent === 'Delete Changelist'", timeout=5000)
    check("4 files move to \"Changes\"" in ev("document.getElementById('dlgMsg').textContent"), "Delete asks first, says where the files go")
    pg.click("#dlgBtns button.primary")
    pg.wait_for_function(f"!document.querySelector('{P}.gt-row[data-id=\"{F}\"]')", timeout=5000)
    check(groups() == ["Changes:4 files"] and sorted(files()) == ["changes|a.txt", "changes|b.txt", "changes|c.txt", "changes|u.txt"],
          f"deleted: its files (also the untracked one) back in Changes, one list again ({groups()})")
    check(_g(R, "rev-parse", "HEAD") == head and _g(R, "diff", "--cached", "--name-only") == "" and not os.path.exists(os.path.join(R, ".reado")),
          "git untouched: HEAD, index unchanged; nothing written in the repository")
    ev("GitUI.toggleWindow(false)")


def repo_menu_tests(pg, shot):
    """The repository menu in the Git window header: a themed popup (not a native select) with a filter,
    the selected repository marked, change-count badges, ↑ / ↓ Enter Esc; picking one switches the window."""
    ev = pg.evaluate
    BTN, BOX = "#gitWin .gw-repo", "#gitPick.grepo"
    names = lambda: ev(f"[...document.querySelectorAll('{BOX} .it .nm')].map(n => n.textContent)")
    check(ev(f"document.querySelector('{BTN}').tagName") == "BUTTON" and not ev("!!document.querySelector('#gitWin select')"),
          "repository chooser is a button, no native <select>")
    check(ev(f"document.querySelector('{BTN} .nm').textContent") == "basic", "button shows the selected repository")
    pg.click(BTN)
    pg.wait_for_selector(BOX)
    n_repos = ev("GitUI.G.repos.length")
    check(len(names()) == n_repos, f"menu lists every repository ({len(names())}/{n_repos})")
    check(ev(f"(() => {{ const c = document.querySelector('{BOX} .it.cur'); return c && c.querySelector('.nm').textContent === 'basic' && c.classList.contains('act') && c.textContent.includes('✓'); }})()"),
          "selected repository marked (✓, highlighted for the keyboard)")
    check(ev(f"document.activeElement === document.querySelector('{BOX} input.q')"), "filter box has the focus")
    for theme in ("light", "dark"):
        ev(f"document.body.classList.contains('theme-{theme}') || runCommand('view.theme')")
        pg.wait_for_function(f"document.body.classList.contains('theme-{theme}')")
        same = ev(f"getComputedStyle(document.querySelector('{BOX}')).backgroundColor === getComputedStyle(document.querySelector('#gitWin')).backgroundColor"
                  f" && getComputedStyle(document.querySelector('{BOX}')).backgroundColor === getComputedStyle(document.getElementById('gitPick')).backgroundColor")
        check(same, f"{theme} theme: menu uses the window's panel colour (theme variables)")
        pg.wait_for_function(f"(() => {{ const b = [...document.querySelectorAll('{BOX} .it')].find(r => r.querySelector('.nm').textContent === 'basic'); return b && /^\\d+$/.test(b.querySelector('.bdg').textContent); }})()", timeout=20000)
        shot(f"r1-repo-menu-{theme}")
    pg.wait_for_function(f"(() => {{ const b = [...document.querySelectorAll('{BOX} .it')].find(r => r.querySelector('.nm').textContent === 'conflict'); return b && b.querySelector('.bdg.con'); }})()", timeout=20000)
    badge = ev(f"(() => {{ const b = [...document.querySelectorAll('{BOX} .it')].find(r => r.querySelector('.nm').textContent === 'basic'); return +b.querySelector('.bdg').textContent; }})()")
    want = ev("GitUI.G.status.files.filter(f => !f.eol).length")
    check(badge == want, f"badge = changed files of the repository ({badge} = {want}); conflicts in red")
    check(ev(f"document.querySelector('{BTN} .bdg').textContent") == str(want), "header button carries the same badge")
    pg.fill(f"{BOX} input.q", "bra")
    check(names() == ["branches"], f"filter narrows the list ({names()})")
    pg.fill(f"{BOX} input.q", "zzz-none")
    check("no repository matches" in pg.inner_text(BOX), "filter without a match says so")
    pg.fill(f"{BOX} input.q", "")
    pg.keyboard.press("Escape")
    check(not ev(f"!!document.querySelector('{BOX}')"), "Esc closes the menu")
    pg.click(BTN)
    pg.wait_for_selector(BOX)
    pg.click(BTN)
    check(not ev(f"!!document.querySelector('{BOX}')"), "a second click on the button closes it")
    pg.click(BTN)
    pg.wait_for_selector(BOX)
    pg.fill(f"{BOX} input.q", "conf")
    pg.keyboard.press("ArrowDown")
    pg.keyboard.press("Enter")
    pg.wait_for_function("GitUI.G.repo.name === 'conflict' && GitUI.G.status && GitUI.G.status.repo", timeout=10000)
    check(not ev(f"!!document.querySelector('{BOX}')") and ev(f"document.querySelector('{BTN} .nm').textContent") == "conflict",
          "↓ Enter picks the repository: menu closes, the window switches")
    check(ev("GitUI.S.repo") == ev("GitUI.G.repo.root"), "choice saved in state.json (git.repo)")
    pg.click(BTN)
    pg.wait_for_selector(BOX)
    pg.click(f"{BOX} .it:has(.nm:text-is('basic'))")
    pg.wait_for_function("GitUI.G.repo.name === 'basic'", timeout=10000)
    check(True, "click picks a repository")
    ev("document.body.classList.contains('theme-dark') && runCommand('view.theme')")


def find_dialog_tests(pg, ev, shot, base):
    """Find File (Ctrl+P) and Find in Files (Ctrl+Shift+F): one frame, switching keeps the text, prefixes, options saved."""
    QO, FIF = "document.getElementById('qoBg').classList.contains('show')", "document.getElementById('fifBg').classList.contains('show')"
    frame = lambda sel: ev(f"(() => {{ const r = document.querySelector('{sel} .fd').getBoundingClientRect(), i = document.querySelector('{sel} .fd-input').getBoundingClientRect();"
                           f" return [Math.round(r.left), Math.round(r.top), Math.round(r.width), Math.round(i.height)]; }})()")
    active = lambda sel: ev(f"document.querySelector('{sel} .fd-tab.active').dataset.fd")
    with open(os.path.join(base, "many.txt"), "w", encoding="utf-8") as f:
        f.write("".join(f"needle {i}\n" for i in range(40)))

    print("== find dialogs: Find File / Find in Files")
    pg.click(".tb-search")
    pg.wait_for_selector("#qoBg.show")
    check(active("#qoBg") == "files" and ev("document.getElementById('qoInput').placeholder").startswith("Find File"), "search box click: Find File, Files tab")
    pg.keyboard.type("f.txt")
    pg.wait_for_function("_qoItems.some(i => i.path === 'my-repo/f.txt')", timeout=10000)
    row = ev("""(() => { const r = [...document.querySelectorAll('#qoList .qo-item')].find(x => x.title === 'my-repo/f.txt');
      return r && {badge: !!r.querySelector('.fbadge'), name: r.querySelector('.qo-name').textContent, dir: r.querySelector('.qo-dir').textContent,
                   mark: r.querySelectorAll('.qo-name mark').length, h: Math.round(r.getBoundingClientRect().height)}; })()""")
    check(row and row["badge"] and row["name"] == "f.txt" and row["dir"] == "my-repo" and row["mark"] >= 5, f"file row: badge · name (matches marked) · dim folder ({row})")
    fq = frame("#qoBg")
    shot("f1-find-file")
    pg.keyboard.press("Tab")
    pg.wait_for_function(FIF + " && !" + QO, timeout=5000)
    check(ev("document.getElementById('fifQ').value") == "f.txt" and active("#fifBg") == "text", "Tab: Find in Files with the same text, In Files tab")
    ff = frame("#fifBg")
    check(fq[:3] == ff[:3] and fq[3] == ff[3], f"same frame: position / width / input height ({fq} vs {ff})")
    pg.keyboard.press("Tab")
    pg.wait_for_function(QO + " && !" + FIF, timeout=5000)
    check(ev("document.getElementById('qoInput').value") == "f.txt", "Tab again: back to Find File, text kept")
    pg.fill("#qoInput", "needle")
    pg.keyboard.press("Control+Shift+F")
    pg.wait_for_function(FIF + " && document.getElementById('fifQ').value === 'needle'", timeout=5000)
    check(True, "Ctrl+Shift+F in Find File: Find in Files, text kept")
    pg.wait_for_function("_fifResults.length > 0", timeout=15000)
    rh = ev("[...document.querySelectorAll('#fifResults .res-line')].slice(0, 3).map(r => Math.round(r.getBoundingClientRect().height))")
    gh = ev("(() => { const g = document.querySelector('#fifResults .res-file'); return {h: Math.round(g.getBoundingClientRect().height), b: !!g.querySelector('.fbadge'), n: g.querySelector('.qo-name').textContent, c: g.querySelector('.cnt').textContent}; })()")
    check(all(h == row["h"] for h in rh) and gh["h"] == row["h"], f"same row height in both lists ({row['h']} / {rh} / {gh['h']})")
    check(gh["b"] and gh["n"] == "many.txt" and gh["c"] == "40", f"result group: badge · file name · count ({gh})")
    check(ev("document.querySelector('#fifResults .res-line.sel .tx mark').textContent") == "needle" and ev("!!document.querySelector('#fifPreview .pv-line.hit')"), "selected hit: match highlighted, preview shown")
    shot("f2-find-in-files")
    pg.keyboard.press("Control+p")
    pg.wait_for_function(QO + " && document.getElementById('qoInput').value === 'needle'", timeout=5000)
    check(not ev(FIF), "Ctrl+P in Find in Files: Find File, text kept")
    pg.click("#qoModes .fd-tab[data-fd=text]")
    pg.wait_for_function(FIF, timeout=5000)
    check(ev("document.getElementById('fifQ').value") == "needle", "In Files tab click: switches, text kept")
    pg.keyboard.press("Escape")
    check(not ev(FIF) and not ev(QO), "Esc closes")

    print("== find dialogs: prefixes, beside, options, recent, more")
    ev("openQO('')")
    pg.keyboard.type("%needle 3")
    pg.wait_for_function(FIF + " && document.getElementById('fifQ').value === 'needle 3'", timeout=5000)
    check(True, "% in Find File: Find in Files with the rest")
    ev("closeFIF(); openQO('>git')")
    check(active("#qoBg") == "cmd", "> : Commands tab")
    ev("document.getElementById('qoInput').value = '#Foo'; updateQOChrome()")
    check(active("#qoBg") == "sym", "# : Symbols tab")
    ev("closeQO(); while (panes.length > 1) closePane(1)")
    ev("openFIF('needle 7')")
    pg.wait_for_function("_fifResults.length === 1", timeout=15000)
    pg.keyboard.press("Control+Enter")
    pg.wait_for_function("panes.length === 2 && panes[activePaneIdx].currentPath === 'many.txt'", timeout=10000)
    check(not ev(FIF), "Find in Files Ctrl+Enter: opens beside (second pane)")
    ev("while (panes.length > 1) closePane(1)")
    ev("openQO('')")
    pg.keyboard.type("many.txt")
    pg.wait_for_function("_qoItems.length && _qoItems[0].path === 'many.txt'", timeout=10000)
    pg.keyboard.press("Control+Enter")
    pg.wait_for_function("panes.length === 2 && panes.some((p, i) => i !== 0 && p.currentPath === 'many.txt' && p.editor && p.editor.getModel())", timeout=10000)
    check(True, "Find File Ctrl+Enter: opens beside")
    ev("while (panes.length > 1) closePane(1)")
    ev("openFIF('')")
    check("needle 7" in ev("[...document.querySelectorAll('#fifResults .fd-recent')].map(r => r.dataset.q)"), "empty Find in Files: recent searches listed")
    pg.click("#fifOpts .fd-tg:has(#fifCase)")
    pg.click("#fifPatBtn"); pg.fill("#fifPatMask", "*.txt"); pg.click("#fifPatApply")  # mask & exclude dialog
    time.sleep(0.6)
    check(ev("STATE.fifOpts && STATE.fifOpts.caseS === true && STATE.fifOpts.glob === '*.txt'"), "options: toggle bar state saved (Cc, file mask)")
    check(ev("document.getElementById('fifCase').checked && getComputedStyle(document.querySelector('#fifOpts .fd-tg:has(#fifCase)')).backgroundColor !== 'rgba(0, 0, 0, 0)'"),
          "Cc toggle shows on")
    pg.keyboard.press("Escape")
    ev("flushState()")
    time.sleep(0.5)
    pg.reload()
    pg.wait_for_function("typeof monaco !== 'undefined' && window.GitUI && document.querySelector('#tree .node')", timeout=30000)
    ev("openFIF('')")
    check(ev("document.getElementById('fifCase').checked && document.getElementById('fifGlob').value === '*.txt'"), "options kept after a restart")
    pg.click("#fifOpts .fd-tg:has(#fifCase)")
    pg.click("#fifPatBtn"); pg.fill("#fifPatMask", ""); pg.click("#fifPatApply")
    time.sleep(0.5)
    server.SETTINGS["search_max_results"] = 10
    try:
        pg.fill("#fifQ", "needle")
        pg.wait_for_function("_fifResults.length === 10 && document.querySelector('#fifResults .fd-more-row')", timeout=15000)
        pg.click("#fifResults .fd-more-row")
        pg.wait_for_function("_fifResults.length === 40", timeout=15000)
        check(not ev("!!document.querySelector('#fifResults .fd-more-row')"), "cap reached: 'show more' loads the rest (10 → 40)")
    finally:
        server.SETTINGS["search_max_results"] = 500
    pg.keyboard.press("Escape")
    ev("STATE.fifReplace = false")
    ev("runCommand('edit.replaceInFiles')")
    check(ev(FIF) and ev("document.getElementById('fifReplRow').style.display !== 'none' && document.activeElement === document.getElementById('fifRepl')"),
          "Replace in Files: the replace row (hidden by default) opens, its box focused")
    pg.keyboard.press("Escape")
    if ev(FIF):
        ev("closeFIF()")

    print("== title-bar search label: responsive")
    widths = []
    for w in (1500, 1000, 720, 560):
        pg.set_viewport_size({"width": w, "height": 800})
        time.sleep(0.4)
        r = ev("(() => { const e = document.getElementById('tbSearchLbl'); return {t: e.textContent, fits: e.scrollWidth <= e.clientWidth + 1}; })()")
        widths.append(len(r["t"]))
        check(r["fits"] and ("Find in Files" in r["t"] or "In Files" in r["t"]) and "Files" in r["t"], f"{w}px: '{r['t']}' fits, files + in files kept")
    check(widths == sorted(widths, reverse=True) and widths[0] > widths[-1], f"narrower window: shorter label {widths}")
    pg.set_viewport_size({"width": 1500, "height": 900})


def readonly_text_tests(pg, shot):
    """Commit message / Console / diff header: selectable, copyable, searchable — under the desktop app's
    page-wide user-select: none (pywebview, text_select off), injected here as the app does."""
    ev = pg.evaluate
    print("== read-only text: select / copy / find (desktop app CSS)")
    pg.add_style_tag(content="body {-webkit-user-select: none; -khtml-user-select: none; -ms-user-select: none; user-select: none; cursor: default;}")
    ev("window._clip = []; navigator.clipboard.writeText = t => { _clip.push(t); return Promise.resolve(); }")
    clip = lambda: ev("_clip[_clip.length - 1] || ''")
    ev("GitUI.toggleWindow(true)")
    ev("GitUI.selectRepo(GitUI.G.repos.find(r => r.name === 'basic').root)")
    ev("GitUI.setTab('log')")
    LOG = "#gitWin [data-page=log]"
    pg.wait_for_selector(LOG + " .gl-row", timeout=20000)
    pg.click(LOG + " .gl-row >> nth=0")
    pg.wait_for_function(f"document.querySelector('{LOG} .gd-msg .subj') && GitUI.Log.detail", timeout=10000)
    body = ev("GitUI.Log.detail.body")
    check(ev(f"getComputedStyle(document.querySelector('{LOG} .gd-msg')).userSelect") == "text" and ev("getComputedStyle(document.body).userSelect") == "none",
          "commit message user-select: text while the page is user-select: none")
    bx = ev(f"(() => {{ const r = document.querySelector('{LOG} .gd-msg').getBoundingClientRect(); return [r.left, r.top]; }})()")
    x, y = bx[0] + 12, bx[1] + 14
    pg.mouse.move(x, y); pg.mouse.down(); pg.mouse.move(x + 220, y + 40, steps=8); pg.mouse.up()
    sel = ev("String(getSelection())")
    check(sel.startswith(body.split("\n")[0][:6]) and "\n" in sel, f"drag selects the message (subject + body) {sel[:40]!r}")
    pg.keyboard.press("Control+c")
    check(clip() == sel, "Ctrl+C copies the selection")
    pg.mouse.click(x + 30, y + 3, button="right")
    pg.wait_for_selector("#ctxMenu")
    labels = ev("[...document.querySelectorAll('#ctxMenu .ctx-item')].map(r => r.dataset.label + (r.classList.contains('disabled') ? '(off)' : ''))")
    check(labels == ["Copy", "Copy Commit Message", "Copy Revision Number", "Select All", "Find…"], f"right-click: Copy / Copy Commit Message / Copy Revision Number / Select All / Find ({labels})")
    pg.click("#ctxMenu .ctx-item[data-label='Copy Commit Message']")
    check(clip() == body, "Copy Commit Message: the whole message")
    pg.mouse.click(x + 30, y + 3, button="right")
    pg.click("#ctxMenu .ctx-item[data-label='Copy Revision Number']")
    check(clip() == ev("GitUI.Log.detail.h"), "Copy Revision Number: the full hash")
    pg.mouse.click(x + 30, y + 3)
    pg.keyboard.press("Control+a")
    sa = ev(f"(() => {{ const m = document.querySelector('{LOG} .gd-msg'), s = getSelection(); return {{in: m.contains(s.anchorNode) && m.contains(s.focusNode), t: String(s)}}; }})()")
    check(sa["in"] and sa["t"].startswith(body.split("\n")[0]) and "copy hash" in sa["t"], "Ctrl+A: the whole message box, not the page")
    print("== read-only text: Ctrl+F in the commit message")
    pg.mouse.click(x + 30, y + 3)
    pg.keyboard.press("Control+f")
    pg.wait_for_selector(".rd-find input", timeout=3000)
    pg.keyboard.type("body line")
    time.sleep(0.2)
    check(ev("document.querySelector('.rd-find .n').textContent") == "1/1" and ev("CSS.highlights.get('rd-find-cur').size") == 1, "Ctrl+F: find bar, match counted and highlighted")
    shot("10-msg-find")
    pg.keyboard.press("Escape")
    check(not ev("!!document.querySelector('.rd-find')") and not ev("CSS.highlights.has('rd-find-cur')"), "Esc closes the find bar, highlights cleared")
    pg.mouse.click(x + 30, y + 3)
    pg.keyboard.press("Control+f")
    pg.keyboard.type("body line")
    pg.click(LOG + " .gl-row >> nth=1")
    pg.wait_for_function("GitUI.Log.detail && GitUI.Log.detail.h === GitUI.Log.rows[1].c.h && document.querySelector('.rd-find .n').textContent === '1/1'"
                         " && [...CSS.highlights.get('rd-find-cur')][0].startContainer.isConnected", timeout=8000)
    check(True, "another commit selected: the open search runs again on its message")
    ev("document.querySelector('.rd-find [data-a=close]').click()")
    q = ev("fetch('/api/git/log?' + new URLSearchParams({repo: GitUI.G.repo.root, text: 'body line for 7', n: 10})).then(r => r.json()).then(d => d.commits.map(c => c.s))")
    check(q == ["commit 7"], f"Log text filter searches the message body too (git log --grep) ({q})")

    print("== read-only text: Console, diff header")
    ev("GitUI.setTab('console')")
    pg.wait_for_selector("#gitWin [data-page=console] .gc-row", timeout=8000)
    cb = "#gitWin [data-page=console] .gw-scroll"
    check(ev(f"getComputedStyle(document.querySelector('{cb}')).userSelect") == "text", "Console: selectable")
    r0 = ev(f"(() => {{ const c = [...document.querySelectorAll('{cb} .gc-row .c')].pop(); c.scrollIntoView({{block: 'center'}});"
            " const r = c.getBoundingClientRect(); return [r.left, r.top + r.height / 2, r.width]; })()")
    pg.mouse.move(r0[0] + 2, r0[1]); pg.mouse.down(); pg.mouse.move(r0[0] + min(160, r0[2]), r0[1], steps=6); pg.mouse.up()
    s1 = ev("String(getSelection())")
    time.sleep(2.6)  # the Console polls every 2 s: no redraw without new entries
    check(s1.startswith("git") and ev("String(getSelection())") == s1, f"Console: selection survives the 2 s refresh ({s1[:30]!r})")
    pg.mouse.click(r0[0] + 4, r0[1], button="right")
    labels = ev("[...document.querySelectorAll('#ctxMenu .ctx-item')].map(r => r.dataset.label)")
    check(labels[:3] == ["Copy", "Copy Command", "Copy All"] or labels[:2] == ["Copy", "Copy Command"], f"Console right-click: Copy / Copy Command / Copy All ({labels})")
    pg.click("#ctxMenu .ctx-item[data-label='Copy Command']")
    check(clip().startswith("git "), "Copy Command")
    ev("GitUI.setTab('changes')")
    pg.wait_for_selector("#gitWin [data-page=changes] .gt-row:has-text('app.py')", timeout=20000)
    pg.click("#gitWin [data-page=changes] .gt-row:has-text('app.py')")
    pg.wait_for_function("GitUI.Changes.pane.spec && GitUI.Changes.pane.spec.path === 'src/app.py'", timeout=10000)
    hd = "#gitWin [data-page=changes] .gdm-t"
    check(ev(f"getComputedStyle(document.querySelector('{hd} .gdm-path')).userSelect") == "text", "diff header: path selectable")
    pg.click(hd + " .gdm-path", button="right")
    pg.click("#ctxMenu .ctx-item[data-label='Copy Path']")
    check(clip() == "src/app.py", "diff header right-click: Copy Path")
    pg.keyboard.press("Escape")


def toolbar_tests(b, url, tmp, errors, shots):
    """Top bar: Git group (branch, Pull, Commit / Push requests), repository chip, palette modes, settings icon."""
    import gitview
    base = os.path.realpath(os.path.join(tmp, "tbfx"))
    os.makedirs(base)
    _put(base, "loose.txt", "not in git\n")
    _g(base, "init", "-q", "--bare", "remote.git")
    _g(base, "clone", "-q", os.path.join(base, "remote.git"), "up")
    _put(os.path.join(base, "up"), "f.txt", "one\n")
    _g(os.path.join(base, "up"), "add", "f.txt")
    _g(os.path.join(base, "up"), "commit", "-q", "-m", "first")
    _g(os.path.join(base, "up"), "push", "-q", "origin", "HEAD:main")
    _g(base, "clone", "-q", "-b", "main", os.path.join(base, "remote.git"), "my-repo")
    A, UP = os.path.join(base, "my-repo"), os.path.join(base, "up")
    server.SETTINGS["base_dir"] = base
    pg = b.new_page(viewport={"width": 1500, "height": 900})
    pg.on("pageerror", lambda e: errors.append("toolbar page: " + str(e) + " " + str(getattr(e, "stack", ""))[:300]))
    pg.goto(url)
    pg.wait_for_function("typeof monaco !== 'undefined' && window.GitUI && document.querySelector('#tree .node')", timeout=30000)
    shot = lambda n: shots and pg.screenshot(path=os.path.join(shots, n + ".png"))
    ev = pg.evaluate
    toast = lambda: ev("document.getElementById('toast').textContent")

    print("== top bar: groups, settings icon, search")
    check(ev("!!document.querySelector('#gtbBranch') && !!document.querySelector('#gtbPull') && !!document.querySelector('#gtbCommit') && !!document.querySelector('#gtbPush')"),
          "Git group: branch · Pull · Commit · Push")
    check(ev("!document.querySelector('#tbGroups [data-cmd=\"edit.findInFiles\"]') && !document.querySelector('#tbGroups [data-group=search]')"),
          "toolbar Find in Files button removed")
    check(ev("!document.querySelector('#tbGroups [data-cmd=\"file.settings\"]') && !!document.getElementById('themeBtn')"), "gear gone from the toolbar, theme toggle stays")
    pos = ev("""(() => { const s = document.getElementById('tsSettings'), g = document.querySelector('#toolStrip .tsb[data-tool=git]');
      return {last: s === s.parentNode.lastElementChild, below: s.getBoundingClientRect().top > g.getBoundingClientRect().bottom - 1, title: s.title}; })()""")
    check(pos["last"] and pos["below"] and pos["title"].startswith("Settings"), f"settings icon at the bottom of the tool strip, below Git ({pos['title']})")
    pg.click("#tsSettings")
    pg.wait_for_function("document.getElementById('settingsBg').classList.contains('show')", timeout=5000)
    check(True, "strip settings icon opens Settings")
    ev("closeSettings()")
    lbl = ev("document.querySelector('.tb-search .ellipsis').textContent")
    check(lbl == "Search files (Ctrl+P) · Find in Files (Ctrl+Shift+F) · Commands (Ctrl+Shift+P)", f"search box label ({lbl})")
    check(ev("Object.fromEntries(['edit.findInFiles','go.file'].map(i => [i, CMD.get(i).keys]))") == {"edit.findInFiles": "Ctrl+Shift+F", "go.file": "Ctrl+P"},
          "Find in Files / Go to file keys unchanged")

    print("== top bar: Git group follows the active file")
    ev("openFile('loose.txt')")
    pg.wait_for_function("currentPath === 'loose.txt' && GitUI && document.querySelector('#gtbBranch .nm').textContent === 'Git'", timeout=10000)
    time.sleep(1.5)
    check(ev("['gtbPull','gtbCommit','gtbPush'].every(id => document.getElementById(id).disabled)") and ev("document.querySelector('#gtbBranch .nm').textContent") == "Git",
          "file outside any repository: 'Git', Pull / Commit / Push disabled")
    check(not ev("!!document.querySelector('#crumbs .crumb-repo')"), "file outside any repository: no repository chip")
    ev("openFile('my-repo/f.txt')")
    pg.wait_for_function("document.querySelector('#gtbBranch .nm').textContent === 'main'", timeout=10000)
    st = ev("""(() => { const q = id => document.getElementById(id);
      return {pull: q('gtbPull').disabled, commit: q('gtbCommit').disabled, push: q('gtbPush').disabled, ab: q('gtbBranch').querySelector('.ab').textContent,
              ct: q('gtbCommit').title, pt: q('gtbPush').title, pl: q('gtbPull').title, bt: q('gtbBranch').title,
              ag: [q('gtbPull'), q('gtbCommit'), q('gtbPush')].map(x => x.classList.contains('agento')),
              border: getComputedStyle(q('gtbCommit')).borderTopStyle, fs: parseFloat(getComputedStyle(q('gtbBranch').querySelector('.nm')).fontSize)}; })()""")
    check(not st["pull"] and st["commit"] and st["push"] and st["ab"] == "", f"clean, up to date: Pull on, Commit / Push off, no ↑↓ ({st})")
    check("AgentO에 요청" in st["ct"] and "AgentO에 요청" in st["pt"] and "AgentO" not in st["pl"] and "--ff-only" in st["pl"], "tooltips: Commit / Push = AgentO requests, Pull = ff-only")
    check(st["ag"] == [False, True, True] and st["border"] == "dashed", "Commit / Push marked as AgentO requests (dashed, A mark)")
    check(st["fs"] >= 13 and "my-repo: branch main → origin/main" in st["bt"], f"branch name larger ({st['fs']}px), tooltip repository + upstream")
    chip = ev("(() => { const c = document.querySelector('#crumbs .crumb-repo'); return c && {t: c.textContent, w: getComputedStyle(c).fontWeight, all: document.getElementById('crumbs').textContent}; })()")
    check(chip and chip["t"] == "my-repo" and int(chip["w"]) >= 700 and chip["all"].replace(" ", "") == "my-repo/f.txt", f"breadcrumb: repository chip, path kept ({chip})")
    shot("t1-toolbar")

    print("== top bar: Pull")
    _put(UP, "f.txt", "one\ntwo\n")
    _put(UP, "g.txt", "g\n")
    _g(UP, "add", "-A"); _g(UP, "commit", "-q", "-m", "remote work"); _g(UP, "push", "-q", "origin", "HEAD:main")
    pg.route("**/api/git/pull", lambda route: (time.sleep(0.8), route.continue_()))
    pg.click("#gtbPull")
    pg.wait_for_function("document.getElementById('dlgTitle').textContent === 'Pull main'", timeout=10000)
    msg = ev("document.getElementById('dlgMsg').textContent")
    check("origin/main" in msg and "my-repo" in msg and "Remote:" in msg and "--ff-only" in msg, "confirmation: repository, branch ← upstream, remote")
    shot("t2-pull-confirm")
    pg.click("#dlgBtns button.primary")
    pg.wait_for_function("document.getElementById('gtbPull').classList.contains('busy')", timeout=5000)
    check(ev("document.getElementById('gtbPull').disabled"), "running: Pull disabled + spinner")
    pg.wait_for_function("document.getElementById('toast').textContent.startsWith('pulled')", timeout=20000)
    check(_g(A, "rev-parse", "HEAD") == _g(UP, "rev-parse", "HEAD"), f"pulled: HEAD = remote ({toast()})")
    pg.unroute("**/api/git/pull")
    pg.wait_for_function("!document.getElementById('gtbPull').classList.contains('busy') && !document.getElementById('gtbPull').disabled", timeout=5000)
    pg.wait_for_function("monaco.editor.getModels().some(m => m.uri.path.endsWith('f.txt') && m.getValue().includes('two'))", timeout=15000)
    check(True, "the open file shows the pulled text")
    _put(A, "f.txt", "local edit\n")
    _put(UP, "f.txt", "remote again\n")
    _g(UP, "commit", "-q", "-am", "remote 2"); _g(UP, "push", "-q", "origin", "HEAD:main")
    before = _g(A, "rev-parse", "HEAD")
    pg.click("#gtbPull")
    pg.wait_for_function("document.getElementById('dlgTitle').textContent === 'Pull main'", timeout=10000)
    pg.click("#dlgBtns button.primary")
    pg.wait_for_function("document.getElementById('dlgTitle').textContent.startsWith('Pull stopped')", timeout=20000)
    msg = ev("document.getElementById('dlgMsg').textContent")
    check("local changes" in msg and "never forces" in msg and "would be overwritten" in msg and _g(A, "rev-parse", "HEAD") == before,
          f"local change in the way: dialog says why + git's message, nothing changed ({msg[:80]})")
    check(ev("[...document.querySelectorAll('#dlgBtns button')].map(b => b.textContent).join('|')").startswith("Stash Changes… (AgentO)|show Console"),
          "refused pull: Stash (AgentO) and Console offered")
    shot("t2b-pull-refused")
    pg.click("#dlgBtns button:has-text('show Console')")
    pg.wait_for_function("STATE.git.open && STATE.git.tab === 'console'", timeout=5000)
    pg.wait_for_function("document.querySelector('#gitWin [data-page=console] .gc-row pre.o')", timeout=8000)
    check("would be overwritten" in ev("document.querySelector('#gitWin [data-page=console]').textContent"), "failure: the Console tab shows the git output")
    ev("GitUI.toggleWindow(false)")

    print("== top bar: Commit / Push requests (AgentO deep link)")
    sent, launched, orig = [], [], (gitview.agento_handler, gitview._startfile, gitview.agento_path)
    try:
        gitview.agento_handler = lambda: None
        gitview.agento_path = lambda p="": launched.append(p)  # never start the real AgentO from a test
        ev("window._clip = []; navigator.clipboard.writeText = t => { _clip.push(t); return Promise.resolve(); }")
        pg.wait_for_function("!document.getElementById('gtbCommit').disabled", timeout=10000)
        pg.click("#gtbCommit")
        pg.wait_for_selector(".gtb-dlg", timeout=5000)
        dl = ev("document.querySelector('.gtb-dlg').textContent")
        check("f.txt" in dl and "my-repo" in dl and "main" in dl, "commit request dialog: repository, branch, changed files")
        pg.fill(".gtb-dlg .msg", "fix: something")
        shot("t3-commit-request")
        pg.click(".gtb-dlg [data-a=go]")  # default for now: the instruction on the clipboard (no deep link)
        pg.wait_for_function("document.getElementById('toast').textContent.includes('commit 지시문을 복사했습니다')", timeout=10000)
        clip = ev("_clip[_clip.length - 1] || ''")
        check(clip.startswith("[ReadO → AgentO]") and "- f.txt" in clip and "fix: something" in clip and not sent and launched,
              f"Commit (clipboard mode): instruction with files + message copied, no deep link ({toast()})")
        pg.click("#gtbCommit")
        pg.wait_for_selector(".gtb-dlg", timeout=5000)
        ev("GitUI.useDeeplink = true")  # the next stage: agento://dispatch
        pg.click(".gtb-dlg [data-a=go]")
        pg.wait_for_function("document.getElementById('toast').textContent.includes('agento://')", timeout=10000)
        check("지시문을 복사했습니다" in toast() and not sent, f"deep link on, no agento: handler → instruction copied ({toast()})")
        gitview.agento_handler = lambda: "AgentO.exe %1"
        gitview._startfile = lambda u: sent.append(u)
        pg.click("#gtbCommit")
        pg.wait_for_selector(".gtb-dlg", timeout=5000)
        pg.fill(".gtb-dlg .msg", "fix: 한글 & more")
        pg.click(".gtb-dlg [data-a=go]")
        pg.wait_for_function("document.getElementById('toast').textContent.includes('commit 요청을 보냈습니다')", timeout=10000)
        check(len(sent) == 1 and "kind=commit" in sent[0] and "msg=fix%3A%20%ED%95%9C%EA%B8%80%20%26%20more" in sent[0], f"commit request sent as a deep link ({sent[-1][:120] if sent else ''})")
        _g(A, "checkout", "-q", "--", "f.txt")
        _g(A, "fetch", "-q"); _g(A, "reset", "-q", "--hard", "origin/main")
        _put(A, "h.txt", "h\n"); _g(A, "add", "h.txt"); _g(A, "commit", "-q", "-m", "local")
        ev("GitUI.useDeeplink = false")
        pg.wait_for_function("!document.getElementById('gtbPush').disabled", timeout=15000)
        pg.click("#gtbPush")
        pg.wait_for_function("document.getElementById('dlgTitle').textContent.startsWith('Push')", timeout=5000)
        pg.click("#dlgBtns button.primary")
        pg.wait_for_function("document.getElementById('toast').textContent.includes('push 지시문을 복사했습니다')", timeout=10000)
        clip = ev("_clip[_clip.length - 1] || ''")
        check("push" in clip and "force push는 하지 마" in clip and len(sent) == 1, "Push (clipboard mode): instruction copied, says no force")
        ev("GitUI.useDeeplink = true")
        pg.wait_for_function("document.querySelector('#gtbBranch .ab').textContent === '↑1' && !document.getElementById('gtbPush').disabled && document.getElementById('gtbCommit').disabled", timeout=15000)
        check(True, "local commit: ↑1 shown, Push on, Commit off (clean)")
        pg.click("#gtbPush")
        pg.wait_for_function("document.getElementById('dlgTitle').textContent.startsWith('Push')", timeout=5000)
        check("force push is never requested" in ev("document.getElementById('dlgMsg').textContent"), "push confirmation: no force")
        pg.click("#dlgBtns button.primary")
        pg.wait_for_function("document.getElementById('toast').textContent.includes('push 요청을 보냈습니다')", timeout=10000)
        check(len(sent) == 2 and "kind=push" in sent[1] and "ahead=1" in sent[1] and _g(A, "rev-list", "--count", "origin/main..HEAD") == "1",
              "push request sent (ahead=1); ReadO pushed nothing")
    finally:
        gitview.agento_handler, gitview._startfile, gitview.agento_path = orig
        ev("GitUI.useDeeplink = false")
    _g(A, "checkout", "-q", "-b", "topic")
    pg.wait_for_function("document.querySelector('#gtbBranch .nm').textContent === 'topic'", timeout=15000)
    check(ev("document.getElementById('gtbPull').disabled") and "no upstream" in ev("document.getElementById('gtbPull').title"), "branch without upstream: Pull disabled, tooltip says why")
    check(not ev("document.getElementById('gtbPush').disabled"), "branch without upstream: Push request allowed (AgentO sets it up)")
    checkout_ui_tests(pg, ev, shot, toast, A, UP)
    eol_ui_tests(pg, ev, shot, toast, base)
    changelist_ui_tests(pg, ev, shot, toast, base)
    ev("openFile('my-repo/f.txt')")
    _g(A, "checkout", "-q", "topic") if _g(A, "rev-parse", "--abbrev-ref", "HEAD") != "topic" else None

    find_dialog_tests(pg, ev, shot, base)
    print("== top bar: narrow windows, dark theme")
    ev("openFile('my-repo/f.txt')")
    pg.wait_for_function("document.querySelector('#gtbBranch .nm').textContent === 'topic'", timeout=10000)
    for w in (1100, 860, 640):
        pg.set_viewport_size({"width": w, "height": 800})
        time.sleep(0.4)
        r = ev("""(() => { const bar = document.querySelector('.topbar'), n = document.querySelector('#gtbBranch .nm'), br = document.getElementById('gtbBranch').getBoundingClientRect();
          return {over: bar.scrollWidth - bar.clientWidth, cls: bar.className, nm: getComputedStyle(n).display, bw: br.width, inside: br.right <= bar.getBoundingClientRect().right + 1,
                  pull: document.getElementById('gtbPull').offsetParent !== null}; })()""")
        check(r["over"] <= 1 and r["inside"] and r["pull"], f"{w}px: no overflow, Git group visible ({r['cls']}, branch {r['bw']:.0f}px, name {r['nm']})")
        if w == 640:
            shot("t5-narrow")
    pg.set_viewport_size({"width": 1500, "height": 900})
    ev("runCommand('view.theme')")
    time.sleep(0.3)
    dark = ev("""(() => { const n = document.querySelector('#gtbBranch .nm'), c = document.querySelector('#crumbs .crumb-repo');
      return {dark: getTheme() === 'dark', nm: getComputedStyle(n).color, bar: getComputedStyle(document.querySelector('.topbar')).backgroundColor, chip: !!c}; })()""")
    check(dark["dark"] and dark["nm"] != dark["bar"] and dark["chip"], f"dark theme: branch text {dark['nm']} on {dark['bar']}, chip shown")
    shot("t6-dark")
    ev("runCommand('view.theme')")
    pg.close()


def main():
    fx = os.path.realpath(sys.argv[1])
    shots = sys.argv[2] if len(sys.argv) > 2 else None
    tmp = tempfile.mkdtemp(prefix="reado-ui-")
    server.CONFIG_PATH = os.path.join(tmp, "config.json")
    server.SETTINGS = dict(server.DEFAULT_SETTINGS, base_dir=fx)
    srv = server.make_server("127.0.0.1", 0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_address[1]}/"
    errors = []
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        pg = b.new_page(viewport={"width": 1500, "height": 950})
        pg.on("pageerror", lambda e: errors.append(str(e)))
        pg.on("console", lambda m: m.type == "error" and errors.append(m.text))
        pg.goto(url)
        pg.wait_for_function("typeof monaco !== 'undefined' && window.GitUI && document.querySelector('#tree .node')", timeout=30000)
        shot = lambda n: shots and pg.screenshot(path=os.path.join(shots, n + ".png"))
        if os.environ.get("READO_UI_ONLY") == "toolbar":  # quick run of the top-bar section alone
            pg.close()  # it would keep polling fx repositories outside the next base folder
            toolbar_tests(b, url, tmp, errors, shots)
            b.close()
            srv.shutdown()
            check(not errors, "no page errors" + (": " + " | ".join(errors[:5]) if errors else ""))
            print(f"\n{'FAILED: ' + str(len(FAILS)) if FAILS else 'all passed'}")
            sys.exit(1 if FAILS else 0)

        print("== commands / menu / keys")
        check(pg.evaluate("MENUS.some(m => m.label === 'Git')"), "Git menu in the menu bar")
        check(pg.evaluate("COMMANDS.filter(c => c.id.startsWith('git.')).length") >= 18, "git commands registered (palette)")
        for km in ("vscode", "intellij"):
            conf = pg.evaluate(f"keymapConflicts('{km}')")
            gitc = [c for c in conf if any(i.startswith("git.") for i in c["ids"])]
            check(not gitc, f"{km} keymap: no conflicts with git keys {gitc or ''}")
        check(pg.evaluate("!!document.querySelector('#tbGroups [data-group=git] #gtbBranch')"), "toolbar Git group (branch button)")
        print("== tool strip Git icon")
        check(not pg.evaluate("fetch('/api/git/info').then(r => r.json()).then(d => !!d.repo)"), "fixture root is not a repository (repositories below it)")
        strip_git_click(pg, "non-repo parent folder")

        print("== Local Changes")
        pg.evaluate("GitUI.toggleWindow(true)")
        pg.wait_for_selector("#gitWin.show")
        pg.wait_for_function("GitUI.G.repo && GitUI.G.repos.length >= 6", timeout=20000)
        pg.evaluate("GitUI.selectRepo(GitUI.G.repos.find(r => r.name === 'basic').root)")
        pg.evaluate("GitUI.setTab('changes')")
        pg.wait_for_function("document.querySelectorAll('#gitWin [data-page=changes] .gt-row').length > 5", timeout=20000)
        txt = pg.inner_text("#gitWin [data-page=changes]")
        check("Unversioned Files" in txt and "app.py" in txt and "설명 파일.txt" in txt, "groups + files (Korean name)")
        check("partly staged" in txt or "staged" in txt, "staged marker")
        shot("1-local-changes")
        print("== repository menu")
        repo_menu_tests(pg, shot)
        pg.evaluate("GitUI.setTab('changes')")
        pg.wait_for_function("document.querySelectorAll('#gitWin [data-page=changes] .gt-row').length > 5", timeout=20000)
        print("== Local Changes: file tree | diff (split)")
        PANE = "GitUI.Changes.pane"
        PANE_READY = PANE + ".ed && " + PANE + ".ed.getModel() && " + PANE + ".bg.querySelector('.gdm-msg').style.display === 'none'"
        geo = pg.evaluate("""(() => { const l = document.querySelector('#gitWin .lc-left').getBoundingClientRect(), d = document.querySelector('#gitWin .lc-diff').getBoundingClientRect();
          return {lr: l.right, dl: d.left, dw: d.width, lt: l.top, dt: d.top, msg: document.querySelector('#gitWin .lc-diff .gdm-msg').textContent}; })()""")
        check(geo["lr"] <= geo["dl"] and geo["dw"] > 300 and abs(geo["lt"] - geo["dt"]) < 2, f"split: file tree left, diff right ({geo['lr']:.0f} | {geo['dl']:.0f}, {geo['dw']:.0f} wide)")
        check("Select a file" in geo["msg"], "nothing selected: 'Select a file' hint")
        pg.evaluate("document.querySelector('#gitWin [data-page=changes] .gw-scroll').scrollTop = 0")
        pg.click("#gitWin [data-page=changes] .gt-row:has-text('app.py')")
        pg.wait_for_function(PANE_READY + " && " + PANE + ".spec.path === 'src/app.py'", timeout=10000)
        check(pg.evaluate("GitUI.DW.wins.length") == 0 and pg.evaluate(PANE + ".ed.getModel().original.getValue().startsWith('line 0')"),
              "click: the diff shows on the right (HEAD left), no window")
        check("HEAD" in pg.evaluate(PANE + ".bg.querySelector('.gdm-sub').textContent"), "pane header: path + compared versions")
        shot("1b-split")
        pg.keyboard.press("ArrowDown")  # the 문서 folder row: the pane keeps app.py
        time.sleep(0.3)
        check(pg.evaluate(PANE + ".spec.path") == "src/app.py", "↓ onto a folder row: the diff stays")
        pg.keyboard.press("ArrowDown")
        pg.wait_for_function(PANE_READY + " && " + PANE + ".spec.path !== 'src/app.py'", timeout=10000)
        p2 = pg.evaluate(PANE + ".spec.path")
        check(p2.split("/")[-1] in pg.evaluate("document.querySelector('#gitWin [data-page=changes] .gt-row.sel').textContent"), f"↓ moves the selection, the diff follows ({p2})")
        pg.keyboard.press("ArrowUp")
        pg.keyboard.press("ArrowUp")
        pg.wait_for_function(PANE + ".spec && " + PANE + ".spec.path === 'src/app.py'", timeout=10000)
        check(True, "↑ back to the first file")
        pg.click("#gitWin .lc-diff [data-a=ws]")
        check(pg.evaluate("STATE.git.ignoreWs === true && " + PANE + ".ed.getOptions ? true : true") and
              pg.evaluate("document.querySelector('#gitWin .lc-diff [data-a=ws]').textContent") == "Ignore whitespace", "whitespace option toggles")
        pg.click("#gitWin .lc-diff [data-a=ws]")
        pg.click("#gitWin .lc-diff [data-a=nextChange]")
        nc = pg.evaluate("(() => { const ed = " + PANE + ".ed, ln = ed.getModifiedEditor().getPosition().lineNumber;"
                         " return [ln, ed.getLineChanges().map(c => [c.modifiedStartLineNumber, c.modifiedEndLineNumber])]; })()")
        check(any(a <= nc[0] <= max(a, b) for a, b in nc[1]), f"next change: cursor on a change (line {nc[0]}, changes {nc[1]})")
        sash = pg.evaluate("(() => { const r = document.querySelector('#gitWin .lc-left + .gw-vsash').getBoundingClientRect(); return {x: r.left + r.width / 2, y: r.top + 40}; })()")
        w0 = pg.evaluate("document.querySelector('#gitWin .lc-left').getBoundingClientRect().width")
        pg.mouse.move(sash["x"], sash["y"]); pg.mouse.down(); pg.mouse.move(sash["x"] + 60, sash["y"]); pg.mouse.move(sash["x"] + 120, sash["y"]); pg.mouse.up()
        w1 = pg.evaluate("document.querySelector('#gitWin .lc-left').getBoundingClientRect().width")
        check(abs(w1 - w0 - 120) <= 2 and abs(pg.evaluate("STATE.git.cw") - w1) <= 1, f"split bar drag: {w0:.0f} -> {w1:.0f} px, remembered")
        pg.mouse.move(sash["x"] + 120, sash["y"]); pg.mouse.down(); pg.mouse.move(sash["x"], sash["y"]); pg.mouse.up()
        pg.dblclick("#gitWin [data-page=changes] .gt-row:has-text('staged.txt')")
        pg.wait_for_function("GitUI.DW.wins.length === 1 && GitUI.DM.ident.endsWith('|staged.txt')", timeout=10000)
        try:  # the pane loads its spec on its own; give it a moment under load
            pg.wait_for_function(PANE + ".spec && " + PANE + ".spec.path === 'staged.txt'", timeout=5000)
        except Exception:
            pass
        check(pg.evaluate(PANE + ".spec.path") == "staged.txt", "double-click: diff window opens (the pane shows the file too)")
        pg.evaluate("GitUI.closeDiffWin(GitUI.DM)")
        pg.click("#gitWin [data-page=changes] .gt-row:has-text('app.py')", button="right")
        check("Show Diff" in pg.evaluate("[...document.querySelectorAll('#ctxMenu .ctx-item')].map(e => e.dataset.label)"), "right-click: Show Diff")
        pg.click("#ctxMenu .ctx-item[data-label='Show Diff']")
        pg.wait_for_function("GitUI.DW.wins.length === 1", timeout=10000)
        check(True, "Show Diff opens the diff window")
        pg.evaluate("GitUI.closeDiffWin(GitUI.DM)")

        print("== diff windows (floating, non-modal)")
        MODAL = "GitUI.DW.wins.length > 0"
        # IntelliJ's annotation tooltip, line by line
        TIP_RE = r"commit [0-9a-f]{40}\nAuthor: \S[^\n]* <[^>\n]+@[^>\n]+>\nDate: \d{1,2}/\d{1,2}/\d{4} \d{1,2}:\d{2} (AM|PM)\n\n\S[\s\S]*"
        DIFF_READY = MODAL + " && GitUI.DM.ed && GitUI.DM.ed.getModel() && GitUI.DM.bg.querySelector('.gdm-msg').style.display === 'none'"
        RECT = "(() => { const r = GitUI.DM.bg.getBoundingClientRect(); return {x: r.left, y: r.top, w: r.width, h: r.height}; })()"
        HEAD = "(() => { const r = GitUI.DM.bg.querySelector('.gdm-head').getBoundingClientRect(); return {x: r.left + 60, y: r.top + r.height / 2}; })()"

        def drag(x0, y0, x1, y1):
            pg.mouse.move(x0, y0)
            pg.mouse.down()
            pg.mouse.move((x0 + x1) / 2, (y0 + y1) / 2)
            pg.mouse.move(x1, y1)
            pg.mouse.up()
        scroller = "#gitWin [data-page=changes] .gw-scroll"
        pg.evaluate(f"document.querySelector('{scroller}').scrollTop = 0")
        # single click on a file -> a diff window
        pg.dblclick("#gitWin [data-page=changes] .gt-row:has-text('app.py')")
        pg.wait_for_function(DIFF_READY, timeout=10000)
        check(pg.evaluate("GitUI.DM.ed.getModel().original.getValue().startsWith('line 0')"), "diff window: double-click opens the diff, HEAD on the left")
        check(pg.evaluate("GitUI.DM.bg.querySelector('.gdm-path').textContent") == "src/app.py", "diff window title: file path")
        check(pg.evaluate("!document.querySelector('.gdm-bg, #gitDiffModal') && !document.querySelector('.qo-bg.show')"), "no dimming / click-blocking overlay")
        check(not pg.evaluate("document.getElementById('diffBg').classList.contains('show')"), "bottom / old diff overlay not used")
        shot("2-diff-window")
        # resize by the bottom-right corner, then move by the title bar
        r0 = pg.evaluate(RECT)
        drag(r0["x"] + r0["w"] - 3, r0["y"] + r0["h"] - 3, r0["x"] + 700, r0["y"] + 420)
        r1 = pg.evaluate(RECT)
        check(abs(r1["w"] - 700) <= 4 and abs(r1["h"] - 420) <= 4, f"resize by the corner ({r0['w']:.0f}x{r0['h']:.0f} -> {r1['w']:.0f}x{r1['h']:.0f})")
        hd = pg.evaluate(HEAD)
        drag(hd["x"], hd["y"], hd["x"] + (40 - r1["x"]), hd["y"] + (50 - r1["y"]))
        r2 = pg.evaluate(RECT)
        check(abs(r2["x"] - 40) <= 3 and abs(r2["y"] - 50) <= 3 and abs(r2["w"] - r1["w"]) < 1, f"move by the title bar (-> {r2['x']:.0f},{r2['y']:.0f})")
        hd = pg.evaluate(HEAD)
        drag(hd["x"], hd["y"], hd["x"] - 900, hd["y"] - 900)
        r3 = pg.evaluate(RECT)
        check(r3["x"] >= 0 and r3["y"] >= 0, f"cannot be dragged off screen ({r3['x']:.0f},{r3['y']:.0f})")
        drag(r3["x"] + 3, r3["y"] + r3["h"] / 2, r3["x"] - 300, r3["y"] + r3["h"] / 2)
        r4 = pg.evaluate(RECT)
        check(r4["x"] >= 0 and abs(r4["w"] - r3["w"]) < 1, "resize from the left edge stays on screen")
        hd = pg.evaluate(HEAD)
        drag(hd["x"], hd["y"], hd["x"] + 40, hd["y"] + 50)
        g = pg.evaluate("STATE.git.dwin")
        check(g and abs(g["x"] - 40) <= 3 and abs(g["w"] - 700) <= 4, f"place and size remembered ({g})")
        # the page underneath stays usable: another file -> a second, cascaded window
        pg.dblclick("#gitWin [data-page=changes] .gt-row:has-text('staged.txt')")
        pg.wait_for_function("GitUI.DW.wins.length === 2 && " + DIFF_READY, timeout=10000)
        rs = pg.evaluate("GitUI.DW.wins.map(w => w.g)")
        check(rs[1]["x"] - rs[0]["x"] == 26 and rs[1]["y"] - rs[0]["y"] == 26, "parent clickable while open: second file (double-click) -> second window, cascaded")
        check("staged.txt" in pg.evaluate("GitUI.DM.ident"), "new window in front")
        shot("2b-two-windows")
        # same file again -> the open window comes to the front, no third one
        pg.dblclick("#gitWin [data-page=changes] .gt-row:has-text('app.py')")
        pg.wait_for_function("GitUI.DM.ident.endsWith('|src/app.py')", timeout=5000)
        check(pg.evaluate("GitUI.DW.wins.length") == 2 and pg.evaluate("GitUI.DM.bg.classList.contains('front')"), "same file again: existing window to the front")
        # clicking a window brings it to the front
        p0 = pg.evaluate("(() => { const r = GitUI.DW.wins[0].bg.querySelector('.gdm-body').getBoundingClientRect(); return [r.left + 10, r.bottom - 10]; })()")
        pg.mouse.click(p0[0], p0[1])
        check(pg.evaluate("GitUI.DM.ident").endswith("|staged.txt"), "click on a window: to the front (z-order)")
        pg.evaluate("GitUI.DM.bg.focus()")
        pg.keyboard.press("Escape")
        check(pg.evaluate("GitUI.DW.wins.length") == 1 and pg.evaluate("GitUI.DM.ident").endswith("|src/app.py"), "Esc closes only the focused window")
        pg.evaluate("GitUI.DM.bg.focus()")
        # prev / next still walk the tree and move its selection
        n_files = pg.evaluate("GitUI.DM.items.length")
        i0 = pg.evaluate("GitUI.DM.idx")
        pg.click(".gdw [data-a=next]")
        pg.wait_for_function(f"GitUI.DM.idx === {i0 + 1} && " + DIFF_READY, timeout=10000)
        p1 = pg.evaluate("GitUI.DM.bg.querySelector('.gdm-path').textContent")
        check(p1 != "src/app.py" and pg.evaluate("document.querySelector('#gitWin [data-page=changes] .gt-row.sel').textContent").find(p1.split('/')[-1]) >= 0,
              f"↓: next file ({p1}), tree selection follows")
        pg.keyboard.press("ArrowUp")
        pg.wait_for_function(f"GitUI.DM.idx === {i0} && " + DIFF_READY, timeout=10000)
        check(pg.evaluate("GitUI.DM.bg.querySelector('.gdm-path').textContent") == "src/app.py", f"↑ goes back ({n_files} files)")
        pg.click(".gdw [data-a=mode]")
        check(pg.evaluate("STATE.git.inline === true && GitUI.DM.bg.querySelector('[data-a=mode]').textContent === 'Unified'"), "side-by-side / unified toggle")
        pg.click(".gdw [data-a=mode]")
        pg.click(".gdw [data-a=max]")
        m = pg.evaluate(RECT)
        check(m["x"] == 0 and m["y"] == 0 and m["w"] == 1500 and m["h"] == 950, "maximize")
        pg.click(".gdw [data-a=max]")
        check(abs(pg.evaluate(RECT)["w"] - 700) <= 4, "restore")
        pg.click(".gdw [data-a=close]")
        check(not pg.evaluate(MODAL), "✕ closes")
        check(pg.evaluate("document.querySelector('#gitWin [data-page=changes] .gt-row.sel').textContent.includes('app.py')"), "Git window keeps the selection after closing")
        # at most 8 windows: the oldest closes
        pg.evaluate("for (let i = 0; i < 9; i++) GitUI.openDiffWin([i], 0, x => Promise.resolve({path: 'f' + x + '.txt', left: 'a', right: 'b' + x}), {ident: x => 'T|' + x})")
        check(pg.evaluate("GitUI.DW.wins.length") == 8 and not pg.evaluate("GitUI.DW.wins.some(w => w.ident === 'T|0')"), "9th window closes the oldest (8 max)")
        check(pg.evaluate("GitUI.DW.wins.every(w => { const r = w.bg.getBoundingClientRect(); return r.left >= 0 && r.top >= 0 && r.right <= innerWidth && r.bottom <= innerHeight; })"),
              "cascaded windows stay on screen")
        pg.evaluate("while (GitUI.DW.wins.length) GitUI.closeDiffWin(GitUI.DW.wins[0])")
        # double-click: one window
        pg.dblclick("#gitWin [data-page=changes] .gt-row:has-text('app.py')")
        pg.wait_for_function(DIFF_READY, timeout=10000)
        time.sleep(0.3)
        check(pg.evaluate("GitUI.DW.wins.length") == 1, "double-click on a file: one window (no conflict)")
        # Open in Editor
        pg.click(".gdw [data-a=edit]")
        pg.wait_for_function("currentDoc() && currentDoc().key === 'basic/src/app.py'", timeout=10000)
        check(not pg.evaluate(MODAL), "Open in Editor opens the file and closes the window")
        # with the file open, the window diffs the live buffer; the editor stays clickable
        pg.dblclick("#gitWin [data-page=changes] .gt-row:has-text('app.py')")
        pg.wait_for_function(DIFF_READY, timeout=10000)
        check(pg.evaluate("GitUI.DM.ed.getModel().modified === currentDoc().model"), "open file -> right side is the editor buffer")
        pg.click(".pane .monaco-editor .view-line >> nth=-1")
        check(pg.evaluate("!!(document.activeElement && document.activeElement.closest('.pane'))") and pg.evaluate(MODAL),
              "editor clickable while the diff window is open")
        pg.evaluate("GitUI.DM.bg.focus()")
        pg.keyboard.press("Escape")
        check(pg.evaluate("!currentDoc().model.isDisposed()"), "closing the window keeps the editor model")

        print("== AgentO dialog")
        pg.evaluate("runCommand('git.agentCommit')")
        pg.wait_for_selector(".gx-dlg", timeout=10000)
        ta = pg.input_value(".gx-dlg textarea")
        check("커밋" in ta and "src/app.py" in ta and "staged.txt" in ta and "basic" in ta, "commit instruction lists the files + repo")
        check("untracked.txt" not in ta, "untracked files not included unless ticked")
        shot("3-agento")
        pg.click(".gx-dlg [data-a=cancel]")

        print("== Log (branches repo)")
        pg.evaluate("GitUI.selectRepo(GitUI.G.repos.find(r => r.name === 'branches').root)")
        pg.evaluate("GitUI.setTab('log')")
        pg.wait_for_function("document.querySelectorAll('#gitWin [data-page=log] .gl-row').length >= 15", timeout=20000)
        check(pg.evaluate("document.querySelectorAll('#gitWin [data-page=log] .gl-row svg path').length > 20"), "graph drawn")
        check(pg.evaluate("[...document.querySelectorAll('#gitWin .ref')].some(r => r.textContent === 'main')"), "branch labels")
        try:  # the branch list (refs) can arrive after the first log page
            pg.wait_for_function("(t => t && t.innerText.includes('feat') && t.innerText.includes('Remote'))(document.querySelector('#gitWin .gb-tree'))", timeout=10000)
        except Exception:
            pass
        check("feat" in pg.inner_text("#gitWin .gb-tree") and "Remote" in pg.inner_text("#gitWin .gb-tree"), "branch tree")
        pg.click("#gitWin [data-page=log] .gl-row[data-i='1']")
        pg.wait_for_function("document.querySelector('#gitWin [data-page=log] .gd-msg').textContent.length > 10", timeout=10000)
        check(pg.evaluate("document.querySelectorAll('#gitWin [data-page=log] .gd-files .gt-row').length > 0"), "commit details: changed files")
        shot("4-log")
        top = pg.evaluate("document.querySelector('#gitWin [data-page=log] .gl-list').scrollTop")
        pg.click("#gitWin [data-page=log] .gd-files .gt-row:not(.group) .st >> nth=0")
        pg.wait_for_function(DIFF_READY, timeout=10000)
        h = pg.evaluate("GitUI.Log.rows[GitUI.Log.selIdx].c.h.slice(0, 8)")
        check(pg.evaluate("GitUI.DM.bg.querySelector('.gdm-hash').textContent") == h, f"log file click: diff window title has the commit hash {h}")
        shot("4b-log-diff")
        pg.keyboard.press("Escape")
        check(not pg.evaluate(MODAL) and pg.evaluate("GitUI.Log.selIdx") == 1 and
              pg.evaluate("document.querySelector('#gitWin [data-page=log] .gl-list').scrollTop") == top, "log keeps the selected commit and scroll")
        # branch filter from the tree
        pg.click("#gitWin .gb-row[data-ref='refs/heads/feat/one']")
        pg.wait_for_function("document.querySelectorAll('#gitWin [data-page=log] .gl-row').length === 4", timeout=10000)
        check(True, "branch tree click filters the log (4 commits)")
        pg.click("#gitWin .gb-row[data-ref='refs/heads/feat/one']")
        pg.wait_for_function("document.querySelectorAll('#gitWin [data-page=log] .gl-row').length >= 15", timeout=10000)
        pg.fill("#gitWin [data-page=log] .gl-filter input.q", "feat/two")
        pg.wait_for_function("GitUI.Log.rows.length > 0 && GitUI.Log.rows.every(r => r.c.s.includes('feat/two'))", timeout=10000)
        check(True, "text filter")
        pg.fill("#gitWin [data-page=log] .gl-filter input.q", "")
        pg.wait_for_function("GitUI.Log.rows.length >= 15", timeout=10000)

        print("== Log: several commits selected (Ctrl / Shift)")
        pg.evaluate("GitUI.selectRepo(GitUI.G.repos.find(r => r.name === 'basic').root)")
        pg.evaluate("GitUI.setTab('log')")
        pg.wait_for_function("GitUI.G.repo.name === 'basic' && GitUI.Log.rows.length === 20 && document.querySelector('#gitWin [data-page=log] .gl-row')", timeout=20000)
        ROW = lambda i: f"#gitWin [data-page=log] .gl-row[data-i='{i}']"
        SUM = "document.querySelector('#gitWin [data-page=log] .gd-sum')"
        def files_tree():
            return pg.evaluate("[...document.querySelectorAll('#gitWin [data-page=log] .gd-files .gt-row')].map(r => r.innerText.replace(/\\s+/g, ' ').trim())")
        pg.click(ROW(0))
        pg.wait_for_function("GitUI.Log.detail && GitUI.Log.detail.h === GitUI.Log.rows[0].c.h", timeout=10000)
        pg.evaluate("GitUI.Log.list.scrollTop = 0")
        pg.click(ROW(2), modifiers=["Control"])
        pg.evaluate("GitUI.Log.list.scrollTop = 16 * 22 - 40")
        time.sleep(0.2)
        pg.click(ROW(16), modifiers=["Control"])
        # the 3-commit summary, not the finished 2-commit one still shown until the next load starts (150 ms later)
        pg.wait_for_function(SUM + ".style.display === 'block' && " + SUM + ".innerText.includes('3 commits selected') && " + SUM + ".innerText.includes('files') && !" + SUM + ".innerText.includes('loading')", timeout=15000)
        sel = pg.evaluate("[...GitUI.Log.selH].map(h => GitUI.Log.rows.findIndex(r => r.c.h === h)).sort((a, b) => a - b)")
        check(sel == [0, 2, 16], f"Ctrl+click: rows 0, 2, 16 selected ({sel})")
        pg.evaluate("GitUI.Log.list.scrollTop = 0"); time.sleep(0.2)
        check(pg.evaluate("[...document.querySelectorAll('#gitWin [data-page=log] .gl-row.sel')].map(r => +r.dataset.i).filter(i => i < 8).join(',')") == "0,2",
              "selected rows highlighted")
        sm = pg.evaluate(SUM + ".innerText")
        check("3 commits selected" in sm and "not one range" in sm, f"summary: '3 commits selected', not one range + what a diff compares ({sm[:90]!r})")
        ft = files_tree()
        check(any(t.startswith("M app.py") and "3 commits" in t and "+3" in t for t in ft) and any("crlf.txt" in t and t.startswith("A") for t in ft)
              and any("src" in t and "1 file" in t for t in ft) and sum("app.py" in t for t in ft) == 1,
              f"merged files: app.py once (3 commits, +3), added files A, folders kept ({ft})")
        shot("4e-log-multi")
        pg.click("#gitWin [data-page=log] .gd-files .gt-row:has-text('app.py')")
        pg.wait_for_function(DIFF_READY, timeout=10000)
        hd = pg.evaluate("GitUI.DM.bg.querySelector('.gdm-hash').textContent")
        base_ok = pg.evaluate("GitUI.Log.multi.base.slice(0, 8) + '..' + GitUI.Log.multi.head.slice(0, 8)") == hd
        check(base_ok and pg.evaluate("GitUI.DM.ed.getModel().original.getValue().split('\\n').length < GitUI.DM.ed.getModel().modified.getValue().split('\\n').length"),
              f"file diff: parent of the oldest .. newest ({hd})")
        pg.keyboard.press("Escape")
        pg.wait_for_function("!(" + MODAL + ")", timeout=5000)
        pg.click(ROW(0), button="right")
        pg.wait_for_selector("#ctxMenu", timeout=5000)
        mi = pg.evaluate("[...document.querySelectorAll('#ctxMenu .ctx-item')].map(e => [e.dataset.label, e.classList.contains('disabled')])")
        md = dict(mi)
        check(md.get("Copy Revision Numbers (3)") is False and md.get("Cherry-Pick… (AgentO)") is True and md.get("Show in Log") is True,
              f"right-click keeps the selection; only copy entries enabled ({mi[:3]})")
        pg.keyboard.press("Escape")
        check(pg.evaluate("GitUI.Log.selH.size") == 3, "right-click on a selected row keeps all 3")
        # Shift+click: a range from the anchor; adjacent rows -> one range diff
        pg.click(ROW(1))
        pg.click(ROW(3), modifiers=["Shift"])
        pg.wait_for_function(SUM + ".innerText.includes('one range: changes')", timeout=15000)
        check(pg.evaluate("[...GitUI.Log.selH].length") == 3 and "3 commits selected" in pg.evaluate(SUM + ".innerText"),
              "Shift+click: rows 1-3, one range (changes base → newest)")
        ft = files_tree()
        check(any(t.startswith("M app.py") and "+3" in t and "commits" not in t for t in ft), f"range files: base..newest with counts ({ft})")
        pg.keyboard.press("Shift+ArrowDown")
        pg.wait_for_function("GitUI.Log.selH.size === 4 && " + SUM + ".innerText.includes('4 commits selected') && " + SUM + ".innerText.includes('one range: changes')", timeout=15000)
        check(True, "Shift+↓ extends the range (4 commits)")
        pg.keyboard.press("Control+a")
        pg.wait_for_function("GitUI.Log.selH.size === 20 && " + SUM + ".innerText.includes('20 commits selected')", timeout=15000)
        check(True, "Ctrl+A: all loaded commits (20)")
        pg.keyboard.press("Control+c")
        check(pg.evaluate("GitUI.Log.selected().length") == 20, "Ctrl+C with several selected: copies the hash list")
        # back to one commit: the single-commit details as before
        pg.click(ROW(1))
        pg.wait_for_function("GitUI.Log.selH.size === 1 && GitUI.Log.detail && GitUI.Log.detail.h === GitUI.Log.rows[1].c.h", timeout=10000)
        one = pg.evaluate("({sum: " + SUM + ".style.display, msg: document.querySelector('#gitWin [data-page=log] .gd-msg').innerText, "
                          "sel: document.querySelectorAll('#gitWin [data-page=log] .gl-row.sel').length})")
        check(one["sum"] == "none" and one["msg"].startswith("commit 18") and one["sel"] == 1 and any("app.py" in t for t in files_tree()),
              f"plain click: one commit again (message, files, no summary) ({one['msg'][:20]!r})")
        pg.click("#gitWin [data-page=log] .gd-files .gt-row:has-text('app.py')")
        pg.wait_for_function(DIFF_READY, timeout=10000)
        check(pg.evaluate("GitUI.DM.bg.querySelector('.gdm-hash').textContent") == pg.evaluate("GitUI.Log.rows[1].c.h.slice(0, 8)"), "single commit: file diff as before")
        pg.keyboard.press("Escape")
        pg.wait_for_function("!(" + MODAL + ")", timeout=5000)
        pg.evaluate("GitUI.selectRepo(GitUI.G.repos.find(r => r.name === 'branches').root)")
        pg.wait_for_function("GitUI.G.repo.name === 'branches' && GitUI.Log.rows.length >= 15", timeout=20000)

        print("== Log columns: resize / show-hide / saved")
        LOGP = "#gitWin [data-page=log]"
        COLS = """(() => { const p = document.querySelector('#gitWin [data-page=log]'), row = p.querySelector('.gl-row'), head = p.querySelector('.gl-head');
          const w = (el, k) => { const e = el.querySelector('.' + k); return e && getComputedStyle(e).display !== 'none' ? Math.round(e.getBoundingClientRect().width) : 0; };
          const list = p.querySelector('.gl-list'), m = row.querySelector('.msg').getBoundingClientRect();
          const rightOf = [...row.children].filter(e => getComputedStyle(e).display !== 'none' && e !== row.querySelector('.msg') && e.tagName !== 'svg');
          return { au: w(row, 'au'), dt: w(row, 'dt'), hs: w(row, 'hs'), hau: w(head, 'au'), hdt: w(head, 'dt'), hhs: w(head, 'hs'),
                   aligned: ['au', 'dt', 'hs'].every(k => { const a = row.querySelector('.' + k), b = head.querySelector('.' + k);
                     return getComputedStyle(a).display === 'none' || Math.abs(a.getBoundingClientRect().left - b.getBoundingClientRect().left) < 1.5; }),
                   msgW: m.width, msgToNext: rightOf.length ? rightOf[0].getBoundingClientRect().left - m.right : list.getBoundingClientRect().right - m.right,
                   hscroll: list.scrollWidth > list.clientWidth, st: JSON.parse(JSON.stringify(STATE.git.logCols)) }; })()"""
        c0 = pg.evaluate(COLS)
        check(pg.evaluate(f"document.querySelector('{LOGP} .gl-head').innerText.replace(/\\s+/g, ' ').trim()") == "Subject Author Date Hash", "column header: Subject Author Date Hash")
        check((c0["au"], c0["dt"], c0["hs"]) == (100, 125, 70) and c0["aligned"], f"default widths fit the content: Author 100, Date 125, Hash 70 ({c0['au']}, {c0['dt']}, {c0['hs']}), header aligned")
        # dates fit the narrower column (no ellipsis)
        clipped = pg.evaluate(f"[...document.querySelectorAll('{LOGP} .gl-row .dt, {LOGP} .gl-row .hs')].filter(e => e.scrollWidth > e.clientWidth).map(e => e.textContent).slice(0, 3)")
        check(not clipped, f"date / hash text fits its default width ({clipped})")
        def drag_edge(k, dx):
            r = pg.evaluate(f"(() => {{ const b = document.querySelector('{LOGP} .gl-head .gl-rs[data-c={k}]').getBoundingClientRect(); return {{x: b.left + b.width / 2, y: b.top + b.height / 2}}; }})()")
            pg.mouse.move(r["x"], r["y"]); pg.mouse.down(); pg.mouse.move(r["x"] + dx / 2, r["y"]); pg.mouse.move(r["x"] + dx, r["y"]); pg.mouse.up()
            return r
        drag_edge("au", -40)
        c1 = pg.evaluate(COLS)
        check(c1["au"] == 140 and c1["hau"] == 140 and c1["st"]["au"]["w"] == 140 and c1["aligned"], f"drag the Author edge left 40px: 100 -> {c1['au']} (header + rows + state)")
        drag_edge("dt", 300)
        c2 = pg.evaluate(COLS)
        check(c2["dt"] == 60, f"minimum width: Date stops at 60 ({c2['dt']})")
        r = pg.evaluate(f"(() => {{ const b = document.querySelector('{LOGP} .gl-head .gl-rs[data-c=dt]').getBoundingClientRect(); return {{x: b.left + b.width / 2, y: b.top + b.height / 2}}; }})()")
        pg.mouse.dblclick(r["x"], r["y"])
        check(pg.evaluate(COLS)["dt"] == 125, "double-click the edge: default width back")
        pg.click(f"{LOGP} .gl-head .msg", button="right")
        pg.wait_for_selector("#ctxMenu", timeout=5000)
        menu = pg.evaluate("[...document.querySelectorAll('#ctxMenu .ctx-item')].map(e => [e.dataset.label, e.classList.contains('checked'), e.classList.contains('disabled')])")
        check([m[0] for m in menu][:4] == ["Subject", "Author", "Date", "Hash"] and all(m[1] for m in menu[:4]) and menu[0][2],
              f"header right-click: column checkboxes, Subject always on ({menu})")
        pg.click("#ctxMenu .ctx-item[data-label='Hash']")
        pg.click(f"{LOGP} .gl-head .msg", button="right")
        pg.click("#ctxMenu .ctx-item[data-label='Date']")
        c3 = pg.evaluate(COLS)
        check(c3["hs"] == 0 and c3["dt"] == 0 and c3["hhs"] == 0 and c3["au"] == 140 and not c3["st"]["hs"]["on"] and not c3["st"]["dt"]["on"]
              and abs(c3["msgToNext"]) < 1.5, f"Hash + Date hidden: rows and header, the message takes the room ({c3['msgW']:.0f}px)")
        shot("4c-log-columns")
        # narrow Git window: no horizontal scroll, the message keeps the rest
        pg.click(f"{LOGP} .gl-head .msg", button="right"); pg.click("#ctxMenu .ctx-item[data-label='Date']")
        pg.click(f"{LOGP} .gl-head .msg", button="right"); pg.click("#ctxMenu .ctx-item[data-label='Hash']")
        for vw in (1000, 760):
            pg.set_viewport_size({"width": vw, "height": 950})
            time.sleep(0.4)
            c4 = pg.evaluate(COLS)
            lw = pg.evaluate(f"document.querySelector('{LOGP} .gl-list').clientWidth")
            check(not c4["hscroll"] and c4["aligned"] and c4["msgW"] >= 0.3 * lw - 60,  # 60: the graph lanes sit left of the message
                  f"narrow window ({vw}px, list {lw}px): no horizontal scroll, message {c4['msgW']:.0f}px, columns {c4['au']}/{c4['dt']}/{c4['hs']}, header aligned")
            if vw == 1000:
                shot("4d-log-narrow")
        pg.set_viewport_size({"width": 1500, "height": 950})
        time.sleep(0.3)
        # saved: state.json on disk, and a fresh page (next run) starts with the same columns
        pg.click(f"{LOGP} .gl-head .msg", button="right"); pg.click("#ctxMenu .ctx-item[data-label='Hash']")
        pg.evaluate("flushState()")
        time.sleep(0.5)
        import json
        with open(os.path.join(tmp, "state.json"), encoding="utf-8") as f:
            st = json.load(f)
        lc = (st.get("ui", st).get("git") or {}).get("logCols") or {}
        check(lc.get("au", {}).get("w") == 140 and lc.get("hs", {}).get("on") is False and lc.get("dt", {}).get("on") is True,
              f"state.json keeps widths + visibility ({lc})")
        pg2 = b.new_page(viewport={"width": 1500, "height": 950})
        pg2.goto(url)
        pg2.wait_for_function("typeof monaco !== 'undefined' && window.GitUI", timeout=30000)
        pg2.evaluate("GitUI.toggleWindow(true)")
        pg2.wait_for_function("GitUI.G.repo", timeout=20000)
        pg2.evaluate("GitUI.setTab('log')")
        pg2.wait_for_function("document.querySelectorAll('#gitWin [data-page=log] .gl-row').length > 3", timeout=20000)
        c5 = pg2.evaluate(COLS)
        check(c5["au"] == 140 and c5["hs"] == 0 and c5["dt"] == 125, f"next run: same widths / hidden columns ({c5['au']}, {c5['dt']}, {c5['hs']})")
        pg2.close()
        pg.click(f"{LOGP} .gl-head .msg", button="right"); pg.click("#ctxMenu .ctx-item[data-label='Hash']")
        pg.click(f"{LOGP} .gl-head .msg", button="right"); pg.click("#ctxMenu .ctx-item[data-label='Reset Column Widths']")
        check(pg.evaluate(COLS)["au"] == 100, "Reset Column Widths")

        print("== Log (30k commits): paging + virtual scroll")
        t0 = time.time()
        pg.evaluate("GitUI.selectRepo(GitUI.G.repos.find(r => r.name === 'huge').root)")
        pg.evaluate("GitUI.setTab('log')")
        try:
            pg.wait_for_function("GitUI.Log.rows.length >= 300", timeout=30000)
        except Exception:
            print(pg.evaluate("({repo: GitUI.G.repo.name, rows: GitUI.Log.rows.length, built: GitUI.Log.built, loaded: GitUI.Log.loaded,"
                              " loading: GitUI.Log.loading, cnt: GitUI.Log.cnt && GitUI.Log.cnt.textContent, f: JSON.stringify(GitUI.Log.filters),"
                              " tab: STATE.git.tab, page: document.querySelector('#gitWin [data-page=log]').innerText.slice(0, 300)})"))
            raise
        first = (time.time() - t0) * 1000
        check(first < 3000, f"first page shown in {first:.0f} ms")
        check(pg.evaluate("document.querySelectorAll('#gitWin [data-page=log] .gl-row').length") < 120, "only visible rows in the DOM")
        t0 = time.time()
        for _ in range(6):
            pg.evaluate("const l = document.querySelector('#gitWin [data-page=log] .gl-list'); l.scrollTop = l.scrollHeight")
            time.sleep(0.35)
        n = pg.evaluate("GitUI.Log.rows.length")
        check(n > 1500, f"scrolling loads more pages ({n} rows)")
        shot("5-log-huge")
        lanes = pg.evaluate("Math.max(...GitUI.Log.rows.map(r => r.g.after.length))")
        check(lanes <= 6, f"lanes stay bounded ({lanes})")

        print("== History / blame / stash / console")
        pg.evaluate("openFile('rename/new/renamed.txt')")
        pg.wait_for_function("currentDoc() && currentDoc().key === 'rename/new/renamed.txt'", timeout=10000)
        pg.evaluate("runCommand('git.history')")
        pg.wait_for_function("GitUI.History && GitUI.History.rows.length === 4", timeout=15000)
        check(True, "file history follows the rename (4 commits)")
        shot("6-history")
        pg.dblclick("#gitWin [data-page=history] .gl-row[data-i='1']")
        pg.wait_for_function(DIFF_READY, timeout=10000)
        check(pg.evaluate("GitUI.DM.items.length") == 4 and "renamed.txt" in pg.evaluate("GitUI.DM.bg.querySelector('.gdm-path').textContent"),
              "history row: modal walks the file's revisions")
        pg.keyboard.press("Escape")
        pg.evaluate("runCommand('git.blame')")
        pg.wait_for_function("GitUI.G.blame.size === 1", timeout=15000)
        time.sleep(0.5)
        check(pg.evaluate("document.querySelectorAll('.gbl').length >= 3"), "blame column in the editor")
        shot("7-blame")
        pg.evaluate("runCommand('git.blame')")
        pg.wait_for_function("GitUI.G.blame.size === 0 && !document.querySelector('.gbl')", timeout=5000)
        check(True, "blame toggles off")

        print("== Annotate with Git Blame (editor / gutter right-click, hover, click, line end)")
        def editor_menu():  # Monaco's menu lives in a shadow root: locators pierce it, querySelector does not
            pg.click(".pane .monaco-editor .view-line >> nth=0", button="right")
            pg.locator(".monaco-menu .action-label", has_text="Annotat").first.wait_for(timeout=5000)
            return [t.strip() for t in pg.locator(".monaco-menu .action-label").all_inner_texts()]
        items = editor_menu()
        check("Annotate with Git Blame" in items and "Close Annotations" not in items, f"editor right-click: Annotate with Git Blame ({items[:6]})")
        time.sleep(0.4)  # Monaco ignores a click right as its menu opens
        pg.locator(".monaco-menu .action-label", has_text="Annotate with Git Blame").click()
        pg.wait_for_function("GitUI.G.blame.size === 1 && document.querySelectorAll('.gbl').length >= 3", timeout=15000)
        check(True, "menu entry turns the annotations on")
        time.sleep(0.4)
        lay = pg.evaluate("""(() => {
          const ed = document.querySelector('.pane .monaco-editor'), e = ed.getBoundingClientRect();
          const rows = [...ed.querySelectorAll('.margin-view-overlays > div')].filter(d => d.querySelector('.cmdr.gbl'));
          const r = rows.sort((x, y) => x.getBoundingClientRect().top - y.getBoundingClientRect().top).map(d => {
            const g = d.querySelector('.cmdr.gbl'), n = d.querySelector('.line-numbers'), sh = d.querySelector('.cmdr.gba');
            const cls = /gbc-(\\d+)/.exec(g.className)[1];
            const range = document.createRange(); range.selectNodeContents(n);
            return { text: getComputedStyle(g, '::before').content, num: n.textContent.trim(), c: +cls,
                     gl: g.getBoundingClientRect().left - e.left, gr: g.getBoundingClientRect().right - e.left,
                     nl: range.getBoundingClientRect().left - e.left, bg: getComputedStyle(sh).backgroundColor };
          });
          const code = ed.querySelector('.view-line').getBoundingClientRect().left - e.left;
          return { rows: r, code, lines: GitUI.G.blame.get(currentDoc().key).data.lines.length };
        })()""")
        rows = lay["rows"]
        check(rows and all(r["gl"] < 2 and r["gr"] <= r["nl"] and r["nl"] < lay["code"] for r in rows),
              f"column order: annotation | line number | code ({rows[0]['gl']:.0f}-{rows[0]['gr']:.0f} | {rows[0]['nl']:.0f} | {lay['code']:.0f})")
        check(all(re.fullmatch(r'"\d{1,2}/\d{1,2}/\d{4} \S.*"', r["text"]) for r in rows), f"M/D/YYYY author on every line ({rows[0]['text']})")
        check(len(rows) == lay["lines"] and [r["num"] for r in rows] == [str(i + 1) for i in range(len(rows))],
              "one annotation per line, on the line's own row")
        alpha = lambda bg: float(bg.split(",")[3].strip(" )")) if bg.startswith("rgba") else (0.0 if bg in ("transparent", "rgba(0, 0, 0, 0)") else 1.0)
        times = pg.evaluate("GitUI.G.blame.get(currentDoc().key).data.commits.map(c => c.at)")
        same = all(r1["bg"] == r2["bg"] for r1 in rows for r2 in rows if r1["c"] == r2["c"])
        by_age = sorted({r["c"]: r for r in rows}.values(), key=lambda r: times[r["c"]])
        darker = all(alpha(x["bg"]) < alpha(y["bg"]) for x, y in zip(by_age, by_age[1:]))
        check(same and darker and alpha(by_age[0]["bg"]) == 0, f"block shade per commit: oldest unshaded, newer darker ({[r['bg'] for r in by_age]})")
        # word wrap: annotation text stays on the line's first row, the shade covers every row
        pg.evaluate("currentPane().editor.updateOptions({wordWrap: 'wordWrapColumn', wordWrapColumn: 1})")
        time.sleep(0.4)
        wr = pg.evaluate("""(() => { const ed = document.querySelector('.pane .monaco-editor');
          const rows = [...ed.querySelectorAll('.margin-view-overlays > div')];
          const lh = currentPane().editor.getOption(monaco.editor.EditorOption.lineHeight);
          return { texts: rows.filter(d => d.querySelector('.cmdr.gbl')).map(d => d.querySelector('.line-numbers').textContent.trim()),
                   shaded: rows.filter(d => d.querySelector('.cmdr.gba')).length, all: rows.length,
                   heights: [...new Set(rows.map(d => Math.round(d.getBoundingClientRect().height)))], lh }; })()""")
        check(wr["texts"] == [str(i + 1) for i in range(len(wr["texts"]))] and wr["shaded"] >= 2 * len(wr["texts"]),
              f"word wrap: text on the first row only, shade on all rows ({len(wr['texts'])} lines, {wr['shaded']} shaded rows)")
        check(wr["heights"] == [wr["lh"]], f"word wrap: every gutter row keeps the line height ({wr['heights']} vs {wr['lh']})")
        pg.evaluate("currentPane().editor.updateOptions({wordWrap: STATE.wordWrap ? 'on' : 'off'})")
        shot("7a-annotate")
        items = editor_menu()
        check("Close Annotations" in items and "Annotate with Git Blame" not in items, f"editor right-click: Close Annotations while on ({items[:6]})")
        pg.keyboard.press("Escape")
        box = pg.locator(".pane .gbl >> nth=0").bounding_box()
        pg.mouse.move(box["x"] + 30, box["y"] + box["height"] / 2)
        pg.wait_for_function("(() => { const t = document.querySelector('.gbl-tip'); return t && t.style.display === 'block'; })()", timeout=5000)
        tip = pg.evaluate("document.querySelector('.gbl-tip').innerText")
        check(re.fullmatch(TIP_RE, tip), f"hover tooltip: commit <full hash> / Author: name <mail> / Date: M/D/YYYY h:mm AM / blank / message ({tip!r})")
        shot("7b-blame-tip")
        pg.mouse.click(box["x"] + 30, box["y"] + box["height"] / 2, button="right")
        pg.wait_for_selector("#ctxMenu", timeout=5000)
        labels = pg.evaluate("[...document.querySelectorAll('#ctxMenu .ctx-item')].map(e => e.dataset.label)")
        check("Close Annotations" in labels and any(x.startswith("Show Diff") for x in labels) and "Show Commit in Git Log" in labels,
              f"gutter right-click menu ({labels})")
        pg.keyboard.press("Escape")
        pg.mouse.click(box["x"] + 30, box["y"] + box["height"] / 2)
        pg.wait_for_function(DIFF_READY, timeout=15000)
        head = pg.evaluate("({hash: GitUI.DM.bg.querySelector('.gdm-hash').textContent, path: GitUI.DM.bg.querySelector('.gdm-path').textContent})")
        check(len(head["hash"]) == 8 and head["path"].endswith("name.txt"), f"annotation click: the commit's diff in the modal, at this file ({head})")
        shot("7c-blame-commit")
        pg.keyboard.press("Escape")
        pg.wait_for_function("!(" + MODAL + ")", timeout=5000)
        pg.mouse.click(box["x"] + 30, box["y"] + box["height"] / 2, button="right")
        pg.click("#ctxMenu .ctx-item[data-label='Close Annotations']")
        pg.wait_for_function("GitUI.G.blame.size === 0 && !document.querySelector('.gbl')", timeout=5000)
        check(True, "gutter menu: Close Annotations")
        pg.click(".pane .margin .line-numbers >> nth=0", button="right")  # the annotation column is gone
        pg.wait_for_selector("#ctxMenu", timeout=5000)
        labels = pg.evaluate("[...document.querySelectorAll('#ctxMenu .ctx-item')].map(e => e.dataset.label)")
        check("Annotate with Git Blame" in labels, f"gutter right-click: Annotate with Git Blame when off ({labels})")
        pg.keyboard.press("Escape")
        check(pg.evaluate("!document.querySelector('.glb-inline') && STATE.git.lineBlame === false"), "line-end commit: off by default")
        pg.evaluate("GitUI.toggleLineBlame(true); currentPane().editor.setPosition({lineNumber: 1, column: 1}); currentPane().editor.focus()")
        pg.wait_for_function("(document.querySelector('.glb-inline') || {}).textContent", timeout=10000)
        txt = pg.evaluate("document.querySelector('.glb-inline').textContent").replace(" ", " ")
        check(" · " in txt, f"line-end commit: author, date · message ({txt!r})")
        shot("7d-line-blame")
        pg.evaluate("GitUI.toggleLineBlame(false)")
        pg.wait_for_function("!document.querySelector('.glb-inline')", timeout=5000)
        check(True, "line-end commit: turns off")
        # consecutive lines of one commit: IntelliJ repeats "date author" on each, not only on the block's first line
        pg.evaluate("openFile('basic/src/app.py')")
        pg.wait_for_function("currentDoc() && currentDoc().key === 'basic/src/app.py'", timeout=10000)
        pg.evaluate("GitUI.toggleBlame(true)")
        pg.wait_for_function("GitUI.G.blame.has('basic/src/app.py') && document.querySelectorAll('.pane .gbl').length >= 6", timeout=15000)
        time.sleep(0.4)
        run = pg.evaluate("""(() => {
          const ed = document.querySelector('.pane .monaco-editor'), d = GitUI.G.blame.get('basic/src/app.py').data;
          const byNum = {};
          for (const r of ed.querySelectorAll('.margin-view-overlays > div')) {
            const g = r.querySelector('.cmdr.gbl'); if (!g) continue;
            byNum[r.querySelector('.line-numbers').textContent.trim()] = { text: getComputedStyle(g, '::before').content, c: +/gbc-(\\d+)/.exec(g.className)[1] };
          }
          return { rows: [2, 3, 4, 5, 6].map(n => byNum[n]), idx: d.lines.slice(1, 6) };
        })()""")
        same = run["rows"] and all(r for r in run["rows"]) and len({r["c"] for r in run["rows"]}) == 1 and len(set(run["idx"])) == 1
        check(same and all(re.fullmatch(r'"\d{1,2}/\d{1,2}/\d{4} \S.*"', r["text"]) for r in run["rows"])
              and len({r["text"] for r in run["rows"]}) == 1,
              f"same-commit run (lines 2-6): 'date author' on every line ({[r and r['text'] for r in run['rows']]})")
        shot("7e-blame-run")
        b2 = pg.locator(".pane .margin-view-overlays > div:has(.line-numbers:text-is('4')) .gbl").bounding_box()
        pg.mouse.move(b2["x"] + 30, b2["y"] + b2["height"] / 2)
        pg.wait_for_function("(() => { const t = document.querySelector('.gbl-tip'); return t && t.style.display === 'block' && t.innerText.includes('body line for 0'); })()", timeout=10000)
        tip = pg.evaluate("document.querySelector('.gbl-tip').innerText")
        check(re.fullmatch(TIP_RE, tip) and tip.endswith("\n\ncommit 0\n\nbody line for 0") and "alice@example.com" in tip,
              f"tooltip on a run's middle line: full message after the blank line ({tip!r})")
        shot("7f-blame-tip-body")
        pg.mouse.move(5, 5)
        pg.evaluate("GitUI.clearBlame(currentDoc())")
        pg.evaluate("GitUI.selectRepo(GitUI.G.repos.find(r => r.name === 'branches').root)")
        pg.evaluate("GitUI.setTab('stash')")
        pg.wait_for_function("document.querySelectorAll('#gitWin .st-list .gt-row').length === 1", timeout=10000)
        pg.click("#gitWin .st-list .gt-row")
        pg.wait_for_function("document.querySelectorAll('#gitWin .st-files .gt-row').length > 0", timeout=10000)
        check(True, "stash list + files")
        pg.click("#gitWin .st-files .gt-row:not(.group) .st >> nth=0")
        pg.wait_for_function(DIFF_READY, timeout=10000)
        check(pg.evaluate("GitUI.DM.ed.getModel().modified.getValue()").startswith("stashed change"), "stash file click: modal diff")
        pg.keyboard.press("Escape")
        check(not pg.evaluate(MODAL), "stash modal closes")
        pg.evaluate("GitUI.setTab('console')")
        pg.wait_for_function("document.querySelectorAll('#gitWin .gc-row').length > 5", timeout=10000)
        check(True, "console lists git commands")
        shot("8-console")

        print("== conflicts + tree colours + status bar")
        pg.evaluate("GitUI.selectRepo(GitUI.G.repos.find(r => r.name === 'conflict').root)")
        pg.evaluate("GitUI.setTab('changes')")
        pg.wait_for_function("document.querySelector('#gitWin [data-page=changes] .gw-banner').style.display === ''", timeout=10000)
        check("MERGING" in pg.inner_text("#gitWin [data-page=changes] .gw-banner"), "merge banner")
        pg.evaluate("openFile('conflict/c.txt')")
        pg.wait_for_function("document.querySelectorAll('.gconf-mark').length >= 2", timeout=15000)
        check(True, "conflict markers highlighted in the editor")
        shot("9-conflict")
        pg.click("#tree .node[data-path='basic']")
        pg.wait_for_function("document.querySelector(\"#tree .node[data-path='basic/untracked.txt']\")", timeout=10000)
        pg.wait_for_function("document.querySelector(\"#tree .node[data-path='basic/untracked.txt']\").classList.contains('gs-U')", timeout=15000)
        check(True, "tree colours (untracked)")
        check(pg.evaluate("document.querySelector(\"#tree .node[data-path='basic/src']\").classList.contains('gd-M')"), "folder with changes marked")
        sb = pg.inner_text("#sbBranch")
        check("main" in sb or "MERGING" in sb, f"status bar branch: {sb!r}")
        shot("10-tree")
        pg.evaluate("setKeymap('intellij')")
        pg.evaluate("GitUI.toggleWindow(false)")
        pg.keyboard.press("Alt+9")
        check(pg.evaluate("document.getElementById('gitWin').classList.contains('show')"), "Alt+9 opens the Git tool window (IntelliJ keymap)")
        pg.evaluate("setKeymap('vscode')")
        pg.keyboard.press("Control+Shift+G")
        check(not pg.evaluate("document.getElementById('gitWin').classList.contains('show')"), "Ctrl+Shift+G toggles it (VS Code keymap)")

        print("== diff windows as OS windows (fake backend; the window's page in its own tab)")
        import gitview
        made = []

        class FakeBE:
            def create(self, wid, path, title):
                made.append(("create", wid, path, title))
                return wid

            def focus(self, h):
                made.append(("focus", h))

            def close(self, h):
                made.append(("close", h))

            def set_title(self, h, t):
                made.append(("title", h, t))

            def open_in_main(self, key, line):
                made.append(("open", key, line))

        def wait_made(kind, n=1, timeout=10):
            end = time.time() + timeout
            while time.time() < end:
                if len([m for m in made if m[0] == kind]) >= n:
                    return True
                time.sleep(0.1)
            return False
        gitview.DIFFWIN.backend = FakeBE()
        try:
            pg.evaluate("GitUI.G.nativeWin = undefined; while (GitUI.DW.wins.length) GitUI.closeDiffWin(GitUI.DW.wins[0]); GitUI.toggleWindow(true)")
            pg.evaluate("GitUI.selectRepo(GitUI.G.repos.find(r => r.name === 'basic').root)")
            pg.evaluate("GitUI.setTab('changes')")
            pg.wait_for_selector("#gitWin [data-page=changes] .gt-row:has-text('app.py')", timeout=20000)
            pg.dblclick("#gitWin [data-page=changes] .gt-row:has-text('app.py')")
            check(wait_made("create"), "double-click: an OS window is asked for")
            time.sleep(0.5)
            cr = [m for m in made if m[0] == "create"][0]
            check(cr[3] == "app.py · local changes" and cr[2].startswith("/diffwin?id=") and pg.evaluate("GitUI.DW.wins.length") == 0,
                  f"title 'file · revision', no in-page panel ({cr[3]})")
            pg.dblclick("#gitWin [data-page=changes] .gt-row:has-text('app.py')")
            check(wait_made("focus") and len([m for m in made if m[0] == "create"]) == 1, "same file again: the window comes to the front (no new one)")
            dw = b.new_page(viewport={"width": 1100, "height": 700})
            dw.on("pageerror", lambda e: errors.append("diffwin: " + str(e)))
            dw.goto(url.rstrip("/") + cr[2])
            READY = "window.DiffWin && DiffWin.ed && DiffWin.ed.getModel() && document.querySelector('.gdm-msg').style.display === 'none'"
            dw.wait_for_function(READY, timeout=20000)
            check(dw.evaluate("DiffWin.ed.getModel().original.getValue().startsWith('line 0') && DiffWin.ed.getModel().modified.getValue().startsWith('changed')"),
                  "diff window page: HEAD left, working tree right")
            check(dw.title() == "app.py · local changes" and dw.evaluate("document.querySelector('.gdm-path').textContent") == "src/app.py",
                  "diff window page: title + path")
            n = dw.evaluate("DiffWin.ed && document.querySelector('.gdm-pos').textContent")
            dw.click("body", position={"x": 5, "y": 5})
            dw.keyboard.press("ArrowDown")
            dw.wait_for_function("DiffWin.idx === 1 && " + READY, timeout=10000)
            check(wait_made("title") and made[[m[0] for m in made].index("title")][2] == dw.title(), f"↓ next file in the window, title follows ({n} -> {dw.title()})")
            dw.click("[data-a=mode]")
            check(dw.evaluate("DiffWin.opt.inline") and dw.evaluate("document.querySelector('[data-a=mode]').textContent") == "Unified", "Side by side / Unified")
            dw.click("[data-a=ws]")
            check(dw.evaluate("DiffWin.opt.ws"), "ignore whitespace")
            dw.keyboard.press("ArrowUp")
            dw.wait_for_function("DiffWin.idx === 0 && " + READY, timeout=10000)
            dw.click("[data-a=edit]")
            check(wait_made("open") and [m for m in made if m[0] == "open"][0][1] == "basic/src/app.py", "Open in Editor: the main window is asked to open the file")
            shot("9-diffwin-page") if False else (shots and dw.screenshot(path=os.path.join(shots, "9-diffwin-page.png")))
            dw.keyboard.press("Escape")
            check(wait_made("close"), "Esc: the window closes")
            dw.close()
        finally:
            gitview.DIFFWIN.close_all()
            gitview.DIFFWIN.backend = None
        readonly_text_tests(pg, shot)
        print("== tool strip Git icon: a repository folder open")
        server.SETTINGS["base_dir"] = os.path.join(fx, "basic")
        rp = b.new_page(viewport={"width": 1200, "height": 800})
        rp.on("pageerror", lambda e: errors.append("repo page: " + str(e)))
        rp.goto(url)
        rp.wait_for_function("typeof monaco !== 'undefined' && window.GitUI && document.querySelector('#tree .node')", timeout=30000)
        check(rp.evaluate("fetch('/api/git/info').then(r => r.json()).then(d => !!d.repo)"), "basic/ is a repository")
        strip_git_click(rp, "repository folder")
        rp.close()
        pg.close()  # it would keep polling fx repositories that are outside the next base folder
        toolbar_tests(b, url, tmp, errors, shots)
        server.SETTINGS["base_dir"] = fx
        b.close()
    srv.shutdown()
    errs = [e for e in errors if "favicon" not in e]
    check(not errs, "no page errors" + (": " + " | ".join(errs[:5]) if errs else ""))
    print(f"\n{'FAILED: ' + str(len(FAILS)) if FAILS else 'all passed'}")
    sys.exit(1 if FAILS else 0)


if __name__ == "__main__":
    main()
