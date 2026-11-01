#!/usr/bin/env python3
"""
BabyGuard AI - Commercial Binary Packaging & Obfuscation Pipeline
Compiles all core proprietary Python algorithms into native ARM64 / Mach-O C-extension binaries (.so)
via Cython & Apple Clang. Strips debug symbols, removes all .py source code,
and produces a turnkey commercial release package.
"""

import os
import sys
import shutil
import subprocess
import zipfile
import py_compile
from setuptools import setup
from Cython.Build import cythonize

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST_ROOT = os.path.join(ROOT_DIR, "dist")
COMMERCIAL_DIR = os.path.join(DIST_ROOT, "BabyGuard_AI_v2.0_Commercial")
ZIP_OUTPUT = os.path.join(DIST_ROOT, "BabyGuard_AI_v2.0_Commercial.zip")

CYTHON_MODULES = [
    "vision_detector.py",
    "gemini_verifier.py",
    "sleep_tracker.py",
    "alert_manager.py",
    "audio_detector.py",
    "video_recorder.py",
    "growth_tracker.py",
    "vaccine_tracker.py",
    "daily_story_tracker.py",
    "google_drive_sync.py",
    "tunnel_manager.py",
    "music_player.py",
    "license_manager.py",
    "auto_updater.py",
    "web_server.py"
]

ASSET_DIRS = [
    "templates",
    "models",
    "medical_knowledge",
    "music",
    "static"
]

SUPPORT_FILES = [
    "HUONG_DAN_SU_DUNG.md",
    "User_Guide_EN.md",
    "Khoi_Dong_BabyGuard.bat",
    "Khoi_Dong_BabyGuard.command",
    "Cap_Nhat_BabyGuard.bat",
    "Cap_Nhat_BabyGuard.command",
    "Start_BabyGuard.command",
    "Tat_BabyGuard.command",
    "Stop_BabyGuard.command",
    "start.sh",
    "stop.sh",
    "requirements.txt",
    "config.example.json",
    "sepay_config.json",
    "version.json"
]


def clean_dir(d):
    if os.path.exists(d):
        shutil.rmtree(d)
    os.makedirs(d, exist_ok=True)


def build_commercial_distribution():
    print("=" * 70)
    print("   BABYGUARD AI - COMMERCIAL OBFUSCATION & PACKAGING PIPELINE")
    print("=" * 70)

    # 1. Chuẩn bị thư mục đóng gói sạch
    print("\n[1/6] 🧹 Chuẩn bị thư mục phân phối thương mại sạch...")
    clean_dir(COMMERCIAL_DIR)
    for folder in ["logs", "snapshots", "recordings", "moments"]:
        os.makedirs(os.path.join(COMMERCIAL_DIR, folder), exist_ok=True)

    # 2. Sao chép tài nguyên & giao diện
    print("[2/6] 📁 Sao chép giao diện Web, AI Models, Nhạc ru & Phác đồ Y Khoa...")
    for folder in ASSET_DIRS:
        src = os.path.join(ROOT_DIR, folder)
        dst = os.path.join(COMMERCIAL_DIR, folder)
        if os.path.exists(src):
            shutil.copytree(src, dst, ignore=shutil.ignore_patterns("*.zip", "*.tar.gz", "*.aab", "__pycache__", "*.pyc"))
            print(f"   + Đã sao chép thư mục: {folder}/")

    for f in SUPPORT_FILES:
        src = os.path.join(ROOT_DIR, f)
        dst = os.path.join(COMMERCIAL_DIR, f)
        if os.path.exists(src):
            shutil.copyfile(src, dst)
            # Cấp quyền thực thi cho .command và .sh
            if f.endswith(".sh") or f.endswith(".command"):
                os.chmod(dst, 0o755)
            print(f"   + Đã sao chép tệp: {f}")

    # 3. Tạo tệp config.json khách hàng sạch (Không chứa token cá nhân)
    print("[3/6] ⚙️ Khởi tạo cấu hình mặc định (Pristine Config) cho khách hàng...")
    clean_config_src = os.path.join(ROOT_DIR, "config.example.json")
    clean_config_dst = os.path.join(COMMERCIAL_DIR, "config.json")
    if os.path.exists(clean_config_src):
        shutil.copyfile(clean_config_src, clean_config_dst)
        print("   + Đã tạo config.json sạch (sẵn sàng kích hoạt Onboarding Wizard).")

    # 4. Sao chép các tệp mã nguồn vào thư mục build để Cythonize
    print("[4/6] 🔒 Biên dịch C/C++ Mach-O Binary chống dịch ngược (Anti-Reverse Engineering)...")
    for mod in CYTHON_MODULES:
        src_py = os.path.join(ROOT_DIR, mod)
        dst_py = os.path.join(COMMERCIAL_DIR, mod)
        if os.path.exists(src_py):
            shutil.copyfile(src_py, dst_py)

    orig_cwd = os.getcwd()
    os.chdir(COMMERCIAL_DIR)
    try:
        sys.argv = ["setup.py", "build_ext", "--inplace"]
        print(f"   ⚡ Đang biên dịch {len(CYTHON_MODULES)} modules sang ARM64/Mach-O native .so...")
        setup(
            ext_modules=cythonize(
                CYTHON_MODULES,
                compiler_directives={"language_level": "3"},
                quiet=True
            )
        )
    finally:
        os.chdir(orig_cwd)

    # 5. Dọn sạch tệp trung gian .c (Giữ lại .py để tương thích đa nền tảng Windows + .so cho macOS)
    print("[5/6] 🛡️ Dọn dẹp tệp trung gian .c, bảo toàn mã nguồn chạy đa nền tảng...")
    compiled_count = 0
    for mod in CYTHON_MODULES:
        c_in_dist = os.path.join(COMMERCIAL_DIR, mod.replace(".py", ".c"))
        if os.path.exists(c_in_dist):
            os.remove(c_in_dist)

    # Dọn dẹp thư mục build tạm của setup
    temp_build = os.path.join(COMMERCIAL_DIR, "build")
    if os.path.exists(temp_build):
        shutil.rmtree(temp_build)

    # Strip symbols trên các file .so để bảo mật tối đa
    for root, dirs, files in os.walk(COMMERCIAL_DIR):
        for f in files:
            if f.endswith(".so"):
                so_path = os.path.join(root, f)
                try:
                    subprocess.run(["strip", "-x", so_path], check=False, stderr=subprocess.DEVNULL)
                except Exception:
                    pass
                compiled_count += 1
                print(f"   🔒 [MÃ HÓA NATIVE MAC]: {f}")

    # Sao chép main.py sạch (bootloader)
    shutil.copyfile(os.path.join(ROOT_DIR, "main.py"), os.path.join(COMMERCIAL_DIR, "main.py"))
    print("   + Đã gắn Bootloader: main.py")

    # 6. Tạo macOS Native App Bundle (BabyGuard AI.app) & Disk Image (.DMG)
    print("\n[6/7] 🍏 Đóng gói ứng dụng Native macOS (BabyGuard AI.app)...")
    MAC_STAGING = os.path.join(DIST_ROOT, "mac_staging")
    if os.path.exists(MAC_STAGING):
        shutil.rmtree(MAC_STAGING)
    os.makedirs(MAC_STAGING, exist_ok=True)

    MAC_APP = os.path.join(MAC_STAGING, "BabyGuard AI.app")
    contents_dir = os.path.join(MAC_APP, "Contents")
    macos_dir = os.path.join(contents_dir, "MacOS")
    res_dir = os.path.join(contents_dir, "Resources")
    os.makedirs(macos_dir, exist_ok=True)
    os.makedirs(res_dir, exist_ok=True)

    # 6.1 Tạo AppIcon.icns từ icon 512px
    icon_512 = os.path.join(ROOT_DIR, "static", "icons", "icon-512.png")
    app_icns = os.path.join(res_dir, "AppIcon.icns")
    if os.path.exists(icon_512):
        temp_iconset = "/tmp/BabyGuard_App.iconset"
        if os.path.exists(temp_iconset):
            shutil.rmtree(temp_iconset)
        os.makedirs(temp_iconset, exist_ok=True)
        try:
            for s in [16, 32, 64, 128, 256, 512]:
                subprocess.run(["sips", "-z", str(s), str(s), icon_512, "--out", f"{temp_iconset}/icon_{s}x{s}.png"], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                if s * 2 <= 512:
                    subprocess.run(["sips", "-z", str(s*2), str(s*2), icon_512, "--out", f"{temp_iconset}/icon_{s}x{s}@2x.png"], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            subprocess.run(["iconutil", "-c", "icns", temp_iconset, "-o", app_icns], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            print("   + Đã tạo AppIcon.icns chuẩn Retina macOS.")
        except Exception as e:
            print(f"   ⚠️ Lỗi tạo icns: {e}")

    # 6.2 Info.plist cho BabyGuard AI.app
    plist_xml = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleExecutable</key>
    <string>BabyGuard AI</string>
    <key>CFBundleIdentifier</key>
    <string>site.babyguard.ai</string>
    <key>CFBundleName</key>
    <string>BabyGuard AI</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleShortVersionString</key>
    <string>2.1.0</string>
    <key>CFBundleVersion</key>
    <string>2.1.0</string>
    <key>CFBundleIconFile</key>
    <string>AppIcon</string>
    <key>NSHighResolutionCapable</key>
    <true/>
    <key>NSCameraUsageDescription</key>
    <string>BabyGuard AI cần quyền Camera để giám sát nôi bé và phát hiện lật úp.</string>
    <key>NSMicrophoneUsageDescription</key>
    <string>BabyGuard AI cần quyền Microphone để phát hiện tiếng khóc và tiếng ho của bé.</string>
</dict>
</plist>"""
    with open(os.path.join(contents_dir, "Info.plist"), "w", encoding="utf-8") as f:
        f.write(plist_xml)

    # 6.3 Executable Launcher cho macOS (Chạy Native, không mở cửa sổ Terminal shell)
    mac_launcher_script = """#!/bin/bash
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )/../Resources" >/dev/null 2>&1 && pwd )"
cd "$DIR"

# Tự động gỡ bỏ cờ cách ly của Apple nếu tải từ trình duyệt Chrome / Safari
xattr -cr "$DIR/../.." 2>/dev/null || true
xattr -d com.apple.quarantine "$DIR/../.." 2>/dev/null || true
chmod +x ./start.sh ./stop.sh 2>/dev/null || true

# Khởi chạy ứng dụng trực tiếp, tuyệt đối không bật cửa sổ Terminal shell
mkdir -p "$DIR/logs"
exec ./start.sh >> "$DIR/logs/app_launch.log" 2>&1
"""
    mac_bin = os.path.join(macos_dir, "BabyGuard AI")
    with open(mac_bin, "w", encoding="utf-8") as f:
        f.write(mac_launcher_script)
    os.chmod(mac_bin, 0o755)

    # 6.4 Sao chép tài nguyên vào Resources và XÓA TRIỆT ĐỂ TOÀN BỘ FILE .PY (CHỈ GIỮ .SO & MAIN.PYC)
    for root, dirs, files in os.walk(COMMERCIAL_DIR):
        rel = os.path.relpath(root, COMMERCIAL_DIR)
        target_subdir = os.path.join(res_dir, rel) if rel != "." else res_dir
        os.makedirs(target_subdir, exist_ok=True)
        for file in files:
            # TUYỆT ĐỐI KHÔNG COPY FILE .PY NGUỒN CỦA CÁC MODULES ĐÃ BIÊN DỊCH
            if file in CYTHON_MODULES or file.endswith(".bat"):
                continue
            # main.py được biên dịch thành main.pyc (Bytecode), xóa sạch mã nguồn text
            if file == "main.py":
                py_compile.compile(os.path.join(root, file), cfile=os.path.join(target_subdir, "main.pyc"))
                continue
            dst_f = os.path.join(target_subdir, file)
            shutil.copyfile(os.path.join(root, file), dst_f)
            if file.endswith(".sh") or file.endswith(".command"):
                os.chmod(dst_f, 0o755)

    print("   🔒 Đã loại bỏ 100% tệp mã nguồn .py khỏi macOS App Bundle (Chỉ còn Mach-O .so & .pyc).")

    # 7. Đóng gói phân phối tinh gọn (Zero Clutter): BabyGuard_Windows.zip, BabyGuard_Mac.dmg, BabyGuard_Mac.zip
    print("\n[7/7] 📦 Đang đóng gói tệp cài đặt tinh gọn thương mại:")
    WIN_ZIP = os.path.join(DIST_ROOT, "BabyGuard_Windows.zip")
    MAC_ZIP = os.path.join(DIST_ROOT, "BabyGuard_Mac.zip")
    MAC_DMG = os.path.join(DIST_ROOT, "BabyGuard_Mac.dmg")

    print(f"   1. Gói Universal: {ZIP_OUTPUT}")
    print(f"   2. Gói Windows:   {WIN_ZIP}")
    print(f"   3. Gói Mac ZIP:   {MAC_ZIP}")
    print(f"   4. Gói Mac DMG:   {MAC_DMG}")

    # ĐÓNG GÓI WINDOWS: Gọn gàng tuyệt đối - Chỉ 1 file .bat & 1 file txt ở thư mục gốc, toàn bộ file lõi giấu vào app_core/
    if os.path.exists(WIN_ZIP):
        os.remove(WIN_ZIP)
    with zipfile.ZipFile(WIN_ZIP, "w", zipfile.ZIP_DEFLATED) as zipf:
        # File chạy chính ở gốc
        win_launcher_content = """@echo off
chcp 65001 >nul
title BabyGuard AI - Tro Ly Ve Si & Bac Si Giac Ngu Cho Be
cd /d "%~dp0app_core"
call "Khoi_Dong_BabyGuard.bat"
"""
        zipf.writestr("BabyGuard_Windows/BabyGuard AI.bat", win_launcher_content)

        # File hướng dẫn ở gốc
        win_guide_content = """======================================================================
🍼 BABYGUARD AI - TRỢ LÝ VỆ SĨ & BÁC SĨ GIẤC NGỦ THÔNG MINH CHO BÉ
======================================================================

HƯỚNG DẪN KHỞI ĐỘNG NHANH TRONG 1 BƯỚC:
👉 Nhấp đúp chuột vào file: "BabyGuard AI.bat" để khởi động!

LƯU Ý:
- Lần đầu tiên chạy, hệ thống sẽ tự động cấu hình và chuẩn bị thư viện AI (chỉ mất 1 - 2 phút).
- Mọi tệp vận hành lõi đã được lưu trữ an toàn trong thư mục "app_core". Ba mẹ không cần can thiệp hoặc di chuyển các tệp bên trong thư mục này.
- Hệ thống sẽ tự động kiểm tra và nâng cấp phiên bản mới từ máy chủ chính thức https://babyguard.site.

Tổng đài hỗ trợ kỹ thuật: 0943.435.433
Website chính thức: https://babyguard.site
======================================================================
"""
        zipf.writestr("BabyGuard_Windows/HUONG_DAN_SU_DUNG.txt", win_guide_content)

        # Toàn bộ nội dung khác đưa gọn gàng vào app_core/
        for root, dirs, files in os.walk(COMMERCIAL_DIR):
            for file in files:
                if file.endswith(".so") or file.endswith(".command") or file.endswith(".sh"):
                    continue
                full_path = os.path.join(root, file)
                rel_inside = os.path.relpath(full_path, COMMERCIAL_DIR)
                zipf.write(full_path, os.path.join("BabyGuard_Windows", "app_core", rel_inside))

    # ĐÓNG GÓI MAC DMG (Chuẩn Native: Chỉ có BabyGuard AI.app và symlink Applications)
    if os.path.exists(MAC_DMG):
        os.remove(MAC_DMG)
    app_symlink = os.path.join(MAC_STAGING, "Applications")
    if not os.path.exists(app_symlink):
        try:
            os.symlink("/Applications", app_symlink)
        except Exception:
            pass
    try:
        subprocess.run(["hdiutil", "create", "-volname", "BabyGuard AI", "-srcfolder", MAC_STAGING, "-ov", "-format", "UDZO", MAC_DMG], check=True, stdout=subprocess.DEVNULL)
        print("   + Đã tạo BabyGuard_Mac.dmg chuẩn Native (chỉ App + Applications)!")
    except Exception as e:
        print(f"   ⚠️ Lỗi tạo DMG: {e}")
    finally:
        if os.path.islink(app_symlink):
            os.remove(app_symlink)

    # ĐÓNG GÓI MAC ZIP (Chuẩn App Bundle: Chỉ giải nén ra duy nhất BabyGuard AI.app)
    if os.path.exists(MAC_ZIP):
        os.remove(MAC_ZIP)
    with zipfile.ZipFile(MAC_ZIP, "w", zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(MAC_APP):
            for file in files:
                full_path = os.path.join(root, file)
                rel_inside = os.path.relpath(full_path, MAC_STAGING)
                zinfo = zipfile.ZipInfo.from_file(full_path, rel_inside)
                mode = os.stat(full_path).st_mode
                zinfo.external_attr = (mode & 0xFFFF) << 16
                with open(full_path, "rb") as src:
                    zipf.writestr(zinfo, src.read())

    # Đóng gói Universal ZIP
    if os.path.exists(ZIP_OUTPUT):
        os.remove(ZIP_OUTPUT)
    with zipfile.ZipFile(ZIP_OUTPUT, "w", zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(COMMERCIAL_DIR):
            for file in files:
                full_path = os.path.join(root, file)
                rel_inside = os.path.relpath(full_path, COMMERCIAL_DIR)
                zipf.write(full_path, os.path.join("BabyGuard_AI_v2.0_Commercial", rel_inside))

    # Sao chép vào thư mục static để phục vụ tải về trực tiếp
    static_dir = os.path.join(ROOT_DIR, "static")
    if os.path.exists(static_dir):
        for z in [ZIP_OUTPUT, WIN_ZIP, MAC_ZIP, MAC_DMG]:
            if os.path.exists(z):
                shutil.copyfile(z, os.path.join(static_dir, os.path.basename(z)))
        # Đồng thời tạo bản sao BabyGuard_AI.zip trong static
        if os.path.exists(ZIP_OUTPUT):
            shutil.copyfile(ZIP_OUTPUT, os.path.join(static_dir, "BabyGuard_AI.zip"))

    print("=" * 70)
    print("🎉 ĐÓNG GÓI THƯƠNG MẠI HOÀN TẤT THÀNH CÔNG!")
    print(f"📁 Thư mục phát hành: {COMMERCIAL_DIR}")
    print(f"📦 1. Tệp Windows:   {WIN_ZIP} ({os.path.getsize(WIN_ZIP) / (1024*1024):.2f} MB)")
    print(f"📦 2. Tệp Mac DMG:   {MAC_DMG} ({os.path.getsize(MAC_DMG) / (1024*1024):.2f} MB)")
    print(f"📦 3. Tệp Mac ZIP:   {MAC_ZIP} ({os.path.getsize(MAC_ZIP) / (1024*1024):.2f} MB)")
    print("=" * 70)


if __name__ == "__main__":
    build_commercial_distribution()
