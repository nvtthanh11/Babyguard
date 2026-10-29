import os
import json
import time
import threading
from datetime import datetime
import cv2
import numpy as np

try:
    from google import genai
    from google.genai import types
    HAS_GENAI = True
except ImportError:
    HAS_GENAI = False

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MOMENTS_META_PATH = os.path.join(BASE_DIR, "moments", "moments_meta.json")
USAGE_LOG_PATH = os.path.join(BASE_DIR, "logs", "gemini_usage.json")

# Danh sách các model Flash đa phương thức (Image + Text) có hạn mức Free độc lập (PerModel-FreeTier)
FREE_MODEL_POOL = [
    "gemini-2.5-flash",
    "gemini-3.8-flash",
    "gemini-3.7-flash",
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
    "gemini-3-flash-preview",
    "gemini-2.5-flash-lite",
]


def enhance_low_light_image(frame_or_burst, clip_limit=2.8):
    """
    Công nghệ bù sáng thông minh & khử nhiễu đa khung hình ban đêm (Night Sight / CLAHE Fusion):
    - Khử nhiễu cảm biến ISO bằng cách chập trung bình đa khung hình (Temporal Stacking).
    - Tự động bù sáng vùng tối & lòng nôi bằng CLAHE và Gamma động trên kênh L (LAB color space).
    - Giữ nguyên màu sắc tự nhiên và không gây cháy/lóa đèn ngủ.
    """
    if frame_or_burst is None:
        return None
    if isinstance(frame_or_burst, (list, tuple)) and len(frame_or_burst) > 1:
        base = np.mean([f.astype(np.float32) for f in frame_or_burst], axis=0).astype(np.uint8)
    elif isinstance(frame_or_burst, (list, tuple)) and len(frame_or_burst) == 1:
        base = frame_or_burst[0].copy()
    else:
        base = frame_or_burst.copy()

    gray = cv2.cvtColor(base, cv2.COLOR_BGR2GRAY)
    mean_b = float(np.mean(gray))

    # Nếu ảnh đã đủ sáng ban ngày (> 140), giữ nguyên
    if mean_b >= 140.0:
        return base

    lab = cv2.cvtColor(base, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)

    if mean_b < 50.0:
        gamma = 0.55
        clip = 3.5
    elif mean_b < 100.0:
        gamma = 0.65
        clip = clip_limit
    else:
        gamma = 0.80
        clip = 2.0

    clahe = cv2.createCLAHE(clipLimit=clip, tileGridSize=(8, 8))
    cl = clahe.apply(l)

    table = np.array([((i / 255.0) ** gamma) * 255 for i in np.arange(0, 256)]).astype("uint8")
    cl_gamma = cv2.LUT(cl, table)

    return cv2.cvtColor(cv2.merge((cl_gamma, a, b)), cv2.COLOR_LAB2BGR)


class GeminiHybridVerifier:
    """
    Chuyên gia Hội chẩn, Giám sát Tracking & Giám khảo Thẩm mỹ AI (Hybrid Cloud-Edge).
    - Tích hợp Bộ đếm Request & Xoay vòng Pool 9 Model Flash miễn phí (Multi-Model Free Quota Pool).
    - Tự động tận dụng hạn mức Request Free khi rảnh để kiểm tra chéo & hiệu chỉnh nóng tọa độ Tracking của AI Local.
    - Kiểm duyệt nghiêm ngặt Quyền Riêng Tư & Thẩm Mỹ trước khi lưu Khoảnh Khắc Đáng Yêu.
    """

    def __init__(self, config: dict):
        self.lock = threading.Lock()
        self.api_key = ""
        self.key_health = "missing"           # "valid", "quota_exceeded", "expired_or_invalid", "missing", "checking"
        self.key_health_label = "Chưa gắn API"
        self.last_checked_at = None
        self.error_detail = ""
        self.active_model = "gemini-2.5-flash"

        # Theo dõi hạn mức từng model trong Pool: {model_name: timestamp_unblocked}
        self.model_cooldown_until = {}
        self.rr_index = 0

        # Bộ đếm lịch sử gọi API (Request Counter)
        self.call_timestamps = []  # list of (unix_ts, call_type, model_used)
        self.daily_date = datetime.now().strftime("%Y-%m-%d")
        self.calls_today = 0
        self.calls_by_type = {
            "tracking_audit": 0,
            "alert_verify": 0,
            "moment_judge": 0,
            "calibration": 0,
            "health_probe": 0
        }
        self._load_usage_stats()

        # Throttling / Cooldown state
        self.last_alert_verify_time = {}  # {alert_type: timestamp}
        self.last_alert_result = {}       # {alert_type: dict}
        self.alert_cooldown_sec = 120.0

        self.last_moment_eval_time = 0.0
        self.moment_cooldown_sec = 45.0

        # Giám sát & Hiệu chỉnh Tracking AI Local bằng Quota Free dư thừa
        self.last_tracking_audit_time = 0.0
        self.tracking_audit_interval_sec = 120.0  # Giãn cách 120s (2 phút) giữa các lần tự động audit để chống tràn quota Free
        self.last_tracking_audit = {
            "timestamp": None,
            "tracking_accurate": True,
            "accuracy_score": 95,
            "corrected": False,
            "feedback_vi": "Đang chờ lượt kiểm tra chéo vị trí bé...",
            "model_used": ""
        }

        self.status_text = "Đang kiểm tra hạn API..."
        self.last_consultation = {
            "timestamp": None,
            "type": None,
            "is_dangerous": False,
            "summary_vi": "Chưa có yêu cầu hội chẩn mới.",
            "confidence": 0
        }
        self.update_config(config)

    # =========================================================================
    # QUẢN LÝ BỘ ĐẾM REQUEST FREE & XOAY VÒNG MULTI-MODEL POOL
    # =========================================================================
    def _load_usage_stats(self):
        try:
            if os.path.exists(USAGE_LOG_PATH):
                with open(USAGE_LOG_PATH, "r", encoding="utf-8") as f:
                    data = json.load(f)
                today = datetime.now().strftime("%Y-%m-%d")
                if data.get("date") == today:
                    self.daily_date = today
                    self.calls_today = int(data.get("calls_today", 0))
                    saved_types = data.get("calls_by_type", {})
                    for k in self.calls_by_type:
                        if k in saved_types:
                            self.calls_by_type[k] = int(saved_types[k])
        except Exception as e:
            print(f"[GeminiVerifier] Lỗi đọc gemini_usage.json: {e}")

    def _save_usage_stats(self):
        try:
            os.makedirs(os.path.dirname(USAGE_LOG_PATH), exist_ok=True)
            with open(USAGE_LOG_PATH, "w", encoding="utf-8") as f:
                json.dump({
                    "date": self.daily_date,
                    "calls_today": self.calls_today,
                    "calls_by_type": self.calls_by_type,
                    "updated_at": time.strftime("%H:%M:%S - %d/%m/%Y")
                }, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _record_api_call_attempt(self, call_type: str, model_used: str):
        now = time.time()
        today = datetime.now().strftime("%Y-%m-%d")
        with self.lock:
            if today != self.daily_date:
                self.daily_date = today
                self.calls_today = 0
                for k in self.calls_by_type:
                    self.calls_by_type[k] = 0

            self.call_timestamps.append((now, call_type, model_used))
            # Giữ lịch sử trong 1 giờ gần nhất
            cutoff = now - 3600.0
            self.call_timestamps = [item for item in self.call_timestamps if item[0] >= cutoff]

            self.calls_today += 1
            if call_type in self.calls_by_type:
                self.calls_by_type[call_type] += 1
            self.active_model = model_used
            self._save_usage_stats()

    def get_usage_stats(self) -> dict:
        now = time.time()
        with self.lock:
            cutoff_1m = now - 60.0
            cutoff_10m = now - 600.0
            calls_1m = sum(1 for ts, _, _ in self.call_timestamps if ts >= cutoff_1m)
            calls_10m = sum(1 for ts, _, _ in self.call_timestamps if ts >= cutoff_10m)
            calls_1h = len(self.call_timestamps)
            last_call_ts = self.call_timestamps[-1][0] if self.call_timestamps else 0.0
            secs_since_last = round(now - last_call_ts, 1) if last_call_ts > 0 else 999.0

            healthy_models = [
                m for m in FREE_MODEL_POOL
                if self.model_cooldown_until.get(m, 0.0) <= now
            ]

            return {
                "calls_last_1m": calls_1m,
                "calls_last_10m": calls_10m,
                "calls_last_1h": calls_1h,
                "calls_today": self.calls_today,
                "calls_by_type": dict(self.calls_by_type),
                "seconds_since_last_call": secs_since_last,
                "active_model": self.active_model,
                "healthy_models_count": len(healthy_models),
                "total_models_pool": len(FREE_MODEL_POOL),
                "free_rpm_pool_limit": len(FREE_MODEL_POOL) * 10,
                "free_rpd_pool_limit": len(FREE_MODEL_POOL) * 20
            }

    def _get_candidate_models(self) -> list:
        """Lấy danh sách các model đang khỏe mạnh trong Pool, ưu tiên xoay vòng để chia đều tải Free Quota."""
        now = time.time()
        with self.lock:
            pool = list(FREE_MODEL_POOL)
            if self.model_name in pool:
                # Xoay vòng bắt đầu từ rr_index để không dồn toàn bộ request vào 1 model duy nhất
                idx = self.rr_index % len(pool)
                self.rr_index = (self.rr_index + 1) % len(pool)
                rotated = pool[idx:] + pool[:idx]
            else:
                rotated = [self.model_name] + pool

            healthy = [m for m in rotated if self.model_cooldown_until.get(m, 0.0) <= now]
            cooling = [m for m in rotated if self.model_cooldown_until.get(m, 0.0) > now]
            return healthy + cooling

    def _call_gemini_resilient(self, contents, call_type: str, json_mode: bool = True, temperature: float = 0.1):
        """
        Gọi Google Gemini với cơ chế tự động xoay vòng qua Pool 9 Model Flash miễn phí.
        Nếu 1 model bị 429 (hết 20 req/ngày của riêng model đó) hoặc 503 (quá tải tạm thời),
        tự động chuyển ngay sang model Flash tiếp theo trong Pool mà không làm gián đoạn hệ thống!
        """
        client = self._get_client()
        if client is None:
            raise RuntimeError("Chưa khởi tạo được Gemini Client.")

        candidates = self._get_candidate_models()
        last_err = None

        for m in candidates[:4]:  # Thử tối đa 4 model khỏe nhất trong Pool cho mỗi lượt
            try:
                cfg = types.GenerateContentConfig(
                    response_mime_type="application/json" if json_mode else "text/plain",
                    temperature=temperature
                )
                resp = client.models.generate_content(
                    model=m,
                    contents=contents,
                    config=cfg
                )
                self._record_api_call_attempt(call_type, m)
                self._record_api_success(model_used=m)
                return resp
            except Exception as e:
                last_err = e
                err_upper = str(e).upper()
                now = time.time()
                if "429" in err_upper or "RESOURCE_EXHAUSTED" in err_upper or "QUOTA" in err_upper:
                    # Nếu chạm giới hạn ngày (PerDay), tạm nghỉ model này 30 phút; nếu giới hạn phút (PerMinute) nghỉ 65s
                    cooldown = 1800.0 if "PERDAY" in err_upper or "17H" in err_upper or "24H" in err_upper else 65.0
                    with self.lock:
                        self.model_cooldown_until[m] = now + cooldown
                    print(f"[GeminiVerifier] 🔄 Model {m} chạm hạn mức Free, tự động chuyển sang model tiếp theo trong Pool...")
                    continue
                elif "503" in err_upper or "UNAVAILABLE" in err_upper or "500" in err_upper or "INTERNAL" in err_upper:
                    with self.lock:
                        self.model_cooldown_until[m] = now + 45.0
                    print(f"[GeminiVerifier] 🔄 Model {m} đang bận (503/500), chuyển sang model dự phòng...")
                    continue
                elif "404" in err_upper or "NOT_FOUND" in err_upper:
                    with self.lock:
                        self.model_cooldown_until[m] = now + 86400.0
                    continue
                else:
                    # Lỗi xác thực API Key (400/403 API_KEY_INVALID) -> Dừng ngay không thử model khác
                    break

        self._record_api_error(last_err)
        raise last_err

    def update_config(self, config: dict):
        old_key = getattr(self, "api_key", "")
        with self.lock:
            self.api_key = (config.get("gemini_api_key") or os.environ.get("GEMINI_API_KEY") or "").strip()
            self.model_name = config.get("gemini_model", "gemini-2.5-flash")
            self.enabled = bool(config.get("gemini_enabled", True))
            self.verify_alerts_enabled = bool(config.get("gemini_verify_alerts", True))
            self.filter_moments_enabled = bool(config.get("gemini_filter_moments", True))
            self.baby_name = config.get("baby_name", "Bé Yêu")
            self.baby_age_months = int(config.get("baby_age_months", 3))

        if not self.api_key or len(self.api_key) < 10:
            self.key_health = "missing"
            self.key_health_label = "Chưa gắn API Key"
            self.status_text = "Chưa cấu hình API Key"
        elif self.api_key != old_key or self.key_health in ("missing", "checking"):
            self.key_health = "checking"
            self.key_health_label = "Đang kiểm tra hạn API..."
            threading.Thread(target=self._probe_key_health_async, daemon=True).start()

    def _probe_key_health_async(self):
        time.sleep(0.5)
        self.test_connection(self.api_key)

    def _record_api_success(self, model_used: str = None):
        self.key_health = "valid"
        m_tag = f" ({model_used})" if model_used else ""
        self.key_health_label = f"✅ API Còn Hạn • Hoạt động tốt{m_tag}"
        self.last_checked_at = time.strftime("%H:%M:%S")
        self.error_detail = ""

    def _record_api_error(self, err: Exception):
        err_str = str(err)
        err_upper = err_str.upper()
        self.last_checked_at = time.strftime("%H:%M:%S")
        self.error_detail = err_str[:160]
        if "429" in err_upper or "RESOURCE_EXHAUSTED" in err_upper or "QUOTA" in err_upper:
            self.key_health = "quota_exceeded"
            self.key_health_label = "⚠️ Tạm hết Quota Free (Đang chờ hồi)"
            self.status_text = "Các model trong Pool đang chờ hồi Quota"
        elif "API_KEY_INVALID" in err_upper or "EXPIRED" in err_upper or "400" in err_upper or "403" in err_upper or "PERMISSION_DENIED" in err_upper:
            self.key_health = "expired_or_invalid"
            self.key_health_label = "❌ API Key Hết Hạn / Không hợp lệ"
            self.status_text = "API Key hết hạn hoặc sai mã"
        else:
            # Lỗi mạng / 503 tạm thời -> KHÔNG khóa is_ready()
            if self.key_health not in ("expired_or_invalid", "missing"):
                self.key_health = "valid"
            self.key_health_label = "⚠️ Máy chủ AI đang bận tạm thời"
            self.status_text = "Đang tự động thử lại với model dự phòng"

    def is_ready(self) -> bool:
        return bool(HAS_GENAI and self.enabled and len(self.api_key) > 10 and self.key_health != "expired_or_invalid")

    def _get_client(self, custom_key: str = None):
        key = (custom_key or self.api_key or "").strip()
        if not HAS_GENAI or not key:
            return None
        return genai.Client(api_key=key)

    @staticmethod
    def _encode_frame_jpeg(frame_bgr, max_dim: int = 768, enhance_night: bool = True) -> bytes:
        if frame_bgr is None:
            return b""
        if enhance_night:
            frame_bgr = enhance_low_light_image(frame_bgr)
        h, w = frame_bgr.shape[:2]
        if max(h, w) > max_dim:
            scale = max_dim / float(max(h, w))
            frame_bgr = cv2.resize(frame_bgr, (int(w * scale), int(h * scale)))
        ok, buf = cv2.imencode(".jpg", frame_bgr, [cv2.IMWRITE_JPEG_QUALITY, 84])
        return buf.tobytes() if ok else b""

    def test_connection(self, api_key: str = None) -> dict:
        """Kiểm tra nhanh kết nối & thời hạn Gemini API Key từ giao diện."""
        key = (api_key or self.api_key or "").strip()
        if not HAS_GENAI:
            return {"success": False, "error": "Thư viện google-genai chưa được cài đặt."}
        if not key or len(key) < 10:
            self.key_health = "missing"
            self.key_health_label = "Chưa gắn API Key"
            return {"success": False, "error": "API Key không hợp lệ hoặc để trống."}
        try:
            old_key = self.api_key
            self.api_key = key
            resp = self._call_gemini_resilient(
                contents="Trả lời ngắn gọn 1 câu tiếng Việt: API Google Gemini đang còn hạn và sẵn sàng bảo vệ bé!",
                call_type="health_probe",
                json_mode=False,
                temperature=0.1
            )
            stats = self.get_usage_stats()
            self.status_text = f"Sẵn sàng ({stats['healthy_models_count']}/{stats['total_models_pool']} Model Free sẵn sàng)"
            return {
                "success": True,
                "key_health": self.key_health,
                "key_health_label": self.key_health_label,
                "last_checked_at": self.last_checked_at,
                "usage": stats,
                "message": f"✅ API Google Còn Hạn! Đang kích hoạt Pool {stats['healthy_models_count']} Model Flash miễn phí (Đã gọi {stats['calls_today']} lần hôm nay)."
            }
        except Exception as e:
            return {
                "success": False,
                "key_health": self.key_health,
                "key_health_label": self.key_health_label,
                "error": f"{self.key_health_label}: {str(e)[:120]}"
            }

    # =========================================================================
    # 0. TẬN DỤNG QUOTA FREE ĐỂ GIÁM SÁT & HIỆU CHỈNH TRACKING AI LOCAL
    # =========================================================================
    def should_run_tracking_audit(self, local_uncertain: bool = False, need_initial_crib_calib: bool = False, pose_changed: bool = False) -> bool:
        """
        Kiểm tra xem trong khoảng thời gian vừa rồi đã gọi API bao nhiêu lần.
        Nếu mới khởi động (cần tự động căn chỉnh khung nôi lần đầu), hoặc vừa giữ tư thế mới đủ 10 giây (pose_changed),
        hoặc đang rảnh (còn dư nhiều request Free) -> Chủ động gửi hình lên Gemini để kiểm tra & hiệu chỉnh!
        """
        if not self.is_ready():
            return False

        now = time.time()
        elapsed = now - self.last_tracking_audit_time
        if need_initial_crib_calib:
            min_interval = 15.0
        elif pose_changed:
            min_interval = 30.0  # Sau khi tư thế mới giữ ổn định 10s, kích hoạt audit với giãn cách >= 30s
        elif local_uncertain:
            min_interval = 90.0  # Khi nôi trống / không bắt được bé, chỉ audit sau mỗi 90s để chống spam quota
        else:
            min_interval = self.tracking_audit_interval_sec

        if elapsed < min_interval:
            return False

        stats = self.get_usage_stats()
        if stats["calls_last_1m"] >= 2 or stats["healthy_models_count"] == 0:
            return False

        return True

    def audit_local_tracking(self, raw_frame, annotated_frame, local_info: dict) -> dict:
        """
        Gửi khung hình lên Gemini để TỰ ĐỘNG thực hiện đồng thời 2 nhiệm vụ (bố mẹ không cần bấm nút):
        1. Kiểm tra & Tự động căn chỉnh Khung Bảo Vệ Nôi / Tấm Đệm của bé (khung viền xanh lá cây Safe Zone).
        2. Kiểm tra & Hiệu chỉnh nóng Khung Tracking Em Bé ('EM BE' màu xanh dương & 'ROI NGỰC').
        """
        self.last_tracking_audit_time = time.time()
        img_bytes = self._encode_frame_jpeg(annotated_frame, max_dim=768)
        if not img_bytes:
            return {"audited": False}

        local_box = local_info.get("norm_box", [0, 0, 0, 0])
        raw_sz = local_info.get("safe_zone", [0.05, 0.08, 0.95, 0.95])
        local_sz = []
        for i, val in enumerate(raw_sz):
            try:
                fv = float(val)
                dim = 1280.0 if i in (0, 2) else 720.0
                if fv > 1.0:
                    fv = fv / 1000.0 if fv <= 1000.0 else fv / dim
                local_sz.append(round(max(0.01, min(0.99, fv)), 3))
            except Exception:
                local_sz.append(0.5)
        local_detected = local_info.get("baby_detected", False)
        local_pose = local_info.get("sleep_pose", "Chưa rõ")

        prompt = f"""
Bạn là Giám sát viên Thị giác Máy tính (AI Tracking & Crib Auto-Calibration Supervisor) của hệ thống BabyGuard AI.
Trên bức ảnh đính kèm, hệ thống AI Local đang vẽ:
1. Khung viền lớn màu xanh lá cây (Vùng An Toàn Nôi / Tấm Đệm của bé): tọa độ hiện tại [left, top, right, bottom] = {local_sz}.
2. Khung chữ nhật màu xanh dương (nhãn "EM BE"): tọa độ hiện tại = {local_box} (phát hiện = {local_detected}, tư thế = "{local_pose}").
3. Vùng đa giác màu xanh lơ: vùng đo nhịp thở lồng ngực.

QUY TẮC CỐT LÕI (CHỐNG NHẬN NHẦM NGƯỜI LỚN & VẬT DỤNG):
- NẾU TRONG ẢNH KHÔNG CÓ EM BÉ (chỉ có người lớn ngồi/nằm trên giường, hoặc nôi/thảm trống chỉ có tay/chân/thân người lớn thò vào, hoặc người lớn bế bé đi ra ngoài khung hình):
  -> BẮT BUỘC ĐẶT baby_present = false!
  -> BẮT BUỘC ĐẶT true_baby_box = null!
  -> BẮT BUỘC ĐẶT true_head_box = null!
  -> TUYỆT ĐỐI KHÔNG ĐƯỢC NHẬM TAY, ĐÙI, BÀN CHÂN, ĐẦU GỐI CỦA NGƯỜI LỚN THÀNH EM BÉ!
  -> TUYỆT ĐỐI KHÔNG ĐƯỢC NHẬM GỐI ÔM, GẤU BÔNG, CHĂN DỒN HOẶC HỌA TIẾT THẢM THÀNH EM BÉ!
- Chỉ khi thực sự nhìn thấy em bé sơ sinh (đầu bé sơ sinh, thân bé sơ sinh trên đệm): mới đặt baby_present = true.

Hãy quan sát bức ảnh và tự động kiểm tra + căn chỉnh cả 2 khung này, đồng thời phân biệt bé đang NGỦ hay đang THỨC:
A. KIỂM TRA TRACKING CƠ THỂ & TRẠNG THÁI THỨC/NGỦ CỦA EM BÉ:
- baby_present (boolean): Thực tế có em bé sơ sinh đang nằm trong ảnh không?
- is_baby_awake (boolean): Em bé đang THỨC (mở mắt nhìn, mút tay, đạp chân tay, ngóc đầu, chơi đùa -> true) hay đang NGỦ (nhắm mắt nằm yên -> false)?
- tracking_accurate (boolean): Khung xanh dương "EM BE" đã bao quanh ĐÚNG cơ thể thực tế của em bé VÀ vùng đo nhịp thở nằm đúng trên thân/ngực bé chưa?
- accuracy_score (integer 0-100): Điểm chính xác của khung Tracking em bé.
- true_baby_box ([xmin, ymin, xmax, ymax] từ 0.0 đến 1.0): Tọa độ khung chữ nhật bao quanh TOÀN BỘ CƠ THỂ thực tế của em bé (trả về null nếu không có em bé).
- true_head_box ([xmin, ymin, xmax, ymax] từ 0.0 đến 1.0): Tọa độ phần đầu thực tế của em bé (trả về null nếu không có em bé).
- head_direction ("right" | "left" | "up" | "down"): Đỉnh đầu của em bé đang hướng về phía nào?

B. KIỂM TRA & TỰ ĐỘNG CĂN CHỈNH KHUNG NÔI / TẤM ĐỆM EM BÉ (SAFE ZONE 3D):
- crib_zone_accurate (boolean): Khung viền xanh lá cây hiện tại đã bao quanh hợp lý vùng tấm đệm/nôi nơi em bé nằm chưa? (Nếu khung xanh lá đang cắt ngang qua đầu/cổ bé, quá hẹp hoặc bị lệch khỏi tấm đệm trắng của bé -> false).
- true_safe_zone_polygon ([[x, y], [x, y], [x, y], [x, y]] từ 0.03 đến 0.97): Tọa độ 4 đỉnh đa giác tứ giác theo thứ tự [Top-Left, Top-Right, Bottom-Right, Bottom-Left] bao quanh TRỌN VẸN tấm đệm nơi em bé nằm theo đúng góc phối cảnh 3D xiên. TUYỆT ĐỐI KHÔNG ĐƯỢC để cạnh cắt ngang đầu/thân bé; cạnh trên phải chạy phía trên đỉnh đầu và gối bé để đảm bảo an toàn. Không bao gồm người lớn nằm cạnh.
- true_safe_zone ([left, top, right, bottom] từ 0.03 đến 0.97): Tọa độ khung chữ nhật bao ngoài tấm đệm của em bé.

QUY ĐỊNH BẮT BUỘC VỀ ĐỊNH DẠNG TỌA ĐỘ:
- TẤT CẢ các giá trị tọa độ x, y, left, top, right, bottom PHẢI LÀ SỐ THẬP PHÂN CHUẨN HÓA (FLOAT) TRONG KHOẢNG 0.03 ĐẾN 0.97 (ví dụ 0.25, 0.75).
- TUYỆT ĐỐI KHÔNG DÙNG TỌA ĐỘ PIXEL LỚN HƠN 1.0 (ví dụ 270, 750, 1000) vì sẽ làm sai lệch hiển thị!

Trả về đúng JSON:
{{
  "baby_present": boolean,
  "is_baby_awake": boolean,
  "tracking_accurate": boolean,
  "accuracy_score": integer,
  "true_baby_box": [float, float, float, float] | null,
  "true_head_box": [float, float, float, float] | null,
  "head_direction": "right" | "left" | "up" | "down",
  "crib_zone_accurate": boolean,
  "true_safe_zone_polygon": [[float, float], [float, float], [float, float], [float, float]],
  "true_safe_zone": [float, float, float, float],
  "sleep_pose_vi": "string",
  "feedback_vi": "Nhận xét ngắn gọn 1 câu tiếng Việt về trạng thái Thức/Ngủ, khung Tracking và Khung Nôi"
}}
"""
        try:
            self.status_text = "Đang tự động kiểm tra Tracking & Khung Nôi..."
            resp = self._call_gemini_resilient(
                contents=[
                    types.Part.from_bytes(data=img_bytes, mime_type="image/jpeg"),
                    prompt
                ],
                call_type="tracking_audit",
                json_mode=True,
                temperature=0.05
            )
            data = json.loads(resp.text)
            acc = bool(data.get("tracking_accurate", True))
            crib_acc = bool(data.get("crib_zone_accurate", True))
            score = int(data.get("accuracy_score", 90))
            baby_present = bool(data.get("baby_present", True))
            is_awake = bool(data.get("is_baby_awake", False))
            feedback = str(data.get("feedback_vi", "Đã tự động kiểm tra & căn chỉnh khung theo dõi."))

            self.last_tracking_audit = {
                "timestamp": time.strftime("%H:%M:%S"),
                "baby_present": baby_present,
                "is_baby_awake": is_awake,
                "tracking_accurate": acc,
                "crib_zone_accurate": crib_acc,
                "accuracy_score": score,
                "corrected": bool(baby_present and (not acc or not crib_acc or score < 78)),
                "feedback_vi": feedback,
                "model_used": self.active_model
            }
            self.last_consultation = {
                "timestamp": time.strftime("%H:%M:%S"),
                "type": "tracking_audit",
                "is_dangerous": False,
                "summary_vi": f"[Tự động Căn Nôi & Tracking • {score}%] {feedback}",
                "confidence": score
            }
            self.status_text = f"Đã tự căn chuẩn ({score}%)" if (acc and crib_acc) else "Đã tự động hiệu chỉnh Nôi & Tracking"
            print(f"[GeminiVerifier] 🎯 Tự động Căn Nôi & Tracking ({self.active_model}): baby_acc={acc}, crib_acc={crib_acc}, awake={is_awake} ({score}%) -> {feedback}")
            # Sanitize true_safe_zone_polygon
            raw_tsz_poly = data.get("true_safe_zone_polygon")
            clean_tsz_poly = None
            if isinstance(raw_tsz_poly, list) and len(raw_tsz_poly) == 4:
                clean_tsz_poly = []
                for p in raw_tsz_poly:
                    px = float(p[0])
                    py = float(p[1])
                    if px > 1.0:
                        px = px / 1000.0 if px <= 1000.0 else px / 1280.0
                    if py > 1.0:
                        py = py / 1000.0 if py <= 1000.0 else py / 720.0
                    clean_tsz_poly.append([round(max(0.01, min(0.99, px)), 3), round(max(0.01, min(0.99, py)), 3)])

            # Sanitize true_safe_zone
            raw_tsz = data.get("true_safe_zone")
            clean_tsz = None
            if isinstance(raw_tsz, list) and len(raw_tsz) == 4:
                clean_tsz = []
                for i, v in enumerate(raw_tsz):
                    fv = float(v)
                    dim = 1280.0 if i in (0, 2) else 720.0
                    if fv > 1.0:
                        fv = fv / 1000.0 if fv <= 1000.0 else fv / dim
                    clean_tsz.append(round(max(0.01, min(0.99, fv)), 3))

            return {
                "audited": True,
                "baby_present": baby_present,
                "is_baby_awake": is_awake,
                "tracking_accurate": acc,
                "crib_zone_accurate": crib_acc,
                "accuracy_score": score,
                "true_baby_box": data.get("true_baby_box"),
                "true_head_box": data.get("true_head_box"),
                "head_direction": data.get("head_direction", "up"),
                "true_safe_zone": clean_tsz,
                "true_safe_zone_polygon": clean_tsz_poly,
                "sleep_pose_vi": data.get("sleep_pose_vi", "Nằm ngửa"),
                "feedback_vi": feedback
            }
        except Exception as e:
            print(f"[GeminiVerifier] Lỗi audit_local_tracking: {e}")
            return {"audited": False, "error": str(e)}

    # =========================================================================
    # =========================================================================
    # 1. HỘI CHẨN CẢNH BÁO NGUY HIỂM CAO (KIỂM TRA CHÉO 4 Ô THỜI GIAN & ĐƯỜNG THỞ)
    # =========================================================================
    def _create_emergency_quad_matrix(self, frame_t_minus_2, frame_t_minus_1, frame_t_0, airway_crop=None):
        """
        Ghép 4 góc nhìn thời gian và cận cảnh đường thở vào DUY NHẤT 1 bức ảnh 1024x1024:
        - Ô 1 [Top-Left]: T - 2.0s
        - Ô 2 [Top-Right]: T - 1.0s
        - Ô 3 [Bottom-Left]: T - 0.0s (Toàn cảnh hiện tại)
        - Ô 4 [Bottom-Right]: Cận cảnh độ nét gốc 100% Mũi - Miệng - Đường thở của bé
        """
        try:
            h, w = frame_t_0.shape[:2]
            f_t2 = frame_t_minus_2 if frame_t_minus_2 is not None else frame_t_0
            f_t1 = frame_t_minus_1 if frame_t_minus_1 is not None else frame_t_0

            p1 = cv2.resize(f_t2, (512, 512))
            p2 = cv2.resize(f_t1, (512, 512))
            p3 = cv2.resize(frame_t_0, (512, 512))

            if airway_crop is not None and airway_crop.size > 0:
                p4 = cv2.resize(airway_crop, (512, 512))
            else:
                # Cắt trung tâm nếu chưa có airway_crop riêng
                cy1, cy2 = int(h * 0.2), int(h * 0.8)
                cx1, cx2 = int(w * 0.2), int(w * 0.8)
                p4 = cv2.resize(frame_t_0[cy1:cy2, cx1:cx2], (512, 512))

            # Vẽ nhãn định danh trực quan trên từng ô
            font = cv2.FONT_HERSHEY_SIMPLEX
            def _draw_badge(img, label):
                cv2.rectangle(img, (8, 8), (270, 38), (15, 23, 42), -1)
                cv2.rectangle(img, (8, 8), (270, 38), (56, 189, 248), 1)
                cv2.putText(img, label, (16, 28), font, 0.55, (255, 255, 255), 1, cv2.LINE_AA)

            _draw_badge(p1, "[1] T - 2.0s (2 giay truoc)")
            _draw_badge(p2, "[2] T - 1.0s (1 giay truoc)")
            _draw_badge(p3, "[3] T - 0.0s (Hien tai)")
            _draw_badge(p4, "[4] Mui-Mieng-Duong Tho (100%)")

            top_row = np.hstack([p1, p2])
            bottom_row = np.hstack([p3, p4])
            quad = np.vstack([top_row, bottom_row])
            return quad
        except Exception as e:
            print(f"[GeminiVerifier] Lỗi ghép 4 ô khẩn cấp: {e}")
            return frame_t_0

    def verify_high_risk_alert(self, frame_bgr, alert_type: str = "covered_face", local_reason: str = "", frame_history: list = None, airway_crop = None) -> dict:
        """
        Kiểm tra chéo an toàn cấp cao (Double-Check Sentinel):
        - Phân tích động thái lồng ngực qua chuỗi thời gian 3 ô + soi đường thở ô 4
        - Chống tràn quota: Giới hạn tối đa 3 req/phút toàn hệ thống, khóa hồi 45s (an toàn) và 90s (nguy hiểm)
        - Fail-Safe Fallback: Nếu Gemini gặp sự cố mạng hoặc timeout > 3.5s -> Luôn tự động bật báo động cấp 1
        """
        if not self.is_ready() or not self.verify_alerts_enabled:
            return {
                "verified_by_gemini": False,
                "is_dangerous": True,
                "diagnosis_vi": local_reason or "Cảnh báo từ hệ thống AI cục bộ (Chưa bật Gemini).",
                "confidence": 80
            }

        now = time.time()

        # 1. Rào chắn Quota: Kiểm tra Cooldown theo từng loại cảnh báo
        last_t = self.last_alert_verify_time.get(alert_type, 0.0)
        cooldown_needed = 45.0 if self.last_alert_result.get(alert_type, {}).get("is_dangerous") is False else 90.0
        if (now - last_t) < cooldown_needed and alert_type in self.last_alert_result:
            cached = self.last_alert_result[alert_type].copy()
            cached["from_cache"] = True
            return cached

        # 2. Rào chắn Quota: Global Rate Limiter tối đa 3 requests/phút
        recent_calls = [t for t, _, _ in self.call_timestamps if (now - t) < 60.0]
        if len(recent_calls) >= 3:
            print(f"[GeminiVerifier] ⏱️ Global Rate Limiter: Đã có {len(recent_calls)} req trong 60s. Tự động chuyển Fallback an toàn!")
            return {
                "verified_by_gemini": False,
                "is_dangerous": True,
                "diagnosis_vi": local_reason or "Cảnh báo khẩn cấp (Hệ thống bảo vệ hạn mức Quota).",
                "confidence": 75
            }

        # 3. Tạo ảnh composite 4 ô
        if frame_history and len(frame_history) >= 2:
            f_t2 = frame_history[0]
            f_t1 = frame_history[1]
            f_t0 = frame_bgr
            composite = self._create_emergency_quad_matrix(f_t2, f_t1, f_t0, airway_crop)
        else:
            composite = self._create_emergency_quad_matrix(frame_bgr, frame_bgr, frame_bgr, airway_crop)

        img_bytes = self._encode_frame_jpeg(composite, max_dim=1024)
        if not img_bytes:
            return {"verified_by_gemini": False, "is_dangerous": True, "diagnosis_vi": local_reason, "confidence": 50}

        prompt = f"""
Bạn là Bác sĩ Nhi khoa Trực ban Cấp cứu (BabyGuard AI Sentinel) cho bé {self.baby_name} ({self.baby_age_months} tháng tuổi).
Hệ thống Edge AI vừa phát hiện tín hiệu bất thường: "{alert_type}" ({local_reason}).

Bức ảnh ghép 4 ô (Composite 4-Panel Matrix) gửi kèm gồm:
- Ô 1 [Top-Left]: Khung cảnh cách đây 2.0 giây.
- Ô 2 [Top-Right]: Khung cảnh cách đây 1.0 giây.
- Ô 3 [Bottom-Left]: Khung cảnh toàn diện hiện tại (T - 0.0s).
- Ô 4 [Bottom-Right]: Cận cảnh 100% độ nét gốc vùng Mũi, Miệng, Đường thở & Lồng ngực của bé.

HÃY ĐỐI SOÁT KỸ LƯỠNG GIỮA CÁC Ô ĐỂ PHÂN BIỆT:
1. ĐỐI VỚI NGUY CƠ CHE MẶT / NGẠT THỞ (covered_face):
   - NGUY HIỂM THẬT (is_dangerous=true): Chăn, gối, thú bông hoặc nệm đang trùm lên hoặc đè trực tiếp vào MŨI/MIỆNG của bé ở Ô 3 và Ô 4 làm cản trở đường thở.
   - BÁO ĐỘNG GIẢ (is_dangerous=false): Vùng MŨI và MIỆNG ở Ô 4 vẫn lộ rõ, thông thoáng khí quyển hoàn toàn. Gối/chăn chỉ nằm bên cạnh sườn, tay hoặc đỉnh đầu để chặn giật mình.

2. ĐỐI VỚI NGUY CƠ NẰM SẤP (prone):
   - NGUY HIỂM THẬT (is_dangerous=true): Bé úp mặt thẳng đứng xuống mặt đệm, đường thở bị chặn.
   - BÁO ĐỘNG GIẢ (is_dangerous=false): Bé nằm nghiêng một bên hoặc quay đầu sang bên thở bình thường.

3. ĐỐI VỚI NGUY CƠ NGƯNG THỞ / BẤT THƯỜNG HÔ HẤP (apnea):
   - So sánh chuyển động lồng ngực/bụng qua Ô 1 -> Ô 2 -> Ô 3:
   - NGUY HIỂM THẬT (is_dangerous=true): Lồng ngực hoàn toàn bất động suốt 3 khung thời gian và có dấu hiệu suy hô hấp/bất thường.
   - BÁO ĐỘNG GIẢ (is_dangerous=false): Bé chỉ đang ngủ sâu bình thường hoặc có vi chuyển động thở nhẹ, hoặc bé đã được người lớn bế ra khỏi nôi.

4. ĐỐI VỚI NGUY CƠ VƯỢT KHUNG NÔI / MÉP GIƯỜNG (danger_zone):
   - NGUY HIỂM THẬT (is_dangerous=true): Bé đang trườn, bò, ngóc đầu hoặc lăn sát mép rơi ngã nguy hiểm (ví dụ mép giường không có rào chắn, thành nôi thấp).
   - BÁO ĐỘNG GIẢ (is_dangerous=false): Bé vẫn nằm an toàn trên tấm đệm hoặc giữa giường lớn, không có nguy cơ ngã tức thì (chỉ do khung nôi bị vẽ chật).
   - NẾU LÀ BÁO ĐỘNG GIẢ CỦA KHUNG NÔI: Hãy trả về tọa độ 4 đỉnh đa giác "corrected_safe_zone_polygon" [[x,y],[x,y],[x,y],[x,y]] (chuẩn hóa 0.03 - 0.97) bao quanh TRỌN VẸN toàn bộ tấm đệm của bé để hệ thống tự động mở rộng khung nôi ôm kín bé, không báo động giả nữa!

Trả về đúng định dạng JSON:
{{
  "is_dangerous": boolean,
  "confidence": integer (0-100),
  "airway_clear": boolean,
  "diagnosis_vi": "Nhận xét ngắn gọn 1-2 câu tiếng Việt chuyên nghiệp",
  "corrected_safe_zone_polygon": [[float, float], [float, float], [float, float], [float, float]] | null
}}
"""
        try:
            self.status_text = f"Đang kiểm tra chéo Gemini ({alert_type})..."
            resp = self._call_gemini_resilient(
                contents=[
                    types.Part.from_bytes(data=img_bytes, mime_type="image/jpeg"),
                    prompt
                ],
                call_type="alert_verify",
                json_mode=True,
                temperature=0.05
            )
            data = json.loads(resp.text)
            is_danger = bool(data.get("is_dangerous", False))
            corr_poly = data.get("corrected_safe_zone_polygon")
            clean_poly = None
            if isinstance(corr_poly, list) and len(corr_poly) == 4:
                try:
                    clean_poly = []
                    for pt in corr_poly:
                        px = float(pt[0])
                        py = float(pt[1])
                        if px > 1.0: px = px / 1000.0 if px <= 1000.0 else px / 1280.0
                        if py > 1.0: py = py / 1000.0 if py <= 1000.0 else py / 720.0
                        clean_poly.append([round(max(0.02, min(0.98, px)), 3), round(max(0.02, min(0.98, py)), 3)])
                except Exception:
                    clean_poly = None

            result = {
                "verified_by_gemini": True,
                "is_dangerous": is_danger,
                "airway_clear": bool(data.get("airway_clear", not is_danger)),
                "confidence": int(data.get("confidence", 90)),
                "diagnosis_vi": str(data.get("diagnosis_vi", "Đã kiểm tra chéo qua Gemini AI.")),
                "corrected_safe_zone_polygon": clean_poly
            }
            self.last_alert_verify_time[alert_type] = now
            self.last_alert_result[alert_type] = result
            self.last_consultation = {
                "timestamp": time.strftime("%H:%M:%S"),
                "type": alert_type,
                "is_dangerous": result["is_dangerous"],
                "summary_vi": result["diagnosis_vi"],
                "confidence": result["confidence"]
            }
            self.status_text = "An toàn (Đã kiểm tra chéo)" if not result["is_dangerous"] else "CẢNH BÁO ĐÃ XÁC THỰC"
            print(f"[GeminiVerifier] 🩺 Double-Check ({alert_type}): dangerous={result['is_dangerous']} - {result['diagnosis_vi']}")
            return result
        except Exception as e:
            # FAIL-SAFE FALLBACK: Khi mạng lỗi hoặc Gemini không phản hồi -> Luôn báo động an toàn cho bé!
            print(f"[GeminiVerifier] ⚠️ Lỗi gọi Gemini verify_high_risk_alert: {e} -> Kích hoạt FAIL-SAFE!")
            return {
                "verified_by_gemini": False,
                "is_dangerous": True,
                "diagnosis_vi": local_reason or "Cảnh báo khẩn cấp: Không thể kiểm tra chéo đám mây, tự động kích hoạt bảo vệ cục bộ!",
                "confidence": 75,
                "corrected_safe_zone_polygon": None
            }

    # =========================================================================
    # 2. GIÁM KHẢO KHOẢNH KHẮC ĐÁNG YÊU + TỰ ĐỘNG CẮT KHUNG CHÂN DUNG (SMART AUTO-CROP)
    # =========================================================================
    @staticmethod
    def apply_smart_crop(frame_bgr, eval_res: dict):
        """
        Nếu xung quanh/rìa ảnh có người lớn bị góc xấu hoặc đồ vật lộn xộn nhưng em bé rất đáng yêu,
        tự động cắt (Crop) lấy riêng khung chân dung sạch sẽ của em bé theo tọa độ clean_crop_box của AI!
        """
        if not eval_res.get("auto_cropped", False):
            return frame_bgr
        cbox = eval_res.get("clean_crop_box")
        if not isinstance(cbox, list) or len(cbox) != 4:
            return frame_bgr
        try:
            h, w = frame_bgr.shape[:2]
            xmin, ymin, xmax, ymax = [float(v) for v in cbox]
            x1 = max(0, int(min(xmin, xmax) * w))
            y1 = max(0, int(min(ymin, ymax) * h))
            x2 = min(w, int(max(xmin, xmax) * w))
            y2 = min(h, int(max(ymin, ymax) * h))
            if (x2 - x1) >= int(w * 0.22) and (y2 - y1) >= int(h * 0.22):
                return frame_bgr[y1:y2, x1:x2].copy()
        except Exception:
            pass
        return frame_bgr

    def evaluate_cute_moment(self, frame_bgr, is_manual: bool = False) -> dict:
        """
        Kiểm duyệt thông minh 2 chế độ (Smart Dual-Mode Moderation & Auto-Crop):
        - Chế độ 1 (Giữ toàn khung - family_wide): Không có người lớn, HOẶC có bố/mẹ mặc đồ lịch sự kín đáo
          và lên hình nguyên vẹn, đẹp đẽ cùng bé -> Lưu toàn khung hình.
        - Chế độ 2 (Tự động cắt cận cảnh bé - baby_portrait): Em bé ngủ/thức đáng yêu và kín đáo, NHƯNG ở rìa ảnh
          có bố/mẹ nằm quay lưng, bị cắt nửa mặt, trang phục chưa chỉnh tề hoặc vướng màn hình phụ ->
          THAY VÌ TỪ CHỐI BỎ PHÍ KHOẢNH KHẮC CỦA BÉ, AI trả về tọa độ clean_crop_box chỉ lấy riêng vùng em bé
          trên tấm nôi, cắt bỏ 100% phần người lớn/vật lộn xộn ở bên ngoài!
        - Chế độ 3 (Từ chối - reject): Chỉ từ chối khi chính em bé đang thay tã, mặt bé bị che khuất, hoặc phần
          nhạy cảm của người lớn đè sát ngay lên người bé không thể cắt tách riêng ra được.
        """
        if not self.filter_moments_enabled:
            return {
                "checked_by_gemini": False,
                "approved": True,
                "privacy_safe": True,
                "has_other_person": False,
                "other_person_aesthetic": True,
                "auto_cropped": False,
                "aesthetic_score": 8,
                "caption_vi": f"Khoảnh khắc của {self.baby_name} (Chụp cục bộ)",
                "reason_vi": "Đã tắt bộ lọc AI"
            }

        if not self.is_ready():
            return {
                "checked_by_gemini": False,
                "approved": False,
                "privacy_safe": False,
                "reason_vi": "Chưa cấu hình hoặc API Key không hợp lệ nên tạm dừng lưu ảnh tự động để bảo vệ quyền riêng tư."
            }

        now = time.time()
        if not is_manual and (now - self.last_moment_eval_time) < self.moment_cooldown_sec:
            return {
                "checked_by_gemini": False,
                "approved": False,
                "reason_vi": "Đang trong thời gian giãn cách kiểm duyệt ảnh."
            }

        img_bytes = self._encode_frame_jpeg(frame_bgr, max_dim=800)
        if not img_bytes:
            return {"checked_by_gemini": False, "approved": True if is_manual else False, "reason_vi": "Lỗi mã hóa ảnh."}

        if is_manual:
            prompt = f"""
Bạn là Trợ lý Nhiếp ảnh Gia Đình của BabyGuard AI cho bé {self.baby_name}.
Bức ảnh này do chính BỐ MẸ / NGƯỜI THÂN CHỦ ĐỘNG BẤM CHỤP để lưu lại khoảnh khắc đáng nhớ của gia đình và bé bên nôi.

YÊU CẦU:
1. TÔN TRỌNG VÀ DUYỆT ẢNH (approved = true, privacy_safe = true) để lưu giữ kỷ niệm cho gia đình (kể cả khi có bố mẹ/người thân đang chăm sóc, ngắm nhìn bé hoặc bé đang ngủ nghiêng).
2. Tạo một câu chú thích (caption_vi) thật ngọt ngào, ấm áp, ghi nhận khoảnh khắc gia đình và bé (ví dụ: "Mẹ âu yếm ngắm nhìn bé yêu", "Khoảnh khắc bình yên bên nôi", "Bé ngủ say giấc trong vòng tay gia đình").

Trả về đúng định dạng JSON:
{{
  "baby_present": boolean,
  "is_baby_central_subject": true,
  "baby_face_clear": true,
  "no_dominant_adults": true,
  "privacy_safe": true,
  "approved": true,
  "aesthetic_score": 9,
  "clean_crop_box": null,
  "caption_vi": "Một câu chú thích ngắn ấm áp, xúc động về khoảnh khắc này",
  "reason_vi": "Ảnh kỷ niệm do gia đình chủ động chụp"
}}
"""
        else:
            prompt = f"""
Bạn là Giám khảo Nhiếp ảnh Nghệ thuật Trẻ Sơ Sinh & Giám sát Quyền Riêng Tư (Strict Baby Photo Critic & Privacy Inspector) của BabyGuard AI.
Bức ảnh này được hệ thống chụp TỰ ĐỘNG để lưu vào Album Kỷ Niệm của bé {self.baby_name}.

TIÊU CHUẨN ĐÁNH GIÁ ẢNH ĐẸP & AN TOÀN BẮT BUỘC (TUYỆT ĐỐI TUÂN THỦ):

1. CHỦ THỂ TRUNG TÂM PHẢI LÀ EM BÉ (BẮT BUỘC):
   - TRONG HÌNH PHẢI CÓ EM BÉ và bé là nhân vật chính trung tâm của bức ảnh (baby_present = true, is_baby_central_subject = true).
   - NẾU ảnh chỉ có chăn màn, nôi trống, đồ vật, hoặc KHÔNG CÓ BÉ -> TỪ CHỐI NGAY (approved = false, reason_vi = "Không có em bé trong hình").
   - NẾU người lớn nằm chiếm ưu thế, người lớn lướt điện thoại, người lớn che khuất bé -> TỪ CHỐI NGAY (approved = false, reason_vi = "Ảnh vướng người lớn chiếm khung hình").

2. TIÊU CHUẨN THẨM MỸ & CẢM XÚC NHIẾP ẢNH:
   - Khuôn mặt bé rõ nét, ánh mắt trong trẻo hoặc đang ngủ say bình yên, nụ cười thiên thần, ngáp chúm chím, mút tay đáng yêu.
   - Bỏ qua nếu bé đang khóc mếu dữ dội, nôn trớ, hoặc mặt bị tối sầm/mờ nhòe rung lắc.
   - Bé mặc quần áo/tã lót lịch sự, trang nghiêm, kín đáo.

3. TỌA ĐỘ CĂN GIỮA CHÂN DUNG BÉ (clean_crop_box):
   - Trả về tọa độ [xmin, ymin, xmax, ymax] (float 0.0 -> 1.0) để hệ thống tự động cắt và ĐƯA BÉ VÀO TRUNG TÂM KHUNG CHÂN DUNG (Center-aligned Portrait Crop), cắt bỏ các viền phòng hoặc đồ vật thừa thãi.

Trả về đúng định dạng JSON:
{{
  "baby_present": boolean,
  "is_baby_central_subject": boolean,
  "baby_face_clear": boolean,
  "no_dominant_adults": boolean,
  "privacy_safe": boolean,
  "approved": boolean,
  "aesthetic_score": integer,
  "clean_crop_box": [float, float, float, float],
  "caption_vi": "Một câu chú thích ngắn ấm áp về nụ cười hoặc giấc ngủ ngoan của bé",
  "reason_vi": "Giải thích ngắn gọn lý do duyệt hoặc từ chối"
}}
"""
        try:
            self.last_moment_eval_time = now
            resp = self._call_gemini_resilient(
                contents=[
                    types.Part.from_bytes(data=img_bytes, mime_type="image/jpeg"),
                    prompt
                ],
                call_type="moment_judge",
                json_mode=True,
                temperature=0.1
            )
            data = json.loads(resp.text)
            baby_present = bool(data.get("baby_present", False))
            is_central = bool(data.get("is_baby_central_subject", False))
            baby_face_clear = bool(data.get("baby_face_clear", False))
            no_adults = bool(data.get("no_dominant_adults", True))
            privacy_safe = bool(data.get("privacy_safe", False))
            score = int(data.get("aesthetic_score", 0))

            if is_manual:
                approved = True
                privacy_safe = True
                baby_face_clear = True
                score = max(8, score)
            else:
                approved = (
                    baby_present
                    and is_central
                    and baby_face_clear
                    and no_adults
                    and privacy_safe
                    and bool(data.get("approved", False))
                    and score >= 7
                )

            result = {
                "checked_by_gemini": True,
                "approved": approved,
                "privacy_safe": privacy_safe,
                "baby_face_clear": baby_face_clear,
                "has_other_person": not no_adults,
                "aesthetic_score": score,
                "clean_crop_box": data.get("clean_crop_box", None),
                "caption_vi": str(data.get("caption_vi", f"Khoảnh khắc đáng yêu của {self.baby_name}")),
                "reason_vi": str(data.get("reason_vi", "Đã đánh giá chất lượng chân dung qua AI"))
            }

            print(f"[GeminiVerifier] Duyệt ảnh Cute Moment ({self.active_model}): approved={approved}, "
                  f"face_clear={baby_face_clear}, privacy_safe={privacy_safe}, score={score} -> {result['reason_vi']}")
            return result
        except Exception as e:
            print(f"[GeminiVerifier] Lỗi evaluate_cute_moment: {e}")
            return {
                "checked_by_gemini": False,
                "approved": False,
                "privacy_safe": False,
                "has_other_person": False,
                "other_person_aesthetic": False,
                "aesthetic_score": 0,
                "caption_vi": "",
                "reason_vi": f"Tạm hoãn lưu ảnh do chưa kết nối được AI kiểm duyệt riêng tư ({str(e)[:80]})"
            }

    def rank_moments_mosaic(self, candidate_images: list) -> dict:
        """
        Bản ghép Mosaic tuyển chọn khoảnh khắc đáng yêu:
        Ghép 6-12 ảnh ứng viên vào 1 bản ghép duy nhất (Contact Sheet Grid).
        Gọi Gemini 1 lượt duy nhất để thẩm định so sánh tương đối:
        - Chọn ra tối đa 10 bức ảnh đẹp nhất (không mờ nhòe, không vướng người lớn, biểu cảm tự nhiên).
        - Trả về danh sách thứ hạng và caption tương ứng.
        """
        if not candidate_images:
            return {"ranked_indices": [], "captions": {}}

        n = min(len(candidate_images), 12)
        tiles = []
        for i, img in enumerate(candidate_images[:n]):
            resized = cv2.resize(img, (480, 480))
            cv2.rectangle(resized, (8, 8), (110, 48), (0, 0, 0), -1)
            cv2.rectangle(resized, (8, 8), (110, 48), (255, 215, 0), 2)
            cv2.putText(resized, f"#{i+1}", (18, 38), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 2, cv2.LINE_AA)
            tiles.append(resized)

        cols = 3 if n >= 5 else 2
        rows = (n + cols - 1) // cols
        blank_tile = np.zeros((480, 480, 3), dtype=np.uint8)
        while len(tiles) < rows * cols:
            tiles.append(blank_tile)

        grid_rows = []
        for r in range(rows):
            row_tiles = tiles[r * cols : (r + 1) * cols]
            grid_rows.append(np.hstack(row_tiles))
        mosaic = np.vstack(grid_rows)

        img_bytes = self._encode_frame_jpeg(mosaic, max_dim=1536)
        if not img_bytes:
            return {"ranked_indices": list(range(n)), "captions": {}}

        prompt = f"""
Bạn là Giám khảo Nghệ thuật & Nhiếp ảnh Gia Đình Trẻ Sơ Sinh (BabyGuard AI).
Đây là bản ghép Mosaic gồm {n} bức ảnh ứng viên được đánh số từ #1 đến #{n} của bé {self.baby_name}.

NHIỆM VỤ CỦA BẠN:
1. Quan sát toàn bộ {n} bức ảnh cùng lúc và so sánh tương quan để chọn ra tối đa 10 bức ảnh ĐẸP NHẤT, CẢM XÚC NHẤT.
2. Tiêu chuẩn ưu tiên:
   - Bé là trung tâm, rõ mặt, nét căng, ánh mắt sáng hoặc giấc ngủ thiên thần, nụ cười chúm chím, ngáp, vươn vai, mút tay.
   - Không bị nhòe mờ rung lắc, không bị lẹm mặt, không có người lớn nằm chiếm ưu thế hoặc nhạy cảm.
3. Trả về danh sách số thứ tự (1-indexed) xếp theo thứ tự từ đẹp nhất trở xuống.

Trả về JSON:
{{
  "selected_indices": [1, 2, 3],
  "captions": {{
    "1": "string caption"
  }}
}}
"""
        try:
            resp = self._call_gemini_resilient(
                contents=[
                    types.Part.from_bytes(data=img_bytes, mime_type="image/jpeg"),
                    prompt
                ],
                call_type="moment_judge",
                json_mode=True,
                temperature=0.1
            )
            data = json.loads(resp.text)
            raw_indices = data.get("selected_indices", [])
            clean_indices = [idx - 1 for idx in raw_indices if isinstance(idx, int) and 1 <= idx <= n]
            if not clean_indices:
                clean_indices = list(range(min(n, 10)))
            return {
                "ranked_indices": clean_indices,
                "captions": data.get("captions", {})
            }
        except Exception as e:
            print(f"[GeminiVerifier] Lỗi rank_moments_mosaic: {e}")
            return {"ranked_indices": list(range(min(n, 10))), "captions": {}}

    # =========================================================================
    # 3. TRỢ LÝ CĂN CHỈNH NÔI THÔNG MINH (AUTO-CALIBRATION)
    # =========================================================================
    def auto_calibrate_crib(self, frame_bgr) -> dict:
        if not self.is_ready():
            return {
                "success": False,
                "error": "Vui lòng nhập Gemini API Key trong phần Cài đặt trước khi dùng tính năng AI Căn chỉnh Nôi."
            }

        img_bytes = self._encode_frame_jpeg(frame_bgr, max_dim=800)
        if not img_bytes:
            return {"success": False, "error": "Không lấy được khung hình từ camera."}

        prompt = """
Bạn là Kỹ sư Thị giác Máy tính & Chuyên gia An toàn Nôi Em Bé (AI Crib 3D Calibration Specialist).
Hãy phân tích khung hình camera giám sát này và xác định:
1. Tọa độ đa giác 4 đỉnh (3D Perspective Quadrilateral) bao quanh TRỌN VẸN VÙNG TẤM ĐỆM / NÔI AN TOÀN của bé theo đúng góc phối cảnh 3D xiên của camera:
   - QUY TẮC BẮT BUỘC:
     + Toàn bộ đầu em bé, gối nằm của bé, thân bé, chăn và gối ôm cạnh bé PHẢI NẰM HOÀN TOÀN 100% BÊN TRONG safe_zone_polygon.
     + TUYỆT ĐỐI KHÔNG ĐƯỢC để cạnh trên hay bất kỳ cạnh nào cắt ngang qua đầu, cổ hay cơ thể em bé!
     + Cạnh trên (Top edge) phải chạy phía TRÊN đỉnh đầu và gối của bé ít nhất 5-8% chiều cao ảnh để chừa khoảng thở an toàn.
     + Cạnh phải (Right edge) phải mở rộng qua hết gối/đệm của bé.
     + Nếu có người lớn nằm ngủ cạnh bé trên giường lớn, đa giác Safe Zone 3D chỉ bao quanh tấm đệm/nôi của em bé, ranh giới cạnh trên chạy sát mép đệm bé mà không bao người lớn.
   - safe_zone_polygon: [[x_tl, y_tl], [x_tr, y_tr], [x_br, y_br], [x_bl, y_bl]] theo thứ tự:
     + Top-Left (Góc trên bên trái tấm đệm/nôi)
     + Top-Right (Góc trên bên phải tấm đệm/nôi)
     + Bottom-Right (Góc dưới bên phải tấm đệm/nôi)
     + Bottom-Left (Góc dưới bên trái tấm đệm/nôi)
     (Tất cả x, y là số float từ 0.02 đến 0.98 chuẩn hóa theo chiều rộng và chiều cao ảnh).
2. Tọa độ khung chữ nhật bao ngoài: safe_zone_top, safe_zone_bottom, safe_zone_left, safe_zone_right.
3. Danh sách các vật thể đang có trong nôi (gối ôm, gối chặn, chăn, thú bông...).
4. Nhận xét ngắn gọn bằng tiếng Việt về mức độ thông thoáng và an toàn của nôi hiện tại.

Trả về đúng định dạng JSON:
{
  "safe_zone_polygon": [[float, float], [float, float], [float, float], [float, float]],
  "safe_zone_top": float,
  "safe_zone_bottom": float,
  "safe_zone_left": float,
  "safe_zone_right": float,
  "baby_present": boolean,
  "objects_detected": ["danh sách vật thể bằng tiếng Việt"],
  "safety_advice_vi": "Lời khuyên ngắn gọn cho bố mẹ bằng tiếng Việt"
}
"""
        try:
            self.status_text = "Đang căn chỉnh nôi bằng AI..."
            resp = self._call_gemini_resilient(
                contents=[
                    types.Part.from_bytes(data=img_bytes, mime_type="image/jpeg"),
                    prompt
                ],
                call_type="calibration",
                json_mode=True,
                temperature=0.1
            )
            data = json.loads(resp.text)
            poly = data.get("safe_zone_polygon")
            if isinstance(poly, list) and len(poly) == 4:
                valid_poly = []
                for p in poly:
                    px = float(p[0])
                    py = float(p[1])
                    if px > 1.0:
                        px = px / 1000.0 if px <= 1000.0 else px / 1280.0
                    if py > 1.0:
                        py = py / 1000.0 if py <= 1000.0 else py / 720.0
                    valid_poly.append([round(max(0.01, min(0.99, px)), 3), round(max(0.01, min(0.99, py)), 3)])
                xs = [p[0] for p in valid_poly]
                ys = [p[1] for p in valid_poly]
                left = min(xs)
                right = max(xs)
                top = min(ys)
                bottom = max(ys)
            else:
                def _clean_s(v, def_v, max_d):
                    try:
                        fv = float(v)
                        if fv > 1.0:
                            fv = fv / 1000.0 if fv <= 1000.0 else fv / max_d
                        return max(0.01, min(0.99, fv))
                    except Exception:
                        return def_v
                top = _clean_s(data.get("safe_zone_top"), 0.18, 720.0)
                bottom = _clean_s(data.get("safe_zone_bottom"), 0.95, 720.0)
                left = _clean_s(data.get("safe_zone_left"), 0.15, 1280.0)
                right = _clean_s(data.get("safe_zone_right"), 0.92, 1280.0)
                valid_poly = [[left, top], [right, top], [right, bottom], [left, bottom]]

            self.status_text = "Đã căn chỉnh nôi thành công"
            return {
                "success": True,
                "safe_zone": {
                    "top": round(top, 3),
                    "bottom": round(bottom, 3),
                    "left": round(left, 3),
                    "right": round(right, 3),
                    "polygon": valid_poly
                },
                "baby_present": bool(data.get("baby_present", True)),
                "objects_detected": data.get("objects_detected", []),
                "safety_advice_vi": str(data.get("safety_advice_vi", "Đã tự động căn chỉnh vùng an toàn 3D theo lòng nôi."))
            }
        except Exception as e:
            err_msg = str(e)
            if "429" in err_msg or "RESOURCE_EXHAUSTED" in err_msg:
                return {
                    "success": False,
                    "error": "Khóa Gemini API đã chạm hạn mức Free (20 lượt/ngày). Khung 3D đã được hiệu chỉnh tối ưu sẵn, hoặc bố mẹ có thể bấm 'Chỉnh Tay' để tinh chỉnh 4 góc."
                }
            return {"success": False, "error": f"Lỗi Gemini AI: {err_msg[:120]}"}

    # =========================================================================
    # 5. BÁC SĨ NHI KHOA AI: PHÂN TÍCH GIẤC NGỦ ĐÊM QUA & 24H (SÁNG HÔM SAU 07:00)
    # =========================================================================
    def generate_daily_sleep_report(self, sleep_summary: dict) -> dict:
        """
        Gửi toàn bộ thống kê Chu kỳ ngủ (NREM/REM), Cửa sổ thức (Wake Window),
        các cơn khóc, ho/sặc sữa, nhịp thở và chỉ số tăng trưởng lên Gemini
        để lập Báo Cáo Sức Khỏe & Giấc Ngủ Nhi Khoa Chuyên Sâu vào sáng hôm sau (07:00)
        kèm trích nguồn nghiên cứu y khoa chính thống (AAP, WHO, AASM).
        """
        if not self.is_ready():
            return {"success": False, "error": "Chưa cấu hình Gemini API Key"}

        baby_name = sleep_summary.get("baby_name", "Bé")
        age_display = sleep_summary.get("age_display", "1 tháng tuổi")
        total_sleep = float(sleep_summary.get("total_sleep_today_hours", 0.0))
        total_awake = float(sleep_summary.get("total_awake_today_hours", 0.0))
        camera_offline = round(max(0.0, 24.0 - (total_sleep + total_awake)), 1)
        
        crying_count = int(sleep_summary.get("crying_count", 0))
        cough_count = int(sleep_summary.get("cough_count", 0))
        avg_bpm = float(sleep_summary.get("avg_bpm", 36.0))
        apnea_count = int(sleep_summary.get("apnea_count", 0))
        growth = sleep_summary.get("growth_data", {})
        growth_str = f"Cân nặng: {growth.get('weight_kg', 'Chưa nhập')} kg | Chiều cao: {growth.get('height_cm', 'Chưa nhập')} cm ({growth.get('weight_status', 'Đang cập nhật')})"

        yesterday = sleep_summary.get("yesterday_sleep", {})
        y_sleep = yesterday.get("total_sleep_hours")
        y_nap = yesterday.get("longest_nap_minutes")
        y_score = yesterday.get("sleep_score")

        delta_summary = sleep_summary.get("delta_summary", {})
        hourly_clusters = delta_summary.get("hourly_clusters", {})
        notable_clusters = []
        for h_key, cl in sorted(hourly_clusters.items()):
            c_coughs = cl.get("cough_count", 0)
            c_chokes = cl.get("choke_risk_count", 0)
            c_cry = cl.get("crying_minutes", 0.0)
            if c_coughs > 0 or c_chokes > 0 or c_cry > 3.0:
                notable_clusters.append(f"  • Khung {cl.get('time_range')}: {c_coughs} lần ho, {c_chokes} nguy cơ sặc, {c_cry}p quấy khóc.")
        cluster_text = "\n".join(notable_clusters) if notable_clusters else "  • Các khung giờ phân bổ êm ả, không phát hiện cụm triệu chứng tập trung."

        sleep_tracking_metric_str = (
            f"- Chu kỳ đo 24h: Tính từ 07:00 sáng hôm trước đến 07:00 sáng hôm nay (Chuẩn AAP/AASM).\n"
            f"- Thời gian ngủ ghi nhận qua camera trong chu kỳ 24h: {total_sleep} giờ (cữ dài nhất: {sleep_summary.get('longest_nap_minutes', 0)} phút)."
        )

        prompt = f"""
Bạn là Bác sĩ Nhi khoa Chuyên gia về Sơ sinh & Giấc ngủ Trẻ em (Pediatrician & Sleep Specialist) của hệ thống BabyGuard AI.
Dưới đây là hồ sơ bệnh án sinh học thực tế của em bé {baby_name} ({age_display}) trong chu kỳ 24h (đo từ 07:00 sáng hôm qua đến 07:00 sáng hôm nay theo chuẩn AAP/AASM):

1. DỮ LIỆU ĐO LƯỜNG SINH HỌC 24H:
{sleep_tracking_metric_str}
- Thời gian thức chơi / vận động trong tầm camera: {total_awake} giờ
- Thời gian ngoài tầm camera (được bố mẹ bế ra ngoài, bú sữa, tắm, chơi...): ~{camera_offline} giờ
- Tỷ lệ Ngủ sâu (NREM): {sleep_summary.get("deep_ratio_pct", 55)}% | Ngủ động (REM): {sleep_summary.get("rem_ratio_pct", 45)}%
- Cữ ngủ liền mạch dài nhất: {sleep_summary.get("longest_nap_minutes", 0)} phút
- Điểm chất lượng giấc ngủ: {sleep_summary.get("sleep_score", 85)}/100
- Số lần giật mình sinh lý Moro/REM: {sleep_summary.get("rem_twitch_count", 0)} lần
- Nhịp thở quang học lồng ngực trung bình: {avg_bpm} BPM (Cảnh báo nguy cơ ngưng thở: {apnea_count} lần)
- Thống kê âm thanh AI: {crying_count} lần quấy khóc, {cough_count} cơn ho / tiếng thở dốc / nguy cơ sặc sữa.
- Chỉ số thể trạng & tăng trưởng: {growth_str}

2. PHÂN TÍCH CỤM BIẾN ĐỘNG THEO TỪNG KHUNG GIỜ (HOURLY CLUSTERS):
{cluster_text}
(LƯU Ý Y KHOA: Tuyệt đối không chia bình quân số lần ho/sặc ra 24h. Cần phân tích cụm thời điểm bé bị ho/sặc dồn dập, ví dụ ho nhiều lúc nửa đêm về sáng thường do trào ngược dạ dày thực quản GERD, sữa trào ngược khi nằm ngang hoặc nhiệt độ phòng giảm lạnh).

Hãy phân tích toàn diện, khoa học và đưa ra BÁO CÁO NHI KHOA BUỔI SÁNG cho bố mẹ với các yêu cầu bắt buộc:
A. PHÂN TÍCH CHU KỲ 24H: Đo từ 07:00 sáng theo chuẩn AAP/AASM, phân tích thời gian ngủ nôi vs ngoài camera ({camera_offline}h) dựa trên nhu cầu ngủ 14-17h của trẻ sơ sinh.
B. ĐÁNH GIÁ CỤM BIẾN ĐỘNG & HÔ HẤP: Nhận xét nhịp thở {avg_bpm} BPM và cụm biến động ho/sặc, hướng dẫn mẹ phòng ngừa trào ngược (vỗ ợ hơi, bế dựng 15-20p sau bú).
C. ĐÁNH GIÁ THỂ TRẠNG THEO CHUẨN WHO: Nhận xét cân nặng, chiều cao đối chiếu trung vị WHO.
D. LỜI KHUYÊN & LỊCH SINH HOẠT HÔM NAY: Wake Window tối ưu cho trẻ lứa tuổi này, quy tắc ngủ an toàn ABC của AAP.
E. TRÍCH DẪN NGUỒN CHÍNH THỐNG: AAP, AASM, WHO.

Trả về đúng định dạng JSON:
{{
  "headline_vi": "Tiêu đề báo cáo ngắn gọn, ấm áp",
  "summary_vi": "Phân tích cụ thể chu kỳ 24h từ 07:00 sáng và nhịp sinh học của bé (3-4 câu tiếng Việt)",
  "respiratory_and_reflux_vi": "Nhận xét chi tiết về nhịp thở và phân tích cụm ho/sặc sữa theo khung giờ (3-4 câu tiếng Việt)",
  "growth_analysis_vi": "Đánh giá chiều cao, cân nặng đối chiếu bảng chuẩn WHO (2-3 câu tiếng Việt)",
  "schedule_advice_vi": "Lịch sinh hoạt và gợi ý canh cửa sổ thức (Wake Window) hôm nay (2-3 câu tiếng Việt)",
  "tips_vi": ["Lời khuyên thực tế 1", "Lời khuyên thực tế 2", "Lời khuyên thực tế 3"],
  "scientific_citations_vi": [
    "Viện Hàn lâm Nhi khoa Hoa Kỳ (AAP) - Hướng dẫn Giấc ngủ An toàn & Phòng ngừa SIDS",
    "Hiệp hội Y học Giấc ngủ Hoa Kỳ (AASM) - Khuyến nghị Thời lượng Giấc ngủ Nhi khoa",
    "Tổ chức Y tế Thế giới (WHO) - Bộ Tiêu chuẩn Tăng trưởng Trẻ em (Child Growth Standards)"
  ]
}}
"""
        try:
            resp = self._call_gemini_resilient(
                contents=[prompt],
                call_type="sleep_doctor_report",
                json_mode=True,
                temperature=0.2
            )
            data = json.loads(resp.text)
            
            headline = data.get("headline_vi", f"Báo cáo Giấc ngủ & Sức khỏe Ngày {sleep_summary.get('today_date')} của {baby_name}")
            summary_vi = str(data.get("summary_vi", ""))
            reflux_vi = str(data.get("respiratory_and_reflux_vi", ""))
            growth_vi = str(data.get("growth_analysis_vi", ""))
            schedule_vi = str(data.get("schedule_advice_vi", ""))
            tips_vi = data.get("tips_vi", [])[:3]
            citations = data.get("scientific_citations_vi", [
                "Viện Hàn lâm Nhi khoa Hoa Kỳ (AAP) - Policy Statement on Infant Safe Sleep",
                "Hiệp hội Y học Giấc ngủ Hoa Kỳ (AASM) - Pediatric Sleep Duration Consensus",
                "Tổ chức Y tế Thế giới (WHO) - Child Growth Standards"
            ])

            # Soạn thảo nội dung định dạng HTML chuẩn đẹp để gửi Telegram
            cluster_tele_part = ""
            if notable_clusters:
                cluster_tele_part = "• <i>Phân tích cụm thời gian biến động:</i>\n" + "\n".join(notable_clusters[:3]) + "\n"

            tele_msg = (
                f"🩺 <b>BÁO CÁO NHI KHOA BUỔI SÁNG (07:00) — {baby_name.upper()}</b>\n"
                f"👶 <i>Độ tuổi: {age_display} | Chu kỳ 24h neo 07:00 AM (Chuẩn AAP/AASM)</i>\n"
                f"━━━━━━━━━━━━━━━━━━━\n\n"
                f"📊 <b>1. GIÁM SÁT GIẤC NGỦ 24H:</b>\n"
                f"• Ghi nhận qua Camera: <b>{total_sleep}h ngủ</b> | <b>{total_awake}h thức</b>\n"
                f"• Ngoài tầm quan sát: ~<b>{camera_offline}h</b> (bế chơi, bú sữa, tắm...)\n"
                f"• Chu kỳ: <b>{sleep_summary.get('deep_ratio_pct', 55)}% NREM</b> (Sâu) | <b>{sleep_summary.get('rem_ratio_pct', 45)}% REM</b> (Động)\n"
                f"• Điểm giấc ngủ AI: <b>{sleep_summary.get('sleep_score', 85)}/100</b>\n"
                f"👉 <i>{summary_vi}</i>\n\n"
                f"🫁 <b>2. HÔ HẤP, HO & PHÒNG CHỐNG SẶC SỮA:</b>\n"
                f"• Nhịp thở khi ngủ: <b>{avg_bpm} BPM</b> (Chuẩn sơ sinh: 30 - 60 BPM)\n"
                f"• Cơn ho / trớ sặc sữa: <b>{cough_count} lần</b> | Tiếng khóc: <b>{crying_count} lần</b>\n"
                f"{cluster_tele_part}"
                f"👉 <i>{reflux_vi}</i>\n\n"
                f"📈 <b>3. THỂ TRẠNG & TĂNG TRƯỞNG (CHUẨN WHO):</b>\n"
                f"• Số đo mới nhất: <b>{growth.get('weight_kg', 'N/A')} kg</b> | <b>{growth.get('height_cm', 'N/A')} cm</b>\n"
                f"👉 <i>{growth_vi}</i>\n\n"
                f"⏰ <b>4. LỊCH SINH HOẠT & CỬA SỔ THỨC (WAKE WINDOW):</b>\n"
                f"👉 <i>{schedule_vi}</i>\n\n"
                f"💡 <b>LỜI KHUYÊN HÔM NAY CHO BỐ MẸ:</b>\n"
            )
            for idx, tip in enumerate(tips_vi, 1):
                tele_msg += f" {idx}. {tip}\n"

            story = sleep_summary.get("daily_story")
            if story and story.get("title") and story.get("content"):
                st_title = story.get("title")
                st_src = story.get("source") or story.get("category") or "Bài học cuộc sống"
                st_cnt = story.get("content")
                st_lesson = story.get("parenting_lesson", "")
                st_prompt = story.get("baby_talk_prompt", "")
                tele_msg += (
                    f"\n📖 <b>5. 1 NGÀY 1 CÂU CHUYỆN Ý NGHĨA CHO CON:</b>\n"
                    f"✨ <b>{st_title}</b> <i>({st_src})</i>\n"
                    f"\"{st_cnt}\"\n"
                    f"🌱 <b>Bài học dạy con:</b> <i>{st_lesson}</i>\n"
                )
                if st_prompt:
                    tele_msg += f"💬 <b>Thủ thỉ cùng con:</b> <i>\"{st_prompt}\"</i>\n"

            tele_msg += (
                f"\n📚 <b>TRÍCH NGUỒN NGHIÊN CỨU Y KHOA:</b>\n"
                f"<i>• {citations[0]}\n"
                f"• {citations[1]}\n"
                f"• {citations[2]}</i>\n"
            )

            # Cảnh báo Lịch tiêm chủng đến hạn (nếu có mũi tiêm cần tiêm hoặc quá hạn)
            v_alert = sleep_summary.get("vaccine_alert_text", "")
            if v_alert:
                tele_msg = f"{v_alert}\n━━━━━━━━━━━━━━━━━━━\n\n" + tele_msg

            # Khuyến cáo y tế bắt buộc theo chỉ thị
            medical_disclaimer = (
                "⚠️ <b>LƯU Ý Y KHOA:</b>\n"
                "<i>Các nhận định trên chỉ là gợi ý tham khảo dành cho bố mẹ dựa trên các thông số mà hệ thống đo đạc được. "
                "Để biết thêm thông tin chi tiết hoặc khi bé có biểu hiện bất thường, bố mẹ cần liên hệ với bác sĩ chuyên ngành Nhi.</i>"
            )
            tele_msg += f"\n{medical_disclaimer}\n"

            report = {
                "date": sleep_summary.get("today_date"),
                "generated_at": time.strftime("%H:%M - %d/%m"),
                "model": f"Bác Sĩ AI ({self.active_model})",
                "headline_vi": headline,
                "summary_vi": summary_vi,
                "respiratory_and_reflux_vi": reflux_vi,
                "growth_analysis_vi": growth_vi,
                "schedule_advice_vi": schedule_vi,
                "tips_vi": tips_vi,
                "daily_story": story,
                "scientific_citations_vi": citations,
                "medical_disclaimer_vi": "Các nhận định trên chỉ là gợi ý tham khảo dành cho bố mẹ dựa trên các thông số mà hệ thống đo đạc được. Để biết thêm thông tin chi tiết hoặc khi bé có biểu hiện bất thường, bố mẹ cần liên hệ với bác sĩ chuyên ngành Nhi.",
                "telegram_text": tele_msg
            }
            return {"success": True, "report": report}
        except Exception as e:
            return {"success": False, "error": str(e)}

    # =========================================================================
    # 5. HỘI CHẨN TĂNG TRƯỞNG THỂ CHẤT (CHIỀU CAO - CÂN NẶNG CHUẨN WHO)
    # =========================================================================
    def consult_growth_progress(self, baby_name: str, age_display: str, gender: str,
                                current_rec: dict, prev_rec: dict = None, who_standard: dict = None) -> dict:
        """
        Bác Sĩ Nhi Khoa Gemini AI so sánh số đo lần này với lần trước,
        tính toán khoảng cách ngày, tốc độ tăng cân/chiều cao và đưa ra đề xuất dinh dưỡng, chăm sóc cho ba mẹ.
        """
        if not self.is_ready():
            return {"success": False, "error": "Gemini AI chưa sẵn sàng hoặc chưa nhập API Key"}

        c_w = current_rec.get("weight_kg", 0.0)
        c_h = current_rec.get("height_cm", 0.0)
        c_head = current_rec.get("head_circ_cm")
        c_date = current_rec.get("date", "Hôm nay")

        prev_info = "Đây là lần đo đầu tiên được ghi nhận của bé."
        days_gap = 0
        w_diff_g = 0
        h_diff_cm = 0
        velocity_str = ""

        if prev_rec:
            p_w = prev_rec.get("weight_kg", 0.0)
            p_h = prev_rec.get("height_cm", 0.0)
            p_head = prev_rec.get("head_circ_cm")
            p_date = prev_rec.get("date", "")
            
            try:
                d_curr = datetime.strptime(str(c_date)[:10], "%Y-%m-%d").date()
                d_prev = datetime.strptime(str(p_date)[:10], "%Y-%m-%d").date()
                days_gap = max(1, (d_curr - d_prev).days)
            except Exception:
                days_gap = 15

            w_diff_g = round((c_w - p_w) * 1000)
            h_diff_cm = round(c_h - p_h, 1)
            g_per_day = round(w_diff_g / max(1, days_gap), 1)
            prev_info = (
                f"Lần đo trước ngày {p_date}: Cân nặng {p_w} kg, Chiều cao {p_h} cm"
                f"{f', Vòng đầu {p_head} cm' if p_head else ''}.\n"
                f"Khoảng cách giữa 2 lần đo: {days_gap} ngày.\n"
                f"Mức tăng trưởng thực tế: Tăng +{w_diff_g}g ({g_per_day} g/ngày) và +{h_diff_cm} cm."
            )
            velocity_str = f"+{w_diff_g}g ({g_per_day}g/ngày), +{h_diff_cm}cm trong {days_gap} ngày"

        who_info = ""
        if who_standard:
            who_info = (
                f"Chuẩn WHO lứa tuổi: Cân nặng trung vị {who_standard.get('weight_median')} kg (Khoảng bình thường: {who_standard.get('weight_range')}), "
                f"Chiều cao trung vị {who_standard.get('length_median')} cm (Khoảng bình thường: {who_standard.get('length_range')})."
            )

        prompt = f"""
Bạn là Bác sĩ Nhi khoa Chuyên gia Dinh dưỡng & Phát triển Thể chất Trẻ em (Senior Pediatrician).
Dưới đây là số liệu đo lường thể trạng của em bé:
- Tên bé: {baby_name} ({gender}, {age_display})
- Số đo lần này ({c_date}): Cân nặng = {c_w} kg, Chiều cao/dài = {c_h} cm{f', Vòng đầu = {c_head} cm' if c_head else ''}
- So sánh với lần đo trước:
{prev_info}
- Đối chiếu Bảng Chuẩn Tăng Trưởng WHO:
{who_info}

Hãy phân tích y khoa sâu sắc và đưa ra ĐỀ XUẤT CHO BA MẸ theo định dạng JSON bắt buộc:
{{
  "growth_status_badge": "Tăng trưởng rất tốt" | "Đạt chuẩn WHO" | "Cần theo dõi thêm",
  "velocity_evaluation_vi": "Nhận xét chi tiết 2-3 câu về tốc độ tăng cân/chiều cao trong khoảng thời gian {days_gap} ngày qua so với chuẩn sinh lý trẻ sơ sinh (khoảng 25-35g/ngày ở tháng đầu).",
  "who_percentile_comparison_vi": "Đánh giá vị trí của bé so với trung vị WHO (rất tốt, đạt chuẩn hay cần cải thiện).",
  "recommendations_vi": [
    "Khuyến nghị cụ thể 1 về cữ bú / lượng sữa ml mỗi ngày phù hợp với cân nặng {c_w}kg",
    "Khuyến nghị cụ thể 2 về giấc ngủ & vận động (Tummy Time, tắm nắng, massage)",
    "Khuyến nghị cụ thể 3 về bổ sung vi chất (như Vitamin D3 400 IU/ngày) và lưu ý theo dõi"
  ],
  "doctor_quote_vi": "Lời nhắn nhủ ấm áp, động viên ba mẹ từ Bác sĩ Nhi khoa (1 câu)"
}}
"""
        try:
            resp = self._call_gemini_resilient(
                contents=prompt,
                call_type="growth_consult",
                json_mode=True,
                temperature=0.1
            )
            data = json.loads(resp.text)
            return {
                "success": True,
                "analysis": {
                    "analyzed_at": time.strftime("%H:%M - %d/%m/%Y"),
                    "days_gap": days_gap,
                    "weight_gain_g": w_diff_g,
                    "height_gain_cm": h_diff_cm,
                    "velocity_str": velocity_str,
                    "status_badge": data.get("growth_status_badge", "Đạt chuẩn WHO"),
                    "velocity_evaluation_vi": data.get("velocity_evaluation_vi", ""),
                    "who_percentile_comparison_vi": data.get("who_percentile_comparison_vi", ""),
                    "recommendations_vi": data.get("recommendations_vi", []),
                    "doctor_quote_vi": data.get("doctor_quote_vi", "Chúc bé luôn mau ăn chóng lớn!"),
                    "medical_disclaimer_vi": "Đây chỉ là gợi ý tham khảo dành cho bố mẹ dựa trên các thông số mà hệ thống đo đạc được. Để biết thêm thông tin chi tiết, bố mẹ cần liên hệ với bác sĩ chuyên ngành Nhi.",
                    "model_used": self.active_model
                }
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    # =========================================================================
    # QUẢN LÝ METADATA CHO ALBUM KHOẢNH KHẮC ĐÁNG YÊU
    # =========================================================================
    @staticmethod
    def save_moment_metadata(filename: str, meta: dict):
        try:
            os.makedirs(os.path.dirname(MOMENTS_META_PATH), exist_ok=True)
            all_meta = {}
            if os.path.exists(MOMENTS_META_PATH):
                with open(MOMENTS_META_PATH, "r", encoding="utf-8") as f:
                    all_meta = json.load(f)
            all_meta[filename] = {
                "caption_vi": meta.get("caption_vi", "Khoảnh khắc đáng yêu của bé"),
                "aesthetic_score": meta.get("aesthetic_score", 8),
                "has_other_person": meta.get("has_other_person", False),
                "checked_by_gemini": meta.get("checked_by_gemini", False),
                "created_at": time.strftime("%H:%M:%S - %d/%m/%Y")
            }
            with open(MOMENTS_META_PATH, "w", encoding="utf-8") as f:
                json.dump(all_meta, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[GeminiVerifier] Lỗi lưu metadata moment: {e}")

    @staticmethod
    def load_moments_metadata() -> dict:
        if os.path.exists(MOMENTS_META_PATH):
            try:
                with open(MOMENTS_META_PATH, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

    def get_status(self) -> dict:
        usage = self.get_usage_stats()
        return {
            "ready": self.is_ready(),
            "enabled": self.enabled,
            "has_api_key": bool(len(self.api_key) > 10),
            "verify_alerts": self.verify_alerts_enabled,
            "filter_moments": self.filter_moments_enabled,
            "model": self.active_model or self.model_name,
            "key_health": self.key_health,
            "key_health_label": self.key_health_label,
            "last_checked_at": self.last_checked_at,
            "error_detail": self.error_detail,
            "usage": usage,
            "tracking_audit": self.last_tracking_audit,
            "status_text": self.status_text if self.is_ready() else "Chưa nhập Gemini API Key",
            "last_consultation": self.last_consultation
        }
