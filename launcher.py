"""Desktop entry point: start the local service and open the app.

This is what the packaged executable runs. Double-clicking it should behave
like opening any other program - no terminal, no Python, no npm - so the work
here is the small amount of plumbing that turns a web service into something a
technician can launch from a shortcut:

* find a port, and recognise the case where the app is *already* running rather
  than starting a confusing second copy,
* wait until the service actually answers before opening a browser at it,
* print status a non-developer can act on, and keep the window open long enough
  to read if startup fails.
"""

from __future__ import annotations

import argparse
import contextlib
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser

DEFAULT_PORT = 8000
HOST = "127.0.0.1"
# How long to wait for the service to answer before giving up on the browser.
STARTUP_TIMEOUT_SEC = 30.0


def _say(message: str = "") -> None:
    """Print and flush.

    stdout is block-buffered whenever it is not a console, so a redirected or
    piped launch would otherwise hold the URL and the data location in the
    buffer until the process exits - which is exactly when they stop being
    useful.
    """
    print(message, flush=True)


def _port_is_free(port: int, host: str = HOST) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        # Without SO_REUSEADDR a port in TIME_WAIT reads as taken when it is not.
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
            return True
        except OSError:
            return False


def _already_ours(port: int, host: str = HOST) -> bool:
    """Is the thing on this port our own app, rather than something unrelated?

    Worth distinguishing: a second copy of ourselves means the user just
    double-clicked twice and wants the window they already have, while some
    other service means we should quietly move to a different port.
    """
    try:
        with urllib.request.urlopen(f"http://{host}:{port}/api/health", timeout=2) as response:
            body = response.read(400).decode("utf-8", "replace")
    except (urllib.error.URLError, OSError, TimeoutError):
        return False
    return '"status"' in body and "wifi_backend" in body


def _free_port(host: str = HOST) -> int:
    """Ask the OS for any free port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return int(sock.getsockname()[1])


def _wait_then_open(url: str, ready: threading.Event) -> None:
    """Open the browser once the service answers, not merely once it is asked to."""
    deadline = time.monotonic() + STARTUP_TIMEOUT_SEC
    while time.monotonic() < deadline:
        if ready.is_set():
            return
        try:
            with urllib.request.urlopen(f"{url}/api/health", timeout=1):
                pass
        except (urllib.error.URLError, OSError, TimeoutError):
            time.sleep(0.3)
            continue

        _say(f"\n  Opening {url}\n")
        with contextlib.suppress(Exception):
            webbrowser.open(url)
        return

    _say(
        "\n  The service did not answer in time. It may still be starting -\n"
        f"  try opening {url} in your browser.\n"
    )


def _banner(url: str, data_dir: str, backend: str, simulated: bool) -> None:
    line = "=" * 62
    _say(f"\n{line}")
    _say("  CHECK SIGNAL WIFI")
    _say(line)
    _say(f"  Open in browser : {url}")
    _say(f"  Survey data     : {data_dir}")
    _say(f"  WiFi source     : {backend}")
    if simulated:
        _say("\n  !! No WiFi tooling found on this machine, so readings are")
        _say("     SIMULATED. They do not come from a real radio.")
    _say(f"\n  Close this window to stop the app.\n{line}\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Check Signal WiFi as a desktop app.")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--host", default=HOST)
    parser.add_argument(
        "--no-browser", action="store_true", help="Start the service without opening a browser"
    )
    args = parser.parse_args(argv)

    port = args.port
    if not _port_is_free(port, args.host):
        if _already_ours(port, args.host):
            url = f"http://{args.host}:{port}"
            _say(f"\n  Check Signal WiFi is already running.\n  Opening {url}\n")
            if not args.no_browser:
                with contextlib.suppress(Exception):
                    webbrowser.open(url)
            return 0
        port = _free_port(args.host)
        _say(f"\n  Port {args.port} is in use by something else; using {port} instead.")

    # Imported here, after the port decision, so a duplicate launch exits fast
    # instead of paying for the whole application import first.
    import uvicorn

    from backend.app import __version__
    from backend.app.config import DATA_DIR
    from backend.app.main import app
    from backend.app.wifi import get_adapter

    adapter = get_adapter()
    url = f"http://{args.host}:{port}"
    _say(f"  Check Signal WiFi v{__version__}")
    _banner(url, str(DATA_DIR), adapter.name, adapter.name == "mock")

    ready = threading.Event()
    if not args.no_browser:
        threading.Thread(target=_wait_then_open, args=(url, ready), daemon=True).start()

    # Protocol implementations are named explicitly rather than left to
    # uvicorn's "auto" discovery: that discovery imports by string at runtime,
    # which a frozen bundle cannot follow.
    config = uvicorn.Config(
        app,
        host=args.host,
        port=port,
        log_level="warning",
        loop="asyncio",
        http="h11",
        ws="websockets",
        lifespan="on",
    )
    server = uvicorn.Server(config)

    try:
        server.run()
    except KeyboardInterrupt:
        pass
    finally:
        ready.set()
    _say("\n  Stopped.\n")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # last resort so the window stays readable
        _say(f"\n  Could not start Check Signal WiFi:\n    {exc}\n")
        import traceback

        traceback.print_exc()
        # A double-clicked window closes the instant the process ends, taking
        # the error with it. Hold it open so there is something to report.
        if getattr(sys, "frozen", False):
            with contextlib.suppress(Exception):
                input("  Press Enter to close this window. ")
        sys.exit(1)
