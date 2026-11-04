"""
Put a tested build into dist: dist-next\\reado.exe -> dist\\reado.exe, the old one -> dist-prev.

    python scripts/swap_dist.py                 # dry run: says what it would do, changes nothing
    python scripts/swap_dist.py --apply         # do it
    python scripts/swap_dist.py --apply --expect <sha256 of dist-next\\reado.exe>
    python scripts/swap_dist.py --apply --expect <sha256> --restart   # then start the new dist exe

Steps (--apply), see docs/RELEASE.md:
  1. dist-next\\reado.exe must exist; with --expect its SHA256 must match. Same hash as
     dist\\reado.exe: already swapped, nothing to do.
  2. A ReadO running from dist, dist-prev or dist-next gets a normal close (WM_CLOSE to its
     windows), never a kill. Found by its program file's folder, plus the PID ReadO wrote in
     %APPDATA%\\ReadO\\instance.json when that process runs from one of those folders.
     If it asks "unsaved changes - quit without saving?", the script answers Cancel (the
     edits stay) and stops. Still running after the wait:
     stops and names the PID.
  3. dist\\reado.exe -> dist-prev\\reado.exe (overwritten), dist-next\\reado.exe -> dist,
     each copy checked by SHA256.
  4. dist-next and the build work folders (build, build-dist-next) are removed, so only
     dist and dist-prev are left.
  5. --restart: start dist\\reado.exe the way a double-click does (this user's APPDATA, so the
     last folder comes back; not isolated) and wait until instance.json says its window is
     shown. With "nothing to do", --restart starts it only when no ReadO runs from dist.
     Not done when step 2 stopped (the old window is still there).
Exit code: 0 done (or nothing to do / dry run), 1 stopped before changing anything,
2 failed while copying (the message says what state dist is in), 3 swapped but the
restarted window did not come up within RESTART_WAIT.
"""
import argparse
import hashlib
import json
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
CLOSE_WAIT = 90  # seconds for a normal close (an app open for hours took over 30 s to exit)
RESTART_WAIT = 60  # seconds for the restarted window to be shown


def instance_path():
    """instance.json of the exe started with this environment (reado.writable_root)."""
    return os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "ReadO", "instance.json")


def read_instance():
    try:
        with open(instance_path(), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else None
    except (OSError, ValueError):
        return None


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


def recorded_instance(folders):
    """{pid: image} for the ReadO that instance.json names, when that process is alive, is
    the one the file describes (program name, start time) and runs from one of the folders."""
    inst = read_instance() or {}
    pid = inst.get("pid")
    if not isinstance(pid, int) or not startguard.pid_alive(pid):
        return {}
    if not startguard.is_same_instance(pid, inst.get("exe"), inst.get("started")):
        return {}
    image, _ = startguard.process_info(pid)
    want = {os.path.normcase(os.path.realpath(f)) for f in folders}
    if image and os.path.normcase(os.path.dirname(os.path.realpath(image))) in want:
        return {pid: image}
    return {}


def start_and_wait(exe, say):
    """Start exe detached (cwd = its folder, as a double-click does) and wait until
    instance.json names a live process of that exe whose window is shown. Returns ok."""
    flags = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith(("_MEI", "_PYI"))}
    t0 = time.time()
    kw = dict(cwd=os.path.dirname(exe), env=env, close_fds=True, stdin=subprocess.DEVNULL,
              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        p = subprocess.Popen([exe], creationflags=flags | 0x01000000, **kw)  # + BREAKAWAY_FROM_JOB
    except OSError:
        p = subprocess.Popen([exe], creationflags=flags, **kw)  # the job does not allow breakaway
    say(f"restart: started {exe} (PID {p.pid}), instance file {instance_path()}")
    want = os.path.normcase(os.path.realpath(exe))
    end = t0 + RESTART_WAIT
    while time.time() < end:
        inst = read_instance() or {}
        pid = inst.get("pid")
        if (inst.get("shown") and isinstance(pid, int) and startguard.pid_alive(pid)
                and os.path.normcase(os.path.realpath(inst.get("exe") or "")) == want
                and float(inst.get("started") or 0) >= t0 - 2):
            say(f"restart: window shown (PID {pid}, port {inst.get('port')})")
            return True
        if p.poll() is not None and not startguard.pid_alive(pid or 0):
            say(f"restart: the exe exited with code {p.returncode} before its window was shown")
            return False
        time.sleep(0.5)
    say(f"restart: no shown window after {RESTART_WAIT} s (see startup.log next to instance.json)")
    return False


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
    ap.add_argument("--restart", action="store_true",
                    help="after the swap start dist\\reado.exe (this user's APPDATA) and wait for its window")
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
    folders = [DIST, PREV, NEXT]
    dist_exe = os.path.join(DIST, EXE)
    if new == cur:
        say("nothing to do: dist already has this build")
        if a.restart and not dry and os.name == "nt":
            if running_from([DIST]) or recorded_instance([DIST]):
                say("restart: ReadO from dist is already running")
            elif not start_and_wait(dist_exe, say):
                return 3
        return 0

    running = {}
    if os.name == "nt":
        running = running_from(folders)
        running.update(recorded_instance(folders))
    for pid, image in sorted(running.items()):
        say(f"{tag}running: PID {pid}  {image}  -> normal close (WM_CLOSE); unsaved changes stop the swap")
    say(f"{tag}copy dist\\{EXE} -> dist-prev\\{EXE}" if cur else f"{tag}no dist\\{EXE} yet: nothing to back up")
    say(f"{tag}copy dist-next\\{EXE} -> dist\\{EXE}, check SHA256 {short(new)}")
    leftovers = [d for d in [NEXT] + WORK_DIRS if os.path.exists(d)]
    for d in leftovers:
        say(f"{tag}remove {os.path.relpath(d, ROOT)}\\")
    if a.restart:
        say(f"{tag}start dist\\{EXE} (APPDATA {os.environ.get('APPDATA', '~')}) and wait for its window")
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
        if a.restart and state in (cur, new) and state:
            start_and_wait(dist_exe, say)
        return 2
    for d in leftovers:
        shutil.rmtree(d, ignore_errors=True)
    left = [d for d in leftovers if os.path.exists(d)]
    say(f"done: dist {short(new)}, dist-prev {short(cur) if cur else short(prev)}")
    say(f"SHA256 dist\\{EXE}: {new}")
    if left:
        say("could not remove (in use?): " + ", ".join(os.path.relpath(d, ROOT) for d in left))
    if a.restart and not start_and_wait(dist_exe, say):
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
