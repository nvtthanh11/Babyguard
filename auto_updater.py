"""
BabyGuard AI - Automatic OTA Update Engine
Tự động định kỳ kiểm tra phiên bản mới từ tên miền chính thức https://babyguard.site,
tải và cập nhật hệ thống trong nền mà không làm gián đoạn hoặc mất dữ liệu của gia đình.
"""

import os
import sys
import json
import time
import shutil
import zipfile
import threading
import requests

PRIMARY_VERSION_URL = "https://babyguard.site/version.json"
FALLBACK_VERSION_URL = "https://cam.babyguard.site/version.json"
GITHUB_VERSION_URL = "https://raw.githubusercontent.com/nvtthanh11/Babyguard/main/version.json"

UPDATE_PACKAGES = [
    "https://babyguard.site/download/BabyGuard_AI.zip",
    "https://cam.babyguard.site/download/BabyGuard_AI.zip",
    "https://raw.githubusercontent.com/nvtthanh11/Babyguard/main/dist/BabyGuard_AI_v2.0_Commercial.zip"
]

PROTECTED_ITEMS = {
    "config.json", ".babyguard_license_state", "sleep_data.json",
    "daily_delta_log.json", "baby_growth.json", "baby_growth_ai.json",
    "baby_vaccines.json", "sepay_transactions.json", "recordings",
    "snapshots", "moments", "logs", ".venv", "venv"
}


def parse_version(v_str):
    try:
        clean = str(v_str).strip().lower().replace("v", "")
        parts = [int(p) for p in clean.split(".") if p.isdigit()]
        return tuple(parts)
    except Exception:
        return (0, 0, 0)


class AutoUpdateWorker(threading.Thread):
    def __init__(self, base_dir, alert_manager=None, check_interval_seconds=14400, initial_delay_seconds=30):
        super().__init__(name="AutoUpdateWorker", daemon=True)
        self.base_dir = os.path.abspath(base_dir)
        self.alert_manager = alert_manager
        self.check_interval = check_interval_seconds
        self.initial_delay = initial_delay_seconds
        self._stop_event = threading.Event()

    def stop(self):
        self._stop_event.set()

    def get_local_version_info(self):
        v_file = os.path.join(self.base_dir, "version.json")
        if os.path.exists(v_file):
            try:
                with open(v_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {"version": "2.1.0"}

    def fetch_remote_manifest(self):
        for url in [PRIMARY_VERSION_URL, FALLBACK_VERSION_URL, GITHUB_VERSION_URL]:
            try:
                resp = requests.get(url, timeout=5)
                if resp.status_code == 200:
                    data = resp.json()
                    if "version" in data:
                        return data, url
            except Exception:
                continue
        return None, None

    def run(self):
        print(f"[AutoUpdate] 🚀 Khởi động dịch vụ tự động kiểm tra phiên bản mới từ https://babyguard.site...")
        if self._stop_event.wait(self.initial_delay):
            return

        while not self._stop_event.is_set():
            try:
                self.check_and_apply_update()
            except Exception as e:
                print(f"[AutoUpdate] Ghi chú kiểm tra cập nhật: {e}")

            if self._stop_event.wait(self.check_interval):
                break

    def check_and_apply_update(self):
        local_info = self.get_local_version_info()
        local_v_str = local_info.get("version", "2.1.0")
        local_v = parse_version(local_v_str)

        remote_info, source_url = self.fetch_remote_manifest()
        if not remote_info:
            return False

        remote_v_str = remote_info.get("version", local_v_str)
        remote_v = parse_version(remote_v_str)

        if remote_v <= local_v:
            print(f"[AutoUpdate] ℹ️ Hệ thống đang ở bản mới nhất v{local_v_str} (Máy chủ: {source_url})")
            return False

        print(f"[AutoUpdate] 🔔 PHÁT HIỆN BẢN CẬP NHẬT MỚI: v{remote_v_str} (Hiện tại: v{local_v_str}) từ {source_url}")
        print(f"[AutoUpdate] 📦 Đang tự động tải và cài đặt cập nhật Over-The-Air...")

        success, msg = self.apply_update(remote_info)
        if success:
            print(f"[AutoUpdate] 🎉 {msg}")
            if self.alert_manager:
                features = remote_info.get("features", [])
                feat_lines = "\n".join([f"  • {f}" for f in features]) if features else "  • Tối ưu hiệu năng & sửa lỗi."
                tele_msg = (
                    "🎉 <b>[BABYGUARD AI — TỰ ĐỘNG CẬP NHẬT THÀNH CÔNG]</b>\n\n"
                    f"✨ Hệ thống đã tự động nâng cấp lên phiên bản mới: <b>v{remote_v_str}</b> "
                    f"từ máy chủ chính thức <code>https://babyguard.site</code>!\n\n"
                    f"📋 <b>Các cải tiến mới:</b>\n{feat_lines}\n\n"
                    "🔒 <i>Toàn bộ dữ liệu cữ ngủ, video kỷ niệm và cấu hình gia đình được bảo toàn nguyên vẹn 100%.</i>"
                )
                try:
                    self.alert_manager.send_telegram_text(tele_msg)
                except Exception as te:
                    print(f"[AutoUpdate] Lỗi gửi thông báo Telegram: {te}")
            return True
        else:
            print(f"[AutoUpdate] ⚠️ Cập nhật thất bại: {msg}")
            return False

    def apply_update(self, remote_info):
        git_dir = os.path.join(self.base_dir, ".git")
        if os.path.exists(git_dir):
            try:
                import subprocess
                proc = subprocess.run(
                    ["git", "pull", "origin", "main"],
                    cwd=self.base_dir,
                    capture_output=True,
                    text=True,
                    timeout=30
                )
                if proc.returncode == 0:
                    return True, "Cập nhật thành công qua Git!"
            except Exception as e:
                pass

        # Tải gói cập nhật OTA qua HTTPS từ tên miền chính thức
        target_pkg_url = None
        resp = None
        for pkg_url in UPDATE_PACKAGES:
            try:
                r = requests.get(pkg_url, timeout=90, stream=True)
                if r.status_code == 200:
                    target_pkg_url = pkg_url
                    resp = r
                    break
            except Exception:
                continue

        if not resp:
            return False, "Không thể kết nối máy chủ phân phối gói cập nhật."

        temp_zip = os.path.join(self.base_dir, "babyguard_update_ota.zip")
        try:
            with open(temp_zip, "wb") as f:
                for chunk in resp.iter_content(chunk_size=65536):
                    if chunk:
                        f.write(chunk)

            with zipfile.ZipFile(temp_zip, "r") as zf:
                for member in zf.namelist():
                    norm_path = member.replace("\\", "/").strip("/")
                    parts = norm_path.split("/")
                    if not parts:
                        continue
                    # Bỏ qua nếu thuộc danh mục bảo vệ dữ liệu người dùng
                    if parts[0] in PROTECTED_ITEMS:
                        continue
                    # Nếu zip có prefix thư mục gốc
                    if parts[0] in ("BabyGuard_AI_v2.0_Commercial", "BabyGuard_Windows", "app_core"):
                        if len(parts) > 1 and parts[1] in PROTECTED_ITEMS:
                            continue
                        rel_path = "/".join(parts[1:])
                        if not rel_path:
                            continue
                        target_path = os.path.join(self.base_dir, rel_path)
                        if member.endswith("/"):
                            os.makedirs(target_path, exist_ok=True)
                        else:
                            os.makedirs(os.path.dirname(target_path), exist_ok=True)
                            with zf.open(member) as src, open(target_path, "wb") as dst:
                                shutil.copyfileobj(src, dst)
                    else:
                        target_path = os.path.join(self.base_dir, norm_path)
                        if member.endswith("/"):
                            os.makedirs(target_path, exist_ok=True)
                        else:
                            os.makedirs(os.path.dirname(target_path), exist_ok=True)
                            with zf.open(member) as src, open(target_path, "wb") as dst:
                                shutil.copyfileobj(src, dst)

            # Cập nhật tệp version.json tại chỗ
            v_file = os.path.join(self.base_dir, "version.json")
            with open(v_file, "w", encoding="utf-8") as f:
                json.dump(remote_info, f, indent=2, ensure_ascii=False)

            return True, f"Đã tự động nâng cấp thành công lên phiên bản v{remote_info.get('version', '')} từ {target_pkg_url}!"
        except Exception as e:
            return False, f"Lỗi trong quá trình giải nén cập nhật: {str(e)}"
        finally:
            if os.path.exists(temp_zip):
                try:
                    os.remove(temp_zip)
                except Exception:
                    pass
