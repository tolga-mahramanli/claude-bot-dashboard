from datetime import datetime, timedelta

import pytz

TZ = pytz.timezone("Europe/Istanbul")
T0 = TZ.localize(datetime(2026, 10, 30, 9, 0))


def test_run_lifecycle_and_totals(history_db):
    rid = history_db.start_run("sabah", "scheduled", T0, prompt="Merhaba")
    history_db.finish_run(rid, "success", T0 + timedelta(seconds=42), response="Selam!\n\nNasılsın?",
                          screenshot="success_1.png", logs="a\nb")
    bad = history_db.start_run("sabah", "manual", T0 + timedelta(hours=1))
    history_db.finish_run(bad, "error", T0 + timedelta(hours=1, seconds=5), error="boom")
    history_db.record_skipped("aksam", "scheduled", T0, "atlandı")

    run = history_db.get_run(rid)
    assert run["duration"] == 42.0 and run["response"].startswith("Selam") and run["logs"] == "a\nb"

    listed = history_db.list_runs()
    assert [r["id"] for r in listed][:2] == [3, bad]
    assert "logs" not in listed[0] and listed[-1]["response_preview"] == "Selam! Nasılsın?"

    assert history_db.totals() == {"success": 1, "error": 1, "session": 0, "skipped": 1, "total": 2}
    assert history_db.list_runs(status="error")[0]["error"] == "boom"
    assert history_db.list_runs(before_id=bad)[0]["id"] == rid

    stats = history_db.job_stats()
    assert stats["sabah"]["total"] == 2 and stats["sabah"]["success"] == 1
    assert stats["sabah"]["last"]["status"] == "error"


def test_heatmap_counts_by_local_day(history_db):
    for i, status in enumerate(["success", "success", "error"]):
        rid = history_db.start_run("sabah", "scheduled", T0 - timedelta(days=i % 2))
        history_db.finish_run(rid, status, T0)
    days = history_db.heatmap(T0, days=7)
    assert len(days) == 7 and days[-1]["date"] == "2026-10-30"
    assert days[-1] == {"date": "2026-10-30", "success": 1, "error": 1}
    assert days[-2] == {"date": "2026-10-29", "success": 1, "error": 0}


def test_interrupted_runs_are_closed_on_init(tmp_path):
    from src import history
    history.init(str(tmp_path / "h.db"))
    rid = history.start_run("sabah", "scheduled", T0)
    history.init(str(tmp_path / "h.db"))
    assert history.get_run(rid)["status"] == "error"
    history._db_path = None


def test_skip_is_consumed_only_near_its_time(history_db):
    history_db.set_skip("sabah", T0)
    assert not history_db.consume_skip("sabah", T0 - timedelta(hours=1))
    assert history_db.consume_skip("sabah", T0 + timedelta(seconds=30))
    assert not history_db.consume_skip("sabah", T0)

    history_db.set_skip("aksam", T0)
    assert history_db.get_skips(T0 + timedelta(hours=2)) == {}


def test_one_offs(history_db):
    oid = history_db.add_one_off("sabah", T0 + timedelta(days=1), T0)
    assert [o["id"] for o in history_db.list_one_offs()] == [oid]
    history_db.set_one_off_status(oid, "cancelled")
    assert history_db.list_one_offs() == []
    assert history_db.get_one_off(oid)["status"] == "cancelled"
