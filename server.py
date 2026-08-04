"""
ReadO — lightweight source viewer + cross-file search.

Endpoints:
  GET  /                       -> source.html
  GET  /api/settings           -> { base_dir, ... }
  POST /api/settings           -> save settings
  GET  /api/tree?path=         -> directory listing (one level)
  GET  /api/file?path=         -> file content (text)
  GET  /api/search?q=&...      -> find-in-files results
"""
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs, unquote
import json
import os
import re
import subprocess
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
HTML_PATH = os.path.join(ROOT, "source.html")
CONFIG_PATH = os.path.join(ROOT, "config.json")
# Bundled 3rd-party assets (Monaco, marked, fonts). Served at /vendor/ so the app
# needs no network access. reado.py repoints this at the PyInstaller bundle dir.
VENDOR_PATH = os.path.join(ROOT, "vendor")

# Only what /vendor/ actually contains; anything else is refused.
VENDOR_MIME = {
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".html": "text/html; charset=utf-8",
    ".woff2": "font/woff2",
    ".woff": "font/woff",
    ".ttf": "font/ttf",
    ".svg": "image/svg+xml",
    ".map": "application/json; charset=utf-8",
}

CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)

DEFAULT_SETTINGS = {
    "base_dir": r"c:\Projects",
    "ignored": [
        ".*",  # all dot-prefixed files/folders (.git, .gradle, .idea, .vscode, .env, ...)
        "bin", "build", "doc", "gradle", "static",
        "node_modules", "dist", "target", "out",
        "__pycache__", "venv", "coverage", "logs",
    ],
    # whitelist of file extensions (search + open). Empty = use defaults below.
    "extensions": [
        ".java", ".kt", ".kts", ".gradle",
        ".js", ".jsx", ".ts", ".tsx", ".vue",
        ".html", ".css", ".scss",
        ".json", ".yml", ".yaml", ".xml", ".properties",
        ".md", ".sql", ".py",
    ],
    "max_file_bytes": 2_000_000,
    "search_max_results": 500,
}


def _allowed_exts():
    exts = SETTINGS.get("extensions") or DEFAULT_SETTINGS["extensions"]
    return {e.lower() if e.startswith(".") else "." + e.lower() for e in exts}


def _is_text_file(name: str) -> bool:
    ext = os.path.splitext(name)[1].lower()
    if not ext:
        # files without extension (Dockerfile, Makefile, etc.) — allow
        return True
    return ext in _allowed_exts()

def _apply_defaults(out: dict) -> dict:
    """If list-typed settings are empty, fall back to default values."""
    for k, default in DEFAULT_SETTINGS.items():
        if isinstance(default, list) and not out.get(k):
            out[k] = list(default)
        elif k not in out or out[k] in ("", None):
            out[k] = default
    return out


def load_settings():
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        out = dict(DEFAULT_SETTINGS)
        out.update({k: v for k, v in data.items() if k in DEFAULT_SETTINGS})
        return _apply_defaults(out)
    except Exception:
        return dict(DEFAULT_SETTINGS)


def save_settings(s: dict):
    cur = load_settings()
    cur.update({k: v for k, v in s.items() if k in DEFAULT_SETTINGS})
    cur = _apply_defaults(cur)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cur, f, indent=2)
    return cur


def ensure_config() -> bool:
    """Materialise config.json with the defaults if it is not there yet.

    load_settings() only falls back in memory, so before this the file appeared
    solely after the user pressed Save - leaving nothing to hand-edit. Returns
    True when a file was created. Must be called *after* CONFIG_PATH is final
    (reado.py repoints it at the exe directory), never at import time.
    """
    if os.path.exists(CONFIG_PATH):
        return False
    try:
        os.makedirs(os.path.dirname(CONFIG_PATH) or ".", exist_ok=True)
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(_apply_defaults(dict(DEFAULT_SETTINGS)), f, indent=2)
        return True
    except OSError:
        # read-only location: keep running on in-memory defaults
        return False


SETTINGS = load_settings()
_first_run = not os.path.exists(CONFIG_PATH)


# ----- file index for Quick Open -----
_files_cache = []          # list of relative paths
_files_cache_base = None   # base_dir when built
_files_cache_built = 0     # timestamp


def _walk_files(base):
    out = []
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = [d for d in dirnames if not _is_ignored(d)]
        for fname in filenames:
            if _is_ignored(fname) or not _is_text_file(fname):
                continue
            try:
                full = os.path.join(dirpath, fname)
                rel = os.path.relpath(full, base).replace("\\", "/")
                out.append(rel)
            except (ValueError, OSError):
                continue
    return out


def _ensure_index():
    global _files_cache, _files_cache_base, _files_cache_built
    base = SETTINGS.get("base_dir", DEFAULT_SETTINGS["base_dir"])
    age = time.time() - _files_cache_built
    if _files_cache_base != base or age > 60:  # rebuild if base changed or older than 60s
        try:
            _files_cache = _walk_files(base)
        except Exception:
            _files_cache = []
        _files_cache_base = base
        _files_cache_built = time.time()
    return _files_cache


def _substring_score(path: str, term: str):
    """Substring (case-insensitive) match like IntelliJ Search Everywhere.
    Supports '*' wildcard. Returns (score, [match start indices in full path]) or None."""
    if not term:
        return (0, [])
    fname = path.rsplit("/", 1)[-1]
    fname_lo = fname.lower()
    path_lo = path.lower()
    t = term.lower()

    # support '*' wildcard: split into parts, all must appear in order
    if "*" in t:
        parts = [p for p in t.split("*") if p]
        if not parts:
            return None
        # Try filename first, then full path
        for haystack, base_score, offset in [
            (fname_lo, 1000, len(path) - len(fname)),
            (path_lo, 500, 0),
        ]:
            indices = []
            cursor = 0
            ok = True
            for part in parts:
                idx = haystack.find(part, cursor)
                if idx < 0:
                    ok = False
                    break
                for k in range(len(part)):
                    indices.append(offset + idx + k)
                cursor = idx + len(part)
            if ok:
                score = base_score - len(haystack) + (50 if indices and indices[0] - offset == 0 else 0)
                return (score, indices)
        return None

    # plain substring
    # filename match wins
    pos = fname_lo.find(t)
    if pos >= 0:
        offset = len(path) - len(fname)
        indices = [offset + pos + k for k in range(len(t))]
        score = 1000
        if pos == 0:
            score += 100  # filename starts with term
        # camelCase boundary bonus
        if pos > 0 and fname[pos].isupper() and not fname[pos-1].isalpha():
            score += 20
        score -= len(fname)
        score -= pos // 2  # earlier match in filename = higher
        return (score, indices)

    # whole-path substring
    pos = path_lo.find(t)
    if pos >= 0:
        indices = [pos + k for k in range(len(t))]
        score = 500
        score -= len(path) // 4
        score -= pos // 4
        return (score, indices)

    return None


def goto_symbol(symbol: str, scope: str = ""):
    """Find probable declaration sites for a symbol across all indexed files.
    Ranks: declaration lines first, plain occurrences after."""
    if not symbol or len(symbol) < 2:
        return {"results": [], "total": 0}
    esc = re.escape(symbol)
    # Patterns that strongly imply a declaration of `symbol`
    decl_pat = re.compile(
        rf"^\s*(?:(?:public|private|protected|internal|export|default|static|final|abstract|open|override)\s+)*"
        rf"(?:class|interface|enum|trait|struct|record|object|@interface|type|function|fun|def|fn|sub)\s+{esc}\b"
        rf"|^\s*(?:const|let|var)\s+{esc}\s*[=:]"
        rf"|^\s*(?:public|private|protected|internal)?\s*(?:static\s+|final\s+)?[\w<>\[\],\s\?]+\s+{esc}\s*\("  # method
        rf"|^\s*{esc}\s*=\s*(?:async\s*)?\(?[^=]*\)?\s*=>",  # arrow assignment
        re.MULTILINE
    )
    word_pat = re.compile(rf"\b{esc}\b")

    base = SETTINGS["base_dir"]
    scope_root = _safe_join(base, scope) if scope else base
    if not scope_root or not os.path.isdir(scope_root):
        return {"results": [], "total": 0}

    base_abs = os.path.abspath(base)
    scope_abs = os.path.abspath(scope_root)
    scope_rel_prefix = ""
    if scope_abs.lower() != base_abs.lower():
        scope_rel_prefix = os.path.relpath(scope_abs, base_abs).replace("\\", "/") + "/"

    indexed = _ensure_index()
    decl_hits = []
    plain_hits = []
    max_total = 200
    for rel in indexed:
        if scope_rel_prefix and not rel.startswith(scope_rel_prefix):
            continue
        full = os.path.join(base, rel.replace("/", os.sep))
        text = _get_content(full)
        if text is None or not word_pat.search(text):
            continue
        lines = text.splitlines()
        for i, line in enumerate(lines):
            if not word_pat.search(line):
                continue
            entry = {"path": rel, "line": i + 1, "text": line.rstrip()}
            if decl_pat.match(line):
                decl_hits.append(entry)
            else:
                plain_hits.append(entry)
            if len(decl_hits) + len(plain_hits) >= max_total:
                break
        if len(decl_hits) + len(plain_hits) >= max_total:
            break
    return {
        "results": decl_hits + plain_hits[: max(0, 50 - len(decl_hits))],
        "declarations": len(decl_hits),
        "total": len(decl_hits) + len(plain_hits),
    }


def find_files(term: str, offset: int = 0, limit: int = 50):
    files = _ensure_index()
    scored = []
    for p in files:
        r = _substring_score(p, term)
        if r is not None:
            scored.append((r[0], p, r[1]))
    scored.sort(key=lambda x: (-x[0], x[1].lower()))
    total = len(scored)
    slice_ = scored[offset:offset + limit]
    return {
        "results": [{"path": p, "indices": idx} for _, p, idx in slice_],
        "total": total,
        "offset": offset,
        "returned": len(slice_),
        "has_more": offset + len(slice_) < total,
    }


import fnmatch as _fnmatch

def _is_ignored(name: str) -> bool:
    """Match against ignored patterns: exact name or glob (* ? [])."""
    n = name.lower()
    for pat in SETTINGS.get("ignored", []):
        if "*" in pat or "?" in pat or "[" in pat:
            if _fnmatch.fnmatchcase(n, pat.lower()):
                return True
        elif n == pat.lower():
            return True
    return False


def _safe_join(base: str, sub: str) -> str | None:
    """Resolve sub relative to base, refuse escapes."""
    if not sub or sub in (".", "./"):
        return base
    p = os.path.abspath(os.path.join(base, sub))
    base_abs = os.path.abspath(base)
    try:
        # require p to be within base_abs (Windows case-insensitive)
        if os.path.commonpath([p.lower(), base_abs.lower()]) != base_abs.lower():
            return None
    except ValueError:
        return None
    return p


def list_dir(rel_path: str = ""):
    base = SETTINGS["base_dir"]
    target = _safe_join(base, rel_path)
    if not target or not os.path.isdir(target):
        return {"error": "not a directory", "path": rel_path}
    items = []
    try:
        entries = os.listdir(target)
    except PermissionError:
        return {"error": "permission denied", "path": rel_path}
    for name in entries:
        if _is_ignored(name):
            continue
        full = os.path.join(target, name)
        try:
            is_dir = os.path.isdir(full)
            size = os.path.getsize(full) if not is_dir else None
        except OSError:
            continue
        if not is_dir and not _is_text_file(name):
            continue
        items.append({"name": name, "is_dir": is_dir, "size": size})
    # dirs first, then files, alphabetical case-insensitive
    items.sort(key=lambda e: (not e["is_dir"], e["name"].lower()))
    return {"path": rel_path, "items": items}


def read_file(rel_path: str):
    base = SETTINGS["base_dir"]
    target = _safe_join(base, rel_path)
    if not target or not os.path.isfile(target):
        return None, "not a file"
    try:
        size = os.path.getsize(target)
    except OSError as e:
        return None, str(e)
    cap = SETTINGS.get("max_file_bytes", 2_000_000)
    truncated = size > cap
    try:
        with open(target, "rb") as f:
            raw = f.read(cap if truncated else size)
    except Exception as e:
        return None, str(e)
    # try utf-8 first, then cp949 (Korean Windows), else replace
    for enc in ("utf-8", "cp949", "latin-1"):
        try:
            text = raw.decode(enc)
            return {"text": text, "size": size, "truncated": truncated, "encoding": enc}, None
        except UnicodeDecodeError:
            continue
    return {"text": raw.decode("utf-8", errors="replace"),
            "size": size, "truncated": truncated, "encoding": "replace"}, None


from concurrent.futures import ThreadPoolExecutor as _TPE
import shutil as _shutil
_SEARCH_EXECUTOR = _TPE(max_workers=32)
RIPGREP = _shutil.which("rg")

# Content cache: path -> (mtime, decoded text or None for binary)
_CONTENT_CACHE = {}
_CONTENT_CACHE_LIMIT = 5000  # cap entries to avoid unbounded memory


def _get_content(full):
    try:
        mt = os.path.getmtime(full)
        size = os.path.getsize(full)
    except OSError:
        return None
    if size > 5_000_000:
        return None
    cached = _CONTENT_CACHE.get(full)
    if cached and cached[0] == mt:
        return cached[1]
    try:
        with open(full, "rb") as f:
            raw = f.read()
    except OSError:
        return None
    if b"\x00" in raw[:1024]:
        text = None
    else:
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            try:
                text = raw.decode("cp949")
            except UnicodeDecodeError:
                text = None
    # simple cap — drop oldest when over the limit
    if len(_CONTENT_CACHE) >= _CONTENT_CACHE_LIMIT:
        # remove ~10% oldest
        for k in list(_CONTENT_CACHE.keys())[: _CONTENT_CACHE_LIMIT // 10]:
            _CONTENT_CACHE.pop(k, None)
    _CONTENT_CACHE[full] = (mt, text)
    return text


def _ripgrep_search(query, case_sensitive, regex, whole_word, scope_root, base, glob, context, max_results):
    if not RIPGREP:
        return None
    args = [RIPGREP, "--json", "--no-config", "--max-filesize", "5M",
            "--max-count", "100"]
    if not case_sensitive: args.append("-i")
    if whole_word: args.append("-w")
    if not regex: args.append("-F")
    if context > 0: args += ["--context", str(context)]
    # extension allow-list as globs
    if glob:
        for g in glob.split(","):
            g = g.strip()
            if g: args += ["--glob", g]
    else:
        for e in (SETTINGS.get("extensions") or DEFAULT_SETTINGS["extensions"]):
            args += ["--glob", "*" + e]
    # ignored folders as exclusion globs
    for ig in (SETTINGS.get("ignored") or []):
        args += ["--glob", "!" + ig]
    args.append(query)
    args.append(scope_root)
    try:
        proc = subprocess.run(
            args, capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=60, creationflags=CREATE_NO_WINDOW,
        )
    except Exception:
        return None
    if proc.returncode not in (0, 1):  # 1 = no matches (still success)
        return None

    results = []
    files_seen = set()
    pending_before = []   # context lines preceding the next match
    last_match = None     # ref to the last match dict, to append "after"
    for raw in proc.stdout.split("\n"):
        if not raw:
            continue
        try:
            obj = json.loads(raw)
        except Exception:
            continue
        t = obj.get("type")
        d = obj.get("data") or {}
        if t == "begin":
            pending_before = []
            last_match = None
        elif t == "context":
            txt = (d.get("lines") or {}).get("text", "").rstrip("\r\n")
            if last_match is not None and len(last_match["after"]) < context:
                last_match["after"].append(txt)
            else:
                pending_before.append(txt)
                if len(pending_before) > context:
                    pending_before.pop(0)
        elif t == "match":
            path = (d.get("path") or {}).get("text", "")
            line_text = (d.get("lines") or {}).get("text", "").rstrip("\r\n")
            ln = d.get("line_number", 0)
            try:
                rel = os.path.relpath(path, base).replace("\\", "/")
            except Exception:
                rel = path
            submatches = d.get("submatches") or []
            col_s = submatches[0].get("start", 0) if submatches else 0
            col_e = submatches[0].get("end", 0) if submatches else 0
            entry = {
                "path": rel, "line": ln, "text": line_text,
                "col_start": col_s, "col_end": col_e,
                "before": list(pending_before), "after": [],
                "before_start": max(1, ln - len(pending_before)),
            }
            results.append(entry)
            files_seen.add(rel)
            last_match = entry
            pending_before = []
            if len(results) >= max_results:
                break
        elif t == "end":
            last_match = None
            pending_before = []
    return {
        "results": results,
        "total": len(results),
        "files": len(files_seen),
        "truncated": len(results) >= max_results,
        "engine": "rg",
    }


def _search_one_file(args):
    full, rel, pat, context, max_per_file = args
    text = _get_content(full)
    if text is None:
        return None
    # Fast path: skip files that have no match anywhere
    if not pat.search(text):
        return None
    out = []
    lines = text.splitlines()
    for i, line in enumerate(lines):
        m = pat.search(line)
        if not m:
            continue
        lineno = i + 1
        before = lines[max(0, i - context): i]
        after = lines[i + 1: i + 1 + context]
        out.append({
            "path": rel,
            "line": lineno,
            "text": line.rstrip(),
            "col_start": m.start(),
            "col_end": m.end(),
            "before": before,
            "after": after,
            "before_start": max(1, lineno - len(before)),
        })
        if len(out) >= max_per_file:
            break
    return out


def find_in_files(query: str, case_sensitive: bool, regex: bool, whole_word: bool,
                  scope: str = "", glob: str = "", context: int = 2):
    base = SETTINGS["base_dir"]
    scope_root = _safe_join(base, scope) if scope else base
    if not scope_root or not os.path.isdir(scope_root):
        return {"error": "invalid scope", "results": []}
    if not query:
        return {"results": [], "total": 0}

    pat_str = query if regex else re.escape(query)
    if whole_word:
        pat_str = r"(?<!\w)" + pat_str + r"(?!\w)"
    try:
        pat = re.compile(pat_str, 0 if case_sensitive else re.IGNORECASE)
    except re.error as e:
        return {"error": f"regex: {e}", "results": []}

    glob_re = None
    if glob:
        parts = [g.strip() for g in glob.split(",") if g.strip()]
        pats = []
        for g in parts:
            pats.append(
                "^" + re.escape(g).replace(r"\*\*", ".*").replace(r"\*", "[^/\\\\]*") + "$"
            )
        glob_re = re.compile("|".join(pats), re.IGNORECASE) if pats else None

    max_results = SETTINGS.get("search_max_results", 500)
    context = max(0, min(int(context), 10))
    per_file_cap = 100

    # Fast path: use ripgrep if available
    rg_res = _ripgrep_search(query, case_sensitive, regex, whole_word,
                              scope_root, base, glob, context, max_results)
    if rg_res is not None:
        return rg_res

    # Reuse the cached file index (built once / refreshed every 60s).
    base_abs = os.path.abspath(base)
    scope_abs = os.path.abspath(scope_root)
    scope_rel_prefix = ""
    if scope_abs.lower() != base_abs.lower():
        scope_rel_prefix = os.path.relpath(scope_abs, base_abs).replace("\\", "/") + "/"

    indexed = _ensure_index()
    tasks = []
    for rel in indexed:
        if scope_rel_prefix and not rel.startswith(scope_rel_prefix):
            continue
        fname = rel.rsplit("/", 1)[-1]
        if glob_re and not glob_re.match(fname):
            continue
        full = os.path.join(base, rel.replace("/", os.sep))
        tasks.append((full, rel, pat, context, per_file_cap))

    # Parallel I/O — much faster than sequential reads on a large monorepo.
    results = []
    total = 0
    files_with_hits = 0
    for batch in _SEARCH_EXECUTOR.map(_search_one_file, tasks, chunksize=8):
        if not batch:
            continue
        files_with_hits += 1
        results.extend(batch)
        total += len(batch)
        if total >= max_results:
            results = results[:max_results]
            total = len(results)
            break

    return {"results": results, "total": total,
            "files": len(tasks), "hits": files_with_hits,
            "truncated": total >= max_results}


# ----- HTTP -----

def settings_status():
    base = SETTINGS.get("base_dir", DEFAULT_SETTINGS["base_dir"])
    return {**SETTINGS, "first_run": _first_run, "base_dir_exists": os.path.isdir(base)}


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode("utf-8")
        elif isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        return

    def do_GET(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        if u.path == "/" or u.path == "/source.html":
            try:
                with open(HTML_PATH, "rb") as f:
                    self._send(200, f.read(), "text/html; charset=utf-8")
            except FileNotFoundError:
                self._send(404, {"error": "source.html missing"})
        elif u.path == "/api/settings":
            self._send(200, settings_status())
        elif u.path == "/api/tree":
            self._send(200, list_dir(q.get("path", "")))
        elif u.path == "/api/file":
            data, err = read_file(q.get("path", ""))
            if err:
                self._send(404, {"error": err})
            else:
                self._send(200, data)
        elif u.path == "/api/search":
            try:
                ctx = int(q.get("ctx", "2"))
            except ValueError:
                ctx = 2
            res = find_in_files(
                query=q.get("q", ""),
                case_sensitive=q.get("case", "0") == "1",
                regex=q.get("regex", "0") == "1",
                whole_word=q.get("word", "0") == "1",
                scope=q.get("scope", ""),
                glob=q.get("glob", ""),
                context=ctx,
            )
            self._send(200, res)
        elif u.path == "/api/goto":
            self._send(200, goto_symbol(q.get("symbol", ""), q.get("scope", "")))
        elif u.path == "/api/files":
            try:
                limit = int(q.get("limit", "50"))
                offset = int(q.get("offset", "0"))
            except ValueError:
                limit, offset = 50, 0
            self._send(200, find_files(q.get("q", ""), offset, limit))
        elif u.path == "/api/projects":
            base = SETTINGS.get("base_dir", DEFAULT_SETTINGS["base_dir"])
            projects = []
            try:
                for name in sorted(os.listdir(base), key=str.lower):
                    if _is_ignored(name):
                        continue
                    full = os.path.join(base, name)
                    if os.path.isdir(full):
                        projects.append(name)
            except OSError:
                pass
            self._send(200, {"projects": projects})
        elif u.path.startswith("/vendor/"):
            self._send_vendor(unquote(u.path[len("/vendor/"):]))
        else:
            self._send(404, {"error": "not found"})

    def _send_vendor(self, rel):
        """Serve a bundled asset from VENDOR_PATH. Read-only, no directory listing."""
        if not rel or rel.endswith("/"):
            return self._send(404, {"error": "not found"})
        full = os.path.abspath(os.path.join(VENDOR_PATH, rel.replace("/", os.sep)))
        root = os.path.abspath(VENDOR_PATH)
        # reject traversal outside the vendor dir
        try:
            if os.path.commonpath([full.lower(), root.lower()]) != root.lower():
                return self._send(403, {"error": "forbidden"})
        except ValueError:  # different drive
            return self._send(403, {"error": "forbidden"})
        ctype = VENDOR_MIME.get(os.path.splitext(full)[1].lower())
        if not ctype:
            return self._send(403, {"error": "forbidden"})
        try:
            with open(full, "rb") as f:
                body = f.read()
        except (FileNotFoundError, IsADirectoryError, PermissionError, OSError):
            return self._send(404, {"error": "not found"})
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        # bundled assets are immutable for a given build
        self.send_header("Cache-Control", "public, max-age=31536000, immutable")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        u = urlparse(self.path)
        if u.path == "/api/settings":
            length = int(self.headers.get("Content-Length") or 0)
            try:
                data = json.loads(self.rfile.read(length) or b"{}")
            except json.JSONDecodeError:
                return self._send(400, {"error": "invalid json"})
            global SETTINGS, _first_run, _files_cache, _files_cache_base, _files_cache_built
            SETTINGS = save_settings(data)
            _first_run = False
            # invalidate file cache so new ignored rules take effect immediately
            _files_cache = []
            _files_cache_base = None
            _files_cache_built = 0
            return self._send(200, settings_status())
        return self._send(404, {"error": "not found"})


def serve(host="127.0.0.1", port=8766):
    print(f"ReadO: http://{host}:{port}/")
    HTTPServer((host, port), Handler).serve_forever()


if __name__ == "__main__":
    ensure_config()
    SETTINGS = load_settings()
    serve()
