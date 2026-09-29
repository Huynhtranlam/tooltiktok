import copy
import io
import json

import pytest
from werkzeug.security import generate_password_hash

from app import create_app
from domain import classify, validate_schedule
from storage import current_schedule, get_db, now


@pytest.fixture
def shared(tmp_path):
    app = create_app({
        "TESTING": True,
        "SECRET_KEY": "test-secret-for-isolated-suite",
        "DATABASE_PATH": str(tmp_path / "shared.sqlite3"),
        "BACKUP_DIR": str(tmp_path / "backups"),
    })
    with app.app_context():
        db = get_db()
        with db:
            db.execute("INSERT INTO users(username,password_hash,role,created_at) VALUES(?,?,?,?)",
                       ("owner", generate_password_hash("a-strong-test-password"), "admin", now()))
    return app


def login(client):
    response = client.post("/api/login", json={"username": "owner", "password": "a-strong-test-password"})
    assert response.status_code == 200
    return {"X-CSRF-Token": response.json["csrf"]}


def sample_csv(*rows):
    head = "Order ID,Created Time,Product Name,Quantity,SKU Subtotal After Discount,Order Status,Order Channel,Order Refund Amount\n"
    return (head + "\n".join(rows) + "\n").encode("utf-8")


def upload(client, path, raw, headers, **fields):
    return client.post(path, data={"file": (io.BytesIO(raw), "orders.csv"), **fields}, headers=headers)


def test_midnight_boundary_and_overlapping_shift(shared):
    with shared.app_context():
        db = get_db()
        schedule = current_schedule(db)
        staff_ids = {r["name"]: r["id"] for r in db.execute("SELECT id,name FROM staff")}
        order = lambda stamp: {"id": stamp, "createdAt": stamp, "status": "Cần vận chuyển", "substatus": "", "channel": "LIVE", "refund": 0, "lines": []}
        assert classify(order("2026-09-21T00:30:00"), schedule, {})["staffId"] == staff_ids["HÀO"]
        assert classify(order("2026-09-21T01:00:00"), schedule, {})["kind"] == "review"
        bad = copy.deepcopy(schedule)
        bad["periods"][0]["shifts"].append({"id":"overlap", "staffId":staff_ids["VY"], "start":"21:30", "end":"22:00", "endDay":0, "days":[0]})
        errors = validate_schedule(bad, set(staff_ids.values()))
        assert errors and "chồng" in errors[0]["message"]


def test_seeded_weekdays_match_the_three_schedule_photos(shared):
    with shared.app_context():
        periods = current_schedule(get_db())["periods"]
        assert [(p["start"], p["end"]) for p in periods] == [
            ("2026-09-01", "2026-09-20"),
            ("2026-09-21", "2026-09-27"),
            ("2026-09-28", "2026-10-04"),
        ]
        second = {shift["id"]: shift for shift in periods[1]["shifts"]}
        third = {shift["id"]: shift for shift in periods[2]["shifts"]}
        assert second["p2-nhung"]["days"] == [0, 1, 2, 3, 4, 5]
        assert second["p2-hao"]["days"] == [1, 3, 4, 5]
        assert third["p3-hao"]["days"] == [0, 2, 3, 5, 6]


def test_two_clients_share_saved_schedule_and_csrf(shared):
    first, second = shared.test_client(), shared.test_client()
    h1, h2 = login(first), login(second)
    state = first.get("/api/state").json
    assert len(state["schedule"]["periods"]) == 3
    assert first.put("/api/schedule", json={"baseVersion":state["schedule"]["version"], "periods":state["schedule"]["periods"]}).status_code == 403
    periods = copy.deepcopy(state["schedule"]["periods"])
    periods[2]["shifts"][0]["end"] = "12:50"
    saved = first.put("/api/schedule", json={"baseVersion":state["schedule"]["version"], "periods":periods}, headers=h1)
    assert saved.status_code == 200, saved.json
    other = second.get("/api/state").json
    assert other["schedule"]["periods"][2]["shifts"][0]["end"] == "12:50"
    conflict = second.put("/api/schedule", json={"baseVersion":state["schedule"]["version"], "periods":periods}, headers=h2)
    assert conflict.status_code == 409


def test_preview_import_non_live_manual_guard_and_closed_snapshot(shared):
    client = shared.test_client()
    headers = login(client)
    raw = sample_csv(
        "LIVE-1,20/09/2026 22:30:00,San pham A,2,100000,Can van chuyen,LIVE,0",
        "SHOP-1,20/09/2026 22:35:00,San pham B,1,50000,Can van chuyen,SHOP,0",
    )
    preview = upload(client, "/api/import/preview", raw, headers)
    assert preview.status_code == 200 and preview.json["orders"] == 2
    commit = upload(client, "/api/import/commit", raw, headers, sha256=preview.json["sha256"])
    assert commit.status_code == 200 and commit.json["inserted"] == 2
    view = client.get("/api/report?from=2026-09-20&to=2026-09-20").json
    assert view["totals"]["orders"] == 1
    assert next(o for o in view["orders"] if o["id"] == "SHOP-1")["assignment"]["kind"] == "excluded"
    forbidden = client.put("/api/manual/SHOP-1", json={"staffId":1,"reason":"wrong channel"}, headers=headers)
    assert forbidden.status_code == 422
    rate = client.post("/api/rates", json={"staffId":5,"effectiveFrom":"2026-09-01","rate":10}, headers=headers)
    assert rate.status_code == 200
    closed = client.post("/api/payroll/close", json={"from":"2026-09-20","to":"2026-09-20"}, headers=headers)
    assert closed.status_code == 201, closed.json
    frozen = client.get(f"/api/payroll/{closed.json['id']}").json
    assert frozen["snapshot"]["totals"]["commission"] == 10000
    assert client.post("/api/rates", json={"staffId":5,"effectiveFrom":"2026-09-01","rate":20}, headers=headers).status_code == 200
    assert client.get(f"/api/payroll/{closed.json['id']}").json["snapshot"]["totals"]["commission"] == 10000
    assert upload(client, "/api/import/commit", raw, headers, sha256=preview.json["sha256"]).status_code == 409


def test_bad_csv_is_previewed_but_never_committed(shared):
    client = shared.test_client(); headers = login(client)
    raw = sample_csv("X,20/09/2026 22:30:00,Product,1,not-money,Open,LIVE,0")
    preview = upload(client, "/api/import/preview", raw, headers)
    assert preview.status_code == 200 and preview.json["errors"]
    commit = upload(client, "/api/import/commit", raw, headers, sha256=preview.json["sha256"])
    assert commit.status_code == 422
    assert client.get("/api/state").json["orderCount"] == 0


def test_server_draft_viewer_permissions_and_day_overlap(shared):
    first, second = shared.test_client(), shared.test_client()
    headers = login(first); login(second)
    schedule = first.get("/api/state").json["schedule"]
    draft = copy.deepcopy(schedule["periods"])
    draft[2]["shifts"][0]["end"] = "12:58"
    assert first.put("/api/schedule/draft", json={"baseVersion":schedule["version"],"periods":draft}, headers=headers).status_code == 200
    assert second.get("/api/state").json["draft"]["periods"][2]["shifts"][0]["end"] == "12:58"
    overlap = first.put("/api/overrides/2026-09-21", json={"shifts":[{"id":"early","staffId":1,"start":"00:30","end":"02:00","endDay":0}]}, headers=headers)
    assert overlap.status_code == 422
    with shared.app_context():
        db = get_db()
        with db:
            db.execute("INSERT INTO users(username,password_hash,role,created_at) VALUES(?,?,?,?)",
                       ("viewer",generate_password_hash("viewer-test-password"),"viewer",now()))
    observer = shared.test_client()
    result = observer.post("/api/login", json={"username":"viewer","password":"viewer-test-password"})
    view_headers = {"X-CSRF-Token":result.json["csrf"]}
    assert observer.get("/api/state").status_code == 200
    assert observer.put("/api/schedule", json={"baseVersion":schedule["version"],"periods":draft}, headers=view_headers).status_code == 403


def test_ambiguous_amount_rejected(shared):
    client = shared.test_client(); headers = login(client)
    raw = sample_csv('X,20/09/2026 22:30:00,Product,1,"1,5",Open,LIVE,0')
    preview = upload(client, "/api/import/preview", raw, headers)
    assert preview.json["errors"] and "Doanh số" in preview.json["errors"][0]


def test_legacy_backup_import_without_replacing_shared_schedule(shared):
    client = shared.test_client(); headers = login(client)
    backup = {"version":1,"config":{"periods":[],"overrides":{},"rates":{"HÀO":5},"manual":{}},
              "orders":[{"id":"OLD-1","created":{"date":"2026-09-20","minute":1320,"label":"20/09/2026 22:00"},
                         "status":"Cần vận chuyển","substatus":"","channel":"LIVE","refund":0,
                         "lines":[{"sku":"S","product":"Old product","variation":"","qty":1,"revenue":100000}]}]}
    raw = json.dumps(backup,ensure_ascii=False).encode("utf-8")
    preview = upload(client,"/api/legacy/preview",raw,headers)
    assert preview.status_code == 200 and preview.json["orders"] == 1
    commit = upload(client,"/api/legacy/commit",raw,headers,sha256=preview.json["sha256"],replaceSchedule="false")
    assert commit.status_code == 200, commit.json
    state = client.get("/api/state").json
    assert state["orderCount"] == 1 and len(state["schedule"]["periods"]) == 3


def test_undated_legacy_order_remains_visible_for_review(shared):
    client = shared.test_client(); headers = login(client)
    backup = {"version":1,"config":{"periods":[],"overrides":{},"rates":{},"manual":{}},
              "orders":[{"id":"NO-TIME","created":None,"status":"Open","channel":"LIVE","refund":0,
                         "lines":[{"product":"Product","qty":1,"revenue":1000}]}]}
    raw = json.dumps(backup).encode()
    preview = upload(client,"/api/legacy/preview",raw,headers)
    assert preview.status_code == 200
    commit = upload(client,"/api/legacy/commit",raw,headers,sha256=preview.json["sha256"],replaceSchedule="false")
    assert commit.status_code == 200, commit.json
    report = client.get("/api/report?from=2026-09-20&to=2026-09-20").json
    assert report["totals"]["review"] == 1
    assert report["review"][0]["assignment"]["reason"] == "Thiếu hoặc sai giờ tạo"
    assert client.put("/api/manual/NO-TIME",json={"staffId":1,"reason":"manual"},headers=headers).status_code == 422


def test_legacy_overnight_schedule_can_replace_initial(shared):
    client = shared.test_client(); headers = login(client)
    backup = {"version":1,"config":{"periods":[{"id":"old-period","start":"2026-10-05","end":"2026-10-11",
              "slots":[{"id":"old-hao","staff":"HÀO","start":"21:00","end":"01:00","days":[0,1,2,3,4,5,6]}]}],
              "overrides":{},"rates":{"HÀO":7},"manual":{}},"orders":[]}
    raw = json.dumps(backup,ensure_ascii=False).encode("utf-8")
    preview = upload(client,"/api/legacy/preview",raw,headers)
    result = upload(client,"/api/legacy/commit",raw,headers,sha256=preview.json["sha256"],replaceSchedule="true")
    assert result.status_code == 200, result.json
    schedule = client.get("/api/state").json["schedule"]
    assert len(schedule["periods"]) == 1
    assert schedule["periods"][0]["shifts"][0]["endDay"] == 1
