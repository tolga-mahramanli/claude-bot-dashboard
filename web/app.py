"""
web/app.py - FastAPI Uygulama Fabrikası
APScheduler'ı lifespan context manager ile başlatır/durdurur.
"""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.requests import Request
from fastapi.responses import HTMLResponse

from src.logger import setup_logger
from src.scheduler import create_scheduler
from web.routes.api import router as api_router

logger = setup_logger("web")

TEMPLATES_DIR = Path(__file__).parent / "templates"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    FastAPI lifespan: uygulama başlarken scheduler'ı başlat,
    kapanırken düzgünce kapat.
    """
    logger.info("🚀 FastAPI başlatılıyor...")

    scheduler = create_scheduler("config/config.yaml")
    scheduler.start()
    logger.info("⏰ APScheduler arka planda başlatıldı")

    yield  # Uygulama burada çalışır

    logger.info("🛑 FastAPI kapatılıyor...")
    if scheduler.running:
        scheduler.shutdown(wait=False)
    logger.info("✅ Scheduler durduruldu")


def create_app() -> FastAPI:
    """FastAPI uygulamasını oluşturur ve rotaları bağlar."""

    app = FastAPI(
        title="Claude Bot Dashboard",
        description="Claude.ai Otomasyon Botu Web Arayüzü",
        version="2.0.0",
        lifespan=lifespan,
        docs_url="/docs",   # Swagger UI
        redoc_url=None,
    )

    # ── API rotaları ──────────────────────────────────────────
    app.include_router(api_router)

    # ── Statik Dosyalar (Ekran Görüntüleri) ───────────────────
    screenshot_dir = Path("screenshots")
    screenshot_dir.mkdir(exist_ok=True)
    app.mount("/screenshots", StaticFiles(directory=str(screenshot_dir)), name="screenshots")

    # ── Ana sayfa (tek sayfalık dashboard) ───────────────────
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

    @app.get("/", response_class=HTMLResponse)
    async def dashboard(request: Request):
        return templates.TemplateResponse("index.html", {"request": request})

    logger.info("✅ FastAPI rotaları hazır")
    return app
