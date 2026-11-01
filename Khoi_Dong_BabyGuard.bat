@echo off
chcp 65001 >nul
title BabyGuard AI - Trợ Lý Vệ Sĩ & Bác Sĩ Giấc Ngủ Cho Bé
cd /d "%~dp0"
color 0B

echo ======================================================================
echo    🍼 BABYGUARD AI - TRỢ LÝ VỆ SĨ & BÁC SĨ GIẤC NGỦ CHO BÉ
echo ======================================================================
echo.
echo [1/3] 🔍 Đang kiểm tra môi trường Python trên máy tính Windows...

set SYSTEM_PYTHON=python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    py --version >nul 2>&1
    if %errorlevel% equ 0 (
        set SYSTEM_PYTHON=py
    ) else (
        echo [!] Chưa tìm thấy Python trên máy tính của bạn.
        echo [*] Đang mở trình tải Python 3.11 chính thức từ trang chủ...
        powershell -Command "Start-Process 'https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe'"
        echo.
        echo [LƯU Ý QUAN TRỌNG KHI CÀI PYTHON]:
        echo   1. Tích chọn vào ô: [v] "Add python.exe to PATH" ở dưới cùng cửa sổ.
        echo   2. Bấm "Install Now" và đợi cài đặt hoàn tất.
        echo   3. Sau đó nhấp đúp lại vào file này để khởi động BabyGuard AI.
        echo.
        pause
        exit /b
    )
)

echo [*] Python hệ thống: Đã nhận diện!
echo.
echo [2/3] 📦 Đang kiểm tra môi trường riêng & thư viện AI...

if not exist ".venv\Scripts\python.exe" (
    echo [*] Đang khởi tạo môi trường chạy riêng biệt cho BabyGuard AI...
    %SYSTEM_PYTHON% -m venv .venv
)

set APP_PYTHON=.venv\Scripts\python.exe
set APP_PIP=.venv\Scripts\pip.exe

if not exist "%APP_PYTHON%" (
    set APP_PYTHON=%SYSTEM_PYTHON%
    set APP_PIP=%SYSTEM_PYTHON% -m pip
)

%APP_PYTHON% -c "import fastapi, uvicorn, cv2, webview, ultralytics" >nul 2>&1
if %errorlevel% neq 0 (
    echo [*] Phát hiện thiếu thư viện. Đang TỰ ĐỘNG CÀI ĐẶT (chỉ mất 1 - 2 phút)...
    echo [*] Vui lòng giữ kết nối Internet ổn định...
    %APP_PIP% install --upgrade pip
    %APP_PIP% install -r requirements.txt
    if %errorlevel% neq 0 (
        echo [!] Có lỗi xảy ra trong quá trình cài đặt thư viện.
        echo [!] Vui lòng kiểm tra lại kết nối mạng Internet.
        pause
        exit /b
    )
    echo [*] Đã cài đặt xong toàn bộ thư viện AI thành công!
) else (
    echo [*] Toàn bộ thư viện AI đã được cài đặt đầy đủ.
)

echo.
echo [3/3] 🚀 Đang khởi động Cửa Sổ Ứng Dụng BabyGuard AI...
start "" %APP_PYTHON% main.py
