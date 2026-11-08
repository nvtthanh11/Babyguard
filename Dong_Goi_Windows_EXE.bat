@echo off
chcp 65001 >nul
title BabyGuard AI - BIEN DICH BAN MOI NHAT CHO WINDOWS
cd /d "%~dp0"
color 0A

echo ======================================================================
echo    🍼 BABYGUARD AI - BIÊN DỊCH BẢN CHÍNH THỨC CHO WINDOWS
echo ======================================================================
echo  (Đã sửa 100%% lỗi đường dẫn BASE_DIR, tự động mở trình duyệt và ghi log)
echo.

set PY_CMD=
python --version >nul 2>&1
if %errorlevel% equ 0 (
    set PY_CMD=python
) else (
    py --version >nul 2>&1
    if %errorlevel% equ 0 (
        set PY_CMD=py
    )
)

if "%PY_CMD%"=="" (
    echo [!] Chưa tìm thấy Python. Vui lòng cài đặt Python (3.10, 3.11 hoặc 3.12).
    pause
    exit /b
)

echo [*] Python: Đã nhận diện (%PY_CMD%)!
echo [*] Đang cài đặt PyInstaller và các gói bổ trợ...
%PY_CMD% -m pip install --upgrade pip
%PY_CMD% -m pip install pyinstaller
%PY_CMD% -m pip install -r requirements.txt

echo.
echo [*] Đang biên dịch main.py thành BabyGuard AI.exe (Khoảng 1-2 phút)...
%PY_CMD% -m PyInstaller --clean -y --windowed ^
    --name "BabyGuard AI" ^
    --add-data "templates;templates" ^
    --add-data "static;static" ^
    --add-data "music;music" ^
    --add-data "models;models" ^
    --add-data "yolov8n-pose.pt;." ^
    --icon "static/icons/icon.ico" ^
    main.py

if %errorlevel% neq 0 (
    echo.
    echo [!] Có lỗi xảy ra trong quá trình biên dịch.
    pause
    exit /b
)

echo.
echo [*] Đang sao chép các tệp cấu hình và tài nguyên hoàn chỉnh...
copy /y "config.json" "dist\BabyGuard AI\config.json" >nul 2>&1
copy /y "HUONG_DAN_SU_DUNG.txt" "dist\BabyGuard AI\HUONG_DAN_SU_DUNG.txt" >nul 2>&1
copy /y "Khoi_Dong_BabyGuard.bat" "dist\BabyGuard AI\Khoi_Dong_BabyGuard.bat" >nul 2>&1

echo.
echo ======================================================================
echo  🎉 BIÊN DỊCH VÀ ĐÓNG GÓI THÀNH CÔNG RỰC RỠ!
echo  👉 Thư mục kết quả: dist\BabyGuard AI\
echo  👉 Nhấp đúp vào: BabyGuard AI.exe để chạy thử!
echo ======================================================================
echo.
pause
