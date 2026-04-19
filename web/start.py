# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Launch both FastAPI backend and Vite frontend dev servers."""

import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = ROOT.parent
FRONTEND_DIR = ROOT / "frontend"


def main() -> None:
    procs: list[subprocess.Popen[bytes]] = []

    try:
        # Start FastAPI backend via uv
        print("[start] Launching FastAPI on http://localhost:8000 ...")
        uv_cmd = shutil.which("uv") or shutil.which("uv.exe")
        if not uv_cmd:
            print("[start] ERROR: uv not found in PATH. Install uv first.")
            return
        api_proc = subprocess.Popen(
            [
                uv_cmd, "run", "--group", "web",
                "python", "-m", "uvicorn",
                "web.api.main:app",
                "--host", "127.0.0.1",
                "--port", "8000",
                "--reload",
                "--reload-dir", str(ROOT / "api"),
            ],
            cwd=str(PROJECT_ROOT),
        )
        procs.append(api_proc)

        # Wait for backend to be ready before starting Vite
        print("[start] Waiting for backend to be ready ...")
        for _ in range(30):
            try:
                urllib.request.urlopen("http://127.0.0.1:8000/api/system/health", timeout=1)
                break
            except Exception:
                if api_proc.poll() is not None:
                    print("[start] ERROR: backend exited unexpectedly.")
                    return
                time.sleep(0.5)
        else:
            print("[start] WARNING: backend not ready after 15s, starting Vite anyway.")

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
