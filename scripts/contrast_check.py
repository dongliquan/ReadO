"""Dark theme contrast check (WCAG 2.x): the One Dark editor theme and the app's dark colors.

    python scripts/contrast_check.py          # report; exit 1 when something fails
    python scripts/contrast_check.py --leaks  # also list Monaco's built-in token rules One Dark does not cover

What it checks
  * every token color the editor can show in One Dark, as Monaco resolves it: a
    token takes the rule with the longest dotted prefix (string.sql before
    string), a later theme overriding an earlier one; the built-in vs / vs-dark
    rules come from the bundled vendor/monaco editor.main.js, so a language rule
    One Dark forgets (string.sql was pure red) shows up here
  * text on the diff tints (deleted / inserted lines, and changed characters on top)
  * the app's dark text colors (ui/base.css, git.css) on the dark backgrounds
  * nothing too saturated: chroma (max - min of r, g, b) under LOUD for text colors
Body text needs 4.5:1, large or non-text marks 3:1. The light theme is not checked
(it is left as it was).
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOUD = 0.8  # #ff0000 is 1.0, One Dark's red #e06c75 is 0.45
DARK_BADGE_BGS = ("#282c34", "#21252b", "#1d3352", "#263b5c")  # panels, active tab strip, selected row


def rgb(h):
    h = h.strip().lstrip("#")
    if len(h) in (3, 4):
        h = "".join(c * 2 for c in h)
    v = [int(h[i:i + 2], 16) for i in range(0, len(h), 2)]
    return (v[0], v[1], v[2], v[3] / 255 if len(v) > 3 else 1.0)


def over(c, bg):
    """c (r, g, b, a) drawn over an opaque bg."""
    a = c[3]
    return tuple(c[i] * a + bg[i] * (1 - a) for i in range(3)) + (1.0,)


def lum(c):
    f = lambda v: v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    return 0.2126 * f(c[0] / 255) + 0.7152 * f(c[1] / 255) + 0.0722 * f(c[2] / 255)


def ratio(a, b):
    x, y = lum(a), lum(b)
    return (max(x, y) + 0.05) / (min(x, y) + 0.05)


def chroma(c):
    return (max(c[:3]) - min(c[:3])) / 255


def read(*p):
    with open(os.path.join(ROOT, *p), encoding="utf-8") as f:
        return f.read()


def block(text, start):
    """The {...} that opens at or after text.index(start)."""
    i = text.index("{", text.index(start))
    depth = 0
    for j in range(i, len(text)):
        depth += {"{": 1, "}": -1}.get(text[j], 0)
        if depth == 0:
            return text[i:j + 1]
    raise ValueError("unbalanced " + start)


def rules_of(js, names=None):
    """(token, rrggbb) of `{ token: 'x', foreground: 'rrggbb' | name }`; names: the palette constants."""
    out = []
    for t, lit, name in re.findall(r"token:\s*['\"]([^'\"]*)['\"],\s*foreground:\s*(?:['\"]([0-9a-fA-F]{6})['\"]|(\w+))", js):
        out.append((t, lit or (names or {})[name]))
    return out


def builtin_rules():
    """Monaco's vs and vs-dark rules from the bundled editor (the order One Dark inherits them in)."""
    src = read("vendor", "monaco", "vs", "editor", "editor.main.js")
    found = re.findall(r'\{token:"([^"]*)",foreground:"([0-9A-Fa-f]{6})"', src)
    # the vs rules come first, then vs-dark (each starts with the "" default rule), then high contrast
    starts = [i for i, (t, _) in enumerate(found) if t == ""]
    vs = found[starts[0]:starts[1]]
    vs_dark = found[starts[1]:starts[2]]
    return vs, vs_dark


def resolve(token, rules):
    """Monaco's TokenTheme: the rule with the longest dotted prefix of token; ties: the later one."""
    parts = token.split(".")
    best, best_len = None, -1
    for t, fg in rules:
        seg = t.split(".") if t else []
        if parts[:len(seg)] == seg and len(seg) >= best_len:
            best, best_len = fg, len(seg)
    return best


def theme(js, name):
    b = block(js, f"'{name}'")
    colors = dict(re.findall(r"'([\w.]+)':\s*'(#[0-9a-fA-F]{6,8})'", b))
    # palette constants declared before the theme (const red = 'ef8a91', …)
    head = js[:js.index(f"'{name}'")]
    names = dict(re.findall(r"\b(\w+)\s*=\s*'([0-9a-fA-F]{6})'", head))
    return rules_of(b, names), colors


def css_vars(css, selector):
    b = block(css, selector)
    return {k: v for k, v in re.findall(r"(--[\w-]+):\s*(#[0-9a-fA-F]{3,8})\b", b)}


def main():
    show_leaks = "--leaks" in sys.argv
    fails, lines = [], []

    def check(what, fg, bg, need, loud_ok=False):
        r = ratio(fg, bg)
        bad = r < need or (not loud_ok and chroma(fg) >= LOUD)
        lines.append(f"{'FAIL' if bad else ' ok '} {r:5.2f}/{need} {'LOUD ' if chroma(fg) >= LOUD else ''}{what}")
        if bad:
            fails.append(what)

    themes_js = read("ui", "themes.js")
    dark_rules, dark_colors = theme(themes_js, "one-dark")
    vs, vs_dark = builtin_rules()
    merged = vs + vs_dark + dark_rules
    ed_bg = rgb(dark_colors["editor.background"])

    # --- editor tokens ---
    tokens = sorted({t for t, _ in vs + vs_dark + dark_rules})
    leaks = []
    for t in tokens:
        fg = resolve(t, merged)
        if fg is None:
            continue
        own = resolve(t, dark_rules)
        if fg != own:
            leaks.append((t, fg))
        check(f"token {t or '(default)'} #{fg.lower()}", rgb(fg), ed_bg, 4.5)
    for k in ("editorLineNumber.foreground", "editorLineNumber.activeForeground"):
        check(f"{k} {dark_colors[k]}", rgb(dark_colors[k]), ed_bg, 4.5)
    for i in (1, 2, 3, 4, 5, 6):
        k = f"editorBracketHighlight.foreground{i}"
        if k in dark_colors:
            check(f"{k} {dark_colors[k]}", rgb(dark_colors[k]), ed_bg, 4.5)

    # --- diff: line tint, and changed characters drawn on top of it ---
    text = rgb(dark_colors["editor.foreground"])
    for side in ("removed", "inserted"):
        line = over(rgb(dark_colors[f"diffEditor.{side}LineBackground"]), ed_bg)
        chars = over(rgb(dark_colors[f"diffEditor.{side}TextBackground"]), line)
        # the tint marks the line: editor text keeps 4.5:1, syntax colors 3:1
        check(f"diff {side} line: editor text", text, line, 4.5)
        check(f"diff {side} changed chars: editor text", text, chars, 4.5)
        for t in ("string", "keyword", "comment", "number", "string.sql", "type"):
            fg = rgb(resolve(t, merged))
            check(f"diff {side} line: {t}", fg, line, 3.0)
            check(f"diff {side} changed chars: {t}", fg, chars, 3.0)

    # --- the app (ui/base.css, git.css) ---
    base = css_vars(read("ui", "base.css"), "body.theme-dark")
    git = css_vars(read("git.css"), "body.theme-dark")
    bgs = {n: rgb(base[n]) for n in ("--bg", "--panel", "--side")}
    for n in ("--text", "--text-dim", "--text-mute", "--accent"):
        for bn, bg in bgs.items():
            check(f"{n} {base[n]} on {bn}", rgb(base[n]), bg, 4.5)
    for n in ("--g-add", "--g-mod", "--g-del", "--g-unv", "--g-con", "--g-ign"):
        check(f"git {n} {git[n]} on --panel", rgb(git[n]), bgs["--panel"], 4.5)
        check(f"git {n} {git[n]} on the selected row --g-sel", rgb(git[n]), rgb(git["--g-sel"]), 3.0)
    check(f"--text on the selected row --g-sel {git['--g-sel']}", rgb(base["--text"]), rgb(git["--g-sel"]), 4.5)
    dark_text = base
    for n in ("--on-accent",):
        if n in dark_text:
            check(f"{n} {dark_text[n]} on --accent", rgb(dark_text[n]), rgb(base["--accent"]), 4.5)
    for n in ("--err", "--ok", "--warn"):
        if n in dark_text:
            for bn, bg in bgs.items():
                check(f"{n} {dark_text[n]} on {bn}", rgb(dark_text[n]), bg, 4.5)

    # --- file badges: the dark variant fileBadge() computes (ui/commands.js darkBadge) ---
    src = read("ui", "commands.js")
    for col in sorted(set(re.findall(r"'(#[0-9a-fA-F]{6})'\]", src[src.index("FILE_BADGES"):src.index("function fileBadge")]))):
        d = dark_badge(col)
        for bn in DARK_BADGE_BGS:
            check(f"badge {col} -> {d} on {bn}", rgb(d), rgb(bn), 4.5)
    # the selected tree row and the active pane's tab strip
    for n in ("--text", "--text-dim"):
        check(f"{n} {base[n]} on --sel-bg {base['--sel-bg']}", rgb(base[n]), rgb(base["--sel-bg"]), 4.5)
        check(f"{n} {base[n]} on --tabs-active {base['--tabs-active']}", rgb(base[n]), rgb(base["--tabs-active"]), 4.5)
    check(f"--text-mute (tab close ×, an icon) on --tabs-active", rgb(base["--text-mute"]), rgb(base["--tabs-active"]), 3.0)
    for n in ("--mark-add", "--mark-mod", "--mark-del"):  # change markers: non-text, 3:1
        check(f"{n} {base[n]} on --panel", rgb(base[n]), bgs["--panel"], 3.0)

    for l in lines:
        if l.startswith("FAIL") or "-v" in sys.argv:
            print(l)
    if show_leaks:
        print("\nbuilt-in rules One Dark does not set itself (token: color it gets):")
        for t, fg in leaks:
            print(f"  {t}: #{fg.lower()}")
    print(f"\n{len(lines) - len(fails)} / {len(lines)} ok")
    return 1 if fails else 0


def dark_badge(hexcol):
    """Python twin of darkBadge() in ui/commands.js: mix toward #d7dae0 in 5% steps until the
    color reads 4.5:1 on the panels, the active tab strip and a selected row, and is calm."""
    c = rgb(hexcol)
    g = (0xd7, 0xda, 0xe0)
    for step in range(4, 21):
        p = step / 20
        m = tuple(int(c[i] * (1 - p) + g[i] * p + 0.5) for i in range(3)) + (1.0,)  # Math.round
        if min(ratio(m, rgb(b)) for b in DARK_BADGE_BGS) >= 4.6 and chroma(m) < 0.6:
            return "#%02x%02x%02x" % m[:3]
    return "#d7dae0"


if __name__ == "__main__":
    sys.exit(main())
