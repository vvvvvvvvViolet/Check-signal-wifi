"""End-to-end checks over the HTTP surface, against the simulated backend."""

from __future__ import annotations

import io
import time

import pytest
from PIL import Image


def make_plan_image(width: int = 800, height: int = 400) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (240, 240, 240)).save(buffer, format="PNG")
    return buffer.getvalue()


def test_health(client):
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["wifi_backend"] == "mock"
    assert body["simulated"] is True


def test_dashboard_answers_the_core_question(client):
    body = client.get("/api/dashboard").json()
    assert body["link"]["ssid"] == "Factory-WiFi"
    assert body["summary"]["grade"] in {"EXCELLENT", "GOOD", "FAIR", "POOR"}
    assert body["summary"]["verdict"] in {"PASS", "WARNING", "FAIL"}
    assert "status_text" in body
    assert set(body["bands"]) == {"excellent", "good", "fair"}


def test_scan_lists_and_groups_networks(client):
    body = client.get("/api/scan").json()
    assert body["count"] >= 4
    rssis = [n["rssi"] for n in body["networks"]]
    assert rssis == sorted(rssis, reverse=True), "strongest first"
    assert any(g["ssid"] == "Factory-WiFi" for g in body["ssid_groups"])
    assert body["channel_usage"]


def test_scan_filters(client):
    filtered = client.get("/api/scan", params={"ssid": "office"}).json()
    assert filtered["count"] >= 1
    assert all("office" in (n["ssid"] or "").lower() for n in filtered["networks"])

    strong = client.get("/api/scan", params={"min_rssi": -65}).json()
    assert all(n["rssi"] >= -65 for n in strong["networks"])


def test_network_test_chain_has_every_rung(client):
    body = client.get("/api/nettest/chain").json()
    assert [s["key"] for s in body["steps"]] == ["wifi", "gateway", "lan", "dns", "internet"]
    for step in body["steps"]:
        assert step["state"] in {"ok", "failed", "blocked"}


def test_diagnosis_endpoint(client):
    body = client.get("/api/diagnosis", params={"include_scan": True}).json()
    assert body["severity"] in {"info", "warning", "critical"}
    assert body["findings"]
    assert body["headline"]


def test_manual_diagnosis_matches_the_spec_example(client):
    body = client.post(
        "/api/diagnosis",
        json={"rssi": -52, "ping_ms": 250, "packet_loss_pct": 15},
    ).json()
    codes = {f["code"] for f in body["findings"]}
    assert "UPSTREAM_DEGRADED" in codes
    assert "WEAK_COVERAGE" not in codes


def test_settings_round_trip(client):
    original = client.get("/api/settings").json()["settings"]

    updated = {**original, "site_name": "Plant 2"}
    updated["thresholds"] = {**original["thresholds"], "ping_warning_ms": 35.0}
    assert client.put("/api/settings", json=updated).status_code == 200

    reloaded = client.get("/api/settings").json()
    assert reloaded["settings"]["site_name"] == "Plant 2"
    assert reloaded["settings"]["thresholds"]["ping_warning_ms"] == 35.0
    assert reloaded["stored"] is True

    client.post("/api/settings/reset")
    assert client.get("/api/settings").json()["settings"]["site_name"] == "Default Site"


def test_settings_reject_impossible_values(client):
    bad = client.get("/api/settings").json()["settings"]
    bad["thresholds"] = {**bad["thresholds"], "loss_warning_pct": 150.0}
    assert client.put("/api/settings", json=bad).status_code == 422


def test_history_create_filter_and_export(client):
    created = client.post(
        "/api/history",
        json={"area": "Line-A", "device": "Scanner-01", "measure": True},
    )
    assert created.status_code == 201
    record = created.json()
    assert record["area"] == "Line-A"
    assert record["result"] in {"PASS", "WARNING", "FAIL"}
    assert record["rssi"] is not None

    listing = client.get("/api/history", params={"area": "Line-A"}).json()
    assert listing["total"] >= 1
    assert all(item["area"] == "Line-A" for item in listing["items"])

    assert client.get("/api/history", params={"area": "Nowhere"}).json()["total"] == 0

    facets = client.get("/api/history/facets").json()
    assert "Line-A" in facets["areas"]
    assert "Scanner-01" in facets["devices"]

    stats = client.get("/api/history/stats").json()
    assert stats["total"] >= 1

    detail = client.get(f"/api/history/{record['id']}").json()
    assert detail["id"] == record["id"]
    assert client.get("/api/history/999999").status_code == 404


def test_history_accepts_supplied_measurements(client):
    body = client.post(
        "/api/history",
        json={
            "area": "Warehouse-1",
            "measure": False,
            "rssi": -78,
            "ping_ms": 25.0,
            "packet_loss_pct": 8.0,
        },
    ).json()
    assert body["rssi"] == -78
    assert body["result"] == "FAIL"
    assert body["grade"] == "POOR"


@pytest.mark.parametrize("fmt", ["csv", "xlsx", "pdf"])
def test_history_export_formats(client, fmt):
    response = client.get("/api/report/history", params={"format": fmt})
    assert response.status_code == 200
    assert response.content
    assert "attachment" in response.headers["content-disposition"]
    if fmt == "pdf":
        assert response.content.startswith(b"%PDF")
    if fmt == "xlsx":
        assert response.content.startswith(b"PK")
    if fmt == "csv":
        assert response.content.startswith(b"\xef\xbb\xbf")  # BOM so Excel reads UTF-8


def test_export_rejects_an_unknown_format(client):
    assert client.get("/api/report/history", params={"format": "docx"}).status_code == 422


def test_floor_plan_survey_and_heatmap(client):
    upload = client.post(
        "/api/heatmap/plans",
        files={"file": ("plan.png", make_plan_image(), "image/png")},
        data={"name": "Production-A", "location": "Building 1"},
    )
    assert upload.status_code == 201
    plan = upload.json()
    assert plan["width_px"] == 800
    assert plan["height_px"] == 400

    assert client.get(f"/api/heatmap/plans/{plan['id']}/image").status_code == 200

    empty = client.get(f"/api/heatmap/plans/{plan['id']}/grid").json()
    assert empty["grid"] is None
    assert "No measurements" in empty["message"]

    for x, y in ((100, 100), (400, 200), (700, 300), (250, 320)):
        created = client.post(
            f"/api/heatmap/plans/{plan['id']}/points",
            json={"x": x, "y": y, "label": f"P{x}", "measure": True},
        )
        assert created.status_code == 201
        assert created.json()["rssi"] is not None

    outside = client.post(
        f"/api/heatmap/plans/{plan['id']}/points", json={"x": 5000, "y": 10, "measure": False}
    )
    assert outside.status_code == 400

    ap = client.post(
        f"/api/heatmap/plans/{plan['id']}/aps",
        json={"name": "AP-01", "bssid": "AA:BB:CC:DD:EE:01", "x": 150, "y": 150},
    )
    assert ap.status_code == 201

    grid = client.get(f"/api/heatmap/plans/{plan['id']}/grid").json()
    assert grid["grid"] is not None
    assert grid["grid"]["cols"] > 0
    assert len(grid["grid"]["matrix"]) == grid["grid"]["rows"]
    assert len(grid["grid"]["grades"]) == grid["grid"]["rows"]
    assert grid["summary"]["total_points"] == 4
    assert len(grid["access_points"]) == 1

    export = client.get(f"/api/report/heatmap/{plan['id']}", params={"format": "xlsx"})
    assert export.status_code == 200

    assert client.delete(f"/api/heatmap/plans/{plan['id']}").status_code == 204
    assert client.get(f"/api/heatmap/plans/{plan['id']}").status_code == 404


def test_floor_plan_rejects_a_non_image(client):
    response = client.post(
        "/api/heatmap/plans",
        files={"file": ("evil.png", b"not actually a png", "image/png")},
        data={"name": "Bad"},
    )
    assert response.status_code == 400


def test_monitor_start_collect_stop(client):
    started = client.post(
        "/api/monitor/start",
        json={"name": "Line-A walk", "area": "Line-A", "interval_sec": 0.5},
    )
    assert started.status_code == 200
    session_id = started.json()["session_id"]

    # Starting twice must not spawn a second reader of the same radio.
    assert client.post("/api/monitor/start", json={"name": "dupe"}).status_code == 409

    deadline = time.time() + 8
    while time.time() < deadline:
        if client.get("/api/monitor/live").json()["buffered_samples"] >= 2:
            break
        time.sleep(0.25)

    live = client.get("/api/monitor/live").json()
    assert live["running"] is True
    assert live["buffered_samples"] >= 1

    stopped = client.post("/api/monitor/stop")
    assert stopped.status_code == 200
    assert stopped.json()["running"] is False
    assert client.post("/api/monitor/stop").status_code == 409

    samples = client.get("/api/monitor/samples", params={"session_id": session_id}).json()
    assert samples
    timestamps = [s["ts"] for s in samples]
    assert timestamps == sorted(timestamps), "samples must come back chronologically"

    summary = client.get("/api/monitor/summary", params={"session_id": session_id}).json()
    assert summary["samples"] == len(samples)

    export = client.get(f"/api/report/session/{session_id}", params={"format": "csv"})
    assert export.status_code == 200

    assert client.delete(f"/api/monitor/sessions/{session_id}").status_code == 204


def test_monitor_websocket_backfills_then_streams(client):
    with client.websocket_connect("/api/monitor/ws") as ws:
        hello = ws.receive_json()
        assert hello["type"] == "hello"
        assert "status" in hello
        assert isinstance(hello["backfill"], list)
