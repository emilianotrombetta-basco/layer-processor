#!/usr/bin/env python3
"""Avvia controller e interfaccia locale con un solo comando."""
from __future__ import annotations

import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DASHBOARD = ROOT / "dashboard"


def wait_for_port(port: int, timeout: float = 30, host: str = "127.0.0.1") -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.25)
    return False


def main() -> int:
    if wait_for_port(3000, timeout=0.5, host="localhost") and wait_for_port(
        8765, timeout=0.5
    ):
        webbrowser.open("http://localhost:3000")
        print("Dashboard già attiva: http://localhost:3000")
        return 0

    if not (DASHBOARD / "node_modules").exists():
        print("Prima preparazione dell’interfaccia…")
        install = subprocess.run(["npm", "install"], cwd=DASHBOARD)
        if install.returncode:
            return install.returncode

    api = subprocess.Popen(
        [sys.executable, str(ROOT / "dashboard_server.py")],
        cwd=ROOT,
    )
    ui = subprocess.Popen(["npm", "run", "dev"], cwd=DASHBOARD)
    try:
        if wait_for_port(3000, host="localhost"):
            webbrowser.open("http://localhost:3000")
            print("Dashboard aperta su http://localhost:3000")
        else:
            print("La dashboard non ha risposto entro il tempo previsto.", file=sys.stderr)
            return 1
        return ui.wait()
    except KeyboardInterrupt:
        return 0
    finally:
        for process in (ui, api):
            if process.poll() is None:
                process.terminate()
        for process in (ui, api):
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()


if __name__ == "__main__":
    raise SystemExit(main())
