"""run_bot_job akışı — tarayıcı yerine sahte bir bot ile."""
from datetime import timedelta

import pytest
from apscheduler.schedulers.background import BackgroundScheduler

from src import scheduler as sched
from src.config_store import section, update_config


class FakeBot:
    outcomes = []
    prompts = []

    def __init__(self, config):
        self.result = {}

    def run_task(self, chat_id=None, prompt=None):
        from src.logger import setup_logger
        setup_logger("bot").info("fake bot çalıştı")
        FakeBot.prompts.append(prompt)
        status = FakeBot.outcomes.pop(0)
        self.result = {"status": status, "error": None if status == "success" else "patladı",
                       "screenshot": "/x/screenshots/success_1.png", "response": "Selam!" if status == "success" else None}
        return status == "success"


@pytest.fixture
def env(config_file, history_db, monkeypatch):
    monkeypatch.setattr(sched, "ClaudeBot", FakeBot)
    aps = BackgroundScheduler(timezone="Europe/Istanbul")
    aps.start(paused=True)  # zamanlar hesaplanır ama hiçbir job tetiklenmez
    monkeypatch.setattr(sched, "_scheduler", aps)
    FakeBot.outcomes, FakeBot.prompts = [], []
    update_config(str(config_file), lambda d: d["scheduler"]["jobs"][0].update(retries=1, retry_delay=3))
    yield str(config_file), aps
    aps.shutdown(wait=False)


def test_success_is_recorded_with_response_and_logs(env, history_db):
    path, _ = env
    FakeBot.outcomes = ["success"]
    assert sched.run_bot_job(config_path=path, job_id="sabah") == "success"
    run = history_db.get_run(history_db.list_runs()[0]["id"])
    assert run["status"] == "success" and run["response"] == "Selam!"
    assert run["screenshot"] == "success_1.png"
    assert "fake bot çalıştı" in run["logs"] and "Görev tetiklendi" in run["logs"]
    assert "{gün}" not in FakeBot.prompts[0] and FakeBot.prompts[0].startswith("Günaydın ")


def test_failure_schedules_a_single_retry(env, history_db):
    path, aps = env
    FakeBot.outcomes = ["error", "error"]
    assert sched.run_bot_job(config_path=path, job_id="sabah") == "error"
    retry = aps.get_job("retry:sabah")
    assert retry is not None and retry.kwargs["attempt"] == 2

    aps.remove_job("retry:sabah")
    sched.run_bot_job(config_path=path, job_id="sabah", trigger="retry", attempt=2)
    assert aps.get_job("retry:sabah") is None  # retries=1 → toplam 2 deneme
    assert [r["attempt"] for r in history_db.list_runs()] == [2, 1]


def test_manual_and_session_failures_do_not_retry(env):
    path, aps = env
    FakeBot.outcomes = ["error", "session"]
    sched.run_bot_job(config_path=path, job_id="sabah", trigger="manual")
    sched.run_bot_job(config_path=path, job_id="sabah")
    assert aps.get_job("retry:sabah") is None


def test_skip_marks_run_as_skipped(env, history_db):
    path, _ = env
    history_db.set_skip("sabah", sched.now_in(sched.load_config(path)) + timedelta(seconds=20))
    assert sched.run_bot_job(config_path=path, job_id="sabah") == "skipped"
    assert FakeBot.prompts == []
    assert history_db.list_runs()[0]["status"] == "skipped"


def test_pause_registers_jobs_without_next_run(env):
    path, aps = env
    sched.set_paused(True, path)
    assert aps.get_job("sabah").next_run_time is None
    sched.set_paused(False, path)
    assert aps.get_job("sabah").next_run_time is not None
    assert aps.get_job("aksam") is None  # pasif görev eklenmez


def test_skip_next_moves_the_displayed_next_run(env):
    path, aps = env
    sched.reload_scheduler(path)
    original = aps.get_job("sabah").next_run_time
    sched.skip_next("sabah")
    job = next(j for j in sched.jobs_overview(path)["jobs"] if j["id"] == "sabah")
    assert job["skipped_run"] == original.isoformat()
    assert job["next_run"] > original.isoformat()
    sched.unskip("sabah")
    job = next(j for j in sched.jobs_overview(path)["jobs"] if j["id"] == "sabah")
    assert job["skipped_run"] is None and job["next_run"] == original.isoformat()


def test_dashboard_log_buffer_has_no_ansi_codes():
    from src.logger import setup_logger
    from src.state import bot_state
    setup_logger("ansi_check").warning("renk kontrolü")
    line = bot_state.get_logs(1)[0]
    assert "\x1b[" not in line and "| WARNING  |" in line
