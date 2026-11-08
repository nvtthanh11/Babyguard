@echo off
chcp 65001 >nul
title Cai Dat Tu Khoi Dong Cung Windows - BabyGuard AI
cd /d "%~dp0"
color 0A

echo ======================================================================
echo    🍼 BABYGUARD AI - CÀI ĐẶT TỰ ĐỘNG CHẠY CÙNG WINDOWS (24/7)
echo ======================================================================
echo.

set SCRIPT_DIR=%~dp0
set VBS_TARGET=%SCRIPT_DIR%Chay_Ngam_Khong_Cua_So.vbs
set STARTUP_DIR=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup
set SHORTCUT_VBS=%TEMP%\CreateShortcut.vbs

echo [*] Đang đăng ký BabyGuard AI vào thư mục khởi động Startup của Windows...

echo Set oWS = WScript.CreateObject("WScript.Shell") > "%SHORTCUT_VBS%"
echo sLinkFile = "%STARTUP_DIR%\BabyGuard_AI.lnk" >> "%SHORTCUT_VBS%"
echo Set oLink = oWS.CreateShortcut(sLinkFile) >> "%SHORTCUT_VBS%"
echo oLink.TargetPath = "wscript.exe" >> "%SHORTCUT_VBS%"
echo oLink.Arguments = """%VBS_TARGET%""" >> "%SHORTCUT_VBS%"
echo oLink.WorkingDirectory = "%SCRIPT_DIR%" >> "%SHORTCUT_VBS%"
echo oLink.Description = "BabyGuard AI - Giam Sat Em Be 24/7" >> "%SHORTCUT_VBS%"
echo oLink.Save >> "%SHORTCUT_VBS%"

cscript //nologo "%SHORTCUT_VBS%"
del "%SHORTCUT_VBS%"

echo.
echo ======================================================================
echo  ✅ CÀI ĐẶT THÀNH CÔNG!
echo ======================================================================
echo  • Từ bây giờ, mỗi khi bạn mở máy tính Windows lên, BabyGuard AI sẽ
echo    TỰ ĐỘNG CHẠY NGẦM dưới nền để giám sát bé 24/7.
echo  • Bạn KHÔNG CẦN mở trình duyệt, chỉ cần kiểm tra Telegram trên điện thoại.
echo ======================================================================
echo.
pause
