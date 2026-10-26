"""
Put a tested build into dist: dist-next\\reado.exe -> dist\\reado.exe, the old one -> dist-prev.

    python scripts/swap_dist.py                 # dry run: says what it would do, changes nothing
    python scripts/swap_dist.py --apply         # do it
    python scripts/swap_dist.py --apply --expect <sha256 of dist-next\\reado.exe>

Steps (--apply), see docs/RELEASE.md:
  1. dist-next\\reado.exe must exist; with --expect its SHA256 must match. Same hash as
     dist\\reado.exe: already swapped, nothing to do.
  2. A ReadO running from dist, dist-prev or dist-next gets a normal close (WM_CLOSE to its
     windows), never a kill. If it asks "unsaved changes - quit without saving?", the
     script answers Cancel (the edits stay) and stops. Still running after the wait:
     stops and names the PID.
  3. dist\\reado.exe -> dist-prev\\reado.exe (overwritten), dist-next\\reado.exe -> dist,
     each copy checked by SHA256.
  4. dist-next and the build work folders (build, build-dist-next) are removed, so only
     dist and dist-prev are left.
Exit code: 0 done (or nothing to do / dry run), 1 stopped before changing anything,
2 failed while copying (the message says what state dist is in).
"""
import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import startguard  # noqa: E402  (process_info, pid_alive)

EXE = "reado.exe"
DIST, PREV, NEXT = (os.path.join(ROOT, d) for d in ("dist", "dist-prev", "dist-next"))
WORK_DIRS = [os.path.join(ROOT, d) for d in ("build", "build-dist-next")]
CLOSE_WAIT = 30  # seconds for a normal close


def sha256(path):
    if not os.path.isfile(path):
        return None
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest().upper()


def short(h):
    return h[:16] + "…" if h else "(none)"


def git_head():
    try:
        return subprocess.run(["git", "-C", ROOT, "log", "-1", "--format=%h %s"],
                              capture_output=True, text=True, timeout=10).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "?"


# ----- running ReadO processes (Windows) -----

def _all_pids():
    import ctypes
    from ctypes import wintypes as wt
    psapi = ctypes.WinDLL("psapi")
    n = 4096
    while True:
        arr = (wt.DWORD * n)()
        got = wt.DWORD()
        if not psapi.EnumProcesses(arr, ctypes.sizeof(arr), ctypes.byref(got)):
            return []
        count = got.value // ctypes.sizeof(wt.DWORD)
        if count < n:
            return [arr[i] for i in range(count) if arr[i]]
        n *= 2


def running_from(folders):
    """{pid: image path} of processes whose program file is in one of the folders."""
    want = {os.path.normcase(os.path.realpath(f)) for f in folders}  # realpath: long names, no 8.3
    found = {}
    for pid in _all_pids():
        image, _ = startguard.process_info(pid)
        if image and os.path.normcase(os.path.dirname(os.path.realpath(image))) in want:
            found[pid] = image
    return found


def _user32():
    import ctypes
    from ctypes import wintypes as wt
    u = ctypes.WinDLL("user32", use_last_error=True)
    u.EnumWindows.argtypes = [ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM), wt.LPARAM]
    u.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
    u.GetClassNameW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
    u.IsWindowVisible.argtypes = [wt.HWND]
    u.GetWindow.argtypes = [wt.HWND, wt.UINT]
    u.GetWindow.restype = wt.HWND
    u.PostMessageW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
    return ctypes, wt, u


def windows_of(pids):
    """[(hwnd, pid, class name, owner hwnd)] of the visible top-level windows of these processes."""
    ctypes, wt, u = _user32()
    out = []

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def each(hwnd, _):
        pid = wt.DWORD()
        u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value in pids and u.IsWindowVisible(hwnd):
            buf = ctypes.create_unicode_buffer(256)
            u.GetClassNameW(hwnd, buf, 256)
            out.append((hwnd, pid.value, buf.value, u.GetWindow(hwnd, 4)))  # GW_OWNER
        return True

    u.EnumWindows(each, 0)
    return out


def close_normally(pids):
    """WM_CLOSE to each app window, then wait. Returns (closed, reason): the unsaved-changes
    box is answered with Cancel, so the window and its edits stay."""
    ctypes, wt, u = _user32()
    WM_CLOSE, WM_COMMAND, IDCANCEL = 0x0010, 0x0111, 2
    for hwnd, pid, cls, owner in windows_of(pids):
        if cls != "#32770":  # not a dialog box
            u.PostMessageW(hwnd, WM_CLOSE, 0, 0)
    end = time.time() + CLOSE_WAIT
    while time.time() < end:
        alive = [p for p in pids if startguard.pid_alive(p)]
        if not alive:
            return True, ""
        boxes = [w for w in windows_of(set(alive)) if w[2] == "#32770"]
        if boxes:
            for hwnd, *_ in boxes:
                u.PostMessageW(hwnd, WM_COMMAND, IDCANCEL, 0)
            return False, (f"ReadO (PID {', '.join(str(b[1]) for b in boxes)}) has unsaved changes: "
                           "the quit was cancelled, its window and edits are as they were")
        time.sleep(0.25)
    alive = [p for p in pids if startguard.pid_alive(p)]
    return False, f"ReadO still running after {CLOSE_WAIT} s (PID {', '.join(map(str, alive))}); close it yourself"


# ----- the swap -----

def main():
    ap = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    ap.add_argument("--apply", action="store_true", help="really swap (default: dry run)")
    ap.add_argument("--expect", help="SHA256 dist-next\\reado.exe must have")
    a = ap.parse_args()
    dry = not a.apply
    say = print
    tag = "[dry run] " if dry else ""

    new, cur, prev = (sha256(os.path.join(d, EXE)) for d in (NEXT, DIST, PREV))
    say(f"HEAD       {git_head()}")
    say(f"dist-next  {short(new)}")
    say(f"dist       {short(cur)}")
    say(f"dist-prev  {short(prev)}")
    if not new:
        say("stop: dist-next\\reado.exe is missing (build.bat dist-next, then the tests)")
        return 1
    if a.expect and a.expect.strip().upper() != new:
        say(f"stop: dist-next\\reado.exe is {new}, not the expected {a.expect.strip().upper()}")
        return 1
    if new == cur:
        say("nothing to do: dist already has this build")
        return 0

    running = running_from([DIST, PREV, NEXT]) if os.name == "nt" else {}
    for pid, image in sorted(running.items()):
        say(f"{tag}running: PID {pid}  {image}  -> normal close (WM_CLOSE); unsaved changes stop the swap")
    say(f"{tag}copy dist\\{EXE} -> dist-prev\\{EXE}" if cur else f"{tag}no dist\\{EXE} yet: nothing to back up")
    say(f"{tag}copy dist-next\\{EXE} -> dist\\{EXE}, check SHA256 {short(new)}")
    leftovers = [d for d in [NEXT] + WORK_DIRS if os.path.exists(d)]
    for d in leftovers:
        say(f"{tag}remove {os.path.relpath(d, ROOT)}\\")
    if dry:
        say("dry run: nothing changed. Run with --apply to swap.")
        return 0

    if running:
        ok, why = close_normally(set(running))
        if not ok:
            say("stop: " + why + ". Nothing was changed.")
            return 1
        say(f"closed: PID {', '.join(map(str, sorted(running)))}")

    try:
        if cur:
            os.makedirs(PREV, exist_ok=True)
            shutil.copy2(os.path.join(DIST, EXE), os.path.join(PREV, EXE))
            if sha256(os.path.join(PREV, EXE)) != cur:
                raise OSError("dist-prev copy does not match the old dist")
        os.makedirs(DIST, exist_ok=True)
        shutil.copy2(os.path.join(NEXT, EXE), os.path.join(DIST, EXE))
        if sha256(os.path.join(DIST, EXE)) != new:
            raise OSError("dist copy does not match dist-next")
    except OSError as e:
        state = sha256(os.path.join(DIST, EXE))
        say(f"failed: {e}. dist\\{EXE} is now {short(state)} "
            f"({'the old build' if state == cur else 'the new build' if state == new else 'damaged: copy dist-prev back'}); "
            "dist-next was kept.")
        return 2
    for d in leftovers:
        shutil.rmtree(d, ignore_errors=True)
    left = [d for d in leftovers if os.path.exists(d)]
    say(f"done: dist {short(new)}, dist-prev {short(cur) if cur else short(prev)}")
    say(f"SHA256 dist\\{EXE}: {new}")
    if left:
        say("could not remove (in use?): " + ", ".join(os.path.relpath(d, ROOT) for d in left))
    return 0


if __name__ == "__main__":
    sys.exit(main())
