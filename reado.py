"""
ReadO — desktop launcher.
Starts the local HTTP server in a thread and opens a native WebView2 window.
"""
import nowmi  # noqa: F401  first: no WMI queries in this process (see nowmi.py)
import json
import os
import re
import shutil
import sys
import threading
import time
import urllib.request

import startguard

_T0 = time.time()
# no window within READO_STARTUP_TIMEOUT (20 s): startup.log + exit, not an invisible hang.
# Started only for the app itself (tests import this module).
WATCHDOG = startguard.Watchdog(startguard.timeout_from_env(), lambda: os.path.join(writable_root(), "startup.log"),
                               on_fire=lambda: remove_instance_file())
if __name__ == "__main__":
    WATCHDOG.start()
    WATCHDOG.stage = "imports"

import webview  # noqa: E402


def app_root():
    if getattr(sys, "frozen", False):
        return sys._MEIPASS
    return os.path.dirname(os.path.abspath(__file__))


def writable_root():
    """Where config.json lives.

    Not next to the exe: build.bat wipes dist/ on every rebuild, which took the
    user's settings with it. %APPDATA%\\ReadO survives rebuilds and moves.
    Running from source keeps using the repo dir (it is gitignored).
    """
    if getattr(sys, "frozen", False):
        base = os.path.join(os.environ.get("APPDATA")
                            or os.path.expanduser("~"), "ReadO")
        os.makedirs(base, exist_ok=True)
        return base
    return os.path.dirname(os.path.abspath(__file__))


def migrate_legacy_config(new_path):
    """One-off: carry over a config.json left next to the exe by older builds."""
    if os.path.exists(new_path) or not getattr(sys, "frozen", False):
        return
    old = os.path.join(os.path.dirname(sys.executable), "config.json")
    if not os.path.exists(old):
        return
    try:
        shutil.copyfile(old, new_path)
    except OSError:
        pass


sys.path.insert(0, app_root())
import server  # noqa: E402
import gitview  # noqa: E402

server.ROOT = app_root()
server.HTML_PATH = os.path.join(app_root(), "source.html")
server.VENDOR_PATH = os.path.join(app_root(), "vendor")
server.CONFIG_PATH = os.path.join(writable_root(), "config.json")
migrate_legacy_config(server.CONFIG_PATH)
# evaluate first-run *before* ensure_config() writes the file, so the UI still
# gets first_run=True on the very first launch
server._first_run = not os.path.exists(server.CONFIG_PATH)
server.ensure_config()
server.SETTINGS = server.load_settings()

HOST = "127.0.0.1"
PREFERRED_PORT = 8766
PORT = PREFERRED_PORT  # the port actually bound (any free one if 8766 is taken)
INSTANCE_PATH = os.path.join(writable_root(), "instance.json")


def cli_files():
    return [os.path.abspath(a) for a in sys.argv[1:] if not a.startswith("-")]


STARTUP_GRACE = 5.0  # a second launch waits up to the first one's start-up limit + this for its window


def _read_instance():
    try:
        with open(INSTANCE_PATH, "r", encoding="utf-8") as f:
            inst = json.load(f)
        return inst if isinstance(inst, dict) else None
    except (OSError, ValueError):
        return None


def _drop_instance_file(pid):
    try:
        if (_read_instance() or {}).get("pid") == pid:
            os.remove(INSTANCE_PATH)
    except OSError:
        pass


def _log(text):  # startup.log next to instance.json (%APPDATA%\ReadO for the exe)
    startguard.append_log(os.path.join(os.path.dirname(INSTANCE_PATH), "startup.log"),
                          f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {text}\n")


def usable_instance():
    """The running instance from instance.json that can take our files, or None.

    Gone (crashed, killed): the file is dropped. Still starting (window not shown
    yet): wait for it, up to its start-up limit + STARTUP_GRACE. Never showed its
    window by then: it is stuck before the window (its watchdog should have ended
    it) — that process is ended (it is checked to be that ReadO, and a window that
    never showed has no unsaved edits) and we start on our own. Files from builds
    without the "shown" field are used as before."""
    inst = _read_instance()
    if not inst or "pid" not in inst:
        return None
    pid = int(inst["pid"])
    if pid == os.getpid():  # our own file (tests): never waited for or ended
        return inst
    if not startguard.pid_alive(pid):
        _drop_instance_file(pid)
        return None
    if "shown" not in inst or inst.get("shown"):
        return inst
    limit = startguard.timeout_from_env() or startguard.STARTUP_TIMEOUT
    deadline = float(inst.get("started") or time.time()) + limit + STARTUP_GRACE
    while time.time() < deadline:
        WATCHDOG.t0 = time.time()  # waiting for the other one is not our own start-up
        time.sleep(0.25)
        cur = _read_instance()
        if not cur or cur.get("pid") != pid or not startguard.pid_alive(pid):
            _drop_instance_file(pid)
            return None
        if cur.get("shown"):
            return cur
    if startguard.is_same_instance(pid, inst.get("exe"), inst.get("started")):
        _log(f"pid {pid} (started {time.strftime('%H:%M:%S', time.localtime(float(inst.get('started') or 0)))}) "
             f"never showed its window — ended by a new launch (pid {os.getpid()})")
        startguard.terminate(pid)
    _drop_instance_file(pid)
    return None


def forward_to_running(paths):
    """If a ReadO is already running (instance.json names its port and
    secrets), hand it our files and return True. A stale file (crashed
    instance, port reused by something else) fails fast and returns False;
    an instance that never showed its window is passed over (usable_instance)."""
    inst = usable_instance()
    if not inst:
        return False
    try:
        if os.name == "nt":  # let it bring its window to the front
            import ctypes
            ctypes.windll.user32.AllowSetForegroundWindow(int(inst["pid"]))
        req = urllib.request.Request(
            f"http://{HOST}:{int(inst['port'])}/api/open-request",
            data=json.dumps({"ipc": inst["ipc"], "paths": paths}).encode("utf-8"),
            headers={"Content-Type": "application/json", server.TOKEN_HEADER: inst["token"]},
            method="POST")
        with urllib.request.urlopen(req, timeout=3) as r:
            return r.status == 200
    except Exception:
        return False


def write_instance_file(shown=False):
    # per-user location (%APPDATA%\ReadO for the exe): lets a second launch
    # reach /api/open-request; the page itself never sees the IPC secret.
    # "shown" turns true once the window is up (a second launch waits for that).
    try:
        with open(INSTANCE_PATH, "w", encoding="utf-8") as f:
            json.dump({"pid": os.getpid(), "port": PORT, "token": server.CSRF_TOKEN,
                       "ipc": server.IPC_SECRET, "started": _T0, "exe": sys.executable, "shown": bool(shown)}, f)
    except OSError:
        pass


def remove_instance_file():
    try:
        with open(INSTANCE_PATH, "r", encoding="utf-8") as f:
            if json.load(f).get("pid") != os.getpid():
                return
        os.remove(INSTANCE_PATH)
    except (OSError, ValueError):
        pass


def wait_ready(timeout=8.0):
    end = time.time() + timeout
    while time.time() < end:
        try:
            with urllib.request.urlopen(f"http://{HOST}:{PORT}/api/settings", timeout=0.5) as r:
                if r.status == 200:
                    return True
        except Exception:
            time.sleep(0.1)
    return False


class Api:
    dirty = 0  # unsaved tabs, reported by the page

    def pick_dir(self, current=""):
        win = webview.windows[0] if webview.windows else None
        if not win:
            return None
        result = win.create_file_dialog(webview.FileDialog.FOLDER, directory=current or "")
        if not result:
            return None
        return result[0] if isinstance(result, (list, tuple)) else result

    def open_files(self):
        """Native open dialog; the chosen files become readable/writable."""
        win = webview.windows[0] if webview.windows else None
        if not win:
            return []
        result = win.create_file_dialog(webview.FileDialog.OPEN, allow_multiple=True)
        return [k for k in (server.grant_external(p) for p in (result or [])) if k]

    def set_dirty(self, count):
        Api.dirty = int(count or 0)

    def assoc_status(self):
        return assoc_status()

    def assoc_register(self):
        return register_assoc()

    def assoc_unregister(self):
        return unregister_assoc()

    def reveal(self, key):
        """Show a file or folder of the working folder (or an opened outside file) in Explorer."""
        full = server.resolve_read_path(str(key or "")) if key else server.base_root()
        if not full or not os.path.exists(full) or os.name != "nt":
            return False
        import subprocess
        subprocess.Popen(["explorer", "/select," + os.path.normpath(full)])
        return True

    # --- the page's title bar (see NativeFrame) ---
    def win_state(self):
        return {"maximized": NativeFrame.maximized(), "frame": NativeFrame.active(),
                "webview_moves": NativeFrame.moves, "webview_refreshes": NativeFrame.refreshes,
                "wmi_refused": list(nowmi.blocked), "startup": WATCHDOG.stage}

    def win_minimize(self):
        NativeFrame.syscommand(0xF020)  # SC_MINIMIZE (keeps the animation)

    def win_toggle_maximize(self):
        NativeFrame.syscommand(0xF120 if NativeFrame.maximized() else 0xF030)  # SC_RESTORE / SC_MAXIMIZE

    def win_close(self):
        NativeFrame.post(0x0010)  # WM_CLOSE: the closing handler asks about unsaved files

    def win_background(self, color):
        """The theme's background behind the page (form + WebView2): what shows
        in the newly exposed area while the page catches up after maximize / resize."""
        NativeFrame.set_background(color)

    def win_drag(self):
        NativeFrame.track(2)  # HTCAPTION: Windows' move loop (Aero Snap, drag off maximized)

    def win_resize(self, edge):
        ht = NativeFrame.EDGES.get(str(edge))
        if ht:
            NativeFrame.track(ht)


class NativeFrame:
    """No native caption or borders, native behaviour otherwise.

    The window keeps its normal styles (WS_THICKFRAME, WS_CAPTION, min/max
    boxes), so Windows still animates it, snaps it (drag to a screen edge,
    Win+arrows) and draws its shadow; WM_NCCALCSIZE only hands the whole
    window to the client area, where the page draws its own title bar. Moving
    and edge resizing start from the page: WM_NCLBUTTONDOWN with HTCAPTION /
    HTLEFT … runs Windows' own move / size loop on the GUI thread."""
    EDGES = {"n": 12, "s": 15, "w": 10, "e": 11, "nw": 13, "ne": 14, "sw": 16, "se": 17}
    hwnd = 0
    form = None
    _proc = None  # keeps the ctypes callback alive
    _old = None
    _monitor = None
    _ctl_field = None
    moves = refreshes = 0  # parent-moved notifications / re-layouts sent to WebView2 (checked by the smoke test)

    @classmethod
    def _api(cls):
        import ctypes
        from ctypes import wintypes as wt
        u = ctypes.windll.user32
        u.CallWindowProcW.restype = ctypes.c_ssize_t
        u.CallWindowProcW.argtypes = [ctypes.c_void_p, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
        u.SetWindowLongPtrW.restype = ctypes.c_void_p
        u.SetWindowLongPtrW.argtypes = [wt.HWND, ctypes.c_int, ctypes.c_void_p]
        u.PostMessageW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
        u.SendMessageW.restype = ctypes.c_ssize_t
        u.SendMessageW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
        u.MonitorFromWindow.restype = wt.HMONITOR
        u.MonitorFromWindow.argtypes = [wt.HWND, wt.DWORD]
        u.MonitorFromRect.restype = wt.HMONITOR
        u.MonitorFromRect.argtypes = [ctypes.POINTER(wt.RECT), wt.DWORD]
        return ctypes, wt, u

    @classmethod
    def install(cls, win):
        if os.name != "nt" or cls._proc:
            return
        try:
            ctypes, wt, u = cls._api()
            cls.form = win.native
            hwnd = cls.hwnd = int(win.native.Handle.ToInt64())

            class MONITORINFO(ctypes.Structure):
                _fields_ = [("cbSize", wt.DWORD), ("rcMonitor", wt.RECT), ("rcWork", wt.RECT), ("dwFlags", wt.DWORD)]

            WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)
            WM_NCCALCSIZE, WM_NCACTIVATE = 0x0083, 0x0086
            WM_MOVE, WM_EXITSIZEMOVE, WM_DISPLAYCHANGE, WM_DPICHANGED = 0x0003, 0x0232, 0x007E, 0x02E0

            def proc(h, msg, wp, lp):
                if msg == WM_NCCALCSIZE:
                    if wp and u.IsZoomed(h):  # maximized: fill the work area, not the screen + frame
                        # the monitor of the *new* window rect (rgrc[0]): a maximized window moved to
                        # another monitor (Win+Shift+arrow, display changes) is still on the old one
                        # here, and its work area would leave the new window without a client area (white)
                        new = ctypes.cast(lp, ctypes.POINTER(wt.RECT))
                        mi = MONITORINFO()
                        mi.cbSize = ctypes.sizeof(MONITORINFO)
                        if u.GetMonitorInfoW(u.MonitorFromRect(new, 2), ctypes.byref(mi)):
                            new[0] = mi.rcWork
                    return 0  # no non-client area
                if msg == WM_NCACTIVATE:  # do not paint a caption on (de)activation
                    return u.CallWindowProcW(cls._old, h, msg, wp, -1)
                if msg in (WM_MOVE, WM_EXITSIZEMOVE, WM_DISPLAYCHANGE, WM_DPICHANGED):
                    r = u.CallWindowProcW(cls._old, h, msg, wp, lp)
                    mon = u.MonitorFromWindow(h, 2)
                    cls.webview_moved(not u.IsIconic(h) and (mon != cls._monitor or msg in (WM_DISPLAYCHANGE, WM_DPICHANGED)))
                    cls._monitor = mon
                    return r
                return u.CallWindowProcW(cls._old, h, msg, wp, lp)

            cls._monitor = u.MonitorFromWindow(hwnd, 2)
            cls._proc = WNDPROC(proc)
            cls._old = u.SetWindowLongPtrW(hwnd, -4, ctypes.cast(cls._proc, ctypes.c_void_p))  # GWLP_WNDPROC
            # WS_THICKFRAME | WS_CAPTION | WS_SYSMENU | WS_MINIMIZEBOX | WS_MAXIMIZEBOX: snap, Win+arrows, animations
            u.SetWindowLongW(hwnd, -16, u.GetWindowLongW(hwnd, -16) | 0x00040000 | 0x00C00000 | 0x00080000 | 0x00020000 | 0x00010000)
            # SWP_FRAMECHANGED | NOMOVE | NOSIZE | NOZORDER | NOACTIVATE: recompute the frame now
            u.SetWindowPos(hwnd, None, 0, 0, 0, 0, 0x0020 | 0x0002 | 0x0001 | 0x0004 | 0x0010)
        except Exception:
            cls._proc = None  # keep the native caption: the window still works
        try:
            win.run_js("window.readoWinSync && window.readoWinSync()")
        except Exception:
            pass

    @classmethod
    def webview_moved(cls, refresh, form=None):
        """WebView2 runs in its own process and only hears about its *own* HWND
        moving; when the form moves (another monitor) it must be told, or it keeps
        rendering for the old position and the window can go blank / white. On a
        monitor (or display / DPI) change its bounds are also re-applied, so it
        lays out and paints again for the new screen. Runs on the GUI thread."""
        form = form or cls.form
        try:
            web = getattr(form, "webview", None)
            if web is None:
                return
            if cls._ctl_field is None:
                from System.Reflection import BindingFlags
                cls._ctl_field = web.GetType().GetField("_coreWebView2Controller", BindingFlags.NonPublic | BindingFlags.Instance) or False
            ctl = cls._ctl_field.GetValue(web) if cls._ctl_field else None
            if ctl is None:
                return
            ctl.NotifyParentWindowPositionChanged()
            cls.moves += 1
            if not refresh:
                return

            def again():
                try:
                    from System.Drawing import Rectangle
                    b = ctl.Bounds
                    ctl.Bounds = Rectangle(b.X, b.Y, b.Width, b.Height + 1)
                    ctl.Bounds = b
                    ctl.NotifyParentWindowPositionChanged()
                    web.Invalidate()
                    cls.refreshes += 1
                except Exception:
                    pass
            from System import Action
            form.BeginInvoke(Action(again))  # after the move message, not inside it
        except Exception:
            pass

    @classmethod
    def follow(cls, form):
        """The same notice for a window without NativeFrame (diff windows), from Form.Move."""
        if os.name != "nt":
            return
        try:
            u = cls._api()[2]
            last = [u.MonitorFromWindow(int(form.Handle.ToInt64()), 2)]

            def moved(sender, e):
                try:
                    mon = u.MonitorFromWindow(int(form.Handle.ToInt64()), 2)
                    cls.webview_moved(mon != last[0] and str(form.WindowState) != "Minimized", form)
                    last[0] = mon
                except Exception:
                    pass
            form.Move += moved
        except Exception:
            pass

    @classmethod
    def active(cls):
        return bool(cls._proc)

    @classmethod
    def maximized(cls):
        if not cls.hwnd:
            return False
        import ctypes
        return bool(ctypes.windll.user32.IsZoomed(cls.hwnd))

    @classmethod
    def post(cls, msg, wp=0, lp=0):
        if cls.hwnd:
            cls._api()[2].PostMessageW(cls.hwnd, msg, wp, lp)

    @classmethod
    def syscommand(cls, sc):
        cls.post(0x0112, sc)  # WM_SYSCOMMAND

    @classmethod
    def set_background(cls, color):
        color = str(color or "")
        if not cls.form or not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
            return

        def go():
            from System.Drawing import Color, ColorTranslator
            cls.form.BackColor = ColorTranslator.FromHtml(color)
            web = getattr(cls.form, "webview", None)
            if web is not None:
                web.DefaultBackgroundColor = Color.FromArgb(255, int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16))
        try:
            from System import Action
            cls.form.BeginInvoke(Action(go))
        except Exception:
            pass

    @classmethod
    def track(cls, ht):
        """Start Windows' move (HTCAPTION) or size (HTLEFT …) loop for the
        mouse button that is down now, on the GUI thread."""
        if not cls.hwnd:
            return
        ctypes, wt, u = cls._api()

        def go():
            # only for a button that is really down: a move loop started without
            # one would wait for the next click anywhere (synthetic / late events)
            if not (u.GetAsyncKeyState(0x01) & 0x8000):  # VK_LBUTTON
                return
            pt = wt.POINT()
            u.GetCursorPos(ctypes.byref(pt))
            u.ReleaseCapture()
            u.SendMessageW(cls.hwnd, 0x00A1, ht, (pt.y & 0xFFFF) << 16 | (pt.x & 0xFFFF))  # WM_NCLBUTTONDOWN
        try:
            from System import Action
            cls.form.BeginInvoke(Action(go))
        except Exception:
            go()


# ----- Windows "Open with" (per user, no admin rights) -----
# HKCU\Software\Classes only. ReadO is *added* to each extension's
# OpenWithProgids list, so Explorer offers it under "Open with" without
# taking over the default program. Unregister removes exactly what was added
# (the extension list is remembered on the ProgID key).
PROGID = "ReadO.File"
CLASSES = r"Software\Classes"
# Common text formats offered in Explorer's "Open with". ReadO opens any text
# file (content check), this list only decides where Explorer offers it.
ASSOC_EXTS = """
.txt .log .md .markdown .json .jsonc .xml .yml .yaml .toml .ini .cfg .conf .properties .env .csv .tsv
.sql .java .kt .kts .gradle .groovy .scala .js .jsx .mjs .cjs .ts .tsx .vue .svelte .html .htm .css
.scss .less .py .go .rs .c .h .cpp .hpp .cc .cs .php .rb .swift .dart .lua .pl .r .sh .bash .zsh
.bat .cmd .ps1 .editorconfig .gitignore .gitattributes .dockerignore
""".split()


def assoc_command():
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" "%1"', sys.executable
    pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    return f'"{pyw if os.path.exists(pyw) else sys.executable}" "{os.path.abspath(__file__)}" "%1"', sys.executable


def assoc_exts():
    exts = ASSOC_EXTS
    out = []
    for e in exts:
        e = e.lower() if e.startswith(".") else "." + e.lower()
        if e not in out and len(e) > 1 and all(c.isalnum() or c in "._-" for c in e):
            out.append(e)
    return out


def _delete_tree(winreg, root, path):
    try:
        with winreg.OpenKey(root, path, 0, winreg.KEY_ALL_ACCESS) as k:
            while True:
                try:
                    child = winreg.EnumKey(k, 0)
                except OSError:
                    break
                _delete_tree(winreg, root, path + "\\" + child)
        winreg.DeleteKey(root, path)
    except FileNotFoundError:
        pass


def _notify_shell():
    import ctypes
    ctypes.windll.shell32.SHChangeNotify(0x08000000, 0, None, None)  # SHCNE_ASSOCCHANGED


def assoc_status():
    if os.name != "nt":
        return {"supported": False}
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, CLASSES + "\\" + PROGID + r"\shell\open\command") as k:
            cmd = winreg.QueryValueEx(k, "")[0]
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, CLASSES + "\\" + PROGID) as k:
            exts = winreg.QueryValueEx(k, "ReadOExtensions")[0]
        return {"supported": True, "registered": True, "command": cmd, "extensions": exts,
                "current": cmd == assoc_command()[0]}
    except OSError:
        return {"supported": True, "registered": False, "command": assoc_command()[0]}


def register_assoc():
    if os.name != "nt":
        return {"supported": False}
    import winreg
    old = assoc_status()
    if old.get("registered"):
        unregister_assoc(notify=False)  # drop extensions no longer in settings
    cmd, exe = assoc_command()
    exts = assoc_exts()
    H = winreg.HKEY_CURRENT_USER
    with winreg.CreateKey(H, CLASSES + "\\" + PROGID) as k:
        winreg.SetValueEx(k, "", 0, winreg.REG_SZ, "ReadO text file")
        winreg.SetValueEx(k, "ReadOExtensions", 0, winreg.REG_MULTI_SZ, exts)
    with winreg.CreateKey(H, CLASSES + "\\" + PROGID + r"\DefaultIcon") as k:
        winreg.SetValueEx(k, "", 0, winreg.REG_SZ, f'"{exe}",0')
    with winreg.CreateKey(H, CLASSES + "\\" + PROGID + r"\shell\open\command") as k:
        winreg.SetValueEx(k, "", 0, winreg.REG_SZ, cmd)
    if getattr(sys, "frozen", False):
        app = CLASSES + "\\Applications\\" + os.path.basename(exe)
        with winreg.CreateKey(H, app) as k:
            winreg.SetValueEx(k, "FriendlyAppName", 0, winreg.REG_SZ, "ReadO")
        with winreg.CreateKey(H, app + r"\shell\open\command") as k:
            winreg.SetValueEx(k, "", 0, winreg.REG_SZ, cmd)
        with winreg.CreateKey(H, app + r"\SupportedTypes") as k:
            for e in exts:
                winreg.SetValueEx(k, e, 0, winreg.REG_SZ, "")
    for e in exts:
        with winreg.CreateKey(H, CLASSES + "\\" + e + r"\OpenWithProgids") as k:
            winreg.SetValueEx(k, PROGID, 0, winreg.REG_NONE, b"")
    _notify_shell()
    return assoc_status()


def unregister_assoc(notify=True):
    if os.name != "nt":
        return {"supported": False}
    import winreg
    H = winreg.HKEY_CURRENT_USER
    st = assoc_status()
    for e in st.get("extensions") or assoc_exts():
        try:
            with winreg.OpenKey(H, CLASSES + "\\" + e + r"\OpenWithProgids", 0, winreg.KEY_ALL_ACCESS) as k:
                winreg.DeleteValue(k, PROGID)
        except OSError:
            pass
        # drop the keys register created, if nothing else lives in them
        for sub in (CLASSES + "\\" + e + r"\OpenWithProgids", CLASSES + "\\" + e):
            try:
                with winreg.OpenKey(H, sub) as k:
                    empty = winreg.QueryInfoKey(k)[:2] == (0, 0)
                if empty:
                    winreg.DeleteKey(H, sub)
            except OSError:
                pass
    _delete_tree(winreg, H, CLASSES + "\\" + PROGID)
    if getattr(sys, "frozen", False):
        _delete_tree(winreg, H, CLASSES + "\\Applications\\" + os.path.basename(sys.executable))
    if notify:
        _notify_shell()
    return assoc_status()


def on_shown(win):
    """The window is up: the watchdog stands down, a second launch may hand us files."""
    if os.environ.get("READO_TEST_HIDDEN") == "1":
        return  # tests: act like a window that never came up (pywebview fires "shown" for hidden windows too)
    WATCHDOG.shown()
    WATCHDOG.stage = "shown"
    write_instance_file(shown=True)
    NativeFrame.install(win)


def on_closing():
    """Ask before quitting with unsaved tabs. Runs on the GUI thread, where a
    plain Win32 message box is safe (evaluate_js here would deadlock)."""
    if Api.dirty <= 0 or os.name != "nt":
        return True
    import ctypes
    MB_OKCANCEL, MB_ICONWARNING, IDOK = 0x1, 0x30, 1
    hwnd = ctypes.windll.user32.GetForegroundWindow()
    answer = ctypes.windll.user32.MessageBoxW(
        hwnd, f"{Api.dirty} file(s) have unsaved changes.\nQuit without saving?",
        "ReadO", MB_OKCANCEL | MB_ICONWARNING)
    return answer == IDOK  # False cancels the close


def on_drop(win, event):
    paths = [f.get("pywebviewFullPath") for f in event.get("dataTransfer", {}).get("files", [])]
    if server.request_open([p for p in paths if p]):
        win.run_js("window.readoPollNow && window.readoPollNow()")


def on_loaded(win):
    from webview.dom import DOMEventHandler
    win.dom.document.events.drop += DOMEventHandler(lambda e: on_drop(win, e), True, True)


def bind_server():
    """8766 if free, else any free loopback port."""
    global PORT
    for port in (PREFERRED_PORT, 0):
        try:
            httpd = server.make_server(HOST, port)
        except OSError:
            continue
        PORT = httpd.server_address[1]
        return httpd
    raise OSError("no free port")


def raise_window(win):
    try:
        win.restore()
        if os.name == "nt":
            import ctypes
            ctypes.windll.user32.SetForegroundWindow(int(win.native.Handle.ToInt64()))
    except Exception:
        pass


class DiffWindowBackend:
    """Diff windows as OS windows of their own (gitview.DIFFWIN decides which; this makes them).

    Each one loads /diffwin?id=… from our server (same token, same origin), has the normal
    Windows caption (it is not the main window's custom frame), and can go anywhere, other
    monitors included. Size and place of the last one closed are kept in diffwin.json; new
    ones cascade from the newest open one. pywebview marshals create / destroy onto the GUI
    thread, so these are called straight from the HTTP handler threads."""
    STEP = 28
    PATH = os.path.join(writable_root(), "diffwin.json")

    def __init__(self, main_win):
        self.main = main_win
        self.open = []  # pywebview windows, oldest first
        try:
            with open(self.PATH, "r", encoding="utf-8") as f:
                self.geom = {k: int(v) for k, v in json.load(f).items() if k in ("x", "y", "w", "h")}
        except (OSError, ValueError, TypeError, AttributeError):
            self.geom = {}

    def _place(self):
        g = {"w": max(500, self.geom.get("w", 1100)), "h": max(320, self.geom.get("h", 760))}
        last = self.open[-1] if self.open else None
        try:
            if last is not None:
                g.update(x=last.x + self.STEP, y=last.y + self.STEP)
            elif "x" in self.geom:
                g.update(x=self.geom["x"], y=self.geom["y"])
        except Exception:
            pass
        return g

    def _remember(self, w):
        try:
            self.geom = {"x": int(w.x), "y": int(w.y), "w": int(w.width), "h": int(w.height)}
            with open(self.PATH, "w", encoding="utf-8") as f:
                json.dump(self.geom, f)
        except Exception:
            pass

    def create(self, wid, path, title):
        g = self._place()
        w = webview.create_window(title=title, url=f"http://{HOST}:{PORT}{path}", width=g["w"], height=g["h"],
                                  x=g.get("x"), y=g.get("y"), min_size=(500, 320), focus=True,
                                  background_color="#282c34" if (server.ui_state().get("theme") == "dark") else "#ffffff")

        def closed():
            if w in self.open:
                self.open.remove(w)
            gitview.DIFFWIN.closed(wid)
        w.events.closing += lambda: self._remember(w)
        w.events.closed += closed
        w.events.shown += lambda: NativeFrame.follow(w.native)
        self.open.append(w)
        return w

    def focus(self, w):
        raise_window(w)

    def close(self, w):
        if w in self.open:
            self.open.remove(w)
        try:
            w.destroy()
        except Exception:
            pass

    def set_title(self, w, title):
        try:
            w.set_title(title)
        except Exception:
            pass

    def open_in_main(self, key, line):
        self.main.run_js(f"window.openFile && openFile({json.dumps(key)}{', ' + str(int(line)) if line else ''})")
        raise_window(self.main)


def theme_background():
    """The page background of the saved theme (source.html: --panel)."""
    try:
        return "#282c34" if server.ui_state().get("theme") == "dark" else "#ffffff"
    except Exception:
        return "#ffffff"


def main():
    files = cli_files()
    # an instance is already running: give it our files instead of a 2nd window
    WATCHDOG.stage = "second launch check"
    if forward_to_running(files):
        return
    # waiting for a stuck first instance is not our own start-up
    WATCHDOG.t0 = time.time()
    WATCHDOG.stage = "server"
    httpd = bind_server()
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    write_instance_file()
    server.request_open(files)
    wait_ready()
    WATCHDOG.stage = "window"
    win = webview.create_window(
        title="ReadO",
        url=f"http://{HOST}:{PORT}/",
        width=1500,
        height=950,
        min_size=(900, 600),
        js_api=Api(),
        # the page draws the title bar; NativeFrame gives the window its sizing
        # frame, snap and animations back (WinForms itself sees a borderless form,
        # so it never adds a caption to the size on restore)
        frameless=os.name == "nt",
        easy_drag=False,
        shadow=True,
        # not white: maximizing exposes this color until WebView2 repaints (a white screen in the dark theme)
        background_color=theme_background(),
        # tests only: a window that never shows (the start-up watchdog / second-launch case)
        hidden=os.environ.get("READO_TEST_HIDDEN") == "1",
    )
    server.on_open_request = lambda: raise_window(win)
    gitview.DIFFWIN.backend = DiffWindowBackend(win)
    win.events.shown += lambda: on_shown(win)
    win.events.closing += on_closing
    # the diff windows go with the main window (pywebview would keep running for them)
    win.events.closed += gitview.DIFFWIN.close_all
    win.events.loaded += lambda: on_loaded(win)
    try:
        WATCHDOG.stage = "webview.start (window not shown yet)"
        # private_mode stays at pywebview's default (True): WebView2 storage is
        # wiped on exit, so UI state is kept by the server (state.json) instead
        webview.start()
    finally:
        remove_instance_file()


if __name__ == "__main__":
    main()
