"""
session.py - Cookie ve Session Yönetimi
Claude.ai oturumunu disk üzerinde saklayıp yükler.
"""

import json
import time
from pathlib import Path
from typing import Optional

from selenium.webdriver.chrome.webdriver import WebDriver

from src.logger import setup_logger

logger = setup_logger("session")


class SessionManager:
    """
    Claude.ai session verilerini (cookie + localStorage) diske kaydeder
    ve yükler. İlk çalışmada manuel login yapılır, sonraki çalışmalarda
    kaydedilmiş session kullanılır.
    """

    def __init__(self, cookie_file: str, storage_file: str) -> None:
        self.cookie_file = Path(cookie_file)
        self.storage_file = Path(storage_file)
        # Dizinlerin var olduğundan emin ol
        self.cookie_file.parent.mkdir(parents=True, exist_ok=True)

    # ──────────────────────────────────────────────────────────
    # Cookie İşlemleri
    # ──────────────────────────────────────────────────────────

    def save_session(self, driver: WebDriver) -> None:
        """Mevcut oturumun cookie ve localStorage'ını diske kaydeder."""
        try:
            # Cookie'leri kaydet
            cookies = driver.get_cookies()
            with open(self.cookie_file, "w", encoding="utf-8") as f:
                json.dump(cookies, f, indent=2, ensure_ascii=False)
            logger.info(f"✅ {len(cookies)} cookie kaydedildi → {self.cookie_file}")

            # localStorage'ı kaydet
            storage = driver.execute_script(
                """
                let storage = {};
                for (let i = 0; i < localStorage.length; i++) {
                    let key = localStorage.key(i);
                    storage[key] = localStorage.getItem(key);
                }
                return storage;
                """
            )
            with open(self.storage_file, "w", encoding="utf-8") as f:
                json.dump(storage, f, indent=2, ensure_ascii=False)
            logger.info(f"✅ localStorage kaydedildi → {self.storage_file}")

        except Exception as exc:
            logger.error(f"Session kaydetme hatası: {exc}", exc_info=True)
            raise

    def load_session(self, driver: WebDriver, base_url: str) -> bool:
        """
        Diske kaydedilmiş session'ı tarayıcıya yükler.
        Returns:
            True  → session başarıyla yüklendi
            False → kayıtlı session yok, yeniden giriş gerekiyor
        """
        if not self.cookie_file.exists():
            logger.warning("⚠️  Cookie dosyası bulunamadı. Manuel giriş gerekiyor.")
            return False

        try:
            # Önce ana domain'e git (cookie domain uyuşması için)
            domain_url = _extract_base_domain(base_url)
            logger.info(f"Domain'e gidiliyor: {domain_url}")
            driver.get(domain_url)
            time.sleep(2)

            # Cookie'leri yükle
            with open(self.cookie_file, "r", encoding="utf-8") as f:
                cookies: list[dict] = json.load(f)

            loaded = 0
            skipped = 0
            for cookie in cookies:
                try:
                    # Selenium'un kabul etmediği alanları temizle
                    cookie = _sanitize_cookie(cookie)
                    driver.add_cookie(cookie)
                    loaded += 1
                except Exception as e:
                    skipped += 1
                    logger.debug(f"Cookie atlandı ({cookie.get('name', '?')}): {e}")

            logger.info(f"✅ {loaded} cookie yüklendi, {skipped} atlandı")

            # localStorage'ı geri yükle (varsa)
            if self.storage_file.exists():
                with open(self.storage_file, "r", encoding="utf-8") as f:
                    storage: dict = json.load(f)

                for key, value in storage.items():
                    driver.execute_script(
                        "localStorage.setItem(arguments[0], arguments[1]);",
                        key,
                        value,
                    )
                logger.info(f"✅ {len(storage)} localStorage öğesi yüklendi")

            return True

        except Exception as exc:
            logger.error(f"Session yükleme hatası: {exc}", exc_info=True)
            return False

    def session_exists(self) -> bool:
        """Cookie dosyasının var olup olmadığını kontrol eder."""
        return self.cookie_file.exists() and self.cookie_file.stat().st_size > 10

    def clear_session(self) -> None:
        """Kayıtlı session dosyalarını siler (çıkış yaptıktan sonra kullan)."""
        for path in (self.cookie_file, self.storage_file):
            if path.exists():
                path.unlink()
                logger.info(f"🗑️  Silindi: {path}")


# ──────────────────────────────────────────────────────────────
# Yardımcı Fonksiyonlar
# ──────────────────────────────────────────────────────────────

def _sanitize_cookie(cookie: dict) -> dict:
    """Selenium'un sorun çıkardığı cookie alanlarını temizler."""
    allowed_keys = {
        "name", "value", "domain", "path",
        "secure", "httpOnly", "expiry", "sameSite",
    }
    sanitized = {k: v for k, v in cookie.items() if k in allowed_keys}

    # sameSite değeri sadece None/Strict/Lax olabilir
    same_site = sanitized.get("sameSite", "")
    if same_site not in ("None", "Strict", "Lax"):
        sanitized.pop("sameSite", None)

    return sanitized


def _extract_base_domain(url: str) -> str:
    """'https://claude.ai/chat/xyz' → 'https://claude.ai' döndürür."""
    from urllib.parse import urlparse
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}"
