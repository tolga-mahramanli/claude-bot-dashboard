// ============================================================
// PM2 Ecosystem - Cross-Platform (Windows, Mac, Linux)
// Kullanım: pm2 start ecosystem.config.js
// ============================================================

module.exports = {
  apps: [
    {
      name: "claude-bot",
      script: "main.py",
      interpreter: process.platform === "win32" ? "python" : "python3",

      // ── Mac Ortam Değişkenleri ───────────────────────────
      // Mac'te Xvfb gerekmez; headless=true yeterli.
      // Chrome, sistem PATH'inden otomatik bulunur.
      env: {
        PYTHONUNBUFFERED: "1",   // Log'ların anında yazılması için
        PYTHONPATH: ".",          // src/ ve web/ modüllerinin bulunması için
        // Mac'te DISPLAY ayarı GEREKMEZ (Xvfb kullanılmaz)
        // DISPLAY: ":99"  ← Ubuntu-only, Mac'te bu satırı kullanmayın
        LANG: "tr_TR.UTF-8",
        LC_ALL: "tr_TR.UTF-8",
      },

      // ── Yeniden Başlatma Politikası ──────────────────────
      autorestart: true,
      max_restarts: 10,
      min_uptime: "30s",
      restart_delay: 5000,

      // ── Log Yönetimi ─────────────────────────────────────
      log_date_format: "YYYY-MM-DD HH:mm:ss",
      out_file: "./logs/pm2_out.log",
      error_file: "./logs/pm2_error.log",
      merge_logs: true,

      // ── Kaynak Limitleri ─────────────────────────────────
      max_memory_restart: "768M",

      // ── Mod ─────────────────────────────────────────────
      exec_mode: "fork",
      instances: 1,

      // ── Graceful Kapatma ─────────────────────────────────
      kill_timeout: 10000,

      // ── Mac-Specific: caffeinate ile uyutmayı engelle ────
      // PM2 bu komutu çalıştırmaz; README'deki talimatı takip edin.

      // ── Hot-reload (geliştirme için, prod'da kapalı) ─────
      watch: false,
    },
  ],
};
