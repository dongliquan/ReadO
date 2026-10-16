"""Keep WMI out of ReadO's process. Imported first: by the PyInstaller runtime
hook (rthook_nowmi.py) in the exe, and at the top of reado.py.

Python 3.12's platform module asks WMI (Win32_OperatingSystem, Win32_Processor)
for platform.system() / machine() / win32_ver(), and pywebview calls
platform.system() on every start. A WMI query that never got an answer left two
ReadO instances without a window: the query thread and the GUI thread stuck on
an RPC call to the endpoint mapper (2026-10-15). platform has a fallback without
WMI (sys.getwindowsversion, the environment) that gives the same answers here.
"""
import os

blocked = []  # what asked for WMI (shown in startup.log and win_state)


def _refuse(what):
    blocked.append(what)
    raise OSError("WMI is not used by ReadO")


def install():
    if os.name != "nt":
        return
    import platform
    platform._wmi_query = lambda table="", *keys: _refuse(f"platform:{table}")
    try:
        import _wmi
    except ImportError:
        return
    _wmi.exec_query = lambda query="": _refuse("_wmi.exec_query")


install()
