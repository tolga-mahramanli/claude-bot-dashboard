"""
web/routes/api.py - REST API Endpoint'leri

GET    /api/status               → Bot durumu + tüm zamanların istatistikleri
GET    /api/config               → Mevcut konfigürasyonu oku
POST   /api/config               → Konfigürasyonu güncelle + scheduler reload
GET    /api/logs                 → Son N log satırı
GET    /api/logs/stream          → SSE (Server-Sent Events) canlı log akışı
GET    /api/screenshots/list     → Ekran görüntüleri
POST   /api/run-now              → Anında bir bot görevi tetikle
GET    /api/jobs                 → Görevler + sonraki çalışmalar + atlamalar + bekleyen tek seferlikler
POST   /api/jobs/{id}/skip       → Sıradaki çalışmayı atla   (DELETE → geri al)
POST   /api/scheduler/pause      → Tüm zamanlanmış çalışmaları duraklat / sürdür
POST   /api/one-offs             → Tek seferlik çalışma planla (DELETE /api/one-offs/{id} → iptal)
GET    /api/runs                 → Çalışma geçmişi (sayfalı)
GET    /api/runs/{id}            → Tek çalışmanın tüm ayrıntıları (yanıt, loglar)
GET    /api/runs/heatmap         → Günlük çalışma takvimi
GET    /api/session              → Oturum sağlığı
POST   /api/prompt/preview       → Prompt değişkenlerini doldurulmuş hâliyle göster
"""

import asyncio
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, HTTPException, BackgroundTasks
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from src import history, prompt_vars
from src.config_store import merge_jobs, section, update_config
from src.logger import setup_logger
from src.scheduler import (
    cancel_one_off, get_scheduler_status, jobs_overview, job_config, load_config, now_in,
    reload_scheduler, run_bot_job, schedule_one_off, set_paused, skip_next, unskip,
)
from src.session import SessionManager
from src.state import bot_state, BotStatus

logger = setup_logger("api")
router = APIRouter(prefix="/api")

CONFIG_PATH = "config/config.yaml"
SCREENSHOT_DIR = Path("./screenshots")


# ── Pydantic modelleri ────────────────────────────────────────

class SchedulerJob(BaseModel):
    id: str
    cron: str = Field(..., description="Cron ifadesi: 'dakika saat gün ay haftanın-günü'")
    enabled: bool = True
    chat_id: str  = Field("", description="Bu göreve özgü Claude chat ID")
    prompt: str   = Field("", description="Bu göreve özgü prompt metni")
    retries: int  = Field(0, ge=0, le=5, description="Hata olursa kaç kez tekrar denensin")
    retry_delay: int = Field(5, ge=1, le=240, description="Denemeler arası bekleme (dk)")


class FullConfig(BaseModel):
    jobs: List[SchedulerJob]
    timezone: str = "Europe/Istanbul"
    headless: bool = True


class PauseRequest(BaseModel):
    paused: bool


class OneOffRequest(BaseModel):
    job_id: str
    run_at: datetime = Field(..., description="ISO 8601; saat dilimi yoksa scheduler dilimi kullanılır")


class PromptPreview(BaseModel):
    prompt: str


def _session_manager(cfg: dict) -> SessionManager:
    sess_cfg = cfg.get("session", {})
    return SessionManager(
        cookie_file=sess_cfg.get("cookie_file", "./sessions/claude_cookies.json"),
        storage_file=sess_cfg.get("storage_file", "./sessions/claude_storage.json"),
    )


# ── Durum ─────────────────────────────────────────────────────

@router.get("/status")
async def get_status():
    """Bot durumu, kalıcı istatistikler ve son çalışma."""
    cfg = load_config(CONFIG_PATH)
    if bot_state.status == BotStatus.NO_SESSION:
        try:
            if _session_manager(cfg).session_exists():
                bot_state.set_idle()
        except Exception:
            pass

    status_data = bot_state.to_dict()
    totals = history.totals()
    last = history.last_finished_run()
    status_data["stats"] = {"total": totals["total"], "success": totals["success"],
                            "error": totals["error"] + totals["session"], "skipped": totals["skipped"]}
    status_data["last_run_record"] = last
    if last:
        status_data["last_run"] = last["started_at"]
    return {
        **status_data,
        "paused": bool(cfg.get("scheduler", {}).get("paused", False)),
        "scheduler": get_scheduler_status(),
    }


@router.get("/session")
async def get_session():
    """Kayıtlı oturumun ne zaman alındığı ve ne zaman sona ereceği."""
    return _session_manager(load_config(CONFIG_PATH)).health()


# ── Konfigürasyon ─────────────────────────────────────────────

@router.get("/config")
async def get_config():
    """Mevcut config.yaml içeriğini döndürür."""
    try:
        config = load_config(CONFIG_PATH)
        sched  = config.get("scheduler", {})
        browser = config.get("browser", {})
        return {
            "jobs":     sched.get("jobs", []),
            "timezone": sched.get("timezone", "Europe/Istanbul"),
            "headless": browser.get("headless", True),
            "paused":   sched.get("paused", False),
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/config")
async def update_config_endpoint(payload: FullConfig):
    """Config.yaml'ı (yorumları koruyarak, atomik) günceller ve scheduler'ı yeniden yükler."""
    ids = [j.id for j in payload.jobs]
    if len(ids) != len(set(ids)):
        raise HTTPException(status_code=400, detail="Görev adları benzersiz olmalı")

    def mutate(doc):
        section(doc, "browser")["headless"] = payload.headless
        sched = section(doc, "scheduler")
        sched["timezone"] = payload.timezone
        merge_jobs(sched, [j.model_dump() for j in payload.jobs])

    try:
        update_config(CONFIG_PATH, mutate)
        reload_scheduler(CONFIG_PATH)
        logger.info("✅ Config güncellendi ve scheduler yeniden yüklendi")
        return {"success": True, "message": "Konfigürasyon güncellendi"}
    except Exception as exc:
        logger.error(f"Config güncelleme hatası: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/prompt/preview")
async def preview_prompt(payload: PromptPreview):
    cfg = load_config(CONFIG_PATH)
    return {
        "rendered":  prompt_vars.render(payload.prompt, now=now_in(cfg)),
        "variables": [{"name": n, "label": l} for n, l in prompt_vars.VARIABLES],
    }


# ── Loglar ────────────────────────────────────────────────────

@router.get("/logs")
async def get_logs(n: int = 100):
    """Son N log satırını döndürür."""
    lines = bot_state.get_logs(last_n=min(n, 300))
    return {"logs": lines, "count": len(lines)}


@router.get("/logs/stream")
async def stream_logs():
    """
    Server-Sent Events ile canlı log akışı.
    Tarayıcı EventSource API ile bağlanır.
    """
    async def event_generator():
        # Monoton sıra numarası: buffer 300'de dolsa bile yeni satırlar tespit edilir.
        # seq=0 → bağlanınca buffer'daki mevcut loglar da gönderilir.
        last_seq = 0
        while True:
            last_seq, new_lines = bot_state.get_logs_since(last_seq)
            for line in new_lines:
                # SSE formatı: "data: <içerik>\n\n"
                # Çok satırlı loglar (traceback) her satıra "data: " ile tek event olur
                payload = line.replace("\n", "\ndata: ")
                yield f"data: {payload}\n\n"

            # Heartbeat (bağlantıyı canlı tut)
            yield ": heartbeat\n\n"
            await asyncio.sleep(1)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ── Ekran görüntüleri ─────────────────────────────────────────

@router.get("/screenshots/list")
async def list_screenshots():
    """Tüm ekran görüntülerini en yeniden eskiye doğru listeler."""
    SCREENSHOT_DIR.mkdir(exist_ok=True)
    files = sorted(SCREENSHOT_DIR.glob("*.png"), key=lambda f: f.stat().st_mtime, reverse=True)
    return {"screenshots": [
        {"filename": f.name, "url": f"/screenshots/{f.name}",
         "timestamp": f.stat().st_mtime, "size": f.stat().st_size}
        for f in files
    ]}


# ── Görev çalıştırma ve planlama ──────────────────────────────

@router.post("/run-now")
async def run_now(background_tasks: BackgroundTasks, job_id: str = ""):
    """
    Botu anında çalıştırır.
    job_id verilirse o job'ın chat_id ve prompt'ı kullanılır.
    Boş bırakılırsa config.yaml'daki ilk aktif job çalıştırılır.
    """
    if bot_state.status == BotStatus.RUNNING:
        raise HTTPException(status_code=409, detail="Bot zaten çalışıyor")

    try:
        jobs_cfg = load_config(CONFIG_PATH).get("scheduler", {}).get("jobs", []) or []
    except Exception:
        jobs_cfg = []

    resolved_id = job_id
    if not resolved_id:
        first = next((j for j in jobs_cfg if j.get("enabled", True)), None)
        resolved_id = first.get("id", "manual") if first else "manual_trigger"

    logger.info(f"▶️  Manuel tetikleme: job={resolved_id}")
    background_tasks.add_task(run_bot_job, config_path=CONFIG_PATH, job_id=resolved_id, trigger="manual")
    return {"success": True, "message": f"'{resolved_id}' görevi başlatıldı", "job_id": resolved_id}


@router.get("/jobs")
async def get_jobs():
    """Görevler, sonraki çalışma zamanları, atlamalar ve bekleyen tek seferlik/tekrar çalışmaları."""
    return jobs_overview(CONFIG_PATH)


@router.post("/jobs/{job_id}/skip")
async def skip_job(job_id: str):
    try:
        at = skip_next(job_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"success": True, "skipped_run": at.isoformat()}


@router.delete("/jobs/{job_id}/skip")
async def unskip_job(job_id: str):
    unskip(job_id)
    return {"success": True}


@router.post("/scheduler/pause")
async def pause_scheduler(payload: PauseRequest):
    set_paused(payload.paused, CONFIG_PATH)
    return {"success": True, "paused": payload.paused}


@router.post("/one-offs")
async def create_one_off(payload: OneOffRequest):
    try:
        one_off_id = schedule_one_off(payload.job_id, payload.run_at, CONFIG_PATH)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"success": True, "id": one_off_id}


@router.delete("/one-offs/{one_off_id}")
async def delete_one_off(one_off_id: int):
    if not history.get_one_off(one_off_id):
        raise HTTPException(status_code=404, detail="Plan bulunamadı")
    cancel_one_off(one_off_id)
    return {"success": True}


# ── Geçmiş ────────────────────────────────────────────────────

@router.get("/runs")
async def list_runs(job_id: str = "", status: str = "", limit: int = 30, before_id: Optional[int] = None):
    runs = history.list_runs(job_id or None, status or None, limit, before_id)
    return {
        "runs":   runs,
        "counts": history.status_counts(job_id or None),
        "more":   len(runs) == max(1, min(limit, 200)),
    }


@router.get("/runs/heatmap")
async def runs_heatmap(days: int = 91):
    cfg = load_config(CONFIG_PATH)
    return {"days": history.heatmap(now_in(cfg), max(7, min(days, 371)))}


@router.get("/runs/{run_id}")
async def get_run(run_id: int):
    run = history.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Çalışma bulunamadı")
    shot = run.get("screenshot")
    run["screenshot_url"] = f"/screenshots/{shot}" if shot and (SCREENSHOT_DIR / shot).exists() else None
    run["job_exists"] = bool(job_config(load_config(CONFIG_PATH), run["job_id"]))
    return run
