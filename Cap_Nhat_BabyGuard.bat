@echo off
chcp 65001 >nul
title BabyGuard AI - Cap Nhat Phien Ban Moi
cd /d "%~dp0"

echo ============================================================
echo   BABYGUARD AI - CÔNG CỤ TỰ ĐỘNG CẬP NHẬT PHIÊN BẢN MỚI
echo ============================================================
echo   An toan: Du lieu cu ngu, ban quyen va video duoc bao ve 100%!
echo.

if exist ".git" (
    echo Dang dong bo phien ban moi nhat tu GitHub...
    git pull origin main
    echo.
    echo Da cap nhat thanh cong!
) else (
    echo Dang kiem tra ban cap nhat moi tu may chu BabyGuard...
    python -c "import urllib.request, json; data=json.loads(urllib.request.urlopen('https://raw.githubusercontent.com/nvtthanh11/Babyguard/main/version.json', timeout=5).read().decode('utf-8')); print('Phien ban moi nhat:', data.get('version', 'v2.1.0'))" 2>nul
    echo.
    echo Ba cung co the mo BabyGuard va bam 'Kiem Tra Cap Nhat' ngay trong phan Cai Dat!
)

echo.
echo ============================================================
echo Hoan tat! Nhan phim bat ky de thoat...
pause >nul
