"""
ReadO — desktop launcher.
Starts the local HTTP server in a thread and opens a native WebView2 window.
"""
import os
import sys
import threading
import time
import urllib.request

import webview


def app_root():
    if getattr(sys, "frozen", False):
        return sys._MEIPASS
    return os.path.dirname(os.path.abspath(__file__))


def writable_root():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


sys.path.insert(0, app_root())
import server  # noqa: E402

server.ROOT = app_root()
server.HTML_PATH = os.path.join(app_root(), "source.html")
server.CONFIG_PATH = os.path.join(writable_root(), "config.json")
server._first_run = not os.path.exists(server.CONFIG_PATH)
server.SETTINGS = server.load_settings()

HOST = "127.0.0.1"
PORT = 8766


def serve():
    server.HTTPServer((HOST, PORT), server.Handler).serve_forever()


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
    def pick_dir(self, current=""):
        win = webview.windows[0] if webview.windows else None
        if not win:
            return None
        result = win.create_file_dialog(webview.FOLDER_DIALOG, directory=current or "")
        if not result:
            return None
        return result[0] if isinstance(result, (list, tuple)) else result


def main():
    threading.Thread(target=serve, daemon=True).start()
    wait_ready()
    webview.create_window(
        title="ReadO",
        url=f"http://{HOST}:{PORT}/",
        width=1500,
        height=950,
        min_size=(900, 600),
        js_api=Api(),
    )
    webview.start()


if __name__ == "__main__":
    main()
