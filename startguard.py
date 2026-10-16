"""Start-up guards for the desktop launcher (reado.py).

- watchdog: if the main window has not been shown within the time limit, write
  startup.log (every thread's stack, what asked for WMI) and end the process,
  instead of hanging on invisibly. A window that never showed has no unsaved edits.
- process helpers for the second launch: is the instance named in instance.json
  still alive, is it really that ReadO (image name, start time; PIDs are reused),
  and ending one that never showed its window.
Plain ctypes (kernel32) — no WMI, psutil or tasklist.
"""
import os
import sys
import threading
import time
import traceback

STARTUP_TIMEOUT = 20.0  # seconds until the window must be shown
LOG_MAX = 256 * 1024    # startup.log is trimmed to its newest part beyond this


def timeout_from_env(default=STARTUP_TIMEOUT):
    """READO_STARTUP_TIMEOUT (seconds; 0 turns the watchdog off — tests only)."""
    try:
        v = float(os.environ.get("READO_STARTUP_TIMEOUT", default))
    except ValueError:
        return default
    return max(0.0, v)


def append_log(path, text):
    try:
        old = ""
        if os.path.exists(path) and os.path.getsize(path) > LOG_MAX:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                old = f.read()[-LOG_MAX // 2:]
        with open(path, "w" if old else "a", encoding="utf-8") as f:
            f.write(old + text)
    except OSError:
        pass


def thread_dump():
    names = {t.ident: t.name for t in threading.enumerate()}
    out = []
    for ident, frame in sys._current_frames().items():
        out.append(f"--- thread {names.get(ident, '?')} ({ident})\n" + "".join(traceback.format_stack(frame)))
    return "\n".join(out)


def hard_exit(code):
    """End now. A thread stuck in a native call can hold the loader lock, and
    ExitProcess (os._exit) would wait for it; TerminateProcess does not."""
    if os.name == "nt":
        import ctypes
        k32 = ctypes.windll.kernel32
        k32.GetCurrentProcess.restype = ctypes.c_void_p
        k32.TerminateProcess(ctypes.c_void_p(k32.GetCurrentProcess()), code)
    os._exit(code)


class Watchdog:
    """shown() before the time limit, or the process logs and ends."""

    def __init__(self, timeout, log_path, on_fire=None, exit_code=3):
        self.timeout, self.log_path, self.on_fire, self.exit_code = timeout, log_path, on_fire, exit_code
        self.stage = "starting"
        self.t0 = time.time()
        self._shown = threading.Event()

    def start(self):
        if self.timeout > 0:
            threading.Thread(target=self._run, name="startup-watchdog", daemon=True).start()
        return self

    def shown(self):
        self._shown.set()

    def is_shown(self):
        return self._shown.is_set()

    def _run(self):
        # measured from t0, which the launcher moves on after waiting for another instance
        while not self._shown.wait(0.25):
            if time.time() - self.t0 >= self.timeout:
                break
        else:
            return
        try:
            import nowmi
            wmi = ", ".join(nowmi.blocked) or "none"
        except Exception:
            wmi = "?"
        append_log(self.log_path() if callable(self.log_path) else self.log_path,
                   f"\n=== {time.strftime('%Y-%m-%d %H:%M:%S')}  no window after {self.timeout:.0f} s — ending (pid {os.getpid()})\n"
                   f"exe: {sys.executable}\nstage: {self.stage}\nWMI requests refused: {wmi}\n{thread_dump()}\n")
        if self.on_fire:
            try:
                self.on_fire()
            except Exception:
                pass
        hard_exit(self.exit_code)


# ----- other processes (the instance a second launch finds) -----

_SYNCHRONIZE, _QUERY_LIMITED, _TERMINATE = 0x00100000, 0x1000, 0x0001


def _k32():
    import ctypes
    from ctypes import wintypes as wt
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.OpenProcess.restype = wt.HANDLE
    k.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
    k.CloseHandle.argtypes = [wt.HANDLE]
    k.WaitForSingleObject.argtypes = [wt.HANDLE, wt.DWORD]
    k.WaitForSingleObject.restype = wt.DWORD
    k.TerminateProcess.argtypes = [wt.HANDLE, wt.UINT]
    k.QueryFullProcessImageNameW.argtypes = [wt.HANDLE, wt.DWORD, wt.LPWSTR, ctypes.POINTER(wt.DWORD)]
    k.GetProcessTimes.argtypes = [wt.HANDLE] + [ctypes.POINTER(wt.FILETIME)] * 4
    return ctypes, wt, k


def pid_alive(pid):
    if os.name != "nt":
        try:
            os.kill(int(pid), 0)
            return True
        except (OSError, ValueError):
            return False
    ctypes, wt, k = _k32()
    h = k.OpenProcess(_SYNCHRONIZE | _QUERY_LIMITED, False, int(pid))
    if not h:
        return ctypes.get_last_error() == 5  # access denied: it exists (another user's); else gone
    try:
        return k.WaitForSingleObject(h, 0) == 0x102  # WAIT_TIMEOUT: still running
    finally:
        k.CloseHandle(h)


def process_info(pid):
    """(image path, start time as a Unix timestamp) or (None, None)."""
    if os.name != "nt":
        return None, None
    ctypes, wt, k = _k32()
    h = k.OpenProcess(_QUERY_LIMITED, False, int(pid))
    if not h:
        return None, None
    try:
        buf = ctypes.create_unicode_buffer(1024)
        n = wt.DWORD(1024)
        image = buf.value if k.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)) else None
        c, e, kt, ut = wt.FILETIME(), wt.FILETIME(), wt.FILETIME(), wt.FILETIME()
        started = None
        if k.GetProcessTimes(h, ctypes.byref(c), ctypes.byref(e), ctypes.byref(kt), ctypes.byref(ut)):
            started = ((c.dwHighDateTime << 32) | c.dwLowDateTime) / 1e7 - 11644473600
        return image, started
    finally:
        k.CloseHandle(h)


def is_same_instance(pid, exe, started, slack=60.0):
    """The process is the one instance.json describes: same program file name and
    started when the file says (a reused PID belongs to some other program or time)."""
    image, t = process_info(pid)
    if not image or t is None:
        return False
    if exe and os.path.basename(image).lower() != os.path.basename(exe).lower():
        return False
    return started is None or abs(t - float(started)) < slack


def terminate(pid, wait=5.0):
    if os.name != "nt":
        return False
    ctypes, wt, k = _k32()
    h = k.OpenProcess(_TERMINATE | _SYNCHRONIZE, False, int(pid))
    if not h:
        return False
    try:
        ok = bool(k.TerminateProcess(h, 4))
        k.WaitForSingleObject(h, int(wait * 1000))
        return ok
    finally:
        k.CloseHandle(h)
