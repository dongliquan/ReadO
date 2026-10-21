"""
Headless checks for the read-only Git views (gitview.py via the HTTP server).

    python tests/test_git.py [--huge N] [--keep] [--repo PATH ...]

Builds fixture repositories in a temp folder (tests/git_fixture.py), starts
the ReadO server on a free port with that folder open, and calls /api/git/*.
--repo PATH: also time the main endpoints on an existing repository
(read-only commands only; the repository is not changed — checked by
comparing HEAD / index / refs before and after).
"""
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
import git_fixture  # noqa: E402
import server  # noqa: E402

FAILS = []


def check(cond, what):
    print(("  ok   " if cond else "  FAIL ") + what)
    if not cond:
        FAILS.append(what)


class Client:
    def __init__(self, port):
        self.port = port

    def get(self, _url, host=None, **q):
        url = f"http://127.0.0.1:{self.port}{_url}"
        if q:
            url += "?" + urllib.parse.urlencode(q, doseq=True)
        req = urllib.request.Request(url, headers={"Host": host or f"127.0.0.1:{self.port}"})
        t0 = time.time()
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                return r.status, json.loads(r.read() or b"{}"), (time.time() - t0) * 1000
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}"), (time.time() - t0) * 1000

    def post(self, path, body, token=True):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json",
                                              **({server.TOKEN_HEADER: server.CSRF_TOKEN} if token else {})})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.status, json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}")

    def git(self, name, **q):
        return self.get("/api/git/" + name, **q)


def snapshot(top):
    """Everything a read-only viewer must leave alone."""
    import hashlib
    gd = os.path.join(top, ".git")
    h = hashlib.sha256()
    for name in ("HEAD", "index", "packed-refs", "ORIG_HEAD", "MERGE_HEAD", "config", "FETCH_HEAD"):
        p = os.path.join(gd, name)
        if os.path.isfile(p):
            with open(p, "rb") as f:
                h.update(name.encode() + f.read())
    for sub in ("refs", "logs"):
        for dp, _, fs in os.walk(os.path.join(gd, sub)):
            for f in sorted(fs):
                with open(os.path.join(dp, f), "rb") as fh:
                    h.update(f.encode() + fh.read())
    return h.hexdigest()


def start(base):
    server.SETTINGS = dict(server.DEFAULT_SETTINGS, base_dir=base)
    srv = server.make_server("127.0.0.1", 0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, Client(srv.server_address[1])


def fx_tests(c, fx):
    R = lambda name: fx[name].replace("\\", "/")
    print("== availability / repos")
    code, d, _ = c.git("info")
    check(code == 200 and d.get("available") and d.get("version"), f"info: git available ({d.get('version')})")
    code, d, _ = c.git("repos")
    names = sorted(r["name"] for r in d.get("repos", []))
    want = {"basic", "branches", "rename", "conflict", "malicious"} | ({"huge"} if "huge" in fx else set())
    check(want <= set(names), f"repos found: {names}")
    code, d, _ = c.git("info", path="basic/src/app.py")
    check(d.get("repo", {}).get("name") == "basic" and d.get("rel") == "src/app.py", "info for a file key -> repo + rel")

    print("== status")
    code, d, _ = c.git("status", repo=R("basic"))
    by = {f["path"]: f for f in d.get("files", [])}
    check(by.get("src/app.py", {}).get("kind") == "modified", "modified file")
    check(by.get("staged.txt", {}).get("staged") and by["staged.txt"]["kind"] == "added", "staged new file")
    check(by.get("gone.txt", {}).get("kind") == "deleted", "deleted file")
    check(by.get("untracked.txt", {}).get("kind") == "untracked", "untracked file")
    check(by.get("newdir/", {}).get("kind") == "untracked", "untracked folder")
    check(by.get("문서/설명 파일.txt", {}).get("kind") == "modified", "Korean + space path unquoted")
    check(d.get("branch", {}).get("head") == "main", "branch head")
    code, d, _ = c.git("status", repo=R("conflict"))
    check(any(f["kind"] == "conflicted" and f["path"] == "c.txt" for f in d.get("files", [])), "conflicted file")
    check(d.get("repo", {}).get("state") == "merging", "repo state merging")
    code, d, _ = c.git("status", repo=R("branches"))
    check(d.get("branch", {}).get("ahead") == 1 and d["branch"].get("upstream") == "origin/main", "ahead 1 of origin/main")

    print("== tree colours")
    code, d, _ = c.git("decor", dir=["basic", "basic/src"])
    check(d.get("files", {}).get("basic/src/app.py") == "M", "decor: modified file")
    check(d.get("files", {}).get("basic/untracked.txt") == "U", "decor: untracked file")
    check(d.get("dirs", {}).get("basic/src") == "M" and "basic" in d.get("dirs", {}), "decor: parent folders marked")

    print("== refs / stash / authors")
    code, d, _ = c.git("refs", repo=R("branches"))
    loc = {b["name"] for b in d.get("local", [])}
    check({"main", "feat/one", "feat/two", "fix/three"} <= loc, f"local branches {sorted(loc)}")
    check(any(b["name"] == "origin/main" for b in d.get("remote", [])), "remote branch")
    check({t["name"] for t in d.get("tags", [])} >= {"v1.0", "v1.1"}, "tags (annotated peeled)")
    code, d, _ = c.git("stash", repo=R("branches"))
    check(len(d.get("items", [])) == 1 and "wip stash" in d["items"][0]["s"], "stash list")
    code, d, _ = c.git("authors", repo=R("basic"))
    check(set(d.get("authors", [])) >= {"Alice", "Bob"}, "authors")

    print("== log")
    code, d, _ = c.git("log", repo=R("branches"), n=500, reload=1)
    cs = d.get("commits", [])
    check(code == 200 and len(cs) >= 15 and d.get("done"), f"log: {len(cs)} commits, done")
    merges = [x for x in cs if len(x["p"]) == 2]
    check(len(merges) >= 3, "merge commits have two parents")
    check(any("HEAD -> main" in r for x in cs for r in x["refs"]), "HEAD ref label")
    check(not any(x["s"].startswith("WIP on") or "wip stash" in x["s"] for x in cs), "stash not in the log")
    pos = {x["h"]: i for i, x in enumerate(cs)}
    check(all(pos[p] > pos[x["h"]] for x in cs for p in x["p"] if p in pos), "parents after children (graph order)")
    # two reloads of the same view at once: the replaced git log is not reported as a failure
    res = []
    ths = [threading.Thread(target=lambda: res.append(c.git("log", repo=R("branches"), n=300, reload=1))) for _ in range(4)]
    [t.start() for t in ths]
    [t.join() for t in ths]
    bad = [d for _, d, _ in res if d.get("error") not in (None, "busy") or (not d.get("error") and not d.get("commits"))]
    check(len(res) == 4 and not bad, f"concurrent reloads: no 'git log exited 1' ({[d.get('error') or len(d.get('commits', [])) for _, d, _ in res]})")
    code, d, _ = c.git("log", repo=R("branches"), ref="refs/heads/feat/one", n=100)
    check(len(d.get("commits", [])) == 4, "branch filter feat/one -> 4 commits")
    code, d, _ = c.git("log", repo=R("basic"), author="Alice", n=100)
    check(len(d.get("commits", [])) > 0 and all(x["an"] == "Alice" for x in d["commits"]), "user filter")
    code, d, _ = c.git("log", repo=R("basic"), text="COMMIT 1", n=100)
    check({x["s"] for x in d.get("commits", [])} >= {"commit 1", "commit 10"}, "text filter (case-insensitive, fixed)")
    code, d, _ = c.git("log", repo=R("basic"), text="commit 1[0-2]", regex=1, case=1, n=100)
    check(len(d.get("commits", [])) == 3, "regex + match case")
    sha = cs[3]["h"]
    code, d, _ = c.git("log", repo=R("branches"), text=sha[:8], n=100)
    check(len(d.get("commits", [])) == 1 and d["commits"][0]["h"] == sha and d.get("hash_hit"), "hash search")
    code, d, _ = c.git("log", repo=R("basic"), path="crlf.txt", n=100)
    check(len(d.get("commits", [])) == 1, "path filter")
    code, d, _ = c.git("log", repo=R("basic"), since="2000-01-01", until="2099-12-31", n=5)
    check(len(d.get("commits", [])) == 5 and d.get("has_more"), "date filter + paging has_more")
    code, d1, _ = c.git("log", repo=R("basic"), n=7, offset=0, reload=1)
    code, d2, _ = c.git("log", repo=R("basic"), n=7, offset=7)
    code, d3, _ = c.git("log", repo=R("basic"), n=100, offset=0, reload=1)
    seq = [x["h"] for x in d1["commits"] + d2["commits"]]
    check(seq == [x["h"] for x in d3["commits"]][:14], "pages continue without gaps / duplicates")

    print("== history (--follow) / commit / show")
    code, d, _ = c.git("log", repo=R("rename"), path="new/renamed.txt", follow=1, n=50)
    hs = d.get("commits", [])
    check(len(hs) == 4, f"history follows the rename ({len(hs)} commits)")
    check(hs and hs[-1].get("path_at") == "old/name.txt" and any(x.get("fs") == "R" for x in hs), "path_at before the move")
    code, d, _ = c.git("commit", repo=R("rename"), rev=hs[1]["h"])
    check(any(f["status"] == "R" and f["orig"] == "old/name.txt" for f in d.get("files", [])), "commit: rename detected")
    code, d, _ = c.git("commit", repo=R("branches"), rev=merges[0]["h"])
    check(code == 200 and len(d.get("p", [])) == 2 and d.get("files"), "merge commit: files vs first parent")
    code, d, _ = c.git("commit", repo=R("basic"), rev="HEAD")
    check("body line for 19" in d.get("body", "") and d.get("files")[0]["add"] >= 1, "commit body + numstat")
    code, d, _ = c.git("log", repo=R("basic"), n=1000, reload=1)
    root = d["commits"][-1]["h"]
    code, d, _ = c.git("commit", repo=R("basic"), rev=root)
    check(code == 200 and d.get("files"), "root commit files")
    code, d, _ = c.git("show", repo=R("rename"), rev=hs[-1]["h"], path="old/name.txt")
    check(d.get("text", "").replace("\r\n", "\n") == "v1\n", "show: file at an old revision")
    code, d, _ = c.git("show", repo=R("basic"), rev="WORKTREE", path="src/app.py")
    check(d.get("text", "").startswith("changed"), "show: working tree")
    code, d, _ = c.git("show", repo=R("basic"), rev="INDEX", path="staged.txt")
    check(d.get("text", "").replace("\r\n", "\n") == "staged new file\n", "show: index")
    code, d, _ = c.git("show", repo=R("basic"), rev="HEAD", path="crlf.txt")
    check(d.get("text") == "a\r\nb\r\n", "show: CRLF kept")
    code, d, _ = c.git("show", repo=R("rename"), rev="HEAD", path="img.png")
    check(d.get("binary"), "show: binary flagged")

    print("== diff modal data (what a file click loads)")
    # Log / Stash file click: parent version vs commit version of each changed file
    code, cm, _ = c.git("commit", repo=R("rename"), rev=hs[0]["h"])
    f = cm["files"][0]
    _, left, _ = c.git("show", repo=R("rename"), rev=cm["parent"], path=f.get("orig") or f["path"])
    _, right, _ = c.git("show", repo=R("rename"), rev=cm["h"], path=f["path"])
    check(left.get("text") and right.get("text") and left["text"] != right["text"], f"commit file {f['path']}: parent and commit sides differ")
    # renamed file: the left side is read at the old path
    code, cm, _ = c.git("commit", repo=R("rename"), rev=hs[1]["h"])
    f = [x for x in cm["files"] if x["status"] == "R"][0]
    _, left, _ = c.git("show", repo=R("rename"), rev=cm["parent"], path=f["orig"])
    check(not left.get("missing") and left.get("text", "").startswith("v1"), "renamed file: left side from the old path")
    # Local Changes click: HEAD vs working tree; deleted / untracked sides are empty
    _, left, _ = c.git("show", repo=R("basic"), rev="HEAD", path="src/app.py")
    _, right, _ = c.git("show", repo=R("basic"), rev="WORKTREE", path="src/app.py")
    check(left.get("text") != right.get("text"), "local file: HEAD and working tree differ")
    _, right, _ = c.git("show", repo=R("basic"), rev="WORKTREE", path="gone.txt")
    check(right.get("missing") is True, "deleted file: working-tree side missing")
    _, d, _ = c.git("stash", repo=R("branches"))
    code, cm, _ = c.git("commit", repo=R("branches"), rev=d["items"][0]["h"])
    check(code == 200 and any(x["path"] == "f.txt" for x in cm.get("files", [])), "stash entry: files for the modal")

    print("== blame")
    code, d, _ = c.git("blame", path="rename/new/renamed.txt")
    check(len(d.get("lines", [])) == 3 and len(d.get("commits", [])) >= 2, "blame lines + commits (across rename)")
    paths = {x.get("f") for x in d.get("commits", [])}
    check("new/renamed.txt" in paths and len(paths) >= 2, f"blame: path per commit follows the rename ({sorted(paths)})")
    old = next((x for x in d.get("commits", []) if x.get("f") != "new/renamed.txt"), None)
    if old:
        _, cm, _ = c.git("commit", repo=R("rename"), rev=old["h"])
        check(any(f["path"] == old["f"] for f in cm.get("files", [])), "blame click: the commit's files include that path")
    check(all(x.get("an") and x.get("at") and x.get("s") for x in d.get("commits", [])), "blame: author / date / subject for the tooltip")
    code, d, _ = c.git("blame", path="basic/src/app.py")
    check(any(x.get("uncommitted") for x in d.get("commits", [])), "blame: uncommitted line")
    # app.py: "changed" (uncommitted), then "line 0".."line 4" all from the first commit, then one line per later commit
    ls, cs = d.get("lines", []), d.get("commits", [])
    n_file = len(open(os.path.join(fx["basic"], "src", "app.py"), encoding="utf-8").read().splitlines())
    run5 = ls[1:6]
    check(len(ls) == n_file and len(set(run5)) == 1 and not cs[run5[0]]["uncommitted"],
          f"blame: a commit for every line, consecutive same-commit lines included ({len(ls)}/{n_file} lines, run {run5})")
    check(all(x.get("ae") for x in cs if not x.get("uncommitted")), "blame: author mail for the tooltip")
    _, cm, _ = c.git("commit", repo=R("basic"), rev=cs[run5[0]]["h"])
    check(cm.get("body") == "commit 0\n\nbody line for 0", f"tooltip message: full commit message ({cm.get('body')!r})")
    code, d, _ = c.git("blame", path="basic/untracked.txt")
    check(d.get("untracked") is True, "blame of an untracked file")

    print("== several commits (Log multi-selection)")
    _, lg, _ = c.git("log", repo=R("basic"), offset=0, n=50, reload=1)
    hs = [x["h"] for x in lg.get("commits", [])]  # newest first: hs[i] = "commit 19 - i"
    code, d = c.post("/api/git/commits", {"repo": R("basic"), "revs": hs[0:3]})
    _, single, _ = c.git("commit", repo=R("basic"), rev=hs[3])
    check(code == 200 and d.get("range") is True and d.get("base") == hs[3] and d.get("head") == hs[0] and d.get("n") == 3,
          f"3 adjacent commits: one range, base = parent of the oldest ({code}, range={d.get('range')})")
    check([(f["path"], f["status"], f["add"], f["del"]) for f in d.get("files", [])] == [("src/app.py", "M", 3, 0)],
          f"range: files of base..newest with line counts ({[(f['path'], f['status'], f['add']) for f in d.get('files', [])]})")
    pick = [hs[0], hs[2], hs[16]]  # commit 19, 17 and 3 (3 adds files)
    code, d = c.post("/api/git/commits", {"repo": R("basic"), "revs": pick})
    fs = {f["path"]: f for f in d.get("files", [])}
    check(code == 200 and d.get("range") is False and d.get("base") == hs[17], f"not adjacent: union, base = parent of the oldest ({d.get('range')})")
    app = fs.get("src/app.py") or {}
    check(app.get("status") == "M" and app.get("n") == 3 and app.get("add") == 3 and app.get("bh") == "M",
          f"union: a file changed by several commits is listed once, line counts added up ({app})")
    added = [p for p, f in fs.items() if f["status"] == "A"]
    check(sorted(added) == sorted(["crlf.txt", "gone.txt", "문서/설명 파일.txt"]) and all(fs[p]["n"] == 1 and fs[p]["bh"] == "A" for p in added),
          f"union: files added by one of them (status A, bh A) {sorted(added)}")
    check([f["path"] for f in d.get("files", [])] == sorted(fs), "union: files sorted by path (one tree)")
    # a merge commit counts with its first-parent changes (as a single merge commit shows)
    _, lgb, _ = c.git("log", repo=R("branches"), offset=0, n=50, reload=1)
    bc = lgb.get("commits", [])
    mi = next(i for i, x in enumerate(bc) if len(x["p"]) > 1)
    _, mc, _ = c.git("commit", repo=R("branches"), rev=bc[mi]["h"])
    code, d = c.post("/api/git/commits", {"repo": R("branches"), "revs": [bc[mi]["h"], bc[mi + 3]["h"]]})
    got = {f["path"] for f in d.get("files", [])}
    check(code == 200 and {f["path"] for f in mc.get("files", [])} <= got, f"merge commit in the selection: its first-parent files ({sorted(got)})")
    # root commit in a range: compared with the empty tree
    code, d = c.post("/api/git/commits", {"repo": R("basic"), "revs": hs[-3:]})
    check(d.get("range") is True and d.get("base") is None and all(f["status"] == "A" for f in d.get("files", [])) and d.get("files"),
          f"range down to the root commit: everything added ({[(f['path'], f['status']) for f in d.get('files', [])]})")
    # guards
    code, d = c.post("/api/git/commits", {"repo": R("basic"), "revs": hs[0:1]})
    check(code == 400, f"one commit is refused (use /commit) ({code})")
    code, d = c.post("/api/git/commits", {"repo": R("basic"), "revs": [hs[0], "--output=x"]})
    check(code == 400 and d.get("error") == "bad_arg", f"option-like revision refused ({code} {d.get('error')})")
    code, d = c.post("/api/git/commits", {"repo": R("basic"), "revs": hs[0:2]}, token=False)
    check(code in (401, 403), f"POST without the page token refused ({code})")
    if "huge" in fx:
        hh = []
        for off in (0, 500, 1000):  # the log pages by 500
            _, lh, _ = c.git("log", repo=R("huge"), offset=off, n=500, reload=1 if off == 0 else 0)
            hh += [x["h"] for x in lh.get("commits", [])]
        t0 = time.time()
        code, d = c.post("/api/git/commits", {"repo": R("huge"), "revs": hh[:800]})
        ms = (time.time() - t0) * 1000
        check(code == 200 and d.get("range") is True and ms < 5000, f"huge: 800 adjacent commits as one range in {ms:.0f} ms")
        t0 = time.time()
        code, d = c.post("/api/git/commits", {"repo": R("huge"), "revs": hh[:1200:2]})
        ms = (time.time() - t0) * 1000
        check(code == 200 and d.get("range") is False and d.get("partial") == 100 and ms < 15000,
              f"huge: 600 scattered commits: the newest 500 listed (partial {d.get('partial')}), {len(d.get('files', []))} files in {ms:.0f} ms")

    print("== diff windows (OS windows via a backend; reado.py plugs in pywebview)")
    import gitview

    class FakeBackend:
        def __init__(self):
            self.calls = []

        def create(self, wid, path, title):
            self.calls.append(("create", wid, path, title))
            return "h-" + wid

        def focus(self, h):
            self.calls.append(("focus", h))

        def close(self, h):
            self.calls.append(("close", h))

        def set_title(self, h, t):
            self.calls.append(("title", h, t))

        def open_in_main(self, key, line):
            self.calls.append(("open", key, line))

    def item(path, n=0):
        return {"path": path, "hash": "", "key": "basic/" + path, "sub": "HEAD ↔ Current version",
                "leftRev": "HEAD", "leftPath": path, "rightRev": "WORKTREE", "rightPath": path,
                "ident": f"L:test|{path}#{n}", "title": f"{path} · local changes"}
    old_be = gitview.DIFFWIN.backend
    code, d = c.post("/api/git/diffwin", {"repo": R("basic"), "items": [item("src/app.py")], "index": 0})
    check(code == 200 and d.get("native") is False, "no backend (browser): native false -> the page uses in-page panels")
    be = gitview.DIFFWIN.backend = FakeBackend()
    try:
        code, d = c.post("/api/git/diffwin", {"repo": R("basic"), "items": [item("src/app.py"), item("staged.txt")], "index": 0})
        made = [x for x in be.calls if x[0] == "create"]
        check(code == 200 and d.get("native") and len(made) == 1 and made[0][2] == "/diffwin?id=" + d["id"] and made[0][3] == "src/app.py · local changes",
              "open: backend creates a window for /diffwin?id=…, titled 'file · revision'")
        wid = d["id"]
        req = urllib.request.Request(f"http://127.0.0.1:{c.port}/diffwin?id={wid}")
        with urllib.request.urlopen(req, timeout=10) as r:
            html = r.read().decode("utf-8")
        check("READO_DIFFWIN" in html and "staged.txt" in html and server.CSRF_TOKEN in html and "/app/diffwin.js" in html,
              "/diffwin page: token + the file list + diffwin.js")
        code, _, _ = c.get("/diffwin", id="nope")
        check(code == 404, "/diffwin with an unknown id: 404")
        code, d2 = c.post("/api/git/diffwin", {"repo": R("basic"), "items": [item("src/app.py")], "index": 0})
        check(d2.get("reused") and d2["id"] == wid and be.calls[-1] == ("focus", "h-" + wid) and len([x for x in be.calls if x[0] == "create"]) == 1,
              "same file + revision again: the open window comes to the front, no new one")
        code, r = c.post("/api/git/diffwin-nav", {"id": wid, "ident": item("staged.txt")["ident"], "title": "staged.txt · local changes"})
        check(r.get("ok") and be.calls[-1] == ("title", "h-" + wid, "staged.txt · local changes"), "↑ / ↓ in a window: title follows, it now stands for that file")
        code, r = c.post("/api/git/diffwin-edit", {"id": wid, "key": "basic/src/app.py", "line": 3})
        check(r.get("ok") and be.calls[-1] == ("open", "basic/src/app.py", 3), "Open in Editor: the main window opens the file")
        code, r = c.post("/api/git/diffwin-edit", {"id": "forged", "key": "x"})
        check(code == 403, "Open in Editor from an unknown window id: refused")
        for n in range(1, 9):
            c.post("/api/git/diffwin", {"repo": R("basic"), "items": [item("f.txt", n)], "index": 0})
        check(len(gitview.DIFFWIN.wins) == 8 and ("close", "h-" + wid) in be.calls and wid not in gitview.DIFFWIN.wins,
              "9 windows: the oldest closes (8 max)")
        code, r = c.post("/api/git/diffwin", {"repo": R("basic"), "items": [dict(item("a.txt"), leftRev="HEAD;rm -rf")], "index": 0})
        check(code == 400, "bad revision in an item: refused")
        code, r = c.post("/api/git/diffwin", {"repo": R("basic"), "items": [dict(item("a.txt"), leftPath="../../etc/passwd")], "index": 0})
        check(code == 400, "path outside the repository in an item: refused")
        code, r = c.post("/api/git/diffwin", {"repo": "C:/Windows", "items": [item("a.txt")], "index": 0})
        check(code == 400, "repository outside the open folder: refused")
        code, r = c.post("/api/git/diffwin", {"repo": R("basic"), "items": [item("a.txt")], "index": 0}, token=False)
        check(code == 403, "without the page token: refused")
        some = next(iter(gitview.DIFFWIN.wins))
        c.post("/api/git/diffwin-close", {"id": some})
        check(some not in gitview.DIFFWIN.wins and be.calls[-1] == ("close", "h-" + some), "Esc in a window: it closes")
        gitview.DIFFWIN.close_all()
        check(not gitview.DIFFWIN.wins and len([x for x in be.calls if x[0] == "close"]) >= 9, "main window closed: every diff window closes")
    finally:
        gitview.DIFFWIN.close_all()
        gitview.DIFFWIN.backend = old_be

    print("== argument injection / guards")
    for bad in ("--output=x", "-c", "HEAD;calc", "../../x", "HEAD --all"):
        code, d, _ = c.git("show", repo=R("basic"), rev=bad, path="crlf.txt")
        check(code == 400 and d.get("error") == "bad_arg", f"rev {bad!r} refused")
    for bad in ("../../Windows/win.ini", "C:/Windows/win.ini", "a/../../b", ""):
        code, d, _ = c.git("show", repo=R("basic"), rev="HEAD", path=bad)
        check(code == 400, f"path {bad!r} refused")
    code, d, _ = c.git("log", repo=R("basic"), ref="--output=C:/x", n=5)
    check(code == 400, "branch filter must be a known ref")
    code, d, _ = c.git("log", repo=R("basic"), since="yesterday; rm", n=5)
    check(code == 400, "date filter must be YYYY-MM-DD")
    code, d, _ = c.git("status", repo=os.environ.get("SystemRoot", "C:/Windows"))
    check(code == 400 and d.get("error") == "not_repo", "repo outside the working folder refused")
    code, d, _ = c.get("/api/git/status", host="evil.example:80", repo=R("basic"))
    check(code == 403, "bad Host refused")
    code, d = c.post("/api/git/terminal", {"repo": R("basic")}, token=False)
    check(code == 403, "terminal without CSRF token refused")
    try:
        import gitview
        gitview.run(["checkout", "main"], fx["basic"])
        check(False, "write command refused by the runner")
    except gitview.GitError as e:
        check(e.code == "bad_arg", "write command refused by the runner")

    print("== malicious repository config")
    marker = fx["marker"]
    if os.path.exists(marker):
        os.remove(marker)
    for name, q in (("status", {}), ("log", {"n": 50, "reload": 1}), ("refs", {}), ("stash", {}),
                    ("authors", {})):
        c.git(name, repo=R("malicious"), **q)
    c.git("decor", dir=["malicious"])
    _, lg, _ = c.git("log", repo=R("malicious"), n=5, reload=1)
    for x in lg.get("commits", []):
        c.git("commit", repo=R("malicious"), rev=x["h"])
        c.git("show", repo=R("malicious"), rev=x["h"], path="a.txt")
    c.git("blame", path="malicious/a.txt")
    c.git("log", repo=R("malicious"), path="a.txt", follow=1, n=5)
    time.sleep(0.5)
    check(not os.path.exists(marker), "no program from the repo config ran")

    print("== editor gutter markers (/api/git-changes, existing feature)")
    text = "changed\n" + "".join(f"line {j}\n" for j in range(24))
    code, d = c.post("/api/git-changes", {"path": "basic/src/app.py", "text": text})
    check(code == 200 and d.get("repo") and d.get("branch") == "main" and d.get("added") == [[1, 1]], f"added line marker {d.get('added')}")
    code, d = c.post("/api/git-changes", {"path": "basic/src/app.py", "text": "x", "want_head": True})
    check(d.get("head", "").replace("\r\n", "\n").startswith("line 0\n"), "compare with HEAD: HEAD text")

    print("== console")
    code, d, _ = c.git("console")
    check(len(d.get("entries", [])) > 10 and all(e["cmd"].startswith("git ") for e in d["entries"]), "console log")


def _g(cwd, *args):
    import subprocess
    r = subprocess.run(["git", "-c", "user.name=T", "-c", "user.email=t@example.com", "-c", "init.defaultBranch=main",
                        "-c", "core.autocrlf=false"] + list(args), cwd=cwd, capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(f"git {' '.join(args)}: {r.stderr}")
    return r.stdout.strip()


def _commit(cwd, name, text, msg):
    with open(os.path.join(cwd, name), "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    _g(cwd, "add", name)
    _g(cwd, "commit", "-q", "-m", msg)


def pull_tests(tmp):
    """Toolbar Pull (fetch + merge --ff-only) against a local bare remote, and the AgentO deep link."""
    import gitview
    base = os.path.join(tmp, "pullfx")
    remote, a, b = (os.path.join(base, n) for n in ("remote.git", "a", "b"))
    os.makedirs(base)
    _g(base, "init", "-q", "--bare", "remote.git")
    _g(base, "clone", "-q", remote, "b")
    _commit(b, "f.txt", "one\n", "first")
    _commit(b, "g.txt", "g\n", "second")
    _g(b, "push", "-q", "origin", "HEAD:main")
    _g(base, "clone", "-q", "-b", "main", remote, "a")
    srv, c = start(base)
    server.CONFIG_PATH = os.path.join(tmp, "cfg", "config.json")  # request files land in tmp
    A = a.replace("\\", "/")
    head = lambda: _g(a, "rev-parse", "HEAD")

    print("== pull (toolbar): info")
    code, d, _ = c.git("pullinfo", repo=A)
    check(code == 200 and d.get("branch") == "main" and d.get("upstream") == "origin/main" and d.get("remote") == "origin"
          and not d.get("reason") and d.get("url"), f"pullinfo: main ← origin/main via origin ({d.get('reason')})")

    print("== pull: fast-forward")
    _commit(b, "f.txt", "one\ntwo\n", "third")
    _g(b, "push", "-q", "origin", "HEAD:main")
    code, d = c.post("/api/git/pull", {"repo": A})
    check(code == 200 and d.get("ok") and d.get("updated") and d.get("commits") == 1 and d.get("files") == 1,
          f"pull: 1 commit, 1 file ({d.get('error')} {d.get('commits')} {d.get('files')})")
    check(head() == _g(b, "rev-parse", "HEAD"), "pull: HEAD = remote head")
    check("fetch origin" in d.get("output", "") and "merge --ff-only" in d.get("output", ""), "pull: output names fetch + merge --ff-only")
    code, con, _ = c.git("console")
    check(any(e["cmd"].startswith("git fetch origin") for e in con.get("entries", []))
          and any(e["cmd"].startswith("git merge --ff-only") and e.get("out") is not None for e in con.get("entries", [])),
          "pull: fetch / merge in the Console with output")
    code, d = c.post("/api/git/pull", {"repo": A})
    check(d.get("ok") and d.get("updated") is False and "Already up to date" in d.get("output", ""), "pull again: already up to date")

    print("== pull: refused cases change nothing")
    _commit(a, "local.txt", "x\n", "local only")
    _commit(b, "h.txt", "h\n", "remote only")
    _g(b, "push", "-q", "origin", "HEAD:main")
    before = head()
    code, d = c.post("/api/git/pull", {"repo": A})
    check(not d.get("ok") and d.get("error") == "non_ff" and head() == before, f"diverged: non_ff, HEAD unchanged ({d.get('error')})")
    _g(a, "reset", "-q", "--hard", "origin/main")
    _commit(b, "f.txt", "one\ntwo\nthree\n", "remote edit of f")
    _g(b, "push", "-q", "origin", "HEAD:main")
    with open(os.path.join(a, "f.txt"), "w", encoding="utf-8", newline="\n") as f:
        f.write("my local edit\n")
    before = head()
    code, d = c.post("/api/git/pull", {"repo": A})
    with open(os.path.join(a, "f.txt"), encoding="utf-8") as f:
        kept = f.read() == "my local edit\n"
    check(not d.get("ok") and d.get("error") == "local_changes" and head() == before and kept,
          f"local change in the way: stopped, HEAD + file unchanged ({d.get('error')})")
    _g(a, "checkout", "-q", "--", "f.txt")
    code, d = c.post("/api/git/pull", {"repo": A, "unsaved": ["f.txt", "other.txt"]})
    check(d.get("need_confirm") == "unsaved" and d.get("files") == ["f.txt"] and head() == before,
          "unsaved edits in an incoming file: asks first, HEAD unchanged")
    code, d = c.post("/api/git/pull", {"repo": A, "unsaved": ["f.txt"], "allow_unsaved": True})
    check(d.get("ok") and d.get("updated"), "unsaved: pull anyway after the confirmation")
    _g(a, "checkout", "-q", "-b", "topic")
    code, d, _ = c.git("pullinfo", repo=A)
    check(d.get("reason") == "no_upstream", "branch without upstream: pullinfo says no_upstream")
    code, d = c.post("/api/git/pull", {"repo": A})
    check(not d.get("ok") and d.get("error") == "no_upstream", "branch without upstream: pull refused")
    _g(a, "checkout", "-q", "main")
    code, d = c.post("/api/git/pull", {"repo": A}, token=False)
    check(code == 403, f"pull without the page token refused ({code})")
    code, d = c.post("/api/git/pull", {"repo": os.environ.get("SystemRoot", "C:/Windows")})
    check(code == 400 and d.get("error") == "not_repo", "pull outside the working folder refused")
    for cmd in (["fetch", "origin"], ["merge", "--ff-only", "origin/main"], ["push"], ["pull"]):
        try:
            gitview.run(cmd, a)
            check(False, f"run() refuses {cmd[0]}")
        except gitview.GitError as e:
            check(e.code == "bad_arg", f"run() refuses {cmd[0]}")
    try:
        gitview._check_allowed(["push", "--force"], write=True)
        check(False, "pull runner refuses push")
    except gitview.GitError:
        check(True, "pull runner refuses push")
    check(gitview._safe_url("https://user:secret@example.com/r.git") == "https://example.com/r.git", "remote URL shown without credentials")

    print("== AgentO deep link (commit / push requests)")
    sent = []
    orig = (gitview.agento_handler, gitview._startfile, gitview.DEEPLINK_MAX)
    try:
        gitview._startfile = lambda url: sent.append(url)
        gitview.agento_handler = lambda: None
        code, d = c.post("/api/git/agento-request", {"repo": A, "kind": "commit"})
        check(not d.get("sent") and d.get("error") == "nothing_to_commit", "commit with no changes: refused")
        with open(os.path.join(a, "new file.txt"), "w") as f:
            f.write("n\n")
        with open(os.path.join(a, "g.txt"), "w") as f:
            f.write("changed\n")
        msg = "fix: 클레임 모델 & a=b?#x\n" + "y" * 400
        code, d = c.post("/api/git/agento-request", {"repo": A, "kind": "commit", "msg": msg})
        q = urllib.parse.parse_qs(urllib.parse.urlsplit(d.get("url", "")).query)
        check(code == 200 and d.get("sent") is False and d.get("fallback") == "no_handler" and not sent,
              "no agento: handler: not launched, fallback")
        check(d.get("url", "").startswith("agento://dispatch?v=1&source=reado&kind=commit&repo="), "URL: scheme, v, source, kind first")
        check(q.get("repo") == [os.path.realpath(a)] and q.get("branch") == ["main"] and q.get("dirty") == ["2"] and q.get("ahead") == ["0"],
              f"URL values decode back (repo, branch, dirty 2, ahead 0) {q.get('dirty')}")
        check(len(q.get("msg", [""])[0]) == 200 and q["msg"][0].startswith("fix: 클레임 모델 & a=b?#x y"), "msg: control chars out, 200 chars, encoded")
        check(" " not in d["url"] and "#" not in d["url"] and "&a=b" not in d["url"] and len(d["url"]) <= 2000, "URL: everything percent-encoded, ≤ 2000")
        ref = q.get("ref", [""])[0]
        rf = os.path.join(tmp, "cfg", "requests", ref + ".json")
        check(bool(ref) and os.path.isfile(rf), "commit: request file written, ref in the URL")
        if os.path.isfile(rf):
            with open(rf, encoding="utf-8") as f:
                p = json.load(f)
            check(p.get("kind") == "commit" and p.get("repo") == os.path.realpath(a) and sorted(x["path"] for x in p.get("files", [])) == ["g.txt", "new file.txt"]
                  and p.get("v") == 1 and len(p.get("msg", "")) == 200, "request file: kind, repo, files, msg")
        code, d = c.post("/api/git/agento-request", {"repo": A, "kind": "commit", "files": ["g.txt"]})
        q = urllib.parse.parse_qs(urllib.parse.urlsplit(d.get("url", "")).query)
        check(d.get("files") == ["g.txt"], "ticked files: only those in the request")
        old = os.path.join(tmp, "cfg", "requests", "20200101-000000-00000000.json")
        with open(old, "w") as f:
            f.write("{}")
        os.utime(old, (time.time() - 3 * 86400,) * 2)
        gitview.agento_handler = lambda: '"C:\\AgentO\\AgentO.exe" "%1"'
        code, d = c.post("/api/git/agento-request", {"repo": A, "kind": "commit", "msg": "m"})
        check(d.get("sent") is True and sent == [d.get("url")], "handler registered: os.startfile(url) called once")
        check(not os.path.exists(old), "request files older than a day removed")
        gitview.DEEPLINK_MAX = len(d["url"]) - 5 + len("m")  # msg no longer fits
        code, d = c.post("/api/git/agento-request", {"repo": A, "kind": "commit", "msg": "m" * 50})
        q = urllib.parse.parse_qs(urllib.parse.urlsplit(d.get("url", "")).query)
        check("msg" not in q and q.get("ref") and len(d["url"]) <= gitview.DEEPLINK_MAX, "over the length limit: msg moves into the request file")
        gitview.DEEPLINK_MAX = 30
        code, d = c.post("/api/git/agento-request", {"repo": A, "kind": "commit"})
        check(d.get("error") == "too_long", "URL still too long: refused")
        gitview.DEEPLINK_MAX = orig[2]

        def boom(url):
            raise OSError("no association")
        gitview._startfile = boom
        code, d = c.post("/api/git/agento-request", {"repo": A, "kind": "commit"})
        check(d.get("sent") is False and d.get("fallback") == "launch_failed", "startfile fails: fallback")
        gitview._startfile = lambda url: sent.append(url)
        code, d = c.post("/api/git/agento-request", {"repo": A, "kind": "push"})
        check(d.get("error") == "nothing_to_push", "push with ↑0: refused")
        _g(a, "add", "-A")
        _g(a, "-c", "user.name=T", "commit", "-q", "-m", "to push")
        sent.clear()
        code, d = c.post("/api/git/agento-request", {"repo": A, "kind": "push"})
        q = urllib.parse.parse_qs(urllib.parse.urlsplit(d.get("url", "")).query)
        check(d.get("sent") and q.get("kind") == ["push"] and q.get("ahead") == ["1"] and "ref" not in q and "force" not in d["url"].lower(),
              "push: ahead 1, no request file, no force parameter")
        check(_g(a, "rev-list", "--count", "origin/main..main") == "1", "push request: nothing was pushed by ReadO")
        for bad in ("reset", "push --force", "", "COMMIT"):
            code, d = c.post("/api/git/agento-request", {"repo": A, "kind": bad})
            check(code == 400 and d.get("error") == "bad_arg", f"kind {bad!r} refused")
        code, d = c.post("/api/git/agento-request", {"repo": A, "kind": "push"}, token=False)
        check(code == 403, "agento-request without the page token refused")
    finally:
        gitview.agento_handler, gitview._startfile, gitview.DEEPLINK_MAX = orig
    srv.shutdown()


def checkout_tests(tmp):
    """Branch checkout (git switch) and Fetch against a local bare remote."""
    import gitview
    base = os.path.join(tmp, "cofx")
    remote, a, b = (os.path.join(base, n) for n in ("remote.git", "a", "b"))
    os.makedirs(base)
    _g(base, "init", "-q", "--bare", "remote.git")
    _g(base, "clone", "-q", remote, "b")
    _commit(b, "f.txt", "one\n", "first")
    _g(b, "push", "-q", "origin", "HEAD:main")
    _g(b, "checkout", "-q", "-b", "feature")
    _commit(b, "feature.txt", "feature\n", "feature work")
    _g(b, "push", "-q", "origin", "feature")
    _g(b, "push", "-q", "origin", "main:other")
    _g(b, "push", "-q", "origin", "main:doomed")
    _g(b, "checkout", "-q", "main")
    _g(base, "clone", "-q", "-b", "main", remote, "a")
    _g(a, "config", "core.autocrlf", "false")  # ReadO's git and _g() write the same line endings
    _g(a, "checkout", "-q", "-b", "local1")
    _commit(a, "f.txt", "one\nlocal1\n", "local1 edit")
    _commit(a, "only1.txt", "1\n", "local1 file")
    _g(a, "checkout", "-q", "main")
    _g(a, "branch", "-q", "--no-track", "other", "main")  # same name as origin/other, not tracking it
    srv, c = start(base)
    A = a.replace("\\", "/")
    branch = lambda: _g(a, "rev-parse", "--abbrev-ref", "HEAD")
    changed = []
    orig_sc = server.source_changed
    server.source_changed = lambda: changed.append(1)
    try:
        print("== checkout: local branch")
        code, d = c.post("/api/git/checkout", {"repo": A, "ref": "refs/heads/local1"})
        check(code == 200 and d.get("ok") and d.get("updated") and branch() == "local1" and not d.get("created"),
              f"local branch: switched to local1 ({d.get('error')} {d.get('git')})")
        check(sorted(d.get("changed", [])) == ["f.txt", "only1.txt"] and os.path.isfile(os.path.join(a, "only1.txt")),
              f"local branch: changed files listed, working tree updated {d.get('changed')}")
        check("git switch --no-guess local1" in d.get("output", ""), "output names git switch")
        code, con, _ = c.git("console")
        check(any(e["cmd"].startswith("git switch --no-guess local1") for e in con.get("entries", [])), "switch in the Console")
        check(len(changed) == 1, "checkout: file list / symbol index refresh started")
        code, d, _ = c.git("status", repo=A)
        check(d.get("branch", {}).get("head") == "local1", "status shows the new branch at once")
        code, d = c.post("/api/git/checkout", {"repo": A, "ref": "refs/heads/local1"})
        check(d.get("ok") and d.get("updated") is False, "checkout of the current branch: nothing to do")

        print("== checkout: remote-only branch -> tracking branch")
        code, d = c.post("/api/git/checkout", {"repo": A, "ref": "refs/remotes/origin/feature"})
        check(d.get("ok") and d.get("created") and branch() == "feature"
              and _g(a, "rev-parse", "--abbrev-ref", "feature@{upstream}") == "origin/feature",
              f"remote branch: local feature created, tracks origin/feature ({d.get('error')} {d.get('git')})")
        check("--create feature --track origin/feature" in d.get("output", "") and os.path.isfile(os.path.join(a, "feature.txt")),
              "remote branch: git switch --create --track, file there")
        _g(a, "checkout", "-q", "main")
        code, d = c.post("/api/git/checkout", {"repo": A, "ref": "refs/remotes/origin/feature"})
        check(d.get("ok") and not d.get("created") and branch() == "feature", "remote branch with a tracking local branch: switches to it")
        _g(a, "checkout", "-q", "main")
        code, d = c.post("/api/git/checkout", {"repo": A, "ref": "refs/remotes/origin/other"})
        check(not d.get("ok") and d.get("error") == "local_exists" and branch() == "main",
              "remote branch whose name a non-tracking local branch has: refused")

        print("== checkout: local changes in the way")
        with open(os.path.join(a, "f.txt"), "w", encoding="utf-8", newline="\n") as f:
            f.write("my edit\n")
        n = len(changed)
        code, d = c.post("/api/git/checkout", {"repo": A, "ref": "refs/heads/local1"})
        with open(os.path.join(a, "f.txt"), encoding="utf-8") as f:
            kept = f.read() == "my edit\n"
        check(not d.get("ok") and d.get("error") == "local_changes" and "would be overwritten" in d.get("git", "")
              and branch() == "main" and kept and len(changed) == n,
              f"local changes: git refuses, its message passed on, branch + file unchanged ({d.get('error')})")
        _g(a, "checkout", "-q", "--", "f.txt")
        code, d = c.post("/api/git/checkout", {"repo": A, "ref": "refs/heads/local1", "unsaved": ["f.txt", "x.txt"]})
        check(d.get("need_confirm") == "unsaved" and d.get("files") == ["f.txt"] and branch() == "main",
              "unsaved editor edits in a file the checkout changes: asks first")
        code, d = c.post("/api/git/checkout", {"repo": A, "ref": "refs/heads/local1", "unsaved": ["f.txt"], "allow_unsaved": True})
        check(d.get("ok") and branch() == "local1", "unsaved: checkout after the confirmation")
        _g(a, "checkout", "-q", "main")

        print("== checkout: refused input")
        for ref in ("refs/heads/nope", "refs/tags/x", "HEAD", "--orphan", "refs/remotes/origin/nope", None):
            code, d = c.post("/api/git/checkout", {"repo": A, "ref": ref})
            check(code == 400 and d.get("error") == "bad_arg" and branch() == "main", f"checkout {ref!r}: bad_arg")
        code, d = c.post("/api/git/checkout", {"repo": A, "ref": "refs/heads/local1"}, token=False)
        check(code == 403 and branch() == "main", f"checkout without the page token refused ({code})")
        code, d = c.post("/api/git/checkout", {"repo": os.environ.get("SystemRoot", "C:/Windows"), "ref": "refs/heads/main"})
        check(code == 400 and d.get("error") == "not_repo", "checkout outside the working folder refused")
        for cmd in (["switch", "local1"], ["checkout", "local1"]):
            try:
                gitview.run(cmd, a)
                check(False, f"run() refuses {cmd[0]}")
            except gitview.GitError as e:
                check(e.code == "bad_arg", f"run() refuses {cmd[0]}")
        for cmd in (["checkout", "-f"], ["reset", "--hard"], ["stash"], ["clean", "-fd"]):
            try:
                gitview._check_allowed(cmd, write=True)
                check(False, f"write runner refuses {cmd[0]}")
            except gitview.GitError:
                check(True, f"write runner refuses {cmd[0]}")

        print("== fetch --prune")
        _commit(b, "new.txt", "n\n", "remote news")
        _g(b, "push", "-q", "origin", "main")
        _g(b, "push", "-q", "origin", "--delete", "doomed")
        head = _g(a, "rev-parse", "HEAD")
        code, d = c.post("/api/git/fetch", {"repo": A})
        refs = _g(a, "for-each-ref", "--format=%(refname)", "refs/remotes")
        check(d.get("ok") and d.get("behind") == 1 and d.get("remote") == "origin" and "fetch --prune origin" in d.get("output", ""),
              f"fetch: origin, ↓1 now known ({d.get('error')} {d.get('behind')})")
        check("refs/remotes/origin/doomed" not in refs and _g(a, "rev-parse", "HEAD") == head,
              "fetch: deleted remote branch pruned, HEAD / working tree untouched")
        code, d = c.post("/api/git/fetch", {"repo": A}, token=False)
        check(code == 403, "fetch without the page token refused")

        print("== pull after fetch, error texts")
        code, d = c.post("/api/git/pull", {"repo": A})
        check(d.get("ok") and d.get("updated") and os.path.isfile(os.path.join(a, "new.txt")), "pull: fetched commit applied")
        check(gitview._pull_error("fatal: Authentication failed for 'https://x/'") == "auth"
              and gitview._pull_error("fatal: could not read Username for 'https://x': terminal prompts disabled") == "auth",
              "auth failures recognised")
    finally:
        server.source_changed = orig_sc
        srv.shutdown()


def perf(c, top, label, rounds=1):
    R = top.replace("\\", "/")
    rows = []

    def t(name, **q):
        best, d = None, None
        for _ in range(rounds):
            code, d, ms = c.git(name, **q)
            best = ms if best is None else min(best, ms)
        rows.append((name + (" " + ",".join(f"{k}={v}" for k, v in q.items() if k not in ("repo",)) if q else ""), best,
                     d.get("error") if isinstance(d, dict) else None))
        return d

    t("status", repo=R, fresh=1)
    t("refs", repo=R)
    d = t("log", repo=R, n=200, reload=1)
    t("log", repo=R, n=200, offset=200)
    t("log", repo=R, n=200, offset=5000)
    for x in (d or {}).get("commits", [])[:1]:
        t("commit", repo=R, rev=x["h"])
    t("authors", repo=R)
    print(f"== timings: {label}")
    for name, ms, err in rows:
        print(f"  {ms:8.0f} ms  {name}" + (f"   [{err}]" if err else ""))
    return rows


def main():
    args = sys.argv[1:]
    n = 30000
    if "--huge" in args:
        i = args.index("--huge"); n = int(args[i + 1]); del args[i:i + 2]
    keep = "--keep" in args
    extra = []
    while "--repo" in args:
        i = args.index("--repo"); extra.append(args[i + 1]); del args[i:i + 2]
    tmp = tempfile.mkdtemp(prefix="reado-git-")
    try:
        t0 = time.time()
        fx = git_fixture.build(os.path.join(tmp, "fx"), n)
        print(f"fixture built in {time.time() - t0:.1f}s ({tmp})")
        snaps = {k: snapshot(v) for k, v in fx.items() if k not in ("marker",)}
        srv, c = start(os.path.join(tmp, "fx"))
        fx_tests(c, fx)
        if n:
            rows = perf(c, fx["huge"], f"fixture huge ({n} commits)")
            first = [ms for name, ms, _ in rows if name.startswith("log n=200,reload")][0]
            check(first < 1500, f"huge: first log page < 1.5 s ({first:.0f} ms)")
        print("== read-only: repositories unchanged")
        for k, v in snaps.items():
            check(snapshot(fx[k]) == v, f"{k}: HEAD / index / refs / config unchanged")
        srv.shutdown()
        pull_tests(tmp)
        checkout_tests(tmp)
        for repo in extra:
            before = snapshot(repo)
            srv, c = start(os.path.dirname(os.path.realpath(repo)))
            perf(c, os.path.realpath(repo), repo, rounds=2)
            srv.shutdown()
            check(snapshot(repo) == before, f"{repo}: unchanged")
    finally:
        if not keep:
            shutil.rmtree(tmp, ignore_errors=True)
    print(f"\n{'FAILED: ' + str(len(FAILS)) if FAILS else 'all passed'}")
    sys.exit(1 if FAILS else 0)


if __name__ == "__main__":
    main()
