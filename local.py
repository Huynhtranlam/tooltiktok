"""Start one private LiveLedger installation on this computer."""

from __future__ import annotations

import argparse
import os
import secrets
import shutil
import subprocess
import sys
import threading
import webbrowser
from pathlib import Path

from waitress import serve

from app import create_app


ROOT = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("TOOLTIKTOK_DATA_DIR", ROOT / "data"))


def prepare_environment() -> None:
    if sys.version_info < (3, 12):
        raise SystemExit("Cần Python 3.12 trở lên.")
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    secret_file = DATA_DIR / ".secret-key"
    if not secret_file.exists():
        try:
            with secret_file.open("x", encoding="utf-8") as file:
                file.write(secrets.token_hex(32))
        except FileExistsError:
            pass
    os.environ.setdefault("TOOLTIKTOK_SECRET_KEY", secret_file.read_text(encoding="utf-8").strip())
    os.environ.setdefault("TOOLTIKTOK_DATA_DIR", str(DATA_DIR))


def open_app_window(url: str) -> None:
    """Use Edge's compact app window when available, otherwise open the browser."""
    candidates = [shutil.which("msedge")]
    for name in ("PROGRAMFILES(X86)", "PROGRAMFILES"):
        if os.environ.get(name):
            candidates.append(str(Path(os.environ[name]) / "Microsoft" / "Edge" / "Application" / "msedge.exe"))
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            try:
                subprocess.Popen([candidate, f"--app={url}", "--new-window"],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return
            except OSError:
                pass
    webbrowser.open(url)


def main() -> None:
    parser = argparse.ArgumentParser(description="Chạy LiveLedger chỉ trên máy này")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("Cổng phải từ 1 đến 65535.")
    prepare_environment()
    app = create_app()
    url = f"http://127.0.0.1:{args.port}/"
    print(f"LiveLedger đang chạy tại {url}")
    print("Dữ liệu riêng của máy này nằm trong thư mục data/. Nhấn Ctrl+C để dừng.")
    timer = threading.Timer(1.0, lambda: open_app_window(url))
    timer.daemon = True
    timer.start()
    serve(app, host="127.0.0.1", port=args.port, threads=4)


if __name__ == "__main__":
    main()
