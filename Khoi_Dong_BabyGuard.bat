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

set PYTHON_CMD=python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    py --version >nul 2>&1
    if %errorlevel% equ 0 (
        set PYTHON_CMD=py
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

echo [*] Python đã sẵn sàng!
echo.
echo [2/3] 📦 Đang kiểm tra các thư viện AI cần thiết...
%PYTHON_CMD% -c "import fastapi, uvicorn, cv2, webview" >nul 2>&1
if %errorlevel% neq 0 (
    echo [*] Phát hiện thiếu thư viện. Đang TỰ ĐỘNG CÀI ĐẶT (chỉ mất 1 - 2 phút)...
    echo [*] Vui lòng giữ kết nối Internet...
    %PYTHON_CMD% -m pip install --upgrade pip
    %PYTHON_CMD% -m pip install -r requirements.txt
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
start "" %PYTHON_CMD% main.py
