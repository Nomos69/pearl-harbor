"""Launch a local Pearl Harbor server and its host GUI together."""

from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import urlopen


PROJECT_DIR = Path(__file__).resolve().parent


def server_is_ready(port: int) -> bool:
    try:
        with urlopen(f"http://127.0.0.1:{port}/healthz", timeout=0.25) as response:
            return response.status == 200 and response.read().strip() == b"OK"
    except (OSError, URLError):
        return False


def wait_for_server(
    server_process: subprocess.Popen[bytes], port: int, timeout: float
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if server_is_ready(port):
            return
        return_code = server_process.poll()
        if return_code is not None:
            raise RuntimeError(
                f"The server stopped during startup with exit code {return_code}."
            )
        time.sleep(0.1)
    raise RuntimeError(f"The server did not become ready within {timeout:.1f} seconds.")


def stop_process(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=2)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Start the Pearl Harbor server and host GUI with one command."
    )
    parser.add_argument(
        "--listen-host",
        default="127.0.0.1",
        help="Server bind address; use 0.0.0.0 when accepting a remote guest.",
    )
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--startup-timeout", type=float, default=5.0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    server_process: subprocess.Popen[bytes] | None = None
    gui_process: subprocess.Popen[bytes] | None = None
    owns_server = False

    try:
        if server_is_ready(args.port):
            print(f"Using the Pearl Harbor server already running on port {args.port}.")
        else:
            print(
                f"Starting Pearl Harbor server on {args.listen_host}:{args.port} ..."
            )
            server_process = subprocess.Popen(
                [
                    sys.executable,
                    str(PROJECT_DIR / "server.py"),
                    "--host",
                    args.listen_host,
                    "--port",
                    str(args.port),
                ],
                cwd=PROJECT_DIR,
            )
            owns_server = True
            wait_for_server(server_process, args.port, args.startup_timeout)
            print("Server ready. Opening Host Operation ...")

        gui_process = subprocess.Popen(
            [
                sys.executable,
                str(PROJECT_DIR / "gui_client.py"),
                "--uri",
                f"ws://127.0.0.1:{args.port}/ws",
                "--host",
            ],
            cwd=PROJECT_DIR,
        )
        return gui_process.wait()
    except KeyboardInterrupt:
        return 130
    except RuntimeError as exc:
        print(f"Launcher error: {exc}", file=sys.stderr)
        return 1
    finally:
        if gui_process is not None:
            stop_process(gui_process)
        if owns_server and server_process is not None:
            print("Stopping Pearl Harbor server ...")
            stop_process(server_process)


if __name__ == "__main__":
    raise SystemExit(main())
