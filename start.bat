@echo off
chcp 65001 >nul
if not exist "venv\Scripts\activate.bat" (
    echo [HATA] Sanal ortam bulunamadi!
    echo Lutfen once setup.bat dosyasini calistirin.
    echo.
    pause
    exit /b 1
)

call venv\Scripts\activate.bat
python main.py %*
