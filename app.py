"""Local TikTok Live order attribution server (one SQLite database per install)."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import sqlite3
from datetime import date, timedelta
from pathlib import Path

from flask import Flask, abort, jsonify, request, send_from_directory, session
from werkzeug.exceptions import HTTPException

from domain import approve_shared_overlaps, classify, namespace_override_shifts, parse_csv, report, schedule_days, validate_day_shifts, validate_schedule
from portable import export_data, inspect_data, restore_data
from storage import (
    all_orders, audit, backup_if_due, close_db, current_schedule,
    get_db, init_db, make_backup, manual_map, now, rate_map,
)


ROOT = Path(__file__).resolve().parent


def create_app(test_config: dict | None = None) -> Flask:
    app = Flask(__name__, static_folder=None)
    data_dir = Path(os.environ.get("TOOLTIKTOK_DATA_DIR", ROOT / "data"))
    app.config.update(
        SECRET_KEY=os.environ.get("TOOLTIKTOK_SECRET_KEY") or secrets.token_hex(32),
        DATABASE_PATH=str(data_dir / "tooltiktok.sqlite3"),
        BACKUP_DIR=str(data_dir / "backups"),
        MAX_CONTENT_LENGTH=105 * 1024 * 1024,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.environ.get("TOOLTIKTOK_COOKIE_SECURE") == "1",
        JSON_AS_ASCII=False,
    )
    if test_config:
        app.config.update(test_config)
    if not app.config.get("TESTING") and not os.environ.get("TOOLTIKTOK_SECRET_KEY"):
        raise RuntimeError("Cần khóa phiên làm việc cố định trong thư mục dữ liệu.")
    init_db(Path(app.config["DATABASE_PATH"]))
    app.teardown_appcontext(close_db)
    if not app.config.get("TESTING"):
        backup_if_due(Path(app.config["DATABASE_PATH"]), Path(app.config["BACKUP_DIR"]))

    def person():
        return get_db().execute("SELECT id,username,role,active FROM users WHERE username=?", ("__local_app__",)).fetchone()

    def admin():
        user = person()
        if not user or user["role"] != "admin" or not user["active"]:
            abort(403, "Chỉ quản lý được thực hiện thao tác này.")
        return user

    def body():
        value = request.get_json(silent=True)
        if not isinstance(value, dict):
            abort(400, "Dữ liệu gửi lên không hợp lệ.")
        return value

    def uploaded_bytes(max_mb: int = 25):
        file = request.files.get("file")
        if not file:
            abort(400, "Chọn file trước khi tiếp tục.")
        raw = file.read(max_mb * 1024 * 1024 + 1)
        if len(raw) > max_mb * 1024 * 1024:
            abort(413, f"File vượt {max_mb} MB.")
        return file.filename or "upload", raw

    def staff_list():
        return [dict(row) for row in get_db().execute("SELECT id,name,active FROM staff ORDER BY name COLLATE NOCASE")]

    def active_closed_for(day: str) -> bool:
        return bool(get_db().execute(
            "SELECT 1 FROM payroll_closures WHERE reopened_at IS NULL AND start_day<=? AND end_day>=? LIMIT 1",
            (day, day),
        ).fetchone())

    def pack_report(start: str, end: str):
        db = get_db()
        staff = {r["id"]: r["name"] for r in db.execute("SELECT id,name FROM staff")}
        return report(all_orders(db), current_schedule(db), manual_map(db), rate_map(db), staff, start, end)

    def legacy_preview(raw: bytes):
        try:
            payload = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ValueError("File sao lưu JSON không đọc được.") from None
        if not isinstance(payload, dict) or payload.get("version") != 1 or not isinstance(payload.get("orders"), list) or not isinstance(payload.get("config"), dict):
            raise ValueError("Đây không phải bản sao lưu của công cụ cũ.")
        cfg = payload["config"]
        names = set()
        periods = cfg.get("periods", [])
        if not isinstance(periods, list):
            periods = []
        for period in periods:
            for shift in period.get("slots", []):
                if shift.get("staff"):
                    names.add(shift["staff"].strip().upper())
        for shifts in cfg.get("overrides", {}).values():
            for shift in shifts:
                if shift.get("staff"):
                    names.add(shift["staff"].strip().upper())
        names.update(str(name).strip().upper() for name in cfg.get("rates", {}) if name)
        names.update(str(name).strip().upper() for name in cfg.get("manual", {}).values() if name)
        orders = payload["orders"]
        if any(not isinstance(o, dict) or not o.get("id") or not isinstance(o.get("lines"), list) for o in orders):
            raise ValueError("Bản sao lưu chứa đơn không hợp lệ.")
        for order in orders:
            created = order.get("created")
            if created is not None and not isinstance(created, dict):
                raise ValueError(f"Đơn {order['id']} có giờ tạo không hợp lệ.")
            if isinstance(created, dict) and created.get("date") is not None and created.get("minute") is not None:
                try:
                    date.fromisoformat(str(created["date"]))
                    minute_value = float(created["minute"])
                    if not 0 <= minute_value < 1440:
                        raise ValueError()
                except (TypeError, ValueError):
                    raise ValueError(f"Đơn {order['id']} có giờ tạo không hợp lệ.") from None
        existing = {r["id"] for r in get_db().execute("SELECT id FROM orders")}
        return payload, {"orders": len(orders), "existingOrders": sum(o["id"] in existing for o in orders),
                         "periods": len(periods), "staff": sorted(names), "sha256": hashlib.sha256(raw).hexdigest()}

    @app.before_request
    def protect():
        if request.host.split(":")[0] not in ("127.0.0.1", "localhost"):
            abort(403, "Ứng dụng chỉ mở trên máy này.")
        if not request.path.startswith("/api/"):
            return None
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            if not secrets.compare_digest(request.headers.get("X-CSRF-Token", ""), session.get("csrf", "missing")):
                abort(403, "Phiên làm việc không hợp lệ. Hãy tải lại trang.")
        return None

    @app.after_request
    def secure_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Cache-Control"] = "no-store" if request.path.startswith("/api/") else "no-cache"
        return response

    @app.errorhandler(HTTPException)
    def handle_http(error):
        if request.path.startswith("/api/"):
            return jsonify({"error": error.description}), error.code
        return error

    @app.errorhandler(ValueError)
    def handle_value(error):
        return jsonify({"error": str(error)}), 400

    @app.get("/")
    def index():
        return send_from_directory(ROOT, "index.html")

    @app.get("/<path:name>")
    def assets(name):
        if name not in ("app.js", "style.css"):
            abort(404)
        return send_from_directory(ROOT, name)

    @app.get("/api/me")
    def me():
        if "csrf" not in session:
            session["csrf"] = secrets.token_urlsafe(32)
        user = person()
        return jsonify({"user": {"id": user["id"], "username": "Máy này", "role": "admin"}, "csrf": session["csrf"]})

    @app.get("/api/state")
    def state():
        db = get_db()
        draft = db.execute("SELECT base_version,data,updated_at FROM schedule_drafts WHERE user_id=?", (person()["id"],)).fetchone()
        latest = db.execute("SELECT filename,created_at,row_count,order_count,inserted,updated FROM import_batches ORDER BY id DESC LIMIT 1").fetchone()
        closures = [dict(r) for r in db.execute("SELECT id,start_day,end_day,closed_at,reopened_at FROM payroll_closures ORDER BY id DESC LIMIT 20")]
        return jsonify({"staff": staff_list(), "schedule": current_schedule(db), "rates": rate_map(db),
                        "draft": {"baseVersion": draft["base_version"], "periods": json.loads(draft["data"]), "updatedAt": draft["updated_at"]} if draft else None,
                        "orderCount": db.execute("SELECT count(*) FROM orders").fetchone()[0],
                        "lastImport": dict(latest) if latest else None, "closures": closures})

    @app.post("/api/staff")
    def add_staff():
        actor = admin()
        name = str(body().get("name") or "").strip().upper()
        if not 1 <= len(name) <= 80:
            raise ValueError("Nhập tên nhân viên từ 1 đến 80 ký tự.")
        db = get_db()
        try:
            with db:
                cursor = db.execute("INSERT INTO staff(name,created_at) VALUES(?,?)", (name, now()))
                db.execute("INSERT INTO commission_rates(staff_id,effective_from,rate,created_at,created_by) VALUES(?,?,0,?,?)",
                           (cursor.lastrowid, "2000-01-01", now(), actor["id"]))
                audit(db, actor["id"], "create", "staff", str(cursor.lastrowid), after={"name": name})
        except sqlite3.IntegrityError:
            raise ValueError("Nhân viên đã tồn tại.") from None
        return jsonify({"id": cursor.lastrowid, "name": name, "active": 1}), 201

    @app.put("/api/schedule")
    def save_schedule():
        actor = admin()
        data = body()
        db = get_db()
        with db:
            # Lock before reading the version so two browsers cannot both save over the same base.
            db.execute("BEGIN IMMEDIATE")
            current = current_schedule(db)
            if data.get("baseVersion") != current["version"]:
                return jsonify({"error": "Lịch đã được người khác cập nhật. Hãy tải lại trước khi lưu."}), 409
            proposed = {"periods": data.get("periods"), "overrides": current["overrides"]}
            errors = validate_schedule(proposed, {r["id"] for r in db.execute("SELECT id FROM staff WHERE active=1")})
            if errors and errors[0].get("code") == "confirm_shared" and data.get("confirmShared") is True:
                approve_shared_overlaps(proposed, schedule_days(proposed))
                errors = validate_schedule(proposed, {r["id"] for r in db.execute("SELECT id FROM staff WHERE active=1")})
            if errors:
                return jsonify({"error": "Lịch chưa hợp lệ.", "fields": errors}), 422
            cursor = db.execute("INSERT INTO schedule_versions(data,created_at,created_by,note) VALUES(?,?,?,?)",
                                (json.dumps({"periods": proposed["periods"]}, ensure_ascii=False), now(), actor["id"], str(data.get("note") or "")[:300]))
            audit(db, actor["id"], "update", "schedule", str(cursor.lastrowid), before=current["periods"], after=proposed["periods"])
            db.execute("DELETE FROM schedule_drafts WHERE user_id=?", (actor["id"],))
        return jsonify(current_schedule(db))

    @app.put("/api/schedule/draft")
    def save_schedule_draft():
        actor = admin()
        data = body()
        periods = data.get("periods")
        serialized = json.dumps(periods, ensure_ascii=False)
        if not isinstance(periods, list) or len(serialized) > 1_000_000:
            raise ValueError("Bản nháp lịch không hợp lệ hoặc quá lớn.")
        db = get_db()
        with db:
            db.execute("INSERT INTO schedule_drafts(user_id,base_version,data,updated_at) VALUES(?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET base_version=excluded.base_version,data=excluded.data,updated_at=excluded.updated_at",
                       (actor["id"], int(data.get("baseVersion", 0)), serialized, now()))
        return jsonify({"savedAt": now()})

    @app.put("/api/overrides/<day>")
    def save_override(day):
        actor = admin()
        try:
            parsed_day = date.fromisoformat(day)
        except ValueError:
            raise ValueError("Ngày đổi ca không hợp lệ.") from None
        data = body()
        shifts = namespace_override_shifts(parsed_day, data.get("shifts"))
        db = get_db()
        schedule = current_schedule(db)
        errors = validate_day_shifts(parsed_day, shifts, schedule, {r["id"] for r in db.execute("SELECT id FROM staff WHERE active=1")})
        if errors and errors[0].get("code") == "confirm_shared" and data.get("confirmShared") is True:
            temporary = {"periods": schedule["periods"], "overrides": {**schedule["overrides"], day: shifts}}
            approve_shared_overlaps(temporary, (parsed_day, parsed_day + timedelta(days=1)))
            errors = validate_day_shifts(parsed_day, shifts, schedule, {r["id"] for r in db.execute("SELECT id FROM staff WHERE active=1")})
        if errors:
            return jsonify({"error": "Lịch ngày chưa hợp lệ.", "fields": errors}), 422
        before = schedule["overrides"].get(day)
        with db:
            db.execute("INSERT INTO day_overrides(day,shifts,updated_at,updated_by) VALUES(?,?,?,?) ON CONFLICT(day) DO UPDATE SET shifts=excluded.shifts,updated_at=excluded.updated_at,updated_by=excluded.updated_by",
                       (day, json.dumps(shifts, ensure_ascii=False), now(), actor["id"]))
            audit(db, actor["id"], "update", "day_override", day, before=before, after=shifts)
        return jsonify({"ok": True})

    @app.delete("/api/overrides/<day>")
    def delete_override(day):
        actor = admin()
        db = get_db()
        before = current_schedule(db)["overrides"].get(day)
        with db:
            db.execute("DELETE FROM day_overrides WHERE day=?", (day,))
            audit(db, actor["id"], "delete", "day_override", day, before=before)
        return jsonify({"ok": True})

    @app.post("/api/rates")
    def save_rate():
        actor = admin()
        data = body()
        try:
            sid, effective, rate = int(data["staffId"]), date.fromisoformat(data["effectiveFrom"]).isoformat(), float(data["rate"])
        except (KeyError, TypeError, ValueError):
            raise ValueError("Chọn nhân viên, ngày hiệu lực và tỷ lệ hợp lệ.") from None
        if not 0 <= rate <= 100:
            raise ValueError("Tỷ lệ phải từ 0% đến 100%.")
        db = get_db()
        if not db.execute("SELECT 1 FROM staff WHERE id=?", (sid,)).fetchone():
            raise ValueError("Nhân viên không tồn tại.")
        before = db.execute("SELECT rate FROM commission_rates WHERE staff_id=? AND effective_from=?", (sid, effective)).fetchone()
        with db:
            db.execute("INSERT INTO commission_rates(staff_id,effective_from,rate,created_at,created_by) VALUES(?,?,?,?,?) ON CONFLICT(staff_id,effective_from) DO UPDATE SET rate=excluded.rate,created_at=excluded.created_at,created_by=excluded.created_by",
                       (sid, effective, rate, now(), actor["id"]))
            audit(db, actor["id"], "update", "rate", f"{sid}:{effective}", before=dict(before) if before else None, after={"rate": rate})
        return jsonify({"ok": True})

    @app.post("/api/import/preview")
    def import_preview():
        admin()
        _, raw = uploaded_bytes()
        orders, summary = parse_csv(raw)
        db = get_db()
        existing = {r["id"] for r in db.execute("SELECT id FROM orders")}
        summary.update({"inserted": sum(o["id"] not in existing for o in orders),
                        "updated": sum(o["id"] in existing for o in orders),
                        "sha256": hashlib.sha256(raw).hexdigest(),
                        "closedOrders": sum(active_closed_for(o["createdAt"][:10]) for o in orders)})
        return jsonify(summary)

    @app.post("/api/import/commit")
    def import_commit():
        actor = admin()
        filename, raw = uploaded_bytes()
        if request.form.get("sha256") != hashlib.sha256(raw).hexdigest():
            abort(409, "File đã thay đổi sau khi xem trước. Hãy xem trước lại.")
        orders, summary = parse_csv(raw)
        if summary["errors"]:
            return jsonify({"error": "CSV còn dòng sai; chưa nhập đơn.", "rows": summary["errors"]}), 422
        db = get_db()
        with db:
            db.execute("BEGIN IMMEDIATE")
            if any(active_closed_for(o["createdAt"][:10]) for o in orders):
                abort(409, "File chứa đơn thuộc kỳ hoa hồng đã chốt. Hãy mở lại kỳ đó trước khi nhập.")
            existing = {r["id"] for r in db.execute("SELECT id FROM orders")}
            cursor = db.execute("INSERT INTO import_batches(filename,sha256,row_count,order_count,inserted,updated,created_at,created_by) VALUES(?,?,?,?,?,?,?,?)",
                                (filename[:250], hashlib.sha256(raw).hexdigest(), summary["rows"], len(orders),
                                 sum(o["id"] not in existing for o in orders), sum(o["id"] in existing for o in orders), now(), actor["id"]))
            for order in orders:
                db.execute("INSERT INTO orders(id,data,import_batch_id,updated_at) VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data,import_batch_id=excluded.import_batch_id,updated_at=excluded.updated_at",
                           (order["id"], json.dumps(order, ensure_ascii=False), cursor.lastrowid, now()))
            audit(db, actor["id"], "import", "csv", str(cursor.lastrowid), after={"file": filename, "rows": summary["rows"], "orders": len(orders)})
        return jsonify({"ok": True, "inserted": sum(o["id"] not in existing for o in orders), "updated": sum(o["id"] in existing for o in orders)})

    @app.get("/api/report")
    def get_report():
        start, end = request.args.get("from", ""), request.args.get("to", "")
        try:
            if date.fromisoformat(start) > date.fromisoformat(end):
                raise ValueError()
        except ValueError:
            raise ValueError("Chọn khoảng ngày hợp lệ; ngày bắt đầu không sau ngày kết thúc.") from None
        return jsonify(pack_report(start, end))

    @app.put("/api/manual/<path:order_id>")
    def manual_assign(order_id):
        actor = admin()
        data = body()
        db = get_db()
        try:
            sid = int(data["staffId"])
        except (KeyError, TypeError, ValueError):
            raise ValueError("Chọn nhân viên.") from None
        if not db.execute("SELECT 1 FROM staff WHERE id=? AND active=1", (sid,)).fetchone():
            raise ValueError("Nhân viên không tồn tại hoặc đã ngừng hoạt động.")
        reason = str(data.get("reason") or "").strip()
        if len(reason) < 5:
            raise ValueError("Ghi lý do điều chỉnh ít nhất 5 ký tự.")
        with db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT data FROM orders WHERE id=?", (order_id,)).fetchone()
            if not row:
                abort(404, "Không tìm thấy đơn.")
            order = json.loads(row["data"])
            if classify(order, current_schedule(db), {})["kind"] == "excluded":
                abort(422, "Đơn hủy, hoàn hoặc không thuộc LIVE không thể gán hoa hồng.")
            if active_closed_for(order["createdAt"][:10]):
                abort(409, "Đơn thuộc kỳ đã chốt. Hãy mở lại kỳ trước khi sửa.")
            before = db.execute("SELECT staff_id,reason FROM manual_assignments WHERE order_id=?", (order_id,)).fetchone()
            db.execute("INSERT INTO manual_assignments(order_id,staff_id,reason,updated_at,updated_by) VALUES(?,?,?,?,?) ON CONFLICT(order_id) DO UPDATE SET staff_id=excluded.staff_id,reason=excluded.reason,updated_at=excluded.updated_at,updated_by=excluded.updated_by",
                       (order_id, sid, reason, now(), actor["id"]))
            audit(db, actor["id"], "update", "manual_assignment", order_id, before=dict(before) if before else None, after={"staffId": sid, "reason": reason})
        return jsonify({"ok": True})

    @app.delete("/api/manual/<path:order_id>")
    def clear_manual(order_id):
        actor = admin()
        db = get_db()
        with db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT data FROM orders WHERE id=?", (order_id,)).fetchone()
            if not row:
                abort(404, "Không tìm thấy đơn.")
            if active_closed_for((json.loads(row["data"]).get("createdAt") or "")[:10]):
                abort(409, "Đơn thuộc kỳ đã chốt.")
            before = db.execute("SELECT staff_id,reason FROM manual_assignments WHERE order_id=?", (order_id,)).fetchone()
            db.execute("DELETE FROM manual_assignments WHERE order_id=?", (order_id,))
            audit(db, actor["id"], "delete", "manual_assignment", order_id, before=dict(before) if before else None)
        return jsonify({"ok": True})

    @app.post("/api/payroll/close")
    def close_payroll():
        actor = admin()
        data = body()
        start, end = str(data.get("from") or ""), str(data.get("to") or "")
        try:
            if date.fromisoformat(start) > date.fromisoformat(end):
                raise ValueError()
        except ValueError:
            raise ValueError("Chọn kỳ hoa hồng hợp lệ.") from None
        db = get_db()
        with db:
            db.execute("BEGIN IMMEDIATE")
            overlap = db.execute("SELECT 1 FROM payroll_closures WHERE reopened_at IS NULL AND start_day<=? AND end_day>=? LIMIT 1", (end, start)).fetchone()
            if overlap:
                abort(409, "Kỳ này chồng một kỳ đã chốt.")
            snapshot = pack_report(start, end)
            unresolved = [o for o in snapshot["review"] if o["assignment"]["kind"] == "review"]
            if unresolved:
                abort(422, f"Còn {len(unresolved)} đơn chưa gán; hãy đối soát trước khi chốt.")
            cursor = db.execute("INSERT INTO payroll_closures(start_day,end_day,snapshot,closed_at,closed_by) VALUES(?,?,?,?,?)",
                                (start, end, json.dumps(snapshot, ensure_ascii=False), now(), actor["id"]))
            audit(db, actor["id"], "close", "payroll", str(cursor.lastrowid), after={"from": start, "to": end, "totals": snapshot["totals"]})
        return jsonify({"id": cursor.lastrowid, "totals": snapshot["totals"]}), 201

    @app.get("/api/payroll/<int:closure_id>")
    def payroll_snapshot(closure_id):
        row = get_db().execute("SELECT * FROM payroll_closures WHERE id=?", (closure_id,)).fetchone()
        if not row:
            abort(404)
        return jsonify({"id": row["id"], "from": row["start_day"], "to": row["end_day"],
                        "closedAt": row["closed_at"], "reopenedAt": row["reopened_at"], "snapshot": json.loads(row["snapshot"])})

    @app.post("/api/payroll/<int:closure_id>/reopen")
    def reopen_payroll(closure_id):
        actor = admin()
        reason = str(body().get("reason") or "").strip()
        if len(reason) < 5:
            raise ValueError("Ghi lý do mở lại kỳ ít nhất 5 ký tự.")
        db = get_db()
        row = db.execute("SELECT * FROM payroll_closures WHERE id=? AND reopened_at IS NULL", (closure_id,)).fetchone()
        if not row:
            abort(404, "Không có kỳ đã chốt này.")
        with db:
            db.execute("UPDATE payroll_closures SET reopened_at=?,reopened_by=? WHERE id=?", (now(), actor["id"], closure_id))
            audit(db, actor["id"], "reopen", "payroll", str(closure_id), after={"reason": reason})
        return jsonify({"ok": True})

    @app.get("/api/audit")
    def audit_view():
        admin()
        rows = get_db().execute("SELECT a.id,a.at,a.action,a.object_type,a.object_id,u.username FROM audit_log a LEFT JOIN users u ON u.id=a.user_id ORDER BY a.id DESC LIMIT 100").fetchall()
        return jsonify([dict(r) for r in rows])

    @app.get("/api/backup")
    def backup_export():
        admin()
        response = jsonify(export_data(get_db()))
        response.headers["Content-Disposition"] = f"attachment; filename=liveledger-data-{date.today().isoformat()}.json"
        return response

    @app.post("/api/backup/preview")
    def preview_portable_backup():
        admin()
        _, raw = uploaded_bytes(100)
        _, summary = inspect_data(raw, get_db())
        return jsonify(summary)

    @app.post("/api/backup/commit")
    def commit_portable_backup():
        actor = admin()
        _, raw = uploaded_bytes(100)
        if request.form.get("sha256") != hashlib.sha256(raw).hexdigest():
            abort(409, "File đã thay đổi sau khi xem trước. Hãy xem trước lại.")
        payload, summary = inspect_data(raw, get_db())
        make_backup(Path(app.config["DATABASE_PATH"]), Path(app.config["BACKUP_DIR"]))
        restore_data(get_db(), payload, actor["id"])
        return jsonify({"ok": True, "orders": summary["orders"], "periods": summary["periods"]})

    @app.post("/api/backup/server")
    def server_backup():
        admin()
        path = make_backup(Path(app.config["DATABASE_PATH"]), Path(app.config["BACKUP_DIR"]))
        return jsonify({"ok": True, "file": path.name})

    @app.post("/api/legacy/preview")
    def preview_legacy():
        admin()
        _, raw = uploaded_bytes()
        _, summary = legacy_preview(raw)
        return jsonify(summary)

    @app.post("/api/legacy/commit")
    def commit_legacy():
        actor = admin()
        _, raw = uploaded_bytes()
        payload, summary = legacy_preview(raw)
        if request.form.get("sha256") != summary["sha256"]:
            abort(409, "File sao lưu đã thay đổi. Hãy xem trước lại.")
        replace_schedule = request.form.get("replaceSchedule") == "true"
        db = get_db()
        make_backup(Path(app.config["DATABASE_PATH"]), Path(app.config["BACKUP_DIR"]))
        cfg = payload["config"]
        staff_map = {}

        def convert_shift(old, days=True):
            start = str(old.get("start") or "")
            end = str(old.get("end") or "")
            next_day = end == "24:00" or (end < start)
            return {"id": str(old.get("id") or secrets.token_hex(8)), "staffId": staff_map[old["staff"].strip().upper()],
                    "start": start, "end": "00:00" if end == "24:00" else end,
                    "endDay": int(next_day), "days": list(old.get("days", list(range(7)))) if days else []}

        def convert_order(old):
            created = old.get("created")
            created_at = None
            if isinstance(created, dict) and created.get("date") is not None and created.get("minute") is not None:
                day = str(created["date"])
                total_seconds = min(86399, round(float(created["minute"]) * 60))
                created_at = f"{day}T{total_seconds // 3600:02d}:{(total_seconds // 60) % 60:02d}:{total_seconds % 60:02d}"
            return {"id": str(old["id"]), "createdAt": created_at,
                    "status": old.get("status", ""), "substatus": old.get("substatus", ""),
                    "channel": old.get("channel", ""), "refund": old.get("refund", 0),
                    "lines": old.get("lines", [])}

        with db:
            db.execute("BEGIN IMMEDIATE")
            if any(active_closed_for(str((o.get("created") or {}).get("date") or "")) for o in payload["orders"]):
                abort(409, "Bản sao lưu có đơn thuộc kỳ đã chốt. Hãy mở lại kỳ trước khi nhập.")
            staff_map.update({r["name"].upper(): r["id"] for r in db.execute("SELECT id,name FROM staff")})
            for name in summary["staff"]:
                staff_map.setdefault(name, None)
            for name, sid in list(staff_map.items()):
                if sid is None:
                    cursor = db.execute("INSERT INTO staff(name,created_at) VALUES(?,?)", (name, now()))
                    staff_map[name] = cursor.lastrowid
                    db.execute("INSERT INTO commission_rates(staff_id,effective_from,rate,created_at,created_by) VALUES(?,?,0,?,?)",
                               (cursor.lastrowid, "2000-01-01", now(), actor["id"]))
            if replace_schedule:
                periods = cfg.get("periods", [])
                if not periods:
                    raise ValueError("Bản sao lưu không có khoảng lịch để thay.")
                converted = {"periods": [{"id": str(p.get("id") or secrets.token_hex(8)), "start": p["start"],
                                          "end": p["end"], "shifts": [convert_shift(s) for s in p["slots"]]} for p in periods],
                             "overrides": {day: [convert_shift(s, False) for s in shifts] for day, shifts in cfg.get("overrides", {}).items()}}
                errors = validate_schedule(converted, set(staff_map.values()))
                if errors:
                    raise ValueError("Lịch trong bản sao lưu chưa hợp lệ: " + errors[0]["message"])
                db.execute("INSERT INTO schedule_versions(data,created_at,created_by,note) VALUES(?,?,?,?)",
                           (json.dumps({"periods": converted["periods"]}, ensure_ascii=False), now(), actor["id"], "Nhập bản sao lưu cũ"))
                db.execute("DELETE FROM day_overrides")
                for day, shifts in converted["overrides"].items():
                    db.execute("INSERT INTO day_overrides(day,shifts,updated_at,updated_by) VALUES(?,?,?,?)",
                               (day, json.dumps(shifts, ensure_ascii=False), now(), actor["id"]))
                for name, value in cfg.get("rates", {}).items():
                    sid = staff_map.get(name.strip().upper())
                    if sid is not None:
                        rate = float(value)
                        if not 0 <= rate <= 100:
                            raise ValueError(f"Tỷ lệ của {name} ngoài khoảng 0–100%.")
                        db.execute("INSERT INTO commission_rates(staff_id,effective_from,rate,created_at,created_by) VALUES(?,?,?,?,?) ON CONFLICT(staff_id,effective_from) DO UPDATE SET rate=excluded.rate,created_at=excluded.created_at,created_by=excluded.created_by",
                                   (sid, "2000-01-01", rate, now(), actor["id"]))
            for old in payload["orders"]:
                order = convert_order(old)
                db.execute("INSERT INTO orders(id,data,updated_at) VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data,updated_at=excluded.updated_at",
                           (order["id"], json.dumps(order, ensure_ascii=False), now()))
            if replace_schedule:
                for order_id, name in cfg.get("manual", {}).items():
                    sid = staff_map.get(str(name).strip().upper())
                    if sid is not None and db.execute("SELECT 1 FROM orders WHERE id=?", (order_id,)).fetchone():
                        db.execute("INSERT INTO manual_assignments(order_id,staff_id,reason,updated_at,updated_by) VALUES(?,?,?,?,?) ON CONFLICT(order_id) DO UPDATE SET staff_id=excluded.staff_id,reason=excluded.reason,updated_at=excluded.updated_at,updated_by=excluded.updated_by",
                                   (order_id, sid, "Chuyển từ công cụ cũ", now(), actor["id"]))
            audit(db, actor["id"], "import", "legacy_backup", summary["sha256"][:12], after={"orders": summary["orders"], "replaceSchedule": replace_schedule})
        return jsonify({"ok": True, "orders": summary["orders"], "replacedSchedule": replace_schedule})

    return app


def cli():
    parser = argparse.ArgumentParser(description="LiveLedger trên máy này")
    parser.add_argument("command", nargs="?", default="serve", choices=("serve", "backup"))
    parser.add_argument("--port", type=int, help="Cổng cố định (mặc định tự chọn từ 8001–8099)")
    args = parser.parse_args()
    from local import choose_port, prepare_environment
    prepare_environment()
    app = create_app()
    if args.command == "backup":
        print(make_backup(Path(app.config["DATABASE_PATH"]), Path(app.config["BACKUP_DIR"])))
    else:
        try:
            port = choose_port(args.port)
        except ValueError as error:
            parser.error(str(error))
        app.run(host="127.0.0.1", port=port, debug=False)


if __name__ == "__main__":
    cli()
