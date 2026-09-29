"""Portable business-data snapshots for independent local installations."""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from domain import validate_day_shifts, validate_schedule
from storage import all_orders, audit, current_schedule, now


FORMAT = "tooltiktok-local-v1"


def _upgrade_shared_export(payload: dict) -> dict:
    """Accept JSON files exported by the first server-backed release."""
    try:
        rates = [{"staffId": int(staff_id), "effectiveFrom": item["effectiveFrom"], "rate": item["rate"]}
                 for staff_id, history in payload["rates"].items() for item in history]
        manual = [{"orderId": order_id, "staffId": int(staff_id),
                   "reason": "Chuyển từ bản xuất cũ", "updatedAt": payload.get("exportedAt")}
                  for order_id, staff_id in payload["manual"].items()]
        closures = [{"id": item["id"], "from": item["start_day"], "to": item["end_day"],
                     "snapshot": json.loads(item["snapshot"]) if isinstance(item["snapshot"], str) else item["snapshot"],
                     "closedAt": item["closed_at"], "reopenedAt": item.get("reopened_at")}
                    for item in payload["closures"]]
        return {"format": FORMAT, "exportedAt": payload.get("exportedAt"),
                "staff": payload["staff"],
                "schedule": {"periods": payload["schedule"]["periods"], "overrides": payload["schedule"]["overrides"]},
                "rates": rates, "orders": payload["orders"], "manual": manual, "closures": closures}
    except (KeyError, TypeError, ValueError, AttributeError, json.JSONDecodeError):
        raise ValueError("Bản xuất LiveLedger cũ không đầy đủ hoặc bị hỏng.") from None


def export_data(db: sqlite3.Connection) -> dict:
    schedule = current_schedule(db)
    return {
        "format": FORMAT,
        "exportedAt": now(),
        "staff": [dict(row) for row in db.execute("SELECT id,name,active FROM staff ORDER BY id")],
        "schedule": {"periods": schedule["periods"], "overrides": schedule["overrides"]},
        "rates": [{"staffId": row["staff_id"], "effectiveFrom": row["effective_from"], "rate": row["rate"]}
                  for row in db.execute("SELECT staff_id,effective_from,rate FROM commission_rates ORDER BY id")],
        "orders": all_orders(db),
        "manual": [{"orderId": row["order_id"], "staffId": row["staff_id"], "reason": row["reason"],
                    "updatedAt": row["updated_at"]}
                   for row in db.execute("SELECT order_id,staff_id,reason,updated_at FROM manual_assignments")],
        "closures": [{"id": row["id"], "from": row["start_day"], "to": row["end_day"],
                      "snapshot": json.loads(row["snapshot"]), "closedAt": row["closed_at"],
                      "reopenedAt": row["reopened_at"]}
                     for row in db.execute("SELECT id,start_day,end_day,snapshot,closed_at,reopened_at FROM payroll_closures ORDER BY id")],
    }


def _money(value, label: str) -> None:
    try:
        amount = Decimal(str(value))
        if not amount.is_finite() or amount < 0:
            raise InvalidOperation()
    except (InvalidOperation, TypeError):
        raise ValueError(f"{label} không hợp lệ trong bản xuất dữ liệu.") from None


def inspect_data(raw: bytes, db: sqlite3.Connection) -> tuple[dict, dict]:
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ValueError("File JSON không đọc được.") from None
    if isinstance(payload, dict) and payload.get("format") == "tooltiktok-shared-v1":
        payload = _upgrade_shared_export(payload)
    if not isinstance(payload, dict) or payload.get("format") != FORMAT:
        raise ValueError("Đây không phải file dữ liệu của LiveLedger bản cài riêng.")
    staff, schedule, rates = payload.get("staff"), payload.get("schedule"), payload.get("rates")
    orders, manual, closures = payload.get("orders"), payload.get("manual"), payload.get("closures")
    if not isinstance(staff, list) or not isinstance(schedule, dict) or not isinstance(rates, list) or not isinstance(orders, list) or not isinstance(manual, list) or not isinstance(closures, list):
        raise ValueError("File thiếu một phần dữ liệu cần thiết.")
    ids, names = set(), set()
    for person in staff:
        if not isinstance(person, dict) or type(person.get("id")) is not int or person["id"] <= 0 or not isinstance(person.get("name"), str) or not person["name"].strip() or person.get("active") not in (0, 1):
            raise ValueError("Danh sách nhân viên trong file không hợp lệ.")
        if person["id"] in ids or person["name"].casefold() in names:
            raise ValueError("File có nhân viên trùng mã hoặc tên.")
        ids.add(person["id"]); names.add(person["name"].casefold())
    periods, overrides = schedule.get("periods"), schedule.get("overrides")
    if not isinstance(periods, list) or not isinstance(overrides, dict):
        raise ValueError("Lịch trong file không hợp lệ.")
    if len(staff) > 500 or len(periods) > 100 or len(overrides) > 10000 or len(rates) > 10000 or len(manual) > 100000 or len(closures) > 10000:
        raise ValueError("File có quá nhiều bản ghi ở một mục; hãy kiểm tra lại.")
    if sum(len(period.get("shifts", [])) for period in periods if isinstance(period, dict)) > 5000:
        raise ValueError("File có quá nhiều ca live.")
    try:
        errors = validate_schedule(schedule, ids)
    except (KeyError, TypeError, AttributeError, ValueError):
        raise ValueError("Lịch trong file không hợp lệ.") from None
    if errors:
        raise ValueError("Lịch trong file không hợp lệ: " + errors[0]["message"])
    for day, shifts in overrides.items():
        try:
            override_day = date.fromisoformat(day)
            day_errors = validate_day_shifts(override_day, shifts, schedule, ids)
        except (TypeError, KeyError, AttributeError, ValueError):
            raise ValueError("Lịch riêng theo ngày trong file không hợp lệ.") from None
        if day_errors:
            raise ValueError("Lịch riêng trong file không hợp lệ: " + day_errors[0]["message"])
    seen_rates = set()
    for item in rates:
        if not isinstance(item, dict) or item.get("staffId") not in ids:
            raise ValueError("Tỷ lệ hoa hồng có nhân viên không hợp lệ.")
        try:
            effective = date.fromisoformat(item["effectiveFrom"]).isoformat()
            rate = float(item["rate"])
        except (KeyError, TypeError, ValueError):
            raise ValueError("Tỷ lệ hoa hồng hoặc ngày hiệu lực không hợp lệ.") from None
        key = (item["staffId"], effective)
        if key in seen_rates or not math.isfinite(rate) or not 0 <= rate <= 100:
            raise ValueError("Tỷ lệ hoa hồng trùng hoặc ngoài khoảng 0–100%.")
        seen_rates.add(key)
    order_ids = set()
    for order in orders:
        if not isinstance(order, dict) or not isinstance(order.get("id"), str) or not order["id"] or order["id"] in order_ids or not isinstance(order.get("lines"), list):
            raise ValueError("File có đơn thiếu mã, trùng mã hoặc thiếu sản phẩm.")
        order_ids.add(order["id"])
        created = order.get("createdAt")
        if created is not None:
            try:
                datetime.fromisoformat(created)
            except (TypeError, ValueError):
                raise ValueError(f"Đơn {order['id']} có giờ tạo không hợp lệ.") from None
        _money(order.get("refund", 0), f"Tiền hoàn của đơn {order['id']}")
        for line in order["lines"]:
            if not isinstance(line, dict) or type(line.get("qty")) is not int or line["qty"] <= 0 or not isinstance(line.get("product"), str):
                raise ValueError(f"Dòng sản phẩm của đơn {order['id']} không hợp lệ.")
            _money(line.get("revenue"), f"Doanh số của đơn {order['id']}")
    seen_manual = set()
    for item in manual:
        if not isinstance(item, dict) or item.get("orderId") not in order_ids or item.get("staffId") not in ids or item.get("orderId") in seen_manual or not isinstance(item.get("reason"), str):
            raise ValueError("Dữ liệu gán đơn thủ công không hợp lệ.")
        seen_manual.add(item["orderId"])
    seen_closures = set()
    for item in closures:
        if not isinstance(item, dict) or type(item.get("id")) is not int or item["id"] <= 0 or item["id"] in seen_closures or not isinstance(item.get("snapshot"), dict):
            raise ValueError("Kỳ hoa hồng đã chốt không hợp lệ.")
        seen_closures.add(item["id"])
        try:
            if date.fromisoformat(item["from"]) > date.fromisoformat(item["to"]):
                raise ValueError()
            datetime.fromisoformat(item["closedAt"])
            if item.get("reopenedAt"):
                datetime.fromisoformat(item["reopenedAt"])
            if not isinstance(item["snapshot"]["totals"], dict) or not isinstance(item["snapshot"]["staff"], list):
                raise ValueError()
            _money(item["snapshot"]["totals"]["commission"], "Hoa hồng trong kỳ đã chốt")
        except (KeyError, TypeError, ValueError):
            raise ValueError("Ngày hoặc kết quả của kỳ đã chốt không hợp lệ.") from None
    summary = {
        "sha256": hashlib.sha256(raw).hexdigest(),
        "exportedAt": payload.get("exportedAt"),
        "staff": len(staff), "periods": len(periods), "orders": len(orders),
        "manual": len(manual), "closures": len(closures),
        "currentOrders": db.execute("SELECT count(*) FROM orders").fetchone()[0],
    }
    return payload, summary


def restore_data(db: sqlite3.Connection, payload: dict, actor_id: int) -> None:
    with db:
        db.execute("BEGIN IMMEDIATE")
        for table in ("manual_assignments", "payroll_closures", "commission_rates", "day_overrides",
                      "schedule_drafts", "schedule_versions", "orders", "import_batches", "staff", "audit_log"):
            db.execute(f"DELETE FROM {table}")
        stamp = now()
        for item in payload["staff"]:
            db.execute("INSERT INTO staff(id,name,active,created_at) VALUES(?,?,?,?)",
                       (item["id"], item["name"], item["active"], stamp))
        db.execute("INSERT INTO schedule_versions(data,created_at,created_by,note) VALUES(?,?,?,?)",
                   (json.dumps({"periods": payload["schedule"]["periods"]}, ensure_ascii=False), stamp, actor_id, "Nhập dữ liệu từ bản cài khác"))
        for day, shifts in payload["schedule"]["overrides"].items():
            db.execute("INSERT INTO day_overrides(day,shifts,updated_at,updated_by) VALUES(?,?,?,?)",
                       (day, json.dumps(shifts, ensure_ascii=False), stamp, actor_id))
        for item in payload["rates"]:
            db.execute("INSERT INTO commission_rates(staff_id,effective_from,rate,created_at,created_by) VALUES(?,?,?,?,?)",
                       (item["staffId"], item["effectiveFrom"], item["rate"], stamp, actor_id))
        for order in payload["orders"]:
            db.execute("INSERT INTO orders(id,data,updated_at) VALUES(?,?,?)",
                       (order["id"], json.dumps(order, ensure_ascii=False), stamp))
        for item in payload["manual"]:
            db.execute("INSERT INTO manual_assignments(order_id,staff_id,reason,updated_at,updated_by) VALUES(?,?,?,?,?)",
                       (item["orderId"], item["staffId"], item["reason"], item.get("updatedAt") or stamp, actor_id))
        for item in payload["closures"]:
            db.execute("INSERT INTO payroll_closures(id,start_day,end_day,snapshot,closed_at,closed_by,reopened_at,reopened_by) VALUES(?,?,?,?,?,?,?,?)",
                       (item["id"], item["from"], item["to"], json.dumps(item["snapshot"], ensure_ascii=False),
                        item["closedAt"], actor_id, item.get("reopenedAt"), actor_id if item.get("reopenedAt") else None))
        audit(db, actor_id, "restore", "portable_backup", str(payload.get("exportedAt") or "unknown"),
              after={"orders": len(payload["orders"]), "periods": len(payload["schedule"]["periods"])})
