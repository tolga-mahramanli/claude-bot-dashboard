# Claude.ai Bot — Dashboard + Scheduler (v2)

Python tabanlı Claude.ai otomasyon botu. **FastAPI Web Dashboard** + **APScheduler** aynı process içinde çalışır. Mac için optimize edilmiştir.

---

## 📁 Proje Yapısı

```
bot-claude/
├── src/
│   ├── bot.py          # Bot motoru (Mac + Ubuntu stealth Chrome)
│   ├── scheduler.py    # APScheduler BackgroundScheduler
│   ├── session.py      # Cookie / localStorage yönetimi
│   ├── logger.py       # Rotating log + Web UI buffer
│   └── state.py        # Thread-safe paylaşılan durum (bot ↔ web)
├── web/
│   ├── app.py          # FastAPI fabrika + lifespan (scheduler başlatma)
│   ├── routes/
│   │   └── api.py      # REST API + SSE endpoint'leri
│   └── templates/
│       └── index.html  # Tek sayfalık premium dashboard
├── config/
│   └── config.yaml     # Tüm ayarlar
├── sessions/           # Cookie + Chrome profil (git'e gitmiyor)
├── logs/               # Rotating log dosyaları
├── screenshots/        # Hata ekran görüntüleri
├── main.py             # Giriş noktası (3 mod)
├── requirements.txt    # Python bağımlılıkları
├── ecosystem.config.js # PM2 konfigürasyonu (Mac uyumlu)
└── setup.sh            # Ubuntu VPS kurulum scripti
```

---

## 🚀 Kurulum (Mac)

### 1. Python sanal ortamı

```bash
cd bot-claude
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Google Chrome kurulu olmalı

Mac'te Chrome `--headless=new` ile çalışır; **Xvfb gerekmez**.

```bash
# Chrome kurulu değilse:
brew install --cask google-chrome
```

### 3. PM2 kurulumu (opsiyonel, 7/24 çalışma için)

```bash
# Node.js kurulu değilse:
brew install node

npm install -g pm2
```

---

## ⚙️ Konfigürasyon

Önce örnek dosyadan kendi config'inizi oluşturun (`config.yaml` git'e gönderilmez):

```bash
cp config/config.example.yaml config/config.yaml
```

Ardından `config/config.yaml` dosyasını düzenleyin **veya** Web Dashboard'dan yapın:

```yaml
claude:
  chat_id: "YOUR_CHAT_ID_HERE"   # claude.ai/chat/<ID>
  prompt: |
    Merhaba! Bu otomatik bir mesajdır.

scheduler:
  jobs:
    - id: "sabah"
      cron: "0 9 * * *"       # Her gün 09:00
      enabled: true
    - id: "aksam"
      cron: "0 18 * * *"      # Her gün 18:00
      enabled: true
  timezone: "Europe/Istanbul"

browser:
  headless: true               # Mac'te true yeterli, Xvfb gerekmez
```

---

## 🔐 İlk Kurulum: Session Kaydetme

**Tek seferlik** — Bot her çalışmada cookie'yi dosyadan okur.

```bash
source venv/bin/activate
python main.py --save-session
```

1. Chrome açılır (görünür modda)
2. claude.ai'ye **manuel giriş** yapın
3. Terminal'e dönüp **Enter**'a basın
4. Session → `sessions/claude_cookies.json` olarak kaydedilir

---

## 🎯 Çalıştırma

### Geliştirme / Test

```bash
source venv/bin/activate

# Önce bir kez test et
python main.py --run-once

# Web UI + Scheduler başlat
python main.py
# → http://localhost:8000
```

### PM2 ile 7/24 Arka Plan

```bash
# Başlat
pm2 start ecosystem.config.js

# Sistem başlangıcında otomatik başlat (Mac)
pm2 startup
# ↑ Çıktısındaki komutu kopyalayıp çalıştırın
pm2 save

# Durumu izle
pm2 status
pm2 logs claude-bot --lines 50

# Yeniden başlat / durdur
pm2 restart claude-bot
pm2 stop claude-bot
```

### Mac'in Uyumasını Engelleme

PM2 arka planda çalışırken Mac'in uyuması görevlerin kaçırılmasına yol açabilir.

**Yöntem 1 — caffeinate (tavsiye edilen):**
```bash
# PM2'yi caffeinate ile sar
caffeinate -i pm2 start ecosystem.config.js

# Veya mevcut PM2 process'ini uyanık tut
caffeinate -w $(pgrep -f "pm2")
```

**Yöntem 2 — Sistem Tercihleri:**
Sistem Tercihleri → Enerji Tasarrufu → "Bilgisayarın otomatik olarak uyumasını engelle" seçeneğini açın.

**Yöntem 3 — launchd (en sağlam):**
```bash
# ~/Library/LaunchAgents/com.claudebot.plist oluşturun
# (README'nin sonundaki örneği kullanın)
```

---

## 🌐 Web Dashboard

`http://localhost:8000` adresine gidin.

| Sekme | Özellik |
|-------|---------|
| **Genel Bakış** | Bot durumu, istatistikler, sonraki çalışma, hızlı eylemler |
| **Loglar** | SSE ile canlı log akışı, otomatik kaydırma |
| **Konfigürasyon** | chat_id, prompt, cron zamanlamaları — kaydet & uygula |
| **Screenshot** | Son hata ekran görüntüsü |

### API Endpoint'leri

| Method | URL | Açıklama |
|--------|-----|----------|
| `GET`  | `/api/status` | Bot durumu + istatistik |
| `GET`  | `/api/config` | Mevcut config'i oku |
| `POST` | `/api/config` | Config güncelle + scheduler reload |
| `GET`  | `/api/logs` | Son N log satırı (`?n=100`) |
| `GET`  | `/api/logs/stream` | SSE canlı log akışı |
| `GET`  | `/api/screenshot` | Son screenshot (base64) |
| `POST` | `/api/run-now` | Anında bot görevi tetikle |
| `GET`  | `/api/jobs` | APScheduler job listesi |
| `GET`  | `/docs` | Swagger UI |

---

## 🏗️ Mimari

```
main.py (uvicorn)
│
├── FastAPI lifespan
│   ├── APScheduler (BackgroundScheduler) ──┐
│   │   └── CronTrigger → run_bot_job()     │
│   └── HTTP Routes                          │
│       ├── GET  /          (dashboard)      │
│       └── /api/*          (REST + SSE)     │
│                                            │
├── ClaudeBot.run_task() ←──────────────────┘
│   ├── undetected_chromedriver (stealth)
│   ├── SessionManager (cookie load/save)
│   └── WebDriverWait (DOM interaction)
│
└── BotState (thread-safe singleton)
    ├── bot.py yazar
    └── api.py okur → SSE / JSON
```

---

## 🐛 Sorun Giderme

| Sorun | Çözüm |
|-------|-------|
| `Session yok` | `python main.py --save-session` |
| `Login sayfası tespit edildi` | Session süresi dolmuş, yeniden `--save-session` |
| `Textarea bulunamadı` | `src/bot.py` → `Selectors` sınıfını güncelle |
| Chrome başlamıyor | `brew install --cask google-chrome` |
| Dashboard açılmıyor | `python main.py` çalışıyor mu? Port 8000 meşgul mü? |
| PM2 `ERRORED` | `pm2 logs claude-bot --err` |
| Mac uyudu, görev kaçtı | `caffeinate` kullan (yukarıdaki bölüm) |

---

## 📦 Bağımlılıklar

| Paket | Amaç |
|-------|------|
| `undetected-chromedriver` | Cloudflare bypass stealth driver |
| `selenium` | WebDriver, WebDriverWait |
| `APScheduler` | BackgroundScheduler cron yönetimi |
| `fastapi` | REST API + SSE web sunucusu |
| `uvicorn` | ASGI sunucusu |
| `jinja2` | HTML şablon motoru |
| `pydantic` | API veri doğrulama |
| `PyYAML` | Konfigürasyon okuma/yazma |

---

## 🔒 Güvenlik

```bash
# Session dosyalarını koru
chmod 600 sessions/*.json sessions/chrome_profile

# .gitignore — sessions/ ve logs/ commit edilmez
cat .gitignore
```

> Dashboard'u dışarıdan erişime açmak istiyorsanız `--host 0.0.0.0` kullanın
> ve mutlaka bir reverse proxy (nginx) + temel kimlik doğrulama ekleyin.

---

## 🍎 launchd ile Mac Başlangıcı (İleri Seviye)

`~/Library/LaunchAgents/com.claudebot.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>          <string>com.claudebot</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/caffeinate</string>
    <string>-i</string>
    <string>/path/to/venv/bin/python</string>
    <string>/path/to/bot-claude/main.py</string>
  </array>
  <key>WorkingDirectory</key> <string>/path/to/bot-claude</string>
  <key>RunAtLoad</key>         <true/>
  <key>KeepAlive</key>         <true/>
  <key>StandardOutPath</key>   <string>/path/to/bot-claude/logs/launchd_out.log</string>
  <key>StandardErrorPath</key> <string>/path/to/bot-claude/logs/launchd_err.log</string>
</dict>
</plist>
```

```bash
launchctl load ~/Library/LaunchAgents/com.claudebot.plist
launchctl start com.claudebot
```
