import os
import glob
import cv2
from datetime import datetime


def detect_macos_google_drive_path() -> str:
    """Tự động phát hiện đường dẫn Google Drive for Desktop trên macOS."""
    home = os.path.expanduser("~")
    patterns = [
        os.path.join(home, "Library/CloudStorage/GoogleDrive-*/My Drive"),
        os.path.join(home, "Library/CloudStorage/GoogleDrive-*"),
        os.path.join(home, "Google Drive/My Drive"),
        os.path.join(home, "Google Drive"),
    ]
    for p in patterns:
        matches = glob.glob(p)
        for m in matches:
            if os.path.isdir(m):
                # Ưu tiên thư mục 'My Drive' nếu có
                sub_my_drive = os.path.join(m, "My Drive")
                if os.path.isdir(sub_my_drive):
                    return sub_my_drive
                return m
    return ""


def get_google_drive_status(config: dict) -> dict:
    """Kiểm tra trạng thái kết nối Google Drive hiện tại."""
    cfg_path = config.get("google_drive_path", "").strip()
    detected_path = detect_macos_google_drive_path()
    active_path = cfg_path or detected_path
    is_valid = bool(active_path and os.path.isdir(active_path))
    enabled = bool(config.get("google_drive_enabled", is_valid))

    return {
        "enabled": enabled,
        "is_detected": bool(detected_path),
        "detected_path": detected_path,
        "configured_path": cfg_path,
        "active_path": active_path,
        "is_valid": is_valid,
        "folder_name": "BabyGuard_Moments",
        "example_file_path": f"{active_path}/BabyGuard_Moments/YYYY/MM/DD/HH-MM-SS.jpg" if active_path else "Chưa kết nối"
    }


def save_moment_to_google_drive(frame_bgr, config: dict, dt: datetime = None) -> str:
    """
    Lưu bản sao ảnh chân dung bé lên Google Drive theo cấu trúc:
    Năm / Tháng / Ngày / Giờ-Phút-Giây.jpg
    Ví dụ: My Drive/BabyGuard_Moments/2026/10/28/09-15-30.jpg
    """
    if dt is None:
        dt = datetime.now()

    status = get_google_drive_status(config)
    if not status["enabled"] or not status["is_valid"]:
        return None

    base_drive = status["active_path"]
    year_str = dt.strftime("%Y")
    month_str = dt.strftime("%m")
    day_str = dt.strftime("%d")
    time_fn = dt.strftime("%H-%M-%S") + ".jpg"

    target_dir = os.path.join(base_drive, "BabyGuard_Moments", year_str, month_str, day_str)
    try:
        os.makedirs(target_dir, exist_ok=True)
        dest_path = os.path.join(target_dir, time_fn)
        success = cv2.imwrite(dest_path, frame_bgr)
        if success:
            print(f"[GoogleDriveSync] ☁️ Đã đồng bộ ảnh khoảnh khắc lên Google Drive: {dest_path}")
            return dest_path
        else:
            print(f"[GoogleDriveSync] ❌ Không thể ghi file ảnh sang Google Drive: {dest_path}")
    except Exception as e:
        print(f"[GoogleDriveSync] ❌ Lỗi đồng bộ Google Drive: {e}")
    return None
