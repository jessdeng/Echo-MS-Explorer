"""Launch echo-ms-explorer as a native desktop window.

Starts the Shiny server in a background daemon thread and opens it inside a
pywebview native window (WKWebView on Mac, WebView2 on Windows, WebKitGTK on
Linux). No browser needed.

If pywebview can't open a window (e.g. headless environment), falls back to
opening the URL in the default browser and keeps the server running.

Run directly with:
    uv run python launch.py
or double-click the matching .command (Mac) / .bat (Windows) launcher.
"""

from __future__ import annotations

import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path

# Make sure the src/ package is importable even when launched by double-click
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

import uvicorn


def find_free_port(start: int = 8765) -> int:
    """Return the first free TCP port at or above `start`."""
    for port in range(start, start + 100):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise RuntimeError(f"No free port found in {start}-{start + 99} range.")


def start_server(port: int) -> uvicorn.Server:
    """Start Shiny + uvicorn in a daemon thread so it dies with the main process."""
    sys.path.insert(0, str(ROOT / "app"))
    import app as app_module  # noqa: E402

    config = uvicorn.Config(
        app_module.app,
        host="127.0.0.1",
        port=port,
        log_level="warning",
        access_log=False,
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    return server


def wait_for_server(port: int, timeout: float = 20.0) -> bool:
    """Poll the port until the server accepts connections, or time out."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.1)
    return False


def open_native_window(url: str) -> bool:
    """Try to open a pywebview native window. Return True if it succeeded
    (and the window has now been closed); False if pywebview is unavailable
    or failed before the window appeared."""
    try:
        import webview  # type: ignore
    except ImportError:
        print("pywebview not installed — falling back to browser.", file=sys.stderr)
        return False

    try:
        webview.create_window(
            title="echo-ms-explorer",
            url=url,
            width=1400,
            height=950,
            min_size=(900, 650),
            resizable=True,
        )
        # webview.start() must run on the main thread.
        # It blocks until the user closes the window.
        webview.start()
        return True
    except Exception as e:
        print(
            f"pywebview failed ({type(e).__name__}: {e}) — falling back to browser.",
            file=sys.stderr,
        )
        return False


def main() -> None:
    port = find_free_port()

    # Write port file so the .command launcher knows where the server is
    (ROOT / ".server-port").write_text(str(port))

    print(f"Starting echo-ms-explorer server on port {port}...", flush=True)
    start_server(port)

    if not wait_for_server(port):
        print("ERROR: Server did not start within 20 seconds.", file=sys.stderr)
        sys.exit(1)

    url = f"http://127.0.0.1:{port}"
    print(f"Server ready at {url}", flush=True)

    # Try native window first (blocks until window closes)
    if open_native_window(url):
        # Window closed normally — exit (this also kills the daemon server)
        return

    # Fallback: open in default browser and keep the server alive
    print(f"Opening in browser: {url}", flush=True)
    webbrowser.open(url)
    print("Server is running. Press Ctrl+C to stop.", flush=True)
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        print("\nShutting down.", flush=True)


if __name__ == "__main__":
    main()
