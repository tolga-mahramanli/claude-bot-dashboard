"""
state.py - Bot ve Web UI arasında thread-safe paylaşılan durum
Singleton pattern; tüm modüller aynı nesneyi import eder.
"""

import threading
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional


class BotStatus(str, Enum):
    IDLE = "idle"           # Zamanlama bekliyor
    RUNNING = "running"     # Görev aktif
    SUCCESS = "success"     # Son görev başarılı
    ERROR = "error"         # Son görev hatalı
    NO_SESSION = "no_session"  # Session dosyası eksik


@dataclass
class BotState:
    """Thread-safe bot durum nesnesi."""

    status: BotStatus = BotStatus.IDLE
    last_run: Optional[datetime] = None
    next_run: Optional[datetime] = None
    last_error: Optional[str] = None
    last_screenshot: Optional[str] = None   # Dosya yolu
    total_runs: int = 0
    success_runs: int = 0
    error_runs: int = 0

    # Son N log satırı (canlı log akışı için)
    _log_buffer: deque = field(default_factory=lambda: deque(maxlen=300))
    # Toplam eklenen log sayısı (monoton artar; buffer dolsa da sıfırlanmaz)
    _log_seq: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock)

    # ── Durum güncelleme metodları ────────────────────────────

    def set_running(self) -> None:
        with self._lock:
            self.status = BotStatus.RUNNING
            self.last_run = datetime.now()
            self.last_error = None

    def set_success(self) -> None:
        with self._lock:
            self.status = BotStatus.SUCCESS
            self.total_runs += 1
            self.success_runs += 1

    def set_error(self, message: str, screenshot: Optional[str] = None) -> None:
        with self._lock:
            self.status = BotStatus.ERROR
            self.last_error = message
            self.total_runs += 1
            self.error_runs += 1
            if screenshot:
                self.last_screenshot = screenshot

    def set_idle(self, next_run: Optional[datetime] = None) -> None:
        with self._lock:
            # Çalışıyorsa durumu idle'a çekme; success/error'ı koru
            if self.status == BotStatus.RUNNING:
                return
            self.status = BotStatus.IDLE
            if next_run:
                self.next_run = next_run

    def update_next_run(self, next_run: Optional[datetime]) -> None:
        with self._lock:
            self.next_run = next_run

    def set_no_session(self) -> None:
        with self._lock:
            self.status = BotStatus.NO_SESSION

    # ── Log yönetimi ─────────────────────────────────────────

    def add_log(self, line: str) -> None:
        with self._lock:
            self._log_buffer.append(line)
            self._log_seq += 1

    def get_logs(self, last_n: int = 100) -> list[str]:
        with self._lock:
            buf = list(self._log_buffer)
        return buf[-last_n:]

    def get_logs_since(self, seq: int) -> tuple[int, list[str]]:
        """
        `seq` sırasından sonra eklenen logları döndürür.
        Returns: (güncel_seq, yeni_satırlar). Buffer'dan taşan eski satırlar atlanır.
        """
        with self._lock:
            current = self._log_seq
            buf = list(self._log_buffer)
        missed = current - seq
        if missed <= 0:
            return current, []
        return current, buf[-missed:]

    # ── JSON serileştirme ─────────────────────────────────────

    def to_dict(self) -> dict:
        with self._lock:
            return {
                "status": self.status.value,
                "last_run": self.last_run.isoformat() if self.last_run else None,
                "next_run": self.next_run.isoformat() if self.next_run else None,
                "last_error": self.last_error,
                "last_screenshot": Path(self.last_screenshot).name
                if self.last_screenshot
                else None,
                "stats": {
                    "total": self.total_runs,
                    "success": self.success_runs,
                    "error": self.error_runs,
                },
            }


# ── Global singleton ──────────────────────────────────────────
bot_state = BotState()
