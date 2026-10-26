"""
Build dist-next\\reado.exe and run every automated suite on it, one after another.

    python scripts/build_test.py                # build + all suites
    python scripts/build_test.py --skip-build   # suites only, on the dist-next that is there
    python scripts/build_test.py --gitfx DIR    # git fixture folder for ui_git_smoke (made if missing)

dist\\ is never built into or touched; putting the build there is scripts/swap_dist.py
(see docs/RELEASE.md). Suites run one at a time: verify_editor's search steps get
"429 busy" when another suite loads the machine. A failed suite is run once more and
the summary says so ("passed on retry"), so a flaky step stays visible.
Logs: %TEMP%\\reado-release\\<time>\\<step>.log. Exit code 0 only if everything passed.
"""
import argparse
import os
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import swap_dist  # noqa: E402  (sha256, running_from, git_head)

NEXT_EXE = os.path.join(ROOT, "dist-next", "reado.exe")
PY = sys.executable


def run(name, cmd, log_dir, ok_text=None, timeout=1800):
    """Run one step; True if it exited 0 (and printed ok_text, when given). The tail goes to the console."""
    log = os.path.join(log_dir, name + ".log")
    t0 = time.time()
    print(f"--- {name}: {' '.join(cmd)}", flush=True)
    try:
        with open(log, "w", encoding="utf-8", errors="replace") as f:
            p = subprocess.run(cmd, cwd=ROOT, stdout=f, stderr=subprocess.STDOUT, timeout=timeout)
        code = p.returncode
    except subprocess.TimeoutExpired:
        code = "timeout"
    with open(log, encoding="utf-8", errors="replace") as f:
        lines = f.read().splitlines()
    fails = [ln for ln in lines if ln.startswith("FAIL")]
    ok = code == 0 and (ok_text is None or any(ok_text in ln for ln in lines[-5:]))
    for ln in fails[:10] + lines[-2:]:
        print("    " + ln)
    print(f"    -> {'ok' if ok else 'FAILED'} (exit {code}, {time.time() - t0:.0f} s, log {log})", flush=True)
    return ok, (lines[-1].strip() if lines else "")


def main():
    ap = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    ap.add_argument("--skip-build", action="store_true", help="test the dist-next that is there")
    ap.add_argument("--gitfx", default=os.path.join(tempfile.gettempdir(), "reado-release-gitfx"),
                    help="git fixture folder for ui_git_smoke (made with tests/git_fixture.py if missing)")
    a = ap.parse_args()
    log_dir = os.path.join(tempfile.gettempdir(), "reado-release", time.strftime("%Y%m%d-%H%M%S"))
    os.makedirs(log_dir, exist_ok=True)

    print(f"HEAD {swap_dist.git_head()}")
    dirty = subprocess.run(["git", "-C", ROOT, "status", "--short", "--untracked-files=no"],
                           capture_output=True, text=True).stdout.split("\n")
    dirty = [d for d in dirty if d.strip()]
    if dirty:
        print("note: uncommitted changes are built in as well:")
        for d in dirty:
            print("    " + d)
    if os.name == "nt" and swap_dist.running_from([os.path.dirname(NEXT_EXE)]):
        print("stop: a ReadO from dist-next is running; close it first (the build replaces that folder)")
        return 1

    results = []  # (step, status, detail)
    if not a.skip_build:
        ok, _ = run("build", ["cmd", "/c", os.path.join(ROOT, "build.bat"), "dist-next"], log_dir, "reado.exe")
        results.append(("build dist-next", "ok" if ok else "FAILED", ""))
        if not ok or not os.path.isfile(NEXT_EXE):
            return summary(results, log_dir)
    elif not os.path.isfile(NEXT_EXE):
        print("stop: dist-next\\reado.exe is missing (run without --skip-build)")
        return 1

    if not os.path.isdir(os.path.join(a.gitfx, "basic")):
        ok, _ = run("git_fixture", [PY, os.path.join("tests", "git_fixture.py"), a.gitfx], log_dir)
        if not ok:
            results.append(("git fixture", "FAILED", a.gitfx))
            return summary(results, log_dir)

    suites = [
        ("verify_editor", [PY, os.path.join("tests", "verify_editor.py")], "passed"),
        ("test_git", [PY, os.path.join("tests", "test_git.py")], "all passed"),
        ("ui_git_smoke", [PY, os.path.join("tests", "ui_git_smoke.py"), a.gitfx], "all passed"),
        ("exe_startup", [PY, os.path.join("tests", "exe_startup.py"), NEXT_EXE], "all passed"),
    ]
    for name, cmd, ok_text in suites:
        ok, last = run(name, cmd, log_dir, ok_text)
        status = "ok"
        if not ok:
            ok, last = run(name + "-retry", cmd, log_dir, ok_text)
            status = "passed on retry" if ok else "FAILED"
        results.append((name, status, last))
    return summary(results, log_dir)


def summary(results, log_dir):
    print("\n=== summary ===")
    for step, status, detail in results:
        print(f"  {step:<16} {status:<16} {detail}")
    h = swap_dist.sha256(NEXT_EXE)
    print(f"  dist-next\\reado.exe SHA256 {h}")
    print(f"  logs {log_dir}")
    bad = [r for r in results if r[1] == "FAILED"]
    if not bad and h:
        print(f"\nall passed. Into dist (see docs/RELEASE.md):\n  python scripts/swap_dist.py --apply --expect {h}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
