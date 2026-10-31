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
    "Khoi_Dong_BabyGuard.command",
    "Start_BabyGuard.command",
    "Tat_BabyGuard.command",
    "Stop_BabyGuard.command",
    "start.sh",
    "stop.sh",
    "requirements.txt",
    "config.example.json",
    "sepay_config.json"
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
            shutil.copytree(src, dst)
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

    # 5. Dọn sạch toàn bộ mã nguồn .py và tệp .c trung gian
    print("[5/6] 🛡️ Xóa bỏ 100% mã nguồn .py và tệp trung gian .c (Chỉ giữ lại binary .so)...")
    compiled_count = 0
    for mod in CYTHON_MODULES:
        py_in_dist = os.path.join(COMMERCIAL_DIR, mod)
        c_in_dist = os.path.join(COMMERCIAL_DIR, mod.replace(".py", ".c"))
        if os.path.exists(py_in_dist):
            os.remove(py_in_dist)
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
                print(f"   🔒 [MÃ HÓA NATIVE]: {f}")

    # Sao chép main.py sạch (bootloader)
    shutil.copyfile(os.path.join(ROOT_DIR, "main.py"), os.path.join(COMMERCIAL_DIR, "main.py"))
    print("   + Đã gắn Bootloader: main.py")

    # 6. Đóng gói tệp ZIP phân phối
    print(f"\n[6/6] 📦 Đóng gói tệp nén thương mại: {ZIP_OUTPUT}...")
    if os.path.exists(ZIP_OUTPUT):
        os.remove(ZIP_OUTPUT)

    with zipfile.ZipFile(ZIP_OUTPUT, "w", zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(COMMERCIAL_DIR):
            for file in files:
                full_path = os.path.join(root, file)
                rel_path = os.path.relpath(full_path, DIST_ROOT)
                zipf.write(full_path, rel_path)

    zip_size_mb = os.path.getsize(ZIP_OUTPUT) / (1024 * 1024)
    print("=" * 70)
    print("🎉 ĐÓNG GÓI THƯƠNG MẠI HOÀN TẤT THÀNH CÔNG!")
    print(f"📁 Thư mục phát hành: {COMMERCIAL_DIR}")
    print(f"📦 Tệp nén sẵn sàng bán: {ZIP_OUTPUT} ({zip_size_mb:.2f} MB)")
    print(f"🛡️ Tổng số module thuật toán cốt lõi được mã hóa nhị phân: {compiled_count} modules")
    print("=" * 70)


if __name__ == "__main__":
    build_commercial_distribution()
