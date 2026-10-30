"""
main.py - Bot Giriş Noktası (v2 - Web UI + Scheduler)
Kullanım:
  python main.py               → Web UI + Scheduler (normal mod)
  python main.py --run-once    → Tek seferlik çalıştır ve çık
  python main.py --save-session → Manuel login, session kaydet
  python main.py --port 8080   → Farklı port
"""

import argparse
import sys
from pathlib import Path

import uvicorn

from src.logger import setup_logger

logger = setup_logger("main")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Claude.ai Otomasyon Botu",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Örnekler:
  python main.py                     # Web UI + Scheduler (http://localhost:8000)
  python main.py --port 9000         # Farklı port
  python main.py --run-once          # Tek seferlik çalıştır
  python main.py --save-session      # Session kaydet (ilk kurulum)
  python main.py --host 0.0.0.0      # Dışarıdan erişim için
        """,
    )
    parser.add_argument("--config", default="config/config.yaml")
    parser.add_argument("--host",   default="127.0.0.1", help="Dinlenecek host (varsayılan: 127.0.0.1)")
    parser.add_argument("--port",   default=8000, type=int, help="Port (varsayılan: 8000)")
    parser.add_argument("--run-once",    action="store_true", help="Tek seferlik çalıştır")
    parser.add_argument("--save-session", action="store_true", help="Session kaydet (ilk kurulum)")
    parser.add_argument("--reload", action="store_true", help="Hot-reload (geliştirme)")
    return parser.parse_args()


def save_session_mode(config: dict) -> None:
    """Manuel login + session kaydetme (ilk kurulum)."""
    import time
    import undetected_chromedriver as uc
    from src.session import SessionManager

    logger.info("=" * 60)
    logger.info("📋 SESSION KAYDETME MODU")
    logger.info("=" * 60)

    config["browser"]["headless"] = False

    options = uc.ChromeOptions()
    options.add_argument("--no-sandbox")
    options.add_argument("--window-size=1280,900")
    options.add_argument("--lang=tr-TR")

    user_data_dir = config.get("browser", {}).get("user_data_dir", "./sessions/chrome_profile")
    Path(user_data_dir).mkdir(parents=True, exist_ok=True)
    options.add_argument(f"--user-data-dir={str(Path(user_data_dir).resolve())}")

    from src.bot import resolve_chrome_version, find_chrome_binary
    chrome_bin = config.get("browser", {}).get("chrome_binary", "") or find_chrome_binary()
    if chrome_bin:
        options.binary_location = chrome_bin
    chrome_version = resolve_chrome_version(config.get("browser", {}), chrome_bin)
    logger.info("Chrome açılıyor...")
    driver = uc.Chrome(options=options, use_subprocess=True, version_main=chrome_version)

    base_url = config.get("claude", {}).get("base_url", "https://claude.ai")
    driver.get(base_url)

    print("\n" + "=" * 60)
    print("🌐 Tarayıcı açıldı: claude.ai")
    print("\n  1. Claude.ai'ye manuel giriş yapın")
    print("  2. Giriş tamamlandığında terminale dönün")
    print("  3. ENTER'a basın")
    print("=" * 60 + "\n")
    input("✅ Giriş yaptıktan sonra ENTER'a basın: ")

    sm = SessionManager(
        cookie_file=config.get("session", {}).get("cookie_file", "./sessions/claude_cookies.json"),
        storage_file=config.get("session", {}).get("storage_file", "./sessions/claude_storage.json"),
    )

    try:
        sm.save_session(driver)
        print("\n✅ Session başarıyla kaydedildi!")
        print("   Şimdi 'python main.py' ile Web UI'ı başlatabilirsiniz.")
    finally:
        driver.quit()


def run_once_mode(config: dict) -> None:
    """Scheduler olmadan tek seferlik çalıştırma."""
    from src.bot import ClaudeBot
    logger.info("▶️  Tek seferlik çalıştırma modu")
    bot = ClaudeBot(config)
    success = bot.run_task()
    sys.exit(0 if success else 1)


def web_mode(host: str, port: int, reload: bool = False) -> None:
    """FastAPI Web UI + APScheduler arka plan modu."""
    logger.info("╔══════════════════════════════════════════╗")
    logger.info("║     Claude Bot Dashboard Başlatılıyor    ║")
    logger.info("╚══════════════════════════════════════════╝")
    logger.info(f"🌐 Dashboard: http://{host}:{port}")
    logger.info(f"📖 API Docs:  http://{host}:{port}/docs")

    uvicorn.run(
        "web.app:create_app",
        factory=True,
        host=host,
        port=port,
        reload=reload,
        log_level="warning",   # uvicorn'un kendi logları sessiz
        access_log=False,
    )


def main() -> None:
    args = parse_args()

    from src.scheduler import load_config
    try:
        config = load_config(args.config)
    except FileNotFoundError as exc:
        logger.error(str(exc))
        sys.exit(1)

    if args.save_session:
        save_session_mode(config)
    elif args.run_once:
        run_once_mode(config)
    else:
        web_mode(host=args.host, port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()
