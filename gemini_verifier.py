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
    def should_run_tracking_audit(self, local_uncertain: bool = False, need_initial_crib_calib: bool = False) -> bool:
        """
        Kiểm tra xem trong khoảng thời gian vừa rồi đã gọi API bao nhiêu lần.
        Nếu mới khởi động (cần tự động căn chỉnh khung nôi lần đầu) hoặc đang rảnh (còn dư nhiều request Free)
        -> Chủ động gửi hình lên Gemini để tự động căn chỉnh Khung Giường/Nôi VÀ kiểm tra khung Tracking Em Bé!
        """
        if not self.is_ready():
            return False

        now = time.time()
        elapsed = now - self.last_tracking_audit_time
        if need_initial_crib_calib:
            min_interval = 6.0
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

B. KIỂM TRA & TỰ ĐỘNG CĂN CHỈNH KHUNG NÔI / TẤM ĐỆM EM BÉ (SAFE ZONE):
- crib_zone_accurate (boolean): Khung viền xanh lá cây hiện tại đã bao quanh hợp lý vùng tấm đệm/chiếu/lòng nôi nơi em bé nằm chưa? (Nếu khung xanh lá đang quá rộng tràn hết ra giường người lớn hoặc bị lệch khỏi tấm đệm trắng của bé -> false).
- true_safe_zone ([left, top, right, bottom] từ 0.03 đến 0.97): Tọa độ khung chữ nhật bao quanh vừa vặn tấm đệm/chiếu/lòng nôi của em bé (mở rộng dư ra khoảng 3-5% quanh mép tấm đệm của bé để làm ranh giới an toàn).

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
Bạn là Giám khảo Nhiếp ảnh Gia đình & Cắt Khung Thông Minh (Smart Auto-Crop) của hệ thống BabyGuard AI.
Hãy đánh giá bức ảnh chụp bé {self.baby_name} để lưu vào Album Kỷ Niệm theo quy tắc THÔNG MINH & LINH HOẠT sau:

1. KIỂM TRA BẢN THÂN EM BÉ (baby_valid & aesthetic_score từ 1-10):
   - Em bé có mặc quần áo/quấn khăn lịch sự (không phải đang thay tã) và gương mặt bé có rõ ràng, đáng yêu, bình yên không?
   - Nếu không thấy mặt bé hoặc bé đang thay tã -> baby_valid = false.

2. KIỂM TRA NGƯỜI KHÁC / VÙNG XUNG QUANH & CHỌN CHẾ ĐỘ XỬ LÝ (crop_mode):
   - Trường hợp A ("family_wide" - Giữ nguyên toàn khung hình):
     + Khi trong ảnh hoàn toàn KHÔNG có người lớn/vật nhạy cảm nào khác;
     + HOẶC có bố/mẹ nằm cạnh bé mà bố/mẹ mặc trang phục lịch sự kín đáo VÀ gương mặt bố/mẹ xuất hiện nguyên vẹn, đẹp đẽ, tình cảm cùng bé.
   - Trường hợp B ("baby_portrait" - Tự động cắt lấy riêng khung cận cảnh em bé):
     + Khi bản thân em bé rất đáng yêu (baby_valid = true), NHƯNG ở xung quanh/rìa ảnh có bố/mẹ đang nằm quay lưng, bị cắt nửa mặt, trang phục ở nhà chưa kín đáo, hoặc có màn hình laptop/iPad ở rìa.
     + ĐỪNG TỪ CHỐI ẢNH! Hãy chọn crop_mode = "baby_portrait" và trả về tọa độ `clean_crop_box: [xmin, ymin, xmax, ymax]` (từ 0.0 đến 1.0) chỉ đóng khung gọn quanh em bé và phần gối/đệm sạch sẽ của bé, sao cho bên trong vùng cắt `clean_crop_box` TUYỆT ĐỐI KHÔNG dính phần cơ thể nhạy cảm hay màn hình phụ của người lớn!
   - Trường hợp C ("reject" - Từ chối hoàn toàn):
     + Chỉ chọn "reject" khi baby_valid = false, hoặc phần cơ thể nhạy cảm của người lớn nằm đè trực tiếp ngay sát mặt/người bé khiến ngay cả khi cắt hẹp (`clean_crop_box`) vẫn bị lộ vùng nhạy cảm.

Trả về đúng định dạng JSON:
{{
  "baby_valid": boolean,
  "crop_mode": "family_wide" | "baby_portrait" | "reject",
  "clean_crop_box": [float, float, float, float],
  "has_other_person_in_final": boolean,
  "aesthetic_score": integer,
  "caption_vi": "Một câu chú thích tiếng Việt thật ngọt ngào, ấm áp cho bức ảnh",
  "reason_vi": "Giải thích ngắn gọn (VD: Đã tự động cắt gọn khung chân dung bé để loại bỏ phần rìa)"
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
            baby_valid = bool(data.get("baby_valid", False))
            crop_mode = str(data.get("crop_mode", "reject")).lower()
            score = int(data.get("aesthetic_score", 8))
            clean_box = data.get("clean_crop_box", [0.15, 0.15, 0.85, 0.85])

            approved = baby_valid and (crop_mode in ("family_wide", "baby_portrait")) and (score >= 6)
            auto_cropped = (crop_mode == "baby_portrait")

            result = {
                "checked_by_gemini": True,
                "approved": approved,
                "privacy_safe": approved,
                "crop_mode": crop_mode,
                "auto_cropped": auto_cropped,
                "clean_crop_box": clean_box,
                "has_other_person": bool(data.get("has_other_person_in_final", False)) if not auto_cropped else False,
                "other_person_aesthetic": True,
                "aesthetic_score": score,
                "caption_vi": str(data.get("caption_vi", f"Khoảnh khắc đáng yêu của {self.baby_name}")),
                "reason_vi": str(data.get("reason_vi", ""))
            }

            print(f"[GeminiVerifier] Duyệt ảnh Cute Moment ({self.active_model}): approved={approved}, "
                  f"mode={crop_mode}, score={score} -> {result['reason_vi']}")
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
Bạn là Kỹ sư Thị giác Máy tính & Chuyên gia An toàn Nôi Em Bé.
Hãy phân tích khung hình camera giám sát này và xác định:
1. Tọa độ khung chữ nhật bao quanh LÒNG NÔI / VÙNG ĐỆM AN TOÀN nơi em bé nằm (tính theo tỷ lệ chuẩn hóa từ 0.0 đến 1.0 so với chiều rộng và chiều cao ảnh):
   - safe_zone_left (0.02 - 0.45)
   - safe_zone_right (0.55 - 0.98)
   - safe_zone_top (0.02 - 0.45)
   - safe_zone_bottom (0.55 - 0.98)
2. Danh sách các vật thể đang có trong nôi (gối ôm, gối chặn, chăn, thú bông...).
3. Nhận xét ngắn gọn bằng tiếng Việt về mức độ thông thoáng và an toàn của nôi hiện tại.

Trả về đúng định dạng JSON:
{
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
            top = float(np.clip(data.get("safe_zone_top", 0.08), 0.02, 0.45))
            bottom = float(np.clip(data.get("safe_zone_bottom", 0.95), 0.55, 0.98))
            left = float(np.clip(data.get("safe_zone_left", 0.05), 0.02, 0.45))
            right = float(np.clip(data.get("safe_zone_right", 0.95), 0.55, 0.98))

            self.status_text = "Đã căn chỉnh nôi thành công"
            return {
                "success": True,
                "safe_zone": {
                    "top": round(top, 3),
                    "bottom": round(bottom, 3),
                    "left": round(left, 3),
                    "right": round(right, 3)
                },
                "baby_present": bool(data.get("baby_present", True)),
                "objects_detected": data.get("objects_detected", []),
                "safety_advice_vi": str(data.get("safety_advice_vi", "Đã tự động căn chỉnh vùng an toàn theo lòng nôi."))
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    # =========================================================================
    # 5. BÁC SĨ NHI KHOA AI: PHÂN TÍCH GIẤC NGỦ ĐÊM QUA & 24H (SÁNG HÔM SAU 07:00)
    # =========================================================================
    def generate_daily_sleep_report(self, sleep_summary: dict) -> dict:
        """
        Gửi toàn bộ thống kê Chu kỳ ngủ (NREM/REM), Cửa sổ thức (Wake Window),
        các cữ ngủ đêm qua & 24h qua lên Gemini để lập Bảng Phân Tích Nhi Khoa vào sáng hôm sau (07:00) hoặc theo yêu cầu.
        """
        if not self.is_ready():
            return {"success": False, "error": "Chưa cấu hình Gemini API Key"}

        prompt = f"""
Bạn là Bác sĩ Nhi khoa Chuyên gia về Giấc ngủ Trẻ sơ sinh & Trẻ nhỏ (Pediatric Sleep Specialist) của hệ thống BabyGuard AI.
Dưới đây là số liệu đo lường sinh học thực tế của em bé trong 24 giờ qua (bao gồm trọn vẹn giấc ngủ đêm qua và các cữ ngủ/thức):
- Ngày báo cáo: {sleep_summary.get("today_date")}
- Tổng thời gian ngủ tích lũy: {sleep_summary.get("total_sleep_today_hours")} giờ
- Tổng thời gian thức chơi & vận động: {sleep_summary.get("total_awake_today_hours")} giờ
- Tỷ lệ Ngủ Sâu (NREM): {sleep_summary.get("deep_ratio_pct")}% | Ngủ Động (REM): {sleep_summary.get("rem_ratio_pct")}%
- Cữ ngủ liền mạch dài nhất: {sleep_summary.get("longest_nap_minutes")} phút
- Số lần thức giấc chuyển cữ: {sleep_summary.get("wake_count_today")} lần
- Số lần giật mình sinh lý (Moro / REM): {sleep_summary.get("rem_twitch_count")} lần
- Điểm chất lượng giấc ngủ: {sleep_summary.get("sleep_score")}/100
- Danh sách các cữ ngủ đã ghi nhận: {json.dumps(sleep_summary.get("sessions", [])[:8], ensure_ascii=False)}

Hãy phân tích chuyên sâu như một Bác sĩ Nhi khoa gửi Báo cáo Tổng kết Sáng hôm sau (07:00 sáng) cho bố mẹ:
1. summary_vi: Nhận xét tổng quan (2-3 câu tiếng Việt ấm áp, khoa học) đánh giá chất lượng giấc ngủ đêm qua & 24h qua của bé (độ sâu giấc ngủ, khả năng tự nối giấc qua chu kỳ 50 phút, sự phát triển trí não trong pha REM và chiều cao trong pha NREM).
2. schedule_advice_vi: Gợi ý lịch sinh hoạt & cách canh Cửa sổ thức (Wake Window) cho các cữ ngủ trong ngày hôm nay dựa trên chất lượng giấc ngủ đêm qua.
3. tips_vi: Mảng gồm đúng 3 lời khuyên thực tế, ngắn gọn cho bố mẹ trong ngày hôm nay.

Trả về đúng định dạng JSON:
{{
  "summary_vi": "string",
  "schedule_advice_vi": "string",
  "tips_vi": ["string", "string", "string"]
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
            report = {
                "date": sleep_summary.get("today_date"),
                "generated_at": time.strftime("%H:%M - %d/%m"),
                "model": f"Bác Sĩ AI ({self.active_model})",
                "summary_vi": str(data.get("summary_vi", "")),
                "schedule_advice_vi": str(data.get("schedule_advice_vi", "")),
                "tips_vi": data.get("tips_vi", [])[:3]
            }
            return {"success": True, "report": report}
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
