"""
logger.py - Merkezi loglama sistemi (v2 - Web UI entegrasyonlu)
Rotating file handler + renkli konsol + BotState log buffer
"""

import logging
import sys
from datetime import datetime
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

import yaml


def setup_logger(name: str = "claude_bot") -> logging.Logger:
    """
    Bot için merkezi logger'ı yapılandırır.
    - Dosyaya günlük rotasyonla yazar
    - Konsola renkli çıktı verir
    - BotState log buffer'ına yazar (Web UI için)
    """
    config = _load_config()
    log_cfg = config.get("logging", {})

    level_str = log_cfg.get("level", "INFO").upper()
    level = getattr(logging, level_str, logging.INFO)

    log_dir = Path(log_cfg.get("log_dir", "./logs"))
    log_dir.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger(name)
    logger.setLevel(level)

    # Duplicate handler engellemesi
    if logger.handlers:
        return logger

    # ── Dosya handler (günlük rotasyon) ──────────────────────
    log_file = log_dir / f"{name}.log"
    file_handler = TimedRotatingFileHandler(
        filename=log_file,
        when="midnight",
        interval=1,
        backupCount=log_cfg.get("max_log_files", 30),
        encoding="utf-8",
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(_get_formatter(colored=False))
    logger.addHandler(file_handler)

    # ── Konsol handler ────────────────────────────────────────
    if log_cfg.get("log_to_console", True):
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(level)
        console_handler.setFormatter(_get_formatter(colored=True))
        logger.addHandler(console_handler)

    # ── Web UI log buffer handler ─────────────────────────────
    state_handler = _StateLogHandler()
    state_handler.setLevel(level)
    state_handler.setFormatter(_get_formatter(colored=False))
    logger.addHandler(state_handler)

    return logger


def _get_formatter(colored: bool = False) -> logging.Formatter:
    if colored:
        return _ColoredFormatter(
            fmt="%(asctime)s │ %(levelname)-8s │ %(name)s │ %(message)s",
            datefmt="%H:%M:%S",
        )
    return logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def _load_config() -> dict:
    config_path = Path(__file__).parent.parent / "config" / "config.yaml"
    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}


class _StateLogHandler(logging.Handler):
    """Log satırlarını BotState buffer'ına yazar (Web UI için)."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            # Circular import'u önlemek için geç import
            from src.state import bot_state
            line = self.format(record)
            bot_state.add_log(line)
        except Exception:
            pass


class _ColoredFormatter(logging.Formatter):
    """ANSI renk kodlarıyla renkli log çıktısı."""

    COLORS = {
        "DEBUG": "\033[36m",
        "INFO": "\033[32m",
        "WARNING": "\033[33m",
        "ERROR": "\033[31m",
        "CRITICAL": "\033[35m",
    }
    RESET = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        # Kayıt tüm handler'larca paylaşılır; renk kodu kalıcı yazılırsa
        # sonraki handler'lar (Web UI tamponu) da ANSI kodlu seviye görür.
        original = record.levelname
        color = self.COLORS.get(original, self.RESET)
        record.levelname = f"{color}{original}{self.RESET}"
        try:
            return super().format(record)
        finally:
            record.levelname = original
