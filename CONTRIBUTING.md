# Contributing

Thanks for looking at ReadO. Issues and pull requests are welcome.

## Set up

```bash
pip install -r requirements.txt
python fetch-vendor.py          # once: Monaco / marked / fonts / ripgrep / ctags into vendor\
python reado.py [file ...]      # run from source
python tests/test_git.py        # headless git API tests (fixture repositories, needs git)
```

The editor and UI suites (`tests/verify_editor.py`, `tests/ui_git_smoke.py`) need `pip install playwright` and
`playwright install chromium`; `python scripts/build_test.py` builds `dist-next` and runs everything
(see `docs/RELEASE.md`).

## Layout

| Path | Content |
|---|---|
| `server.py`, `srv_*.py` | Loopback HTTP server: files, search, symbols, go to definition, file operations |
| `gitview.py`, `git.js`, `git.css` | Read-only Git views |
| `source.html`, `ui/` | Single-page UI (Monaco); a new `ui/*` file needs its include line in `source.html` |
| `reado.py` | pywebview launcher (window, single instance, drag and drop) |
| `tests/`, `scripts/` | Test suites, build and release helpers |

## Conventions

- UI text is English. Keep ReadO read-only for git (commands that change a repository become instructions for an
  agent; nothing runs in ReadO).
- Keep pull requests small and say how you checked them (which suites, what you clicked).
- Every README is kept in four languages (English, Korean, Chinese, Japanese) with the same sections.
