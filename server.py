"""
ReadO — lightweight source viewer + cross-file search.

Endpoints:
  GET  /                       -> source.html (with the CSRF token injected)
  GET  /api/settings           -> { base_dir, ... }
  POST /api/settings           -> save settings            (write API, guarded)
  GET  /api/tree?path=         -> directory listing (one level)
  GET  /api/file?path=         -> file content (text) + mtime_ns, encoding, readonly
  GET  /api/state              -> saved UI state
  POST /api/save               -> save an open file           (write API, guarded)
  POST /api/create             -> new empty file in base_dir   (write API, guarded)
  POST /api/replace-preview    -> replace in files: plan only  (write API, guarded)
  POST /api/replace-apply      -> replace in files: write ticked files (write API, guarded)
  POST /api/stat               -> change polling + files to open (write API, guarded)
  POST /api/state              -> save UI state               (write API, guarded)
  POST /api/open-request       -> second instance hands over files (guarded + IPC secret)
  GET  /api/search?q=&...      -> find-in-files results
  GET  /api/goto?symbol=&from= -> declarations (ctags index, else search + patterns; index_only=1: index only)
  GET  /api/refs?symbol=&from= -> usages (whole word, case-sensitive)
  GET  /api/symbols?q=&cat=    -> workspace symbol search (ctags index)
  GET  /api/component?name=&from= -> file(s) for a component tag (<ItemTop>, <item-top>)
  GET  /api/tags-status        -> symbol index state (starts / refreshes it)
  POST /api/outline            -> symbols of an editor buffer  (write API, guarded)
  POST /api/link               -> what an import path / imported name points at (guarded)
  POST /api/rename /delete /mkdir -> tree file operations (write API, guarded; delete = Recycle Bin)
  POST /api/git-changes        -> changed lines of a buffer against git HEAD (guarded)
  GET  /api/git/...            -> read-only git views (gitview.py: status, log, commit, show, blame …)
  POST /api/git/agento /terminal -> start AgentO / open a terminal in a repository (guarded)
  GET  /app/git.js /app/git.css -> the Git tool window (next to source.html)
  GET  /api/files?q=           -> Quick Open file-name search
  GET  /api/projects           -> top-level folders of base_dir
  GET  /vendor/...             -> bundled 3rd-party assets
  GET  /favicon.ico            -> the app icon (title bar logo)

Security model (see "request guards" below):
  * every request must carry Host 127.0.0.1:<port> or localhost:<port>
    (blocks DNS rebinding) and must not come from another site
    (Origin / Sec-Fetch-Site);
  * every POST goes through @write_api, which also requires the per-process
    CSRF token (X-ReadO-Token header) and a JSON body. The token is injected
    into source.html when it is served, together with a fetch() wrapper that
    adds the header to same-origin non-GET requests automatically.
"""
from http.server import BaseHTTPRequestHandler, HTTPServer, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs, unquote
from collections import OrderedDict
import base64
import fnmatch as _fnmatch
import hmac
import json
import os
import re
import secrets
import subprocess
import sys
import tempfile
import threading
import time

import gitview

# The srv_*.py modules hold parts of this one and `import server`: run as a
# script (python server.py), make that name mean this module, not a 2nd copy.
sys.modules.setdefault("server", sys.modules[__name__])

ROOT = os.path.dirname(os.path.abspath(__file__))
HTML_PATH = os.path.join(ROOT, "source.html")
CONFIG_PATH = os.path.join(ROOT, "config.json")
# Bundled 3rd-party assets (Monaco, marked, fonts, ripgrep). Served at /vendor/ so
# the app needs no network access. reado.py repoints this at the PyInstaller bundle dir.
VENDOR_PATH = os.path.join(ROOT, "vendor")

# Only what /vendor/ actually serves; anything else (e.g. rg.exe) is refused.
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

# Page parts served from next to source.html (fixed list, no directory access)
APP_FILES = {"/app/git.js": "text/javascript; charset=utf-8", "/app/git.css": "text/css; charset=utf-8",
             "/app/diffwin.js": "text/javascript; charset=utf-8"}

CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)

DEFAULT_SETTINGS = {
    "config_version": 2,
    # empty until the user opens a folder (start screen); remembered afterwards
    "base_dir": "",
    # hidden everywhere (tree, Quick Open, search). Exact names or globs.
    "ignored": [".git", ".svn", ".hg", "node_modules", "__pycache__", ".venv", "venv"],
    # shown in the tree, but left out of search, Quick Open and symbol indexing
    "search_ignored": ["build", "dist", "target", "out", "bin", "obj", "coverage"],
    "max_file_bytes": 2_000_000,
    "search_max_results": 500,
    # also hide what .gitignore files exclude (tree, Quick Open, symbols, search)
    "respect_gitignore": False,
}

# What older builds wrote as defaults. A config still carrying exactly these is
# migrated to the general defaults above; anything the user changed is kept.
_V1_DEFAULT_IGNORED = [".*", "bin", "build", "doc", "gradle", "static", "node_modules", "dist",
                       "target", "out", "__pycache__", "venv", "coverage", "logs"]
_V1_DEFAULT_BASE_DIR = r"c:\Projects"

# Text vs binary: a file is a text candidate unless its extension is a known
# binary format; opening it then checks the content (_looks_binary). This
# replaces the old extension allow-list, so .txt/.sh/.toml/.log/Dockerfile...
# behave the same inside and outside the working folder.
BINARY_EXTS = frozenset("""
.exe .dll .so .dylib .o .obj .a .lib .pdb .ilk .exp .class .jar .war .ear .aar .dex .apk .ipa
.pyc .pyo .pyd .whl .egg .node .wasm .zip .gz .tgz .bz2 .xz .zst .7z .rar .tar .cab .iso .img .dmg
.msi .msix .deb .rpm .png .jpg .jpeg .gif .bmp .ico .icns .webp .tif .tiff .psd .ai .heic .avif
.pdf .doc .docx .xls .xlsx .ppt .pptx .hwp .hwpx .odt .ods .odp .mp3 .mp4 .m4a .avi .mov .mkv
.wav .flac .ogg .webm .wmv .woff .woff2 .ttf .otf .eot .bin .dat .db .sqlite .sqlite3 .mdb
.accdb .dbf .pak .swf .fla .blend .fbx .glb .unitypackage .keystore .jks .p12 .pfx .der
""".split())

# Left out of Find / Replace in Files while the search box's "default excludes"
# toggle is on (with settings.search_ignored): IDE folders, minified / bundled
# output, source maps, lock files and IntelliJ shelf patches (.idea/shelf/*/
# shelved.patch, also when the shelf is kept outside .idea) - noise in a text
# search. Quick Open keeps them so they can still be opened by name.
SEARCH_DEFAULT_EXCLUDES = (".idea", ".vs", "*.min.js", "*.min.css", "*.min.mjs", "*.bundle.js", "*.chunk.js",
                           "*.map", "*.tsbuildinfo", "shelved.patch", "*.lock", "package-lock.json", "pnpm-lock.yaml",
                           "npm-shrinkwrap.json")
EXCLUDE_MAX = 50           # patterns per search
EXCLUDE_MAX_LEN = 200      # characters per pattern


def parse_excludes(text):
    """The search box's exclude patterns (comma or newline separated globs) ->
    (patterns, None) or (None, error). Like VS Code's: `*.min.js`, `.idea/**`,
    `src/gen` match at any depth (the open folder often holds several
    projects), a leading / anchors at the open folder (`/web/dist`). Refuses
    what could leave the folder or read as an rg option: drive letters, `..`,
    a leading - or !."""
    out = []
    for raw in re.split(r"[,\r\n]", str(text or "")):
        p = raw.strip().replace("\\", "/")
        if not p:
            continue
        if len(out) >= EXCLUDE_MAX:
            return None, f"too many exclude patterns (maximum {EXCLUDE_MAX})"
        if len(p) > EXCLUDE_MAX_LEN:
            return None, f"exclude pattern is too long: {p[:40]}…"
        if any(ord(ch) < 32 for ch in p) or p[0] in "-!" or ":" in p or ".." in p.split("/"):
            return None, f"exclude pattern not allowed: {p}"
        anchored = p.startswith("/")
        p = p.strip("/") + ("/**" if p.endswith("/") and p.strip("/") else "")
        if not p or p.count("[") != p.count("]") or p.count("{") != p.count("}"):
            return None, f"exclude pattern not allowed: {raw.strip()}"
        if anchored:
            p = "/" + p
        elif "/" in p and not p.startswith("**/"):
            p = "**/" + p
        out.append(p)
    return out, None


def split_mask(glob, exclude):
    """The file mask's `!pattern` entries are excludes too: (include mask,
    exclude patterns, None) or (None, None, error)."""
    inc, neg = [], []
    for g in str(glob or "").split(","):
        g = g.strip()
        (neg if g.startswith("!") else inc).append(g[1:] if g.startswith("!") else g)
    excludes, err = parse_excludes(",".join([str(exclude or "")] + neg))
    if err:
        return None, None, err
    return ",".join(x for x in inc if x), excludes, None


def _glob_rx(pat):
    """One exclude glob -> regex over a /-path (** any depth, * ? [] {a,b} within a segment)."""
    rx, i = "", 0
    while i < len(pat):
        c = pat[i]
        if pat.startswith("**/", i):
            rx += "(?:.*/)?"; i += 3; continue
        if pat.startswith("**", i):
            rx += ".*"; i += 2; continue
        if c == "*":
            rx += "[^/]*"
        elif c == "?":
            rx += "[^/]"
        elif c == "[":
            j = pat.find("]", i + 1)
            body = pat[i + 1:j].replace("\\", "\\\\")
            rx += "[^" + body[1:] + "]" if body[:1] == "!" else "[" + body + "]"
            i = j + 1; continue
        elif c == "{":
            j = pat.find("}", i + 1)
            rx += "(?:" + "|".join(re.escape(x) for x in pat[i + 1:j].split(",")) + ")"
            i = j + 1; continue
        else:
            rx += re.escape(c)
        i += 1
    return rx


def _exclude_matcher(patterns):
    """rel path -> excluded? Like rg's globs: a pattern without / matches a file
    or folder name at any depth, one with / the path from the open folder (the
    file itself or any folder above it; parse_excludes gives the unanchored
    ones a **/ prefix). None when there is nothing to match."""
    def rx(pats):
        return re.compile("(?:" + "|".join(f"(?:{_glob_rx(p)})" for p in pats) + r")\Z", re.IGNORECASE) if pats else None

    name_re = rx([p for p in patterns if "/" not in p])
    path_re = rx([p.lstrip("/") for p in patterns if "/" in p])
    if not name_re and not path_re:
        return None

    def excluded(rel):
        parts = rel.split("/")
        if name_re and any(name_re.match(x) for x in parts):
            return True
        return bool(path_re) and any(path_re.match("/".join(parts[:k])) for k in range(1, len(parts) + 1))
    return excluded


# ----- name filters (ignored patterns) -----
# Precomputed once per settings value instead of on every call: these run for
# every directory entry during tree listing and index walks.
_filters_key = None
_filters_val = None


def _compile_names(patterns):
    exact, globs = set(), []
    for pat in patterns or []:
        p = str(pat).lower()
        if "*" in p or "?" in p or "[" in p:
            globs.append(_fnmatch.translate(p))
        elif p:
            exact.add(p)
    return frozenset(exact), (re.compile("|".join(globs)) if globs else None)


def _filters():
    global _filters_key, _filters_val
    ignored = SETTINGS.get("ignored") or []
    search_ignored = SETTINGS.get("search_ignored") or []
    key = (tuple(ignored), tuple(search_ignored))
    if key != _filters_key:
        _filters_val = (_compile_names(ignored), _compile_names(search_ignored))
        _filters_key = key
    return _filters_val


def _name_match(compiled, name):
    exact, glob_re = compiled
    n = name.lower()
    return n in exact or (glob_re is not None and glob_re.match(n) is not None)


def _is_binary_name(name: str) -> bool:
    return os.path.splitext(name)[1].lower() in BINARY_EXTS


def _is_text_file(name: str) -> bool:
    """Text *candidate* by name: anything not on the binary blocklist. The
    content check happens when the file is read (_looks_binary)."""
    return not _is_binary_name(name)


def _is_ignored(name: str) -> bool:
    """Hidden everywhere: exact name or glob (* ? []) from settings.ignored."""
    return _name_match(_filters()[0], name)


def _is_search_ignored(name: str) -> bool:
    """Visible in the tree but skipped by search / Quick Open / symbols."""
    return _name_match(_filters()[1], name)


def base_root():
    """realpath of the working folder, or None when none is open. Every path
    check goes through this: an empty base_dir must never mean "the current
    directory"."""
    b = SETTINGS.get("base_dir") or ""
    if not b.strip():
        return None
    real = os.path.realpath(b)
    return real if os.path.isdir(real) else None


def _apply_defaults(out: dict) -> dict:
    """Fill in missing keys (an explicitly empty list stays empty)."""
    for k, default in DEFAULT_SETTINGS.items():
        if k not in out or out[k] is None or (isinstance(default, list) and not isinstance(out[k], list)):
            out[k] = list(default) if isinstance(default, list) else default
    return out


def _migrate_settings(data: dict) -> dict:
    """Config files from older builds (no config_version): drop the
    extension allow-list, swap the old org-specific defaults for the general
    ones, keep whatever the user actually changed."""
    if not isinstance(data, dict) or int(data.get("config_version") or 1) >= 2:
        return data
    d = dict(data)
    d.pop("extensions", None)
    old = d.get("ignored")
    if not old or {str(x).lower() for x in old} == {x.lower() for x in _V1_DEFAULT_IGNORED}:
        d["ignored"] = list(DEFAULT_SETTINGS["ignored"])
        d["search_ignored"] = list(DEFAULT_SETTINGS["search_ignored"])
    if str(d.get("base_dir", "")).lower() == _V1_DEFAULT_BASE_DIR.lower() and not os.path.isdir(d["base_dir"]):
        d["base_dir"] = ""
    d["config_version"] = 2
    return d


def _write_config(cur):
    folder = os.path.dirname(CONFIG_PATH) or "."
    os.makedirs(folder, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=folder, prefix=".reado-config-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            json.dump(cur, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, CONFIG_PATH)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def load_settings(persist=True):
    """Settings from config.json; a migrated old config is written back once
    (persist=False only reads, used at import time)."""
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return _apply_defaults({})
    migrated = _migrate_settings(data)
    out = _apply_defaults({k: v for k, v in migrated.items() if k in DEFAULT_SETTINGS})
    if migrated is not data and persist:
        try:
            _write_config(out)  # persist the migration once
        except OSError:
            pass
    return out


def save_settings(s: dict):
    cur = load_settings()
    cur.update({k: v for k, v in s.items() if k in DEFAULT_SETTINGS and k != "config_version"})
    cur = _apply_defaults(cur)
    _write_config(cur)
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


SETTINGS = load_settings(persist=False)  # reado.py / __main__ load the real one
_first_run = not os.path.exists(CONFIG_PATH)


# ----- file index for Quick Open / goto / fallback search -----
# Built synchronously only the first time (or when base_dir changes). After that
# a stale index (older than INDEX_TTL) is served as-is while a background thread
# rebuilds it, so no request waits for a full walk.
INDEX_TTL = 60
_index_lock = threading.Lock()        # guards _index
_index_build_lock = threading.Lock()  # one synchronous cold build at a time
_index = {"base": None, "files": [], "built": 0.0, "building": False, "version": 0}
_file_query_cache = OrderedDict()
_file_query_cache_lock = threading.Lock()
FILE_QUERY_CACHE_MAX = 12


# ----- .gitignore (optional filter: settings.respect_gitignore) -----
# When on, files and folders a .gitignore excludes are hidden from the tree,
# Quick Open, the symbol index and search (ripgrep gets the same rules). Rules
# come from every .gitignore between the repository root (the folder holding
# .git, found upwards from base_dir) and the file, plus .git/info/exclude; the
# last matching rule wins and "!" re-includes, as in git. Parsed files are
# cached by mtime.
_gi_cache = {}  # .gitignore path -> (mtime_ns, [(regex, negate, dir_only)])


def _gi_compile(pattern):
    """One gitignore pattern -> (regex over the path relative to its folder, negate, dir_only), or None."""
    p = pattern.rstrip("\n\r")
    if not p or p.startswith("#"):
        return None
    p = re.sub(r"(?<!\\)\s+$", "", p)
    negate = p.startswith("!")
    if negate:
        p = p[1:]
    p = p.replace("\\#", "#").replace("\\!", "!")
    dir_only = p.endswith("/")
    p = p.rstrip("/")
    if not p:
        return None
    anchored = "/" in p
    p = p.lstrip("/")
    out, i = [], 0
    while i < len(p):
        c = p[i]
        if p.startswith("**/", i):
            out.append("(?:.*/)?"); i += 3; continue
        if p.startswith("/**", i) and i + 3 == len(p):
            out.append("/.*"); i += 3; continue
        if c == "*":
            out.append("[^/]*")
        elif c == "?":
            out.append("[^/]")
        elif c == "[":
            j = p.find("]", i + 1)
            if j < 0:
                out.append(re.escape(c))
            else:
                body = p[i + 1:j]
                if body.startswith("!"):
                    body = "^" + body[1:]
                out.append("[" + body.replace("\\", "\\\\") + "]")
                i = j
        else:
            out.append(re.escape(c))
        i += 1
    rx = "".join(out)
    rx = ("^" + rx if anchored else "^(?:.*/)?" + rx) + "$"
    try:
        return re.compile(rx, re.IGNORECASE if os.name == "nt" else 0), negate, dir_only
    except re.error:
        return None


def _gi_rules(path):
    """Compiled rules of one ignore file (cached by mtime)."""
    try:
        m = os.stat(path).st_mtime_ns
    except OSError:
        return []
    hit = _gi_cache.get(path)
    if hit and hit[0] == m:
        return hit[1]
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            rules = [r for r in (_gi_compile(line) for line in f) if r]
    except OSError:
        rules = []
    if len(_gi_cache) > 2000:
        _gi_cache.clear()
    _gi_cache[path] = (m, rules)
    return rules


def _gi_repo_root(base):
    d = base
    for _ in range(40):
        if os.path.exists(os.path.join(d, ".git")):
            return d
        up = os.path.dirname(d)
        if up == d:
            break
        d = up
    return base


def _gi_chain(folder, root, memo):
    """[(folder, rules)] of every ignore file from root down to folder."""
    key = _norm(folder)
    if key in memo:
        return memo[key]
    if _norm(folder) == _norm(root) or not _within(folder, root):
        chain = []
        excl = os.path.join(root, ".git", "info", "exclude")
        if os.path.isfile(excl):
            chain.append((root, _gi_rules(excl)))
    else:
        chain = list(_gi_chain(os.path.dirname(folder), root, memo))
    gi = os.path.join(folder, ".gitignore")
    if os.path.isfile(gi):
        chain = chain + [(folder, _gi_rules(gi))]
    memo[key] = chain
    return chain


def gitignored(full, is_dir, memo=None, root=None):
    """True if git would ignore this path (the path itself or a parent folder)."""
    base = base_root()
    if not base or not _within(full, base):
        return False
    root = root or _gi_repo_root(base)
    memo = {} if memo is None else memo
    # a file in an ignored folder is ignored, whatever its own rules say
    parent = os.path.dirname(full)
    pk = ("dir", _norm(parent))
    if pk not in memo:
        memo[pk] = _norm(parent) != _norm(base) and _within(parent, base) and gitignored(parent, True, memo, root)
    if memo[pk]:
        return True
    verdict = False
    for folder, rules in _gi_chain(parent, root, memo):
        rel = os.path.relpath(full, folder).replace("\\", "/")
        for rx, negate, dir_only in rules:
            if dir_only and not is_dir:
                continue
            if rx.match(rel):
                verdict = not negate
    return verdict


def _gi_on():
    return bool(SETTINGS.get("respect_gitignore"))


def _walk_files(base, search_excluded=True):
    """Relative paths of every visible text file under base (os.walk order).
    search_excluded=False keeps what settings.search_ignored leaves out."""
    out = []
    stack = [base]
    gi = _gi_on()
    gi_memo, gi_root = {}, (_gi_repo_root(base) if gi else None)
    while stack:
        top = stack.pop()
        try:
            it = os.scandir(top)
        except OSError:
            continue
        subdirs = []
        with it:
            for e in it:
                name = e.name
                try:
                    is_dir = e.is_dir()
                except OSError:
                    continue
                if is_dir:
                    # like os.walk(followlinks=False): list symlinked dirs, don't descend
                    if not _is_ignored(name) and not (search_excluded and _is_search_ignored(name)) and not e.is_symlink() \
                            and not (gi and gitignored(e.path, True, gi_memo, gi_root)):
                        subdirs.append(e.path)
                    continue
                if e.is_symlink():
                    continue
                if _is_ignored(name) or (search_excluded and _is_search_ignored(name)) or not _is_text_file(name):
                    continue
                if gi and gitignored(e.path, False, gi_memo, gi_root):
                    continue
                try:
                    out.append(os.path.relpath(e.path, base).replace("\\", "/"))
                except ValueError:
                    continue
        stack.extend(reversed(subdirs))
    return out


def _rebuild_index_bg(base):
    try:
        files = _walk_files(base)
    except Exception:
        files = None
    with _index_lock:
        _index["building"] = False
        if files is not None and _index["base"] == base:
            _index["files"] = files
            _index["built"] = time.time()
            _index["version"] += 1


def _ensure_index():
    base = base_root()
    if base is None:
        return []
    with _index_lock:
        if _index["base"] == base:
            if time.time() - _index["built"] > INDEX_TTL and not _index["building"]:
                _index["building"] = True
                threading.Thread(target=_rebuild_index_bg, args=(base,), daemon=True).start()
            return _index["files"]
    with _index_build_lock:
        with _index_lock:
            if _index["base"] == base:  # another thread finished the cold build
                return _index["files"]
        try:
            files = _walk_files(base)
        except Exception:
            files = []
        with _index_lock:
            _index.update(base=base, files=files, built=time.time(), building=False,
                          version=_index["version"] + 1)
        return files


def _index_reset():
    with _index_lock:
        _index.update(base=None, files=[], built=0.0, version=_index["version"] + 1)
    with _file_query_cache_lock:
        _file_query_cache.clear()


def source_changed():
    """Many files changed under the folder at once (git pull / checkout): the file list and
    the symbol index catch up in the background, the old ones stay usable meanwhile."""
    with _index_lock:
        _index["built"] = 0.0
        built = _index["base"] is not None and _index["base"] == base_root()
    with _file_query_cache_lock:
        _file_query_cache.clear()
    if built:  # else the first search builds it anyway
        _ensure_index()
    ensure_tags(force=True)


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


def find_files(term: str, offset: int = 0, limit: int = 50):
    files = _ensure_index()
    with _index_lock:
        version = _index["version"]
    key = (version, term.lower())
    with _file_query_cache_lock:
        scored = _file_query_cache.get(key)
        if scored is not None:
            _file_query_cache.move_to_end(key)
    if scored is None:
        scored = []
        for p in files:
            r = _substring_score(p, term)
            if r is not None:
                scored.append((r[0], p, r[1]))
        scored.sort(key=lambda x: (-x[0], x[1].lower()))
        # Bound memory by entry count and per-query result size.
        if len(scored) <= 10000:
            with _file_query_cache_lock:
                _file_query_cache[key] = scored
                _file_query_cache.move_to_end(key)
                while len(_file_query_cache) > FILE_QUERY_CACHE_MAX:
                    _file_query_cache.popitem(last=False)
    total = len(scored)
    slice_ = scored[max(0, offset):max(0, offset) + max(0, min(limit, 200))]
    return {
        "results": [{"path": p, "indices": idx} for _, p, idx in slice_],
        "total": total,
        "offset": offset,
        "returned": len(slice_),
        "has_more": offset + len(slice_) < total,
    }


def _norm(p: str) -> str:
    return os.path.normcase(os.path.abspath(p))


def _within(path: str, root: str) -> bool:
    try:
        return os.path.commonpath([_norm(path), _norm(root)]) == _norm(root)
    except ValueError:  # different drive
        return False


def _safe_join(base: str, sub: str) -> str | None:
    """Resolve sub relative to base, refusing lexical and symlink escapes.
    No base (no folder open) resolves nothing."""
    if not base or not str(base).strip():
        return None
    if not sub or sub in (".", "./"):
        p = os.path.realpath(base)
    else:
        p = os.path.realpath(os.path.join(base, sub))
    root = os.path.realpath(base)
    return p if _within(p, root) else None


def list_dir(rel_path: str = ""):
    base = base_root()
    if base is None:
        return {"error": "no folder open", "no_folder": True, "path": rel_path, "items": []}
    target = _safe_join(base, rel_path)
    if not target or not os.path.isdir(target):
        return {"error": "not a directory", "path": rel_path}
    items = []
    gi = _gi_on()
    gi_memo = {}
    try:
        it = os.scandir(target)
    except PermissionError:
        return {"error": "permission denied", "path": rel_path}
    except OSError as e:
        return {"error": str(e), "path": rel_path}
    with it:
        for e in it:
            name = e.name
            if _is_ignored(name):
                continue
            try:
                is_dir = e.is_dir()
                if e.is_symlink():
                    continue
                size = None if is_dir else e.stat().st_size
            except OSError:
                continue
            if gi and gitignored(e.path, is_dir, gi_memo):
                continue
            item = {"name": name, "is_dir": is_dir, "size": size}
            if not is_dir and _is_binary_name(name):
                item["binary"] = True  # listed (dimmed) but not opened as text
            items.append(item)
    # dirs first, then files, alphabetical case-insensitive
    items.sort(key=lambda e: (not e["is_dir"], e["name"].lower()))
    return {"path": rel_path, "items": items}


def _cut_at_boundary(raw: bytes) -> bytes:
    """Trim a truncated read to the last complete line (or at least to a whole
    UTF-8 character) so the tail does not decode as garbage or flip the
    detected encoding."""
    nl = raw.rfind(b"\n")
    if nl > 0:
        return raw[:nl + 1]
    i = len(raw)
    while i > 0 and len(raw) - i < 3 and (raw[i - 1] & 0xC0) == 0x80:
        i -= 1
    if i > 0 and raw[i - 1] >= 0xC0:  # lead byte: drop it if its sequence is cut
        lead = raw[i - 1]
        need = 4 if lead >= 0xF0 else 3 if lead >= 0xE0 else 2
        if len(raw) - (i - 1) < need:
            return raw[:i - 1]
    return raw


_BOMS = ((b"\xef\xbb\xbf", "utf-8"), (b"\xff\xfe", "utf-16-le"), (b"\xfe\xff", "utf-16-be"))
SAVE_ENCODINGS = ("utf-8", "cp949", "latin-1", "utf-16-le", "utf-16-be")


def _guess_utf16(sample: bytes):
    """UTF-16 without a BOM: mostly-ASCII text has a NUL in every other byte."""
    half = len(sample) // 2
    if half < 2:
        return None
    even, odd = sample[0::2].count(0), sample[1::2].count(0)
    if odd > 0.4 * half and even < 0.05 * half:
        return "utf-16-le"
    if even > 0.4 * half and odd < 0.05 * half:
        return "utf-16-be"
    return None


_CTRL_OK = frozenset((8, 9, 10, 12, 13, 27))  # BS TAB LF FF CR ESC appear in real text


def _looks_binary(sample: bytes) -> bool:
    """Content check on the first 8 KB: any NUL, or more than 30% control
    bytes, means binary (callers try UTF-16 before this)."""
    if not sample:
        return False
    if b"\x00" in sample:
        return True
    ctrl = sum(1 for b in sample if b < 32 and b not in _CTRL_OK)
    return ctrl > 0.30 * len(sample)


def _decode(raw: bytes):
    """(text, encoding, bom). BOM first, then BOM-less UTF-16, utf-8 -> cp949
    (Korean Windows) -> latin-1, which never fails."""
    for mark, enc in _BOMS:
        if raw.startswith(mark):
            return raw[len(mark):].decode(enc, errors="replace"), enc, True
    enc16 = _guess_utf16(raw[:8192])
    if enc16:
        return raw.decode(enc16, errors="replace"), enc16, False
    for enc in ("utf-8", "cp949"):
        try:
            return raw.decode(enc), enc, False
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1"), "latin-1", False


def sniff_binary(raw: bytes) -> bool:
    """True if raw (the start of a file) is not text by ReadO's rules."""
    head = raw[:8192]
    if any(head.startswith(m) for m, _ in _BOMS) or _guess_utf16(head):
        return False
    return _looks_binary(head)


def resolve_read_path(key: str):
    """Absolute path for a client file key, or None. Keys are paths relative to
    base_dir, or absolute paths the user opened explicitly (see grant_external)."""
    base = base_root()
    if _is_abs_key(key):
        full = os.path.realpath(key)
        if base and _within(full, base):
            return full
        return full if _is_granted(full) else None
    return _safe_join(base, key) if base else None


def read_file(rel_path: str, encoding: str = ""):
    """encoding: decode with this one (reopen with encoding) instead of guessing."""
    target = resolve_read_path(rel_path)
    if not target or not os.path.isfile(target):
        return None, "not a file"
    try:
        st = os.stat(target)
    except OSError as e:
        return None, str(e)
    size = st.st_size
    cap = SETTINGS.get("max_file_bytes", 2_000_000)
    truncated = size > cap
    try:
        with open(target, "rb") as f:
            raw = f.read(cap if truncated else size)
    except Exception as e:
        return None, str(e)
    if truncated:
        raw = _cut_at_boundary(raw)
    if _is_binary_name(target) or sniff_binary(raw):
        return None, BinaryFile(size)
    if encoding in SAVE_ENCODINGS:
        bom = False
        for mark, benc in _BOMS:
            if raw.startswith(mark) and benc == encoding:
                raw, bom = raw[len(mark):], True
        text, enc = raw.decode(encoding, errors="replace"), encoding
    else:
        text, enc, bom = _decode(raw)
    if truncated:
        readonly = ("large file (%.1f MB): only the first %.1f MB is shown and it is read-only"
                    % (size / 1_000_000, cap / 1_000_000))
    else:
        readonly = _write_target(rel_path, must_exist=True)[1]
    return {"text": text, "size": size, "truncated": truncated, "encoding": enc,
            "bom": bom, "binary": False, "mtime_ns": str(st.st_mtime_ns),
            "readonly": readonly}, None


class BinaryFile(str):
    """read_file() error for a non-text file (sent as 415 with its size)."""
    def __new__(cls, size):
        obj = super().__new__(cls, "binary file — ReadO opens text files only")
        obj.size = size
        return obj


# ----- search -----
from concurrent.futures import ThreadPoolExecutor as _TPE
import shutil as _shutil
# 8 workers read files as fast as 32 here, and leave the GIL free often
# enough for tree/file requests to stay responsive during a fallback search.
_SEARCH_EXECUTOR = _TPE(max_workers=8)
_SEARCH_GATE = threading.BoundedSemaphore(2)

# Set False to force the pure-Python search path (benchmarks / troubleshooting).
USE_RIPGREP = True
MAX_LINE_CHARS = 2000      # longer result/context lines are clipped around the match
RG_TIMEOUT = 60            # seconds before a ripgrep run is killed


def _rg_path():
    """Bundled vendor/rg/rg.exe first, then rg on PATH, else None."""
    if not USE_RIPGREP:
        return None
    exe = "rg.exe" if os.name == "nt" else "rg"
    bundled = os.path.join(VENDOR_PATH, "rg", exe)
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
    if sniff_binary(raw):
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
    ignore = (["--no-ignore-dot", "--no-ignore-global", "--no-require-git"] if _gi_on() else ["--no-ignore"])
    args = ["--json", "--no-config"] + ignore + ["--hidden", "--max-filesize", "5M"]
    # optional "files to include" filter from the search box (*.java, src/**)
    for g in (glob or "").split(","):
        g = g.strip()
        if g:
            args += ["--glob", g]
    # every non-binary file is searched (rg also skips binary content itself);
    # known binary types, hidden and search-excluded names are left out.
    # Excludes come last so they win over the include globs.
    args += ["--iglob", "!*{" + ",".join(sorted(BINARY_EXTS)) + "}"]
    skip = list(SETTINGS.get("ignored") or [])
    if defaults is not False:
        skip += list(SETTINGS.get("search_ignored") or [])
    if defaults:
        skip += SEARCH_DEFAULT_EXCLUDES
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
            stdin=subprocess.DEVNULL, creationflags=CREATE_NO_WINDOW, cwd=cwd,
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
    for rel in _ensure_index():
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
                 for rel in _walk_files(scope_root, search_excluded=False))
    skip = _exclude_matcher(list(SEARCH_DEFAULT_EXCLUDES if defaults else ()) + list(excludes))
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
    base = base_root()
    scope_root = _safe_join(base, scope) if scope else base
    if not scope_root or not os.path.isdir(scope_root):
        return {"error": "invalid scope", "results": []}
    glob, excludes, err = split_mask(glob, exclude)
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

    max_results = SETTINGS.get("search_max_results", 500)
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


# ----- go to definition / references -----
# Candidates come from a whole-word, case-sensitive search for the symbol (rg,
# or the Python scan); each hit line is then classified with declaration
# patterns for the file's language. Call sites (`return foo(`, `new Foo(`,
# `a.foo(`, `x = foo(`) are rejected, and the remaining declarations are ranked
# (kind, same file, nearby folders, file named after the symbol).
_LANG_BY_EXT = {}
for _fam, _exts in {
    "java": "java kt kts scala groovy gradle",
    "js": "js jsx mjs cjs ts tsx mts cts vue svelte",
    "py": "py pyi pyw",
    "go": "go",
    "cs": "cs",
    "c": "c h cc cpp cxx hpp hh hxx ino m mm",
    "rs": "rs",
    "php": "php phtml",
    "rb": "rb rake gemspec",
    "sql": "sql ddl pks pkb",
}.items():
    for _e in _exts.split():
        _LANG_BY_EXT["." + _e] = _fam

# words that make "<word> name(" a use, not a declaration
_NOT_DECL_BEFORE = frozenset("""return new throw throws await yield else case goto in of typeof delete
echo print not and or is as sizeof instanceof await do raise assert del lambda if while for switch
catch using import from package include require""".split())

_MOD_JAVA = r"(?:(?:public|private|protected|internal|static|final|abstract|sealed|open|data|inner|enum|annotation|value|companion|override|suspend|inline|synchronized|native|default|strictfp|transient|volatile|const|lateinit|external|operator|infix|tailrec|virtual|async|partial|readonly|unsafe|extern|new|explicit|implicit)\s+)*"
_ANNOT = r"(?:@[\w.]+(?:\([^)]*\))?\s+)*"


def _decl_rules(fam, name):
    """[(kind, compiled pattern)] for one language family. `kind` drives
    ranking: type > function > field."""
    n = re.escape(name)
    T = r"\w[\w.<>\[\],?\s*&:]*?"  # a type before the name (Java/C#/C), starts with a word char
    rules = {
        "java": [
            ("type", rf"^\s*{_ANNOT}{_MOD_JAVA}(?:class|interface|enum|record|object|trait|@interface|typealias)\s+{n}\b"),
            ("function", rf"\bfun\s+(?:<[^>]*>\s*)?(?:[\w.]+\.)?{n}\s*[(<]"),
            ("function", rf"^\s*{_ANNOT}{_MOD_JAVA}(?:<[^>]+>\s+)?{T}\s+{n}\s*\("),
            ("function", rf"^\s*{_ANNOT}(?:public|private|protected)\s+{n}\s*\("),  # constructor
            ("field", rf"^\s*{_ANNOT}{_MOD_JAVA}(?:val|var)\s+{n}\b"),
            ("field", rf"^\s*{_ANNOT}(?:(?:public|private|protected|static|final|volatile|transient)\s+)+{T}\s+{n}\s*(?:=|;|$)"),
            # enum constant (FOO, / FOO(1);) — constant-style names only, so a
            # bare call statement `foo(x);` is not taken for one
            ("field", rf"^\s*{n}\s*(?:\([^)]*\))?\s*[,;{{]\s*(?://.*)?$" if re.match(r"^[A-Z][A-Z0-9_]*$", name) else r"(?!)"),
        ],
        "js": [
            ("type", rf"^\s*(?:export\s+)?(?:default\s+)?(?:declare\s+)?(?:abstract\s+)?(?:class|interface|type|enum|namespace|module)\s+{n}\b"),
            ("function", rf"^\s*(?:export\s+)?(?:default\s+)?(?:declare\s+)?(?:async\s+)?function\s*\*?\s*{n}\s*[(<]"),
            ("function", rf"^\s*(?:export\s+)?(?:const|let|var)\s+{n}\s*(?::[^=]+)?=\s*(?:async\s*)?(?:function\b|\([^)]*\)\s*(?::[^=]+)?=>|\w+\s*=>)"),
            ("function", rf"^\s*(?:(?:public|private|protected|static|async|readonly|get|set|override|abstract|declare)\s+)*\*?{n}\s*(?:<[^>]*>)?\s*\([^)]*\)\s*(?::\s*[^={{;]+)?\s*\{{"),
            ("field", rf"^\s*(?:export\s+)?(?:declare\s+)?(?:const|let|var)\s+{n}\b"),
            ("field", rf"^\s*(?:(?:public|private|protected|static|readonly|declare|override)\s+)+{n}\s*[?!]?\s*[:=;]"),
        ],
        "py": [
            ("type", rf"^\s*class\s+{n}\b"),
            ("function", rf"^\s*(?:async\s+)?def\s+{n}\s*[(\[]"),
            ("field", rf"^{n}\s*(?::[^=]+)?=(?!=)"),
            ("field", rf"^\s+self\.{n}\s*(?::[^=]+)?=(?!=)"),
        ],
        "go": [
            ("type", rf"^\s*type\s+{n}\b"),
            ("type", rf"^\s+{n}\s+(?:struct|interface)\b"),  # inside a type ( ... ) block
            ("function", rf"^\s*func\s+(?:\([^)]*\)\s*)?{n}\s*[(\[]"),
            ("field", rf"^\s*(?:var|const)\s+{n}\b"),
            ("field", rf"^\s+{n}\s+[\w\[\]*.]+\s*(?:=|`|//|$)"),  # var/const block entry, struct field
        ],
        "cs": [
            ("type", rf"^\s*{_ANNOT}(?:\[[^\]]*\]\s*)*{_MOD_JAVA}(?:class|interface|struct|enum|record(?:\s+(?:class|struct))?|delegate\s+{T})\s+{n}\b"),
            ("function", rf"^\s*(?:\[[^\]]*\]\s*)*{_MOD_JAVA}(?:<[^>]+>\s+)?{T}\s+{n}\s*(?:<[^>]*>)?\s*\("),
            ("function", rf"^\s*(?:public|private|protected|internal)\s+{n}\s*\("),
            ("field", rf"^\s*(?:\[[^\]]*\]\s*)*(?:(?:public|private|protected|internal|static|readonly|const|volatile|override|virtual|abstract|new|required)\s+)+{T}\s+{n}\s*(?:=|;|\{{|=>|$)"),
        ],
        "c": [
            ("type", rf"^\s*(?:typedef\s+)?(?:template\s*<[^>]*>\s*)?(?:struct|class|union|enum(?:\s+class)?)\s+(?:\w+\s+)*{n}\b(?![^;{{]*;\s*$)"),
            ("type", rf"\btypedef\b.*\b{n}\s*;"),
            ("type", rf"^\s*using\s+{n}\s*="),
            ("function", rf"^\s*#\s*define\s+{n}\b"),
            ("function", rf"^(?!\s*(?:return|else|case|if|while|for|switch|do)\b)\s*(?:[\w\*&:<>,~]+\s+)+[\*&]*(?:\w+::)*~?{n}\s*\([^;]*$"),
            ("field", rf"^\s*(?:(?:static|extern|const|constexpr|inline|volatile|unsigned|signed)\s+)*[\w:<>]+[\s\*&]+{n}\s*(?:\[[^\]]*\])?\s*(?:=|;)"),
        ],
        "rs": [
            ("function", rf"^\s*(?:pub(?:\([^)]*\))?\s+)?(?:default\s+)?(?:const\s+)?(?:async\s+)?(?:unsafe\s+)?(?:extern\s+\"\w+\"\s+)?fn\s+{n}\b"),
            ("type", rf"^\s*(?:pub(?:\([^)]*\))?\s+)?(?:struct|enum|trait|type|union|mod)\s+{n}\b"),
            ("type", rf"^\s*impl(?:<[^>]*>)?\s+(?:[\w:<>]+\s+for\s+)?{n}\b"),
            ("function", rf"^\s*macro_rules!\s*{n}\b"),
            ("field", rf"^\s*(?:pub(?:\([^)]*\))?\s+)?(?:const|static)\s+(?:mut\s+)?{n}\b"),
        ],
        "php": [
            ("type", rf"^\s*(?:abstract\s+|final\s+|readonly\s+)*(?:class|interface|trait|enum)\s+{n}\b"),
            ("function", rf"\bfunction\s+&?{n}\s*\("),
            ("field", rf"^\s*(?:(?:public|private|protected|static|readonly|var|final)\s+)+(?:const\s+)?(?:\??[\w\\]+\s+)?\$?{n}\b"),
            ("field", rf"^\s*const\s+{n}\b"),
        ],
        "rb": [
            ("type", rf"^\s*(?:class|module)\s+(?:[\w:]+::)?{n}\b"),
            ("function", rf"^\s*def\s+(?:self\.)?{n}\b"),
            ("field", rf"^\s*(?:attr_(?:reader|writer|accessor)\b.*:{n}\b|{n}\s*=(?!=))"),
        ],
        "sql": [
            ("type", rf"(?i)\bcreate\s+(?:or\s+replace\s+)?(?:temp(?:orary)?\s+)?(?:table|view|materialized\s+view|type|sequence|index|unique\s+index|schema)\s+(?:if\s+not\s+exists\s+)?(?:[\w\"`\[\]]+\.)?[\"`\[]?{n}\b"),
            ("function", rf"(?i)\bcreate\s+(?:or\s+replace\s+)?(?:definer\s*=\s*\S+\s+)?(?:function|procedure|trigger|package(?:\s+body)?)\s+(?:[\w\"`\[\]]+\.)?[\"`\[]?{n}\b"),
        ],
    }.get(fam)
    if rules is None:  # unknown language: keyword + name
        rules = [("type", rf"^\s*(?:export\s+)?(?:(?:public|private|abstract|static)\s+)*(?:class|interface|enum|struct|trait|type|module|namespace)\s+{n}\b"),
                 ("function", rf"^\s*(?:export\s+)?(?:(?:public|private|static|async)\s+)*(?:function|def|fn|func|fun|sub|proc|procedure|method)\s+{n}\b")]
    return [(k, re.compile(p)) for k, p in rules]


_rules_cache = OrderedDict()


def _rules_for(fam, name):
    key = (fam, name)
    hit = _rules_cache.get(key)
    if hit is None:
        hit = _decl_rules(fam, name)
        _rules_cache[key] = hit
        if len(_rules_cache) > 400:
            _rules_cache.popitem(last=False)
    return hit


def _lang_family(path):
    return _LANG_BY_EXT.get(os.path.splitext(path)[1].lower())


def _name_col(line, name):
    """1-based column of `name` as a whole word in line (0 if absent)."""
    m = re.search(r"(?<![\w$])" + re.escape(name) + r"(?![\w$])", line)
    return m.start() + 1 if m else 0


def classify_decl(path, line, name):
    """Kind ('type' / 'function' / 'field') if this line declares `name`."""
    fam = _lang_family(path)
    st = line.lstrip()
    if (st.startswith(("//", "/*", "*")) or (st.startswith("--") and fam == "sql")
            or (st.startswith("#") and fam in ("py", "rb"))):
        return None  # comment line
    for kind, pat in _rules_for(fam, name):
        m = pat.search(line)
        if not m:
            continue
        # reject uses that merely look like declarations
        col = _name_col(line, name)
        before = line[:col - 1].rstrip() if col else ""
        if before.endswith((".", "=", "(", ",", "->", "::", "!", "&&", "||", "?", ":")) and kind != "type":
            allowed = ((before.endswith("::") and fam == "c")             # void Foo::bar( (C++)
                       or re.search(r"\bfun\s+[\w.<>]*$", before)         # fun Foo.bar( (Kotlin)
                       or (fam == "py" and before.endswith("self."))      # self.x = (Python)
                       or (fam == "php" and before.endswith("$")))
            if not allowed:
                continue
        prev = re.findall(r"[A-Za-z_]\w*", before)
        if prev and prev[-1] in _NOT_DECL_BEFORE:
            continue
        return kind
    return None


_KIND_SCORE = {"type": 30, "function": 20, "field": 10}


def rank_decls(decls, name, from_path):
    """Sort declaration hits: kind, same file, folder proximity, file named
    after the symbol; test folders slightly last."""
    from_dir = (from_path or "").replace("\\", "/").split("/")[:-1]

    def score(d):
        p = d["path"].replace("\\", "/")
        parts = p.split("/")
        s = _KIND_SCORE.get(d.get("kind"), 0)
        if from_path and p == from_path.replace("\\", "/"):
            s += 15
        common = 0
        for a, b in zip(parts[:-1], from_dir):
            if a != b:
                break
            common += 1
        s += min(common * 2, 12)
        if os.path.splitext(parts[-1])[0] == name:
            s += 20
        if "/test/" in "/" + p.lower() or "/tests/" in "/" + p.lower():
            s -= 3
        return -s
    return sorted(decls, key=score)


GOTO_MAX_DECL = 200     # declarations kept
GOTO_MAX_PLAIN = 50     # plain occurrences kept (returned when no declaration is found)
GOTO_SCAN_CAP = 5000    # occurrences examined before giving up (rg path)
REFS_MAX = 500          # references returned


def _word_hits_rg(symbol, scope_root, base, kind, gen, cap):
    """(path, line_no, text) for whole-word, case-sensitive occurrences via
    rg; None if rg is unavailable or failed."""
    rg = _rg_path()
    if not rg:
        return None
    args = [rg] + _rg_common_args("") + ["--max-count", "200", "-w", "-F", "-s", "-e", symbol, scope_root]
    out, exit_code = [], None
    events = _rg_events(args, kind, gen)
    for obj in events:
        t = obj.get("type")
        if t == "match":
            d = obj["data"]
            try:
                rel = os.path.relpath(_rg_decode(d.get("path"))[0], base).replace("\\", "/")
            except ValueError:
                continue
            out.append((rel, d.get("line_number", 0), _rg_decode(d.get("lines"))[0].rstrip("\r\n")))
            if len(out) >= cap:
                exit_code = 0
                break
        elif t == "_exit":
            exit_code = obj["code"]
    events.close()  # kills rg if we stopped early
    if exit_code == "stale":
        return []
    if exit_code not in (0, 1):
        return None
    return out


def _word_hits_one_file(args):
    full, rel, symbol, word_pat, kind, gen = args
    if _is_stale(kind, gen):
        return None
    text = _get_content(full)
    if text is None or symbol not in text or not word_pat.search(text):
        return None
    out = []
    for i, line in enumerate(text.splitlines()):
        if word_pat.search(line):
            out.append((rel, i + 1, line))
            if len(out) >= 200:
                break
    return out


def _word_hits(symbol, scope_root, base, kind, gen, cap):
    hits = _word_hits_rg(symbol, scope_root, base, kind, gen, cap)
    if hits is not None:
        return hits
    word_pat = re.compile(r"(?<![\w$])" + re.escape(symbol) + r"(?![\w$])")
    tasks = [(full, rel, symbol, word_pat, kind, gen) for rel, full in _scoped_index(base, scope_root)]
    out = []
    it = _SEARCH_EXECUTOR.map(_word_hits_one_file, tasks, chunksize=8)
    try:
        for batch in it:
            if _is_stale(kind, gen):
                break
            out.extend(batch or ())
            if len(out) >= cap:
                break
    finally:
        it.close()
    return out[:cap]


def _scope_and_base(scope):
    base = base_root()
    if base is None:
        return None, None
    scope_root = _safe_join(base, scope) if scope else base
    if not scope_root or not os.path.isdir(scope_root):
        return None, None
    return base, scope_root


def goto_symbol(symbol: str, scope: str = "", from_path: str = "", index_only: bool = False):
    """Probable declarations of `symbol`, best first. Uses the ctags symbol
    index when it is ready, else word hits + declaration patterns. With no
    declaration found, plain occurrences are returned (declarations == 0).
    index_only: never search (hover links ask for every word they touch)."""
    if not symbol or len(symbol) < 2 or not re.match(r"^[\w$]+$", symbol):
        return {"results": [], "declarations": 0, "total": 0}
    base, scope_root = _scope_and_base(scope)
    if base is None:
        return {"results": [], "declarations": 0, "total": 0}
    tagged = ctags_lookup(symbol, scope_root, base)
    if tagged:
        ranked = rank_decls(tagged, symbol, from_path)[:GOTO_MAX_DECL]
        return {"results": ranked, "declarations": len(ranked), "total": len(ranked), "source": "ctags"}
    if index_only:
        return {"results": [], "declarations": 0, "total": 0, "source": "none" if tagged is None else "ctags"}
    gen = _new_gen("goto")
    hits = _word_hits(symbol, scope_root, base, "goto", gen, GOTO_SCAN_CAP)
    decls, plain = [], []
    for rel, ln, line in hits:
        entry = {"path": rel, "line": ln, "col": _name_col(line, symbol), "text": _clip(line.rstrip())[0]}
        kind = classify_decl(rel, line, symbol)
        if kind:
            entry["kind"] = kind
            decls.append(entry)
        elif len(plain) < GOTO_MAX_PLAIN:
            plain.append(entry)
    decls = rank_decls(decls, symbol, from_path)[:GOTO_MAX_DECL]
    return {"results": decls if decls else plain, "declarations": len(decls),
            "total": len(hits), "source": "search"}


def find_references(symbol: str, scope: str = "", from_path: str = ""):
    """Whole-word, case-sensitive occurrences (declarations flagged), the
    current file first, then nearby folders."""
    if not symbol or not re.match(r"^[\w$]+$", symbol):
        return {"results": [], "total": 0}
    base, scope_root = _scope_and_base(scope)
    if base is None:
        return {"results": [], "total": 0}
    gen = _new_gen("refs")
    hits = _word_hits(symbol, scope_root, base, "refs", gen, REFS_MAX + 1)
    out = []
    for rel, ln, line in hits[:REFS_MAX]:
        out.append({"path": rel, "line": ln, "col": _name_col(line, symbol),
                    "text": _clip(line.rstrip())[0], "decl": bool(classify_decl(rel, line, symbol))})
    from_dir = (from_path or "").split("/")[:-1]

    def near(r):
        parts = r["path"].split("/")
        common = 0
        for a, b in zip(parts[:-1], from_dir):
            if a != b:
                break
            common += 1
        return (r["path"] != from_path, -common, r["path"], r["line"])
    out.sort(key=near)
    return {"results": out, "total": len(out), "truncated": len(hits) > REFS_MAX}


# ----- component tags (Vue / JSX / Svelte / Astro): <ItemTop> -> ItemTop.vue -----
# Order: (a) the file's own imports — relative paths, tsconfig/jsconfig
# "paths", vite aliases, else "@/" "~/" guessed as the project's src/ — then
# (b) file names in the folder index (ItemTop.vue, item-top.vue,
# ItemTop/index.vue, Nuxt components/<dir>/Name.vue), nearest first.
# Only files inside the working folder are returned.
COMPONENT_EXTS = (".vue", ".tsx", ".jsx", ".svelte", ".astro", ".ts", ".js", ".mjs")
_COMPONENT_FILE_EXTS = frozenset((".vue", ".tsx", ".jsx", ".svelte", ".astro"))
_IMPORT_DEFAULT = re.compile(r"""import\s+(?:type\s+)?([A-Za-z_$][\w$]*)\s*(?:,\s*\{[^}]*\})?\s*from\s*['"]([^'"]+)['"]""")
_IMPORT_NAMED = re.compile(r"""import\s*(?:type\s*)?\{([^}]*)\}\s*from\s*['"]([^'"]+)['"]""")
_IMPORT_ASYNC = re.compile(r"""([A-Za-z_$][\w$]*)\s*[:=]\s*(?:defineAsyncComponent\(\s*)?(?:\(\s*\)|async\s*\(\s*\))\s*=>\s*import\(\s*['"]([^'"]+)['"]""")
_REEXPORT = re.compile(r"""export\s*\{([^}]*)\}\s*from\s*['"]([^'"]+)['"]""")


def _norm_name(name):
    """ItemTop / item-top / itemTop -> 'itemtop' (for comparing)."""
    return re.sub(r"[-_.]", "", name).lower()


def _component_imports(text):
    """{localName: module spec} from a component file's script."""
    out = {}
    for m in _IMPORT_DEFAULT.finditer(text):
        out.setdefault(m.group(1), m.group(2))
    for m in _IMPORT_NAMED.finditer(text):
        for part in m.group(1).split(","):
            bits = part.strip().split()
            if bits:
                out.setdefault(bits[-1], m.group(2))  # "A as B" -> B
    for m in _IMPORT_ASYNC.finditer(text):
        out.setdefault(m.group(1), m.group(2))
    return out


def _strip_json_comments(text):
    text = re.sub(r"(?m)^\s*//.*$", "", text)
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return re.sub(r",(\s*[}\]])", r"\1", text)


def _read_small(full, limit=512_000):
    try:
        if os.path.getsize(full) > limit:
            return None
        with open(full, "rb") as f:
            return _decode(f.read())[0]
    except OSError:
        return None


def _project_roots(full, base):
    """Folders from the file up to base_dir that look like a JS project root."""
    out, d = [], os.path.dirname(full)
    while _within(d, base):
        if any(os.path.isfile(os.path.join(d, n)) for n in
               ("package.json", "tsconfig.json", "jsconfig.json", "vite.config.ts", "vite.config.js")):
            out.append(d)
        if _norm(d) == _norm(base):
            break
        d = os.path.dirname(d)
    return out or [os.path.dirname(full)]


def _tsconfig_aliases(root, depth=0):
    """[(prefix, [target dirs])] from tsconfig/jsconfig paths (+ one extends)."""
    out = []
    for name in ("tsconfig.json", "jsconfig.json", "tsconfig.app.json"):
        p = os.path.join(root, name)
        text = _read_small(p)
        if text is None:
            continue
        try:
            cfg = json.loads(_strip_json_comments(text))
        except ValueError:
            continue
        co = cfg.get("compilerOptions") or {}
        base_url = os.path.join(root, co.get("baseUrl") or ".")
        for key, targets in (co.get("paths") or {}).items():
            prefix = key[:-1] if key.endswith("*") else key
            dirs = [os.path.normpath(os.path.join(base_url, t[:-1] if t.endswith("*") else t))
                    for t in targets if isinstance(t, str)]
            out.append((prefix, dirs))
        ext = cfg.get("extends")
        if isinstance(ext, str) and ext.startswith(".") and depth < 2:
            out += _tsconfig_aliases(os.path.dirname(os.path.normpath(os.path.join(root, ext))), depth + 1)
    return out


_VITE_ALIAS = re.compile(
    r"""['"]?([@~$\w/-]+)['"]?\s*:\s*(?:fileURLToPath\(\s*new\s+URL\(\s*['"]([^'"]+)['"]"""
    r"""|(?:path\.)?resolve\(\s*__dirname\s*,\s*['"]([^'"]+)['"]"""
    r"""|(?:path\.)?join\(\s*__dirname\s*,\s*['"]([^'"]+)['"])""")
_VITE_FIND = re.compile(
    r"""find\s*:\s*['"]([^'"]+)['"]\s*,\s*replacement\s*:\s*(?:fileURLToPath\(\s*new\s+URL\(\s*)?(?:(?:path\.)?resolve\(\s*__dirname\s*,\s*)?['"]([^'"]+)['"]""")


def _vite_aliases(root):
    out = []
    for name in ("vite.config.ts", "vite.config.js", "vite.config.mjs", "vite.config.mts", "vue.config.js"):
        text = _read_small(os.path.join(root, name))
        if text is None:
            continue
        for m in _VITE_ALIAS.finditer(text):
            target = next(g for g in m.groups()[1:] if g)
            out.append((m.group(1), [os.path.normpath(os.path.join(root, target))]))
        for m in _VITE_FIND.finditer(text):
            out.append((m.group(1), [os.path.normpath(os.path.join(root, m.group(2)))]))
    return out


def _try_module_file(path):
    """A module path as written in an import -> an existing file, or None."""
    cands = [path] if os.path.splitext(path)[1].lower() in COMPONENT_EXTS else []
    cands += [path + e for e in COMPONENT_EXTS]
    cands += [os.path.join(path, "index" + e) for e in COMPONENT_EXTS]
    for c in cands:
        if os.path.isfile(c):
            return c
    return None


def _resolve_spec(spec, from_full, base):
    """Import spec -> absolute file inside base, or None. Packages are skipped."""
    tries = []
    if spec.startswith("."):
        tries.append(os.path.normpath(os.path.join(os.path.dirname(from_full), spec)))
    else:
        roots = _project_roots(from_full, base)
        for root in roots:
            for prefix, dirs in _tsconfig_aliases(root) + _vite_aliases(root):
                p = prefix.rstrip("/")
                if spec == p or spec.startswith(p + "/"):
                    rest = spec[len(p):].lstrip("/")
                    tries += [os.path.normpath(os.path.join(d, rest)) for d in dirs]
        m = re.match(r"^(?:~@|@|~)/(.*)$", spec)
        if m:  # conventional aliases: src/ (Vue CLI, Vite), project root / app/ (Nuxt)
            for root in roots:
                tries += [os.path.join(root, d, m.group(1)) for d in ("src", "", "app")]
    for t in tries:
        f = _try_module_file(t)
        if f:
            real = os.path.realpath(f)
            if _within(real, base):
                return real
    return None


def _follow_barrel(full, name, base, depth=0):
    """import { ItemTop } from './components' -> the file index.ts re-exports."""
    if os.path.splitext(full)[1].lower() in _COMPONENT_FILE_EXTS or depth > 2:
        return full
    text = _read_small(full) or ""
    for m in _REEXPORT.finditer(text):
        for part in m.group(1).split(","):
            bits = part.strip().split()
            if bits and bits[-1] == name:
                nxt = _resolve_spec(m.group(2), full, base)
                if nxt:
                    return _follow_barrel(nxt, name, base, depth + 1)
    return full


def _nuxt_names(rel):
    """Names Nuxt auto-registers for a file under components/:
    components/base/foo/Button.vue -> BaseFooButton (prefix not repeated)."""
    parts = rel.split("/")
    if "components" not in parts[:-1]:
        return ()
    i = len(parts) - 1 - parts[::-1].index("components")
    dirs, stem = parts[i + 1:-1], os.path.splitext(parts[-1])[0]
    if stem.lower() == "index" and dirs:
        stem, dirs = dirs[-1], dirs[:-1]
    words = [w for d in dirs for w in re.split(r"[-_]", d) if w]
    sw = [w for w in re.split(r"(?<=[a-z0-9])(?=[A-Z])|[-_]", stem) if w]
    short = "".join(sw)
    out = {_norm_name("".join(words) + short)}
    # Nuxt does not repeat dir words the file name already starts with:
    # components/base/BaseButton.vue -> BaseButton (not BaseBaseButton)
    for n in range(1, len(words) + 1):
        if [w.lower() for w in sw[:n]] == [w.lower() for w in words[-n:]]:
            out.add(_norm_name("".join(words[:-n]) + short))
    return out


def find_component(name, from_key=""):
    """Candidate files for a component tag, best first."""
    base = base_root()
    if base is None or not re.match(r"^[A-Za-z][\w.-]*$", name or ""):
        return {"results": [], "name": name}
    key = _norm_name(name.split(".")[0])
    pascal = "".join(w[:1].upper() + w[1:] for w in re.split(r"[-_]", name.split(".")[0]) if w)
    from_full = resolve_read_path(from_key) if from_key else None
    results, seen = [], set()

    def add(full, how):
        try:
            rel = os.path.relpath(full, base).replace("\\", "/")
        except ValueError:
            return
        if rel not in seen and _within(full, base):
            seen.add(rel)
            results.append({"path": rel, "line": 1, "col": 1, "how": how})

    # (a) imports of the current file
    if from_full and os.path.isfile(from_full):
        text = _get_content(from_full) or ""
        for local, spec in _component_imports(text).items():
            if _norm_name(local) == key or local == pascal:
                hit = _resolve_spec(spec, from_full, base)
                if hit:
                    add(_follow_barrel(hit, local, base), "import")
    if results:
        return {"results": results, "name": name}
    # (b) file names in the folder
    from_rel = os.path.relpath(from_full, base).replace("\\", "/") if from_full and _within(from_full, base) else ""
    cands = []
    for rel in _ensure_index():
        stem, ext = os.path.splitext(rel.rsplit("/", 1)[-1])
        if ext.lower() not in _COMPONENT_FILE_EXTS:
            continue
        how = None
        if _norm_name(stem) == key:
            how = "name"
        elif stem.lower() == "index" and "/" in rel and _norm_name(rel.split("/")[-2]) == key:
            how = "folder"
        elif key in _nuxt_names(rel):
            how = "nuxt"
        if how:
            cands.append((rel, how))
    from_parts = from_rel.split("/")[:-1]

    def near(c):
        parts = c[0].split("/")
        common = 0
        for a, b in zip(parts[:-1], from_parts):
            if a != b:
                break
            common += 1
        return (-common, {"name": 0, "folder": 1, "nuxt": 2}[c[1]], len(parts), c[0])
    for rel, how in sorted(cands, key=near)[:30]:
        add(os.path.join(base, rel.replace("/", os.sep)), how)
    return {"results": results, "name": name}


# ----- links: import paths, includes and imported names -> file + position -----
# link_at() looks at one spot of an editor buffer (the page sends the buffer,
# so unsaved edits count) and says what it points at:
#   kind "path"     an import / include / require / src= path   -> the file(s)
#   kind "symbol"   a name brought in by an import (or obj.member of one)
#                   -> the file and the exported / declared position
#   kind "external" a package or system header that is not in the folder
#   kind "missing"  looks like a link but nothing matches
#   kind "none"     not a link: the page falls back to the symbol index
# Everything is computed on demand (hover / click); config files (tsconfig,
# vite, package.json, composer.json, go.mod, Cargo.toml) are read through the
# mtime-checked content cache and their parsed aliases are cached per folder.
JS_MODULE_EXTS = (".ts", ".tsx", ".d.ts", ".js", ".jsx", ".mjs", ".cjs", ".mts", ".cts",
                  ".vue", ".svelte", ".astro", ".json")
_JS_FAMILY = frozenset((".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".mts", ".cts", ".vue", ".svelte",
                        ".astro", ".mdx"))
_CSS_FAMILY = frozenset((".css", ".scss", ".sass", ".less", ".styl"))
_MARKUP_FAMILY = frozenset((".html", ".htm", ".xhtml", ".jsp", ".php", ".erb", ".hbs", ".njk", ".twig"))
_JVM_EXTS = (".java", ".kt", ".kts", ".scala", ".groovy")
_C_FAMILY = frozenset((".c", ".h", ".cc", ".cpp", ".cxx", ".hpp", ".hh", ".hxx", ".m", ".mm", ".ino"))
_STRING_RE = re.compile(r"""(['"`])((?:\\.|(?!\1).)*)\1""")
_IDENT_RE = re.compile(r"[A-Za-z_$][\w$]*")
_alias_cache = {}  # project root -> (config mtimes, [(prefix, [dirs])])


def _mtime(full):
    try:
        return os.stat(full).st_mtime_ns
    except OSError:
        return None


def _pkg_imports(root):
    """package.json "imports" (#name/*) as aliases."""
    text = _read_small(os.path.join(root, "package.json"))
    if not text:
        return []
    try:
        imp = (json.loads(text) or {}).get("imports") or {}
    except ValueError:
        return []
    out = []
    for key, target in imp.items():
        if isinstance(target, dict):
            target = target.get("default") or target.get("import") or next((v for v in target.values() if isinstance(v, str)), None)
        if not isinstance(target, str):
            continue
        prefix = key[:-1] if key.endswith("*") else key
        t = target[:-1] if target.endswith("*") else target
        out.append((prefix, [os.path.normpath(os.path.join(root, t))]))
    return out


_ALIAS_FILES = ("tsconfig.json", "jsconfig.json", "tsconfig.app.json", "vite.config.ts", "vite.config.js",
                "vite.config.mjs", "vite.config.mts", "vue.config.js", "package.json")


def _aliases_for(root):
    """tsconfig / jsconfig paths + vite aliases + package.json imports, cached
    until one of those files changes."""
    sig = tuple(_mtime(os.path.join(root, n)) for n in _ALIAS_FILES)
    hit = _alias_cache.get(root)
    if hit and hit[0] == sig:
        return hit[1]
    aliases = _tsconfig_aliases(root) + _vite_aliases(root) + _pkg_imports(root)
    aliases.sort(key=lambda a: -len(a[0]))  # longest prefix first
    if len(_alias_cache) > 200:
        _alias_cache.clear()
    _alias_cache[root] = (sig, aliases)
    return aliases


def _try_file(path, exts):
    """path as written (any extension) or with one of exts, or path/index.*"""
    if os.path.isfile(path):
        return path
    for e in exts:
        if os.path.isfile(path + e):
            return path + e
    for e in exts:
        c = os.path.join(path, "index" + e)
        if os.path.isfile(c):
            return c
    return None


def _rel_key(full, base):
    return os.path.relpath(full, base).replace("\\", "/")


def _inside(full, base):
    if not full:
        return None
    real = os.path.realpath(full)
    return real if _within(real, base) else None


def resolve_js_spec(spec, from_full, base):
    """JS/TS/CSS module spec -> (file or None, is_package)."""
    spec = spec.split("?")[0].split("#")[0] if not spec.startswith("#") else spec
    if not spec:
        return None, False
    tries = []
    if spec.startswith((".", "/")):
        if spec.startswith("/"):  # root-relative (markup / vite public): project roots
            tries += [os.path.join(r, spec.lstrip("/")) for r in _project_roots(from_full, base)]
            tries += [os.path.join(r, "public", spec.lstrip("/")) for r in _project_roots(from_full, base)]
        else:
            tries.append(os.path.normpath(os.path.join(os.path.dirname(from_full), spec)))
    else:
        roots = _project_roots(from_full, base)
        for root in roots:
            for prefix, dirs in _aliases_for(root):
                p = prefix.rstrip("/")
                if p and (spec == p or spec.startswith(p + "/")):
                    rest = spec[len(p):].lstrip("/")
                    tries += [os.path.normpath(os.path.join(d, rest)) for d in dirs]
        m = re.match(r"^(?:~@|@|~)/(.*)$", spec)
        if m:  # conventional aliases: src/ (Vue CLI, Vite), project root / app/ (Nuxt)
            for root in roots:
                tries += [os.path.join(root, d, m.group(1)) for d in ("src", "", "app")]
        if spec.startswith("~") and not m:  # sass / webpack: ~pkg/...
            return None, True
        if not tries:  # bare spec: a sibling written without ./ (CSS, markup), a baseUrl path, else a package
            for t in [os.path.join(os.path.dirname(from_full), spec)] + [os.path.join(r, d, spec) for r in roots for d in ("", "src")]:
                f = _inside(_try_file(os.path.normpath(t), JS_MODULE_EXTS), base)
                if f:
                    return f, False
            return None, True
    for t in tries:
        f = _inside(_try_file(t, JS_MODULE_EXTS), base)
        if f:
            return f, False
    m = re.match(r"^(?:~@|@|~|#)/(.+)$", spec)
    if m:  # no config defines the alias (or the project root is elsewhere): match the path itself
        f = _alias_fallback(m.group(1), from_full, base)
        if f:
            return f, False
    return None, False


def _alias_fallback(rest, from_full, base):
    """`@/main/page/X.vue` with no alias config: a file under the working folder
    whose path ends with main/page/X.vue (extension / index.* may be left out),
    else one with the same file name — nearest to the importing file first."""
    from_rel = _rel_key(from_full, base) if _within(from_full, base) else ""
    rest = rest.strip("/")
    has_ext = os.path.splitext(rest)[1].lower() in JS_MODULE_EXTS or "." in rest.rsplit("/", 1)[-1]

    def variants(tail):
        if has_ext:
            return ["/" + tail]
        return ["/" + tail + e for e in JS_MODULE_EXTS] + ["/" + tail + "/index" + e for e in JS_MODULE_EXTS]
    for tail in (rest, rest.rsplit("/", 1)[-1]):
        hits = _index_files_ending(variants(tail), base, from_rel, 1)
        if hits:
            return _inside(os.path.join(base, hits[0].replace("/", os.sep)), base)
    return None


def _line_col(text, idx):
    line = text.count("\n", 0, idx) + 1
    return line, idx - (text.rfind("\n", 0, idx) + 1) + 1


def _js_imports(text):
    """{local: (spec, imported)} — imported is a name, 'default' or '*'."""
    out = {}
    for m in re.finditer(r"""\bimport\s+(?:type\s+)?([^'";]*?)\s*from\s*['"]([^'"]+)['"]""", text):
        clause, spec = m.group(1), m.group(2)
        named = re.search(r"\{([^}]*)\}", clause, re.S)
        if named:
            for part in named.group(1).split(","):
                bits = part.replace("type ", "").strip().split()
                if not bits:
                    continue
                if len(bits) == 3 and bits[1] == "as":
                    out.setdefault(bits[2], (spec, bits[0]))
                else:
                    out.setdefault(bits[0], (spec, bits[0]))
            clause = clause[:named.start()] + clause[named.end():]
        ns = re.search(r"\*\s*as\s+([A-Za-z_$][\w$]*)", clause)
        if ns:
            out.setdefault(ns.group(1), (spec, "*"))
            clause = clause[:ns.start()] + clause[ns.end():]
        d = re.match(r"\s*([A-Za-z_$][\w$]*)", clause)
        if d:
            out.setdefault(d.group(1), (spec, "default"))
    for m in re.finditer(r"""\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*require\(\s*['"]([^'"]+)['"]\s*\)""", text):
        out.setdefault(m.group(1), (m.group(2), "*"))
    for m in re.finditer(r"""\b(?:const|let|var)\s*\{([^}]*)\}\s*=\s*require\(\s*['"]([^'"]+)['"]\s*\)""", text):
        for part in m.group(1).split(","):
            bits = [b.strip() for b in part.split(":")]
            if bits[0]:
                out.setdefault(bits[-1], (m.group(2), bits[0]))
    return out


_JS_DECL = r"(?:export\s+)?(?:declare\s+)?(?:default\s+)?(?:abstract\s+)?(?:async\s+)?(?:function\s*\*?|class|const|let|var|interface|type|enum|namespace)\s+"


def _decl_pos(text, pattern, name, flags=re.M):
    m = re.search(pattern, text, flags)
    if not m:
        return None
    i = text.find(name, m.start()) if name else m.start()
    return _line_col(text, i if i >= 0 else m.start())


def _find_js_export(full, name, base, depth=0):
    """(file, line, col) of the export `name` ('default' / '*') in a module,
    following re-exports up to three files deep."""
    text = _get_content(full) or ""
    if name == "*" or not text:
        return full, 1, 1
    if name == "default":
        m = re.search(r"^\s*export\s+default\b", text, re.M)
        if m:
            return (full,) + _line_col(text, m.start() + (len(m.group(0)) - len(m.group(0).lstrip())))
        return full, 1, 1  # a .vue / .svelte component: its top
    n = re.escape(name)
    pos = _decl_pos(text, r"^\s*export\s+" + _JS_DECL[len("(?:export\\s+)?"):] + n + r"\b", name)
    if pos:
        return (full,) + pos
    for m in re.finditer(r"export\s*\{([^}]*)\}(\s*from\s*['\"]([^'\"]+)['\"])?", text):
        for part in m.group(1).split(","):
            bits = part.replace("type ", "").strip().split()
            if not bits or bits[-1] != name:
                continue
            orig = bits[0]
            if m.group(3):  # export { a as name } from './x'
                if depth < 3:
                    nxt, _ = resolve_js_spec(m.group(3), full, base)
                    if nxt:
                        return _find_js_export(nxt, orig, base, depth + 1)
                return (full,) + _line_col(text, m.start())
            pos = _decl_pos(text, r"^\s*" + _JS_DECL + re.escape(orig) + r"\b", orig)
            return (full,) + (pos or _line_col(text, m.start()))
    m = re.search(r"export\s*\*\s*as\s+" + n + r"\s+from\s*['\"]([^'\"]+)['\"]", text)
    if m:
        nxt, _ = resolve_js_spec(m.group(1), full, base)
        return (nxt, 1, 1) if nxt else (full,) + _line_col(text, m.start())
    if depth < 3:
        for m in re.finditer(r"export\s*\*\s*from\s*['\"]([^'\"]+)['\"]", text):
            nxt, _ = resolve_js_spec(m.group(1), full, base)
            if nxt:
                r = _find_js_export(nxt, name, base, depth + 1)
                if r[1] != 1 or r[2] != 1:
                    return r
    pos = _decl_pos(text, r"^\s*" + _JS_DECL + n + r"\b", name)
    return (full,) + (pos or (1, 1))


# declarations first; a method only when its body opens on the same line (so a
# call like `  getProduct(id)` inside another method is not taken for it)
_MEMBER_PATTERNS = (
    r"\b(?:function|const|let|var|def|class|interface|type|enum|val|struct|trait|fun|fn)\s+{n}\b",
    r"\b{n}\s*:\s*(?:async\s+)?(?:function\b|\(|[A-Za-z_$][\w$]*\s*=>)",
    r"^\s*(?:(?:public|private|protected|static|async|readonly|override|abstract|get|set|final|synchronized|"
    r"native|default|suspend|open|inline|virtual)\s+)*(?:[\w$<>\[\],.?]+\s+)?{n}\s*(?:<[^>]*>)?\s*\([^;\n]*\)"
    r"\s*(?::\s*[^{;\n]+)?\s*(?:throws[^{;\n]+)?\{",
    r"^\s*(?:(?:public|private|protected|static|readonly|declare)\s+)*{n}\s*[?!]?\s*[:=]",
)
_NOT_DECL_LINE = re.compile(r"^\s*(?:return|if|else|while|for|switch|case|throw|await|new|import|from|//|\*|#)\b")


def _find_member(full, name):
    """Line/col of a member (method, property, function) declared in a file."""
    text = _get_content(full) or ""
    for pat in _MEMBER_PATTERNS:
        for m in re.finditer(pat.replace("{n}", re.escape(name)), text, re.M):
            ls = text.rfind("\n", 0, m.start()) + 1
            le = text.find("\n", m.start())
            if _NOT_DECL_LINE.match(text[ls:le if le >= 0 else None]):
                continue
            i = text.find(name, m.start())
            return _line_col(text, i)
    m = re.search(r"\b" + re.escape(name) + r"\b", text)
    return _line_col(text, m.start()) if m else (1, 1)


def _token_at(line_text, col):
    """(kind, value, start, end) at a 1-based column: a quoted string's
    contents, or an identifier (dotted names joined for 'dotted')."""
    i = col - 1
    for m in _STRING_RE.finditer(line_text):
        if m.start() <= i < m.end():
            return "string", m.group(2), m.start(2) + 1, m.end(2) + 1
    for m in re.finditer(r"[A-Za-z_$][\w$]*", line_text):
        if m.start() <= i <= m.end() and (i < m.end() or i == m.end() and i > m.start()):
            return "word", m.group(0), m.start() + 1, m.end() + 1
    return None, None, 0, 0


def _dotted_at(line_text, col):
    """'a.b.C' around the column (for Java / Python / C# names), with the part
    up to the clicked segment."""
    for m in re.finditer(r"[A-Za-z_][\w]*(?:\.[A-Za-z_*][\w]*)*", line_text):
        if m.start() <= col - 1 <= m.end():
            dot = line_text.find(".", col - 1, m.end())
            upto = line_text[m.start():dot if dot >= 0 else m.end()]
            return m.group(0), upto, m.start() + 1, m.end() + 1
    return None, None, 0, 0


def _index_files_ending(suffixes, base, from_rel, limit=20):
    """Index paths ending with one of the suffixes, nearest to from_rel first."""
    suffixes = tuple(s.lower() for s in suffixes)
    hits = [r for r in _ensure_index() if r.lower().endswith(suffixes) or r.lower() in tuple(s.lstrip("/") for s in suffixes)]
    from_parts = from_rel.split("/")[:-1]

    def near(r):
        parts = r.split("/")
        common = 0
        for a, b in zip(parts[:-1], from_parts):
            if a != b:
                break
            common += 1
        return (-common, len(parts), r)
    return sorted(hits, key=near)[:limit]


def _result(full, base, line=1, col=1, how=""):
    return {"path": _rel_key(full, base), "line": line, "col": col, "how": how}


# --- per-language handlers: (text, lines, ln, col, from_full, from_rel, base) -> dict | None ---

def _link_js(ctx):
    text, line_text, col, from_full, base = ctx["text"], ctx["line_text"], ctx["col"], ctx["from_full"], ctx["base"]
    kind, val, s, e = _token_at(line_text, col)
    before = line_text[:s - 2] if kind == "string" else ""
    path_ctx = kind == "string" and re.search(
        r"(?:\bfrom|^\s*import|\bimport\s*\(|\brequire\s*\(|\brequire\.resolve\s*\(|@import(?:\s+url\()?|@use|@forward|"
        r"\burl\(|\b(?:src|href)\s*=|\bimport\s+type)\s*$", before)
    if not path_ctx:  # unquoted CSS url(...)
        for m in re.finditer(r"\burl\(\s*([^'\")\s]+)\s*\)", line_text):
            if m.start(1) <= col - 1 <= m.end(1):
                kind, val, s, e, path_ctx = "string", m.group(1), m.start(1) + 1, m.end(1) + 1, True
    if path_ctx:
        if re.match(r"^(?:[a-z][\w+.-]*:|//|#|data:|\{|\$)", val, re.I) or "{{" in val or "${" in val:
            return None
        f, pkg = resolve_js_spec(val, from_full, base)
        rng = [s, e]
        if f:
            return {"kind": "path", "range": rng, "spec": val, "results": [_result(f, base, how="path")]}
        return {"kind": "external" if pkg else "missing", "range": rng, "spec": val}
    if kind != "word":
        return None
    imports = _js_imports(text)
    owner = re.search(r"([A-Za-z_$][\w$]*)\s*(?:\?\.|\.)\s*$", line_text[:s - 1])
    if owner and owner.group(1) in imports and owner.group(1) != val:  # obj.member of an imported obj
        spec, imported = imports[owner.group(1)]
        f, pkg = resolve_js_spec(spec, from_full, base)
        if not f:
            return {"kind": "external" if pkg else "missing", "range": [s, e], "spec": spec, "name": val}
        if imported not in ("*", "default"):
            f = _find_js_export(f, imported, base)[0]
        ln, c = _find_member(f, val)
        return {"kind": "symbol", "range": [s, e], "spec": spec, "name": val,
                "results": [_result(f, base, ln, c, "member")]}
    if val in imports:
        spec, imported = imports[val]
        f, pkg = resolve_js_spec(spec, from_full, base)
        if not f:
            return {"kind": "external" if pkg else "missing", "range": [s, e], "spec": spec, "name": val}
        f2, ln, c = _find_js_export(f, imported, base)
        return {"kind": "symbol", "range": [s, e], "spec": spec, "name": imported if imported not in ("*", "default") else val,
                "results": [_result(f2, base, ln, c, "import")]}
    return None


def _py_module(mod, from_full, base, from_rel):
    """'a.b' / '.x' / '..' -> module file (a/b.py or a/b/__init__.py)."""
    dots = len(mod) - len(mod.lstrip("."))
    parts = [p for p in mod.lstrip(".").split(".") if p]
    cands = []
    if dots:
        d = os.path.dirname(from_full)
        for _ in range(dots - 1):
            d = os.path.dirname(d)
        cands.append(os.path.join(d, *parts) if parts else d)
    else:
        d = os.path.dirname(from_full)
        while _within(d, base):  # the folder of the file and every parent (source roots)
            cands += [os.path.join(d, *parts), os.path.join(d, "src", *parts)]
            if _norm(d) == _norm(base):
                break
            d = os.path.dirname(d)
    for c in cands:
        for f in (c + ".py", c + ".pyi", os.path.join(c, "__init__.py")):
            if os.path.isfile(f) and _inside(f, base):
                return os.path.realpath(f)
    if parts and not dots:
        tail = "/".join(parts)
        hits = _index_files_ending(["/" + tail + ".py", "/" + tail + "/__init__.py"], base, from_rel, 1)
        if hits:
            return os.path.join(base, hits[0].replace("/", os.sep))
    return None


def _py_name_in(full, name, base, from_rel):
    """A name inside a module: a submodule file, or its def / class / assignment."""
    if os.path.basename(full) == "__init__.py":
        sub = _py_module("." + name, os.path.join(os.path.dirname(full), "x.py"), base, from_rel)
        if sub:
            return sub, 1, 1
    text = _get_content(full) or ""
    pos = _decl_pos(text, r"^\s*(?:async\s+)?def\s+" + re.escape(name) + r"\b|^\s*class\s+" + re.escape(name)
                    + r"\b|^" + re.escape(name) + r"\s*(?::[^=\n]+)?=", name)
    if not pos:  # re-exported: from .x import name
        m = re.search(r"^\s*from\s+(\.[\w.]*)\s+import\s+[^\n]*\b" + re.escape(name) + r"\b", text, re.M)
        if m:
            nxt = _py_module(m.group(1), full, base, from_rel)
            if nxt and nxt != full:
                return _py_name_in(nxt, name, base, from_rel)
    return (full,) + (pos or (1, 1))


def _link_py(ctx):
    text, line_text, col, from_full, base, from_rel = (ctx[k] for k in ("text", "line_text", "col", "from_full", "base", "from_rel"))
    m = re.match(r"^(\s*from\s+)([\w.]+)(\s+import\s+)(.*)$", line_text)
    if m:
        mod_s, mod_e = len(m.group(1)) + 1, len(m.group(1)) + len(m.group(2)) + 1
        f = _py_module(m.group(2), from_full, base, from_rel)
        if mod_s <= col <= mod_e:
            seg_end = line_text.find(".", col - 1, mod_e - 1)
            mod = m.group(2) if seg_end < 0 else line_text[mod_s - 1:seg_end]
            f = _py_module(mod, from_full, base, from_rel) or f
            if f:
                return {"kind": "path", "range": [mod_s, mod_e], "spec": m.group(2), "results": [_result(f, base, how="module")]}
            return {"kind": "external" if not m.group(2).startswith(".") else "missing", "range": [mod_s, mod_e], "spec": m.group(2)}
        kind, val, s, e = _token_at(line_text, col)
        if kind == "word" and s > mod_e and val not in ("import", "as"):
            orig = val
            am = re.search(r"\b([A-Za-z_]\w*)\s+as\s+" + re.escape(val) + r"\b", m.group(4))
            if am:
                orig = am.group(1)
            if not f:
                return {"kind": "external", "range": [s, e], "spec": m.group(2), "name": val}
            f2, ln, c = _py_name_in(f, orig, base, from_rel)
            return {"kind": "symbol", "range": [s, e], "spec": m.group(2), "name": orig, "results": [_result(f2, base, ln, c, "import")]}
        return None
    m = re.match(r"^\s*import\s+(.*)$", line_text)
    if m:
        dotted, upto, s, e = _dotted_at(line_text, col)
        if not dotted or dotted == "import":
            return None
        f = _py_module(upto, from_full, base, from_rel)
        if f:
            return {"kind": "path", "range": [s, e], "spec": dotted, "results": [_result(f, base, how="module")]}
        return {"kind": "external", "range": [s, e], "spec": dotted}
    # usage: name imported with from-import, or module.attr
    kind, val, s, e = _token_at(line_text, col)
    if kind != "word":
        return None
    imports = {}
    for im in re.finditer(r"^\s*from\s+([\w.]+)\s+import\s+\(?([^)\n]*)", text, re.M):
        for part in im.group(2).split(","):
            bits = part.strip().split()
            if bits and bits[0] != "*":
                imports.setdefault(bits[-1], (im.group(1), bits[0]))
    for im in re.finditer(r"^\s*import\s+([\w.]+)(?:\s+as\s+(\w+))?\s*$", text, re.M):
        imports.setdefault(im.group(2) or im.group(1).split(".")[0], (im.group(1), "*"))
    owner = re.search(r"([A-Za-z_]\w*)\.\s*$", line_text[:s - 1])
    if owner and owner.group(1) in imports:
        mod, name = imports[owner.group(1)]
        sub = mod if name == "*" else (mod + name if mod.endswith(".") else mod + "." + name)
        f = _py_module(sub, from_full, base, from_rel) or _py_module(mod, from_full, base, from_rel)
        if f:
            f2, ln, c = _py_name_in(f, val, base, from_rel)
            return {"kind": "symbol", "range": [s, e], "name": val, "results": [_result(f2, base, ln, c, "member")]}
        return {"kind": "external", "range": [s, e], "spec": mod, "name": val}
    if val in imports and imports[val][1] != "*":
        mod, name = imports[val]
        f = _py_module(mod, from_full, base, from_rel)
        if f:
            f2, ln, c = _py_name_in(f, name, base, from_rel)
            return {"kind": "symbol", "range": [s, e], "name": name, "results": [_result(f2, base, ln, c, "import")]}
        return {"kind": "external", "range": [s, e], "spec": mod, "name": val}
    return None


def _jvm_class_files(dotted, base, from_rel):
    """'a.b.C' (maybe 'a.b.C.member') -> [(file, member or None)]"""
    parts = dotted.split(".")
    for n in range(len(parts), 0, -1):
        if not parts[n - 1][:1].isupper():  # class names are capitalised
            continue
        member = parts[n] if n < len(parts) else None
        tail = "/".join(parts[:n])
        hits = _index_files_ending(["/" + tail + e for e in _JVM_EXTS], base, from_rel, 5)
        if hits:
            return [(os.path.join(base, h.replace("/", os.sep)), member) for h in hits]
        # file not in a package-shaped folder: same class name and a matching package line
        pkg = ".".join(parts[:n - 1])
        for h in _index_files_ending(["/" + parts[n - 1] + e for e in _JVM_EXTS], base, from_rel, 20):
            full = os.path.join(base, h.replace("/", os.sep))
            if re.search(r"^\s*package\s+" + re.escape(pkg) + r"\s*;?\s*$", _get_content(full) or "", re.M):
                return [(full, member)]
    return []


def _jvm_type_pos(full, name):
    text = _get_content(full) or ""
    return _decl_pos(text, r"\b(?:class|interface|enum|record|object|@interface|trait)\s+" + re.escape(name) + r"\b", name) or (1, 1)


def _link_jvm(ctx):
    text, line_text, col, from_full, base, from_rel = (ctx[k] for k in ("text", "line_text", "col", "from_full", "base", "from_rel"))
    m = re.match(r"^\s*import\s+(?:static\s+)?([\w.]+(?:\.\*)?)\s*;?", line_text)
    if m:
        dotted, upto, s, e = _dotted_at(line_text, col)
        if not dotted or dotted in ("import", "static"):
            return None
        if dotted.endswith(".*"):  # wildcard: every class in the package
            pkg = dotted[:-2].replace(".", "/")
            hits = [h for h in _ensure_index() if h.rsplit("/", 1)[0].endswith(pkg) and h.endswith(_JVM_EXTS)][:40]
            if hits:
                return {"kind": "path", "range": [s, e], "spec": dotted,
                        "results": [{"path": h, "line": 1, "col": 1, "how": "package"} for h in sorted(hits)]}
            return {"kind": "external", "range": [s, e], "spec": dotted}
        found = _jvm_class_files(dotted, base, from_rel)
        if not found:
            return {"kind": "external", "range": [s, e], "spec": dotted}
        out = []
        for f, member in found:
            name = os.path.splitext(os.path.basename(f))[0]
            ln, c = _find_member(f, member) if member else _jvm_type_pos(f, name)
            out.append(_result(f, base, ln, c, "import"))
        return {"kind": "symbol" if found[0][1] else "path", "range": [s, e], "spec": dotted, "results": out}
    kind, val, s, e = _token_at(line_text, col)
    if kind != "word":
        return None
    owner = re.search(r"([A-Za-z_]\w*)\.\s*$", line_text[:s - 1])
    cls, member = (owner.group(1), val) if owner and owner.group(1)[:1].isupper() else (val, None)
    im = re.search(r"^\s*import\s+([\w.]+\." + re.escape(cls) + r")\s*;?\s*$", text, re.M)
    files = [f for f, _ in _jvm_class_files(im.group(1), base, from_rel)] if im else []
    if not files:  # same package
        same = os.path.join(os.path.dirname(from_full), cls)
        files = [same + e for e in _JVM_EXTS if os.path.isfile(same + e)]
    if not files:
        return None
    f = files[0]
    ln, c = _find_member(f, member) if member else _jvm_type_pos(f, cls)
    return {"kind": "symbol", "range": [s, e], "name": member or cls, "results": [_result(f, base, ln, c, "import")]}


def _go_mod(from_full, base):
    d = os.path.dirname(from_full)
    while _within(d, base):
        t = _read_small(os.path.join(d, "go.mod"))
        if t:
            m = re.search(r"^module\s+(\S+)", t, re.M)
            return (d, m.group(1)) if m else None
        if _norm(d) == _norm(base):
            break
        d = os.path.dirname(d)
    return None


def _go_pkg_files(spec, from_full, base):
    gm = _go_mod(from_full, base)
    if not gm or not (spec == gm[1] or spec.startswith(gm[1] + "/")):
        return []
    d = os.path.join(gm[0], *spec[len(gm[1]):].strip("/").split("/"))
    try:
        names = sorted(n for n in os.listdir(d) if n.endswith(".go") and not n.endswith("_test.go"))
    except OSError:
        return []
    return [os.path.join(d, n) for n in names]


def _link_go(ctx):
    text, lines, ln, line_text, col, from_full, base = (ctx[k] for k in ("text", "lines", "ln", "line_text", "col", "from_full", "base"))
    kind, val, s, e = _token_at(line_text, col)
    in_block = False
    for prev in reversed(lines[:ln - 1]):
        if re.match(r"^\s*\)", prev):
            break
        if re.match(r"^\s*import\s*\(", prev):
            in_block = True
            break
    if kind == "string" and (in_block or re.match(r"^\s*import\b", line_text)):
        files = _go_pkg_files(val, from_full, base)
        if files:
            return {"kind": "path", "range": [s, e], "spec": val, "results": [_result(f, base, how="package") for f in files]}
        return {"kind": "external", "range": [s, e], "spec": val}
    if kind != "word":
        return None
    owner = re.search(r"([A-Za-z_]\w*)\.\s*$", line_text[:s - 1])
    if not owner:
        return None
    for im in re.finditer(r"""^\s*(?:import\s+)?(\w+\s+)?"([^"]+)"\s*$""", text, re.M):
        alias = (im.group(1) or "").strip() or im.group(2).rsplit("/", 1)[-1]
        if alias != owner.group(1):
            continue
        for f in _go_pkg_files(im.group(2), from_full, base):
            t = _get_content(f) or ""
            pos = _decl_pos(t, r"^(?:func\s+(?:\([^)]*\)\s*)?|type\s+|var\s+|const\s+|\s+)" + re.escape(val) + r"\b", val)
            if pos:
                return {"kind": "symbol", "range": [s, e], "name": val, "results": [_result(f, base, pos[0], pos[1], "package")]}
        return {"kind": "external", "range": [s, e], "spec": im.group(2), "name": val}
    return None


def _link_c(ctx):
    line_text, col, from_full, base, from_rel = (ctx[k] for k in ("line_text", "col", "from_full", "base", "from_rel"))
    m = re.match(r"""^\s*#\s*(?:include|import)\s*([<"])([^>"]+)[>"]""", line_text)
    if not m or not (m.start(2) <= col - 1 <= m.end(2)):
        return None
    spec, rng = m.group(2), [m.start(2) + 1, m.end(2) + 1]
    if m.group(1) == '"':
        f = _inside(os.path.normpath(os.path.join(os.path.dirname(from_full), spec)), base)
        if f and os.path.isfile(f):
            return {"kind": "path", "range": rng, "spec": spec, "results": [_result(f, base, how="include")]}
    hits = _index_files_ending(["/" + spec], base, from_rel, 8)
    if hits:
        return {"kind": "path", "range": rng, "spec": spec, "results": [{"path": h, "line": 1, "col": 1, "how": "include"} for h in hits]}
    return {"kind": "external" if m.group(1) == "<" else "missing", "range": rng, "spec": spec}


def _link_php(ctx):
    line_text, col, from_full, base, from_rel = (ctx[k] for k in ("line_text", "col", "from_full", "base", "from_rel"))
    kind, val, s, e = _token_at(line_text, col)
    if kind == "string" and re.search(r"\b(?:require|include)(?:_once)?\b", line_text):
        rel = val.lstrip("/") if "__DIR__" in line_text[:s] else val
        f = _inside(os.path.normpath(os.path.join(os.path.dirname(from_full), rel)), base)
        if f and os.path.isfile(f):
            return {"kind": "path", "range": [s, e], "spec": val, "results": [_result(f, base, how="require")]}
        return {"kind": "missing", "range": [s, e], "spec": val}
    m = re.match(r"^\s*use\s+(?:function\s+|const\s+)?([\w\\]+)", line_text)
    if m and m.start(1) <= col - 1 <= m.end(1):
        name, rng = m.group(1).strip("\\"), [m.start(1) + 1, m.end(1) + 1]
        parts = name.split("\\")
        hits = []
        for root in _project_roots(from_full, base):
            comp = _read_small(os.path.join(root, "composer.json"))
            try:
                psr = ((json.loads(comp) if comp else {}).get("autoload") or {}).get("psr-4") or {}
            except ValueError:
                psr = {}
            for prefix, dirs in psr.items():
                if name.startswith(prefix.rstrip("\\")):
                    rest = name[len(prefix.rstrip("\\")):].strip("\\").split("\\")
                    for d in dirs if isinstance(dirs, list) else [dirs]:
                        f = os.path.join(root, d, *rest) + ".php"
                        if os.path.isfile(f) and _inside(f, base):
                            hits.append(f)
        if not hits:
            hits = [os.path.join(base, h.replace("/", os.sep)) for h in
                    _index_files_ending(["/" + "/".join(parts[-2:]) + ".php", "/" + parts[-1] + ".php"], base, from_rel, 5)]
        if hits:
            out = []
            for f in hits:
                ln, c = _jvm_type_pos(f, parts[-1])
                out.append(_result(f, base, ln, c, "use"))
            return {"kind": "symbol", "range": rng, "spec": name, "results": out}
        return {"kind": "external", "range": rng, "spec": name}
    return None


def _rust_mod_file(dir_, name):
    for f in (os.path.join(dir_, name + ".rs"), os.path.join(dir_, name, "mod.rs")):
        if os.path.isfile(f):
            return f
    return None


def _link_rust(ctx):
    line_text, col, from_full, base = (ctx[k] for k in ("line_text", "col", "from_full", "base"))
    here = os.path.dirname(from_full)
    stem = os.path.splitext(os.path.basename(from_full))[0]
    mod_dir = here if stem in ("mod", "lib", "main") else os.path.join(here, stem)
    m = re.match(r"^\s*(?:pub(?:\([^)]*\))?\s+)?mod\s+(\w+)\s*;", line_text)
    if m and m.start(1) <= col - 1 <= m.end(1):
        f = _inside(_rust_mod_file(mod_dir, m.group(1)), base)
        rng = [m.start(1) + 1, m.end(1) + 1]
        return {"kind": "path", "range": rng, "spec": m.group(1), "results": [_result(f, base, how="mod")]} if f else \
            {"kind": "missing", "range": rng, "spec": m.group(1)}
    m = re.match(r"^\s*(?:pub(?:\([^)]*\))?\s+)?use\s+([\w:{}, *]+)", line_text)
    if not m:
        return None
    kind, val, s, e = _token_at(line_text, col)
    if kind != "word" or val in ("use", "pub"):
        return None
    path = re.findall(r"\w+", line_text[m.start(1):s - 1]) + [val]
    if path[0] == "crate":
        d = here
        while _within(d, base) and not os.path.isfile(os.path.join(d, "Cargo.toml")):
            if _norm(d) == _norm(base):
                break
            d = os.path.dirname(d)
        cur = os.path.join(d, "src")
    elif path[0] == "super":
        cur = os.path.dirname(mod_dir)
    elif path[0] == "self":
        cur = mod_dir
    else:
        return {"kind": "external", "range": [s, e], "spec": "::".join(path)}
    f = None
    for i, seg in enumerate(path[1:], 1):
        nxt = _rust_mod_file(cur, seg)
        if nxt:
            f, cur = nxt, os.path.join(cur, seg)
            continue
        if f:  # an item of the last module file
            t = _get_content(f) or ""
            pos = _decl_pos(t, r"\b(?:fn|struct|enum|trait|type|const|static|mod|union|macro_rules!)\s+" + re.escape(seg) + r"\b", seg)
            f = _inside(f, base)
            return {"kind": "symbol", "range": [s, e], "name": seg, "results": [_result(f, base, *(pos or (1, 1)), "use")]} if f else None
        break
    f = _inside(f, base)
    if f:
        return {"kind": "path", "range": [s, e], "spec": "::".join(path), "results": [_result(f, base, how="use")]}
    return {"kind": "missing", "range": [s, e], "spec": "::".join(path)}


def _link_csharp(ctx):
    line_text, col, base, from_rel = (ctx[k] for k in ("line_text", "col", "base", "from_rel"))
    m = re.match(r"^\s*(?:global\s+)?using\s+(?:static\s+)?(?:\w+\s*=\s*)?([\w.]+)\s*;", line_text)
    if not m or not (m.start(1) <= col - 1 <= m.end(1)):
        return None
    ns, rng = m.group(1), [m.start(1) + 1, m.end(1) + 1]
    hits, scanned = [], 0
    for rel in _ensure_index():
        if not rel.endswith(".cs"):
            continue
        scanned += 1
        if scanned > 4000:  # very large solutions: the symbol index is the better tool
            break
        t = _get_content(os.path.join(base, rel.replace("/", os.sep))) or ""
        pos = _decl_pos(t, r"^[ \t]*namespace\s+" + re.escape(ns) + r"\s*[;{\n]", "")
        if pos:
            hits.append({"path": rel, "line": pos[0], "col": 1, "how": "namespace"})
            if len(hits) >= 20:
                break
    if hits:
        return {"kind": "path", "range": rng, "spec": ns, "results": hits}
    return {"kind": "external", "range": rng, "spec": ns}


def _link_ruby(ctx):
    line_text, col, from_full, base, from_rel = (ctx[k] for k in ("line_text", "col", "from_full", "base", "from_rel"))
    m = re.match(r"""^\s*(require_relative|require|load)\s*\(?\s*['"]([^'"]+)['"]""", line_text)
    if not m or not (m.start(2) <= col - 1 <= m.end(2)):
        return None
    spec, rng = m.group(2), [m.start(2) + 1, m.end(2) + 1]
    spec_rb = spec if spec.endswith(".rb") else spec + ".rb"
    if m.group(1) == "require_relative":
        f = _inside(os.path.normpath(os.path.join(os.path.dirname(from_full), spec_rb)), base)
        if f and os.path.isfile(f):
            return {"kind": "path", "range": rng, "spec": spec, "results": [_result(f, base, how="require")]}
        return {"kind": "missing", "range": rng, "spec": spec}
    hits = _index_files_ending(["/lib/" + spec_rb, "/" + spec_rb], base, from_rel, 5)
    if hits:
        return {"kind": "path", "range": rng, "spec": spec, "results": [{"path": h, "line": 1, "col": 1, "how": "require"} for h in hits]}
    return {"kind": "external", "range": rng, "spec": spec}


def _link_markup(ctx):
    """src= / href= in HTML-like files, plus whatever the JS rules see."""
    return _link_js(ctx)


def _handler_for(path):
    low = path.lower()
    ext = os.path.splitext(low)[1]
    if low.endswith(".d.ts") or ext in _JS_FAMILY or ext in _CSS_FAMILY:
        return _link_js
    if ext in (".py", ".pyi"):
        return _link_py
    if ext in _JVM_EXTS:
        return _link_jvm
    if ext == ".go":
        return _link_go
    if ext in _C_FAMILY:
        return _link_c
    if ext == ".php":
        return lambda ctx: _link_php(ctx) or _link_markup(ctx)
    if ext == ".rs":
        return _link_rust
    if ext == ".cs":
        return _link_csharp
    if ext in (".rb", ".rake"):
        return _link_ruby
    if ext in _MARKUP_FAMILY:
        return _link_markup
    return None


def link_at(from_key, text, line, col):
    base = base_root()
    from_full = resolve_read_path(from_key or "")
    none = {"kind": "none"}
    if base is None or not from_full:
        return none
    if not isinstance(text, str):
        text = _get_content(from_full) or ""
    handler = _handler_for(from_full)
    lines = text.split("\n")
    if handler is None or not (1 <= line <= len(lines)):
        return none
    line_text = lines[line - 1].rstrip("\r")
    if len(line_text) > 4000:
        return none
    from_rel = _rel_key(from_full, base) if _within(from_full, base) else ""
    ctx = {"text": text, "lines": lines, "ln": line, "line_text": line_text, "col": int(col),
           "from_full": from_full, "base": base, "from_rel": from_rel}
    try:
        res = handler(ctx)
    except (OSError, ValueError, re.error):
        res = None
    if not res:
        return none
    for r in res.get("results", []):
        r.setdefault("line", 1)
        r.setdefault("col", 1)
    return res


# ----- symbol index (Universal Ctags) -> srv_tags.py -----
from srv_tags import (  # noqa: E402,F401
    CTAGS_ARGS, CTAGS_INCREMENTAL_MAX, CTAGS_INDEX_OFF, CTAGS_MAX_FILE, SYMBOL_CATS, TAGS_TTL,
    _CTAGS_SKIP_KINDS, _FUNC_KINDS, _TYPE_KINDS, _camel_initials, _find_all, _index_candidates,
    _joined, _line_of, _name_search_index, _outline_lock, _rebuild_by_name, _run_ctags,
    _symbol_score, _tag_tuples, _tags, _tags_build, _tags_lock, ctags_lookup, ctags_path,
    ensure_tags, kind_category, outline_text, search_symbols, tags_file_changed,
)


# ----- request guards -----
# Per-process secret. Only the page we serve knows it (Host checks keep other
# origins from reading that page), so a request carrying it came from ReadO.
CSRF_TOKEN = secrets.token_urlsafe(32)
TOKEN_HEADER = "X-ReadO-Token"
MAX_JSON_BODY = 1_000_000  # default body cap for write APIs (bytes)

# Injected before </head> of source.html: exposes the token and makes every
# same-origin non-GET fetch() carry it, so pages need no per-call changes.
_TOKEN_SNIPPET = (
    '<meta name="reado-token" content="{t}">\n'
    '<script>(function(){{var t="{t}";window.READO_TOKEN=t;var f=window.fetch;'
    'window.fetch=function(input,init){{init=init||{{}};'
    'var req=(typeof Request!=="undefined"&&input instanceof Request)?input:null;'
    'var m=(init.method||(req&&req.method)||"GET").toUpperCase();'
    'if(m!=="GET"&&m!=="HEAD"){{try{{var u=new URL(req?req.url:String(input),location.href);'
    'if(u.origin===location.origin){{var h=new Headers(init.headers||(req?req.headers:undefined));'
    'h.set("{h}",t);init.headers=h;}}}}catch(e){{}}}}'
    'return f.call(this,input,init);}};}})();</script>\n'
)


def _allowed_hosts(port):
    return {f"127.0.0.1:{port}", f"localhost:{port}"}


def check_read_request(handler):
    """Checks for every request. Returns an error string, or None if OK.

    Host must be our loopback name (stops DNS rebinding: an attacker's domain
    resolving to 127.0.0.1 still sends its own Host). Requests initiated by a
    page on another site are refused via Origin / Sec-Fetch-Site."""
    port = handler.server.server_address[1]
    hosts = _allowed_hosts(port)
    if handler.headers.get("Host", "").lower() not in hosts:
        return "bad host"
    origin = handler.headers.get("Origin")
    if origin is not None and origin.lower() not in {"http://" + h for h in hosts}:
        return "cross-origin request refused"
    if handler.headers.get("Sec-Fetch-Site", "").lower() in ("cross-site", "same-site"):
        return "cross-site request refused"
    return None


def check_write_request(handler, max_body=MAX_JSON_BODY):
    """check_read_request + CSRF token + JSON content type + body size.
    Returns an error string, or None if OK."""
    err = check_read_request(handler)
    if err:
        return err
    token = handler.headers.get(TOKEN_HEADER, "")
    if not hmac.compare_digest(token.encode(), CSRF_TOKEN.encode()):
        return "missing or invalid " + TOKEN_HEADER
    ctype = handler.headers.get("Content-Type", "").split(";")[0].strip().lower()
    if ctype != "application/json":
        return "Content-Type must be application/json"
    try:
        length = int(handler.headers.get("Content-Length") or -1)
    except ValueError:
        length = -1
    if length < 0:
        return "Content-Length required"
    if length > max_body:
        return "request body too large"
    return None


_WIN_RESERVED = {"con", "prn", "aux", "nul",
                 *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}
_BAD_NAME_CHARS = set('<>:"|?*') | {chr(c) for c in range(32)}


def resolve_write_path(rel_path, must_exist=False):
    """Validate a client-supplied path for writing. Returns (abs_path, None)
    or (None, error).

    Allowed only if: inside base_dir after resolving symlinks/junctions, no
    component is ignored (.git, node_modules, ...), the extension is in the
    allow-list, names are valid on Windows (no ':' streams, reserved device
    names, trailing dot/space), the parent folder exists and the target is not
    a directory. must_exist=True additionally refuses creating new files."""
    if not isinstance(rel_path, str) or not rel_path.strip():
        return None, "path required"
    parts = rel_path.replace("\\", "/").strip("/").split("/")
    for p in parts:
        if p in ("", ".", ".."):
            return None, "invalid path"
        if any(c in _BAD_NAME_CHARS for c in p) or p != p.rstrip(" ."):
            return None, f"invalid file name: {p}"
        if p.split(".")[0].lower() in _WIN_RESERVED:
            return None, f"reserved file name: {p}"
        if _is_ignored(p):
            return None, f"path is ignored by settings: {p}"
    if _is_binary_name(parts[-1]):
        return None, "binary file type is not editable"
    base_real = base_root()
    if base_real is None:
        return None, "no folder open"
    full = os.path.realpath(os.path.join(base_real, *parts))
    if not _within(full, base_real) or _norm(full) == _norm(base_real):
        return None, "path outside base_dir"
    if not os.path.isdir(os.path.dirname(full)):
        return None, "parent folder does not exist"
    if os.path.exists(full):
        if not os.path.isfile(full):
            return None, "not a regular file"
    elif must_exist:
        return None, "file does not exist"
    return full, None


def atomic_write(full, data: bytes, expect_mtime_ns=None):
    """Write bytes to a path from resolve_write_path() atomically (temp file in
    the same folder + os.replace). If expect_mtime_ns is given and the file
    changed on disk since, nothing is written. Returns (new_mtime_ns, None) or
    (None, error)."""
    if expect_mtime_ns is not None:
        try:
            if os.stat(full).st_mtime_ns != int(expect_mtime_ns):
                return None, "file changed on disk"
        except FileNotFoundError:
            return None, "file changed on disk"
    folder = os.path.dirname(full)
    try:
        fd, tmp = tempfile.mkstemp(dir=folder, prefix=".reado-", suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, full)
        except BaseException:
            try:
                os.remove(tmp)
            except OSError:
                pass
            raise
    except OSError as e:
        return None, str(e)
    notify_file_changed(full)
    return os.stat(full).st_mtime_ns, None


def notify_file_changed(full):
    """Call after creating/changing/deleting a file under base_dir so search
    caches and the Quick Open index pick it up."""
    _CONTENT_CACHE.discard(full)
    with _index_lock:
        _index["built"] = 0.0  # next lookup refreshes in the background
    tags_file_changed(full)


# ----- files outside base_dir -----
# The page can never name an arbitrary absolute path: a file outside base_dir
# is readable/writable only after the *user* picked it through a native channel
# in reado.py (open dialog, command-line argument, drag and drop, a second
# instance forwarding its arguments), which calls grant_external(). Grants are
# exact files, persisted in state.json so restored tabs keep working.
EXTERNAL_MAX = 100
_state_lock = threading.Lock()
_state = None            # lazily loaded: {"ui": {...}, "external": [abs paths]}
_pending_open = []       # keys the page should open (polled via /api/stat)


def _is_abs_key(key) -> bool:
    return isinstance(key, str) and (
        re.match(r"^[A-Za-z]:[\\/]", key) is not None or key.startswith(("\\\\", "//")))


def _state_path():
    # next to config.json (%APPDATA%\ReadO for the exe); resolved at call time
    # because reado.py repoints CONFIG_PATH after import
    return os.path.join(os.path.dirname(CONFIG_PATH) or ".", "state.json")


def _load_state_locked():
    global _state
    if _state is None:
        try:
            with open(_state_path(), "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            data = {}
        ui = data.get("ui") if isinstance(data, dict) else None
        ext = data.get("external") if isinstance(data, dict) else None
        _state = {"ui": ui if isinstance(ui, dict) else {},
                  "external": [p for p in (ext or []) if isinstance(p, str)][:EXTERNAL_MAX]}
    return _state


def _save_state_locked():
    path = _state_path()
    folder = os.path.dirname(path) or "."
    try:
        fd, tmp = tempfile.mkstemp(dir=folder, prefix=".reado-state-", suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(_state, f, ensure_ascii=False)
        os.replace(tmp, path)
    except OSError:
        pass  # read-only location: state lives for this session only


def _is_granted(full) -> bool:
    n = _norm(full)
    with _state_lock:
        return any(_norm(p) == n for p in _load_state_locked()["external"])


def grant_external(path):
    """Called by reado.py for a file the user chose. Returns the key the page
    uses for it (relative inside base_dir, absolute outside), or None if it is
    not a regular file."""
    if not isinstance(path, str) or not path:
        return None
    full = os.path.realpath(path)
    if not os.path.isfile(full):
        return None
    base = base_root()
    if base and _within(full, base):
        return os.path.relpath(full, base).replace("\\", "/")
    with _state_lock:
        st = _load_state_locked()
        n = _norm(full)
        st["external"] = [full] + [p for p in st["external"] if _norm(p) != n][:EXTERNAL_MAX - 1]
        _save_state_locked()
    return full


def request_open(paths):
    """Grant paths and queue them for the page to open. Returns the keys."""
    keys = [k for k in (grant_external(p) for p in paths) if k]
    with _state_lock:
        _pending_open.extend(keys)
    return keys


def resolve_external_write_path(key):
    """resolve_write_path() for an absolute key: the exact granted file, which
    must still exist as a regular file outside base_dir."""
    full = os.path.realpath(key)
    base = base_root()
    if base and _within(full, base):
        return resolve_write_path(os.path.relpath(full, base), must_exist=True)
    if not _is_granted(full):
        return None, "file was not opened by the user"
    if not os.path.isfile(full):
        return None, "file does not exist"
    if _is_binary_name(full):  # same rule as inside the folder
        return None, "binary file type is not editable"
    return full, None


def _write_target(key, must_exist=True):
    if _is_abs_key(key):
        return resolve_external_write_path(key)
    return resolve_write_path(key, must_exist=must_exist)


def ui_state():
    with _state_lock:
        return _load_state_locked()["ui"]


# Write-API registry: path -> (handler fn, max body bytes)
POST_ROUTES = {}


def write_api(path, max_body=MAX_JSON_BODY):
    """Register a state-changing endpoint (POST, JSON in / JSON out).

    The decorated function receives the parsed JSON object (always a dict) and
    returns a dict (sent as 200) or a (status, dict) tuple. Guards run before
    it: check_write_request() and JSON parsing. Example for a save API:

        @write_api("/api/save", max_body=50_000_000)
        def api_save(data):
            full, err = resolve_write_path(data.get("path"), must_exist=True)
            if err:
                return 400, {"error": err}
            mtime, err = atomic_write(full, data["text"].encode("utf-8"),
                                      data.get("mtime_ns"))
            return (409, {"error": err}) if err else {"mtime_ns": mtime}
    """
    def deco(fn):
        POST_ROUTES[path] = (fn, max_body)
        return fn
    return deco


VERSION = "0.1.0"  # the app version (Help → About); bump with CHANGELOG.md


def settings_status():
    return {**SETTINGS, "first_run": _first_run, "base_dir_exists": base_root() is not None, "version": VERSION}


@write_api("/api/settings")
def api_save_settings(data):
    global SETTINGS, _first_run
    SETTINGS = save_settings(data)
    _first_run = False
    # invalidate file index so new ignored rules take effect immediately
    _index_reset()
    with _tags_lock:
        _tags["checked"] = 0.0  # symbol index re-checks its file list
    ensure_tags()
    return settings_status()


MAX_SAVE_BODY = 16_000_000   # JSON of a max_file_bytes file, escapes included


@write_api("/api/save", max_body=MAX_SAVE_BODY)
def api_save(data):
    """Save an open file. mtime_ns is what the page loaded (or last saved);
    null overwrites without the check (the user chose "overwrite")."""
    text = data.get("text")
    if not isinstance(text, str):
        return 400, {"error": "text required"}
    full, err = _write_target(data.get("path"), must_exist=True)
    if err:
        return 400, {"error": err}
    try:
        if os.path.getsize(full) > SETTINGS.get("max_file_bytes", 2_000_000):
            return 400, {"error": "file is too large to edit"}
    except OSError as e:
        return 400, {"error": str(e)}
    enc = data.get("encoding") or "utf-8"
    if enc not in SAVE_ENCODINGS:
        return 400, {"error": "unsupported encoding: " + str(enc)}
    try:
        raw = text.encode(enc)
    except UnicodeEncodeError as e:
        return 400, {"error": f"cannot save as {enc}: {text[e.start:e.end]!r} has no {enc} form",
                     "code": "encode"}
    if data.get("bom"):
        raw = next((m for m, e in _BOMS if e == enc), b"") + raw
    expect = data.get("mtime_ns")
    if expect is not None:
        try:
            expect = int(expect)
        except (TypeError, ValueError):
            return 400, {"error": "bad mtime_ns"}
    mtime, err = atomic_write(full, raw, expect_mtime_ns=expect)
    if err == "file changed on disk":
        return 409, {"error": err, "code": "conflict"}
    if err:
        return 500, {"error": err}
    # mtime_ns travels as a string: it does not fit in a JS number
    return {"mtime_ns": str(mtime), "size": len(raw)}


@write_api("/api/create")
def api_create(data):
    """Create an empty file inside base_dir. Refuses if it already exists."""
    full, err = resolve_write_path(data.get("path"), must_exist=False)
    if err:
        return 400, {"error": err}
    try:
        # O_EXCL: never replaces a file that appeared after the check above
        fd = os.open(full, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0))
        os.close(fd)
    except FileExistsError:
        return 409, {"error": "file already exists", "code": "exists"}
    except OSError as e:
        return 500, {"error": str(e)}
    notify_file_changed(full)
    base = base_root()
    return {"path": os.path.relpath(full, base).replace("\\", "/"),
            "mtime_ns": str(os.stat(full).st_mtime_ns)}


# ----- replace in files, rename / delete / new folder -> srv_fileops.py -----
def _recycle(full):
    """Move to the Windows Recycle Bin (SHFileOperation, FOF_ALLOWUNDO). True on success."""
    if os.name != "nt":
        return False
    import ctypes
    from ctypes import wintypes as wt

    class SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [("hwnd", wt.HWND), ("wFunc", wt.UINT), ("pFrom", wt.LPCWSTR), ("pTo", wt.LPCWSTR),
                    ("fFlags", ctypes.c_ushort), ("fAnyOperationsAborted", wt.BOOL),
                    ("hNameMappings", ctypes.c_void_p), ("lpszProgressTitle", wt.LPCWSTR)]
    # FO_DELETE; FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT | FOF_NOERRORUI
    op = SHFILEOPSTRUCTW(None, 3, os.path.abspath(full) + "\0\0", None, 0x40 | 0x10 | 0x4 | 0x400, False, None, None)
    rc = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
    return rc == 0 and not op.fAnyOperationsAborted and not os.path.lexists(full)

from srv_fileops import (  # noqa: E402,F401
    REPLACE_MAX_FILES, REPLACE_SAMPLES, _bad_name, _make_replacer, _replace_candidates,
    _replace_plan, _replace_query, _tree_changed, api_delete, api_link, api_mkdir, api_outline,
    api_rename, api_replace_apply, api_replace_preview, resolve_fs_target,
)


# ----- Git: changed lines of a buffer against HEAD, and HEAD's text -----
# Optional: needs git on PATH and a repository around the file; otherwise the
# page simply shows no markers. HEAD's text is cached per file and HEAD commit.
_git_cache = {}  # full path -> (head sha, text or None)
GIT_TIMEOUT = 5


def _git(args, cwd):
    # same guarded runner as the Git tool window (read-only commands, repo
    # config that would run programs switched off, timeout)
    return gitview.run_simple(args, cwd, timeout=GIT_TIMEOUT)


def git_head_text(full):
    """(text at HEAD or None, branch, in_repo)."""
    folder = os.path.dirname(full)
    # --abbrev-ref applies to the revisions after it: toplevel, sha, branch
    top = _git(["rev-parse", "--show-toplevel", "HEAD", "--abbrev-ref", "HEAD"], folder)
    if top is None:
        return None, "", False
    lines = top.decode("utf-8", "replace").split("\n")
    root, sha, branch = (lines + ["", "", ""])[:3]
    hit = _git_cache.get(full)
    if hit and hit[0] == sha:
        return hit[1], branch, True
    rel = os.path.relpath(full, root).replace("\\", "/")
    raw = _git(["show", f"HEAD:{rel}"], root)
    text = _decode(raw)[0] if raw is not None and not sniff_binary(raw) else None
    if len(_git_cache) > 300:
        _git_cache.clear()
    _git_cache[full] = (sha, text)
    return text, branch, True


def git_line_changes(old, new):
    """{added: [[from, to]], modified: [[from, to]], deleted: [after_line]} (1-based)."""
    import difflib
    a, b = old.split("\n"), new.split("\n")
    out = {"added": [], "modified": [], "deleted": []}
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag == "insert":
            out["added"].append([j1 + 1, j2])
        elif tag == "replace":
            out["modified"].append([j1 + 1, j2])
        elif tag == "delete":
            out["deleted"].append(max(j1, 1))
    return out


@write_api("/api/git-changes", max_body=MAX_SAVE_BODY)
def api_git_changes(data):
    """Changed lines of the editor buffer against HEAD (the page sends the buffer)."""
    full = resolve_read_path(str(data.get("path") or ""))
    text = data.get("text")
    if not full or not isinstance(text, str):
        return {"repo": False}
    head, branch, in_repo = git_head_text(full)
    if not in_repo:
        return {"repo": False}
    if data.get("want_head"):  # "compare with HEAD": the text itself
        return {"repo": True, "branch": branch, "head": head}
    if head is None:  # not in HEAD: the whole file is new
        n = text.count("\n") + 1
        return {"repo": True, "branch": branch, "untracked": True, "added": [[1, n]], "modified": [], "deleted": []}
    if len(text) > 4_000_000 or len(head) > 4_000_000:
        return {"repo": True, "branch": branch, "too_big": True, "added": [], "modified": [], "deleted": []}
    return {"repo": True, "branch": branch, **git_line_changes(head.replace("\r\n", "\n"), text.replace("\r\n", "\n"))}


gitview.register(sys.modules[__name__])


@write_api("/api/stat")
def api_stat(data):
    """Poll for external changes: mtime_ns of open files (null = gone) and of
    expanded tree folders, plus files queued by reado.py to be opened."""
    files, dirs = data.get("files") or [], data.get("dirs") or []
    out_f, out_d = {}, {}
    for key in files[:300]:
        if not isinstance(key, str):
            continue
        full = resolve_read_path(key)
        try:
            out_f[key] = str(os.stat(full).st_mtime_ns) if full and os.path.isfile(full) else None
        except OSError:
            out_f[key] = None
    for rel in dirs[:500]:
        if not isinstance(rel, str):
            continue
        full = _safe_join(base_root(), rel)
        try:
            out_d[rel] = str(os.stat(full).st_mtime_ns) if full and os.path.isdir(full) else None
        except OSError:
            out_d[rel] = None
    with _state_lock:
        pending = _pending_open[:]
        _pending_open.clear()
    return {"files": out_f, "dirs": out_d, "open": pending}


@write_api("/api/state", max_body=256_000)
def api_save_state(data):
    """UI state (theme, tabs, recent files/searches). Kept server-side because
    pywebview's private mode (its default) wipes localStorage on exit."""
    ui = data.get("ui")
    if not isinstance(ui, dict):
        return 400, {"error": "ui object expected"}
    with _state_lock:
        _load_state_locked()["ui"] = ui
        _save_state_locked()
    return {"ok": True}


# A second `reado.exe file` hands its arguments to the running instance. The
# page never sees IPC_SECRET (reado.py writes it to a per-user file), so a
# compromised page cannot grant itself files through this route.
IPC_SECRET = secrets.token_urlsafe(32)


@write_api("/api/open-request")
def api_open_request(data):
    if not hmac.compare_digest(str(data.get("ipc", "")).encode(), IPC_SECRET.encode()):
        return 403, {"error": "forbidden"}
    paths = [p for p in (data.get("paths") or []) if isinstance(p, str)]
    keys = request_open(paths)
    if on_open_request:
        try:
            on_open_request()  # reado.py raises the window
        except Exception:
            pass
    return {"opened": keys}


on_open_request = None  # set by reado.py


# ----- HTTP -----

# source.html keeps its inline <style> and <script> in ui/*.css|js; each
# `<!--#include ui/NAME-->` line is replaced by that file when the page is
# served, so the browser still gets one inline style and one inline script
# (one script: function hoisting and run order stay exactly as they were).
_INCLUDE_RE = re.compile(r"^[ \t]*<!--#include (ui/[\w.-]+\.(?:js|css))-->\r?\n", re.M)


def expand_includes(html):
    root = os.path.dirname(HTML_PATH)

    def sub(m):
        with open(os.path.join(root, *m.group(1).split("/")), "r", encoding="utf-8") as f:
            return f.read()
    return _INCLUDE_RE.sub(sub, html)


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
        self.send_header("X-Content-Type-Options", "nosniff")
        if ctype.startswith("text/html"):
            # no framing by other pages (clickjacking of the settings form)
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Content-Security-Policy", "frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        return

    def _serve_html(self):
        try:
            with open(HTML_PATH, "r", encoding="utf-8") as f:
                html = expand_includes(f.read())
        except FileNotFoundError:
            return self._send(404, {"error": "source.html missing"})
        snippet = _TOKEN_SNIPPET.format(t=CSRF_TOKEN, h=TOKEN_HEADER)
        # saved UI state inline, so the theme applies before first paint
        state = json.dumps(ui_state(), ensure_ascii=False).replace("<", "\\u003c")
        snippet += f"<script>window.READO_STATE={state};</script>\n"
        i = html.lower().find("</head>")
        html = html[:i] + snippet + html[i:] if i >= 0 else snippet + html
        self._send(200, html, "text/html; charset=utf-8")

    def _serve_diffwin(self, wid):
        """A diff window's page (gitview.DIFFWIN: what it compares)."""
        desc = gitview.DIFFWIN.desc(wid)
        if not desc:
            return self._send(404, {"error": "no such diff window"})
        try:
            with open(os.path.join(os.path.dirname(HTML_PATH), "diffwin.html"), "r", encoding="utf-8") as f:
                html = f.read()
        except FileNotFoundError:
            return self._send(404, {"error": "diffwin.html missing"})
        snippet = _TOKEN_SNIPPET.format(t=CSRF_TOKEN, h=TOKEN_HEADER)
        data = json.dumps({"id": wid, "state": ui_state(), "desc": desc}, ensure_ascii=False).replace("<", "\\u003c")
        snippet += f"<script>window.READO_DIFFWIN={data};</script>\n"
        i = html.lower().find("</head>")
        html = html[:i] + snippet + html[i:] if i >= 0 else snippet + html
        self._send(200, html, "text/html; charset=utf-8")

    def do_GET(self):
        err = check_read_request(self)
        if err:
            return self._send(403, {"error": err})
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        if u.path == "/" or u.path == "/source.html":
            self._serve_html()
        elif u.path == "/diffwin":
            self._serve_diffwin(q.get("id", ""))
        elif u.path == "/api/settings":
            self._send(200, settings_status())
        elif u.path == "/api/state":
            self._send(200, {"ui": ui_state()})
        elif u.path == "/api/tree":
            self._send(200, list_dir(q.get("path", "")))
        elif u.path == "/api/file":
            data, err = read_file(q.get("path", ""), q.get("encoding", ""))
            if isinstance(err, BinaryFile):
                self._send(415, {"error": str(err), "binary": True, "size": err.size})
            elif err:
                self._send(404, {"error": err})
            else:
                self._send(200, data)
        elif u.path == "/api/search":
            try:
                ctx = int(q.get("ctx", "2"))
            except ValueError:
                ctx = 2
            try:
                limit = int(q.get("max", "0") or 0)
            except ValueError:
                limit = 0
            if not _SEARCH_GATE.acquire(blocking=False):
                return self._send(429, {"error": "search capacity reached; try again shortly"})
            try:
                res = find_in_files(
                    query=q.get("q", ""),
                    case_sensitive=q.get("case", "0") == "1",
                    regex=q.get("regex", "0") == "1",
                    whole_word=q.get("word", "0") == "1",
                    scope=q.get("scope", ""),
                    glob=q.get("glob", ""),
                    context=ctx,
                    limit=limit,
                    exclude=q.get("exclude", ""),
                    default_excludes=q.get("defexcl", "1") != "0",
                )
            finally:
                _SEARCH_GATE.release()
            self._send(200, res)
        elif u.path == "/api/goto" and q.get("index_only") == "1":  # cheap: no search, no gate
            self._send(200, goto_symbol(q.get("symbol", ""), q.get("scope", ""), q.get("from", ""), index_only=True))
        elif u.path == "/api/goto":
            if not _SEARCH_GATE.acquire(blocking=False):
                return self._send(429, {"error": "search capacity reached; try again shortly"})
            try:
                res = goto_symbol(q.get("symbol", ""), q.get("scope", ""), q.get("from", ""))
            finally:
                _SEARCH_GATE.release()
            self._send(200, res)
        elif u.path == "/api/refs":
            if not _SEARCH_GATE.acquire(blocking=False):
                return self._send(429, {"error": "search capacity reached; try again shortly"})
            try:
                res = find_references(q.get("symbol", ""), q.get("scope", ""), q.get("from", ""))
            finally:
                _SEARCH_GATE.release()
            self._send(200, res)
        elif u.path == "/api/component":
            self._send(200, find_component(q.get("name", ""), q.get("from", "")))
        elif u.path == "/api/symbols":
            try:
                limit = max(1, min(int(q.get("limit", "100")), 500))
            except ValueError:
                limit = 100
            self._send(200, search_symbols(q.get("q", ""), q.get("cat", ""), limit))
        elif u.path == "/api/tags-status":
            self._send(200, ensure_tags())
        elif u.path == "/api/files":
            try:
                limit = int(q.get("limit", "50"))
                offset = int(q.get("offset", "0"))
            except ValueError:
                limit, offset = 50, 0
            self._send(200, find_files(q.get("q", ""), offset, limit))
        elif u.path == "/api/projects":
            base = base_root()
            projects = []
            try:
                for name in sorted(os.listdir(base) if base else [], key=str.lower):
                    if _is_ignored(name):
                        continue
                    full = os.path.join(base, name)
                    if os.path.isdir(full):
                        projects.append(name)
            except OSError:
                pass
            self._send(200, {"projects": projects})
        elif u.path.startswith("/api/git/"):
            code, body = gitview.handle_get(u.path[len("/api/git/"):], parse_qs(u.query))
            self._send(code, body)
        elif u.path in APP_FILES:
            self._send_app_file(u.path[len("/app/"):])
        elif u.path.startswith("/vendor/"):
            self._send_vendor(unquote(u.path[len("/vendor/"):]))
        elif u.path == "/favicon.ico":  # the app icon, next to source.html (title bar logo)
            self._send_icon()
        else:
            self._send(404, {"error": "not found"})

    def _send_icon(self):
        try:
            with open(os.path.join(os.path.dirname(HTML_PATH), "icon.ico"), "rb") as f:
                body = f.read()
        except OSError:
            return self._send(404, {"error": "not found"})
        self.send_response(200)
        self.send_header("Content-Type", "image/x-icon")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "public, max-age=86400")
        self.end_headers()
        self.wfile.write(body)

    def _send_app_file(self, name):
        """git.js / git.css: parts of the page kept in their own files, next to source.html."""
        try:
            with open(os.path.join(os.path.dirname(HTML_PATH), name), "rb") as f:
                body = f.read()
        except OSError:
            return self._send(404, {"error": "not found"})
        self._send(200, body, APP_FILES["/app/" + name])

    def _send_vendor(self, rel):
        """Serve a bundled asset from VENDOR_PATH. Read-only, no directory listing."""
        if not rel or rel.endswith("/"):
            return self._send(404, {"error": "not found"})
        full = os.path.abspath(os.path.join(VENDOR_PATH, rel.replace("/", os.sep)))
        # reject traversal outside the vendor dir
        if not _within(full, VENDOR_PATH):
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
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        route = POST_ROUTES.get(urlparse(self.path).path)
        if route is None:
            err = check_read_request(self)
            return self._send(403 if err else 404, {"error": err or "not found"})
        fn, max_body = route
        err = check_write_request(self, max_body)
        if err:
            if err != "request body too large":
                # read the (size-capped) body first: closing a socket with
                # unread data makes Windows reset it before the client gets
                # the 403
                try:
                    n = int(self.headers.get("Content-Length") or 0)
                    if 0 < n <= max_body:
                        self.rfile.read(n)
                except (ValueError, OSError):
                    pass
            return self._send(413 if err == "request body too large" else 403, {"error": err})
        length = int(self.headers["Content-Length"])
        try:
            data = json.loads(self.rfile.read(length) or b"{}")
        except (json.JSONDecodeError, UnicodeDecodeError):
            return self._send(400, {"error": "invalid json"})
        if not isinstance(data, dict):
            return self._send(400, {"error": "json object expected"})
        res = fn(data)
        code, body = res if isinstance(res, tuple) else (200, res)
        return self._send(code, body)


class ReadOServer(ThreadingHTTPServer):
    """One thread per request, so a long search no longer freezes tree/file
    requests. Daemon threads let the app exit while a search is running."""
    daemon_threads = True
    # HTTPServer sets SO_REUSEADDR, which on Windows would let another process
    # bind the same port alongside us; keep the platform default instead.
    allow_reuse_address = os.name != "nt"

    def handle_error(self, request, client_address):
        # The page cancelled the request (newer search, closed window): not an
        # error. The windowed exe also has no stderr to print a traceback to.
        if isinstance(sys.exc_info()[1], (ConnectionAbortedError, ConnectionResetError, BrokenPipeError)):
            return
        if sys.stderr is not None:
            super().handle_error(request, client_address)


def make_server(host="127.0.0.1", port=8766):
    """The server ReadO runs. Loopback only — the guards above assume it."""
    if host not in ("127.0.0.1", "localhost", "::1"):
        raise ValueError("ReadO must bind to loopback only")
    return ReadOServer((host, port), Handler)


def serve(host="127.0.0.1", port=8766):
    print(f"ReadO: http://{host}:{port}/")
    make_server(host, port).serve_forever()


if __name__ == "__main__":
    ensure_config()
    SETTINGS = load_settings()
    serve()
