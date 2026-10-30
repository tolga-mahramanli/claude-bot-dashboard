#!/bin/bash
# ============================================================
# Ubuntu VPS - Kurulum Scripti
# Tek komutla tüm bağımlılıkları kurar ve botu yapılandırır
# Kullanım: chmod +x setup.sh && ./setup.sh
# ============================================================

set -e  # Hata durumunda dur

# Renkli çıktı
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log()     { echo -e "${GREEN}[+]${NC} $1"; }
warn()    { echo -e "${YELLOW}[!]${NC} $1"; }
error()   { echo -e "${RED}[✗]${NC} $1"; exit 1; }
section() { echo -e "\n${BLUE}══ $1 ══${NC}"; }

# ── Kök kontrolü ──────────────────────────────────────────────
if [[ $EUID -eq 0 ]]; then
  warn "Root olarak çalıştırılıyor. sudo gerekiyorsa scriptler bunu halleder."
fi

section "Sistem Güncellemesi"
sudo apt-get update -qq
sudo apt-get upgrade -y -qq
log "Sistem güncellendi"

# ── Python 3.11+ ──────────────────────────────────────────────
section "Python Kurulumu"
sudo apt-get install -y -qq python3 python3-pip python3-venv python3-dev
PYTHON_VER=$(python3 --version 2>&1)
log "Python: $PYTHON_VER"

# ── Google Chrome ─────────────────────────────────────────────
section "Google Chrome Kurulumu"
if ! command -v google-chrome &> /dev/null; then
    wget -q https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb -O /tmp/chrome.deb
    sudo apt-get install -y -qq /tmp/chrome.deb
    rm /tmp/chrome.deb
    log "Chrome kuruldu: $(google-chrome --version)"
else
    log "Chrome zaten kurulu: $(google-chrome --version)"
fi

# ── Xvfb (Virtual Display - Headless için gerekli) ────────────
section "Xvfb Virtual Display"
sudo apt-get install -y -qq xvfb x11-utils

# Xvfb systemd servisini oluştur
sudo tee /etc/systemd/system/xvfb.service > /dev/null << 'EOF'
[Unit]
Description=Xvfb Virtual Display
After=network.target

[Service]
ExecStart=/usr/bin/Xvfb :99 -screen 0 1920x1080x24 -ac +extension GLX +render -noreset
Restart=always
RestartSec=3
Environment="DISPLAY=:99"

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable xvfb
sudo systemctl start xvfb
log "Xvfb servisi başlatıldı (DISPLAY=:99)"

# ── Node.js ve PM2 ────────────────────────────────────────────
section "Node.js ve PM2 Kurulumu"
if ! command -v node &> /dev/null; then
    curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
    sudo apt-get install -y -qq nodejs
    log "Node.js: $(node --version)"
fi

if ! command -v pm2 &> /dev/null; then
    sudo npm install -g pm2 --silent
    log "PM2 kuruldu: $(pm2 --version)"
else
    log "PM2 zaten kurulu: $(pm2 --version)"
fi

# ── Python Virtual Environment ────────────────────────────────
section "Python Sanal Ortamı"
if [ ! -d "venv" ]; then
    python3 -m venv venv
    log "venv oluşturuldu"
fi

source venv/bin/activate
pip install --upgrade pip -q
pip install -r requirements.txt -q
log "Python bağımlılıkları kuruldu"

# ── Dizin yapısını oluştur ────────────────────────────────────
section "Dizin Yapısı"
mkdir -p logs screenshots sessions/chrome_profile
log "Dizinler oluşturuldu: logs/ screenshots/ sessions/"

# ── .gitignore ────────────────────────────────────────────────
cat > .gitignore << 'EOF'
venv/
__pycache__/
*.pyc
*.pyo
sessions/
logs/
screenshots/
.env
*.log
EOF
log ".gitignore oluşturuldu"

# ── PM2 startup ───────────────────────────────────────────────
section "PM2 Startup Konfigürasyonu"
sudo env PATH=$PATH:/usr/bin pm2 startup systemd -u $USER --hp $HOME
log "PM2 sistem başlangıcında otomatik başlayacak"

# ── Özet ──────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}╔══════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║       Kurulum Başarıyla Tamamlandı!          ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════╝${NC}"
echo ""
echo "Sonraki adımlar:"
echo ""
echo -e "  ${YELLOW}1.${NC} config/config.yaml dosyasını düzenleyin:"
echo "     - chat_id'yi ayarlayın"
echo "     - prompt'u ayarlayın"
echo "     - cron zamanlamalarını ayarlayın"
echo ""
echo -e "  ${YELLOW}2.${NC} İlk kez session kaydedin:"
echo "     source venv/bin/activate"
echo "     python main.py --save-session"
echo ""
echo -e "  ${YELLOW}3.${NC} Test edin:"
echo "     python main.py --run-once"
echo ""
echo -e "  ${YELLOW}4.${NC} PM2 ile başlatın:"
echo "     pm2 start ecosystem.config.js"
echo "     pm2 save"
echo ""
echo -e "  ${YELLOW}5.${NC} Logları izleyin:"
echo "     pm2 logs claude-bot"
echo ""
