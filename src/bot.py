"""
bot.py - Ana Bot Motoru (v3 - per-job chat_id + prompt desteği)
Cloudflare bypass + stealth Chrome + Claude.ai otomasyon
"""

import os
import platform
import time
import random
import traceback
from datetime import datetime
from pathlib import Path
from typing import Optional

import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import (
    TimeoutException,
    NoSuchElementException,
    ElementNotInteractableException,
    WebDriverException,
)

from src.logger import setup_logger
from src.session import SessionManager
from src.state import bot_state, BotStatus

logger = setup_logger("bot")

IS_MAC = platform.system() == "Darwin"


# ────────────────────────────────────────────────────────────────
# Claude.ai DOM Selektörleri
# ────────────────────────────────────────────────────────────────
class Selectors:
    TEXTAREA          = 'div[contenteditable="true"][data-placeholder]'
    TEXTAREA_FB1      = 'div[contenteditable="true"]'
    TEXTAREA_FB2      = 'p[data-placeholder]'
    SEND_BUTTON_SELECTORS = [
        'button[aria-label="Send message"]',
        'button[aria-label="Send Message"]',
        'button[data-testid="send-button"]',
        'button[type="submit"]',
    ]
    STOP_BUTTON       = 'button[aria-label="Stop Response"], button[aria-label="Stop"]'
    PAGE_LOADED       = 'div[class*="conversation"], main'
    LOGIN_INDICATOR   = 'button[data-testid="login-with-google"], a[href*="/login"]'


# ────────────────────────────────────────────────────────────────

class ClaudeBot:
    """
    Claude.ai'ye mesaj gönderen stealth bot.
    Her run_task() çağrısında chat_id ve prompt override edilebilir
    → her zamanlanmış görev farklı chat + prompt kullanabilir.
    """

    def __init__(self, config: dict) -> None:
        self.config      = config
        self.driver: Optional[uc.Chrome] = None

        self.claude_cfg  = config.get("claude",   {})
        self.browser_cfg = config.get("browser",  {})
        self.timeout_cfg = config.get("timeouts", {})
        self.session_cfg = config.get("session",  {})

        self.base_url = self.claude_cfg.get("base_url", "https://claude.ai/chat")

        self.session_manager = SessionManager(
            cookie_file  = self.session_cfg.get("cookie_file",  "./sessions/claude_cookies.json"),
            storage_file = self.session_cfg.get("storage_file", "./sessions/claude_storage.json"),
        )

        self.screenshot_dir = Path(
            config.get("logging", {}).get("screenshot_dir", "./screenshots")
        )
        self.screenshot_dir.mkdir(parents=True, exist_ok=True)

    # ── Driver ────────────────────────────────────────────────

    def _build_driver(self) -> uc.Chrome:
        """Mac ve Ubuntu için ayrı stealth driver oluşturur."""
        options = uc.ChromeOptions()

        if self.browser_cfg.get("headless", True):
            options.add_argument("--headless=new")

        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--disable-extensions")
        options.add_argument("--no-first-run")
        options.add_argument("--lang=tr-TR,tr")
        options.add_argument("--disable-ipc-flooding-protection")

        if IS_MAC:
            options.add_argument(
                "--user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
            )
        else:
            options.add_argument(
                "--user-agent=Mozilla/5.0 (X11; Linux x86_64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
            )

        w = self.browser_cfg.get("window_size", {}).get("width",  1440)
        h = self.browser_cfg.get("window_size", {}).get("height", 900)
        options.add_argument(f"--window-size={w},{h}")

        user_data_dir = self.browser_cfg.get("user_data_dir", "./sessions/chrome_profile")
        Path(user_data_dir).mkdir(parents=True, exist_ok=True)
        options.add_argument(f"--user-data-dir={os.path.abspath(user_data_dir)}")

        proxy = self.browser_cfg.get("proxy", "")
        if proxy:
            options.add_argument(f"--proxy-server={proxy}")

        chrome_bin = self.browser_cfg.get("chrome_binary", "")
        if not chrome_bin and IS_MAC:
            for p in [
                "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                "/Applications/Chromium.app/Contents/MacOS/Chromium",
            ]:
                if Path(p).exists():
                    chrome_bin = p
                    break
        if chrome_bin:
            options.binary_location = chrome_bin

        chrome_version = self.browser_cfg.get("version_main", 154)
        logger.info(f"Driver başlatılıyor (platform={platform.system()}, headless={self.browser_cfg.get('headless', True)})")
        driver = uc.Chrome(options=options, use_subprocess=True, version_main=chrome_version)

        ua = (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
            if IS_MAC else
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
        )
        driver.execute_cdp_cmd("Network.setUserAgentOverride", {"userAgent": ua})
        driver.execute_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )
        logger.info("✅ Driver hazır")
        return driver

    def _close_driver(self) -> None:
        if self.driver:
            try:
                self.driver.quit()
                logger.info("Driver kapatıldı")
            except Exception:
                pass
            finally:
                self.driver = None

    # ── Session ───────────────────────────────────────────────

    def _is_logged_in(self) -> bool:
        try:
            self.driver.find_element(By.CSS_SELECTOR, Selectors.LOGIN_INDICATOR)
            logger.warning("⚠️  Login sayfası tespit edildi!")
            return False
        except NoSuchElementException:
            return True

    # ── Ana Görev ─────────────────────────────────────────────

    def run_task(
        self,
        chat_id: Optional[str] = None,
        prompt:  Optional[str] = None,
    ) -> bool:
        """
        Tek bir bot görevini çalıştırır.

        Args:
            chat_id: Job'a özgü chat ID   (None → global config'deki değer)
            prompt:  Job'a özgü prompt    (None → global config'deki değer)
        """
        # Öncelik: job parametresi > global config
        effective_chat_id = chat_id or self.claude_cfg.get("chat_id", "")
        effective_prompt  = prompt  or self.claude_cfg.get("prompt", "Merhaba!")
        target_url = f"{self.base_url}/{effective_chat_id}" if effective_chat_id else self.base_url

        logger.info("=" * 60)
        logger.info(f"🤖 Görev başlıyor → {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info(f"🎯 Chat URL   : {target_url}")
        logger.info(f"💬 Prompt     : {effective_prompt[:80]}{'...' if len(effective_prompt) > 80 else ''}")

        bot_state.set_running()

        try:
            self.driver = self._build_driver()

            if not self.session_manager.session_exists():
                logger.error("❌ Session dosyası bulunamadı!")
                bot_state.set_no_session()
                return False

            self.session_manager.load_session(self.driver, target_url)

            logger.info(f"Sayfaya gidiliyor: {target_url}")
            self.driver.get(target_url)
            self._human_delay(2, 4)

            if not self._is_logged_in():
                logger.error("❌ Oturum açılmamış!")
                ss = self._take_screenshot("login_required")
                bot_state.set_error("Oturum geçersiz - yeniden login gerekiyor", ss)
                return False

            self._wait_for_page_load()

            success = self._send_message(effective_prompt)
            if success:
                self._wait_for_response()
                self.session_manager.save_session(self.driver)
                
                # Başarılı olduğunda da screenshot al
                ss = self._take_screenshot("success")
                bot_state.last_screenshot = ss  # State'e yaz ki dashboard görsün
                bot_state.set_success()
                
                logger.info("✅ Görev başarıyla tamamlandı!")
                return True
            else:
                bot_state.set_error("Mesaj gönderilemedi")
                return False

        except Exception as exc:
            err_msg = str(exc)
            logger.error(f"❌ Kritik hata: {err_msg}")
            logger.error(traceback.format_exc())
            ss = self._take_screenshot("critical_error")
            bot_state.set_error(err_msg, ss)
            return False

        finally:
            self._close_driver()

    # ── Sayfa Etkileşim ───────────────────────────────────────

    def _wait_for_page_load(self) -> None:
        timeout = self.timeout_cfg.get("page_load", 30)
        logger.info(f"Sayfa yüklenmesi bekleniyor (max {timeout}s)...")
        wait = WebDriverWait(self.driver, timeout)
        try:
            wait.until(EC.presence_of_element_located(
                (By.CSS_SELECTOR, Selectors.PAGE_LOADED)
            ))
            logger.info("✅ Sayfa yüklendi")
        except TimeoutException:
            logger.warning("⚠️  Conversation elementi bulunamadı, devam ediliyor...")
        wait.until(lambda d: d.execute_script("return document.readyState") == "complete")
        self._human_delay(1, 2)

    def _find_textarea(self):
        """Textarea'yı birden fazla selektörle arar."""
        timeout = self.timeout_cfg.get("element_wait", 20)
        wait = WebDriverWait(self.driver, timeout)
        for selector in (Selectors.TEXTAREA, Selectors.TEXTAREA_FB1, Selectors.TEXTAREA_FB2):
            try:
                el = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, selector)))
                ce = el.get_attribute("contenteditable")
                if ce in ("true", "plaintext-only", None):
                    logger.debug(f"Textarea bulundu: {selector}")
                    return el
            except TimeoutException:
                continue
        raise NoSuchElementException(
            "Textarea bulunamadı! src/bot.py → Selectors sınıfını güncelleyin."
        )

    def _send_message(self, prompt: str) -> bool:
        """
        Claude.ai textarea'ya prompt yazar ve gönderir.

        Kritik: Claude.ai React kullanır → insertText + event dispatch
        ile React state'i güncellenir → gönder butonu aktif olur.
        """
        try:
            logger.info("Textarea aranıyor...")
            textarea = self._find_textarea()

            # 1. Odaklan
            self.driver.execute_script("arguments[0].focus();", textarea)
            self._human_delay(0.4, 0.8)

            # 2. Temizle (Mac: Cmd+A, Linux: Ctrl+A)
            modifier = Keys.COMMAND if IS_MAC else Keys.CONTROL
            textarea.send_keys(modifier + "a")
            textarea.send_keys(Keys.DELETE)
            self._human_delay(0.3, 0.5)

            # 3. Metni yaz + React state'ini güncelle
            logger.info(f"Prompt yazılıyor ({len(prompt)} karakter)...")
            inserted = self.driver.execute_script(
                """
                const el = arguments[0];
                const text = arguments[1];
                el.focus();
                document.execCommand('selectAll', false, null);
                document.execCommand('delete', false, null);
                const inserted = document.execCommand('insertText', false, text);
                return inserted;
                """,
                textarea, prompt,
            )

            if not inserted:
                # Fallback: React event dispatch
                logger.warning("execCommand başarısız, React event dispatch deneniyor...")
                self.driver.execute_script(
                    """
                    const el = arguments[0];
                    const text = arguments[1];
                    el.focus();
                    el.innerHTML = '';
                    const textNode = document.createTextNode(text);
                    el.appendChild(textNode);
                    const range = document.createRange();
                    range.selectNodeContents(el);
                    range.collapse(false);
                    const sel = window.getSelection();
                    sel.removeAllRanges();
                    sel.addRange(range);
                    ['input', 'change', 'keyup'].forEach(name => {
                        el.dispatchEvent(new Event(name, { bubbles: true, cancelable: true }));
                    });
                    """,
                    textarea, prompt,
                )

            self._human_delay(0.8, 1.2)

            # 4. Doğrulama
            actual = (self.driver.execute_script(
                "return arguments[0].innerText || arguments[0].textContent;", textarea
            ) or "").strip()

            if not actual:
                logger.error("❌ Metin textarea'ya yazılamadı!")
                self._take_screenshot("text_insert_failed")
                return False

            logger.info(f"✅ Metin doğrulandı ({len(actual)} karakter)")

            # 5. Gönder
            if not self._click_send_button():
                logger.info("Gönder butonu bulunamadı/disabled → Enter deneniyor...")
                textarea.send_keys(Keys.RETURN)

            logger.info("✅ Mesaj gönderildi")
            self._human_delay(
                self.timeout_cfg.get("after_send", 3),
                self.timeout_cfg.get("after_send", 3) + 2,
            )
            return True

        except (TimeoutException, NoSuchElementException) as exc:
            logger.error(f"❌ Mesaj gönderilemedi: {exc}")
            self._take_screenshot("send_message_error")
            return False
        except ElementNotInteractableException as exc:
            logger.error(f"❌ Element ile etkileşim kurulamadı: {exc}")
            self._take_screenshot("element_not_interactable")
            return False

    def _click_send_button(self) -> bool:
        """Gönder butonunu bulur, disabled kontrolü yapar ve tıklar."""
        timeout = self.timeout_cfg.get("element_wait", 15)
        wait = WebDriverWait(self.driver, timeout)

        for selector in Selectors.SEND_BUTTON_SELECTORS:
            try:
                btn = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, selector)))
                is_disabled = btn.get_attribute("disabled")
                if is_disabled:
                    time.sleep(0.5)
                    if btn.get_attribute("disabled"):
                        logger.warning(f"⚠️  Gönder butonu disabled: {selector}")
                        continue
                wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, selector)))
                btn.click()
                logger.info(f"✅ Gönder butonu tıklandı: {selector}")
                return True
            except (TimeoutException, NoSuchElementException):
                continue

        logger.warning("⚠️  Gönder butonu hiçbir selektörle bulunamadı")
        return False

    def _wait_for_response(self) -> None:
        max_wait = self.timeout_cfg.get("response_wait", 120)
        logger.info(f"Claude yanıtı bekleniyor (max {max_wait}s)...")
        wait_start = WebDriverWait(self.driver, 10)
        wait_end = WebDriverWait(self.driver, max_wait)

        try:
            # Önce Stop butonunun çıkmasını bekle (en fazla 10sn)
            wait_start.until(EC.presence_of_element_located((By.CSS_SELECTOR, Selectors.STOP_BUTTON)))
            logger.info("↳ Claude yanıt yazıyor...")
            
            # Stop butonu çıktıysa, şimdi kaybolmasını bekle
            wait_end.until(EC.invisibility_of_element_located((By.CSS_SELECTOR, Selectors.STOP_BUTTON)))
            logger.info("✅ Claude yanıtı tamamlandı")
        except TimeoutException:
            # 10sn içinde Stop butonu hiç çıkmadıysa (ya hemen cevap bitti ya da buton selektörü değişti)
            logger.warning("⚠️  Stop butonu çıkmadı veya çok hızlı bitti. İşleme devam ediliyor...")
            self._human_delay(2, 4)

    # ── Yardımcılar ───────────────────────────────────────────

    def _take_screenshot(self, label: str) -> Optional[str]:
        if not self.driver:
            return None
            
        self._cleanup_old_screenshots()
        
        try:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = self.screenshot_dir / f"{label}_{ts}.png"
            self.driver.save_screenshot(str(filename))
            logger.info(f"📸 Screenshot: {filename}")
            return str(filename)
        except Exception as exc:
            logger.error(f"Screenshot alınamadı: {exc}")
            return None

    def _cleanup_old_screenshots(self, days: int = 7) -> None:
        """7 günden eski ekran görüntülerini temizler."""
        try:
            now = time.time()
            cutoff = now - (days * 86400)
            for f in self.screenshot_dir.glob("*.png"):
                if f.is_file() and f.stat().st_mtime < cutoff:
                    f.unlink()
                    logger.debug(f"Eski screenshot silindi: {f.name}")
        except Exception as exc:
            logger.warning(f"Screenshot temizliği başarısız: {exc}")

    @staticmethod
    def _human_delay(min_sec: float, max_sec: float) -> None:
        time.sleep(random.uniform(min_sec, max_sec))
