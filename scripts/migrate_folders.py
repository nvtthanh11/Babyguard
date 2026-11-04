import os
import re
import shutil
from datetime import datetime, timedelta

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MOMENTS_DIR = os.path.join(BASE_DIR, "moments")
RECORDINGS_DIR = os.path.join(BASE_DIR, "recordings")
SNAPSHOTS_DIR = os.path.join(BASE_DIR, "snapshots")


def migrate_moments():
    print("--- BẮT ĐẦU DI CHUYỂN KHOẢNH KHẮC (MOMENTS) THEO THƯ MỤC NGÀY ---")
    if not os.path.exists(MOMENTS_DIR):
        return
    count = 0
    for fn in os.listdir(MOMENTS_DIR):
        src = os.path.join(MOMENTS_DIR, fn)
        if not os.path.isfile(src) or not fn.endswith((".jpg", ".png", ".jpeg")):
            continue
        m = re.match(r"^moment_(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})\.", fn)
        if m:
            yyyy, mm, dd, hh, min_, ss = m.groups()
            date_folder = f"{yyyy}-{mm}-{dd}"
        else:
            mtime = os.path.getmtime(src)
            date_folder = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d")
        
        target_dir = os.path.join(MOMENTS_DIR, date_folder)
        os.makedirs(target_dir, exist_ok=True)
        dst = os.path.join(target_dir, fn)
        shutil.move(src, dst)
        count += 1

    print(f"✅ Đã di chuyển thành công {count} ảnh khoảnh khắc vào thư mục ngày tương ứng.")


def migrate_recordings():
    print("--- BẮT ĐẦU DI CHUYỂN & ĐỔI TÊN VIDEO THEO KHOẢNG THỜI GIAN VÀ THƯ MỤC NGÀY ---")
    if not os.path.exists(RECORDINGS_DIR):
        return
    count = 0
    for fn in os.listdir(RECORDINGS_DIR):
        src = os.path.join(RECORDINGS_DIR, fn)
        if not os.path.isfile(src) or not fn.endswith((".mp4", ".jpg", ".jpeg")):
            continue
        
        # 1. Montage videos
        if fn.startswith("montage_"):
            m = re.search(r"montage_(\d{4})(\d{2})(\d{2})_", fn)
            if m:
                yyyy, mm, dd = m.groups()
                date_folder = f"{yyyy}-{mm}-{dd}"
            else:
                date_folder = datetime.fromtimestamp(os.path.getmtime(src)).strftime("%Y-%m-%d")
            new_fn = fn
        # 2. Standard recordings: YYYYMMDD_HHMMSS_event.ext
        elif re.match(r"^(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})_(.+)$", fn):
            m = re.match(r"^(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})_(.+)$", fn)
            yyyy, mm, dd, hh, min_, ss, rest = m.groups()
            date_folder = f"{yyyy}-{mm}-{dd}"
            try:
                end_dt = datetime.strptime(f"{yyyy}{mm}{dd}_{hh}{min_}{ss}", "%Y%m%d_%H%M%S")
                start_dt = end_dt - timedelta(seconds=30)
                sh_str = start_dt.strftime("%Hh%Mp%S")
                eh_str = end_dt.strftime("%Hh%Mp%S")
                ext = fn.split(".")[-1]
                event_name = rest.rsplit(".", 1)[0]
                new_fn = f"{sh_str}_den_{eh_str}_{event_name}.{ext}"
            except Exception:
                new_fn = fn
        # 3. Already has _den_
        elif "_den_" in fn:
            date_folder = datetime.fromtimestamp(os.path.getmtime(src)).strftime("%Y-%m-%d")
            new_fn = fn
        else:
            date_folder = datetime.fromtimestamp(os.path.getmtime(src)).strftime("%Y-%m-%d")
            new_fn = fn

        target_dir = os.path.join(RECORDINGS_DIR, date_folder)
        os.makedirs(target_dir, exist_ok=True)
        dst = os.path.join(target_dir, new_fn)
        shutil.move(src, dst)
        count += 1

    print(f"✅ Đã di chuyển và đổi tên thành công {count} video/thumbnail vào thư mục ngày tương ứng.")


def migrate_snapshots():
    print("--- BẮT ĐẦU DI CHUYỂN SNAPSHOTS THEO THƯ MỤC NGÀY ---")
    if not os.path.exists(SNAPSHOTS_DIR):
        return
    count = 0
    for fn in os.listdir(SNAPSHOTS_DIR):
        src = os.path.join(SNAPSHOTS_DIR, fn)
        if not os.path.isfile(src) or not fn.endswith((".jpg", ".png", ".jpeg")):
            continue
        
        # Check patterns: ts_event.jpg or YYYYMMDD_HHMMSS or moment_YYYYMMDD_HHMMSS
        m_moment = re.match(r"^moment_(\d{4})(\d{2})(\d{2})_", fn)
        m_standard = re.match(r"^(\d{4})(\d{2})(\d{2})_", fn)
        m_ts = re.match(r"^(\d{10})_", fn)

        if m_moment:
            yyyy, mm, dd = m_moment.groups()
            date_folder = f"{yyyy}-{mm}-{dd}"
        elif m_standard:
            yyyy, mm, dd = m_standard.groups()
            date_folder = f"{yyyy}-{mm}-{dd}"
        elif m_ts:
            ts = int(m_ts.group(1))
            date_folder = datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
        else:
            date_folder = datetime.fromtimestamp(os.path.getmtime(src)).strftime("%Y-%m-%d")

        target_dir = os.path.join(SNAPSHOTS_DIR, date_folder)
        os.makedirs(target_dir, exist_ok=True)
        dst = os.path.join(target_dir, fn)
        shutil.move(src, dst)
        count += 1
        if count % 10000 == 0:
            print(f"  ...đã chuyển {count} snapshots...")

    print(f"✅ Đã di chuyển thành công {count} ảnh snapshots vào thư mục ngày tương ứng.")


if __name__ == "__main__":
    migrate_moments()
    migrate_recordings()
    migrate_snapshots()
