"""
bot.py - Ana Bot Motoru (v3 - per-job chat_id + prompt desteği)
Cloudflare bypass + stealth Chrome + Claude.ai otomasyon
"""

import os
import platform
import re
import subprocess
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

IS_MAC     = platform.system() == "Darwin"
IS_WINDOWS = platform.system() == "Windows"

MAC_CHROME_PATHS = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
]


def _windows_chrome_paths() -> list:
    """Windows'ta Chrome'un standart kurulum konumları (sistem + kullanıcı bazlı)."""
    paths = []
    for env in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
        base = os.environ.get(env)
        if base:
            paths.append(str(Path(base) / "Google" / "Chrome" / "Application" / "chrome.exe"))
    return paths


def find_chrome_binary() -> str:
    """Mac/Windows'ta Chrome'u standart konumlarda arar; Linux'ta PATH'e bırakılır."""
    candidates = MAC_CHROME_PATHS if IS_MAC else _windows_chrome_paths() if IS_WINDOWS else []
    for p in candidates:
        if Path(p).exists():
            return p
    return ""


def _detect_chrome_major_windows(chrome_bin: str = "") -> Optional[int]:
    """
    Windows'ta `chrome.exe --version` çıktı vermez (hatta pencere açabilir).
    Sürümü önce registry'den, olmazsa kurulum klasöründeki sürüm dizininden okur.
    """
    import winreg  # yalnızca Windows'ta mevcut

    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            with winreg.OpenKey(hive, r"Software\Google\Chrome\BLBeacon") as key:
                version, _ = winreg.QueryValueEx(key, "version")
                return int(str(version).split(".")[0])
        except (OSError, ValueError):
            continue

    # Yedek: ...\Chrome\Application\156.0.8078.76\ gibi sürüm klasörü
    for exe in ([chrome_bin] if chrome_bin else []) + _windows_chrome_paths():
        app_dir = Path(exe).parent
        if not app_dir.is_dir():
            continue
        versions = [
            int(d.name.split(".")[0]) for d in app_dir.iterdir()
            if d.is_dir() and re.fullmatch(r"\d+\.\d+\.\d+\.\d+", d.name)
        ]
        if versions:
            return max(versions)
    return None


def detect_chrome_major(chrome_bin: str = "") -> Optional[int]:
    """
    Kurulu Chrome'un ana sürümünü (ör. 156) döndürür; bulunamazsa None.
    Chrome otomatik güncellendiğinde sabit version_main ChromeDriver'ı kırar.
    """
    if IS_WINDOWS:
        return _detect_chrome_major_windows(chrome_bin)

    candidates = [chrome_bin] if chrome_bin else []
    candidates += MAC_CHROME_PATHS if IS_MAC else [
        "google-chrome", "google-chrome-stable", "chromium", "chromium-browser",
    ]
    for binary in candidates:
        try:
            out = subprocess.run(
                [binary, "--version"], capture_output=True, text=True, timeout=10,
            ).stdout
        except (OSError, subprocess.SubprocessError):
            continue
        match = re.search(r"(\d+)\.\d+\.\d+", out)
        if match:
            return int(match.group(1))
    return None


def resolve_chrome_version(browser_cfg: dict, chrome_bin: str = "") -> Optional[int]:
    """Config'de version_main varsa onu, yoksa otomatik algılananı kullanır."""
    configured = browser_cfg.get("version_main")
    if configured:
        return int(configured)
    detected = detect_chrome_major(chrome_bin)
    if detected:
        logger.info(f"Kurulu Chrome sürümü algılandı: {detected}")
    else:
        logger.warning("⚠️  Chrome sürümü algılanamadı; undetected_chromedriver'a bırakılıyor")
    return detected


def resolve_cached_driver(chrome_version: Optional[int]) -> Optional[str]:
    """
    Daha önce indirilip patch'lenmiş ve ana sürümü uyuşan chromedriver varsa
    yolunu döndürür. Böylece her görevde GitHub'dan tekrar indirme yapılmaz
    ve geçici DNS/ağ kesintilerinde (Errno 8) görev çökmez.
    """
    try:
        patcher = uc.Patcher(version_main=chrome_version)
        exe_path = Path(patcher.executable_path)
        if not exe_path.exists():
            return None
        if not patcher.is_binary_patched(str(exe_path)):
            return None
        if chrome_version:
            out = subprocess.run(
                [str(exe_path), "--version"],
                capture_output=True, text=True, timeout=5,
            ).stdout
            match = re.search(r"ChromeDriver\s+(\d+)\.", out)
            if not match or int(match.group(1)) != chrome_version:
                return None
        return str(exe_path)
    except Exception:
        return None


def cleanup_stale_profile_locks(user_data_dir: str) -> None:
    """
    Önceki Chrome sürecinden kalan ölü/zombie SingletonLock dosyalarını temizler.
    """
    if IS_WINDOWS:
        return
    profile = Path(user_data_dir)
    lock_file = profile / "SingletonLock"
    if not (lock_file.is_symlink() or lock_file.exists()):
        return

    stale = False
    try:
        target = os.readlink(lock_file)
        match = re.search(r"-(\d+)$", target)
        if match:
            pid = int(match.group(1))
            try:
                os.waitpid(pid, os.WNOHANG)
            except OSError:
                pass
            try:
                os.kill(pid, 0)
                stat_out = subprocess.run(
                    ["ps", "-o", "stat=", "-p", str(pid)],
                    capture_output=True, text=True, timeout=3,
                ).stdout.strip()
                if not stat_out or stat_out.startswith("Z"):
                    stale = True
            except OSError:
                stale = True
    except OSError:
        stale = True

    if stale:
        for name in ("SingletonLock", "SingletonSocket", "SingletonCookie"):
            p = profile / name
            try:
                if p.is_symlink() or p.exists():
                    p.unlink()
            except OSError:
                pass
        logger.debug("Eski Chrome profil kilidi (SingletonLock) temizlendi")


# ────────────────────────────────────────────────────────────────
# Claude.ai DOM Selektörleri (Hibrit: İngilizce + Türkçe + Genel)
# ────────────────────────────────────────────────────────────────
class Selectors:
    TEXTAREA_SELECTORS = [
        'div.ProseMirror[contenteditable="true"]',
        'div[contenteditable="true"][data-placeholder]',
        'div[contenteditable="true"]',
        'p[data-placeholder]',
    ]
    SEND_BUTTON_SELECTORS = [
        # İngilizce
        'button[aria-label="Send message"]',
        'button[aria-label="Send Message"]',
        'button[aria-label*="Send" i]',
        # Türkçe
        'button[aria-label="Mesaj gönder"]',
        'button[aria-label="Mesajı gönder"]',
        'button[aria-label="Gönder"]',
        'button[aria-label*="gönder" i]',
        # Dil bağımsız
        'button[data-testid="send-button"]',
        'button[type="submit"]',
    ]
    STOP_BUTTON = (
        'button[aria-label="Stop Response"], '
        'button[aria-label="Stop response"], '
        'button[aria-label="Stop"], '
        'button[aria-label="Yanıtı durdur"], '
        'button[aria-label="Durdur"], '
        'button[data-testid="stop-button"]'
    )
    PAGE_LOADED     = 'div[class*="conversation"], main'
    LOGIN_INDICATOR = 'button[data-testid="login-with-google"], a[href*="/login"], input[type="email"]'


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

        # User-Agent burada sabitlenmez; driver açıldıktan sonra gerçek
        # Chrome sürümüne göre CDP ile ayarlanır (bkz. _apply_user_agent).

        w = self.browser_cfg.get("window_size", {}).get("width",  1440)
        h = self.browser_cfg.get("window_size", {}).get("height", 900)
        options.add_argument(f"--window-size={w},{h}")

        user_data_dir = self.browser_cfg.get("user_data_dir", "./sessions/chrome_profile")
        Path(user_data_dir).mkdir(parents=True, exist_ok=True)
        cleanup_stale_profile_locks(user_data_dir)
        options.add_argument(f"--user-data-dir={os.path.abspath(user_data_dir)}")

        proxy = self.browser_cfg.get("proxy", "")
        if proxy:
            options.add_argument(f"--proxy-server={proxy}")

        chrome_bin = self.browser_cfg.get("chrome_binary", "") or find_chrome_binary()
        if chrome_bin:
            options.binary_location = chrome_bin

        chrome_version = resolve_chrome_version(self.browser_cfg, chrome_bin)
        cached_driver = resolve_cached_driver(chrome_version)
        logger.info(f"Driver başlatılıyor (platform={platform.system()}, headless={self.browser_cfg.get('headless', True)})")
        driver = uc.Chrome(
            options=options,
            use_subprocess=True,
            version_main=chrome_version,
            driver_executable_path=cached_driver,
        )

        self._apply_user_agent(driver)
        driver.execute_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )
        logger.info("✅ Driver hazır")
        return driver

    @staticmethod
    def _apply_user_agent(driver: uc.Chrome) -> None:
        """
        UA + Client Hints'i çalışan Chrome'un gerçek sürümüyle eşleştirir.
        Sabit bir sürüm (ör. Chrome/126) kurulu tarayıcıyla çelişip tespit
        riskini artırır; headless modda ise 'HeadlessChrome' ibaresini gizler.
        """
        full_version = driver.capabilities.get("browserVersion", "") or "0.0.0.0"
        major = full_version.split(".")[0]
        if IS_MAC:
            platform_token, ch_platform = "Macintosh; Intel Mac OS X 10_15_7", "macOS"
        elif IS_WINDOWS:
            platform_token, ch_platform = "Windows NT 10.0; Win64; x64", "Windows"
        else:
            platform_token, ch_platform = "X11; Linux x86_64", "Linux"
        ua = (
            f"Mozilla/5.0 ({platform_token}) AppleWebKit/537.36 "
            f"(KHTML, like Gecko) Chrome/{major}.0.0.0 Safari/537.36"
        )
        driver.execute_cdp_cmd("Network.setUserAgentOverride", {
            "userAgent": ua,
            "userAgentMetadata": {
                "brands": [
                    {"brand": "Google Chrome", "version": major},
                    {"brand": "Chromium",      "version": major},
                    {"brand": "Not=A?Brand",   "version": "24"},
                ],
                "fullVersion":     full_version,
                "platform":        ch_platform,
                "platformVersion": "",
                "architecture":    "",
                "model":           "",
                "mobile":          False,
            },
        })
        logger.info(f"User-Agent ayarlandı: Chrome/{major} ({full_version})")

    def _close_driver(self) -> None:
        if self.driver:
            browser_pid = getattr(self.driver, "browser_pid", None)
            try:
                self.driver.quit()
                logger.info("Driver kapatıldı")
            except Exception:
                pass
            finally:
                self.driver = None
                if browser_pid and not IS_WINDOWS:
                    for _ in range(10):
                        try:
                            pid, _ = os.waitpid(browser_pid, os.WNOHANG)
                            if pid != 0:
                                break
                        except OSError:
                            break
                        time.sleep(0.05)

    # ── Session ───────────────────────────────────────────────

    def _is_logged_in(self) -> bool:
        try:
            current_url = self.driver.current_url or ""
            if "/login" in current_url:
                logger.warning("⚠️  Login sayfası tespit edildi (URL)!")
                return False
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

            had_cookie_file = self.session_manager.session_exists()
            if had_cookie_file:
                self.session_manager.load_session(self.driver, target_url)
            else:
                logger.warning("⚠️  Cookie dosyası bulunamadı; Chrome profilindeki oturum kontrol ediliyor...")

            logger.info(f"Sayfaya gidiliyor: {target_url}")
            self.driver.get(target_url)
            self._human_delay(2, 4)

            if not self._is_logged_in():
                if not had_cookie_file:
                    logger.error("❌ Session dosyası bulunamadı ve Chrome profilinde açık oturum yok!")
                    bot_state.set_no_session()
                    return False
                logger.error("❌ Oturum açılmamış!")
                ss = self._take_screenshot("login_required")
                bot_state.set_error("Oturum geçersiz - yeniden login gerekiyor", ss)
                return False

            if not had_cookie_file:
                logger.info("✅ Chrome profilinden aktif oturum kurtarıldı, session dosyası kaydediliyor...")
                try:
                    self.session_manager.save_session(self.driver)
                except Exception as save_exc:
                    logger.warning(f"⚠️  Kurtarılan session diske yazılamadı: {save_exc}")

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
        """Textarea'yı birden fazla selektörle tek bekleme döngüsünde arar."""
        timeout = self.timeout_cfg.get("element_wait", 20)

        def _locate_any(driver):
            for selector in Selectors.TEXTAREA_SELECTORS:
                for el in driver.find_elements(By.CSS_SELECTOR, selector):
                    try:
                        if not (el.is_displayed() and el.is_enabled()):
                            continue
                        ce = el.get_attribute("contenteditable")
                        if ce in ("true", "plaintext-only", None):
                            logger.debug(f"Textarea bulundu: {selector}")
                            return el
                    except Exception:
                        continue
            return False

        try:
            return WebDriverWait(self.driver, timeout).until(_locate_any)
        except TimeoutException:
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
        """Gönder butonunu (TR/EN/genel) tek döngüde arar, aktifse tıklar."""
        def _locate_clickable_btn(driver):
            for selector in Selectors.SEND_BUTTON_SELECTORS:
                for btn in driver.find_elements(By.CSS_SELECTOR, selector):
                    try:
                        if not btn.is_displayed():
                            continue
                        if btn.get_attribute("disabled") or btn.get_attribute("aria-disabled") == "true":
                            continue
                        return selector, btn
                    except Exception:
                        continue
            return False

        try:
            selector, btn = WebDriverWait(self.driver, 3).until(_locate_clickable_btn)
            btn.click()
            logger.info(f"✅ Gönder butonu tıklandı: {selector}")
            return True
        except TimeoutException:
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
