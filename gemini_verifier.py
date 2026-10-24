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
        self.tracking_audit_interval_sec = 50.0  # Khi rảnh không gọi API trong 50s -> Gửi hình kiểm tra Tracking Local
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
    def _encode_frame_jpeg(frame_bgr, max_dim: int = 768) -> bytes:
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
            min_interval = 6.0
        elif pose_changed:
            min_interval = 10.0  # Sau khi tư thế mới giữ ổn định 10s, kích hoạt audit
        elif local_uncertain:
            min_interval = 20.0
        else:
            min_interval = self.tracking_audit_interval_sec

        if elapsed < min_interval:
            return False

        stats = self.get_usage_stats()
        if stats["calls_last_1m"] >= 4 or stats["healthy_models_count"] == 0:
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
        local_sz = local_info.get("safe_zone", [0.05, 0.08, 0.95, 0.95])
        local_detected = local_info.get("baby_detected", False)
        local_pose = local_info.get("sleep_pose", "Chưa rõ")

        prompt = f"""
Bạn là Giám sát viên Thị giác Máy tính (AI Tracking & Crib Auto-Calibration Supervisor) của hệ thống BabyGuard AI.
Trên bức ảnh đính kèm, hệ thống AI Local đang vẽ:
1. Khung viền lớn màu xanh lá cây (Vùng An Toàn Nôi / Tấm Đệm của bé): tọa độ hiện tại [left, top, right, bottom] = {local_sz}.
2. Khung chữ nhật màu xanh dương (nhãn "EM BE"): tọa độ hiện tại = {local_box} (phát hiện = {local_detected}, tư thế = "{local_pose}").
3. Vùng đa giác màu xanh lơ: vùng đo nhịp thở lồng ngực.

Hãy quan sát bức ảnh và tự động kiểm tra + căn chỉnh cả 2 khung này, đồng thời phân biệt bé đang NGỦ hay đang THỨC:
A. KIỂM TRA TRACKING CƠ THỂ & TRẠNG THÁI THỨC/NGỦ CỦA EM BÉ:
- baby_present (boolean): Thực tế có em bé đang nằm trong ảnh không?
- is_baby_awake (boolean): Em bé đang THỨC (mở mắt nhìn, mút tay, đạp chân tay, ngóc đầu, chơi đùa -> true) hay đang NGỦ (nhắm mắt nằm yên -> false)?
- tracking_accurate (boolean): Khung xanh dương "EM BE" đã bao quanh ĐÚNG cơ thể thực tế của em bé VÀ vùng đo nhịp thở nằm đúng trên thân/ngực bé chưa?
- accuracy_score (integer 0-100): Điểm chính xác của khung Tracking em bé.
- true_baby_box ([xmin, ymin, xmax, ymax] từ 0.0 đến 1.0): Tọa độ khung chữ nhật bao quanh TOÀN BỘ CƠ THỂ thực tế của em bé.
- true_head_box ([xmin, ymin, xmax, ymax] từ 0.0 đến 1.0): Tọa độ phần đầu thực tế của em bé.
- head_direction ("right" | "left" | "up" | "down"): Đỉnh đầu của em bé đang hướng về phía nào?

B. KIỂM TRA & TỰ ĐỘNG CĂN CHỈNH KHUNG NÔI / TẤM ĐỆM EM BÉ (SAFE ZONE 3D):
- crib_zone_accurate (boolean): Khung viền xanh lá cây hiện tại đã bao quanh hợp lý vùng tấm đệm/nôi nơi em bé nằm chưa? (Nếu khung xanh lá đang cắt ngang qua đầu/cổ bé, quá hẹp hoặc bị lệch khỏi tấm đệm trắng của bé -> false).
- true_safe_zone_polygon ([[x, y], [x, y], [x, y], [x, y]] từ 0.03 đến 0.97): Tọa độ 4 đỉnh đa giác tứ giác theo thứ tự [Top-Left, Top-Right, Bottom-Right, Bottom-Left] bao quanh TRỌN VẸN tấm đệm nơi em bé nằm theo đúng góc phối cảnh 3D xiên. TUYỆT ĐỐI KHÔNG ĐƯỢC để cạnh cắt ngang đầu/thân bé; cạnh trên phải chạy phía trên đỉnh đầu và gối bé để đảm bảo an toàn. Không bao gồm người lớn nằm cạnh.
- true_safe_zone ([left, top, right, bottom] từ 0.03 đến 0.97): Tọa độ khung chữ nhật bao ngoài tấm đệm của em bé.

Trả về đúng JSON:
{{
  "baby_present": boolean,
  "is_baby_awake": boolean,
  "tracking_accurate": boolean,
  "accuracy_score": integer,
  "true_baby_box": [float, float, float, float],
  "true_head_box": [float, float, float, float],
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
                "true_safe_zone": data.get("true_safe_zone"),
                "true_safe_zone_polygon": data.get("true_safe_zone_polygon"),
                "sleep_pose_vi": data.get("sleep_pose_vi", "Nằm ngửa"),
                "feedback_vi": feedback
            }
        except Exception as e:
            print(f"[GeminiVerifier] Lỗi audit_local_tracking: {e}")
            return {"audited": False, "error": str(e)}

    # =========================================================================
    # 1. HỘI CHẨN CẢNH BÁO NGUY HIỂM CAO (CHỐNG BÁO ĐỘNG GIẢ GỐI ÔM / NẰM SẤP)
    # =========================================================================
    def verify_high_risk_alert(self, frame_bgr, alert_type: str = "covered_face", local_reason: str = "") -> dict:
        if not self.is_ready() or not self.verify_alerts_enabled:
            return {
                "verified_by_gemini": False,
                "is_dangerous": True,
                "diagnosis_vi": local_reason or "Cảnh báo từ hệ thống AI cục bộ.",
                "confidence": 80
            }

        now = time.time()
        last_t = self.last_alert_verify_time.get(alert_type, 0.0)
        if (now - last_t) < self.alert_cooldown_sec and alert_type in self.last_alert_result:
            cached = self.last_alert_result[alert_type].copy()
            cached["from_cache"] = True
            return cached

        img_bytes = self._encode_frame_jpeg(frame_bgr, max_dim=768)
        if not img_bytes:
            return {"verified_by_gemini": False, "is_dangerous": True, "diagnosis_vi": local_reason, "confidence": 50}

        prompt = f"""
Bạn là Bác sĩ Nhi khoa & Chuyên gia An toàn Giấc ngủ Trẻ sơ sinh (BabyGuard AI).
Hệ thống camera Edge AI vừa phát tín hiệu nghi ngờ: "{alert_type}" ({local_reason}) đối với bé {self.baby_name} ({self.baby_age_months} tháng tuổi).

Hãy quan sát thật kỹ bức ảnh thực tế này và phân biệt chính xác:
1. NGUY HIỂM THẬT (is_dangerous = true):
   - Chăn, khăn, gối ôm hoặc thú bông đang đè trực tiếp lên vùng MŨI hoặc MIỆNG làm cản trở đường thở của bé.
   - Hoặc bé đang nằm úp sấp mặt (prone) úp mũi xuống đệm.
2. BÁO ĐỘNG GIẢ / AN TOÀN (is_dangerous = false):
   - Gối ôm / thú bông CHỈ nằm sát bên cạnh sườn, vai hoặc đỉnh đầu để chặn cho bé khỏi giật mình, nhưng vùng MŨI và MIỆNG của bé vẫn lộ rõ, thông thoáng hoàn toàn.
   - Hoặc bé chỉ đang nằm nghiêng đầu ngủ ngon lành, không bị vật gì đè lên mặt.

Trả về đúng định dạng JSON:
{{
  "is_dangerous": boolean,
  "confidence": integer (0-100),
  "airway_clear": boolean,
  "diagnosis_vi": "Câu nhận xét ngắn gọn, rõ ràng bằng tiếng Việt giải thích vì sao an toàn hoặc nguy hiểm"
}}
"""
        try:
            self.status_text = "Đang hội chẩn Gemini..."
            resp = self._call_gemini_resilient(
                contents=[
                    types.Part.from_bytes(data=img_bytes, mime_type="image/jpeg"),
                    prompt
                ],
                call_type="alert_verify",
                json_mode=True,
                temperature=0.1
            )
            data = json.loads(resp.text)
            result = {
                "verified_by_gemini": True,
                "is_dangerous": bool(data.get("is_dangerous", False)),
                "airway_clear": bool(data.get("airway_clear", True)),
                "confidence": int(data.get("confidence", 90)),
                "diagnosis_vi": str(data.get("diagnosis_vi", "Đã kiểm tra qua Gemini AI."))
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
            self.status_text = "An toàn (Đã xác thực AI)" if not result["is_dangerous"] else "CẢNH BÁO ĐÃ XÁC THỰC"
            print(f"[GeminiVerifier] Hội chẩn ({alert_type}): dangerous={result['is_dangerous']} - {result['diagnosis_vi']}")
            return result
        except Exception as e:
            print(f"[GeminiVerifier] Lỗi gọi Gemini verify_high_risk_alert: {e}")
            return {
                "verified_by_gemini": False,
                "is_dangerous": True,
                "diagnosis_vi": local_reason or "Cảnh báo từ AI cục bộ",
                "confidence": 75
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
            return {"checked_by_gemini": False, "approved": False, "reason_vi": "Lỗi mã hóa ảnh."}

        prompt = f"""
Bạn là Giám khảo Nhiếp ảnh Trẻ Sơ Sinh & Giám sát Quyền Riêng Tư (Strict Infant Photography & Privacy Inspector) của hệ thống BabyGuard AI.
Bức ảnh này được hệ thống chụp để lưu vào Album Kỷ Niệm của bé {self.baby_name}.

QUY TẮC KIỂM DUYỆT BẮT BUỘC (TUYỆT ĐỐI KHÔNG DU DI):

1. KIỂM DUYỆT QUYỀN RIÊNG TƯ & AN TOÀN (ZERO TOLERANCE - TỪ CHỐI NGAY LẬP TỨC):
   - NẾU trong ảnh có bất kỳ người lớn nào cởi trần, hở lưng, lộ đùi, mặc đồ lót, đồ ngủ nhạy cảm, hoặc nằm ở tư thế khó coi/phản cảm:
     -> BẮT BUỘC TỪ CHỐI (approved = false, privacy_safe = false, reason_vi = "Ảnh có người lớn chưa chỉnh tề hoặc tư thế nhạy cảm").
   - NẾU KHÔNG THẤY RÕ RÀNG KHUÔN MẶT CỦA EM BÉ (ảnh chỉ có tay/chân/lưng bé, chụp sau gáy, chăn gối che mất mặt, ảnh tối đen hoặc mờ tịt):
     -> BẮT BUỘC TỪ CHỐI (approved = false, baby_face_clear = false, reason_vi = "Không nhận diện được rõ nét khuôn mặt em bé").
   - NẾU em bé đang thay tã hoặc không mặc tã/quần áo:
     -> BẮT BUỘC TỪ CHỐI (approved = false, reason_vi = "Bé chưa mặc đồ chỉnh tề").

2. ĐIỀU KIỆN ĐỂ DUYỆT LƯU VÀO ALBUM (approved = true):
   - CHỈ DUYỆT khi và chỉ khi nhìn thấy RÕ RÀNG VÀ ĐẦY ĐỦ KHUÔN MẶT EM BÉ (mắt, mũi, miệng rõ ràng). Bé đang ngủ bình yên hoặc thức nhìn đáng yêu.
   - Bé mặc quần áo/tã/quấn khăn lịch sự kín đáo.
   - Bố cục ảnh tập trung vào em bé, hoàn toàn KHÔNG có cảnh nhạy cảm của người lớn.
   - Điểm thẩm mỹ đạt từ 7/10 trở lên.

Trả về đúng định dạng JSON:
{{
  "baby_face_clear": boolean,
  "privacy_safe": boolean,
  "has_adult_nudity_or_body": boolean,
  "approved": boolean,
  "aesthetic_score": integer,
  "caption_vi": "Một câu chú thích tiếng Việt thật ấm áp về nụ cười hoặc giấc ngủ của bé",
  "reason_vi": "Giải thích lý do duyệt hoặc từ chối"
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
            baby_face_clear = bool(data.get("baby_face_clear", False))
            privacy_safe = bool(data.get("privacy_safe", False))
            has_nudity = bool(data.get("has_adult_nudity_or_body", False))
            score = int(data.get("aesthetic_score", 0))

            approved = (
                baby_face_clear
                and privacy_safe
                and not has_nudity
                and bool(data.get("approved", False))
                and score >= 7
            )

            result = {
                "checked_by_gemini": True,
                "approved": approved,
                "privacy_safe": approved,
                "baby_face_clear": baby_face_clear,
                "has_other_person": False,
                "aesthetic_score": score,
                "caption_vi": str(data.get("caption_vi", f"Khoảnh khắc đáng yêu của {self.baby_name}")),
                "reason_vi": str(data.get("reason_vi", ""))
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
                valid_poly = [[round(float(np.clip(p[0], 0.01, 0.99)), 3),
                               round(float(np.clip(p[1], 0.01, 0.99)), 3)] for p in poly]
                xs = [p[0] for p in valid_poly]
                ys = [p[1] for p in valid_poly]
                left = min(xs)
                right = max(xs)
                top = min(ys)
                bottom = max(ys)
            else:
                top = float(np.clip(data.get("safe_zone_top", 0.08), 0.02, 0.45))
                bottom = float(np.clip(data.get("safe_zone_bottom", 0.95), 0.55, 0.98))
                left = float(np.clip(data.get("safe_zone_left", 0.05), 0.02, 0.45))
                right = float(np.clip(data.get("safe_zone_right", 0.95), 0.55, 0.98))
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
        if y_sleep is not None:
            sleep_tracking_metric_str = (
                f"- Chu kỳ 24h trọn vẹn ngày hôm trước: Bé đã ngủ {y_sleep} giờ (cữ sâu dài nhất {y_nap} phút, điểm giấc ngủ: {y_score}/100 đạt chuẩn AAP).\n"
                f"- Tiến độ cữ ngủ sáng nay (từ 00:00): Hệ thống camera ghi nhận {total_sleep} giờ ngủ trong nôi."
            )
        else:
            sleep_tracking_metric_str = f"- Thời gian ngủ trực tiếp qua camera ghi nhận: {total_sleep} giờ"

        prompt = f"""
Bạn là Bác sĩ Nhi khoa Chuyên gia về Sơ sinh & Giấc ngủ Trẻ em (Pediatrician & Sleep Specialist) của hệ thống BabyGuard AI.
Dưới đây là hồ sơ đo lường sinh học thực tế của em bé {baby_name} ({age_display}) trong 24 giờ qua:

1. DỮ LIỆU ĐO LƯỜNG THỰC TẾ QUA CAMERA BABYGUARD AI:
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

Hãy phân tích toàn diện, khoa học và đưa ra BÁO CÁO NHI KHOA BUỔI SÁNG cho bố mẹ với các yêu cầu bắt buộc:
A. PHÂN TÍCH RÕ RÀNG: Dữ liệu ghi nhận trong camera vs Thời gian ngoài camera:
   - Ghi nhận chính xác số giờ camera bắt được. Nếu đang là buổi sáng sớm và hệ thống vừa reset lúc 00:00, hãy đối chiếu chu kỳ 24h trọn vẹn của ngày hôm trước ({y_sleep if y_sleep is not None else total_sleep}h) để đánh giá đúng nhịp sinh học tổng thể của bé thay vì vội kết luận bé thiếu ngủ.
   - Với thời gian ngoài camera ({camera_offline} giờ): Phân tích dựa trên chuẩn sinh lý của Viện Hàn lâm Nhi khoa Hoa Kỳ (AAP) và Hiệp hội Y học Giấc ngủ Hoa Kỳ (AASM) cho trẻ ở độ tuổi {age_display} (nhu cầu ngủ tổng 14-17 giờ/ngày, cửa sổ thức 45-90 phút).
B. ĐÁNH GIÁ SỨC KHỎE HÔ HẤP & TIÊU HÓA:
   - Đánh giá nhịp thở {avg_bpm} BPM (đối chiếu chuẩn sinh lý sơ sinh 30 - 60 BPM).
   - Đánh giá các cơn ho/sặc sữa ({cough_count} lần) và quấy khóc ({crying_count} lần), hướng dẫn mẹ cách chống sặc sữa và trào ngược dạ dày thực quản (GERD): giữ bé thẳng đứng 15-20 phút sau bú, vỗ ợ hơi, kê cao đầu nôi 15 độ.
C. ĐÁNH GIÁ THỂ TRẠNG THEO CHUẨN WHO:
   - Nhận xét chiều cao và cân nặng so với Chuẩn Tăng trưởng Trẻ em của WHO (WHO Child Growth Standards).
D. LỜI KHUYÊN & LỊCH SINH HOẠT HÔM NAY:
   - Hướng dẫn Cửa sổ thức (Wake Window) và giờ ru ngủ tối ưu cho ngày hôm nay.
   - Tuân thủ quy tắc ngủ an toàn ABC (Alone, Back, Crib) của AAP.
E. TRÍCH DẪN NGUỒN NGHIÊN CỨU KHOA HỌC:
   - Phải ghi rõ nguồn trích dẫn: Viện Hàn lâm Nhi khoa Hoa Kỳ (AAP Policy Statement on Safe Sleep), Tổ chức Y tế Thế giới (WHO Child Growth Standards), Hiệp hội Y học Giấc ngủ Hoa Kỳ (AASM).

Trả về đúng định dạng JSON:
{{
  "headline_vi": "Tiêu đề báo cáo ngắn gọn, ấm áp",
  "summary_vi": "Phân tích cụ thể giữa số liệu đo trong camera và ước lượng thời gian ngoài camera theo chuẩn sinh lý lứa tuổi (3-4 câu tiếng Việt)",
  "respiratory_and_reflux_vi": "Nhận xét chi tiết về nhịp thở, ho/sặc sữa và hướng dẫn xử lý chống sặc sữa (3-4 câu tiếng Việt)",
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
            tele_msg = (
                f"🩺 <b>BÁO CÁO NHI KHOA BUỔI SÁNG (07:00) — {baby_name.upper()}</b>\n"
                f"👶 <i>Độ tuổi: {age_display} | Ngày: {sleep_summary.get('today_date')}</i>\n"
                f"━━━━━━━━━━━━━━━━━━━\n\n"
                f"📊 <b>1. GIÁM SÁT GIẤC NGỦ & CAMERA 24H:</b>\n"
                f"• Ghi nhận qua Camera: <b>{total_sleep}h ngủ</b> | <b>{total_awake}h thức</b>\n"
                f"• Ngoài tầm quan sát: ~<b>{camera_offline}h</b> (bế chơi, bú sữa, tắm...)\n"
                f"• Chu kỳ: <b>{sleep_summary.get('deep_ratio_pct', 55)}% NREM</b> (Sâu) | <b>{sleep_summary.get('rem_ratio_pct', 45)}% REM</b> (Động)\n"
                f"• Điểm giấc ngủ AI: <b>{sleep_summary.get('sleep_score', 85)}/100</b>\n"
                f"👉 <i>{summary_vi}</i>\n\n"
                f"🫁 <b>2. HÔ HẤP, HO & PHÒNG CHỐNG SẶC SỮA:</b>\n"
                f"• Nhịp thở khi ngủ: <b>{avg_bpm} BPM</b> (Chuẩn sơ sinh: 30 - 60 BPM)\n"
                f"• Cơn ho / trớ sặc sữa: <b>{cough_count} lần</b> | Tiếng khóc: <b>{crying_count} lần</b>\n"
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
