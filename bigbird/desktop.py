"""Desktop shell: runs the FastAPI backend in a background thread and opens
a native window (via pywebview) pointing at it.
"""

import socket
import threading
import time

import uvicorn
import webview

from bigbird.api import app

HOST = "127.0.0.1"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((HOST, 0))
        return s.getsockname()[1]


def _wait_until_up(host: str, port: int, timeout: float = 10.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return
        except OSError:
            time.sleep(0.1)
    raise RuntimeError(f"backend didn't come up on {host}:{port} within {timeout}s")


def main() -> None:
    port = _free_port()
    config = uvicorn.Config(app, host=HOST, port=port, log_level="warning")
    server = uvicorn.Server(config)

    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    _wait_until_up(HOST, port)

    window = webview.create_window("bigbird", f"http://{HOST}:{port}/", width=1000, height=720)
    window.events.closing += lambda: setattr(server, "should_exit", True)

    webview.start()


if __name__ == "__main__":
    main()
