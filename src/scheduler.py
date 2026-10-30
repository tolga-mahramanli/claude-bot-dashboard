"""
scheduler.py - APScheduler BackgroundScheduler (Web UI uyumlu)
BlockingScheduler yerine BackgroundScheduler kullanır;
FastAPI uvicorn ile aynı process içinde çalışır.
"""

import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

import yaml
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED, EVENT_JOB_MISSED

from src.bot import ClaudeBot
from src.logger import setup_logger
from src.state import bot_state

logger = setup_logger("scheduler")

# Eş zamanlı çalışmayı önlemek için kilit
_task_lock = threading.Lock()

# Singleton scheduler instance
_scheduler: Optional[BackgroundScheduler] = None


def load_config(config_path: str = "config/config.yaml") -> dict:
    """YAML konfigürasyon dosyasını yükler."""
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Config dosyası bulunamadı: {config_path}")
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def run_bot_job(
    config_path: str = "config/config.yaml",
    job_id: str = "default",
    chat_id: str = "",
    prompt: str = "",
) -> None:
    """APScheduler tarafından çağrılan görev fonksiyonu."""
    if not _task_lock.acquire(blocking=False):
        logger.warning(f"⚠️  [{job_id}] Önceki görev hâlâ çalışıyor, bu tur atlandı.")
        return

    try:
        logger.info(f"▶️  Görev tetiklendi: {job_id}")
        logger.info(f"   chat_id : {chat_id[:8] + '...' if len(chat_id) > 8 else chat_id or '(global config)'}")
        logger.info(f"   prompt  : {prompt[:60] + '...' if len(prompt) > 60 else prompt or '(global config)'}")

        config = load_config(config_path)
        bot = ClaudeBot(config)
        # None geçirilirse bot kendi global config'inden alır
        success = bot.run_task(
            chat_id=chat_id or None,
            prompt=prompt   or None,
        )

        if success:
            logger.info(f"✅ [{job_id}] Görev başarıyla tamamlandı")
        else:
            logger.error(f"❌ [{job_id}] Görev başarısız oldu")

    except Exception as exc:
        logger.error(f"❌ [{job_id}] Beklenmedik hata: {exc}", exc_info=True)
    finally:
        _task_lock.release()
        _update_next_run()


def _update_next_run() -> None:
    """Scheduler'dan sonraki çalışma zamanını al ve state'e yaz."""
    global _scheduler
    if _scheduler is None:
        return
    try:
        jobs = _scheduler.get_jobs()
        next_times = [j.next_run_time for j in jobs if j.next_run_time]
        if next_times:
            bot_state.update_next_run(min(next_times).replace(tzinfo=None))
    except Exception:
        pass


def _on_job_executed(event) -> None:
    logger.info(f"📌 Job tamamlandı: {event.job_id}")
    _update_next_run()


def _on_job_error(event) -> None:
    logger.error(f"💥 Job hatası: {event.job_id} — {event.exception}")


def _on_job_missed(event) -> None:
    logger.warning(f"⏰ Job kaçırıldı: {event.job_id}")


def create_scheduler(config_path: str = "config/config.yaml") -> BackgroundScheduler:
    """
    BackgroundScheduler oluşturur ve görevleri ekler.
    FastAPI lifespan'ında çağrılır.
    """
    global _scheduler
    config = load_config(config_path)
    sched_cfg = config.get("scheduler", {})
    timezone = sched_cfg.get("timezone", "Europe/Istanbul")
    jobs_cfg = sched_cfg.get("jobs", [])

    scheduler = BackgroundScheduler(timezone=timezone)
    scheduler.add_listener(_on_job_executed, EVENT_JOB_EXECUTED)
    scheduler.add_listener(_on_job_error, EVENT_JOB_ERROR)
    scheduler.add_listener(_on_job_missed, EVENT_JOB_MISSED)

    _register_jobs(scheduler, jobs_cfg, timezone, config_path)

    _scheduler = scheduler
    return scheduler


def _register_jobs(scheduler: BackgroundScheduler, jobs_cfg: list, timezone: str, config_path: str) -> None:
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

        scheduler.add_job(
            func=run_bot_job,
            trigger=CronTrigger(
                minute=minute, hour=hour, day=day,
                month=month, day_of_week=day_of_week,
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
            misfire_grace_time=300,
            replace_existing=True,
        )
        logger.info(f"⏰ Job eklendi → {job_id} | cron: {cron_expr} | chat: {job_chat_id[:8] + '...' if job_chat_id else 'global'}")


def reload_scheduler(config_path: str = "config/config.yaml") -> None:
    """
    Config güncellendikten sonra scheduler'ı yeniden yükler.
    Web UI'dan config değiştiğinde çağrılır.
    """
    global _scheduler
    if _scheduler is None:
        return

    config = load_config(config_path)
    sched_cfg = config.get("scheduler", {})
    timezone = sched_cfg.get("timezone", "Europe/Istanbul")
    jobs_cfg = sched_cfg.get("jobs", [])

    # Mevcut tüm job'ları temizle
    _scheduler.remove_all_jobs()
    logger.info("🔄 Tüm job'lar temizlendi, yeniden yükleniyor...")

    _register_jobs(_scheduler, jobs_cfg, timezone, config_path)
    _update_next_run()
    logger.info("✅ Scheduler yeniden yüklendi")


def get_scheduler_status() -> dict:
    """Tüm job'ların durumunu döndürür (API için)."""
    global _scheduler
    if _scheduler is None:
        return {"running": False, "jobs": []}

    jobs = []
    for job in _scheduler.get_jobs():
        # kwargs içinden chat_id ve prompt önizlemesini al
        kw = job.kwargs or {}
        chat_id_preview = kw.get("chat_id", "")
        prompt_preview  = kw.get("prompt",  "")
        jobs.append({
            "id":      job.id,
            "name":    job.name,
            "next_run": job.next_run_time.isoformat() if job.next_run_time else None,
            "chat_id": chat_id_preview,
            "prompt_preview": prompt_preview[:40] + "..." if len(prompt_preview) > 40 else prompt_preview,
        })

    return {
        "running": _scheduler.running,
        "jobs": jobs,
    }
