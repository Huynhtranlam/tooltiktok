"""Central SQLite storage. All clients connect to the server, never to this file."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from flask import current_app, g


SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY, username TEXT NOT NULL UNIQUE COLLATE NOCASE,
  password_hash TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('admin','viewer')),
  active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS staff (
  id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE COLLATE NOCASE,
  active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS schedule_versions (
  id INTEGER PRIMARY KEY, data TEXT NOT NULL, created_at TEXT NOT NULL,
  created_by INTEGER REFERENCES users(id), note TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS schedule_drafts (
  user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  base_version INTEGER NOT NULL, data TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS day_overrides (
  day TEXT PRIMARY KEY, shifts TEXT NOT NULL, updated_at TEXT NOT NULL,
  updated_by INTEGER REFERENCES users(id)
);
CREATE TABLE IF NOT EXISTS commission_rates (
  id INTEGER PRIMARY KEY, staff_id INTEGER NOT NULL REFERENCES staff(id),
  effective_from TEXT NOT NULL, rate REAL NOT NULL CHECK(rate BETWEEN 0 AND 100),
  created_at TEXT NOT NULL, created_by INTEGER REFERENCES users(id),
  UNIQUE(staff_id,effective_from)
);
CREATE TABLE IF NOT EXISTS import_batches (
  id INTEGER PRIMARY KEY, filename TEXT NOT NULL, sha256 TEXT NOT NULL,
  row_count INTEGER NOT NULL, order_count INTEGER NOT NULL,
  inserted INTEGER NOT NULL, updated INTEGER NOT NULL,
  created_at TEXT NOT NULL, created_by INTEGER REFERENCES users(id)
);
CREATE TABLE IF NOT EXISTS orders (
  id TEXT PRIMARY KEY, data TEXT NOT NULL, import_batch_id INTEGER REFERENCES import_batches(id),
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS manual_assignments (
  order_id TEXT PRIMARY KEY REFERENCES orders(id) ON DELETE CASCADE,
  staff_id INTEGER NOT NULL REFERENCES staff(id), reason TEXT NOT NULL,
  updated_at TEXT NOT NULL, updated_by INTEGER NOT NULL REFERENCES users(id)
);
CREATE TABLE IF NOT EXISTS payroll_closures (
  id INTEGER PRIMARY KEY, start_day TEXT NOT NULL, end_day TEXT NOT NULL,
  snapshot TEXT NOT NULL, closed_at TEXT NOT NULL,
  closed_by INTEGER NOT NULL REFERENCES users(id), reopened_at TEXT,
  reopened_by INTEGER REFERENCES users(id)
);
CREATE TABLE IF NOT EXISTS audit_log (
  id INTEGER PRIMARY KEY, at TEXT NOT NULL, user_id INTEGER REFERENCES users(id),
  action TEXT NOT NULL, object_type TEXT NOT NULL, object_id TEXT NOT NULL,
  before_json TEXT, after_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_rates_staff_day ON commission_rates(staff_id,effective_from);
CREATE INDEX IF NOT EXISTS idx_payroll_days ON payroll_closures(start_day,end_day);
CREATE INDEX IF NOT EXISTS idx_audit_at ON audit_log(at);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=15)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA busy_timeout=15000")
    db.execute("PRAGMA journal_mode=WAL")
    return db


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        g.db = connect(Path(current_app.config["DATABASE_PATH"]))
    return g.db


def close_db(_error=None) -> None:
    db = g.pop("db", None)
    if db is not None:
        db.close()


def initial_schedule(staff_ids: dict[str, int]) -> dict:
    all_days = list(range(7))

    def shift(key, name, start, end, days=all_days):
        return {"id": key, "staffId": staff_ids[name], "start": start,
                "end": "00:00" if end == "24:00" else end,
                "endDay": int(end == "24:00" or end < start), "days": list(days)}

    return {"periods": [
        {"id": "p-2026-09-01", "start": "2026-09-01", "end": "2026-09-20", "shifts": [
            shift("p1-nhung", "NHUNG", "10:00", "14:00"),
            shift("p1-vy", "VY", "15:00", "19:00"),
            shift("p1-hao", "HÀO", "21:00", "01:00"),
        ]},
        {"id": "p-2026-09-21", "start": "2026-09-21", "end": "2026-09-27", "shifts": [
            shift("p2-nhung", "NHUNG", "11:00", "13:00", [0, 1, 2, 3, 4, 5]),
            shift("p2-thu", "THƯ", "13:02", "15:00", [0, 3, 4, 5, 6]),
            shift("p2-vy", "VY", "16:00", "18:00", [1, 2, 3, 4, 5, 6]),
            shift("p2-phat", "PHÁT", "19:00", "21:00", [0, 1, 2, 3, 5, 6]),
            shift("p2-hao", "HÀO", "21:15", "24:00", [1, 3, 4, 5]),
        ]},
        {"id": "p-2026-09-28", "start": "2026-09-28", "end": "2026-10-04", "shifts": [
            shift("p3-nhung", "NHUNG", "11:00", "13:00"),
            shift("p3-vy", "VY", "13:05", "15:05"),
            shift("p3-hao", "HÀO", "18:00", "20:00", [0, 2, 3, 5, 6]),
            shift("p3-phat", "PHÁT", "20:05", "23:05", [1, 2, 3, 4, 5, 6]),
            shift("p3-thu", "THƯ", "15:06", "17:05", [0, 1, 4]),
        ]},
    ]}


def init_db(path: Path) -> None:
    db = connect(path)
    db.executescript(SCHEMA)
    if not db.execute("SELECT 1 FROM staff LIMIT 1").fetchone():
        stamp = now()
        for name in ("NHUNG", "VY", "THƯ", "PHÁT", "HÀO"):
            db.execute("INSERT INTO staff(name,created_at) VALUES(?,?)", (name, stamp))
        staff_ids = {r["name"]: r["id"] for r in db.execute("SELECT id,name FROM staff")}
        db.execute("INSERT INTO schedule_versions(data,created_at,note) VALUES(?,?,?)",
                   (json.dumps(initial_schedule(staff_ids), ensure_ascii=False), stamp, "Ba khoảng lịch từ ảnh người dùng"))
        for sid in staff_ids.values():
            db.execute("INSERT INTO commission_rates(staff_id,effective_from,rate,created_at) VALUES(?,?,0,?)",
                       (sid, "2000-01-01", stamp))
    db.commit()
    db.close()


def current_schedule(db: sqlite3.Connection) -> dict:
    row = db.execute("SELECT id,data,created_at FROM schedule_versions ORDER BY id DESC LIMIT 1").fetchone()
    result = json.loads(row["data"])
    result["version"] = row["id"]
    result["savedAt"] = row["created_at"]
    result["overrides"] = {r["day"]: json.loads(r["shifts"]) for r in db.execute("SELECT day,shifts FROM day_overrides")}
    return result


def all_orders(db: sqlite3.Connection) -> list[dict]:
    return [json.loads(r["data"]) for r in db.execute("SELECT data FROM orders")]


def manual_map(db: sqlite3.Connection) -> dict[str, int]:
    return {r["order_id"]: r["staff_id"] for r in db.execute("SELECT order_id,staff_id FROM manual_assignments")}


def rate_map(db: sqlite3.Connection) -> dict[int, list[dict]]:
    result: dict[int, list[dict]] = {}
    for row in db.execute("SELECT staff_id,effective_from,rate FROM commission_rates ORDER BY staff_id,effective_from"):
        result.setdefault(row["staff_id"], []).append({"effectiveFrom": row["effective_from"], "rate": row["rate"]})
    return result


def audit(db: sqlite3.Connection, user_id: int | None, action: str, object_type: str,
          object_id: str, before=None, after=None) -> None:
    dump = lambda value: json.dumps(value, ensure_ascii=False) if value is not None else None
    db.execute("INSERT INTO audit_log(at,user_id,action,object_type,object_id,before_json,after_json) VALUES(?,?,?,?,?,?,?)",
               (now(), user_id, action, object_type, object_id, dump(before), dump(after)))


def make_backup(path: Path, backup_dir: Path) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    target = backup_dir / f"tooltiktok-{datetime.now(timezone.utc):%Y%m%d-%H%M%S-%f}.sqlite3"
    source = connect(path)
    dest = sqlite3.connect(target)
    try:
        source.backup(dest)
    finally:
        dest.close()
        source.close()
    backups = sorted(backup_dir.glob("tooltiktok-*.sqlite3"), reverse=True)
    for old in backups[30:]:
        old.unlink()
    return target


def backup_if_due(path: Path, backup_dir: Path) -> None:
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    if not list(backup_dir.glob(f"tooltiktok-{today}-*.sqlite3")):
        make_backup(path, backup_dir)
