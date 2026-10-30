@echo off
chcp 65001 >nul
echo ============================================================
echo   Claude.ai Bot - Windows Kurulum Scripti
echo ============================================================
echo.

where python >nul 2>nul
if %ERRORLEVEL% neq 0 (
    echo [HATA] Python bulunamadi!
    echo Lutfen Python 3.10, 3.11 veya 3.12 kurun ve kurulum sirasinda
    echo "Add python.exe to PATH" secenegini isaretlediginizden emin olun.
    echo https://www.python.org/downloads/
    echo.
    pause
    exit /b 1
)

echo [+] Python bulundu.
echo [+] Python sanal ortami (venv) olusturuluyor...
if not exist "venv" (
    python -m venv venv
    if %ERRORLEVEL% neq 0 (
        echo [HATA] venv olusturulamadi!
        pause
        exit /b 1
    )
    echo [+] venv olusturuldu.
) else (
    echo [*] venv zaten mevcut.
)

echo [+] Sanal ortam aktif ediliyor...
call venv\Scripts\activate.bat

echo [+] Pip guncelleniyor...
python -m pip install --upgrade pip -q

echo [+] Bagimliliklar yukleniyor (bu islem 1-2 dakika surebilir)...
pip install -r requirements.txt -q
if %ERRORLEVEL% neq 0 (
    echo [HATA] Bagimliliklar yuklenirken bir sorun olustu.
    pause
    exit /b 1
)
echo [+] Tum bagimliliklar basariyla kuruldu.

echo [+] Gerekli klasorler olusturuluyor...
if not exist "logs" mkdir logs
if not exist "screenshots" mkdir screenshots
if not exist "sessions" mkdir sessions
if not exist "sessions\chrome_profile" mkdir sessions\chrome_profile

if not exist "config\config.yaml" (
    echo [+] config.example.yaml -> config.yaml kopyalaniyor...
    copy config\config.example.yaml config\config.yaml >nul
    echo [!] config\config.yaml olusturuldu. Lutfen chat_id ve prompt ayarlarinizi yapin.
) else (
    echo [*] config\config.yaml zaten mevcut.
)

echo.
echo ============================================================
echo       Windows Kurulumu Basariyla Tamamlandi!
echo ============================================================
echo.
echo Sonraki adimlar:
echo   1. config\config.yaml dosyasini Not Defteri veya bir editor ile acip
echo      chat_id ve prompt alanlarini duzenleyin (veya Web UI'dan yapin).
echo.
echo   2. Ilk kez oturum kaydetmek icin:
echo        venv\Scripts\activate
echo        python main.py --save-session
echo.
echo   3. Botu ve Dashboard'u baslatmak icin:
echo        start.bat   veya   python main.py
echo.
echo   Tarayicidan http://localhost:8000 adresine giderek kontrol edebilirsiniz.
echo ============================================================
echo.
pause
