"""Start-up guards of the built exe (watchdog, second launch past a stuck instance).

    python tests/exe_startup.py dist\\reado.exe

Runs the exe with APPDATA pointed at a scratch folder (the user's %APPDATA%\\ReadO
is not touched) and ends only the processes it started. Opens real ReadO windows
for a few seconds; sends no keyboard or mouse input.
  1. normal start: window shown, instance.json says so; a second launch hands over its file and exits
  2. window never shown (READO_TEST_HIDDEN=1) + READO_STARTUP_TIMEOUT=4: startup.log, the process ends itself
  3. a stuck first instance (hidden, watchdog off) + a normal second launch: the second one ends the
     stuck one, starts on its own and shows its window
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

EXE = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), "..", "dist", "reado.exe"))
FAILS = []


def check(cond, what):
    print(("  ok   " if cond else "  FAIL ") + what)
    if not cond:
        FAILS.append(what)


def alive(p):
    return p.poll() is None


def end_tree(p):
    if p and alive(p):
        subprocess.run(["taskkill", "/PID", str(p.pid), "/T", "/F"], capture_output=True)


def main():
    root = tempfile.mkdtemp(prefix="reado-startup-")
    appdata, base = os.path.join(root, "appdata"), os.path.join(root, "base")
    rdir = os.path.join(appdata, "ReadO")
    os.makedirs(rdir)
    os.makedirs(base)
    with open(os.path.join(base, "a.txt"), "w") as f:
        f.write("hello\n")
    with open(os.path.join(rdir, "config.json"), "w") as f:
        json.dump({"base_dir": base}, f)
    inst_path, log_path = os.path.join(rdir, "instance.json"), os.path.join(rdir, "startup.log")

    def inst():
        try:
            with open(inst_path, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return None

    def wait(cond, timeout):
        end = time.time() + timeout
        while time.time() < end:
            v = cond()
            if v:
                return v
            time.sleep(0.2)
        return None

    def launch(*args, **env):
        e = dict(os.environ, APPDATA=appdata)
        e.pop("READO_STARTUP_TIMEOUT", None)
        e.update({k: str(v) for k, v in env.items()})
        return subprocess.Popen([EXE, *args], env=e)

    def log_text():
        try:
            return open(log_path, encoding="utf-8").read()
        except OSError:
            return ""

    started = []
    try:
        print(f"== {EXE}")
        print("== 1. normal start, second launch hands over")
        a = launch()
        started.append(a)
        i = wait(lambda: (inst() or {}).get("shown") and inst(), 30)
        check(bool(i) and alive(a), "window shown: instance.json has shown=true")
        check(i and i.get("exe", "").lower().endswith("reado.exe") and i.get("started"), "instance.json names the exe and its start time")
        b = launch(os.path.join(base, "a.txt"))
        started.append(b)
        try:
            b.wait(10)
        except subprocess.TimeoutExpired:
            pass
        check(not alive(b) and alive(a) and (inst() or {}).get("pid") == (i or {}).get("pid"), "second launch handed its file over and exited; the first keeps running")
        check("no window after" not in log_text(), "no watchdog entry for a normal start")
        end_tree(a)
        wait(lambda: not alive(a), 10)
        try:
            os.remove(inst_path)
        except OSError:
            pass

        print("== 2. window never shown: the watchdog ends it")
        t = time.time()
        h = launch(READO_TEST_HIDDEN=1, READO_STARTUP_TIMEOUT=4)
        started.append(h)
        try:
            h.wait(25)
        except subprocess.TimeoutExpired:
            pass
        dt = time.time() - t
        lt = log_text()
        check(not alive(h) and dt < 20, f"process ended by itself after {dt:.1f} s (limit 4 s)")
        check("no window after 4 s" in lt and "stage: webview.start" in lt and "--- thread" in lt, "startup.log: reason, stage, thread stacks")
        check("WMI requests refused: platform" in lt, "startup.log: pywebview's platform query went to the non-WMI fallback")
        check(inst() is None, "instance.json removed")

        print("== 3. a stuck instance does not swallow the next launch")
        s = launch(READO_TEST_HIDDEN=1, READO_STARTUP_TIMEOUT=0)
        started.append(s)
        si = wait(lambda: inst(), 30)
        check(bool(si) and si.get("shown") is False, "stuck instance: instance.json with shown=false")
        t = time.time()
        n = launch(READO_STARTUP_TIMEOUT=10)  # its own cold start must fit too; 3 s was too short on a loaded machine
        started.append(n)
        ni = wait(lambda: (inst() or {}).get("shown") and inst()["pid"] != (si or {}).get("pid") and inst(), 40)
        dt = time.time() - t
        check(bool(ni) and alive(n), f"new launch showed its own window after {dt:.1f} s (waited for the stuck one first)")
        wait(lambda: not alive(s), 10)
        check(not alive(s), "the stuck instance was ended")
        check(f"pid {(si or {}).get('pid')}" in log_text() and "never showed its window" in log_text(), "startup.log: which instance was ended and why")
    finally:
        for p in started:
            end_tree(p)
        time.sleep(1)
        shutil.rmtree(root, ignore_errors=True)
    print(f"\n{'FAILED: ' + str(len(FAILS)) if FAILS else 'all passed'}")
    sys.exit(1 if FAILS else 0)


if __name__ == "__main__":
    main()
