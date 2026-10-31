"""API uç noktaları — gerçek scheduler/tarayıcı başlatılmadan (lifespan çalışmaz)."""
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(config_file, history_db, monkeypatch):
    from web.routes import api
    monkeypatch.setattr(api, "CONFIG_PATH", str(config_file))
    from web.app import create_app
    return TestClient(create_app())  # 'with' yok → scheduler başlamaz


def test_status_uses_persistent_history(client, history_db):
    from src.scheduler import now_in, load_config
    from web.routes import api
    t = now_in(load_config(api.CONFIG_PATH))
    rid = history_db.start_run("sabah", "scheduled", t)
    history_db.finish_run(rid, "success", t, response="Selam")
    data = client.get("/api/status").json()
    assert data["stats"]["total"] == 1 and data["stats"]["success"] == 1
    assert data["last_run_record"]["response_preview"] == "Selam"
    assert data["paused"] is False


def test_runs_list_detail_and_heatmap(client, history_db):
    t = datetime.now().astimezone()
    rid = history_db.start_run("sabah", "manual", t, prompt="p")
    history_db.finish_run(rid, "error", t, error="x", logs="line")
    runs = client.get("/api/runs?job_id=sabah").json()
    assert runs["runs"][0]["id"] == rid and runs["counts"]["error"] == 1 and runs["more"] is False
    detail = client.get(f"/api/runs/{rid}").json()
    assert detail["logs"] == "line" and detail["job_exists"] is True and detail["screenshot_url"] is None
    assert client.get("/api/runs/999").status_code == 404
    assert len(client.get("/api/runs/heatmap?days=30").json()["days"]) == 30


def test_config_roundtrip_preserves_comments(client, config_file):
    cfg = client.get("/api/config").json()
    jobs = cfg["jobs"]
    jobs[0]["retries"] = 3
    payload = {"jobs": jobs, "timezone": cfg["timezone"], "headless": cfg["headless"]}
    assert client.post("/api/config", json=payload).status_code == 200
    assert "# hafta içi" in config_file.read_text(encoding="utf-8")
    assert client.get("/api/config").json()["jobs"][0]["retries"] == 3

    payload["jobs"].append(dict(jobs[0]))
    assert client.post("/api/config", json=payload).status_code == 400  # yinelenen ad


def test_prompt_preview(client):
    data = client.post("/api/prompt/preview", json={"prompt": "Bugün {gün}, {x|x}"}).json()
    assert "{gün}" not in data["rendered"] and data["rendered"].endswith(", x")
    assert any(v["name"] == "tarih" for v in data["variables"])


def test_one_off_validation(client):
    future = (datetime.now() + timedelta(hours=2)).isoformat(timespec="minutes")
    assert client.post("/api/one-offs", json={"job_id": "yok", "run_at": future}).status_code == 400
    past = (datetime.now() - timedelta(hours=2)).isoformat(timespec="minutes")
    assert client.post("/api/one-offs", json={"job_id": "sabah", "run_at": past}).status_code == 400
    created = client.post("/api/one-offs", json={"job_id": "sabah", "run_at": future}).json()
    assert client.delete(f"/api/one-offs/{created['id']}").status_code == 200


def test_jobs_overview_shape(client):
    data = client.get("/api/jobs").json()
    assert [j["id"] for j in data["jobs"]] == ["sabah", "aksam"]
    assert data["jobs"][0]["stats"] == {"total": 0, "success": 0}
    assert data["upcoming"] == [] and data["paused"] is False
