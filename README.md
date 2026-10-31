# Claude.ai Bot — Dashboard + Scheduler

Python tabanlı Claude.ai otomasyon botu. **FastAPI Web Dashboard** + **APScheduler** aynı process içinde çalışır. **Windows, macOS ve Linux** tam uyumludur.

---

## 📁 Proje Yapısı

```
claude-bot-dashboard/
├── src/
│   ├── bot.py          # Bot motoru (Windows, Mac, Linux stealth Chrome)
│   ├── scheduler.py    # APScheduler: cron, tek seferlik, tekrar deneme, atlama, duraklatma
│   ├── history.py      # Kalıcı çalışma geçmişi (SQLite)
│   ├── prompt_vars.py  # Prompt değişkenleri ({tarih}, {gün}, {a|b} …)
│   ├── config_store.py # config.yaml'ı yorumları koruyarak, atomik yazma
│   ├── session.py      # Cookie / localStorage yönetimi
│   ├── logger.py       # Rotating log + Web UI buffer
│   └── state.py        # Thread-safe paylaşılan durum (bot ↔ web)
├── web/
│   ├── app.py          # FastAPI fabrika + lifespan (scheduler başlatma)
│   ├── routes/
│   │   └── api.py      # REST API + SSE endpoint'leri
│   ├── templates/
│   │   └── index.html  # Dashboard iskeleti
│   └── static/
│       ├── css/app.css # Tasarım sistemi (açık/koyu tema)
│       └── js/app.js   # Dashboard istemcisi
├── config/
│   ├── config.example.yaml # Örnek konfigürasyon şablonu
│   └── config.yaml     # Kişisel ayarlarınız (.gitignore'da saklanır)
├── tests/              # pytest testleri
├── data/               # history.db — çalışma geçmişi (git'e gitmez)
├── sessions/           # Cookie + Chrome profil (git'e gitmez)
├── logs/               # Log dosyaları
├── screenshots/        # Hata ve başarı ekran görüntüleri
├── main.py             # Giriş noktası (Web UI / Run-once / Save-session)
├── requirements.txt    # Python bağımlılıkları
├── requirements-dev.txt # + test bağımlılıkları (pytest)
├── ecosystem.config.js # PM2 konfigürasyonu (Cross-platform)
├── setup.bat           # Windows tek tıkla otomatik kurulum
├── start.bat           # Windows tek tıkla başlatma
└── setup.sh            # Ubuntu VPS kurulum scripti
```

---

## 🚀 Hızlı Kurulum

Ön koşul: Bilgisayarınızda **Google Chrome** ve **Python 3.10, 3.11 veya 3.12** kurulu olmalıdır.

### 🪟 Windows Kurulumu

#### Yöntem 1 — Tek Tıkla Kurulum (Kolay):
Klasör içerisindeki `setup.bat` dosyasına çift tıklayın. Script otomatik olarak:
- Python sürümünü doğrular
- `venv` sanal ortamını oluşturur
- Bağımlılıkları kurar
- Klasör yapısını ve `config.yaml` şablonunu hazırlar

#### Yöntem 2 — Manuel Kurulum (Komut İstemi / CMD veya PowerShell):
```cmd
:: 1. Sanal ortamı oluştur ve aktif et
python -m venv venv
venv\Scripts\activate

:: 2. Bağımlılıkları yükle
python -m pip install --upgrade pip
pip install -r requirements.txt

:: 3. Konfigürasyon dosyasını oluştur
copy config\config.example.yaml config\config.yaml
```

---

### 🍎 macOS Kurulumu

```bash
# 1. Sanal ortamı oluştur ve aktif et
python3 -m venv venv
source venv/bin/activate

# 2. Bağımlılıkları yükle
pip install --upgrade pip
pip install -r requirements.txt

# 3. Konfigürasyon dosyasını oluştur
cp config/config.example.yaml config/config.yaml
```

*Google Chrome kurulu değilse:*
```bash
brew install --cask google-chrome
```

---

### 🐧 Linux (Ubuntu VPS) Kurulumu

Headless Linux sunucularda sanal ekran (Xvfb) gerektiğinden tek komutla kurulum scriptini kullanabilirsiniz:

```bash
chmod +x setup.sh
./setup.sh
```

---

## ⚙️ Konfigürasyon

`config/config.yaml` dosyasını Not Defteri veya tercih ettiğiniz bir kod editörüyle düzenleyin (veya Web Dashboard açıldıktan sonra arayüzden yapın):

```yaml
claude:
  base_url: https://claude.ai/chat
  chat_id: ''          # Global varsayılan sohbet ID (opsiyonel)
  prompt: ''

scheduler:
  jobs:
    - id: "sabah-raporu"
      cron: "0 9 * * 1-5"          # Hafta içi 09:00 (dakika saat gün ay haftanın-günü; 0=Pazar)
      enabled: true
      chat_id: "YOUR_CHAT_ID_HERE" # claude.ai/chat/<ID> adresindeki UUID
      prompt: "Bugün {gün}, {tarih}. {Günlük özeti|Kısa bir özet} hazırla."
      retries: 2                   # Hata olursa 2 kez daha dene
      retry_delay: 5               # Denemeler arası 5 dakika
    - id: "aksam-kontrol"
      cron: "0 18 * * *"           # Her gün 18:00
      enabled: true
      chat_id: "YOUR_CHAT_ID_HERE"
      prompt: "Yarım kalan görevleri gözden geçir ve tamamla."
  timezone: "Europe/Istanbul"
  paused: false                    # true → tüm zamanlanmış çalışmalar durur

history:
  db_path: ./data/history.db       # Kalıcı çalışma geçmişi

browser:
  headless: true                   # Arka planda gizli çalışması için true
  window_size:
    width: 1920
    height: 1080
```

**Prompt değişkenleri** — her çalışmada doldurulur: `{tarih}` (30.10.2026), `{gün}` (Cuma), `{saat}`, `{ay}`, `{yıl}`, `{dün}`, `{yarın}`. `{seçenek 1|seçenek 2}` her seferinde seçeneklerden birini rastgele seçer; düz süslü parantez için `{{` ve `}}` yazın. Tanınmayan `{…}` ifadeleri olduğu gibi bırakılır.

**Tekrar deneme** — yalnızca zamanlanmış, tekrar ve tek seferlik çalışmalarda uygulanır. Oturum hatalarında (giriş gerekli) tekrar denenmez, çünkü yeniden denemek sorunu çözmez.

Dashboard'dan kaydettiğinizde dosyadaki yorumlar korunur ve dosya atomik yazılır (yarıda kesilen bir kayıt `config.yaml`'ı bozmaz).

> **Önemli:** `config/config.yaml` kişisel sohbet ID'lerinizi içerdiği için `.gitignore` tarafından korunur ve Git reponuza yüklenmez.

---

## 🔐 İlk Kurulum: Oturum (Session) Kaydetme

Botun Cloudflare ve giriş engellerine takılmaması için **tek seferlik** tarayıcıda giriş yapıp session kaydedilir:

### Windows:
```cmd
venv\Scripts\activate
python main.py --save-session
```

### macOS / Linux:
```bash
source venv/bin/activate
python main.py --save-session
```

1. Chrome görünür modda açılır ve `claude.ai` sayfasına gider.
2. Claude hesabınıza manuel giriş yapın (Google ile veya e-posta ile).
3. Sohbet ekranını gördüğünüzde terminale geri dönün ve **ENTER** tuşuna basın.
4. Çerezler `sessions/claude_cookies.json` dosyasına şifrelenmeden yerel olarak kaydedilir. Artık bot otomatik çalışabilir!

---

## 🎯 Botu Çalıştırma

### 1. Web Dashboard + Scheduler (Normal Mod)

**Windows:**
`start.bat` dosyasına çift tıklayın veya CMD'de:
```cmd
venv\Scripts\activate
python main.py
```

**macOS / Linux:**
```bash
source venv/bin/activate
python main.py
```

Tarayıcınızdan **`http://localhost:8000`** adresine gidin.

### 2. Tek Seferlik Test Çalıştırması
Scheduler beklemeden botun mesaj gönderimini test etmek için (sonuç çalışma geçmişine de yazılır):
```bash
python main.py --run-once
```

### 3. Testler
```bash
pip install -r requirements-dev.txt
python -m pytest
```

---

## 🌐 Web Dashboard Özellikleri

| Bölüm | Açıklama |
|---|---|
| **Genel Bakış** | Duruma göre renk değiştiren canlı durum göstergesi, sonraki çalışmaya geri sayım, önümüzdeki 24 saatin zaman çizelgesi (atlanan, tek seferlik ve tekrar çalışmaları dahil), tüm zamanların başarı oranı |
| **Çalışma Takvimi** | Son 26 haftanın günlük ısı haritası ve kesintisiz başarı serisi |
| **Oturum Sağlığı** | `sessionKey` çerezinin bitişine kalan gün; yenileme zamanı yaklaşınca uyarı ve kopyalanabilir komut |
| **Son Çalışma** | Claude'un son yanıtı, ekran görüntüsü ve ayrıntılara geçiş |
| **Hızlı Eylemler** | "Şimdi Çalıştır", görev başına ▶ ve ⋯ menüsü: *bir kez planla*, *sıradakini atla / geri al*, *geçmişini gör*; tüm zamanlamayı tek tıkla **duraklat / sürdür** |
| **Geçmiş** | Kalıcı çalışma geçmişi; görev ve sonuca göre filtre. Her çalışmanın ayrıntısında Claude'un tam yanıtı (kopyalanabilir), gönderilen mesaj, hata, ekran görüntüsü ve o çalışmanın logları |
| **Canlı Loglar** | SSE ile gerçek zamanlı akış; seviye filtresi, arama ve vurgulama, duraklatma, `.log` olarak indirme |
| **Görevler** | Saat + gün seçici ile cron'suz zamanlama, prompt değişkenleri ve canlı önizleme, tekrar deneme ayarı, chat URL'si yapıştırınca ID'yi otomatik ayıklama, kaydedilmemiş değişiklik çubuğu (`⌘/Ctrl+S`) |
| **Galeri** | Duruma göre filtrelenen, güne göre gruplanan ekran görüntüleri; klavyeyle gezilebilen tam ekran görüntüleyici |
| **Komut Paleti** | `⌘K` / `Ctrl+K` ile her yere ve her eyleme erişim; `1`–`5` ile bölümler arası geçiş |
| **Tema** | Açık, koyu ve sistem teması; mobilde alt sekme çubuğu |

---

## 🔄 7/24 Arka Planda Kesintisiz Çalıştırma

### 🪟 Windows için Arka Plan Çalıştırma

#### Seçenek A — PM2 ile Çalıştırma:
Node.js kurulu ise:
```cmd
npm install -g pm2
pm2 start ecosystem.config.js
pm2 save
```

#### Seçenek B — Windows Görev Zamanlayıcısı (Task Scheduler):
1. `Win + R` basıp `taskschd.msc` yazın.
2. **Temel Görev Oluştur** seçeneğine tıklayın.
3. Tetikleyici olarak **Bilgisayar başladığında** veya **Kullanıcı oturum açtığında** seçin.
4. Eylem olarak **Program başlat**:
   - Program: `C:\...\bot-claude\venv\Scripts\python.exe`
   - Bağımsız değişkenler: `main.py`
   - Başlangıç yeri: `C:\...\bot-claude`
5. Kaydedin.

#### ⚠️ Windows'un Uyumasını Engelleme:
Bilgisayar uyku moduna geçerse zamanlanmış bot görevleri çalışamaz.
- **Ayarlar** → **Sistem** → **Güç ve Uyku** bölümünden:
  - "Prize takılıyken şu süre sonunda uyku moduna geç:" ayarını **Hiçbir zaman** olarak ayarlayın.

---

### 🍎 macOS için Arka Plan Çalıştırma

```bash
# PM2 ile başlatma
pm2 start ecosystem.config.js
pm2 startup
pm2 save
```

#### ⚠️ Mac'in Uyumasını Engelleme:
```bash
# caffeinate ile uyanık tutarak PM2 çalıştırma
caffeinate -i pm2 start ecosystem.config.js
```

---

## 🐛 Sık Karşılaşılan Sorunlar ve Çözümleri

| Sorun | Neden | Çözüm |
|---|---|---|
| `Session dosyası bulunamadı` | İlk oturum kaydedilmemiş | `python main.py --save-session` komutunu çalıştırıp giriş yapın. |
| `Oturum geçersiz / login required` | Claude çerezlerinin süresi dolmuş | Yeniden `python main.py --save-session` çalıştırın. |
| `cannot connect to chrome / version mismatch` | Chrome güncellenmiş | Bot sürümü otomatik algılar; gerekirse `config.yaml` içindeki `browser.version_main` satırını kontrol edin. |
| `Textarea bulunamadı` | Claude.ai arayüz selektörleri değişmiş | `src/bot.py` içindeki `Selectors` sınıfını güncelleyin. |
| Windows'ta `ExecutionPolicy` hatası | PowerShell script çalıştırma kısıtı | `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` komutunu girin veya `setup.bat` / CMD kullanın. |
| Port 8000 meşgul | Başka bir servis portu kullanıyor | `python main.py --port 8080` ile farklı portta başlatın. |

---

## 📦 Temel Kütüphaneler

- **[undetected-chromedriver](https://github.com/ultrafunkamsterdam/undetected-chromedriver)** — Cloudflare & Bot tespit bypass motoru
- **[Selenium](https://www.selenium.dev/)** — Web otomasyon ve element yönetimi
- **[APScheduler](https://apscheduler.readthedocs.io/)** — Cron tabanlı asenkron arka plan görev zamanlayıcısı
- **[FastAPI](https://fastapi.tiangolo.com/)** & **[Uvicorn](https://www.uvicorn.org/)** — Yüksek performanslı web dashboard sunucusu
- **[PyYAML](https://pyyaml.org/)** & **[Pydantic](https://docs.pydantic.dev/)** — Tip güvenli yapılandırma ve API doğrulama

---

## 🔒 Güvenlik Notu

- Oturum çerezleri (`sessions/`) ve konfigürasyon (`config/config.yaml`) dosyalarınız hassas veriler içerir. Bu klasörler varsayılan olarak `.gitignore` dosyasında listelenmiştir.
- Web Dashboard'u yerel ağınız dışına (`--host 0.0.0.0`) açacaksanız önünde mutlaka parola korumalı bir ters vekil sunucu (Nginx / Cloudflare Tunnel) konumlandırın.
