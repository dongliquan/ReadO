"""Replace in files (preview, then apply) and tree file operations: rename, delete, new folder.

Split out of server.py. Names of the server module are read as S.NAME at
call time, so reassignments there (settings, tests) apply here too."""
import os
import re
import shutil as _shutil
import subprocess
import threading

import server as S

# ----- replace in files -----
# Two steps, both guarded write APIs: /api/replace-preview computes per-file
# counts and sample lines (nothing is written), /api/replace-apply rewrites
# only the files the user ticked, each through resolve_write_path +
# atomic_write with the mtime seen at preview time (changed since -> skipped).
REPLACE_MAX_FILES = 1000
REPLACE_SAMPLES = 3


def _make_replacer(replacement, regex):
    """Literal replacement, or for regex mode $1 / ${name} / $& / $$ like the
    JS-style syntax users type in editors."""
    if not regex:
        return lambda m: replacement

    def rep(m):
        def sub(t):
            g = t.group(1)
            if g == "$":
                return "$"
            if g == "&":
                return m.group(0)
            g = g.strip("{}")
            try:
                return m.group(int(g) if g.isdigit() else g) or ""
            except (IndexError, re.error):
                return t.group(0)
        return re.sub(r"\$(\$|&|\d+|\{\w+\})", sub, replacement)
    return rep


def _replace_query(data):
    """(pattern, replacer, scope_root, error) from a replace request."""
    query = data.get("q") or ""
    replacement = data.get("replace")
    if not isinstance(query, str) or not query or len(query) > 512:
        return None, None, None, "query required (max 512 chars)"
    if not isinstance(replacement, str):
        return None, None, None, "replacement required"
    regex = bool(data.get("regex"))
    pat, err = S._compile_query(query, bool(data.get("case")), regex, bool(data.get("word")))
    if err:
        return None, None, None, err
    base = S.base_root()
    scope = data.get("scope") or ""
    scope_root = S._safe_join(base, scope) if scope else base
    if not scope_root or not os.path.isdir(scope_root):
        return None, None, None, "invalid scope"
    if not isinstance(data.get("exclude") or "", str) or not isinstance(data.get("glob") or "", str):
        return None, None, None, "file mask and exclude must be text"
    err = S.split_mask(data.get("glob"), data.get("exclude"))[2]
    if err:
        return None, None, None, err
    return pat, _make_replacer(replacement, regex), scope_root, None


def _replace_candidates(data, pat, scope_root):
    """Relative paths of files that may contain a match (rg -l, or a scan)."""
    base = S.base_root()
    glob, excludes = S.split_mask(data.get("glob"), data.get("exclude"))[:2]
    glob, excludes = glob or "", excludes or []
    defaults = data.get("default_excludes") is not False
    rg = S._rg_path()
    if rg:
        args = [rg] + [a for a in S._rg_common_args(glob, excludes, defaults) if a != "--json"] + ["--files-with-matches"]
        if not data.get("case"):
            args.append("-i")
        if data.get("word"):
            args.append("-w")
        if not data.get("regex"):
            args.append("-F")
        args += ["-e", data["q"], S._rg_scope_arg(base, scope_root)]
        try:
            proc = subprocess.run(args, capture_output=True, timeout=S.RG_TIMEOUT, cwd=base,
                                  stdin=subprocess.DEVNULL, creationflags=S.CREATE_NO_WINDOW)
            if proc.returncode in (0, 1):
                out = []
                for line in proc.stdout.decode("utf-8", errors="replace").splitlines():
                    try:
                        out.append(S._rg_rel(line.strip(), base))
                    except ValueError:
                        continue
                return sorted(out, key=str.lower)
        except (OSError, subprocess.TimeoutExpired):
            pass
    glob_re = None
    if glob:
        pats = ["^" + re.escape(g.strip()).replace(r"\*", "[^/\\\\]*") + "$"
                for g in glob.split(",") if g.strip()]
        glob_re = re.compile("|".join(pats), re.IGNORECASE) if pats else None
    out = []
    for rel, full in S._search_candidates(base, scope_root, excludes, defaults):
        if glob_re and not glob_re.match(rel.rsplit("/", 1)[-1]):
            continue
        text = S._get_content(full)
        if text is not None and pat.search(text):
            out.append(rel)
    return out


def _replace_plan(rel, pat, replacer, with_samples):
    """Read one file and compute its replacement. Returns a dict with path,
    count, mtime_ns and either new bytes (_raw) or readonly (why it is skipped)."""
    item = {"path": rel, "count": 0}
    full, err = S.resolve_write_path(rel, must_exist=True)
    if err:
        item["readonly"] = err
        return item
    try:
        st = os.stat(full)
        item["mtime_ns"] = str(st.st_mtime_ns)
        if st.st_size > S.SETTINGS.get("max_file_bytes", 2_000_000):
            item["readonly"] = "file is too large to edit"
            return item
        with open(full, "rb") as f:
            raw = f.read()
    except OSError as e:
        item["readonly"] = str(e)
        return item
    text, enc, bom = S._decode(raw)
    if not enc.startswith("utf-16") and b"\x00" in raw[:8192]:
        item["readonly"] = "binary file"
        return item
    new, n = pat.subn(replacer, text)
    item["count"] = n
    item["encoding"] = enc
    if not n:
        return item
    try:
        out = new.encode(enc)
    except UnicodeEncodeError as e:
        item["readonly"] = f"result has characters {enc} cannot store: {new[e.start:e.end]!r}"
        return item
    item["_full"] = full
    item["_raw"] = (next((m for m, e in S._BOMS if e == enc), b"") if bom else b"") + out
    if with_samples:
        samples = []
        for m in pat.finditer(text):
            s = text.rfind("\n", 0, m.start()) + 1
            e = text.find("\n", m.start())
            line = text[s:e if e >= 0 else len(text)].rstrip("\r")
            if samples and samples[-1]["line"] == text.count("\n", 0, s) + 1:
                continue
            samples.append({"line": text.count("\n", 0, s) + 1,
                            "before": S._clip(line, m.start() - s, m.end() - s)[0],
                            "after": S._clip(pat.sub(replacer, line))[0]})
            if len(samples) >= REPLACE_SAMPLES:
                break
        item["samples"] = samples
    return item


@S.write_api("/api/replace-preview")
def api_replace_preview(data):
    pat, replacer, scope_root, err = _replace_query(data)
    if err:
        return 400, {"error": err}
    cands = _replace_candidates(data, pat, scope_root)
    truncated = len(cands) > REPLACE_MAX_FILES
    files = []
    for rel in cands[:REPLACE_MAX_FILES]:
        item = _replace_plan(rel, pat, replacer, True)
        item.pop("_full", None)
        item.pop("_raw", None)
        if item["count"] or item.get("readonly"):
            files.append(item)
    return {"files": files, "truncated": truncated,
            "total": sum(f["count"] for f in files if not f.get("readonly"))}


@S.write_api("/api/replace-apply")
def api_replace_apply(data):
    pat, replacer, scope_root, err = _replace_query(data)
    if err:
        return 400, {"error": err}
    results = []
    for f in (data.get("files") or [])[:REPLACE_MAX_FILES]:
        rel = f.get("path") if isinstance(f, dict) else None
        if not isinstance(rel, str):
            continue
        res = {"path": rel}
        full = S._safe_join(S.base_root(), rel)
        if not full or not S._within(full, scope_root):
            res["error"] = "outside the search scope"
            results.append(res)
            continue
        item = _replace_plan(rel, pat, replacer, False)
        if item.get("readonly"):
            res["error"] = item["readonly"]
        elif not item["count"]:
            res["error"] = "no matches any more"
        elif str(f.get("mtime_ns")) != item.get("mtime_ns"):
            res["error"] = "file changed on disk since the preview"
        else:
            mtime, err = S.atomic_write(item["_full"], item["_raw"], expect_mtime_ns=int(f["mtime_ns"]))
            if err:
                res["error"] = err
            else:
                res.update(count=item["count"], mtime_ns=str(mtime))
        results.append(res)
    done = [r for r in results if "error" not in r]
    return {"results": results, "files": len(done), "count": sum(r["count"] for r in done)}


@S.write_api("/api/outline", max_body=S.MAX_SAVE_BODY)
def api_outline(data):
    """Symbols of the editor buffer for the outline panel / Ctrl+Shift+O.
    {"symbols": null} tells the page to use its regex fallback."""
    text = data.get("text")
    if not isinstance(text, str):
        return 400, {"error": "text required"}
    return {"symbols": S.outline_text(str(data.get("name") or ""), text)}


@S.write_api("/api/link", max_body=S.MAX_SAVE_BODY)
def api_link(data):
    """What the spot (line, col) of an editor buffer links to (see link_at)."""
    try:
        line, col = int(data.get("line")), int(data.get("col"))
    except (TypeError, ValueError):
        return 400, {"error": "line and col required"}
    return S.link_at(str(data.get("from") or ""), data.get("text"), line, col)


# ----- rename / delete / new folder (tree) -----
# Same guard as saving: inside base_dir after resolving links, never base_dir
# itself, no ignored component (.git, node_modules …), valid Windows names.
def resolve_fs_target(rel_path, must_exist=True):
    """(abs_path, None) for a file or folder the tree may rename / delete /
    create, else (None, error)."""
    if not isinstance(rel_path, str) or not rel_path.strip():
        return None, "path required"
    parts = rel_path.replace("\\", "/").strip("/").split("/")
    for p in parts:
        err = _bad_name(p)
        if err:
            return None, err
    base_real = S.base_root()
    if base_real is None:
        return None, "no folder open"
    full = os.path.join(base_real, *parts)
    real = os.path.realpath(full)
    if not S._within(real, base_real) or S._norm(real) == S._norm(base_real):
        return None, "path outside base_dir"
    if must_exist and not os.path.lexists(full):
        return None, "not found"
    return full, None


def _bad_name(p):
    if p in ("", ".", ".."):
        return "invalid path"
    if any(c in S._BAD_NAME_CHARS for c in p) or p != p.rstrip(" ."):
        return f"invalid name: {p}"
    if p.split(".")[0].lower() in S._WIN_RESERVED:
        return f"reserved name: {p}"
    if S._is_ignored(p):
        return f"path is ignored by settings: {p}"
    return None


def _tree_changed(full):
    """A file or a whole folder appeared / moved / vanished."""
    S._CONTENT_CACHE.discard(full)
    S._index_reset()
    with S._tags_lock:
        S._tags["checked"] = 0.0
    S.ensure_tags()




@S.write_api("/api/rename")
def api_rename(data):
    """Rename a file or folder in place: {path, name} -> {path: new path}."""
    full, err = resolve_fs_target(data.get("path"))
    if err:
        return 400, {"error": err}
    name = str(data.get("name") or "").strip()
    err = _bad_name(name) if "/" not in name and "\\" not in name else "a name, not a path"
    if err:
        return 400, {"error": err}
    dest = os.path.join(os.path.dirname(full), name)
    same = S._norm(dest) == S._norm(full)  # case-only rename on Windows
    if os.path.lexists(dest) and not same:
        return 409, {"error": f"{name} already exists", "code": "exists"}
    try:
        os.rename(full, dest)
    except OSError as e:
        return 500, {"error": str(e)}
    _tree_changed(full)
    _tree_changed(dest)
    return {"path": S._rel_key(dest, S.base_root()), "is_dir": os.path.isdir(dest)}


@S.write_api("/api/delete")
def api_delete(data):
    """Delete a file or folder: Recycle Bin first; {permanent: true} deletes
    for good (asked by the page when the Recycle Bin is not available)."""
    full, err = resolve_fs_target(data.get("path"))
    if err:
        return 400, {"error": err}
    if not data.get("permanent"):
        if S._recycle(full):
            _tree_changed(full)
            return {"recycled": True}
        return 409, {"error": "could not move it to the Recycle Bin", "code": "no_recycle"}
    try:
        if os.path.isdir(full) and not os.path.islink(full):
            _shutil.rmtree(full)
        else:
            os.remove(full)
    except OSError as e:
        return 500, {"error": str(e)}
    _tree_changed(full)
    return {"recycled": False}


@S.write_api("/api/mkdir")
def api_mkdir(data):
    full, err = resolve_fs_target(data.get("path"), must_exist=False)
    if err:
        return 400, {"error": err}
    if os.path.lexists(full):
        return 409, {"error": "already exists", "code": "exists"}
    if not os.path.isdir(os.path.dirname(full)):
        return 400, {"error": "parent folder does not exist"}
    try:
        os.mkdir(full)
    except OSError as e:
        return 500, {"error": str(e)}
    _tree_changed(full)
    return {"path": S._rel_key(full, S.base_root())}


# ----- recent lists: which entries are gone -----
# One batch for Find File's recent files and the recent folders. Bounded: at
# most EXISTS_MAX entries and EXISTS_BUDGET seconds in all (network drives), the
# rest is left out of the answer. An entry is reported gone (False) only when
# what it hangs on is there (the open folder, the drive or share) and the entry
# is not; anything it cannot tell is left out, and the page keeps it.
EXISTS_MAX = 200
EXISTS_BUDGET = 1.5


def _anchor_ok(full):
    drive = os.path.splitdrive(full)[0]
    return bool(drive) and os.path.isdir(drive + os.sep)


def _file_state(key):
    full = S.resolve_read_path(key)  # relative: inside the open folder; absolute: opened by the user
    if not full:
        return None
    if os.path.isfile(full):
        return True
    anchor = S.base_root() if not S._is_abs_key(key) else None
    return False if (os.path.isdir(anchor) if anchor else _anchor_ok(full)) else None


def _dir_state(path):
    if os.path.isdir(path):
        return True
    return False if _anchor_ok(os.path.abspath(path)) else None


@S.write_api("/api/exists")
def api_exists(data):
    files = [k for k in data.get("files") or [] if isinstance(k, str) and k][:EXISTS_MAX]
    # folders: only those in the saved recent-folders list (no probing of other paths)
    known = set(S.ui_state().get("recentFolders") or [])
    dirs = [d for d in data.get("dirs") or [] if isinstance(d, str) and d in known][:EXISTS_MAX]
    out = {"files": {}, "dirs": {}}

    def work():
        for k in files:
            s = _file_state(k)
            if s is not None:
                out["files"][k] = s
        for d in dirs:
            s = _dir_state(d)
            if s is not None:
                out["dirs"][d] = s
    t = threading.Thread(target=work, daemon=True)
    t.start()
    t.join(EXISTS_BUDGET)
    return {"files": dict(out["files"]), "dirs": dict(out["dirs"]), "complete": not t.is_alive()}
