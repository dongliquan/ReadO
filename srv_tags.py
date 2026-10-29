"""Symbol index (Universal Ctags): workspace symbols, declarations and the outline.

vendor/ctags/ctags.exe (bundled like rg) or a Universal Ctags on PATH.

Split out of server.py. Names of the server module are read as S.NAME at
call time, so reassignments there (settings, tests) apply here too."""
import json
import os
import re
import shutil as _shutil
import subprocess
import sys
import tempfile
import threading
import time

import server as S

# ----- symbol index (Universal Ctags) -----
# vendor/ctags/ctags.exe (bundled like rg) or a Universal Ctags on PATH. The
# whole working folder is indexed in a background thread from the same file
# list Quick Open uses (so ignore rules match); afterwards only changed files
# are re-tagged: files ReadO saves immediately (notify_file_changed), files
# changed by other programs when the index is older than INDEX_TTL. Without
# ctags, or while the first index is being built, go to definition falls back
# to word search + declaration patterns above.
CTAGS_ARGS = ["--output-format=json", "--fields=+neS-P", "--sort=no", "-f", "-"]
# data formats whose "symbols" are keys/headings: noise in a code index
CTAGS_INDEX_OFF = ["--languages=-JSON,-Markdown,-Asciidoc,-ReStructuredText,-Iniconf,-XML,-SVG"]
CTAGS_MAX_FILE = 2_000_000          # bytes; larger files are skipped
CTAGS_INCREMENTAL_MAX = 3000        # more changed files than this -> full rebuild
# ctags runs one file at a time: a list this long is split over parallel runs
# (23.5k files: 154 s -> 38 s with 4), leaving most cores free
CTAGS_SPLIT_MIN = 2000
CTAGS_JOBS = min(4, max(1, (os.cpu_count() or 1) // 4))
# how often files changed by *other* programs are looked for (a stat of every
# file); files saved in ReadO are re-tagged right away
TAGS_TTL = 300
# kinds that are never a "definition" target
_CTAGS_SKIP_KINDS = frozenset("""package packageName import include using local parameter label
heading chapter section subsection subsubsection l4subsection l5subsection anchor key""".split())
_TYPE_KINDS = frozenset("""class interface enum struct union record trait typedef type alias annotation
object module namespace protocol category implementation actor typealias table view""".split())
_FUNC_KINDS = frozenset("""method function func fn constructor macro subroutine procedure prototype
trigger singletonMethod getter setter accessor generator""".split())

_ctags_exe = None
_ctags_checked = False
_tags_lock = threading.Lock()
_tags = {"base": None, "ready": False, "building": False, "by_name": {}, "by_file": {},
         "mtimes": {}, "checked": 0.0, "files": 0, "symbols": 0, "secs": 0.0, "error": None,
         "dirty": set(), "names": None}


def ctags_path():
    global _ctags_exe, _ctags_checked
    if _ctags_checked:
        return _ctags_exe
    _ctags_checked = True
    exe = "ctags.exe" if os.name == "nt" else "ctags"
    for cand in (os.path.join(S.VENDOR_PATH, "ctags", exe), _shutil.which("ctags")):
        if not cand or not os.path.isfile(cand):
            continue
        try:  # Exuberant/BSD ctags have no JSON output
            out = subprocess.run([cand, "--version"], capture_output=True, timeout=10,
                                 stdin=subprocess.DEVNULL, creationflags=S.CREATE_NO_WINDOW).stdout
            if b"Universal Ctags" in out:
                _ctags_exe = cand
                break
        except (OSError, subprocess.TimeoutExpired):
            continue
    return _ctags_exe


def kind_category(kind):
    if kind in _TYPE_KINDS:
        return "type"
    if kind in _FUNC_KINDS:
        return "function"
    return "field"


def _run_ctags(paths, extra=()):
    """Tag the given absolute paths; yields parsed JSON tag objects."""
    exe = ctags_path()
    if not exe or not paths:
        return
    proc = subprocess.Popen([exe] + CTAGS_ARGS + list(extra) + ["-L", "-"],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                            creationflags=S.CREATE_NO_WINDOW)

    def feed():
        try:
            proc.stdin.write("\n".join(paths).encode("utf-8") + b"\n")
        except OSError:
            pass
        finally:
            try:
                proc.stdin.close()
            except OSError:
                pass
    threading.Thread(target=feed, daemon=True).start()
    try:
        for raw in proc.stdout:
            if not raw.startswith(b'{"_type": "tag"'):
                continue
            try:
                yield json.loads(raw)
            except ValueError:
                continue
    finally:
        if proc.poll() is None:
            proc.kill()
        proc.wait()
        proc.stdout.close()


def _tag_tuples(paths, base):
    """{rel: [(name, rel, line, kind, scope, end, signature)]} for paths.
    A long list (the full build) is split over CTAGS_JOBS ctags runs, every
    k-th file each so big bundles spread out; the result keeps the order a
    single run gives (files in list order)."""
    jobs = CTAGS_JOBS if len(paths) >= CTAGS_SPLIT_MIN else 1
    if jobs <= 1:
        return _tag_tuples_one(paths, base)
    ctags_path()  # resolve it here, not in the workers at the same time
    parts = [None] * jobs

    def work(i):
        parts[i] = _tag_tuples_one(paths[i::jobs], base)
    threads = [threading.Thread(target=work, args=(i,), daemon=True) for i in range(jobs)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    if any(p is None for p in parts):
        raise RuntimeError("ctags run failed")
    order = {}
    for i, p in enumerate(paths):
        try:
            order[os.path.relpath(p, base).replace("\\", "/")] = i
        except ValueError:
            pass
    items = [kv for part in parts for kv in part.items()]
    items.sort(key=lambda kv: order.get(kv[0], len(paths)))
    return dict(items)


def _tag_tuples_one(paths, base):
    out, rels = {}, {}
    intern = sys.intern  # names/kinds/scopes repeat a lot: share one string each
    for t in _run_ctags(paths, CTAGS_INDEX_OFF):
        kind = t.get("kind", "")
        if kind in _CTAGS_SKIP_KINDS:
            continue
        path = t.get("path")
        rel = rels.get(path)
        if rel is None:
            try:
                rel = rels[path] = os.path.relpath(path, base).replace("\\", "/")
            except (ValueError, TypeError):
                continue
        out.setdefault(rel, []).append((intern(t.get("name", "")), rel, int(t.get("line", 0)), intern(kind),
                                        intern(t.get("scope", "")), int(t.get("end", 0) or 0),
                                        t.get("signature", "")))
    return out


def _index_candidates(base):
    """{rel: mtime_ns} of files to tag (Quick Open list, size-capped)."""
    out = {}
    for rel in S._ensure_index():
        try:
            st = os.stat(os.path.join(base, rel.replace("/", os.sep)))
        except OSError:
            continue
        if st.st_size <= CTAGS_MAX_FILE:
            out[rel] = st.st_mtime_ns
    return out


def _rebuild_by_name(by_file):
    by_name = {}
    for tags in by_file.values():
        for tg in tags:
            by_name.setdefault(tg[0], []).append(tg)
    return by_name


def _camel_initials(name):
    """'OrderServiceImpl' -> 'osi', 'get_order_id' -> 'goi' (CamelHumps matching)."""
    out = []
    for i, c in enumerate(name):
        if i == 0 or c.isupper() and not name[i - 1].isupper() or (name[i - 1] in "_$" and c.isalnum()):
            out.append(c)
    return "".join(out).lower()


def _joined(items):
    """'\n' + items joined by '\n' + '\n', and starts[k] = index of the newline
    in front of item k. A match at position p belongs to item
    bisect_right(starts, p) - 1; searching '\n' + q finds prefixes."""
    starts, pos = [], 0
    for it in items:
        starts.append(pos)
        pos += len(it) + 1
    return "\n" + "\n".join(items) + "\n", starts


def _name_search_index(by_name):
    """Names as two joined strings (lowercase names, CamelHumps initials) so a
    query is a handful of C-level str.find calls, not a Python loop."""
    names = sorted(by_name)
    lower = [n.lower() for n in names]
    blob, starts = _joined(lower)
    iblob, istarts = _joined([_camel_initials(n) for n in names])
    nblob, _ = _joined(names)  # case kept, for hump queries like "FrA"
    return {"names": names, "lower": lower, "blob": blob, "starts": starts,
            "iblob": iblob, "istarts": istarts, "nblob": nblob}


def _tags_build(base, full):
    """Full build, or an incremental pass over changed/new/removed files."""
    t0 = time.time()
    try:
        cands = _index_candidates(base)
        with _tags_lock:
            same = _tags["base"] == base and _tags["ready"]
            old_m = dict(_tags["mtimes"]) if same else {}
            old_f = dict(_tags["by_file"]) if same else {}
            dirty = set(_tags["dirty"]) if same else set()
            _tags["dirty"].clear()
        if full or not same:
            changed, removed = list(cands), []
        else:
            changed = [r for r, m in cands.items() if old_m.get(r) != m or r in dirty]
            removed = [r for r in old_m if r not in cands]
            if len(changed) > CTAGS_INCREMENTAL_MAX:
                changed, old_f = list(cands), {}
        if changed or removed or not same:
            fresh = _tag_tuples([os.path.join(base, r.replace("/", os.sep)) for r in changed], base)
            by_file = {r: v for r, v in old_f.items() if r not in removed and r not in changed}
            by_file.update(fresh)
            by_name = _rebuild_by_name(by_file)
            names = _name_search_index(by_name)  # ready before the first Ctrl+T
        else:
            by_file = old_f
            by_name = None
        with _tags_lock:
            if _tags["base"] != base:  # folder changed while building
                return
            if by_name is not None:
                _tags.update(by_file=by_file, by_name=by_name, names=names,
                             symbols=sum(len(v) for v in by_file.values()))
            _tags.update(mtimes=cands, ready=True, files=len(cands), error=None,
                         checked=time.time())
            if full or not same:
                _tags["secs"] = round(time.time() - t0, 2)
    except Exception as e:  # never let a parser problem kill the server
        with _tags_lock:
            _tags["error"] = str(e)
    finally:
        with _tags_lock:
            _tags["building"] = False


def ensure_tags(force=False):
    """Start a (re)build in the background when needed. Returns a status dict."""
    base = S.base_root()
    with _tags_lock:
        if base is None or not ctags_path():
            return {"available": bool(ctags_path()), "ready": False, "building": False}
        if _tags["base"] != base:
            _tags.update(base=base, ready=False, by_name={}, by_file={}, mtimes={}, symbols=0,
                         files=0, dirty=set(), checked=0.0)
        stale = force or not _tags["ready"] or _tags["dirty"] or time.time() - _tags["checked"] > TAGS_TTL
        if stale and not _tags["building"]:
            _tags["building"] = True
            full = not _tags["ready"]
            threading.Thread(target=_tags_build, args=(base, full), daemon=True).start()
        return {"available": True, "ready": _tags["ready"], "building": _tags["building"],
                "files": _tags["files"], "symbols": _tags["symbols"], "secs": _tags["secs"],
                "error": _tags["error"]}


def tags_file_changed(full):
    """notify_file_changed hook: re-tag this file soon."""
    base = S.base_root()
    if not base or not S._within(full, base):
        return
    rel = os.path.relpath(full, base).replace("\\", "/")
    with _tags_lock:
        if _tags["base"] == base and _tags["ready"]:
            _tags["dirty"].add(rel)
    ensure_tags()


def _line_of(base, rel, line_no):
    text = S._get_content(os.path.join(base, rel.replace("/", os.sep)))
    if text is None:
        return ""
    lines = text.splitlines()
    return lines[line_no - 1] if 0 < line_no <= len(lines) else ""


def ctags_lookup(symbol, scope_root, base):
    """Declarations of `symbol` from the index, or None when the index is not
    usable yet (the caller then falls back to search)."""
    ensure_tags()
    with _tags_lock:
        if not _tags["ready"] or _tags["base"] != base:
            return None
        hits = list(_tags["by_name"].get(symbol, ()))
    prefix = ""
    if os.path.normcase(scope_root) != os.path.normcase(base):
        prefix = os.path.relpath(scope_root, base).replace("\\", "/") + "/"
    out = []
    for name, rel, ln, kind, scope, end, sig in hits:
        if prefix and not rel.startswith(prefix):
            continue
        line = _line_of(base, rel, ln)
        out.append({"path": rel, "line": ln, "col": S._name_col(line, symbol), "text": S._clip(line.rstrip())[0],
                    "kind": kind_category(kind), "ctkind": kind, "scope": scope})
        if len(out) >= S.GOTO_MAX_DECL:
            break
    return out


def _symbol_score(name, nl, q, ql, camel):
    """Lower is better. Exact > prefix > CamelHumps > substring."""
    if name == q:
        return 0
    if nl == ql:
        return 1
    if name.startswith(q):
        return 2 + len(name) / 1000
    if nl.startswith(ql):
        return 3 + len(name) / 1000
    if camel:
        return 4 + len(name) / 1000
    return 5 + nl.find(ql) / 100 + len(name) / 1000


def _find_all(blob, starts, needle, cap):
    """Item indexes whose text contains needle (see _joined)."""
    import bisect
    out, p = set(), blob.find(needle)
    while p >= 0 and len(out) < cap:
        out.add(bisect.bisect_right(starts, p) - 1)
        p = blob.find(needle, p + 1)
    return out


SYMBOL_CATS = {"class": "type", "method": "function", "field": "field"}


def search_symbols(query, cat="", limit=100):
    """Workspace symbol search (Ctrl+T). cat: '' | 'class' | 'method' | 'field'."""
    st = ensure_tags()
    q = (query or "").strip()
    want = SYMBOL_CATS.get(cat)
    if not st.get("ready"):
        return dict(st, results=[], total=0)
    if not q:
        return dict(st, results=[], total=0)
    with _tags_lock:
        by_name = _tags["by_name"]
        idx = _tags["names"]
        if idx is None:
            idx = _tags["names"] = _name_search_index(by_name)
    ql = q.lower()
    hits = _find_all(idx["blob"], idx["starts"], ql, 50000)
    camel = set()
    if len(q) > 1 and any(c.isupper() for c in q[1:]):
        # IntelliJ-style humps: "FrA" -> Fr*A* (FreshlyAdded), "OSImpl" -> O*S*Impl
        humps = re.findall(r"[A-Z0-9][a-z0-9_$]*|[a-z0-9_$]+", q)
        pat = re.compile(r"(?m)^" + r"[a-z0-9_$]*".join(re.escape(x) for x in humps))
        import bisect
        for m in pat.finditer(idx["nblob"]):
            camel.add(bisect.bisect_right(idx["starts"], m.start() - 1) - 1)
            if len(camel) >= 50000:
                break
        camel -= hits
    elif len(ql) > 1 and ql.isalnum():  # lowercase initials: "osi" -> OrderServiceImpl
        camel = _find_all(idx["iblob"], idx["istarts"], "\n" + ql, 50000) - hits
    scored = [(_symbol_score(idx["names"][k], idx["lower"][k], q, ql, k in camel), idx["names"][k])
              for k in hits | camel if 0 <= k < len(idx["names"])]
    scored.sort()
    with _tags_lock:
        out, total = [], 0
        for s, n in scored:
            for name, rel, ln, kind, scope, end, sig in by_name[n]:
                if want and kind_category(kind) != want:
                    continue
                total += 1
                if len(out) < limit:
                    out.append({"name": name, "path": rel, "line": ln, "kind": kind,
                                "cat": kind_category(kind), "scope": scope, "signature": sig})
            if len(out) >= limit and total > limit * 3:
                break
    return dict(st, results=out, total=total)


_outline_lock = threading.Lock()
_outline_dir = None


def outline_text(name, text):
    """Symbols of an editor buffer (ctags on a temp copy, so unsaved edits
    count). None when ctags is not available."""
    global _outline_dir
    if not ctags_path():
        return None
    base_name = re.sub(r"[^\w.\-]", "_", os.path.basename(name or "file.txt")) or "file.txt"
    with _outline_lock:
        if _outline_dir is None or not os.path.isdir(_outline_dir):
            _outline_dir = tempfile.mkdtemp(prefix="reado-outline-")
            import atexit  # the scratch folder goes away with the process
            atexit.register(_shutil.rmtree, _outline_dir, True)
        path = os.path.join(_outline_dir, base_name)
        try:
            with open(path, "w", encoding="utf-8", newline="") as f:
                f.write(text)
            tags = list(_run_ctags([path]))
        finally:
            try:
                os.remove(path)
            except OSError:
                pass
    lines = text.splitlines()
    out = []
    for t in tags:
        kind = t.get("kind", "")
        if kind in ("local", "parameter", "package", "packageName", "import", "include"):
            continue
        ln = int(t.get("line", 0))
        scope = t.get("scope", "")
        line = lines[ln - 1] if 0 < ln <= len(lines) else ""
        depth = 0 if not scope else len(re.split(r"\.|::|/", scope))
        out.append({"name": t.get("name", ""), "kind": kind, "line": ln, "endLine": int(t.get("end", 0) or 0) or ln,
                    "col": max(1, S._name_col(line, t.get("name", ""))), "scope": scope, "depth": min(depth, 6),
                    "detail": t.get("signature", "")})
    out.sort(key=lambda s: (s["line"], s["depth"]))
    return out
