"""
Build throw-away git repositories for the Git tool window tests.

    python tests/git_fixture.py <dir> [--huge N]

<dir> must not exist yet (or be empty). Repositories created:
  basic/      linear history, staged + unstaged + untracked, Korean / space names, CRLF
  branches/   main + feature branches, merge commits, tags, a remote (ahead / behind)
  rename/     moved + edited file (history --follow), binary + big file
  conflict/   stopped in a merge conflict
  malicious/  repo config that would run programs (fsmonitor, filter, diff.external,
              textconv) -> each writes a marker file; ReadO must never trigger them
  huge/       N commits (default 30000) with periodic merges, made with fast-import
"""
import os
import subprocess
import sys

ENV = dict(os.environ, GIT_AUTHOR_NAME="Alice", GIT_AUTHOR_EMAIL="alice@example.com",
           GIT_COMMITTER_NAME="Alice", GIT_COMMITTER_EMAIL="alice@example.com",
           GIT_CONFIG_NOSYSTEM="1", LC_ALL="C")
ENV.pop("GIT_DIR", None)
_t = [1_700_000_000]


def git(cwd, *args, author=None, inp=None, check=True):
    env = dict(ENV)
    _t[0] += 60
    env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"] = f"{_t[0]} +0900"
    if author:
        env["GIT_AUTHOR_NAME"], env["GIT_AUTHOR_EMAIL"] = author, author.lower() + "@example.com"
    r = subprocess.run(["git", "-c", "init.defaultBranch=main", "-c", "core.autocrlf=false", *args], cwd=cwd, env=env,
                       input=inp, capture_output=True)
    if check and r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {r.stderr.decode(errors='replace')}")
    return r.stdout.decode("utf-8", "replace")


def write(path, text, mode="w", newline=None):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, mode, encoding=None if "b" in mode else "utf-8", newline=newline) as f:
        f.write(text)


def init(root, name):
    d = os.path.join(root, name)
    os.makedirs(d)
    git(d, "init", "-q")
    git(d, "config", "user.name", "Alice")
    git(d, "config", "user.email", "alice@example.com")
    git(d, "config", "core.autocrlf", "false")
    return d


def basic(root):
    d = init(root, "basic")
    for i in range(20):
        write(os.path.join(d, "src", "app.py"), "".join(f"line {j}\n" for j in range(i + 5)))
        if i == 3:
            write(os.path.join(d, "문서", "설명 파일.txt"), "한글 내용\n")
            write(os.path.join(d, "crlf.txt"), "a\r\nb\r\n", newline="")
            write(os.path.join(d, "gone.txt"), "to be deleted\n")
        git(d, "add", "-A")
        git(d, "commit", "-q", "-m", f"commit {i}\n\nbody line for {i}", author="Bob" if i % 3 else "Alice")
    write(os.path.join(d, "src", "app.py"), "changed\n" + open(os.path.join(d, "src", "app.py"), encoding="utf-8").read())
    write(os.path.join(d, "staged.txt"), "staged new file\n")
    git(d, "add", "staged.txt")
    write(os.path.join(d, "문서", "설명 파일.txt"), "한글 내용 수정\n")
    os.remove(os.path.join(d, "gone.txt"))
    write(os.path.join(d, "untracked.txt"), "?\n")
    write(os.path.join(d, "newdir", "a.txt"), "?\n")
    return d


def branches(root):
    d = init(root, "branches")
    write(os.path.join(d, "f.txt"), "0\n")
    git(d, "add", "-A"); git(d, "commit", "-q", "-m", "root")
    for b in ("feat/one", "feat/two", "fix/three"):
        git(d, "checkout", "-q", "-b", b, "main")
        for k in range(3):
            write(os.path.join(d, b.replace("/", "_") + ".txt"), f"{k}\n")
            git(d, "add", "-A"); git(d, "commit", "-q", "-m", f"{b} {k}", author="Carol")
        git(d, "checkout", "-q", "main")
        write(os.path.join(d, "f.txt"), b + "\n")
        git(d, "commit", "-q", "-am", f"main before {b}")
        git(d, "merge", "-q", "--no-ff", "-m", f"Merge branch '{b}'", b)
    git(d, "tag", "v1.0")
    git(d, "tag", "-a", "v1.1", "-m", "annotated")
    bare = os.path.join(root, "branches-remote.git")
    git(root, "clone", "-q", "--bare", d, bare)
    git(d, "remote", "add", "origin", bare)
    git(d, "fetch", "-q", "origin")
    git(d, "branch", "-q", "--set-upstream-to=origin/main", "main")
    write(os.path.join(d, "f.txt"), "ahead\n")
    git(d, "commit", "-q", "-am", "local only (ahead 1)")
    git(d, "stash", "list")
    write(os.path.join(d, "f.txt"), "stashed change\n")
    git(d, "stash", "push", "-q", "-m", "wip stash")
    return d


def rename(root):
    d = init(root, "rename")
    write(os.path.join(d, "old", "name.txt"), "v1\n")
    git(d, "add", "-A"); git(d, "commit", "-q", "-m", "add name.txt")
    write(os.path.join(d, "old", "name.txt"), "v1\nv2\n")
    git(d, "commit", "-q", "-am", "edit name.txt")
    os.makedirs(os.path.join(d, "new"))
    git(d, "mv", "old/name.txt", "new/renamed.txt")
    git(d, "commit", "-q", "-m", "move to new/renamed.txt")
    write(os.path.join(d, "new", "renamed.txt"), "v1\nv2\nv3\n")
    git(d, "commit", "-q", "-am", "edit after move")
    write(os.path.join(d, "img.png"), b"\x89PNG\r\n\x1a\n" + bytes(range(256)) * 4, "wb")
    write(os.path.join(d, "big.txt"), "x" * 80 + "\n", "w")
    git(d, "add", "-A"); git(d, "commit", "-q", "-m", "binary")
    return d


def conflict(root):
    d = init(root, "conflict")
    write(os.path.join(d, "c.txt"), "base\n")
    git(d, "add", "-A"); git(d, "commit", "-q", "-m", "base")
    git(d, "checkout", "-q", "-b", "other")
    write(os.path.join(d, "c.txt"), "theirs\n")
    git(d, "commit", "-q", "-am", "theirs")
    git(d, "checkout", "-q", "main")
    write(os.path.join(d, "c.txt"), "ours\n")
    git(d, "commit", "-q", "-am", "ours")
    git(d, "merge", "other", check=False)
    return d


def malicious(root):
    d = init(root, "malicious")
    marker = os.path.join(root, "PWNED.txt").replace("\\", "/")
    hook = os.path.join(root, "evil.cmd")
    with open(hook, "w") as f:
        f.write(f'@echo pwned>> "{marker}"\r\n@type nul\r\n')
    sh = os.path.join(root, "evil.sh")
    with open(sh, "w", newline="\n") as f:
        f.write(f'#!/bin/sh\necho pwned >> "{marker}"\ncat\n')
    evil = sh.replace("\\", "/")
    write(os.path.join(d, ".gitattributes"), "*.txt filter=evil diff=evil\n")
    write(os.path.join(d, "a.txt"), "hello\n")
    git(d, "add", "-A"); git(d, "commit", "-q", "-m", "one")
    write(os.path.join(d, "a.txt"), "hello\nworld\n")
    git(d, "commit", "-q", "-am", "two")
    for k, v in (("core.fsmonitor", evil), ("filter.evil.clean", evil), ("filter.evil.smudge", evil),
                 ("diff.external", evil), ("diff.evil.textconv", evil),
                 ("diff.evil.command", evil), ("core.pager", evil), ("log.showSignature", "true"),
                 ("gpg.program", evil)):
        git(d, "config", k, v)
    # make the file stat-dirty so status would re-read (and clean-filter) it
    write(os.path.join(d, "a.txt"), "hello\nworld\n")
    os.utime(os.path.join(d, "a.txt"), None)
    write(os.path.join(d, "b.txt"), "untracked\n")
    return d, marker


def huge(root, n):
    d = init(root, "huge")
    lines = []
    out = lines.append
    mark = 0
    main_mark = None
    t = 1_600_000_000
    authors = ["Alice", "Bob", "Carol", "Dave", "Eve", "김철수"]
    side_mark = None
    for i in range(n):
        mark += 1
        t += 300
        a = authors[i % len(authors)]
        msg = f"commit {i}: change file{i % 500}".encode()
        on_side = (i % 100) in range(40, 46)
        ref = "refs/heads/side" if on_side else "refs/heads/main"
        out(f"commit {ref}\nmark :{mark}\nauthor {a} <{i % 7}@ex.com> {t} +0900\ncommitter {a} <{i % 7}@ex.com> {t} +0900\n".encode())
        out(b"data %d\n" % len(msg) + msg + b"\n")
        if on_side:
            parent = side_mark if (i % 100) != 40 else main_mark
            if parent:
                out(f"from :{parent}\n".encode())
        else:
            if main_mark:
                out(f"from :{main_mark}\n".encode())
            if (i % 100) == 50 and side_mark:
                out(f"merge :{side_mark}\n".encode())
        content = f"{i}\n".encode()
        out(f"M 644 inline dir{i % 20}/file{i % 500}.txt\ndata {len(content)}\n".encode() + content + b"\n")
        if on_side:
            side_mark = mark
        else:
            main_mark = mark
    out(f"reset refs/heads/main\nfrom :{main_mark}\n\n".encode())
    git(d, "fast-import", "--quiet", inp=b"".join(lines))
    git(d, "reset", "-q", "--hard", "main")
    return d


def build(root, n_huge=30000):
    os.makedirs(root, exist_ok=True)
    if os.listdir(root):
        raise SystemExit(f"{root} is not empty")
    out = {"basic": basic(root), "branches": branches(root), "rename": rename(root), "conflict": conflict(root)}
    out["malicious"], out["marker"] = malicious(root)
    if n_huge:
        out["huge"] = huge(root, n_huge)
    return out


if __name__ == "__main__":
    args = sys.argv[1:]
    n = 30000
    if "--huge" in args:
        i = args.index("--huge")
        n = int(args[i + 1])
        del args[i:i + 2]
    if not args:
        raise SystemExit(__doc__)
    for k, v in build(args[0], n).items():
        print(f"{k}: {v}")
