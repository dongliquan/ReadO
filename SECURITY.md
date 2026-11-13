# Security policy

## Reporting a vulnerability

Please report vulnerabilities **privately** with GitHub's *Report a vulnerability* button (Security tab) instead of a
public issue. Include what you found, how to reproduce it, and the ReadO version.

## What ReadO can touch

ReadO reads and edits files in the folders you open, and runs `git` (read-only sub-commands) and the bundled ripgrep
and Universal Ctags on them.

- The built-in HTTP server listens on `127.0.0.1` only. Pages are protected by Host / Origin checks and a per-process
  token on every write request.
- The Git views only run read-only git sub-commands. A repository's own config cannot make git start programs
  (fsmonitor, filter drivers, external diff / textconv are switched off); revisions and paths are validated.
- ReadO has no telemetry and makes no network requests at run time (Monaco, marked, fonts, ripgrep and ctags are
  bundled).
- Release builds are **not code-signed**; Windows SmartScreen may warn on first start.
