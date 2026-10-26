"""Go to definition and find usages: whole-word search hits classified by declaration rules.

Split out of server.py. Names of the server module are read as S.NAME at
call time, so reassignments there (settings, tests) apply here too."""
import os
import re
from collections import OrderedDict

import server as S

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
    rg = S._rg_path()
    if not rg:
        return None
    args = [rg] + S._rg_common_args("") + ["--max-count", "200", "-w", "-F", "-s", "-e", symbol, scope_root]
    out, exit_code = [], None
    events = S._rg_events(args, kind, gen)
    for obj in events:
        t = obj.get("type")
        if t == "match":
            d = obj["data"]
            try:
                rel = os.path.relpath(S._rg_decode(d.get("path"))[0], base).replace("\\", "/")
            except ValueError:
                continue
            out.append((rel, d.get("line_number", 0), S._rg_decode(d.get("lines"))[0].rstrip("\r\n")))
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
    if S._is_stale(kind, gen):
        return None
    text = S._get_content(full)
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
    tasks = [(full, rel, symbol, word_pat, kind, gen) for rel, full in S._scoped_index(base, scope_root)]
    out = []
    it = S._SEARCH_EXECUTOR.map(_word_hits_one_file, tasks, chunksize=8)
    try:
        for batch in it:
            if S._is_stale(kind, gen):
                break
            out.extend(batch or ())
            if len(out) >= cap:
                break
    finally:
        it.close()
    return out[:cap]


def _scope_and_base(scope):
    base = S.base_root()
    if base is None:
        return None, None
    scope_root = S._safe_join(base, scope) if scope else base
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
    tagged = S.ctags_lookup(symbol, scope_root, base)
    if tagged:
        ranked = rank_decls(tagged, symbol, from_path)[:GOTO_MAX_DECL]
        return {"results": ranked, "declarations": len(ranked), "total": len(ranked), "source": "ctags"}
    if index_only:
        return {"results": [], "declarations": 0, "total": 0, "source": "none" if tagged is None else "ctags"}
    gen = S._new_gen("goto")
    hits = _word_hits(symbol, scope_root, base, "goto", gen, GOTO_SCAN_CAP)
    decls, plain = [], []
    for rel, ln, line in hits:
        entry = {"path": rel, "line": ln, "col": _name_col(line, symbol), "text": S._clip(line.rstrip())[0]}
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
    gen = S._new_gen("refs")
    hits = _word_hits(symbol, scope_root, base, "refs", gen, REFS_MAX + 1)
    out = []
    for rel, ln, line in hits[:REFS_MAX]:
        out.append({"path": rel, "line": ln, "col": _name_col(line, symbol),
                    "text": S._clip(line.rstrip())[0], "decl": bool(classify_decl(rel, line, symbol))})
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
