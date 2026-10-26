"""Find in Files: ripgrep with a parallel Python fallback, content cache and search generations.

Split out of server.py. Names of the server module are read as S.NAME at
call time, so reassignments there (settings, tests) apply here too."""
import base64
import json
import os
import re
import subprocess
import sys
import threading
from collections import OrderedDict

import server as S

# ----- search -----
from concurrent.futures import ThreadPoolExecutor as _TPE
import shutil as _shutil
# 8 workers read files as fast as 32 here, and leave the GIL free often
# enough for tree/file requests to stay responsive during a fallback search.
_SEARCH_EXECUTOR = _TPE(max_workers=8)
_SEARCH_GATE = threading.BoundedSemaphore(2)

# Set False to force the pure-Python search path (benchmarks / troubleshooting).
MAX_LINE_CHARS = 2000      # longer result/context lines are clipped around the match
RG_TIMEOUT = 60            # seconds before a ripgrep run is killed


def _rg_path():
    """Bundled vendor/rg/rg.exe first, then rg on PATH, else None."""
    if not S.USE_RIPGREP:
        return None
    exe = "rg.exe" if os.name == "nt" else "rg"
    bundled = os.path.join(S.VENDOR_PATH, "rg", exe)
    if os.path.isfile(bundled):
        return bundled
    return _shutil.which("rg")


# Only the newest request of each kind keeps running: the UI throws away stale
# responses anyway, so an older search/goto stops early instead of burning CPU.
_gen_lock = threading.Lock()
_latest_gen = {"search": 0, "goto": 0, "refs": 0}


def _new_gen(kind):
    with _gen_lock:
        _latest_gen[kind] += 1
        return _latest_gen[kind]


def _is_stale(kind, gen):
    return _latest_gen[kind] != gen


class _ByteLRU:
    """Decoded file contents keyed by path, bounded by (approximate) bytes.

    Least-recently-used entries are evicted first, so a repo larger than the
    budget keeps its hot part cached instead of churning the whole cache on
    every search (the old count-capped FIFO did that past 5,000 files)."""

    def __init__(self, budget):
        self.budget = budget
        self._d = OrderedDict()   # path -> (mtime_ns, size, text, cost)
        self._bytes = 0
        self._lock = threading.Lock()

    def get(self, key, mtime_ns, size):
        with self._lock:
            e = self._d.get(key)
            if e is None or e[0] != mtime_ns or e[1] != size:
                return False, None
            self._d.move_to_end(key)
            return True, e[2]

    def put(self, key, mtime_ns, size, text):
        cost = (sys.getsizeof(text) if text is not None else 0) + 200
        if cost > self.budget // 8:
            return
        with self._lock:
            old = self._d.pop(key, None)
            if old is not None:
                self._bytes -= old[3]
            self._d[key] = (mtime_ns, size, text, cost)
            self._bytes += cost
            while self._bytes > self.budget and self._d:
                _, ev = self._d.popitem(last=False)
                self._bytes -= ev[3]

    def discard(self, key):
        with self._lock:
            old = self._d.pop(key, None)
            if old is not None:
                self._bytes -= old[3]

    def clear(self):
        with self._lock:
            self._d.clear()
            self._bytes = 0

    def __len__(self):
        return len(self._d)

    def stats(self):
        return {"entries": len(self._d), "bytes": self._bytes, "budget": self.budget}


CONTENT_CACHE_BYTES = 256 * 1024 * 1024
_CONTENT_CACHE = _ByteLRU(CONTENT_CACHE_BYTES)


def _get_content(full):
    try:
        st = os.stat(full)
    except OSError:
        return None
    if st.st_size > 5_000_000:
        return None
    hit, text = _CONTENT_CACHE.get(full, st.st_mtime_ns, st.st_size)
    if hit:
        return text
    try:
        with open(full, "rb") as f:
            raw = f.read()
    except OSError:
        return None
    if S.sniff_binary(raw):
        text = None
    else:
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            try:
                text = raw.decode("cp949")
            except UnicodeDecodeError:
                text = None
    _CONTENT_CACHE.put(full, st.st_mtime_ns, st.st_size, text)
    return text


def _clip(text, col_s=0, col_e=0):
    """Clip a very long line (minified files) to a window around the match.
    Returns (text, col_s, col_e) with the columns shifted into the window."""
    if len(text) <= MAX_LINE_CHARS:
        return text, col_s, col_e
    start = max(0, min(col_s - MAX_LINE_CHARS // 4, len(text) - MAX_LINE_CHARS))
    end = start + MAX_LINE_CHARS
    pre = "…" if start > 0 else ""
    post = "…" if end < len(text) else ""
    shift = start - len(pre)
    return pre + text[start:end] + post, max(0, col_s - shift), max(0, col_e - shift)


def _rg_decode(field):
    """ripgrep JSON gives {"text": ...} for UTF-8 and {"bytes": base64} otherwise."""
    if not field:
        return "", None
    if "text" in field:
        return field["text"], None
    raw = base64.b64decode(field.get("bytes", ""))
    for enc in ("utf-8", "cp949"):
        try:
            return raw.decode(enc), raw
        except UnicodeDecodeError:
            pass
    return raw.decode("utf-8", errors="replace"), raw


def _byte_to_char(line_text, raw, off):
    """rg submatch offsets are bytes; convert to a str index."""
    if raw is None:
        if line_text.isascii():
            return off
        raw = line_text.encode("utf-8")
        return len(raw[:off].decode("utf-8", errors="ignore"))
    return len(raw[:off].decode("utf-8", errors="ignore"))


def _rg_common_args(glob, excludes=(), defaults=None):
    """defaults=None: the settings' ignored + search_ignored (go to definition);
    True / False: Find / Replace in Files with the search box's "default
    excludes" toggle on (search_ignored + SEARCH_DEFAULT_EXCLUDES) or off, plus
    its exclude patterns. Slash patterns are matched from rg's working folder,
    so those callers run rg in the open folder (_rg_scope_arg)."""
    # --no-ignore/--hidden: ReadO's own "ignored" setting decides what is
    # searched (as in the Python fallback), not .gitignore or dot-file rules;
    # with respect_gitignore on, .gitignore / .git/info/exclude count too
    # (also outside a git checkout), but not .ignore files or the global one
    ignore = (["--no-ignore-dot", "--no-ignore-global", "--no-require-git"] if S._gi_on() else ["--no-ignore"])
    args = ["--json", "--no-config"] + ignore + ["--hidden", "--max-filesize", "5M"]
    # optional "files to include" filter from the search box (*.java, src/**)
    for g in (glob or "").split(","):
        g = g.strip()
        if g:
            args += ["--glob", g]
    # every non-binary file is searched (rg also skips binary content itself);
    # known binary types, hidden and search-excluded names are left out.
    # Excludes come last so they win over the include globs.
    args += ["--iglob", "!*{" + ",".join(sorted(S.BINARY_EXTS)) + "}"]
    skip = list(S.SETTINGS.get("ignored") or [])
    if defaults is not False:
        skip += list(S.SETTINGS.get("search_ignored") or [])
    if defaults:
        skip += S.SEARCH_DEFAULT_EXCLUDES
    for ig in skip + list(excludes or ()):
        args += ["--iglob", "!" + ig]
    return args


def _rg_scope_arg(base, scope_root):
    """scope_root as rg's path argument when rg runs in base: relative, so
    slash globs anchor at the open folder, and behind ./ so a folder named
    "-x" is never read as an option."""
    rel = os.path.relpath(scope_root, base)
    return "." if rel == "." else "./" + rel.replace("\\", "/")


def _rg_rel(path, base):
    """An rg output path (relative to its working folder, or absolute) -> rel path."""
    return os.path.relpath(os.path.join(base, path), base).replace("\\", "/")


def _rg_events(args, kind, gen, cwd=None):
    """Run ripgrep and yield its JSON events as they stream in.

    Stops (and kills rg) when the consumer stops iterating, when a newer
    request of the same kind arrives, or after RG_TIMEOUT. Yields a final
    {"type": "_exit", "code": n} so callers can tell errors from no-matches."""
    try:
        proc = subprocess.Popen(
            args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL, creationflags=S.CREATE_NO_WINDOW, cwd=cwd,
        )
    except OSError:
        yield {"type": "_exit", "code": -1}
        return
    timer = threading.Timer(RG_TIMEOUT, proc.kill)
    timer.daemon = True
    timer.start()
    try:
        for raw in proc.stdout:
            if _is_stale(kind, gen):
                yield {"type": "_exit", "code": "stale"}
                return
            try:
                yield json.loads(raw)
            except ValueError:
                continue
        proc.wait()
        yield {"type": "_exit", "code": proc.returncode}
    finally:
        timer.cancel()
        if proc.poll() is None:
            proc.kill()
            proc.wait()
        proc.stdout.close()


def _ripgrep_search(query, case_sensitive, regex, whole_word, scope_root, base, glob,
                    context, max_results, gen, excludes=(), defaults=True):
    rg = _rg_path()
    if not rg:
        return None
    args = [rg] + _rg_common_args(glob, excludes, defaults) + ["--max-count", "100"]
    if not case_sensitive: args.append("-i")
    if whole_word: args.append("-w")
    if not regex: args.append("-F")
    if context > 0: args += ["--context", str(context)]
    args += ["-e", query, _rg_scope_arg(base, scope_root)]

    results = []
    files_seen = set()
    # rg prints a line shared by two nearby matches only once (as the first
    # one's "after" and the next one's "before"), so context is rebuilt from
    # line numbers: `recent` holds the last `context` lines seen in the file,
    # `waiting` the matches still collecting "after" lines.
    recent = []
    waiting = []
    full = False          # max_results reached: only finish pending "after"s
    exit_code = None
    events = _rg_events(args, "search", gen, cwd=base)
    for obj in events:
        t = obj.get("type")
        d = obj.get("data") or {}
        if t in ("context", "match"):
            ln = d.get("line_number", 0)
            line_text, raw = _rg_decode(d.get("lines"))
            line_text = line_text.rstrip("\r\n")
            clipped = _clip(line_text)[0]
            for m in waiting:
                if m["line"] < ln <= m["line"] + context:
                    m["after"].append(clipped)
            waiting = [m for m in waiting if m["line"] + context > ln]
            if full and not waiting:
                exit_code = 0
                break
            if t == "match" and not full:
                path = _rg_decode(d.get("path"))[0]
                try:
                    rel = _rg_rel(path, base)
                except ValueError:
                    rel = path
                submatches = d.get("submatches") or []
                col_s = _byte_to_char(line_text, raw, submatches[0].get("start", 0)) if submatches else 0
                col_e = _byte_to_char(line_text, raw, submatches[0].get("end", 0)) if submatches else 0
                text, col_s, col_e = _clip(line_text.rstrip(), col_s, col_e)
                before = [x for k, x in recent if ln - context <= k < ln]
                entry = {
                    "path": rel, "line": ln, "text": text,
                    "col_start": col_s, "col_end": col_e,
                    "before": before, "after": [],
                    "before_start": max(1, ln - len(before)),
                }
                results.append(entry)
                files_seen.add(rel)
                if context:
                    waiting.append(entry)
                if len(results) >= max_results:
                    full = True
                    if not waiting:
                        exit_code = 0
                        break
            if context:
                recent.append((ln, clipped))
                del recent[:-context]
        elif t in ("begin", "end"):
            recent = []
            waiting = []
            if full:
                exit_code = 0
                break
        elif t == "_exit":
            exit_code = obj["code"]
    events.close()  # kills rg if we stopped early
    if exit_code == "stale":
        return {"results": [], "total": 0, "cancelled": True, "engine": "rg"}
    if exit_code not in (0, 1):  # 1 = no matches; anything else -> python fallback
        return None
    return {
        "results": results,
        "total": len(results),
        "files": len(files_seen),
        "truncated": len(results) >= max_results,
        "engine": "rg",
    }


def _search_one_file(args):
    full, rel, pat, needle, context, max_per_file, gen = args
    if _is_stale("search", gen):
        return None
    text = _get_content(full)
    if text is None:
        return None
    # Fast paths: skip files that have no match anywhere. For a literal query a
    # plain substring test (on lowered text when case-insensitive) is several
    # times faster than an IGNORECASE regex scan.
    if needle is not None:
        if needle[0] not in (text.lower() if needle[1] else text):
            return None
    if not pat.search(text):
        return None
    out = []
    lines = text.splitlines()
    for i, line in enumerate(lines):
        m = pat.search(line)
        if not m:
            continue
        lineno = i + 1
        before = [_clip(x)[0] for x in lines[max(0, i - context): i]]
        after = [_clip(x)[0] for x in lines[i + 1: i + 1 + context]]
        txt, col_s, col_e = _clip(line.rstrip(), m.start(), m.end())
        out.append({
            "path": rel,
            "line": lineno,
            "text": txt,
            "col_start": col_s,
            "col_end": col_e,
            "before": before,
            "after": after,
            "before_start": max(1, lineno - len(before)),
        })
        if len(out) >= max_per_file:
            break
    return out


def _scoped_index(base, scope_root):
    """Index entries under scope_root as (rel, full) pairs."""
    base_abs = os.path.abspath(base)
    scope_abs = os.path.abspath(scope_root)
    prefix = ""
    if os.path.normcase(scope_abs) != os.path.normcase(base_abs):
        prefix = os.path.relpath(scope_abs, base_abs).replace("\\", "/") + "/"
    for rel in S._ensure_index():
        if prefix and not rel.startswith(prefix):
            continue
        yield rel, os.path.join(base, rel.replace("/", os.sep))


def _search_candidates(base, scope_root, excludes, defaults):
    """Files a Find / Replace in Files scan without ripgrep looks at: the index
    (which already skips search_ignored), or with the defaults off a fresh walk
    that keeps them; then the default and typed exclude patterns."""
    if defaults:
        pairs = _scoped_index(base, scope_root)
    else:
        rel_scope = os.path.relpath(scope_root, base).replace("\\", "/")
        prefix = "" if rel_scope == "." else rel_scope + "/"
        pairs = ((prefix + rel, os.path.join(scope_root, rel.replace("/", os.sep)))
                 for rel in S._walk_files(scope_root, search_excluded=False))
    skip = S._exclude_matcher(list(S.SEARCH_DEFAULT_EXCLUDES if defaults else ()) + list(excludes))
    for rel, full in pairs:
        if not (skip and skip(rel)):
            yield rel, full


def _compile_query(query, case_sensitive, regex, whole_word):
    """Python pattern for a Find-in-Files query: (pattern, None) or (None, error)."""
    pat_str = query if regex else re.escape(query)
    if whole_word:
        if not regex and re.match(r"\w", query) and re.search(r"\w$", query):
            # same meaning as the lookarounds when the term starts/ends with a
            # word char, and much faster in Python's re
            pat_str = r"\b" + pat_str + r"\b"
        else:
            pat_str = r"(?<!\w)" + pat_str + r"(?!\w)"
    try:
        return re.compile(pat_str, 0 if case_sensitive else re.IGNORECASE), None
    except re.error as e:
        return None, f"regex: {e}"


SEARCH_MORE_MAX = 20_000  # "show more" in Find in Files raises the cap up to this


def find_in_files(query: str, case_sensitive: bool, regex: bool, whole_word: bool,
                  scope: str = "", glob: str = "", context: int = 2, limit: int = 0,
                  exclude: str = "", default_excludes: bool = True):
    base = S.base_root()
    scope_root = S._safe_join(base, scope) if scope else base
    if not scope_root or not os.path.isdir(scope_root):
        return {"error": "invalid scope", "results": []}
    glob, excludes, err = S.split_mask(glob, exclude)
    if err:
        return {"error": err, "results": []}
    if not query:
        return {"results": [], "total": 0}
    if len(query) > 512:
        return {"error": "query is too long (maximum 512 characters)", "results": []}
    if regex and not _rg_path() and re.search(r"\([^)]*[+*][^)]*\)[+*{]", query):
        return {"error": "nested quantified groups require ripgrep for safe execution", "results": []}

    pat, err = _compile_query(query, case_sensitive, regex, whole_word)
    if err:
        return {"error": err, "results": []}

    glob_re = None
    if glob:
        parts = [g.strip() for g in glob.split(",") if g.strip()]
        pats = []
        for g in parts:
            pats.append(
                "^" + re.escape(g).replace(r"\*\*", ".*").replace(r"\*", "[^/\\\\]*") + "$"
            )
        glob_re = re.compile("|".join(pats), re.IGNORECASE) if pats else None

    max_results = S.SETTINGS.get("search_max_results", 500)
    if limit:
        max_results = max(1, min(int(limit), SEARCH_MORE_MAX))
    context = max(0, min(int(context), 10))
    per_file_cap = 100
    gen = _new_gen("search")

    # Fast path: ripgrep (bundled in vendor/rg, or on PATH)
    rg_res = _ripgrep_search(query, case_sensitive, regex, whole_word,
                              scope_root, base, glob, context, max_results, gen, excludes, default_excludes)
    if rg_res is not None:
        return rg_res

    # (substring, compare-lowercased) prefilter for literal queries
    needle = None
    if not regex:
        needle = (query, False) if case_sensitive else (query.lower(), True)
        if needle[1] and len(needle[0]) != len(query):
            needle = None  # lower() changed the length (rare Unicode): skip prefilter
    tasks = []
    for rel, full in _search_candidates(base, scope_root, excludes, default_excludes):
        fname = rel.rsplit("/", 1)[-1]
        if glob_re and not glob_re.match(fname):
            continue
        tasks.append((full, rel, pat, needle, context, per_file_cap, gen))

    # Parallel I/O — much faster than sequential reads on a large monorepo.
    results = []
    total = 0
    files_with_hits = 0
    it = _SEARCH_EXECUTOR.map(_search_one_file, tasks, chunksize=8)
    try:
        for batch in it:
            if _is_stale("search", gen):
                return {"results": [], "total": 0, "cancelled": True}
            if not batch:
                continue
            files_with_hits += 1
            results.extend(batch)
            total += len(batch)
            if total >= max_results:
                results = results[:max_results]
                total = len(results)
                break
    finally:
        it.close()  # cancels the queued tasks when we stop early

    return {"results": results, "total": total,
            "files": len(tasks), "hits": files_with_hits,
            "truncated": total >= max_results}
