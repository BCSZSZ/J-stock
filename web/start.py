# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Launch both FastAPI backend and Vite frontend dev servers."""

import shutil
import subprocess
import sys
import signal
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = ROOT.parent
FRONTEND_DIR = ROOT / "frontend"


def main() -> None:
    procs: list[subprocess.Popen[bytes]] = []

    try:
        # Start FastAPI backend
        print("[start] Launching FastAPI on http://localhost:8000 ...")
        api_proc = subprocess.Popen(
            [
                sys.executable, "-m", "uvicorn",
                "web.api.main:app",
                "--host", "127.0.0.1",
                "--port", "8000",
                "--reload",
                "--reload-dir", str(ROOT / "api"),
            ],
            cwd=str(PROJECT_ROOT),
        )
        procs.append(api_proc)

        # Start Vite dev server
        print("[start] Launching Vite on http://localhost:5173 ...")
        npm_cmd = shutil.which("npm") or shutil.which("npm.cmd")
        if not npm_cmd:
            print("[start] ERROR: npm not found in PATH. Install Node.js first.")
            return
        vite_proc = subprocess.Popen(
            [npm_cmd, "run", "dev"],
            cwd=str(FRONTEND_DIR),
        )
        procs.append(vite_proc)

        print("[start] Both servers running. Press Ctrl+C to stop.")
        # Wait for either to exit
        for p in procs:
            p.wait()

    except KeyboardInterrupt:
        print("\n[start] Shutting down...")
    finally:
        for p in procs:
            if p.poll() is None:
                p.terminate()
                try:
                    p.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    p.kill()
        print("[start] Done.")


if __name__ == "__main__":
    main()
