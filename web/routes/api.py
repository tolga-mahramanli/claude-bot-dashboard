"""
web/routes/api.py - REST API Endpoint'leri

GET  /api/status          → Bot durumu + istatistikler
GET  /api/config          → Mevcut konfigürasyonu oku
POST /api/config          → Konfigürasyonu güncelle + scheduler reload
GET  /api/logs            → Son N log satırı
GET  /api/logs/stream     → SSE (Server-Sent Events) canlı log akışı
GET  /api/screenshot      → Son hata screenshot'ını base64 döndür
POST /api/run-now         → Anında bir bot görevi tetikle
GET  /api/jobs            → APScheduler job listesi
"""

import asyncio
import base64
import os
import threading
from pathlib import Path
from typing import Optional

import yaml
from fastapi import APIRouter, HTTPException, BackgroundTasks
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel, Field

from src.logger import setup_logger
from src.scheduler import reload_scheduler, get_scheduler_status, run_bot_job, load_config
from src.state import bot_state, BotStatus

logger = setup_logger("api")
router = APIRouter(prefix="/api")

CONFIG_PATH = "config/config.yaml"
SCREENSHOT_DIR = Path("./screenshots")


# ── Pydantic modelleri ────────────────────────────────────────

class ClaudeConfig(BaseModel):
    chat_id: str = Field(..., description="Claude chat ID")
    prompt: str = Field(..., description="Gönderilecek prompt metni")


class SchedulerJob(BaseModel):
    id: str
    cron: str = Field(..., description="Cron ifadesi: 'dakika saat gün ay haftanın-günü'")
    enabled: bool = True
    chat_id: str  = Field("", description="Bu göreve özgü Claude chat ID")
    prompt: str   = Field("", description="Bu göreve özgü prompt metni")


class FullConfig(BaseModel):
    jobs: list[SchedulerJob]
    timezone: str = "Europe/Istanbul"
    headless: bool = True


# ── Endpoint'ler ──────────────────────────────────────────────

@router.get("/status")
async def get_status():
    """Bot durumu, istatistikler ve sonraki çalışma zamanı."""
    if bot_state.status == BotStatus.NO_SESSION:
        try:
            from src.session import SessionManager
            cfg = load_config(CONFIG_PATH)
            sess_cfg = cfg.get("session", {})
            sm = SessionManager(
                cookie_file=sess_cfg.get("cookie_file", "./sessions/claude_cookies.json"),
                storage_file=sess_cfg.get("storage_file", "./sessions/claude_storage.json"),
            )
            if sm.session_exists():
                bot_state.set_idle()
        except Exception:
            pass

    status_data = bot_state.to_dict()
    scheduler_data = get_scheduler_status()
    return {
        **status_data,
        "scheduler": scheduler_data,
    }


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
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/config")
async def update_config(payload: FullConfig):
    """Config.yaml'ı günceller ve scheduler'ı yeniden yükler."""
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}

        # Browser ayarı
        config.setdefault("browser", {})["headless"] = payload.headless

        # Scheduler: job'lar artık kendi chat_id ve prompt'larını taşıyor
        config.setdefault("scheduler", {})["timezone"] = payload.timezone
        config["scheduler"]["jobs"] = [
            {
                "id":      j.id,
                "cron":    j.cron,
                "enabled": j.enabled,
                "chat_id": j.chat_id,
                "prompt":  j.prompt,
            }
            for j in payload.jobs
        ]

        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            yaml.dump(config, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

        reload_scheduler(CONFIG_PATH)
        logger.info("✅ Config güncellendi ve scheduler yeniden yüklendi")
        return {"success": True, "message": "Konfigürasyon güncellendi"}

    except Exception as exc:
        logger.error(f"Config güncelleme hatası: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


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


@router.get("/screenshot")
async def get_screenshot():
    """Geriye dönük uyumluluk için (şu an dashboard eski kodu kullanıyorsa). En son screenshot."""
    SCREENSHOT_DIR.mkdir(exist_ok=True)
    screenshot_path = bot_state.last_screenshot

    if not screenshot_path or not Path(screenshot_path).exists():
        files = sorted(SCREENSHOT_DIR.glob("*.png"), key=lambda f: f.stat().st_mtime, reverse=True)
        if not files:
            return JSONResponse({"screenshot": None, "filename": None})
        screenshot_path = str(files[0])

    try:
        with open(screenshot_path, "rb") as f:
            data = base64.b64encode(f.read()).decode("utf-8")
        return {
            "screenshot": data,
            "filename": Path(screenshot_path).name,
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/screenshots/list")
async def list_screenshots():
    """Tüm ekran görüntülerini en yeniden eskiye doğru listeler."""
    SCREENSHOT_DIR.mkdir(exist_ok=True)
    files = sorted(SCREENSHOT_DIR.glob("*.png"), key=lambda f: f.stat().st_mtime, reverse=True)
    
    result = []
    for f in files:
        result.append({
            "filename": f.name,
            "url": f"/screenshots/{f.name}",
            "timestamp": f.stat().st_mtime,
            "size": f.stat().st_size
        })
    return {"screenshots": result}


@router.post("/run-now")
async def run_now(background_tasks: BackgroundTasks, job_id: str = ""):
    """
    Botu anında çalıştırır.
    job_id verilirse o job'ın chat_id ve prompt'ı kullanılır.
    Boş bırakılırsa config.yaml'daki ilk job çalıştırılır.
    """
    if bot_state.status == BotStatus.RUNNING:
        raise HTTPException(status_code=409, detail="Bot zaten çalışıyor")

    # Job'a özgü chat_id + prompt'ı config'den çek
    try:
        config = load_config(CONFIG_PATH)
        jobs_cfg = config.get("scheduler", {}).get("jobs", [])
    except Exception:
        jobs_cfg = []

    job_chat_id = ""
    job_prompt  = ""
    resolved_id = job_id or "manual_trigger"

    if job_id:
        # İstenen job'ı bul
        for j in jobs_cfg:
            if j.get("id") == job_id:
                job_chat_id = j.get("chat_id", "")
                job_prompt  = j.get("prompt",  "")
                break
    elif jobs_cfg:
        # job_id verilmediyse → ilk aktif job
        for j in jobs_cfg:
            if j.get("enabled", True):
                resolved_id = j.get("id", "manual")
                job_chat_id = j.get("chat_id", "")
                job_prompt  = j.get("prompt",  "")
                break

    logger.info(f"▶️  Manuel tetikleme: job={resolved_id}, chat={job_chat_id[:8] + '...' if job_chat_id else 'global'}")

    def _run():
        run_bot_job(
            config_path=CONFIG_PATH,
            job_id=resolved_id,
            chat_id=job_chat_id,
            prompt=job_prompt,
        )

    background_tasks.add_task(_run)
    return {
        "success": True,
        "message": f"'{resolved_id}' gorevi başlatıldı",
        "job_id": resolved_id,
    }


@router.get("/jobs")
async def get_jobs():
    """
    APScheduler job listesi + config'deki job detaylarını birleştirir.
    Dashboard'un job seçici doldurması için kullanılır.
    """
    scheduler_status = get_scheduler_status()

    # Config'deki tam job listesini de ekle (scheduler'a giremeyen pasifler dahil)
    try:
        config = load_config(CONFIG_PATH)
        jobs_cfg = config.get("scheduler", {}).get("jobs", [])
    except Exception:
        jobs_cfg = []

    # Scheduler next_run ile config bilgisini birleştir
    sched_map = {j["id"]: j for j in scheduler_status.get("jobs", [])}

    merged = []
    for j in jobs_cfg:
        sid = j.get("id", "")
        merged.append({
            "id":             sid,
            "enabled":        j.get("enabled", True),
            "cron":           j.get("cron", ""),
            "chat_id":        j.get("chat_id", ""),
            "prompt_preview": (j.get("prompt", "")[:50] + "...") if len(j.get("prompt", "")) > 50 else j.get("prompt", ""),
            "next_run":       sched_map.get(sid, {}).get("next_run"),
        })

    return {
        "running": scheduler_status.get("running", False),
        "jobs":    merged,
    }
