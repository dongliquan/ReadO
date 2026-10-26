"""Component tags and links: <ItemTop> -> ItemTop.vue, import paths, aliases, includes and imported names -> file + position.

Split out of server.py. Names of the server module are read as S.NAME at
call time, so reassignments there (settings, tests) apply here too."""
import json
import os
import re

import server as S

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
            return S._decode(f.read())[0]
    except OSError:
        return None


def _project_roots(full, base):
    """Folders from the file up to base_dir that look like a JS project root."""
    out, d = [], os.path.dirname(full)
    while S._within(d, base):
        if any(os.path.isfile(os.path.join(d, n)) for n in
               ("package.json", "tsconfig.json", "jsconfig.json", "vite.config.ts", "vite.config.js")):
            out.append(d)
        if S._norm(d) == S._norm(base):
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
            if S._within(real, base):
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
    base = S.base_root()
    if base is None or not re.match(r"^[A-Za-z][\w.-]*$", name or ""):
        return {"results": [], "name": name}
    key = _norm_name(name.split(".")[0])
    pascal = "".join(w[:1].upper() + w[1:] for w in re.split(r"[-_]", name.split(".")[0]) if w)
    from_full = S.resolve_read_path(from_key) if from_key else None
    results, seen = [], set()

    def add(full, how):
        try:
            rel = os.path.relpath(full, base).replace("\\", "/")
        except ValueError:
            return
        if rel not in seen and S._within(full, base):
            seen.add(rel)
            results.append({"path": rel, "line": 1, "col": 1, "how": how})

    # (a) imports of the current file
    if from_full and os.path.isfile(from_full):
        text = S._get_content(from_full) or ""
        for local, spec in _component_imports(text).items():
            if _norm_name(local) == key or local == pascal:
                hit = _resolve_spec(spec, from_full, base)
                if hit:
                    add(_follow_barrel(hit, local, base), "import")
    if results:
        return {"results": results, "name": name}
    # (b) file names in the folder
    from_rel = os.path.relpath(from_full, base).replace("\\", "/") if from_full and S._within(from_full, base) else ""
    cands = []
    for rel in S._ensure_index():
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
    return real if S._within(real, base) else None


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
    from_rel = _rel_key(from_full, base) if S._within(from_full, base) else ""
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
    text = S._get_content(full) or ""
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
    text = S._get_content(full) or ""
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
    hits = [r for r in S._ensure_index() if r.lower().endswith(suffixes) or r.lower() in tuple(s.lstrip("/") for s in suffixes)]
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
        while S._within(d, base):  # the folder of the file and every parent (source roots)
            cands += [os.path.join(d, *parts), os.path.join(d, "src", *parts)]
            if S._norm(d) == S._norm(base):
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
    text = S._get_content(full) or ""
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
            if re.search(r"^\s*package\s+" + re.escape(pkg) + r"\s*;?\s*$", S._get_content(full) or "", re.M):
                return [(full, member)]
    return []


def _jvm_type_pos(full, name):
    text = S._get_content(full) or ""
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
            hits = [h for h in S._ensure_index() if h.rsplit("/", 1)[0].endswith(pkg) and h.endswith(_JVM_EXTS)][:40]
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
    while S._within(d, base):
        t = _read_small(os.path.join(d, "go.mod"))
        if t:
            m = re.search(r"^module\s+(\S+)", t, re.M)
            return (d, m.group(1)) if m else None
        if S._norm(d) == S._norm(base):
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
            t = S._get_content(f) or ""
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
        while S._within(d, base) and not os.path.isfile(os.path.join(d, "Cargo.toml")):
            if S._norm(d) == S._norm(base):
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
            t = S._get_content(f) or ""
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
    for rel in S._ensure_index():
        if not rel.endswith(".cs"):
            continue
        scanned += 1
        if scanned > 4000:  # very large solutions: the symbol index is the better tool
            break
        t = S._get_content(os.path.join(base, rel.replace("/", os.sep))) or ""
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
    base = S.base_root()
    from_full = S.resolve_read_path(from_key or "")
    none = {"kind": "none"}
    if base is None or not from_full:
        return none
    if not isinstance(text, str):
        text = S._get_content(from_full) or ""
    handler = _handler_for(from_full)
    lines = text.split("\n")
    if handler is None or not (1 <= line <= len(lines)):
        return none
    line_text = lines[line - 1].rstrip("\r")
    if len(line_text) > 4000:
        return none
    from_rel = _rel_key(from_full, base) if S._within(from_full, base) else ""
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
