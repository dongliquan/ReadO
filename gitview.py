"""
ReadO — read-only git views (Local Changes, Log, History, Blame, branches).

ReadO only *looks* at repositories; every command that would change one
(commit, checkout, stash …) is handed to AgentO as an instruction instead
(see docs/GIT-DESIGN.md). The exceptions only bring other commits into view:
Pull (fetch + fast-forward-only merge), Fetch and branch checkout (git switch),
run by pull() / fetch() / checkout() alone. This module therefore:

  * runs the installed git CLI (no bundled git); missing or older than
    MIN_VERSION -> the Git UI shows why and stays off;
  * only runs sub-commands from READ_ONLY (checked in one place, run());
    the WRITE_CMDS steps only with fixed options, never forced, one at a time per repo;
  * neutralises repository settings that make read commands execute
    programs (core.fsmonitor and filter drivers from the repo's own config,
    external diff / textconv), takes no optional locks, never prompts;
  * validates every rev (hex / known ref / HEAD~n) and path (repo-relative,
    no "..", literal pathspecs) before it reaches git;
  * kills an older request of the same kind when a newer one starts, and
    times every call out.

Endpoints (GET, read guard; POST via server.write_api):
  GET  /api/git/info?path=|repo=        -> git availability + repo of a file / folder
  GET  /api/git/repos                   -> repositories at / under the working folder
  GET  /api/git/status?repo=&fresh=     -> branch + changed files (porcelain v2)
  GET  /api/git/decor?dir=..&eol=       -> tree colours for expanded folders (eol=1: line-ending-only too)
  GET  /api/git/fp?repo=                -> cheap fingerprint (HEAD / index / refs mtimes)
  GET  /api/git/refs?repo=              -> local / remote branches, tags
  GET  /api/git/authors?repo=           -> recent authors (User filter)
  GET  /api/git/log?repo=&offset=&n=&ref=&author=&since=&until=&path=&text=&regex=&case=&follow=&reload=
  GET  /api/git/commit?repo=&rev=       -> message, refs and changed files of one commit
  GET  /api/git/show?repo=&rev=&path=   -> file text at a rev (sha / HEAD / INDEX / WORKTREE)
  GET  /api/git/blame?path=             -> per-line commit of a file (working tree)
  GET  /api/git/stash?repo=             -> stash list (read only)
  GET  /api/git/console                 -> the git commands ReadO ran (Console tab)
  POST /api/git/agento                  -> start / focus AgentO (guarded)
  POST /api/git/terminal                -> open a terminal in the repository (guarded)
  GET  /api/git/pullinfo?repo=          -> branch / upstream / remote for the Pull confirmation
  POST /api/git/pull                    -> fetch + merge --ff-only (guarded)
  POST /api/git/fetch                   -> fetch --prune (guarded)
  POST /api/git/checkout                -> switch to a local branch / track a remote one (guarded)
  POST /api/git/agento-request          -> agento://dispatch deep link for Commit / Push (guarded)
"""
import collections
import os
import re
import secrets
import shutil
import subprocess
import threading
import time

S = None  # the server module (set by register(); avoids importing it twice as __main__)

MIN_VERSION = (2, 24)    # --end-of-options
TIMEOUT = 10             # seconds, default per call
LOG_PAGE_MAX = 1000
LOG_MAX = 400_000        # commits kept per log session
STATUS_MAX = 5000        # changed files listed per repository
COMMIT_FILES_MAX = 3000
SHOW_MAX = 16_000_000    # bytes of a file version sent to the diff view
BLAME_MAX = 8_000_000

# Sub-commands ReadO may run. Anything else is refused in run().
READ_ONLY = frozenset("""version rev-parse status log show cat-file diff-tree blame for-each-ref
config symbolic-ref ls-files rev-list merge-base diff""".split())
# The exceptions (Pull / Fetch / Checkout, see pull()): fetch, a fast-forward-only merge and
# git switch. Only pull() / fetch() / checkout() run these, with fixed options; run() still
# refuses them.
WRITE_CMDS = frozenset(("fetch", "merge", "switch"))
PULL_TIMEOUT = 60
# `config` only with these (reading) options
_CONFIG_READ = frozenset(("--get", "--get-regexp", "--get-all", "--list", "-l", "--show-scope",
                          "--show-origin", "--includes", "--local", "--global", "--system", "--worktree", "-z"))


class GitError(Exception):
    def __init__(self, code, detail=""):
        super().__init__(code)
        self.code, self.detail = code, detail


# ----- git executable -----

_exe_lock = threading.Lock()
_exe = {"t": 0, "path": None, "version": None, "reason": None}


def _find_git():
    cand = (S.SETTINGS.get("git_path") or "").strip() if S else ""
    if cand and os.path.isfile(cand):
        return cand
    p = shutil.which("git")
    if p:
        return p
    for env in ("ProgramFiles", "ProgramW6432", "ProgramFiles(x86)", "LOCALAPPDATA"):
        root = os.environ.get(env)
        if root:
            for sub in (r"Git\cmd\git.exe", r"Programs\Git\cmd\git.exe"):
                f = os.path.join(root, sub)
                if os.path.isfile(f):
                    return f
    return None


def git_exe():
    """(path, version tuple, reason). reason is None when usable."""
    with _exe_lock:
        if time.time() - _exe["t"] < 60:
            return _exe["path"], _exe["version"], _exe["reason"]
        path, ver, reason = _find_git(), None, None
        if not path:
            reason = "no_git"
        else:
            try:
                r = subprocess.run([path, "version"], capture_output=True, timeout=10, stdin=subprocess.DEVNULL,
                                   env=_env(), creationflags=S.CREATE_NO_WINDOW if S else 0)
                m = re.search(rb"(\d+)\.(\d+)(?:\.(\d+))?", r.stdout)
                ver = tuple(int(x or 0) for x in m.groups()) if m else None
            except (OSError, subprocess.SubprocessError):
                ver = None
            if not ver:
                reason = "no_git"
            elif ver[:2] < MIN_VERSION:
                reason = "old_git"
        _exe.update(t=time.time(), path=path, version=ver, reason=reason)
        return path, ver, reason


def _env():
    # nothing inherited from a git hook / shell (GIT_DIR, GIT_INDEX_FILE, GIT_EXTERNAL_DIFF …)
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("GIT_")}
    env.update(GIT_OPTIONAL_LOCKS="0", GIT_TERMINAL_PROMPT="0", GCM_INTERACTIVE="never",
               GIT_PAGER="cat", PAGER="cat", GIT_LITERAL_PATHSPECS="1", GIT_ASKPASS="",
               SSH_ASKPASS="", LC_ALL="C", LANG="C", GIT_NO_REPLACE_OBJECTS="1")
    return env


# Fixed for every call. Per-repo additions come from _repo_overrides().
BASE_CONFIG = ["-c", "core.quotepath=off", "-c", "color.ui=false", "-c", "log.showSignature=false",
               "-c", "i18n.logOutputEncoding=UTF-8", "-c", "core.pager=cat", "-c", "diff.external=",
               "-c", "status.submoduleSummary=false", "-c", "core.hooksPath=" + os.devnull]

_ovr_cache = {}  # repo top -> (time, [-c …])
_ovr_lock = threading.Lock()


def _repo_overrides(top):
    """-c settings that switch off programs a repository's *own* config asks
    git to run during read commands: core.fsmonitor (a hook path) and filter
    drivers (clean / smudge / process). User / system config is trusted."""
    if not top:
        return ["-c", "core.fsmonitor=false"]
    with _ovr_lock:
        hit = _ovr_cache.get(top)
        if hit and time.time() - hit[0] < 30:
            return hit[1]
    out = []
    pat = r"^(core\.fsmonitor|filter\..+\.(clean|smudge|process|required))$"
    lines = []
    try:
        res = _raw(["config", "--show-scope", "--includes", "--get-regexp", pat], top, BASE_CONFIG, timeout=5)
        if res[0] in (0, 1):
            for ln in res[1].decode("utf-8", "replace").splitlines():
                scope, _, rest = ln.partition("\t")
                if scope in ("local", "worktree", "command"):
                    lines.append(rest)
        else:
            raise GitError("config")
    except GitError:  # git without --show-scope: treat repo-local config as the only source
        try:
            res = _raw(["config", "--local", "--includes", "--get-regexp", pat], top, BASE_CONFIG, timeout=5)
            lines = res[1].decode("utf-8", "replace").splitlines() if res[0] == 0 else []
        except GitError:
            lines = []
    drivers = set()
    for ln in lines:
        key = ln.split(" ", 1)[0].lower()
        if key.startswith("filter."):
            drivers.add(key[len("filter."):].rsplit(".", 1)[0])
    out += ["-c", "core.fsmonitor=false"]  # a repo can point it at any program
    for d in sorted(drivers):
        if re.fullmatch(r"[A-Za-z0-9_.\-]{1,100}", d):
            out += ["-c", f"filter.{d}.clean=", "-c", f"filter.{d}.smudge=",
                    "-c", f"filter.{d}.process=", "-c", f"filter.{d}.required=false"]
    with _ovr_lock:
        _ovr_cache[top] = (time.time(), out)
    return out


# ----- running git -----

_running = {}  # kind -> Popen (the newest request of that kind)
_run_lock = threading.Lock()
_GATE = threading.BoundedSemaphore(4)
CONSOLE = collections.deque(maxlen=300)
_console_seq = [0]


def _log_console(args, cwd, ms, rc, kind, err="", out=""):
    with _run_lock:
        _console_seq[0] += 1
        CONSOLE.append({"id": _console_seq[0], "t": time.time(), "cmd": "git " + " ".join(_q(a) for a in args)[:400],
                        "cwd": cwd, "ms": int(ms), "rc": rc, "kind": kind or "", "err": (err or "")[:300],
                        "out": (out or "")[:4000]})


def _q(a):
    return a if re.fullmatch(r"[\w@%+=:,./^~\-]+", a) else '"' + a.replace('"', '\\"') + '"'


def _check_allowed(args, write=False):
    if write:
        if not args or args[0] not in WRITE_CMDS:
            raise GitError("bad_arg", "not a pull / checkout command: " + (args[0] if args else ""))
        return
    if not args or args[0] not in READ_ONLY:
        raise GitError("bad_arg", "not a read-only git command: " + (args[0] if args else ""))
    if args[0] == "diff" and any(a.startswith(("--output", "--ext-diff", "--textconv")) for a in args):
        raise GitError("bad_arg", "diff: no output file / external programs")
    if args[0] == "config" and not any(a in ("--get", "--get-regexp", "--get-all", "--list", "-l") for a in args):
        raise GitError("bad_arg", "config: read options only")
    if args[0] == "config" and any(a.startswith("-") and a not in _CONFIG_READ for a in args[1:]):
        raise GitError("bad_arg", "config: read options only")


def _popen(args, cwd, cfg, write=False):
    exe, _, reason = git_exe()
    if reason:
        raise GitError(reason)
    _check_allowed(args, write)
    return subprocess.Popen([exe] + cfg + args, cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, env=_env(), creationflags=S.CREATE_NO_WINDOW)


def _raw(args, cwd, cfg, timeout=TIMEOUT, kind=None, write=False):
    """(returncode, stdout bytes, stderr str). Raises GitError on timeout /
    cancellation / missing git. write: a pull step (output kept in the Console)."""
    t0 = time.time()
    if not _GATE.acquire(timeout=timeout):
        raise GitError("busy")
    try:
        proc = _popen(args, cwd, cfg, write)
        if kind:
            with _run_lock:
                old = _running.get(kind)
                _running[kind] = proc
            if old is not None and old.poll() is None:
                old.readO_cancelled = True
                old.kill()
        try:
            out, err = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()
            _log_console(args, cwd, (time.time() - t0) * 1000, -1, kind, "timeout")
            raise GitError("timeout", f"git {args[0]} took longer than {timeout}s")
        finally:
            if kind:
                with _run_lock:
                    if _running.get(kind) is proc:
                        del _running[kind]
        rc = proc.returncode
        errs = err.decode("utf-8", "replace").strip()
        if getattr(proc, "readO_cancelled", False):
            _log_console(args, cwd, (time.time() - t0) * 1000, rc, kind, "cancelled")
            raise GitError("cancelled")
        if write:
            _log_console(args, cwd, (time.time() - t0) * 1000, rc, kind, errs if rc else "",
                         "\n".join(x for x in (out.decode("utf-8", "replace").strip(), errs) if x))
        elif args[0] != "config":
            _log_console(args, cwd, (time.time() - t0) * 1000, rc, kind, errs if rc else "")
        return rc, out, errs
    except OSError as e:
        raise GitError("no_git", str(e))
    finally:
        _GATE.release()


def run(args, top, timeout=TIMEOUT, kind=None, ok=(0,)):
    """stdout bytes of a read-only git command in repository `top`."""
    rc, out, err = _raw(args, top, BASE_CONFIG + _repo_overrides(top), timeout, kind)
    if rc not in ok:
        if "unsafe repository" in err or "dubious ownership" in err:
            raise GitError("unsafe_repo", err)
        raise GitError("git_failed", err[:500])
    return out


def run_simple(args, cwd, timeout=5):
    """For server._git (gutter markers): stdout or None, never raises."""
    try:
        return run(args, cwd, timeout=timeout)
    except GitError:
        return None


# ----- validation -----

_HEX = re.compile(r"[0-9a-fA-F]{4,64}")
_HEADISH = re.compile(r"HEAD(?:[~^]\d{0,4})*")
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


def _check_rel(path):
    """A repo-relative path from the page: forward slashes, no '..', not absolute."""
    if not isinstance(path, str) or not path or len(path) > 4096 or "\0" in path:
        raise GitError("bad_arg", "path")
    p = path.replace("\\", "/").strip("/")
    if not p or re.match(r"^[A-Za-z]:", p) or any(seg in ("..", "") for seg in p.split("/")):
        raise GitError("bad_arg", "path")
    return p


def _refnames(top):
    return {r["ref"] for r in refs(top, cached=True)["all"]}


def _check_rev(rev, top, allow_special=False):
    if allow_special and rev in ("INDEX", "WORKTREE"):
        return rev
    if isinstance(rev, str) and re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", rev):
        return rev  # a full object name; the command that uses it fails if it is not a commit
    if not isinstance(rev, str) or not rev or len(rev) > 256:
        raise GitError("bad_arg", "rev")
    if _HEX.fullmatch(rev) or _HEADISH.fullmatch(rev):
        ok = True
    else:
        ok = rev in _refnames(top) or ("refs/heads/" + rev) in _refnames(top) or rev.startswith("stash@{") and re.fullmatch(r"stash@\{\d{1,5}\}", rev)
    if not ok:
        raise GitError("bad_arg", "unknown revision")
    out = run(["rev-parse", "--verify", "--quiet", "--end-of-options", rev + "^{commit}"], top, ok=(0, 1))
    sha = out.decode().strip()
    if not re.fullmatch(r"[0-9a-f]{40,64}", sha):
        raise GitError("bad_arg", "unknown revision")
    return sha


# ----- repositories -----

_top_cache = {}  # normcased folder -> (time, top or None)
_top_lock = threading.Lock()


def _toplevel(folder):
    key = os.path.normcase(folder)
    with _top_lock:
        hit = _top_cache.get(key)
        if hit and time.time() - hit[0] < 30:
            return hit[1]
    top = None
    try:
        out = _raw(["rev-parse", "--show-toplevel"], folder, BASE_CONFIG + ["-c", "core.fsmonitor=false"], timeout=5)
        if out[0] == 0:
            t = out[1].decode("utf-8", "replace").strip()
            top = os.path.realpath(t) if t else None
        elif "dubious ownership" in out[2] or "unsafe repository" in out[2]:
            top = None
    except GitError:
        top = None
    if top and not _related(top):
        top = None
    with _top_lock:
        if len(_top_cache) > 2000:
            _top_cache.clear()
        _top_cache[key] = (time.time(), top)
    return top


def _related(top):
    """A repository ReadO may show: inside the working folder, around it, or
    holding a file the user opened explicitly."""
    base = S.base_root()
    if base and (S._within(top, base) or S._within(base, top)):
        return True
    with S._state_lock:
        ext = list(S._load_state_locked()["external"])
    return any(S._within(p, top) for p in ext)


def repo_of(param):
    """`repo` query value (absolute top-level path) -> validated top."""
    if not isinstance(param, str) or not param.strip():
        raise GitError("not_repo")
    full = os.path.realpath(param)
    if not os.path.isdir(full):
        raise GitError("not_repo")
    top = _toplevel(full)
    if not top or os.path.normcase(top) != os.path.normcase(full):
        raise GitError("not_repo")
    return top


def _git_dir(top):
    g = os.path.join(top, ".git")
    if os.path.isfile(g):  # worktree / submodule: "gitdir: <path>"
        try:
            with open(g, "r", encoding="utf-8") as f:
                line = f.read(4096).strip()
            if line.startswith("gitdir:"):
                d = line[7:].strip()
                return os.path.realpath(d if os.path.isabs(d) else os.path.join(top, d))
        except OSError:
            pass
    return g


def _common_dir(gd):
    try:
        with open(os.path.join(gd, "commondir"), "r", encoding="utf-8") as f:
            c = f.read().strip()
        return os.path.realpath(c if os.path.isabs(c) else os.path.join(gd, c))
    except OSError:
        return gd


def repo_state(top):
    gd = _git_dir(top)
    ex = lambda n: os.path.exists(os.path.join(gd, n))
    if ex("rebase-merge") or ex("rebase-apply"):
        return "rebasing"
    if ex("MERGE_HEAD"):
        return "merging"
    if ex("CHERRY_PICK_HEAD"):
        return "cherry-picking"
    if ex("REVERT_HEAD"):
        return "reverting"
    if ex("BISECT_LOG"):
        return "bisecting"
    return ""


def fingerprint(top):
    gd = _git_dir(top)
    cd = _common_dir(gd)
    parts = []
    for f in (os.path.join(gd, "HEAD"), os.path.join(gd, "index"), os.path.join(gd, "logs", "HEAD"),
              os.path.join(cd, "packed-refs"), os.path.join(cd, "refs", "heads"), os.path.join(cd, "refs", "tags"),
              os.path.join(cd, "refs", "stash"), os.path.join(gd, "MERGE_HEAD"), os.path.join(gd, "rebase-merge"),
              os.path.join(cd, "FETCH_HEAD")):
        try:
            parts.append(str(os.stat(f).st_mtime_ns))
        except OSError:
            parts.append("-")
    return ".".join(parts)


def _summary(top):
    b = S.base_root()
    return {"root": top.replace("\\", "/"), "name": os.path.basename(top) or top,
            "base": b.replace("\\", "/") if b else "", "state": repo_state(top)}


def info(path_key="", repo=""):
    exe, ver, reason = git_exe()
    out = {"available": reason is None, "version": ".".join(map(str, ver)) if ver else None, "reason": reason,
           "min_version": ".".join(map(str, MIN_VERSION))}
    if reason:
        return out
    top, rel = None, ""
    if repo:
        top = repo_of(repo)
    else:
        full = S.resolve_read_path(path_key) if path_key else S.base_root()
        if full:
            folder = full if os.path.isdir(full) else os.path.dirname(full)
            top = _toplevel(folder)
            if top:
                rel = os.path.relpath(full, top).replace("\\", "/")
                rel = "" if rel == "." else rel
    if top:
        out["repo"] = _summary(top)
        out["rel"] = rel
        try:
            br = run(["rev-parse", "--abbrev-ref", "HEAD"], top, timeout=5, ok=(0, 128)).decode().strip()
            out["repo"]["branch"] = br if br and br != "HEAD" else ""
            out["repo"]["detached"] = br == "HEAD"
        except GitError:
            pass
    return out


def repos():
    """Repositories to choose from: the one around the working folder, plus
    those directly under it (two levels)."""
    base = S.base_root()
    if not base:
        return {"repos": []}
    found, seen = [], set()

    def add(top):
        if top and os.path.normcase(top) not in seen:
            seen.add(os.path.normcase(top))
            found.append(_summary(top))

    add(_toplevel(base))

    def scan(folder, depth):
        try:
            names = sorted(os.listdir(folder), key=str.lower)
        except OSError:
            return
        for n in names:
            if len(found) >= 100 or S._is_ignored(n) and n != ".git":
                continue
            full = os.path.join(folder, n)
            if n == ".git" or not os.path.isdir(full):
                continue
            if os.path.exists(os.path.join(full, ".git")):
                add(_toplevel(full))
            elif depth < 2:
                scan(full, depth + 1)

    scan(base, 1)
    return {"repos": found}


# ----- status -----

_status_cache = {}  # top -> (time, fp, data)
_status_lock = threading.Lock()
STATUS_TTL = 2.0


def _unquote(s):
    """C-style quoted path from git (only when it contains ", \\ or control chars)."""
    if len(s) < 2 or s[0] != '"' or s[-1] != '"':
        return s
    s = s[1:-1]
    out, i = bytearray(), 0
    esc = {"n": 10, "t": 9, "r": 13, '"': 34, "\\": 92, "a": 7, "b": 8, "f": 12, "v": 11}
    while i < len(s):
        c = s[i]
        if c == "\\" and i + 1 < len(s):
            n = s[i + 1]
            if n in esc:
                out.append(esc[n]); i += 2; continue
            if re.fullmatch(r"[0-7]{3}", s[i + 1:i + 4]):
                out.append(int(s[i + 1:i + 4], 8)); i += 4; continue
        out += c.encode("utf-8"); i += 1
    return out.decode("utf-8", "replace")


def _kind(x, y):
    if x in "UD" and y in "UD" and (x == "U" or y == "U" or x == y == "D") or x == "A" and y == "A":
        return "conflicted"
    for c in (y, x):
        if c == "D":
            return "deleted"
    if "R" in (x, y):
        return "renamed"
    if "C" in (x, y):
        return "copied"
    if x == "A":
        return "added"
    if "T" in (x, y):
        return "typechange"
    return "modified"


_status_locks = collections.defaultdict(threading.Lock)


def status(top, fresh=False, ttl=STATUS_TTL):
    """One `git status` per repository at a time; callers arriving meanwhile
    (tree colours, Local Changes) wait and share the result. ttl: how old a
    result may be when HEAD / index did not move (working-tree edits do not
    move them, so the page asks again now and then)."""
    t_req = time.time()
    with _status_locks[os.path.normcase(top)]:
        fp = fingerprint(top)
        with _status_lock:
            hit = _status_cache.get(top)
        if hit and hit[1] == fp and (hit[0] >= t_req or not fresh and time.time() - hit[0] < ttl):
            return hit[2]
        return _status_run(top, fp)


def _status_run(top, fp):
    t0 = time.time()
    out = run(["status", "--porcelain=v2", "-z", "--branch", "--untracked-files=normal",
               "--ignore-submodules=dirty"], top, timeout=30)
    ms = int((time.time() - t0) * 1000)
    branch = {"oid": "", "head": "", "upstream": "", "ahead": 0, "behind": 0}
    files, truncated = [], False
    recs = out.decode("utf-8", "replace").split("\0")
    i = 0
    while i < len(recs):
        r = recs[i]
        i += 1
        if not r:
            continue
        if r.startswith("# "):
            k, _, v = r[2:].partition(" ")
            if k == "branch.oid":
                branch["oid"] = "" if v == "(initial)" else v
            elif k == "branch.head":
                branch["head"] = "" if v == "(detached)" else v
                branch["detached"] = v == "(detached)"
            elif k == "branch.upstream":
                branch["upstream"] = v
            elif k == "branch.ab":
                m = re.match(r"\+(\d+) -(\d+)", v)
                if m:
                    branch["ahead"], branch["behind"] = int(m.group(1)), int(m.group(2))
            continue
        if len(files) >= STATUS_MAX:
            truncated = True
            if r[0] == "2":
                i += 1
            continue
        t = r[0]
        if t == "1":
            p = r.split(" ", 8)
            if len(p) < 9:
                continue
            x, y = p[1][0], p[1][1]
            files.append({"path": p[8], "x": x, "y": y, "kind": _kind(x, y),
                          "staged": x != ".", "unstaged": y != ".", "sub": p[2] != "N..."})
        elif t == "2":
            p = r.split(" ", 9)
            orig = recs[i] if i < len(recs) else ""
            i += 1
            if len(p) < 10:
                continue
            x, y = p[1][0], p[1][1]
            files.append({"path": p[9], "orig": orig, "x": x, "y": y, "kind": _kind(x, y),
                          "staged": x != ".", "unstaged": y != ".", "sub": p[2] != "N..."})
        elif t == "u":
            p = r.split(" ", 10)
            if len(p) < 11:
                continue
            files.append({"path": p[10], "x": p[1][0], "y": p[1][1], "kind": "conflicted",
                          "staged": False, "unstaged": True, "sub": False})
        elif t == "?":
            files.append({"path": r[2:], "x": "?", "y": "?", "kind": "untracked",
                          "staged": False, "unstaged": True, "sub": False})
    eol_ms = _mark_eol(top, files, branch["oid"])
    data = {"repo": _summary(top), "branch": branch, "files": files, "truncated": truncated, "ms": ms,
            "eol_only": sum(1 for f in files if f.get("eol")), "eol_ms": eol_ms}
    with _status_lock:
        _status_cache[top] = (time.time(), fp, data)
    return data


# ----- line-ending-only changes -----
# A file git calls modified whose text differs from HEAD only in CR at line ends (an editor or
# core.autocrlf / .gitattributes rewrote CRLF <-> LF) gets "eol": true. The page hides those by
# default (Local Changes, counts, tree colours). Judged by `git diff HEAD --numstat
# --ignore-cr-at-eol`, which leaves such files out; only for files whose index or working tree
# equals HEAD on one side (x or y "."), so a staged real change is never hidden. Results are kept
# per file (HEAD, mtime, size): a status poll re-checks only files that changed.
EOL_CHECK_MAX = 3000   # files checked per status run (the rest: shown as changed)
EOL_ARGS_MAX = 24000   # characters of paths per git call (Windows command line limit 32k)
_eol_cache = {}        # top -> {path: ((head, mtime_ns, size), eol_only)}


def _mark_eol(top, files, head):
    if not head:
        return 0
    t0 = time.time()
    cache = _eol_cache.setdefault(top, {})
    todo, keys = [], {}
    for f in files:
        if f["kind"] != "modified" or f["sub"] or "." not in (f["x"], f["y"]):
            continue
        try:
            stt = os.stat(os.path.join(top, f["path"].replace("/", os.sep)))
        except OSError:
            continue
        k = (head, stt.st_mtime_ns, stt.st_size)
        hit = cache.get(f["path"])
        if hit and hit[0] == k:
            f["eol"] = hit[1]
        elif len(todo) < EOL_CHECK_MAX:
            todo.append(f)
            keys[f["path"]] = k
    batch, size = [], 0
    for f in todo + [None]:
        if f is not None and size + len(f["path"]) < EOL_ARGS_MAX:
            batch.append(f); size += len(f["path"]) + 3
            continue
        if batch:
            try:
                out = run(["diff", "HEAD", "--numstat", "--ignore-cr-at-eol", "--no-textconv", "--no-ext-diff",
                           "--no-renames", "-z", "--"] + [x["path"] for x in batch], top, timeout=30)
                listed = {r.split("\t", 2)[2] for r in out.decode("utf-8", "replace").split("\0") if r.count("\t") >= 2}
                for x in batch:
                    x["eol"] = x["path"] not in listed
                    cache[x["path"]] = (keys[x["path"]], x["eol"])
            except GitError:
                pass
        batch, size = ([f], len(f["path"]) + 3) if f is not None else ([], 0)
    if len(cache) > 20000:
        cache.clear()
    for f in files:
        if not f.get("eol"):
            f.pop("eol", None)
    return int((time.time() - t0) * 1000)


def eol_only(top):
    """Repo-relative paths git calls changed whose difference is only line endings."""
    return {f["path"] for f in status(top, fresh=True)["files"] if f.get("eol")}


_WOULD = re.compile(r"would be overwritten by \w+:\s*\n((?:\t.*\n?)+)")


def _blocking_files(text):
    """Files git names in "Your local changes … would be overwritten by merge / checkout"."""
    out = []
    for m in _WOULD.finditer(text.replace("\r\n", "\n")):
        out += [ln.strip() for ln in m.group(1).splitlines() if ln.strip()]
    return out


def _eol_note(top, text, res):
    """A refused pull / checkout: which of the files in the way differ only in line endings."""
    files = _blocking_files(text)
    if not files:
        return res
    try:
        eol = eol_only(top)
    except GitError:
        return res
    hit = [f for f in files if f in eol]
    if hit:
        res.update(eol_files=hit[:200], eol_all=len(hit) == len(files), blocking=files[:200])
        try:
            res["autocrlf"] = _cfg(top, "core.autocrlf")
        except GitError:
            pass
    return res


_CODE = {"modified": "M", "added": "A", "deleted": "D", "renamed": "R", "copied": "A", "typechange": "M",
         "conflicted": "C", "untracked": "U"}


def decor(dirs, with_eol=False):
    """Tree colours for the folders the page shows: {files: {key: code}, dirs: {key: code}}.
    with_eol: line-ending-only changes coloured too (else they look unchanged)."""
    base = S.base_root()
    if not base:
        return {"files": {}, "dirs": {}}
    tops = []
    for d in (dirs or [""])[:200]:
        full = S._safe_join(base, d) if d else base
        if not full or not os.path.isdir(full):
            continue
        top = _toplevel(full)
        if top and top not in tops:
            tops.append(top)
        if len(tops) >= 12:
            break
    files, folders = {}, {}
    nbase = os.path.normcase(base)
    for top in tops:
        with _status_lock:
            hit = _status_cache.get(top)
        slow = hit[2].get("ms", 0) / 1000 if hit else 0
        try:  # tree colours may lag a little; a slow repository is asked less often
            st = status(top, ttl=max(8.0, slow * 15))
        except GitError:
            continue
        for f in st["files"]:
            if f.get("eol") and not with_eol:
                continue
            full = os.path.join(top, f["path"].rstrip("/").replace("/", os.sep))
            nf = os.path.normcase(full)
            if not (nf == nbase or nf.startswith(nbase + os.sep)):
                continue
            key = os.path.relpath(full, base).replace("\\", "/")
            code = _CODE.get(f["kind"], "M")
            if f["path"].endswith("/"):  # wholly untracked folder
                folders[key] = code
            else:
                files[key] = code
            parts = key.split("/")[:-1]
            for j in range(1, len(parts) + 1):
                k = "/".join(parts[:j])
                if folders.get(k) != "C":
                    folders[k] = "C" if code == "C" else folders.get(k, "M")
    return {"files": files, "dirs": folders, "repos": [t.replace("\\", "/") for t in tops]}


# ----- refs -----

_refs_cache = {}  # top -> (fp, data)


def refs(top, cached=False):
    fp = fingerprint(top)
    hit = _refs_cache.get(top)
    if hit and (hit[0] == fp or cached and time.time() - hit[2] < 5):
        return hit[1]
    fmt = "%(refname)%1f%(objectname)%1f%(*objectname)%1f%(upstream:short)%1f%(upstream:track,nobracket)%1f%(HEAD)%1f%(committerdate:unix)"
    out = run(["for-each-ref", "--format=" + fmt, "refs/heads", "refs/remotes", "refs/tags"], top, timeout=15)
    local, remote, tags, allr = [], [], [], []
    head = ""
    for ln in out.decode("utf-8", "replace").splitlines():
        p = ln.split("\x1f")
        if len(p) < 7:
            continue
        ref, sha, peeled, up, track, is_head, ct = p
        sha = peeled or sha
        item = {"ref": ref, "sha": sha}
        if ref.startswith("refs/heads/"):
            item["name"] = ref[11:]
            m_a, m_b = re.search(r"ahead (\d+)", track), re.search(r"behind (\d+)", track)
            item.update(upstream=up, ahead=int(m_a.group(1)) if m_a else 0, behind=int(m_b.group(1)) if m_b else 0,
                        gone="gone" in track, current=is_head == "*", t=int(ct or 0))
            if is_head == "*":
                head = item["name"]
            local.append(item)
        elif ref.startswith("refs/remotes/"):
            item["name"] = ref[13:]
            if item["name"].endswith("/HEAD"):
                continue
            remote.append(item)
        elif ref.startswith("refs/tags/"):
            item["name"] = ref[10:]
            tags.append(item)
        allr.append(item)
        if len(allr) >= 20000:
            break
    try:
        head_sha = run(["rev-parse", "--verify", "--quiet", "HEAD"], top, ok=(0, 1)).decode().strip()
    except GitError:
        head_sha = ""
    try:
        user = run(["config", "--get", "user.name"], top, timeout=5, ok=(0, 1)).decode("utf-8", "replace").strip()
    except GitError:
        user = ""
    data = {"repo": _summary(top), "head": head, "head_sha": head_sha, "user": user, "local": local, "remote": remote,
            "tags": tags, "all": allr}
    _refs_cache[top] = (fp, data, time.time())
    if len(_refs_cache) > 50:
        _refs_cache.pop(next(iter(_refs_cache)))
    return data


def authors(top):
    out = run(["log", "--format=%an", "-n", "3000", "--branches", "--remotes", "HEAD", "--"], top, timeout=15,
              kind="authors:" + top, ok=(0, 128))
    cnt = collections.Counter(a for a in out.decode("utf-8", "replace").splitlines() if a)
    return {"authors": [a for a, _ in cnt.most_common(300)]}


# ----- log (sessions: one streaming `git log` per view, pages read from it) -----

LOG_FMT = "%x1e%H%x1f%P%x1f%an%x1f%ae%x1f%at%x1f%D%x1f%s%x1f"


class _LogSession:
    def __init__(self, key, args, top):
        self.key, self.top = key, top
        self.recs, self.done, self.err = [], False, None
        self.killed = False  # replaced by a newer session: its exit code is not an error
        self.cond = threading.Condition()
        self.t0 = time.time()
        self.args = args
        self.proc = _popen(args, top, BASE_CONFIG + _repo_overrides(top))
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        buf = b""
        try:
            while True:
                chunk = self.proc.stdout.read1(1 << 16) if hasattr(self.proc.stdout, "read1") else self.proc.stdout.read(1 << 16)
                if not chunk:
                    break
                buf += chunk
                parts = buf.split(b"\x1e")
                buf = parts.pop()  # incomplete (or the trailing name-status of the last record)
                new = [r for r in (self._parse(p) for p in parts if p.strip()) if r]
                if new:
                    with self.cond:
                        self.recs.extend(new)
                        self.cond.notify_all()
                if len(self.recs) >= LOG_MAX:
                    self.proc.kill()
                    break
            if buf.strip():
                r = self._parse(buf)
                if r:
                    with self.cond:
                        self.recs.append(r)
            self.proc.wait(timeout=5)
            rc = self.proc.returncode
            err = self.proc.stderr.read().decode("utf-8", "replace").strip()
            if self.killed:
                pass
            elif rc not in (0, None) and not self.recs and rc != 128:
                self.err = err[:500] or f"git log exited {rc}"
            elif rc == 128 and not self.recs and "does not have any commits" not in err:
                self.err = err[:500] if "unknown revision" not in err else None
        except (OSError, ValueError, subprocess.SubprocessError) as e:
            self.err = str(e)
        finally:
            with self.cond:
                self.done = True
                self.cond.notify_all()
            _log_console(self.args, self.top, (time.time() - self.t0) * 1000, self.proc.returncode, "log",
                         self.err or "")

    @staticmethod
    def _parse(raw):
        p = raw.decode("utf-8", "replace").split("\x1f")
        if len(p) < 8:
            return None
        h, parents, an, ae, at, refs_, subj, tail = p[0].strip(), p[1], p[2], p[3], p[4], p[5], p[6], p[7]
        rec = {"h": h, "p": parents.split() if parents else [], "an": an, "ae": ae, "at": int(at or 0),
               "refs": [r.strip() for r in refs_.split(",") if r.strip()] if refs_ else [], "s": subj}
        tail = tail.strip("\n")
        if tail:  # --name-status of a --follow history: the file's path in this commit
            last = None
            for ln in tail.split("\n"):
                f = ln.split("\t")
                if len(f) >= 2 and f[0][:1] in "MADRCTU":
                    last = (f[0][:1], _unquote(f[-1]), _unquote(f[1]) if len(f) >= 3 else None)
            if last:
                rec["fs"], rec["path_at"] = last[0], last[1]
                if last[2]:
                    rec["path_from"] = last[2]
        return rec

    def page(self, offset, n, wait=20):
        end = time.time() + wait
        with self.cond:
            while len(self.recs) < offset + n and not self.done:
                left = end - time.time()
                if left <= 0:
                    break
                self.cond.wait(left)
            return self.recs[offset:offset + n], self.done, len(self.recs)

    def kill(self):
        self.killed = True
        try:
            if self.proc.poll() is None:
                self.proc.kill()
        except OSError:
            pass


_sessions = {}  # (top, view) -> _LogSession
_sess_lock = threading.Lock()


def _multi(q, name):
    v = q.get(name) or []
    return [x for x in (v if isinstance(v, list) else [v]) if isinstance(x, str) and x]


def log(top, q):
    view = "history" if _first(q, "follow") == "1" else "log"
    try:
        offset = max(0, int(_first(q, "offset") or 0))
        n = max(1, min(int(_first(q, "n") or 200), LOG_PAGE_MAX))
    except ValueError:
        raise GitError("bad_arg", "offset / n")
    args = ["log", "--date-order", "--no-ext-diff", "--no-textconv", "--format=" + LOG_FMT]
    known = None
    revs = []
    for r in _multi(q, "ref")[:50]:
        known = known or _refnames(top)
        if r in known or r == "HEAD":
            revs.append(r)
        else:
            raise GitError("bad_arg", "unknown branch: " + r)
    text = (_first(q, "text") or "").strip()[:200]
    regex, case = _first(q, "regex") == "1", _first(q, "case") == "1"
    hash_hit = None
    if text and _HEX.fullmatch(text):
        try:
            out = run(["rev-parse", "--verify", "--quiet", "--end-of-options", text + "^{commit}"], top, ok=(0, 1))
            hash_hit = out.decode().strip() or None
        except GitError:
            hash_hit = None
    if hash_hit:
        args += ["-n", "1", "--end-of-options", hash_hit]
    else:
        if text:
            args.append("--grep=" + text)
        for a in _multi(q, "author")[:20]:
            args.append("--author=" + a[:200])
        if text or _multi(q, "author"):
            args.append("--extended-regexp" if regex else "--fixed-strings")
            if not case:
                args.append("--regexp-ignore-case")
        for k in ("since", "until"):
            v = _first(q, k)
            if v:
                if not _DATE.fullmatch(v):
                    raise GitError("bad_arg", k)
                args.append(f"--{k}={v} " + ("00:00:00" if k == "since" else "23:59:59"))
        paths = [_check_rel(p) for p in _multi(q, "path")[:20]]
        if view == "history":
            if len(paths) != 1:
                raise GitError("bad_arg", "history needs one path")
            args += ["--follow", "--name-status", "-M"]
        elif paths:
            args.append("--parents")  # parent rewriting keeps the graph connected
        head = ["HEAD"] if refs(top, cached=True)["head_sha"] else []
        if revs or view == "history":
            args += ["--end-of-options"] + (revs or head) + ["--"] + paths
        else:  # every branch, remote branch and tag (not refs/stash)
            args += ["--branches", "--remotes", "--tags", "--end-of-options"] + head + ["--"] + paths
    key = repr(args)
    slot = (top, view)
    with _sess_lock:
        s = _sessions.get(slot)
        if s and (s.key != key or _first(q, "reload") == "1" and offset == 0):
            s.kill()
            s = None
        if s is None:
            s = _LogSession(key, args, top)
            _sessions[slot] = s
            while len(_sessions) > 6:
                old = next(iter(_sessions))
                _sessions.pop(old).kill()
    recs, done, total = s.page(offset, n)
    while s.killed and not recs:  # a second request replaced this session: read from its successor
        with _sess_lock:
            nxt = _sessions.get(slot)
        if nxt is None or nxt is s or nxt.key != key:
            raise GitError("busy")
        s = nxt
        recs, done, total = s.page(offset, n)
    if s.err and not recs:
        raise GitError("git_failed", s.err)
    return {"commits": recs, "offset": offset, "done": done, "loaded": total,
            "has_more": not done or total > offset + len(recs), "hash_hit": bool(hash_hit),
            "ms": int((time.time() - s.t0) * 1000)}


def _first(q, name):
    v = q.get(name)
    if isinstance(v, list):
        return v[0] if v else ""
    return v or ""


# ----- one commit -----

def commit(top, rev):
    sha = _check_rev(rev, top)
    fmt = "%H%x1f%P%x1f%an%x1f%ae%x1f%at%x1f%cn%x1f%ce%x1f%ct%x1f%D%x1f%B"
    out = run(["show", "-s", "--no-ext-diff", "--no-textconv", "--format=" + fmt, "--end-of-options", sha], top)
    p = out.decode("utf-8", "replace").split("\x1f", 9)
    if len(p) < 10:
        raise GitError("git_failed", "unexpected show output")
    parents = p[1].split()
    c = {"h": p[0], "p": parents, "an": p[2], "ae": p[3], "at": int(p[4] or 0), "cn": p[5], "ce": p[6],
         "ct": int(p[7] or 0), "refs": [r.strip() for r in p[8].split(",") if r.strip()], "body": p[9].rstrip("\n")}
    tgt = ["--root", "--end-of-options", sha] if not parents else ["--end-of-options", parents[0], sha]
    out = run(["diff-tree", "-r", "-M", "--no-ext-diff", "--no-textconv", "-z", "--raw", "--numstat"] + tgt,
              top, timeout=30)
    files, stats = _parse_raw_numstat(out.decode("utf-8", "replace").split("\0"))
    for f in files:
        a, d = stats.get(f["path"], ("", ""))
        f["binary"] = a == "-"
        f["add"] = int(a) if a.isdigit() else 0
        f["del"] = int(d) if d.isdigit() else 0
    c["files"] = files
    c["truncated"] = len(files) >= COMMIT_FILES_MAX
    c["parent"] = parents[0] if parents else None
    return c


def _with_stats(files, stats):
    for f in files:
        a, d = stats.get(f["path"], ("", ""))
        f["binary"] = a == "-"
        f["add"] = int(a) if a.isdigit() else 0
        f["del"] = int(d) if d.isdigit() else 0
    return files


def _tree_diff(top, base, head):
    """files changed from `base` (None: the empty tree) to `head`, with line counts."""
    # git knows the empty tree without it being stored (SHA-1 / SHA-256 repositories)
    base = base or ("4b825dc642cb6eb9a060e54bf8d69288fbee4904" if len(head) == 40 else
                    "6ef19b41225c5369f1c104d45d8d85efa9b057b53b14b4b9b939dd74decc5321")
    tgt = ["--end-of-options", base, head]
    out = run(["diff-tree", "-r", "-M", "--no-ext-diff", "--no-textconv", "-z", "--raw", "--numstat"] + tgt, top, timeout=30, kind="commits")
    return _with_stats(*_parse_raw_numstat(out.decode("utf-8", "replace").split("\0")))


# ----- several commits (Log multi-selection) -----
MULTI_MAX = 500         # commits whose own changes are listed (each one is a git log argument: ~41 bytes)
MULTI_RANGE_MAX = 5000  # a contiguous range only needs its two ends


def commits(top, revs):
    """Changed files of several selected commits (`revs`: full hashes, newest first as listed).
    A contiguous range (the selection is exactly base..newest, base = the oldest one's first parent) is
    one diff base..newest. Otherwise: the union of each commit's own changes (one `git log`), statuses
    merged per file and line counts added up; a file's diff still compares base with the newest
    (`bh`: its status there, "" when base and newest have the same content)."""
    revs = list(dict.fromkeys(r for r in revs if isinstance(r, str)))
    if len(revs) < 2:
        raise GitError("bad_arg", "select two or more commits")
    if len(revs) > MULTI_RANGE_MAX:
        raise GitError("bad_arg", f"more than {MULTI_RANGE_MAX} commits")
    for r in revs:
        if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", r):
            raise GitError("bad_arg", "rev")
    t0 = time.time()
    head, oldest = revs[0], revs[-1]
    out = run(["rev-list", "--parents", "-n", "1", "--end-of-options", oldest], top, kind="commits").decode().split()
    if not out or out[0] != oldest:
        raise GitError("bad_arg", "unknown revision")
    base = out[1] if len(out) > 1 else None
    out = run(["rev-list", "--max-count=" + str(len(revs) + 1), "--end-of-options", head] + (["^" + base] if base else []),
              top, kind="commits").decode().split()
    is_range = set(out) == set(revs)
    res = {"n": len(revs), "range": is_range, "base": base, "head": head, "partial": 0}
    if is_range:
        files = _tree_diff(top, base, head)
        for f in files:
            f["bh"] = f["status"]
            f["n"] = None
    else:
        use = revs[:MULTI_MAX]
        res["partial"] = len(revs) - len(use)
        out = run(["log", "--no-walk=unsorted", "-m", "--first-parent", "--root", "-r", "-M", "--no-ext-diff", "--no-textconv",
                   "-z", "--raw", "--numstat", "--format=%x01%H", "--end-of-options"] + use, top, timeout=60, kind="commits")
        per = {}  # hash -> files
        cur = None
        chunk = []
        for t in out.decode("utf-8", "replace").split("\0") + ["\x01"]:
            t = t.lstrip("\n")
            if t.startswith("\x01"):
                if cur:
                    per[cur] = _with_stats(*_parse_raw_numstat(chunk))
                cur, chunk = t[1:], []
            else:
                chunk.append(t)
        merged = {}
        for h in reversed(use):  # oldest first
            for f in per.get(h, []):
                m = merged.get(f["path"])
                if m is None:
                    m = merged[f["path"]] = {"path": f["path"], "first": f["status"], "status": f["status"], "add": 0, "del": 0,
                                             "binary": False, "n": 0}
                    if f.get("orig"):
                        m["orig"] = f["orig"]
                m["last"] = f["status"]
                m["add"] += f["add"]
                m["del"] += f["del"]
                m["binary"] = m["binary"] or f["binary"]
                m["n"] += 1
        files = []
        for m in merged.values():
            first, last = m.pop("first"), m.pop("last")
            if last == "D" and first != "A":
                m["status"] = "D"
            elif first == "A" and last != "D":
                m["status"] = "A"
            elif first in "RC" and m.get("orig"):
                m["status"] = first
            else:
                m["status"] = "M"
            files.append(m)
            if len(files) >= COMMIT_FILES_MAX:
                break
        files.sort(key=lambda f: f["path"])
        bh = {f["path"]: f for f in _tree_diff(top, base, head)}
        for f in files:
            b = bh.get(f["path"])
            f["bh"] = b["status"] if b else ""
            if b and b.get("orig"):
                f["bh_orig"] = b["orig"]
    res["files"] = files
    res["truncated"] = len(files) >= COMMIT_FILES_MAX
    res["ms"] = int((time.time() - t0) * 1000)
    return res


def _parse_raw_numstat(tok):
    """`diff-tree -z --raw --numstat`: raw records (":mode mode sha sha S" NUL path [NUL path])
    then numstat records ("add TAB del TAB path" or "add TAB del TAB" NUL old NUL new)."""
    files, stats, i = [], {}, 0
    while i < len(tok):
        t = tok[i]
        if not t:
            i += 1
            continue
        if t.startswith(":"):
            st = t.split(" ")[-1]
            if st[:1] in "RC":
                if len(files) < COMMIT_FILES_MAX:
                    files.append({"status": st[0], "orig": tok[i + 1] if i + 1 < len(tok) else "",
                                  "path": tok[i + 2] if i + 2 < len(tok) else ""})
                i += 3
            else:
                if len(files) < COMMIT_FILES_MAX:
                    files.append({"status": st[:1], "path": tok[i + 1] if i + 1 < len(tok) else ""})
                i += 2
            continue
        f = t.split("\t")
        if len(f) == 3 and f[2] == "" and i + 2 < len(tok):  # rename: "add TAB del TAB" NUL old NUL new
            stats[tok[i + 2]] = (f[0], f[1])
            i += 3
        else:
            if len(f) == 3:
                stats[f[2]] = (f[0], f[1])
            i += 1
    return files, stats


# ----- file text at a revision -----

def show(top, rev, path):
    rel = _check_rel(path)
    if rev == "WORKTREE":
        full = os.path.realpath(os.path.join(top, rel.replace("/", os.sep)))
        if not S._within(full, top) or not os.path.isfile(full):
            return {"missing": True, "text": ""}
        size = os.path.getsize(full)
        if size > SHOW_MAX:
            return {"too_big": True, "text": "", "size": size}
        with open(full, "rb") as f:
            raw = f.read()
    else:
        spec = ":" + rel if rev == "INDEX" else _check_rev(rev, top) + ":" + rel
        rc, raw, err = _raw(["cat-file", "blob", spec], top, BASE_CONFIG + _repo_overrides(top), timeout=20)
        if rc != 0:
            if rev == "INDEX":  # conflicted / not staged: stage 2 (ours) if any
                rc, raw, err = _raw(["cat-file", "blob", ":2:" + rel], top, BASE_CONFIG + _repo_overrides(top), timeout=20)
            if rc != 0:
                return {"missing": True, "text": ""}
        if len(raw) > SHOW_MAX:
            return {"too_big": True, "text": "", "size": len(raw)}
    if S.sniff_binary(raw[:8192]):
        return {"binary": True, "text": "", "size": len(raw)}
    text, enc = S._decode(raw)[:2]
    return {"text": text, "encoding": enc, "size": len(raw)}


# ----- blame -----

def blame(path_key, ignore_ws=False):
    full = S.resolve_read_path(path_key)
    if not full or not os.path.isfile(full):
        raise GitError("bad_arg", "not a file")
    top = _toplevel(os.path.dirname(full))
    if not top:
        raise GitError("not_repo")
    if os.path.getsize(full) > BLAME_MAX:
        raise GitError("too_big")
    rel = os.path.relpath(full, top).replace("\\", "/")
    args = ["blame", "--porcelain", "--no-textconv"] + (["-w"] if ignore_ws else []) + ["--", rel]
    try:
        out = run(args, top, timeout=60, kind="blame")
    except GitError as e:
        if e.code == "git_failed" and ("no such path" in e.detail or "no such ref" in e.detail):
            return {"repo": _summary(top), "untracked": True, "lines": [], "commits": []}
        raise
    commits, index, lines = [], {}, []
    cur = None
    for ln in out.decode("utf-8", "replace").split("\n"):
        if not ln:
            continue
        if ln[0] == "\t":
            if cur is not None:
                lines.append(index[cur])
            continue
        p = ln.split(" ")
        if len(p) >= 3 and re.fullmatch(r"[0-9a-f]{40,64}", p[0]):
            cur = p[0]
            if cur not in index:
                index[cur] = len(commits)
                commits.append({"h": cur, "an": "", "at": 0, "s": "", "f": "", "uncommitted": set(cur) == {"0"}})
            continue
        if cur is None:
            continue
        c = commits[index[cur]]
        k, _, v = ln.partition(" ")
        if k == "author":
            c["an"] = v
        elif k == "author-time":
            c["at"] = int(v or 0)
        elif k == "summary":
            c["s"] = v
        elif k == "author-mail":
            c["ae"] = v.strip("<>")
        elif k == "filename":  # path in that commit (differs after a rename)
            c["f"] = _unquote(v)
    return {"repo": _summary(top), "rel": rel, "lines": lines, "commits": commits}


# ----- stash (list only) -----

def stash(top):
    gd = _common_dir(_git_dir(top))
    if not os.path.exists(os.path.join(gd, "refs", "stash")) and not _has_packed(gd, "refs/stash"):
        return {"items": []}
    out = run(["log", "-g", "--no-ext-diff", "--format=%gd%x1f%H%x1f%at%x1f%gs", "refs/stash", "--"], top,
              timeout=15, ok=(0, 128))
    items = []
    for ln in out.decode("utf-8", "replace").splitlines():
        p = ln.split("\x1f")
        if len(p) == 4:
            items.append({"name": p[0], "h": p[1], "at": int(p[2] or 0), "s": p[3]})
    return {"items": items[:500]}


def _has_packed(gd, ref):
    try:
        with open(os.path.join(gd, "packed-refs"), "r", encoding="utf-8", errors="replace") as f:
            return any(ln.rstrip().endswith(" " + ref) for ln in f)
    except OSError:
        return False


# ----- AgentO / terminal (outside programs; POST, guarded) -----

def _running_exe(name):
    """Full path of a running process with this exe name (Windows), else None."""
    if os.name != "nt":
        return None
    import ctypes
    from ctypes import wintypes
    psapi, k32 = ctypes.WinDLL("psapi"), ctypes.WinDLL("kernel32")
    arr = (wintypes.DWORD * 4096)()
    needed = wintypes.DWORD()
    if not psapi.EnumProcesses(arr, ctypes.sizeof(arr), ctypes.byref(needed)):
        return None
    k32.OpenProcess.restype = wintypes.HANDLE
    for pid in arr[:needed.value // ctypes.sizeof(wintypes.DWORD)]:
        h = k32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            continue
        try:
            buf = ctypes.create_unicode_buffer(1024)
            size = wintypes.DWORD(1024)
            if k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
                if os.path.basename(buf.value).lower() == name.lower():
                    return buf.value
        finally:
            k32.CloseHandle(h)
    return None


def agento_path(user_path=""):
    cands = []
    if user_path and os.path.basename(user_path).lower() == "agento.exe":
        cands.append(user_path)
    try:
        r = _running_exe("AgentO.exe")
        if r:
            cands.append(r)
    except Exception:
        pass
    la = os.environ.get("LOCALAPPDATA", "")
    for root in (os.path.join(la, "Programs", "AgentO"), os.path.join(os.environ.get("ProgramFiles", ""), "AgentO")):
        cands.append(os.path.join(root, "AgentO.exe"))
    for c in cands:
        if c and os.path.isfile(c):
            return c
    return None


def api_agento(data):
    exe = agento_path(str(data.get("path") or ""))
    if not exe:
        return {"launched": False, "reason": "not_found"}
    if data.get("probe"):
        return {"launched": False, "path": exe}
    try:
        subprocess.Popen([exe], cwd=os.path.dirname(exe), close_fds=True,
                         creationflags=getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
    except OSError as e:
        return {"launched": False, "reason": str(e)}
    return {"launched": True, "path": exe}


def api_terminal(data):
    try:
        top = repo_of(str(data.get("repo") or ""))
    except GitError as e:
        return 400, {"error": e.code}
    wt = shutil.which("wt")
    try:
        if wt:
            subprocess.Popen([wt, "-d", top], close_fds=True)
        else:
            subprocess.Popen(["cmd.exe", "/K", "cd", "/d", top], cwd=top, close_fds=True,
                             creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0))
    except OSError as e:
        return 500, {"error": str(e)}
    return {"ok": True, "terminal": "wt" if wt else "cmd"}


# ----- Pull (the one write ReadO runs itself) -----
# `git pull --ff-only`, run as its two halves so the page can be warned before files it has
# unsaved edits for change: fetch the upstream's remote, then `merge --ff-only <fetched sha>`.
# Never a merge commit, rebase or autostash; anything but a fast-forward stops with nothing changed.

_write_locks = collections.defaultdict(threading.Lock)  # one pull / fetch / checkout per repo
_REMOTE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.\-/]{0,199}")


def _wrun(args, top):
    """A pull step: (rc, stdout + stderr text). Console keeps the output."""
    rc, out, err = _raw(args, top, BASE_CONFIG + _repo_overrides(top), PULL_TIMEOUT, write=True)
    return rc, "\n".join(x for x in (out.decode("utf-8", "replace").strip(), err) if x)


def _cfg(top, key):
    out = run(["config", "--get", key], top, timeout=5, ok=(0, 1)).decode("utf-8", "replace").strip()
    return out


def _safe_url(u):
    """A remote URL for display, without a user:password@ part."""
    return re.sub(r"^([a-z][a-z0-9+.\-]*://)[^/@]*@", r"\1", u or "", flags=re.I)


def pull_info(top):
    """What the Pull button / confirmation shows: branch, upstream, remote, why it cannot run."""
    st = status(top, fresh=True)
    b = st["branch"]
    out = {"repo": _summary(top), "branch": b.get("head", ""), "upstream": b.get("upstream", ""),
           "ahead": b.get("ahead", 0), "behind": b.get("behind", 0), "dirty": len(st["files"]),
           "eol_only": st.get("eol_only", 0),
           "remote": "", "url": "", "state": repo_state(top), "reason": ""}
    if not out["branch"]:
        out["reason"] = "detached"
    elif not out["upstream"]:
        out["reason"] = "no_upstream"
    elif out["state"]:
        out["reason"] = "repo_busy"
    if out["branch"]:
        out["remote"] = _cfg(top, "branch." + out["branch"] + ".remote")
        if out["remote"] and out["remote"] != "." and _REMOTE.fullmatch(out["remote"]):
            out["url"] = _safe_url(_cfg(top, "remote." + out["remote"] + ".url"))
    if not out["reason"] and out["remote"] != "." and not _REMOTE.fullmatch(out["remote"] or ""):
        out["reason"] = "no_upstream"
    return out


def _is_ancestor(top, a, b):
    return _raw(["merge-base", "--is-ancestor", a, b], top, BASE_CONFIG + _repo_overrides(top))[0] == 0


def _pull_error(text):
    t = text.lower()
    if "would be overwritten" in t or "untracked working tree files" in t:
        return "local_changes"
    if "not possible to fast-forward" in t or "diverg" in t:
        return "non_ff"
    if ("could not read username" in t or "authentication failed" in t or "terminal prompts disabled" in t
            or "permission denied" in t or "could not read from remote repository" in t):
        return "auth"
    return "git_failed"


def pull(top, unsaved=(), allow_unsaved=False):
    lock = _write_locks[os.path.normcase(top)]
    if not lock.acquire(blocking=False):
        raise GitError("busy", "a pull / checkout is already running in this repository")
    try:
        inf = pull_info(top)
        if inf["reason"]:
            return {"ok": False, "error": inf["reason"], "info": inf}
        output = []
        if inf["remote"] != ".":
            rc, text = _wrun(["fetch", inf["remote"]], top)
            output.append("$ git fetch " + inf["remote"] + ("\n" + text if text else ""))
            if rc:
                return {"ok": False, "error": _pull_error(text), "output": "\n".join(output), "info": inf}
        head = run(["rev-parse", "--verify", "HEAD^{commit}"], top).decode().strip()
        up = run(["rev-parse", "--verify", "--end-of-options", "@{upstream}^{commit}"], top).decode().strip()
        if head == up or _is_ancestor(top, up, head):
            return {"ok": True, "updated": False, "output": "\n".join(output + ["Already up to date."]), "info": inf}
        if not _is_ancestor(top, head, up):
            output.append(f"{inf['branch']} and {inf['upstream']} have diverged — not a fast-forward; nothing changed.")
            return {"ok": False, "error": "non_ff", "output": "\n".join(output), "info": inf}
        files = [f for f in run(["diff-tree", "-r", "--name-only", "--no-renames", "-z", head, up], top,
                                timeout=30).decode("utf-8", "replace").split("\0") if f]
        unsaved = {str(u).replace("\\", "/") for u in (unsaved or []) if isinstance(u, str)}
        hit = sorted(f for f in files if f in unsaved)
        if hit and not allow_unsaved:
            return {"ok": False, "need_confirm": "unsaved", "files": hit, "incoming": len(files),
                    "output": "\n".join(output), "info": inf}
        rc, text = _wrun(["merge", "--ff-only", up], top)
        output.append("$ git merge --ff-only " + up[:12] + ("\n" + text if text else ""))
        if rc:
            return _eol_note(top, text, {"ok": False, "error": _pull_error(text), "output": "\n".join(output), "info": inf})
        n = int(run(["rev-list", "--count", head + ".." + up], top).decode().strip() or 0)
        _source_changed(top)
        return {"ok": True, "updated": True, "from": head, "to": up, "commits": n, "files": len(files),
                "changed": files[:2000], "output": "\n".join(output), "info": inf}
    finally:
        lock.release()


def _source_changed(top):
    """After a pull / checkout moved HEAD: status / refs caches and the folder's file list
    and symbol index catch up (the page re-reads open files and the tree itself)."""
    _status_cache.pop(top, None)
    try:
        S.source_changed()
    except Exception:  # never fail the git step over an index refresh
        pass


def fetch(top):
    """git fetch --prune from the current branch's remote (else git's default remote)."""
    lock = _write_locks[os.path.normcase(top)]
    if not lock.acquire(blocking=False):
        raise GitError("busy", "a pull / checkout is already running in this repository")
    try:
        b = status(top, fresh=True)["branch"].get("head", "")
        remote = _cfg(top, "branch." + b + ".remote") if b else ""
        args = ["fetch", "--prune"] + ([remote] if remote and remote != "." and _REMOTE.fullmatch(remote) else [])
        rc, text = _wrun(args, top)
        output = "$ git " + " ".join(args) + ("\n" + text if text else "")
        if rc:
            return {"ok": False, "error": _pull_error(text), "output": output}
        st = status(top, fresh=True)["branch"]
        return {"ok": True, "remote": args[2] if len(args) > 2 else "", "output": output or "$ git fetch --prune",
                "ahead": st.get("ahead", 0), "behind": st.get("behind", 0), "upstream": st.get("upstream", "")}
    finally:
        lock.release()


def _remotes(top):
    out = run(["config", "--get-regexp", r"^remote\..*\.url$"], top, timeout=5, ok=(0, 1)).decode("utf-8", "replace")
    names = [ln.split(" ", 1)[0][7:-4] for ln in out.splitlines() if ln.startswith("remote.")]
    return sorted((n for n in names if n), key=len, reverse=True)  # longest first: "a/b" before "a"


def _checkout_error(text):
    t = text.lower()
    if "would be overwritten" in t or "untracked working tree files" in t or "you need to resolve" in t:
        return "local_changes"
    return "git_failed"


def checkout(top, ref, unsaved=(), allow_unsaved=False):
    """Switch to a local branch (refs/heads/x), or to a remote one (refs/remotes/o/x) through a
    local tracking branch x (made with git switch --create x --track o/x when missing). Never
    forced: git refuses when local changes are in the way and nothing changes."""
    lock = _write_locks[os.path.normcase(top)]
    if not lock.acquire(blocking=False):
        raise GitError("busy", "a pull / checkout is already running in this repository")
    try:
        if not isinstance(ref, str) or not ref.startswith(("refs/heads/", "refs/remotes/")):
            raise GitError("bad_arg", "ref")
        state = repo_state(top)
        if state:
            return {"ok": False, "error": "repo_busy", "state": state}
        rf = refs(top)
        cur = rf["head"]
        local = {x["name"]: x for x in rf["local"]}
        created, tracking = False, ""
        if ref.startswith("refs/heads/"):
            item = local.get(ref[11:])
            if not item or item["ref"] != ref:
                raise GitError("bad_arg", "unknown branch " + ref[11:])
            name = item["name"]
        else:
            item = next((x for x in rf["remote"] if x["ref"] == ref), None)
            if not item:
                raise GitError("bad_arg", "unknown remote branch " + ref[13:])
            tracking = item["name"]
            remote = next((r for r in _remotes(top) if tracking.startswith(r + "/")), "")
            name = tracking[len(remote) + 1:] if remote else ""
            if not name or name.startswith("-"):
                raise GitError("bad_arg", "no remote for " + tracking)
            have = local.get(name)
            if have and have["upstream"] != tracking:
                return {"ok": False, "error": "local_exists", "branch": name, "upstream": have["upstream"],
                        "remote_branch": tracking}
            if have:
                item = have  # already tracked by a local branch: switch to that one
            else:
                created = True
        if name == cur:
            return {"ok": True, "updated": False, "branch": name, "output": f"Already on '{name}'."}
        files = []
        if rf["head_sha"]:
            files = [f for f in run(["diff-tree", "-r", "--name-only", "--no-renames", "-z", rf["head_sha"], item["sha"]],
                                    top, timeout=30).decode("utf-8", "replace").split("\0") if f]
        unsaved = {str(u).replace("\\", "/") for u in (unsaved or []) if isinstance(u, str)}
        hit = sorted(f for f in files if f in unsaved)
        if hit and not allow_unsaved:
            return {"ok": False, "need_confirm": "unsaved", "files": hit, "branch": name}
        args = ["switch", "--no-guess"] + (["--create", name, "--track", tracking] if created else [name])
        rc, text = _wrun(args, top)
        output = "$ git " + " ".join(_q(a) for a in args) + ("\n" + text if text else "")
        if rc:
            return _eol_note(top, text, {"ok": False, "error": _checkout_error(text), "git": text[:4000], "output": output, "branch": name})
        _refs_cache.pop(top, None)
        _source_changed(top)
        return {"ok": True, "updated": True, "branch": name, "from": cur, "created": created, "tracking": tracking,
                "files": len(files), "changed": files[:2000], "output": output}
    finally:
        lock.release()


def _write_top(data):
    exe, _, reason = git_exe()
    if reason:
        raise GitError(reason)
    return repo_of(str(data.get("repo") or ""))


def _unsaved_arg(data):
    unsaved = data.get("unsaved") or []
    if not isinstance(unsaved, list) or len(unsaved) > 10000:
        raise GitError("bad_arg", "unsaved")
    return unsaved


def _api_error(e):
    return (400 if e.code in ("bad_arg", "not_repo") else 200), {"ok": False, "error": e.code, "detail": e.detail}


def api_fetch(data):
    try:
        return fetch(_write_top(data))
    except GitError as e:
        return _api_error(e)


def api_checkout(data):
    try:
        top = _write_top(data)
        return checkout(top, data.get("ref"), _unsaved_arg(data), bool(data.get("allow_unsaved")))
    except GitError as e:
        return _api_error(e)


def api_pull(data):
    try:
        exe, _, reason = git_exe()
        if reason:
            return {"ok": False, "error": reason}
        top = repo_of(str(data.get("repo") or ""))
        unsaved = data.get("unsaved") or []
        if not isinstance(unsaved, list) or len(unsaved) > 10000:
            raise GitError("bad_arg", "unsaved")
        return pull(top, unsaved, bool(data.get("allow_unsaved")))
    except GitError as e:
        return (400 if e.code in ("bad_arg", "not_repo") else 200), {"ok": False, "error": e.code, "detail": e.detail}


# ----- AgentO deep-link requests (toolbar Commit / Push) -----
# ReadO does not commit or push. The buttons hand the request to AgentO through
# agento://dispatch?… (docs/GIT-DESIGN.md, "AgentO deep-link request spec (v1)"): structured
# values only, no commands. Without a registered agento: handler the page copies an instruction.

AGENTO_KINDS = ("commit", "push")
DEEPLINK_MAX = 2000      # Windows ShellExecute / browsers stay well below their limits
DEEPLINK_MSG_MAX = 200
REQUEST_TTL = 24 * 3600  # request files older than this are removed
REQUEST_FILES_MAX = 2000


def requests_dir():
    return os.path.join(os.path.dirname(S.CONFIG_PATH) or ".", "requests")


def agento_handler():
    """The registered agento: protocol's open command, or None (HKCR\\agento with "URL Protocol")."""
    try:
        import winreg
    except ImportError:
        return None
    try:
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, "agento") as k:
            winreg.QueryValueEx(k, "URL Protocol")
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, r"agento\shell\open\command") as k:
            cmd = winreg.QueryValueEx(k, "")[0]
        return cmd or None
    except OSError:
        return None


def _startfile(url):  # replaced in tests
    os.startfile(url)


def _clean_msg(msg):
    msg = re.sub(r"[\x00-\x1f\x7f]+", " ", str(msg or "")).strip()
    return re.sub(r"\s{2,}", " ", msg)[:DEEPLINK_MSG_MAX]


def _prune_requests(d):
    try:
        names = os.listdir(d)
    except OSError:
        return
    now = time.time()
    for n in names:
        p = os.path.join(d, n)
        try:
            if n.endswith(".json") and now - os.path.getmtime(p) > REQUEST_TTL:
                os.remove(p)
        except OSError:
            pass


def _write_request(payload):
    import json
    d = requests_dir()
    os.makedirs(d, exist_ok=True)
    _prune_requests(d)
    rid = time.strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(4)
    payload = dict(payload, id=rid)
    tmp = os.path.join(d, rid + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
    os.replace(tmp, os.path.join(d, rid + ".json"))
    return rid


def deeplink(params):
    """agento://dispatch?… from ordered (name, value) pairs; every value percent-encoded."""
    import urllib.parse
    return "agento://dispatch?" + "&".join(k + "=" + urllib.parse.quote(str(v), safe="") for k, v in params)


def agento_request(top, kind, msg="", files=None):
    """Build the request: (url, ref id or None, payload)."""
    if kind not in AGENTO_KINDS:
        raise GitError("bad_arg", "kind")
    st = status(top, fresh=True)
    b = st["branch"]
    changed = [f for f in st["files"] if f["kind"] != "conflicted"]
    if files:  # the page's ticked files: only those that really changed
        want = {_check_rel(f) for f in files[:REQUEST_FILES_MAX]}
        picked = [f for f in changed if f["path"] in want]
        changed = picked or changed
    msg = _clean_msg(msg)
    branch = b.get("head", "")
    if not branch:
        raise GitError("detached")
    if kind == "commit" and not changed:
        raise GitError("nothing_to_commit")
    if kind == "push" and b.get("upstream") and not b.get("ahead"):
        raise GitError("nothing_to_push")
    root = top.replace("/", "\\") if os.name == "nt" else top
    payload = {"v": 1, "source": "reado", "kind": kind, "repo": root, "branch": branch,
               "upstream": b.get("upstream", ""), "ahead": b.get("ahead", 0), "behind": b.get("behind", 0),
               "dirty": len(st["files"]), "msg": msg, "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
               "files": [{"path": f["path"], "kind": f["kind"]} for f in changed[:REQUEST_FILES_MAX]] if kind == "commit" else []}
    params = [("v", 1), ("source", "reado"), ("kind", kind), ("repo", root), ("branch", branch),
              ("ahead", payload["ahead"]), ("dirty", payload["dirty"])]
    ref = None
    if kind == "commit":  # the file list travels in a request file, not the URL
        ref = _write_request(payload)
    url = deeplink(params + ([("msg", msg)] if msg else []) + ([("ref", ref)] if ref else []))
    if len(url) > DEEPLINK_MAX and msg:  # the message moves into the request file
        ref = ref or _write_request(payload)
        url = deeplink(params + [("ref", ref)])
    if len(url) > DEEPLINK_MAX:
        raise GitError("too_long", "repository path too long for a deep link")
    return url, ref, payload


def api_agento_request(data):
    try:
        exe, _, reason = git_exe()
        if reason:
            return {"sent": False, "error": reason}
        top = repo_of(str(data.get("repo") or ""))
        files = data.get("files") or []
        if not isinstance(files, list):
            raise GitError("bad_arg", "files")
        url, ref, payload = agento_request(top, str(data.get("kind") or ""), data.get("msg") or "", files)
    except GitError as e:
        return (400 if e.code in ("bad_arg", "not_repo") else 200), {"sent": False, "error": e.code, "detail": e.detail}
    out = {"url": url, "ref": ref, "branch": payload["branch"], "ahead": payload["ahead"],
           "dirty": payload["dirty"], "files": [f["path"] for f in payload["files"]]}
    if not agento_handler():
        return dict(out, sent=False, fallback="no_handler")
    try:
        _startfile(url)
    except OSError as e:
        return dict(out, sent=False, fallback="launch_failed", detail=str(e)[:200])
    return dict(out, sent=True)


# ----- routing -----

def handle_get(name, q):
    """(status, body) for GET /api/git/<name>. q: parse_qs dict (lists)."""
    try:
        if name == "info":
            return 200, info(_first(q, "path"), _first(q, "repo"))
        if name == "console":
            since = int(_first(q, "since") or 0)
            with _run_lock:
                return 200, {"entries": [e for e in CONSOLE if e["id"] > since]}
        exe, _, reason = git_exe()
        if reason:
            return 200, {"error": reason}
        if name == "repos":
            return 200, repos()
        if name == "decor":
            return 200, decor(_multi(q, "dir") or [""], _first(q, "eol") == "1")
        if name == "blame":
            return 200, blame(_first(q, "path"), _first(q, "w") == "1")
        top = repo_of(_first(q, "repo"))
        if name == "status":
            return 200, status(top, _first(q, "fresh") == "1")
        if name == "fp":
            return 200, {"fp": fingerprint(top), "state": repo_state(top)}
        if name == "refs":
            d = refs(top)
            return 200, {k: v for k, v in d.items() if k != "all"}
        if name == "authors":
            return 200, authors(top)
        if name == "log":
            return 200, log(top, q)
        if name == "commit":
            return 200, commit(top, _first(q, "rev"))
        if name == "show":
            rev = _check_rev(_first(q, "rev"), top, allow_special=True)
            return 200, show(top, rev, _first(q, "path"))
        if name == "stash":
            return 200, stash(top)
        if name == "pullinfo":
            return 200, pull_info(top)
        return 404, {"error": "not found"}
    except GitError as e:
        code = 400 if e.code in ("bad_arg", "not_repo") else 200
        return code, {"error": e.code, "detail": e.detail}


# ----- diff windows (separate OS windows, one per file + revision) -----
# The page sends a list of files to compare (all resolved: revision + path per side); a
# window shows one at a time and walks the list with ↑ / ↓. The OS windows themselves are
# made by reado.py (pywebview), plugged in as DIFFWIN.backend; without one (browser mode,
# tests) the page falls back to its in-page diff panels.

class DiffWindows:
    MAX = 8

    def __init__(self):
        self.lock = threading.RLock()
        self.wins = {}  # id -> {"ident", "desc", "title", "handle", "t"}
        self.backend = None  # create(id, path, title) -> handle, focus(h), close(h), set_title(h, t), open_in_main(key, line)

    def _by_ident(self, ident):
        return next((i for i, w in self.wins.items() if w["ident"] == ident), None)

    def open(self, ident, title, desc):
        be = self.backend
        if be is None:
            return {"native": False}
        with self.lock:
            wid = self._by_ident(ident)
            if wid is not None:
                w = self.wins[wid]
                w["t"] = time.time()
                be.focus(w["handle"])
                return {"native": True, "id": wid, "reused": True}
            while len(self.wins) >= self.MAX:  # the oldest goes
                old = min(self.wins, key=lambda i: self.wins[i]["opened"])
                self.close(old)
            wid = secrets.token_urlsafe(9)
            self.wins[wid] = {"ident": ident, "desc": desc, "title": title, "handle": None,
                              "t": time.time(), "opened": time.time()}
        try:
            h = be.create(wid, "/diffwin?id=" + wid, title)
        except Exception as e:  # no window: let the page show it in-page
            with self.lock:
                self.wins.pop(wid, None)
            return {"native": False, "error": str(e)[:200]}
        with self.lock:
            if wid in self.wins:
                self.wins[wid]["handle"] = h
        return {"native": True, "id": wid}

    def close(self, wid):
        with self.lock:
            w = self.wins.pop(wid, None)
        if w and self.backend and w["handle"] is not None:
            try:
                self.backend.close(w["handle"])
            except Exception:
                pass

    def closed(self, wid):  # the user closed it (backend callback)
        with self.lock:
            self.wins.pop(wid, None)

    def close_all(self):  # the main window is gone
        for wid in list(self.wins):
            self.close(wid)

    def desc(self, wid):
        with self.lock:
            w = self.wins.get(wid)
            return w and w["desc"]

    def navigate(self, wid, ident, title):  # ↑ / ↓ inside a window: it now stands for that file
        with self.lock:
            w = self.wins.get(wid)
            if not w:
                return False
            w["ident"], w["title"] = ident, title
            h = w["handle"]
        if self.backend and h is not None:
            try:
                self.backend.set_title(h, title)
            except Exception:
                pass
        return True


DIFFWIN = DiffWindows()
DIFF_ITEMS_MAX = 3000


def _check_item(it):
    if not isinstance(it, dict):
        raise GitError("bad_arg", "item")
    out = {}
    for side in ("left", "right"):
        rev, path = it.get(side + "Rev"), it.get(side + "Path")
        if rev is not None:
            if not isinstance(rev, str) or not (rev in ("WORKTREE", "HEAD", "INDEX") or _HEX.fullmatch(rev)):
                raise GitError("bad_arg", side + " revision")
            _check_rel(path)
        out[side + "Rev"], out[side + "Path"] = rev, path if rev is not None else None
    for k in ("path", "hash", "sub", "key", "ident", "title"):
        v = it.get(k)
        out[k] = str(v)[:2000] if v is not None else None
    return out


def api_diffwin(data):
    try:
        top = repo_of(data.get("repo"))
    except GitError as e:
        return 400, {"error": e.code}
    items = data.get("items")
    if not isinstance(items, list) or not items or len(items) > DIFF_ITEMS_MAX:
        return 400, {"error": "bad_arg", "detail": "items"}
    try:
        items = [_check_item(i) for i in items]
        idx = max(0, min(int(data.get("index") or 0), len(items) - 1))
    except (GitError, ValueError) as e:
        return 400, {"error": "bad_arg", "detail": getattr(e, "detail", str(e))}
    cur = items[idx]
    desc = {"repo": {"root": top}, "items": items, "index": idx}
    return DIFFWIN.open(cur["ident"] or "", cur["title"] or "diff", desc)


def api_diffwin_nav(data):
    ok = DIFFWIN.navigate(str(data.get("id") or ""), str(data.get("ident") or "")[:2000], str(data.get("title") or "")[:300])
    return {"ok": ok}


def api_diffwin_close(data):  # Esc in a diff window
    wid = str(data.get("id") or "")
    if wid not in DIFFWIN.wins:
        return {"ok": False}
    DIFFWIN.close(wid)
    return {"ok": True}


def api_diffwin_edit(data):
    """Open in Editor from a diff window: the main window opens the file and comes to the front."""
    if str(data.get("id") or "") not in DIFFWIN.wins:
        return 403, {"error": "forbidden"}
    key = data.get("key")
    if not isinstance(key, str) or not key:
        return 400, {"error": "bad_arg"}
    line = data.get("line")
    line = int(line) if isinstance(line, int) and line > 0 else None
    be = DIFFWIN.backend
    if not be:
        return {"ok": False}
    be.open_in_main(key, line)
    return {"ok": True}


def api_commits(data):
    """Log multi-selection: POST, as hundreds of hashes do not fit in a URL (read-only like GET /commit)."""
    try:
        revs = data.get("revs")
        if not isinstance(revs, list):
            raise GitError("bad_arg", "revs")
        exe, _, reason = git_exe()
        if reason:
            return {"error": reason}
        return commits(repo_of(str(data.get("repo") or "")), revs)
    except GitError as e:
        return (400 if e.code in ("bad_arg", "not_repo") else 200), {"error": e.code, "detail": e.detail}


def register(server_module):
    global S
    S = server_module
    S.write_api("/api/git/commits", max_body=1_000_000)(api_commits)
    S.write_api("/api/git/agento")(api_agento)
    S.write_api("/api/git/pull")(api_pull)
    S.write_api("/api/git/fetch")(api_fetch)
    S.write_api("/api/git/checkout")(api_checkout)
    S.write_api("/api/git/agento-request", max_body=1_000_000)(api_agento_request)
    S.write_api("/api/git/terminal")(api_terminal)
    S.write_api("/api/git/diffwin", max_body=4_000_000)(api_diffwin)
    S.write_api("/api/git/diffwin-nav")(api_diffwin_nav)
    S.write_api("/api/git/diffwin-edit")(api_diffwin_edit)
    S.write_api("/api/git/diffwin-close")(api_diffwin_close)
