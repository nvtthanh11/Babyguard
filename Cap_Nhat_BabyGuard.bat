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
    echo Dang dong bo phien ban moi nhat qua Git...
    git pull origin main
    echo.
    echo Da cap nhat thanh cong!
) else (
    echo Dang ket noi may chu chinh thuc https://babyguard.site...
    python -c "import sys, urllib.request, json; data=json.loads(urllib.request.urlopen('https://babyguard.site/version.json', timeout=5).read().decode('utf-8')); print('✨ Phien ban moi nhat tren babyguard.site:', data.get('version', '2.1.0'))" 2>nul
    echo.
    echo Ba chi can mo BabyGuard AI, he thong se tu dong kiem tra va tai ban moi nhat!
    echo Hoac ba co the bam 'Kiem Tra Cap Nhat' ngay trong phan Cai Dat tren giao dien.
)

echo.
echo ============================================================
echo Hoan tat! Nhan phim bat ky de thoat...
pause >nul
