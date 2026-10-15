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

        print("== commands / menu / keys")
        check(pg.evaluate("MENUS.some(m => m.label === 'Git')"), "Git menu in the menu bar")
        check(pg.evaluate("COMMANDS.filter(c => c.id.startsWith('git.')).length") >= 18, "git commands registered (palette)")
        for km in ("vscode", "intellij"):
            conf = pg.evaluate(f"keymapConflicts('{km}')")
            gitc = [c for c in conf if any(i.startswith("git.") for i in c["ids"])]
            check(not gitc, f"{km} keymap: no conflicts with git keys {gitc or ''}")
        check(pg.evaluate("!!document.querySelector('#tbGroups [data-group=git] [data-cmd=\"git.toolwin\"]')"), "toolbar Git button")

        print("== Local Changes")
        pg.evaluate("GitUI.toggleWindow(true)")
        pg.wait_for_selector("#gitWin.show")
        pg.wait_for_function("GitUI.G.repo && GitUI.G.repos.length >= 6", timeout=20000)
        pg.evaluate("document.querySelector('#gitWin .gw-repo').value = GitUI.G.repos.find(r => r.name === 'basic').root;"
                    "document.querySelector('#gitWin .gw-repo').dispatchEvent(new Event('change'))")
        pg.evaluate("GitUI.setTab('changes')")
        pg.wait_for_function("document.querySelectorAll('#gitWin [data-page=changes] .gt-row').length > 5", timeout=20000)
        txt = pg.inner_text("#gitWin [data-page=changes]")
        check("Unversioned Files" in txt and "app.py" in txt and "설명 파일.txt" in txt, "groups + files (Korean name)")
        check("partly staged" in txt or "staged" in txt, "staged marker")
        shot("1-local-changes")
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
        check(pg.evaluate(PANE + ".spec.path") == "staged.txt", "double-click: diff window opens (the pane shows the file too)")
        pg.evaluate("GitUI.closeDiffWin(GitUI.DM)")
        pg.click("#gitWin [data-page=changes] .gt-row:has-text('app.py')", button="right")
        check("Show Diff in Window" in pg.evaluate("[...document.querySelectorAll('#ctxMenu .ctx-item')].map(e => e.dataset.label)"), "right-click: Show Diff in Window")
        pg.click("#ctxMenu .ctx-item[data-label='Show Diff in Window']")
        pg.wait_for_function("GitUI.DW.wins.length === 1", timeout=10000)
        check(True, "Show Diff in Window opens the window")
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
        pg.evaluate("document.querySelector('#gitWin .gw-repo').value = GitUI.G.repos.find(r => r.name === 'branches').root;"
                    "document.querySelector('#gitWin .gw-repo').dispatchEvent(new Event('change'))")
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
        pg.evaluate("document.querySelector('#gitWin .gw-repo').value = GitUI.G.repos.find(r => r.name === 'basic').root;"
                    "document.querySelector('#gitWin .gw-repo').dispatchEvent(new Event('change'))")
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
        pg.wait_for_function(SUM + ".style.display === 'block' && " + SUM + ".innerText.includes('files') && !" + SUM + ".innerText.includes('loading')", timeout=15000)
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
        pg.evaluate("document.querySelector('#gitWin .gw-repo').value = GitUI.G.repos.find(r => r.name === 'branches').root;"
                    "document.querySelector('#gitWin .gw-repo').dispatchEvent(new Event('change'))")
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
        pg.evaluate("document.querySelector('#gitWin .gw-repo').value = GitUI.G.repos.find(r => r.name === 'huge').root;"
                    "document.querySelector('#gitWin .gw-repo').dispatchEvent(new Event('change'))")
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
        pg.evaluate("document.querySelector('#gitWin .gw-repo').value = GitUI.G.repos.find(r => r.name === 'branches').root;"
                    "document.querySelector('#gitWin .gw-repo').dispatchEvent(new Event('change'))")
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
        pg.evaluate("document.querySelector('#gitWin .gw-repo').value = GitUI.G.repos.find(r => r.name === 'conflict').root;"
                    "document.querySelector('#gitWin .gw-repo').dispatchEvent(new Event('change'))")
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
            pg.evaluate("document.querySelector('#gitWin .gw-repo').value = GitUI.G.repos.find(r => r.name === 'basic').root;"
                        "document.querySelector('#gitWin .gw-repo').dispatchEvent(new Event('change'))")
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
        b.close()
    srv.shutdown()
    errs = [e for e in errors if "favicon" not in e]
    check(not errs, "no page errors" + (": " + " | ".join(errs[:5]) if errs else ""))
    print(f"\n{'FAILED: ' + str(len(FAILS)) if FAILS else 'all passed'}")
    sys.exit(1 if FAILS else 0)


if __name__ == "__main__":
    main()
