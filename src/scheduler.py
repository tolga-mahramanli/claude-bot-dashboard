"""
scheduler.py - APScheduler BackgroundScheduler (Web UI uyumlu)
BlockingScheduler yerine BackgroundScheduler kullanır;
FastAPI uvicorn ile aynı process içinde çalışır.

Scheduler'daki job kimlikleri:
  <job_id>          → config'deki cron görevi
  once:<id>         → tek seferlik planlanmış çalışma (history.one_offs)
  retry:<job_id>    → hata sonrası tekrar denemesi
"""

import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED, EVENT_JOB_MISSED

from src import history, prompt_vars
from src.bot import ClaudeBot
from src.config_store import load_config, section, update_config
from src.logger import setup_logger
from src.state import bot_state

__all__ = ["load_config"]  # web katmanı config'i buradan okuyor

logger = setup_logger("scheduler")

ONCE_PREFIX = "once:"
RETRY_PREFIX = "retry:"
MISFIRE_GRACE = 300  # sn

# Eş zamanlı çalışmayı önlemek için kilit
_task_lock = threading.Lock()

# Singleton scheduler instance
_scheduler: Optional[BackgroundScheduler] = None
_config_path = "config/config.yaml"


# ── Yardımcılar ───────────────────────────────────────────────

def _timezone(config: dict) -> str:
    return config.get("scheduler", {}).get("timezone", "Europe/Istanbul")


def now_in(config: dict) -> datetime:
    """Scheduler saat diliminde şimdiki zaman (aware)."""
    return datetime.now(pytz.timezone(_timezone(config)))


def job_config(config: dict, job_id: str) -> dict:
    for job in config.get("scheduler", {}).get("jobs", []) or []:
        if job.get("id") == job_id:
            return job
    return {}


def init_history(config: dict) -> None:
    history.init(config.get("history", {}).get("db_path", history.DEFAULT_DB_PATH))


def _is_paused(config: dict) -> bool:
    return bool(config.get("scheduler", {}).get("paused", False))


# ── Görev çalıştırma ──────────────────────────────────────────

def run_bot_job(
    config_path: str = "config/config.yaml",
    job_id: str = "default",
    chat_id: str = "",
    prompt: str = "",
    trigger: str = "scheduled",
    attempt: int = 1,
    one_off_id: Optional[int] = None,
) -> str:
    """
    Bir bot görevini çalıştırır ve sonucunu geçmişe yazar.
    chat_id/prompt verilmezse config'deki görevden, o da boşsa global ayardan alınır.
    Dönüş: success | error | session | skipped
    """
    config = load_config(config_path)
    started = now_in(config)

    if trigger == "scheduled" and history.consume_skip(job_id, started):
        logger.info(f"⏭️  [{job_id}] Bu çalışma isteğe bağlı olarak atlandı")
        history.record_skipped(job_id, trigger, started, "Kullanıcı tarafından atlandı")
        return "skipped"

    if not _task_lock.acquire(blocking=False):
        logger.warning(f"⚠️  [{job_id}] Önceki görev hâlâ çalışıyor, bu tur atlandı.")
        run_id = history.record_skipped(job_id, trigger, started, "Önceki görev hâlâ çalışıyordu")
        if one_off_id:
            history.set_one_off_status(one_off_id, "done", run_id)
        return "skipped"

    job = job_config(config, job_id)
    run_id = None
    status, result = "error", {}
    try:
        bot_state.begin_run_capture()

        chat_id = chat_id or job.get("chat_id", "")
        raw_prompt = prompt or job.get("prompt", "") or config.get("claude", {}).get("prompt", "") or "Merhaba!"
        rendered = prompt_vars.render(raw_prompt, now=started)

        label = f" (deneme {attempt})" if attempt > 1 else ""
        logger.info(f"▶️  Görev tetiklendi: {job_id} [{trigger}]{label}")
        logger.info(f"   chat_id : {chat_id[:8] + '...' if len(chat_id) > 8 else chat_id or '(global config)'}")
        logger.info(f"   prompt  : {rendered[:60] + '...' if len(rendered) > 60 else rendered}")

        run_id = history.start_run(job_id, trigger, started, attempt, chat_id, rendered)
        if one_off_id:
            history.set_one_off_status(one_off_id, "done", run_id)

        bot = ClaudeBot(config)
        success = bot.run_task(chat_id=chat_id or None, prompt=rendered)
        result = bot.result or {}
        status = result.get("status") or ("success" if success else "error")

        if status == "success":
            logger.info(f"✅ [{job_id}] Görev başarıyla tamamlandı")
        else:
            logger.error(f"❌ [{job_id}] Görev başarısız oldu")

    except Exception as exc:
        logger.error(f"❌ [{job_id}] Beklenmedik hata: {exc}", exc_info=True)
        result = {"error": str(exc)}
        status = "error"
    finally:
        logs = bot_state.end_run_capture()
        if run_id is not None:
            shot = result.get("screenshot")
            history.finish_run(
                run_id, status, now_in(config),
                error=result.get("error"),
                screenshot=Path(shot).name if shot else None,
                response=result.get("response"),
                logs=logs,
            )
        _task_lock.release()
        _update_next_run()

    if status == "error" and trigger not in ("manual", "cli") and job:
        _schedule_retry(config, job, attempt, config_path)
    return status


def _schedule_retry(config: dict, job: dict, attempt: int, config_path: str) -> None:
    """Görevin tekrar deneme politikasına göre bir sonraki denemeyi planlar."""
    retries = int(job.get("retries", 0) or 0)
    if attempt > retries or _scheduler is None:
        return
    if _is_paused(config):
        logger.info(f"⏸️  [{job['id']}] Zamanlayıcı duraklatıldığı için tekrar denenmeyecek")
        return
    delay = max(1, int(job.get("retry_delay", 5) or 5))
    run_at = now_in(config) + timedelta(minutes=delay)
    _scheduler.add_job(
        func=run_bot_job,
        trigger=DateTrigger(run_date=run_at),
        kwargs={"config_path": config_path, "job_id": job["id"], "trigger": "retry", "attempt": attempt + 1},
        id=f"{RETRY_PREFIX}{job['id']}",
        name=f"{job['id']} (tekrar {attempt + 1}/{retries + 1})",
        misfire_grace_time=MISFIRE_GRACE,
        replace_existing=True,
    )
    logger.info(f"🔁 [{job['id']}] {delay} dk sonra tekrar denenecek ({attempt + 1}/{retries + 1})")


def _update_next_run() -> None:
    """Scheduler'dan sonraki çalışma zamanını al ve state'e yaz."""
    if _scheduler is None:
        return
    try:
        next_times = [j.next_run_time for j in _scheduler.get_jobs() if j.next_run_time]
        bot_state.update_next_run(min(next_times).replace(tzinfo=None) if next_times else None)
    except Exception:
        pass


def _on_job_executed(event) -> None:
    logger.info(f"📌 Job tamamlandı: {event.job_id}")
    _update_next_run()


def _on_job_error(event) -> None:
    logger.error(f"💥 Job hatası: {event.job_id} — {event.exception}")


def _on_job_missed(event) -> None:
    logger.warning(f"⏰ Job kaçırıldı: {event.job_id}")
    if event.job_id.startswith(ONCE_PREFIX):
        history.set_one_off_status(int(event.job_id[len(ONCE_PREFIX):]), "missed")


# ── Kurulum / yeniden yükleme ─────────────────────────────────

def create_scheduler(config_path: str = "config/config.yaml") -> BackgroundScheduler:
    """
    BackgroundScheduler oluşturur ve görevleri ekler.
    FastAPI lifespan'ında çağrılır.
    """
    global _scheduler, _config_path
    _config_path = config_path
    config = load_config(config_path)
    init_history(config)

    scheduler = BackgroundScheduler(timezone=_timezone(config))
    scheduler.add_listener(_on_job_executed, EVENT_JOB_EXECUTED)
    scheduler.add_listener(_on_job_error, EVENT_JOB_ERROR)
    scheduler.add_listener(_on_job_missed, EVENT_JOB_MISSED)

    _scheduler = scheduler
    _register_all(scheduler, config, config_path)
    return scheduler


_DOW_NAMES = ["sun", "mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def _crontab_dow(expr: str) -> str:
    """
    Standart crontab haftanın-günü alanını (0/7=Pazar, 1=Pazartesi) APScheduler'a çevirir.
    APScheduler'da 0=Pazartesi olduğundan "1-5" çevrilmeden verilirse Salı–Cumartesi çalışır.
    Sayısal olmayan parçalar ("*", "mon-fri", "*/2") olduğu gibi bırakılır.
    """
    parts = []
    for token in expr.split(","):
        if token.isdigit() and int(token) <= 7:
            parts.append(_DOW_NAMES[int(token)])
        elif "-" in token and all(p.isdigit() and int(p) <= 7 for p in token.split("-", 1)):
            start, end = (int(p) for p in token.split("-", 1))
            parts.extend(_DOW_NAMES[d] for d in range(start, end + 1))
        else:
            parts.append(token)
    return ",".join(dict.fromkeys(parts))


def _register_all(scheduler: BackgroundScheduler, config: dict, config_path: str) -> None:
    """Cron görevlerini ve bekleyen tek seferlik çalışmaları ekler; duraklatma durumunu uygular."""
    paused = _is_paused(config)
    timezone = _timezone(config)
    _register_jobs(scheduler, config.get("scheduler", {}).get("jobs", []) or [], timezone, config_path, paused)
    _register_one_offs(scheduler, config, config_path, paused)

    for job in scheduler.get_jobs():
        if not job.id.startswith(RETRY_PREFIX):
            continue
        if paused:
            job.pause()
        else:
            job.resume()
    if paused:
        logger.info("⏸️  Zamanlayıcı duraklatılmış durumda — görevler çalışmayacak")


def _register_jobs(scheduler: BackgroundScheduler, jobs_cfg: list, timezone: str,
                   config_path: str, paused: bool = False) -> None:
    """Config'deki tüm aktif görevleri scheduler'a ekler."""
    for job in jobs_cfg:
        if not job.get("enabled", True):
            logger.info(f"⏸️  Devre dışı job: {job.get('id', '?')}")
            continue

        job_id   = job.get("id", "job_default")
        cron_expr = job.get("cron", "0 9 * * *")
        # Job'a özgü değerler
        job_chat_id = job.get("chat_id", "")
        job_prompt  = job.get("prompt",  "")

        try:
            minute, hour, day, month, day_of_week = cron_expr.split()
        except ValueError:
            logger.error(f"Geçersiz cron ({job_id}): {cron_expr}")
            continue

        extra = {"next_run_time": None} if paused else {}
        scheduler.add_job(
            func=run_bot_job,
            trigger=CronTrigger(
                minute=minute, hour=hour, day=day,
                month=month, day_of_week=_crontab_dow(day_of_week),
                timezone=timezone,
            ),
            kwargs={
                "config_path": config_path,
                "job_id":      job_id,
                "chat_id":     job_chat_id,
                "prompt":      job_prompt,
            },
            id=job_id,
            name=job_id,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=MISFIRE_GRACE,
            replace_existing=True,
            **extra,
        )
        logger.info(f"⏰ Job eklendi → {job_id} | cron: {cron_expr} | chat: {job_chat_id[:8] + '...' if job_chat_id else 'global'}")


def _add_one_off_job(scheduler: BackgroundScheduler, row: dict, config_path: str, paused: bool) -> None:
    extra = {"next_run_time": None} if paused else {}
    scheduler.add_job(
        func=run_bot_job,
        trigger=DateTrigger(run_date=datetime.fromisoformat(row["run_at"])),
        kwargs={"config_path": config_path, "job_id": row["job_id"], "trigger": "once", "one_off_id": row["id"]},
        id=f"{ONCE_PREFIX}{row['id']}",
        name=f"{row['job_id']} (tek seferlik)",
        misfire_grace_time=MISFIRE_GRACE,
        replace_existing=True,
        **extra,
    )


def _register_one_offs(scheduler: BackgroundScheduler, config: dict, config_path: str, paused: bool) -> None:
    now = now_in(config)
    for row in history.list_one_offs("pending"):
        run_at = datetime.fromisoformat(row["run_at"])
        if run_at < now - timedelta(seconds=MISFIRE_GRACE):
            history.set_one_off_status(row["id"], "missed")
            logger.warning(f"⏰ Tek seferlik çalışma kaçırıldı: {row['job_id']} @ {row['run_at']}")
            continue
        _add_one_off_job(scheduler, row, config_path, paused)


def reload_scheduler(config_path: str = "config/config.yaml") -> None:
    """
    Config güncellendikten sonra scheduler'ı yeniden yükler.
    Bekleyen tekrar denemeleri korunur; cron ve tek seferlik görevler yeniden eklenir.
    """
    if _scheduler is None:
        return

    config = load_config(config_path)
    for job in _scheduler.get_jobs():
        if not job.id.startswith(RETRY_PREFIX):
            job.remove()
    logger.info("🔄 Görevler temizlendi, yeniden yükleniyor...")

    _register_all(_scheduler, config, config_path)
    _update_next_run()
    logger.info("✅ Scheduler yeniden yüklendi")


# ── Web UI işlemleri ──────────────────────────────────────────

def set_paused(paused: bool, config_path: str = "config/config.yaml") -> None:
    """Tüm zamanlanmış çalışmaları duraklatır / sürdürür (config'e kalıcı yazılır)."""
    update_config(config_path, lambda doc: section(doc, "scheduler").__setitem__("paused", bool(paused)))
    logger.info("⏸️  Zamanlayıcı duraklatıldı" if paused else "▶️  Zamanlayıcı sürdürüldü")
    reload_scheduler(config_path)


def skip_next(job_id: str) -> datetime:
    """Görevin sıradaki zamanlanmış çalışmasını atlanacak olarak işaretler."""
    job = _scheduler.get_job(job_id) if _scheduler else None
    if not job or not job.next_run_time:
        raise ValueError("Bu görevin planlanmış bir sonraki çalışması yok")
    history.set_skip(job_id, job.next_run_time)
    logger.info(f"⏭️  [{job_id}] {job.next_run_time:%d.%m %H:%M} çalışması atlanacak")
    return job.next_run_time


def unskip(job_id: str) -> None:
    history.clear_skip(job_id)
    logger.info(f"↩️  [{job_id}] Atlama geri alındı")


def schedule_one_off(job_id: str, run_at: datetime, config_path: str = "config/config.yaml") -> int:
    """Görevi belirtilen zamanda bir kez çalıştırmak üzere planlar."""
    config = load_config(config_path)
    if not job_config(config, job_id):
        raise ValueError(f"'{job_id}' adında bir görev yok")
    now = now_in(config)
    if run_at.tzinfo is None:
        run_at = pytz.timezone(_timezone(config)).localize(run_at)
    if run_at <= now:
        raise ValueError("Planlanan zaman gelecekte olmalı")

    one_off_id = history.add_one_off(job_id, run_at, now)
    if _scheduler is not None:
        _add_one_off_job(_scheduler, history.get_one_off(one_off_id), config_path, _is_paused(config))
    logger.info(f"📅 [{job_id}] Tek seferlik çalışma planlandı: {run_at:%d.%m.%Y %H:%M}")
    return one_off_id


def cancel_one_off(one_off_id: int) -> None:
    history.set_one_off_status(one_off_id, "cancelled")
    if _scheduler is not None and _scheduler.get_job(f"{ONCE_PREFIX}{one_off_id}"):
        _scheduler.remove_job(f"{ONCE_PREFIX}{one_off_id}")
    logger.info(f"🗑️  Tek seferlik çalışma iptal edildi (#{one_off_id})")


def get_scheduler_status() -> dict:
    """Scheduler'daki tüm job'ların durumunu döndürür (API için)."""
    if _scheduler is None:
        return {"running": False, "jobs": []}

    jobs = []
    for job in _scheduler.get_jobs():
        kw = job.kwargs or {}
        prompt_preview = kw.get("prompt", "")
        jobs.append({
            "id":      job.id,
            "name":    job.name,
            "next_run": job.next_run_time.isoformat() if job.next_run_time else None,
            "chat_id": kw.get("chat_id", ""),
            "prompt_preview": prompt_preview[:40] + "..." if len(prompt_preview) > 40 else prompt_preview,
        })
    return {"running": _scheduler.running, "jobs": jobs}


def jobs_overview(config_path: str = "config/config.yaml") -> dict:
    """
    Config'deki görevleri scheduler, atlama ve geçmiş bilgileriyle birleştirir.
    Dashboard'un görev listesi, zaman çizelgesi ve geri sayımı bunu kullanır.
    """
    config = load_config(config_path)
    now = now_in(config)
    skips = history.get_skips(now)
    stats = history.job_stats()
    sched = {j.id: j for j in _scheduler.get_jobs()} if _scheduler else {}

    jobs = []
    for j in config.get("scheduler", {}).get("jobs", []) or []:
        jid = str(j.get("id", ""))
        aps = sched.get(jid)
        next_run = aps.next_run_time if aps else None
        skipped_run = None
        skip_at = skips.get(jid)
        if next_run and skip_at and abs((next_run - skip_at).total_seconds()) < 60:
            skipped_run = next_run
            next_run = aps.trigger.get_next_fire_time(next_run, next_run + timedelta(seconds=1))
        prompt = j.get("prompt", "") or ""
        jobs.append({
            "id":             jid,
            "enabled":        j.get("enabled", True),
            "cron":           j.get("cron", ""),
            "chat_id":        j.get("chat_id", ""),
            "prompt_preview": prompt[:50] + "..." if len(prompt) > 50 else prompt,
            "retries":        int(j.get("retries", 0) or 0),
            "next_run":       next_run.isoformat() if next_run else None,
            "skipped_run":    skipped_run.isoformat() if skipped_run else None,
            "stats":          stats.get(jid, {"total": 0, "success": 0}),
        })

    upcoming = []
    for aps in sched.values():
        if aps.id.startswith(ONCE_PREFIX) or aps.id.startswith(RETRY_PREFIX):
            upcoming.append({
                "kind":     "once" if aps.id.startswith(ONCE_PREFIX) else "retry",
                "id":       int(aps.id[len(ONCE_PREFIX):]) if aps.id.startswith(ONCE_PREFIX) else None,
                "job_id":   aps.kwargs.get("job_id"),
                "label":    aps.name,
                "run_at":   (aps.next_run_time or aps.trigger.run_date).isoformat(),
                "paused":   aps.next_run_time is None,
            })
    upcoming.sort(key=lambda u: u["run_at"])

    return {
        "running":  bool(_scheduler and _scheduler.running),
        "paused":   _is_paused(config),
        "timezone": _timezone(config),
        "jobs":     jobs,
        "upcoming": upcoming,
    }
