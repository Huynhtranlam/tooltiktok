"""Start one private LiveLedger installation on this computer."""

from __future__ import annotations

import argparse
import getpass
import os
import secrets
import sys
import threading
import webbrowser
from pathlib import Path

from waitress import serve
from werkzeug.security import generate_password_hash

from app import create_app
from storage import get_db, now


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


def create_first_admin(app) -> None:
    with app.app_context():
        db = get_db()
        if db.execute("SELECT 1 FROM users LIMIT 1").fetchone():
            return
        print("Lần chạy đầu: tạo tài khoản quản lý cho riêng máy này.")
        while True:
            password = getpass.getpass("Mật khẩu admin (ít nhất 12 ký tự): ")
            repeated = getpass.getpass("Nhập lại mật khẩu: ")
            if len(password) >= 12 and password == repeated:
                break
            print("Mật khẩu cần ít nhất 12 ký tự và hai lần nhập phải giống nhau.")
        with db:
            db.execute("INSERT INTO users(username,password_hash,role,created_at) VALUES(?,?,?,?)",
                       ("admin", generate_password_hash(password), "admin", now()))
        print("Đã tạo tài khoản admin trên máy này.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Chạy LiveLedger chỉ trên máy này")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("Cổng phải từ 1 đến 65535.")
    prepare_environment()
    app = create_app()
    create_first_admin(app)
    url = f"http://127.0.0.1:{args.port}/"
    print(f"LiveLedger đang chạy tại {url}")
    print("Dữ liệu riêng của máy này nằm trong thư mục data/. Nhấn Ctrl+C để dừng.")
    timer = threading.Timer(1.0, lambda: webbrowser.open(url))
    timer.daemon = True
    timer.start()
    serve(app, host="127.0.0.1", port=args.port, threads=4)


if __name__ == "__main__":
    main()
