"""Pure scheduling, CSV, and commission rules for each local installation."""

from __future__ import annotations

import csv
import io
import re
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from itertools import combinations


TIME_RE = re.compile(r"^(\d{2}):(\d{2})$")
CANCEL_RE = re.compile(r"hủy|huỷ|cancel|hoàn tiền|hoàn trả|trả hàng|return|refund", re.I)
REQUIRED_COLUMNS = {
    "Order ID", "Created Time", "Product Name", "Quantity", "SKU Subtotal After Discount"
}


def minute(value: str) -> int:
    match = TIME_RE.fullmatch(str(value or ""))
    if not match or int(match[1]) > 23 or int(match[2]) > 59:
        raise ValueError("Giờ phải theo dạng HH:MM từ 00:00 đến 23:59.")
    return int(match[1]) * 60 + int(match[2])


def day_number(value: date) -> int:
    """Sunday=0, matching the UI and legacy backups."""
    return (value.weekday() + 1) % 7


def _period_for(periods: list[dict], day: date) -> dict | None:
    key = day.isoformat()
    return next((p for p in periods if p["start"] <= key <= p["end"]), None)


def shifts_for(schedule: dict, day: date) -> list[dict]:
    overrides = schedule.get("overrides", {})
    if day.isoformat() in overrides:
        return overrides[day.isoformat()]
    period = _period_for(schedule.get("periods", []), day)
    return [s for s in period["shifts"] if day_number(day) in s["days"]] if period else []


def _intervals_for(schedule: dict, day: date) -> list[tuple[int, int, dict]]:
    result = []
    for anchor, offset in ((day - timedelta(days=1), -1440), (day, 0)):
        for shift in shifts_for(schedule, anchor):
            start = minute(shift["start"]) + offset
            end = minute(shift["end"]) + 1440 * int(shift["endDay"]) + offset
            if end > 0 and start < 1440:
                result.append((start, end, shift))
    return result


def _shared_pair(left: dict, right: dict) -> bool:
    def confirmed(owner, partner):
        return any(isinstance(link, dict) and link.get("shiftId") == partner["id"]
                   and link.get("ownerStaffId") == owner["staffId"] and link.get("staffId") == partner["staffId"]
                   for link in owner.get("sharedWith", []))
    return confirmed(left, right) or confirmed(right, left)


def _valid_shared_links(shift: dict) -> bool:
    links = shift.get("sharedWith", [])
    return isinstance(links, list) and all(
        isinstance(link, dict) and isinstance(link.get("shiftId"), str) and link["shiftId"]
        and link["shiftId"] != shift.get("id") and type(link.get("ownerStaffId")) is int
        and type(link.get("staffId")) is int for link in links)


def _overlap_pairs(intervals: list[tuple[int, int, dict]]):
    for left, right in combinations(intervals, 2):
        if max(left[0], right[0]) < min(left[1], right[1]):
            yield left, right


def approve_shared_overlaps(schedule: dict, days) -> None:
    """Record the user's confirmation on every overlapping pair of shifts."""
    for day in days:
        for left, right in _overlap_pairs(_intervals_for(schedule, day)):
            a, b = left[2], right[2]
            if a["staffId"] == b["staffId"]:
                continue
            for owner, partner in ((a, b), (b, a)):
                links = owner.setdefault("sharedWith", [])
                link = {"shiftId": partner["id"], "ownerStaffId": owner["staffId"], "staffId": partner["staffId"]}
                if link not in links:
                    links.append(link)


def _overlap_errors(schedule: dict, days) -> list[dict]:
    pending = []
    seen_pairs = set()
    for day in sorted(days):
        intervals = _intervals_for(schedule, day)
        for group in combinations(intervals, 3):
            if max(item[0] for item in group) < min(item[1] for item in group):
                return [{"path": "overlap", "message": f"Ngày {day:%d/%m/%Y}: tối đa hai nhân viên được live chung cùng lúc."}]
        pairs = list(_overlap_pairs(intervals))
        for left, right in pairs:
            a, b = left[2], right[2]
            if a["staffId"] == b["staffId"]:
                return [{"path": "overlap", "message": f"Ngày {day:%d/%m/%Y}: một nhân viên có hai ca chồng giờ."}]
        for left, right in pairs:
            a, b = left[2], right[2]
            if not _shared_pair(a, b):
                pair = tuple(sorted((a["id"], b["id"])))
                if pair not in seen_pairs:
                    pending.append({"path": "overlap", "code": "confirm_shared", "staffIds": [a["staffId"], b["staffId"]],
                                    "message": f"Ngày {day:%d/%m/%Y}: hai ca chồng giờ. Xác nhận live chung để chia doanh thu 50/50."})
                    seen_pairs.add(pair)
    return pending


def namespace_override_shifts(day: date, shifts):
    """Keep one-day shift IDs distinct from recurring shifts across midnight."""
    if not isinstance(shifts, list):
        return shifts
    prefix = f"day-{day.isoformat()}-"
    ids = {shift["id"]: shift["id"] if shift["id"].startswith(prefix) else prefix + shift["id"]
           for shift in shifts if isinstance(shift, dict) and isinstance(shift.get("id"), str) and shift["id"]}
    for shift in shifts:
        if isinstance(shift, dict) and shift.get("id") in ids:
            shift["id"] = ids[shift["id"]]
            if isinstance(shift.get("sharedWith"), list):
                for link in shift["sharedWith"]:
                    if isinstance(link, dict) and isinstance(link.get("shiftId"), str):
                        link["shiftId"] = ids.get(link["shiftId"], link["shiftId"])
    return shifts


def schedule_days(schedule: dict) -> set[date]:
    days: set[date] = set()
    for period in schedule["periods"]:
        first, last = date.fromisoformat(period["start"]), date.fromisoformat(period["end"])
        for delta in range((last - first).days + 2):
            days.add(first + timedelta(days=delta))
    for key in schedule.get("overrides", {}):
        day = date.fromisoformat(key)
        days.update((day, day + timedelta(days=1)))
    return days


def validate_schedule(schedule: dict, staff_ids: set[int]) -> list[dict]:
    """Return field-addressable errors, including cross-midnight conflicts."""
    errors: list[dict] = []
    periods = schedule.get("periods")
    if not isinstance(periods, list) or not periods:
        return [{"path": "periods", "message": "Cần ít nhất một khoảng lịch."}]
    seen_ids: set[str] = set()
    for pi, period in enumerate(periods):
        path = f"periods.{pi}"
        try:
            start, end = date.fromisoformat(period["start"]), date.fromisoformat(period["end"])
            if end < start:
                raise ValueError()
        except (KeyError, TypeError, ValueError):
            errors.append({"path": path + ".dates", "message": f"Khoảng {pi + 1}: chọn ngày bắt đầu và kết thúc hợp lệ."})
            continue
        if (end - start).days > 3660:
            errors.append({"path": path + ".dates", "message": f"Khoảng {pi + 1}: tối đa 10 năm."})
        if not isinstance(period.get("shifts"), list) or not period["shifts"]:
            errors.append({"path": path + ".shifts", "message": f"Khoảng {pi + 1}: cần ít nhất một ca."})
            continue
        for si, shift in enumerate(period["shifts"]):
            spath = f"{path}.shifts.{si}"
            sid = str(shift.get("id") or "")
            if not sid or sid in seen_ids:
                errors.append({"path": spath, "message": "Mỗi ca cần một mã riêng."})
            seen_ids.add(sid)
            if not _valid_shared_links(shift):
                errors.append({"path": spath + ".sharedWith", "message": "Danh sách ca live chung không hợp lệ."})
            if shift.get("staffId") not in staff_ids:
                errors.append({"path": spath + ".staffId", "message": f"Khoảng {pi + 1}, ca {si + 1}: chọn nhân viên."})
            days = shift.get("days")
            if not isinstance(days, list) or not days or any(type(d) is not int or d not in range(7) for d in days):
                errors.append({"path": spath + ".days", "message": f"Khoảng {pi + 1}, ca {si + 1}: chọn ít nhất một thứ trong tuần."})
            try:
                start_min = minute(shift["start"])
            except (KeyError, ValueError):
                errors.append({"path": spath + ".start", "message": f"Khoảng {pi + 1}, ca {si + 1}: chọn giờ bắt đầu."})
                continue
            try:
                end_min = minute(shift["end"])
            except (KeyError, ValueError):
                errors.append({"path": spath + ".end", "message": f"Khoảng {pi + 1}, ca {si + 1}: chọn giờ kết thúc."})
                continue
            if shift.get("endDay") not in (0, 1) or type(shift.get("endDay")) is not int:
                errors.append({"path": spath + ".endDay", "message": f"Khoảng {pi + 1}, ca {si + 1}: chọn kết thúc hôm nay hoặc hôm sau."})
            elif not 0 < end_min + shift["endDay"] * 1440 - start_min <= 1440:
                errors.append({"path": spath + ".end", "message": f"Khoảng {pi + 1}, ca {si + 1}: giờ kết thúc phải sau giờ bắt đầu và ca không quá 24 giờ."})
    if errors:
        return errors
    sorted_periods = sorted(periods, key=lambda p: p["start"])
    for left, right in zip(sorted_periods, sorted_periods[1:]):
        if left["end"] >= right["start"]:
            errors.append({"path": "periods", "message": f"Khoảng {left['start']}–{left['end']} chồng ngày với {right['start']}–{right['end']}."})
    if errors:
        return errors
    try:
        dates = schedule_days(schedule)
    except ValueError:
        return [{"path": "overrides", "message": "Ngày đổi ca không hợp lệ."}]
    return _overlap_errors(schedule, dates)


def validate_day_shifts(day: date, shifts: list[dict], schedule: dict, staff_ids: set[int]) -> list[dict]:
    temporary = {"periods": schedule["periods"], "overrides": {**schedule.get("overrides", {}), day.isoformat(): shifts}}
    # Check the new day's fields and the adjacent overnight boundaries using the same rules.
    if not isinstance(shifts, list):
        return [{"path": "shifts", "message": "Danh sách ca không hợp lệ."}]
    seen_ids = set()
    for i, shift in enumerate(shifts):
        if not isinstance(shift, dict) or not isinstance(shift.get("id"), str) or not shift["id"] or shift["id"] in seen_ids:
            return [{"path": f"shifts.{i}.id", "message": "Mỗi ca trong ngày cần một mã riêng."}]
        seen_ids.add(shift["id"])
        if shift.get("staffId") not in staff_ids:
            return [{"path": f"shifts.{i}.staffId", "message": f"Ca {i + 1}: chọn nhân viên."}]
        if not _valid_shared_links(shift):
            return [{"path": f"shifts.{i}.sharedWith", "message": "Danh sách ca live chung không hợp lệ."}]
        try:
            start, end = minute(shift["start"]), minute(shift["end"])
            offset = shift["endDay"]
            if type(offset) is not int or offset not in (0, 1) or not 0 < end + offset * 1440 - start <= 1440:
                raise ValueError()
        except (KeyError, ValueError):
            return [{"path": f"shifts.{i}.end", "message": f"Ca {i + 1}: chọn khoảng giờ hợp lệ, tối đa 24 giờ."}]
    return _overlap_errors(temporary, (day, day + timedelta(days=1)))


def classify(order: dict, schedule: dict, manual: dict[str, int]) -> dict:
    if not order.get("createdAt"):
        return {"kind": "excluded", "staffId": None, "reason": "Thiếu hoặc sai giờ tạo"}
    if CANCEL_RE.search(str(order.get("status", "")) + " " + str(order.get("substatus", ""))) or Decimal(str(order.get("refund", 0) or 0)) > 0:
        return {"kind": "excluded", "staffId": None, "reason": "Hủy hoặc hoàn tiền"}
    if str(order.get("channel", "")).strip().upper() != "LIVE":
        return {"kind": "excluded", "staffId": None, "reason": "Không thuộc kênh LIVE"}
    if order["id"] in manual:
        sid = manual[order["id"]]
        return {"kind": "assigned", "staffId": sid, "shares": [{"staffId": sid, "fraction": 1}], "reason": "Gán thủ công"}
    created = datetime.fromisoformat(order["createdAt"])
    offset = created.hour * 60 + created.minute + created.second / 60
    matches = []
    for start, end, shift in _intervals_for(schedule, created.date()):
        if start <= offset < end:
            matches.append(shift)
    if len(matches) == 1:
        sid = matches[0]["staffId"]
        return {"kind": "assigned", "staffId": sid, "shares": [{"staffId": sid, "fraction": 1}], "reason": "Theo lịch live"}
    if len(matches) == 2 and matches[0]["staffId"] != matches[1]["staffId"] and _shared_pair(*matches):
        return {"kind": "assigned", "staffId": None,
                "shares": [{"staffId": shift["staffId"], "fraction": 0.5} for shift in matches],
                "reason": "Live chung · chia doanh thu 50/50"}
    return {"kind": "review", "staffId": None, "reason": "Ca live chồng nhau" if matches else "Ngoài khung giờ live"}


def _decimal(value: str, label: str, row: int) -> Decimal:
    cleaned = str(value or "").strip()
    if not (re.fullmatch(r"\d+(?:\.\d+)?", cleaned) or re.fullmatch(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?", cleaned)):
        raise ValueError(f"Dòng {row}: {label} không phải số rõ ràng (ví dụ 1000 hoặc 1,000.50).")
    cleaned = cleaned.replace(",", "")
    try:
        number = Decimal(cleaned)
        if not number.is_finite():
            raise InvalidOperation()
        return number
    except InvalidOperation:
        raise ValueError(f"Dòng {row}: {label} không phải số.") from None


def parse_csv(data: bytes) -> tuple[list[dict], dict]:
    if len(data) > 25 * 1024 * 1024:
        raise ValueError("File CSV vượt 25 MB.")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ValueError("File CSV cần mã hóa UTF-8.") from None
    reader = csv.DictReader(io.StringIO(text, newline=""))
    headers = set(reader.fieldnames or [])
    missing = REQUIRED_COLUMNS - headers
    if missing:
        raise ValueError("CSV thiếu cột: " + ", ".join(sorted(missing)))
    orders: dict[str, dict] = {}
    errors = []
    rows = 0
    for row_number, row in enumerate(reader, 2):
        rows += 1
        if None in row:
            errors.append(f"Dòng {row_number}: số cột không khớp tiêu đề.")
            continue
        order_id = (row.get("Order ID") or "").strip()
        if not order_id:
            errors.append(f"Dòng {row_number}: thiếu mã đơn.")
            continue
        raw_time = (row.get("Created Time") or "").strip()
        try:
            created = datetime.strptime(raw_time, "%d/%m/%Y %H:%M:%S")
        except ValueError:
            try:
                created = datetime.strptime(raw_time, "%d/%m/%Y %H:%M")
            except ValueError:
                errors.append(f"Dòng {row_number}: giờ tạo đơn không đúng định dạng ngày/tháng/năm giờ:phút.")
                continue
        try:
            quantity = _decimal(row.get("Quantity", ""), "Số lượng", row_number)
            amount = _decimal(row.get("SKU Subtotal After Discount", ""), "Doanh số", row_number)
            refund = _decimal(row.get("Order Refund Amount") or "0", "Tiền hoàn", row_number)
            if quantity <= 0 or quantity != quantity.to_integral_value() or amount < 0 or refund < 0:
                raise ValueError(f"Dòng {row_number}: số lượng phải là số nguyên dương; tiền không được âm.")
        except ValueError as exc:
            errors.append(str(exc))
            continue
        line = {
            "sku": (row.get("Seller SKU") or row.get("SKU ID") or "").strip(),
            "product": (row.get("Product Name") or "").strip(),
            "variation": (row.get("Variation") or "").strip(),
            "qty": int(quantity),
            "revenue": str(amount),
        }
        order = orders.get(order_id)
        if order is None:
            order = {
                "id": order_id,
                "createdAt": created.isoformat(timespec="seconds"),
                "status": (row.get("Order Status") or "").strip(),
                "substatus": (row.get("Order Substatus") or "").strip(),
                "channel": (row.get("Order Channel") or "").strip(),
                "refund": str(refund),
                "lines": [],
            }
            orders[order_id] = order
        elif order["createdAt"] != created.isoformat(timespec="seconds"):
            errors.append(f"Dòng {row_number}: mã đơn {order_id} có giờ tạo khác các dòng trước.")
        order["lines"].append(line)
        if len(errors) >= 100:
            break
    if not rows:
        raise ValueError("CSV không có dòng đơn hàng.")
    return list(orders.values()), {"rows": rows, "orders": len(orders), "errors": errors, "channels": dict(Counter(o["channel"] or "(trống)" for o in orders.values()))}


def report(orders: list[dict], schedule: dict, manual: dict[str, int], rates: dict[int, list[dict]], staff: dict[int, str], start: str, end: str) -> dict:
    by_staff = defaultdict(lambda: {"orders": Decimal(0), "qty": Decimal(0), "revenue": Decimal(0), "commission": Decimal(0)})
    products = defaultdict(lambda: {"orders": {}, "qty": Decimal(0), "revenue": Decimal(0)})
    details, review = [], []
    for order in orders:
        day = (order.get("createdAt") or "")[:10]
        if day and (day < start or day > end):
            continue
        assignment = classify(order, schedule, manual)
        detail = {**order, "assignment": assignment}
        details.append(detail)
        if assignment["kind"] != "assigned":
            review.append(detail)
            continue
        detail["rates"] = []
        for share in assignment["shares"]:
            sid, fraction = share["staffId"], Decimal(str(share["fraction"]))
            effective = Decimal(str(next((r["rate"] for r in reversed(rates.get(sid, [])) if r["effectiveFrom"] <= day), 0)))
            by_staff[sid]["orders"] += fraction
            for line in order["lines"]:
                qty, amount = Decimal(str(line["qty"])) * fraction, Decimal(str(line["revenue"])) * fraction
                by_staff[sid]["qty"] += qty
                by_staff[sid]["revenue"] += amount
                by_staff[sid]["commission"] += amount * effective / Decimal(100)
                key = (sid, line["product"] or "Sản phẩm không tên")
                products[key]["orders"][order["id"]] = fraction
                products[key]["qty"] += qty
                products[key]["revenue"] += amount
            detail["rates"].append({"staffId": sid, "rate": float(effective)})
        if assignment["staffId"] is not None:
            detail["rate"] = detail["rates"][0]["rate"]
    staff_rows = [{"staffId": sid, "staff": staff.get(sid, "Nhân viên đã xóa"),
                   "orders": float(values["orders"]), "qty": float(values["qty"]),
                   "revenue": float(values["revenue"]), "commission": float(values["commission"])}
                  for sid, values in by_staff.items()]
    staff_rows.sort(key=lambda r: -r["revenue"])
    product_rows = [{"staffId": sid, "staff": staff.get(sid, "Nhân viên đã xóa"), "product": name,
                     "orders": float(sum(values["orders"].values())), "qty": float(values["qty"]), "revenue": float(values["revenue"])}
                    for (sid, name), values in products.items()]
    product_rows.sort(key=lambda r: (r["staff"], -r["revenue"]))
    totals = {key: float(sum(values[key] for values in by_staff.values())) for key in ("orders", "qty", "revenue", "commission")}
    totals["review"] = len(review)
    return {"staff": staff_rows, "products": product_rows, "orders": details, "review": review, "totals": totals}
