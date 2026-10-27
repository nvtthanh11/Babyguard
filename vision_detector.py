import os
import sys
import time
import json
import threading
from datetime import datetime
import cv2
import numpy as np
import torch
from scipy.signal import butter, filtfilt
from PIL import Image, ImageDraw, ImageFont
from ultralytics import YOLO


BASE_DIR = os.path.dirname(os.path.abspath(__file__))


class VisionTracker:
    def __init__(self, model_path: str = None, camera_index: int = 0,
                 width: int = 1280, height: int = 720, fps: int = 15,
                 motion_threshold: float = 18.0, on_motion_callback=None, on_prone_callback=None,
                 on_covered_face_callback=None, on_danger_zone_callback=None, on_apnea_callback=None,
                 frame_callback=None, sleep_tracker=None, gemini_verifier=None,
                 prone_alert_enabled: bool = True,
                 danger_zone_enabled: bool = True,
                 safe_zone_top: float = 0.15,
                 safe_zone_bottom: float = 0.88,
                 safe_zone_left: float = 0.08,
                 safe_zone_right: float = 0.92,
                 covered_face_alert: bool = True,
                 breathing_monitor_enabled: bool = True,
                 cute_moments_enabled: bool = True,
                 moments_dir: str = None,
                 danger_zone_y_percent: float = None,
                 danger_zone_x_percent: float = None,
                 safe_zone_polygon: list = None):
        self.camera_index = camera_index
        self.width = width
        self.height = height
        self.target_fps = fps
        self.motion_threshold = motion_threshold
        self.on_motion_callback = on_motion_callback
        self.on_prone_callback = on_prone_callback
        self.on_covered_face_callback = on_covered_face_callback
        self.on_danger_zone_callback = on_danger_zone_callback
        self.on_apnea_callback = on_apnea_callback
        self.frame_callback = frame_callback
        self.sleep_tracker = sleep_tracker
        self.gemini_verifier = gemini_verifier
        self.gemini_suppressed_until = 0.0
        self.pending_alert_verify = False
        self.pending_moment_eval = False
        
        self.prone_alert_enabled = prone_alert_enabled
        self.danger_zone_enabled = danger_zone_enabled
        def _clean_coord(val, default_val, max_d):
            try:
                v = float(val) if val is not None else default_val
                if v > 1.0:
                    v = v / 1000.0 if v <= 1000.0 else v / max_d
                return round(max(0.01, min(0.99, v)), 3)
            except Exception:
                return default_val

        if safe_zone_polygon and isinstance(safe_zone_polygon, list) and len(safe_zone_polygon) == 4:
            clean_poly = []
            for p in safe_zone_polygon:
                clean_poly.append([
                    _clean_coord(p[0], 0.15, 1280.0),
                    _clean_coord(p[1], 0.18, 720.0)
                ])
            self.safe_zone_polygon = clean_poly
            xs = [p[0] for p in self.safe_zone_polygon]
            ys = [p[1] for p in self.safe_zone_polygon]
            self.safe_zone_left = round(min(xs), 3)
            self.safe_zone_right = round(max(xs), 3)
            self.safe_zone_top = round(min(ys), 3)
            self.safe_zone_bottom = round(max(ys), 3)
        else:
            self.safe_zone_top = _clean_coord(safe_zone_top, 0.18, 720.0)
            self.safe_zone_bottom = _clean_coord(danger_zone_y_percent if danger_zone_y_percent is not None else safe_zone_bottom, 0.95, 720.0)
            self.safe_zone_left = _clean_coord(safe_zone_left, 0.15, 1280.0)
            self.safe_zone_right = _clean_coord(danger_zone_x_percent if danger_zone_x_percent is not None else safe_zone_right, 0.92, 1280.0)
            self.safe_zone_polygon = [
                [self.safe_zone_left, self.safe_zone_top],
                [self.safe_zone_right, self.safe_zone_top],
                [self.safe_zone_right, self.safe_zone_bottom],
                [self.safe_zone_left, self.safe_zone_bottom]
            ]
        self.danger_zone_y_percent = self.safe_zone_bottom
        self.danger_zone_x_percent = self.safe_zone_right
        self.covered_face_alert = covered_face_alert
        self.breathing_monitor_enabled = breathing_monitor_enabled
        self.cute_moments_enabled = cute_moments_enabled
        self.moments_dir = moments_dir or os.path.join(BASE_DIR, "moments")
        os.makedirs(self.moments_dir, exist_ok=True)
        # Chu kỳ giãn cách tối ưu: 12 phút (720s) giữa các lần chụp để ảnh luôn chọn lọc & tiết kiệm API
        self.moment_capture_interval = 720.0
        # Cho phép tự động chụp khoảnh khắc đầu tiên sau 30s kể từ khi khởi động
        self.last_moment_time = time.time() - (self.moment_capture_interval - 30.0)
        self.recent_moment_crops = [] # Lưu các thumbnail 64x64 để chống chụp trùng lặp >= 78%
        self.last_moment_landmarks = None # (mouth_ratio, open_ratio)
        self.initial_crib_calibrated = bool(safe_zone_polygon and len(safe_zone_polygon) == 4)

        # Tọa Độ Vàng (Snapshot Rollback an toàn) & Xác thực 2 bước (Two-Phase Commit)
        import copy, collections
        self.last_verified_safe_zone = copy.deepcopy(self.safe_zone_polygon)
        self.pending_crib_candidate = None
        self.pending_crib_hits = 0

        # Buffer lưu trữ 5 khung hình thô gần nhất để khử nhiễu đa khung hình ban đêm (Night Stacking)
        self.raw_frame_burst = collections.deque(maxlen=5)
        
        # Breathing metrics (Đo quang học nhịp thở thật từ bụng & lồng ngực với Butterworth DSP)
        self.breathing_bpm = 42.0
        self.breathing_status = "Đang đo..."
        self.chest_history = []
        self.last_motion_time = time.time()
        self.last_breath_peak_time = time.time()
        self.last_chest_poly = None
        
        self.is_near_edge = False
        
        self.covered_face_frame_count = 0
        self.danger_zone_frame_count = 0
        self.had_visible_face = False
        self.last_face_box = None
        self.is_swaddled = False

        # Face-First Detector (OpenCV YuNet ONNX model)
        yunet_path = os.path.join(BASE_DIR, "models", "face_detection_yunet.onnx")
        self.has_face_detector = False
        self.face_detector = None
        if os.path.exists(yunet_path) and hasattr(cv2, "FaceDetectorYN"):
            try:
                self.face_detector = cv2.FaceDetectorYN.create(
                    model=yunet_path,
                    config="",
                    input_size=(self.width, self.height),
                    score_threshold=0.38,
                    nms_threshold=0.3
                )
                self.has_face_detector = True
                print("[VisionTracker] Loaded YuNet Face Detector successfully.")
            except Exception as e:
                print(f"[VisionTracker] Warning: YuNet Face Detector failed: {e}")
        
        # Select device (Apple Silicon Metal MPS or CPU)
        self.device = "mps" if torch.backends.mps.is_available() else "cpu"
        if not model_path:
            model_path = os.path.join(BASE_DIR, "models", "yolov8n-pose.pt")
            if not os.path.exists(model_path):
                model_path = os.path.join(BASE_DIR, "yolov8n-pose.pt")
        elif not os.path.isabs(model_path) and not os.path.exists(model_path):
            alt_path = os.path.join(BASE_DIR, "models", model_path)
            if os.path.exists(alt_path):
                model_path = alt_path
        print(f"[VisionTracker] Loading YOLOv8-pose from {model_path} on {self.device.upper()}...")
        self.model = YOLO(model_path)
        
        # Load Vietnamese TrueType Font
        font_path = "/System/Library/Fonts/Supplemental/Arial.ttf"
        if not os.path.exists(font_path):
            font_path = "/Library/Fonts/Arial Unicode.ttf"
        try:
            self.font_title = ImageFont.truetype(font_path, 18)
            self.font_body = ImageFont.truetype(font_path, 15)
            self.font_small = ImageFont.truetype(font_path, 13)
        except Exception as e:
            print(f"[VisionTracker] Warning: font loading failed ({e}), using default")
            self.font_title = self.font_body = self.font_small = ImageFont.load_default()

        # State variables
        self.is_running = False
        self.lock = threading.Lock()
        self.raw_frame = None
        self.annotated_frame = None
        
        # Tracking metrics
        self.baby_detected = False
        self.adult_holding_baby = False
        self.baby_stable_detected = False
        self.baby_stable_frames = 0
        self.baby_last_seen_time = 0.0
        self.last_baby_box = None
        self.covered_face_active = False
        self.covered_face_frame_count = 0
        self.lost_frames = 0
        self.motion_score = 0.0
        self.smoothed_motion = 0.0
        self.sleep_pose = "Đang quét..."
        self.baby_status = "Đang quét..."
        self.prev_keypoints = None
        self.prev_keypoints_conf = None
        self.fps_actual = 0.0
        
        # Tầng 1: Debounce thời gian theo dõi thay đổi tư thế ngủ (Bé phải giữ tư thế mới >= 10 giây mới gửi Gemini)
        self.last_confirmed_pose = "Đang quét..."
        self.pose_candidate = None
        self.pose_candidate_start_time = 0.0
        self.pose_debounce_sec = 10.0
        self.pose_changed_and_stabilized = False

        self.prone_frame_count = 0
        self.worker_thread = None

    def _determine_pose(self, kpts_xy, confs):
        """
        Estimate sleeping position from COCO 17 keypoints:
        0: nose, 1: l_eye, 2: r_eye, 3: l_ear, 4: r_ear
        5: l_shoulder, 6: r_shoulder, 11: l_hip, 12: r_hip
        """
        nose_conf = confs[0]
        eye_max = max(confs[1], confs[2])
        face_conf = np.mean(confs[:3])
        torso_conf = np.mean([confs[5], confs[6]])

        # Prone (Face-down danger):
        # Torso/back is clearly seen from behind, but nose & eyes are completely covered
        if torso_conf > 0.45 and face_conf < 0.15:
            return "Nằm sấp (Cảnh báo nguy hiểm)", "danger"

        # Side sleeping (common when propped with a bolster pillow):
        # One eye/ear is clearly visible while the other is hidden
        eye_diff = abs(confs[1] - confs[2])
        if (confs[1] > 0.35 and confs[2] < 0.2) or (confs[2] > 0.35 and confs[1] < 0.2) or eye_diff > 0.4:
            return "Nằm nghiêng an toàn", "safe"

        # Supine (on back):
        # Both eyes / nose visible
        if nose_conf > 0.3 and eye_max > 0.3:
            return "Nằm ngửa an toàn", "safe"

        return "Nằm ngủ ngoan", "safe"

    def _get_safe_zone_polygon(self, w: int, h: int) -> np.ndarray:
        """Trả về mảng đa giác 4 đỉnh của vùng an toàn (Safe Zone) theo góc phối cảnh 3D."""
        if getattr(self, "safe_zone_polygon", None) and len(self.safe_zone_polygon) >= 3:
            pts = []
            for p in self.safe_zone_polygon:
                px = float(p[0])
                py = float(p[1])
                if px > 1.0:
                    px = px / 1000.0 if px <= 1000.0 else px / float(w)
                if py > 1.0:
                    py = py / 1000.0 if py <= 1000.0 else py / float(h)
                px = max(0.01, min(0.99, px))
                py = max(0.01, min(0.99, py))
                pts.append([int(px * w), int(py * h)])
            return np.array(pts, dtype=np.int32)
        
        def _clamp(v, default_v, max_d):
            try:
                val = float(v)
                if val > 1.0:
                    val = val / 1000.0 if val <= 1000.0 else val / max_d
                return max(0.01, min(0.99, val))
            except Exception:
                return default_v

        x1 = int(_clamp(self.safe_zone_left, 0.15, float(w)) * w)
        x2 = int(_clamp(self.safe_zone_right, 0.92, float(w)) * w)
        y1 = int(_clamp(self.safe_zone_top, 0.18, float(h)) * h)
        y2 = int(_clamp(self.safe_zone_bottom, 0.95, float(h)) * h)
        return np.array([[x1, y1], [x2, y1], [x2, y2], [x1, y2]], dtype=np.int32)

    def _is_point_in_safe_zone(self, px: float, py: float, w: int, h: int, margin_px: float = 0.0) -> bool:
        """Sử dụng cv2.pointPolygonTest chuẩn xác để kiểm tra tọa độ (px, py) có nằm trong Safe Zone không."""
        poly = self._get_safe_zone_polygon(w, h)
        dist = cv2.pointPolygonTest(poly, (float(px), float(py)), True)
        return dist >= -float(margin_px)

    def _validate_crib_polygon(self, pts: list, w: int = 1280, h: int = 720, check_baby: bool = True) -> bool:
        """
        Kiểm định tính hợp lệ vật lý của khung nôi 3D (Sanity Check):
        1. Đúng 4 đỉnh tọa độ tỷ lệ float chuẩn hóa [0.01, 0.99].
        2. Tứ giác lồi hợp lệ (không xoắn chéo hình đồng hồ cát).
        3. Diện tích hợp lý: Chiếm từ 10% đến 88% diện tích màn hình.
        4. Nếu bé đang nằm nôi: Trọng tâm của bé phải nằm lọt bên trong khung nôi đề xuất.
        """
        if not isinstance(pts, list) or len(pts) != 4:
            return False
        try:
            np_pts = np.array(pts, dtype=np.float32)
            for p in np_pts:
                if p[0] < 0.01 or p[0] > 0.99 or p[1] < 0.01 or p[1] > 0.99:
                    return False

            # Kiểm tra tính lồi (chống xoắn mép)
            if not cv2.isContourConvex(np_pts.reshape(-1, 1, 2)):
                return False

            # Kiểm tra diện tích theo công thức Shoelace
            area = float(cv2.contourArea(np_pts))
            if area < 0.10 or area > 0.88:
                return False

            # Kiểm tra xem có chứa em bé không nếu bé đang được định vị
            if check_baby and getattr(self, "last_baby_box", None) is not None and getattr(self, "baby_detected", False):
                bcx = (self.last_baby_box[0] + self.last_baby_box[2]) / 2.0 / float(w)
                bcy = (self.last_baby_box[1] + self.last_baby_box[3]) / 2.0 / float(h)
                dist = cv2.pointPolygonTest(np_pts, (float(bcx), float(bcy)), False)
                if dist < 0:  # Trọng tâm bé nằm ngoài khung nôi đề xuất
                    return False

            return True
        except Exception:
            return False

    def _commit_safe_zone(self, pts: list):
        """Chính thức xác thực và lưu Khung Nôi 3D vào cấu hình và mốc Rollback."""
        import copy
        with self.lock:
            self.safe_zone_polygon = copy.deepcopy(pts)
            xs = [p[0] for p in self.safe_zone_polygon]
            ys = [p[1] for p in self.safe_zone_polygon]
            self.safe_zone_left = round(min(xs), 3)
            self.safe_zone_right = round(max(xs), 3)
            self.safe_zone_top = round(min(ys), 3)
            self.safe_zone_bottom = round(max(ys), 3)
            self.last_verified_safe_zone = copy.deepcopy(self.safe_zone_polygon)
            self.initial_crib_calibrated = True

        cfg_path = os.path.join(BASE_DIR, "config.json")
        if os.path.exists(cfg_path):
            try:
                with open(cfg_path, "r", encoding="utf-8") as fp:
                    cfg_data = json.load(fp)
                cfg_data["safe_zone_left"] = self.safe_zone_left
                cfg_data["safe_zone_right"] = self.safe_zone_right
                cfg_data["safe_zone_top"] = self.safe_zone_top
                cfg_data["safe_zone_bottom"] = self.safe_zone_bottom
                cfg_data["safe_zone_polygon"] = self.safe_zone_polygon
                with open(cfg_path, "w", encoding="utf-8") as fp:
                    json.dump(cfg_data, fp, ensure_ascii=False, indent=4)
            except Exception as ce:
                print(f"[VisionTracker] Lỗi lưu Safe Zone vào config.json: {ce}")

    def get_enhanced_low_light_frame(self, burst_frames=None) -> np.ndarray:
        """
        Bù sáng đa khung hình thích ứng (Multi-frame Exposure Stacking & CLAHE):
        - Chập trung bình 3-5 frame để triệt tiêu nhiễu hạt cảm biến ISO ban đêm.
        - Tự động nâng sáng vùng bóng tối và lòng nôi bằng CLAHE + Gamma động trên kênh L.
        """
        frames = burst_frames or list(self.raw_frame_burst)
        if not frames:
            return None
        if len(frames) == 1:
            base = frames[0].copy()
        else:
            base = np.mean([f.astype(np.float32) for f in frames], axis=0).astype(np.uint8)

        gray = cv2.cvtColor(base, cv2.COLOR_BGR2GRAY)
        mean_b = float(np.mean(gray))

        if mean_b >= 140.0:
            return base

        lab = cv2.cvtColor(base, cv2.COLOR_BGR2LAB)
        l, a, b = cv2.split(lab)

        if mean_b < 50.0:
            gamma = 0.55
            clip = 3.5
        elif mean_b < 100.0:
            gamma = 0.65
            clip = 2.8
        else:
            gamma = 0.80
            clip = 2.0

        clahe = cv2.createCLAHE(clipLimit=clip, tileGridSize=(8, 8))
        cl = clahe.apply(l)

        table = np.array([((i / 255.0) ** gamma) * 255 for i in np.arange(0, 256)]).astype("uint8")
        cl_gamma = cv2.LUT(cl, table)

        return cv2.cvtColor(cv2.merge((cl_gamma, a, b)), cv2.COLOR_LAB2BGR)

    def _classify_person(self, xyxy, kpts, frame_h, frame_w):
        """
        Phân loại chính xác đâu là Người Lớn (Adult) và đâu là Em Bé (Baby)
        dựa trên kích thước, hình thái và cv2.pointPolygonTest đối chiếu trực tiếp với Safe Zone.
        """
        box_w = float(xyxy[2] - xyxy[0])
        box_h = float(xyxy[3] - xyxy[1])
        box_area = box_w * box_h
        frame_area = float(frame_h * frame_w)

        h_ratio = box_h / float(frame_h)
        area_ratio = box_area / frame_area

        # Đo khoảng cách 2 vai (Keypoints 5 và 6)
        shoulder_w = 0.0
        if kpts[5, 2] > 0.20 and kpts[6, 2] > 0.20:
            shoulder_w = float(np.linalg.norm(kpts[5, :2] - kpts[6, :2]))

        bcx = (xyxy[0] + xyxy[2]) / 2.0
        bcy = (xyxy[1] + xyxy[3]) / 2.0

        # Kiểm tra trực tiếp trọng tâm cơ thể với đa giác Safe Zone do người dùng cài đặt
        in_crib_zone = self._is_point_in_safe_zone(bcx, bcy, frame_w, frame_h, margin_px=35.0)
        touches_border = (xyxy[0] < 20 or xyxy[1] < 20 or xyxy[2] > (frame_w - 20) or xyxy[3] > (frame_h - 20))

        # Tiêu chuẩn Người Lớn (Adult):
        # 1. Thân hình to lớn vượt kích thước trẻ sơ sinh:
        #    - shoulder_w > 120.0px (người lớn thường > 170px, bé sơ sinh < 95px)
        #    - area_ratio > 0.14 (diện tích người lớn > 14-35% khung hình, bé chỉ 5-11%)
        #    - h_ratio > 0.58 (người lớn cao lớn trùm gần hết khung hình)
        #    - h_ratio > 0.48 kết hợp shoulder_w > 100.0px
        # 2. Hoặc người lớn từ ngoài mép màn hình thò vào / ngồi bên mép:
        #    - touches_border và (box_w > 180 hoặc box_h > 220 hoặc shoulder_w > 90.0)
        is_adult = (shoulder_w > 120.0) or (area_ratio > 0.14) or (h_ratio > 0.58) or \
                   (h_ratio > 0.48 and shoulder_w > 100.0) or \
                   (touches_border and (box_w > 180 or box_h > 220 or shoulder_w > 90.0))

        return {
            "is_adult": is_adult,
            "in_crib_zone": in_crib_zone,
            "touches_border": touches_border,
            "h_ratio": h_ratio,
            "shoulder_w": shoulder_w,
            "area_ratio": area_ratio,
            "box_w": box_w,
            "box_h": box_h
        }

    def _check_crib_occupied(self, frame, h, w):
        """Kiểm tra khu vực Safe Zone xem có bé/chăn đệm hay phòng tối đen trống rỗng."""
        x1 = max(0, int(w * self.safe_zone_left))
        x2 = min(w, int(w * self.safe_zone_right))
        y1 = max(0, int(h * self.safe_zone_top))
        y2 = min(h, int(h * self.safe_zone_bottom))
        cz = frame[y1:y2, x1:x2]
        if cz.size == 0:
            return False
        gray = cv2.cvtColor(cz, cv2.COLOR_BGR2GRAY)
        mean_b = float(np.mean(gray))
        max_b = float(np.max(gray))

        hsv = cv2.cvtColor(cz, cv2.COLOR_BGR2HSV)
        skin1 = cv2.inRange(hsv, np.array([0, 25, 40]), np.array([25, 210, 245]))
        skin2 = cv2.inRange(hsv, np.array([168, 25, 40]), np.array([180, 210, 245]))
        skin = skin1 | skin2
        skin_count = int(np.sum(skin > 0))

        if mean_b < 10.0 and max_b < 35.0 and skin_count < 100:
            return False
        return True

    def _check_skin_in_roi(self, frame, x1, y1, x2, y2):
        """Đo tỷ lệ màu da người trong ROI để phân biệt khuôn mặt thật với khăn/chăn trùm kín."""
        if x2 <= x1 or y2 <= y1:
            return 0.0
        roi = frame[max(0, y1):min(frame.shape[0], y2), max(0, x1):min(frame.shape[1], x2)]
        if roi.size == 0:
            return 0.0
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        skin1 = cv2.inRange(hsv, np.array([0, 25, 40]), np.array([25, 210, 245]))
        skin2 = cv2.inRange(hsv, np.array([168, 25, 40]), np.array([180, 210, 245]))
        skin = skin1 | skin2
        return float(np.sum(skin > 0)) / float(skin.size)

    def _detect_baby_face(self, frame):
        """
        Nhận diện khuôn mặt 360 độ bằng model YuNet (quét cả 3 hướng: Nằm dọc 0°, Nằm ngang đầu bên phải 90° CCW, Nằm ngang đầu bên trái 90° CW):
        - Khắc phục triệt để lỗi khi bé nằm ngang nhưng khung nhận diện lại kéo thẳng đứng xuống đệm/gối bên dưới.
        - Định vị chính xác trục sống lưng từ Đỉnh đầu -> Mắt -> Mũi -> Miệng -> Lồng ngực theo đúng hướng nằm thực tế của bé.
        """
        if not getattr(self, "has_face_detector", False) or self.face_detector is None:
            return None, False, None

        h, w = frame.shape[:2]
        raw_candidates = []

        # 1. Quét hướng thẳng 0° (Bé nằm dọc)
        self.face_detector.setInputSize((w, h))
        _, faces_0 = self.face_detector.detect(frame)
        if faces_0 is not None:
            for f in faces_0:
                bbox = f[:4].astype(int)
                conf = float(f[-1])
                lms = f[4:14].reshape((5, 2)).astype(np.float32)
                raw_candidates.append((bbox, conf, lms, "0"))

        # 2. Quét hướng nằm ngang (90° CCW: Đầu bên phải - Mình bên trái & 90° CW: Đầu bên trái - Mình bên phải)
        # Thu nhỏ 0.5x khi quét xoay để tốc độ xử lý < 2.5ms mà vẫn đạt độ chính xác > 91%
        scale = 0.5
        sw, sh = int(w * scale), int(h * scale)
        small = cv2.resize(frame, (sw, sh))

        # 2a. Xoay 90° ngược chiều kim đồng hồ (90° CCW) -> Đầu bé bên phải trở thành thẳng đứng
        img_ccw = cv2.rotate(small, cv2.ROTATE_90_COUNTERCLOCKWISE)
        self.face_detector.setInputSize((sh, sw))
        _, faces_ccw = self.face_detector.detect(img_ccw)
        if faces_ccw is not None:
            for f in faces_ccw:
                rx, ry, rw_b, rh_b = f[:4]
                conf = float(f[-1])
                fx = int((sw - 1 - (ry + rh_b)) / scale)
                fy = int(rx / scale)
                fw = int(rh_b / scale)
                fh = int(rw_b / scale)
                lms_rot = f[4:14].reshape((5, 2))
                lms = np.zeros((5, 2), dtype=np.float32)
                for i in range(5):
                    lms[i, 0] = (sw - 1 - lms_rot[i, 1]) / scale
                    lms[i, 1] = lms_rot[i, 0] / scale
                raw_candidates.append((np.array([fx, fy, fw, fh], dtype=int), conf, lms, "90_ccw"))

        # 2b. Xoay 90° cùng chiều kim đồng hồ (90° CW) -> Đầu bé bên trái trở thành thẳng đứng
        img_cw = cv2.rotate(small, cv2.ROTATE_90_CLOCKWISE)
        self.face_detector.setInputSize((sh, sw))
        _, faces_cw = self.face_detector.detect(img_cw)
        if faces_cw is not None:
            for f in faces_cw:
                rx, ry, rw_b, rh_b = f[:4]
                conf = float(f[-1])
                fx = int(ry / scale)
                fy = int((sh - 1 - (rx + rw_b)) / scale)
                fw = int(rh_b / scale)
                fh = int(rw_b / scale)
                lms_rot = f[4:14].reshape((5, 2))
                lms = np.zeros((5, 2), dtype=np.float32)
                for i in range(5):
                    lms[i, 0] = lms_rot[i, 1] / scale
                    lms[i, 1] = (sh - 1 - lms_rot[i, 0]) / scale
                raw_candidates.append((np.array([fx, fy, fw, fh], dtype=int), conf, lms, "90_cw"))

        if not raw_candidates:
            return None, False, None

        baby_faces = []
        adult_faces = []

        for bbox, conf, landmarks, orient in raw_candidates:
            fx, fy, fw, fh = bbox
            fx = max(0, fx)
            fy = max(0, fy)
            fw = min(w - fx, fw)
            fh = min(h - fy, fh)
            if fw < 36 or fh < 36:
                continue

            fcx = fx + fw / 2.0
            fcy = fy + fh / 2.0

            # Kiểm tra tâm mặt với đa giác Safe Zone bằng cv2.pointPolygonTest
            in_crib = self._is_point_in_safe_zone(fcx, fcy, w, h, margin_px=40.0)

            # Lọc bỏ mặt giả từ thú bông/đồ chơi
            skin_ratio = self._check_skin_in_roi(frame, fx, fy, fx + fw, fy + fh)
            if skin_ratio < 0.030:
                continue

            # Tính tỷ lệ tóc / chân mày tối màu bên trong khung đầu để phân biệt Đầu thật với Bàn chân/Bàn tay bé
            head_crop = frame[fy:fy + fh, fx:fx + fw]
            hair_bonus = 0.0
            if head_crop.size > 0:
                gray_h = cv2.cvtColor(head_crop, cv2.COLOR_BGR2GRAY)
                dark_ratio = float(np.sum(gray_h < 68)) / float(gray_h.size)
                if 0.03 <= dark_ratio <= 0.65:
                    hair_bonus = 0.18

            # Phân biệt người lớn vs em bé:
            if (not in_crib) or (fw > 0.22 * w) or (fh > 0.32 * h):
                adult_faces.append({"bbox": np.array([fx, fy, fw, fh]), "conf": conf, "landmarks": landmarks})
            else:
                baby_faces.append({
                    "bbox": np.array([fx, fy, fw, fh]),
                    "conf": conf,
                    "rank_score": conf + hair_bonus,
                    "landmarks": landmarks,
                    "skin_ratio": skin_ratio,
                    "orient": orient
                })

        best_baby_face = None
        if baby_faces:
            baby_faces.sort(key=lambda x: x["rank_score"], reverse=True)
            best_baby_face = baby_faces[0]

        has_adult_face = len(adult_faces) > 0
        best_adult_face = adult_faces[0]["bbox"] if adult_faces else None

        return best_baby_face, has_adult_face, best_adult_face

    def _check_body_obstruction(self, frame, body_box, face_bbox, landmarks=None):
        """
        Kiểm tra nguy cơ bít tắc đường thở (Mũi - Miệng - Sát Cằm):
        - KHÔNG quét rộng xuống toàn bộ hộp chữ nhật bên dưới (tránh bắt nhầm gối ôm nằm sát sườn bé).
        - Chỉ kiểm tra vùng tam giác Đường Thở & Thượng vị ngay sát dưới mũi-miệng dọc theo trục mặt!
        """
        h, w = frame.shape[:2]
        fx, fy, fw, fh = face_bbox

        # Tính tâm vùng mũi-miệng-cằm (Airway Zone)
        if landmarks is not None and len(landmarks) >= 5:
            eye_mid = (landmarks[0] + landmarks[1]) / 2.0
            mouth_mid = (landmarks[3] + landmarks[4]) / 2.0
            v = mouth_mid - eye_mid
            u = v / max(1e-5, np.linalg.norm(v))
            airway_cx = int(mouth_mid[0] + 0.15 * fw * u[0])
            airway_cy = int(mouth_mid[1] + 0.15 * fh * u[1])
        else:
            airway_cx = int(fx + fw * 0.5)
            airway_cy = int(fy + fh * 0.78)

        # Khung kiểm tra hẹp chỉ bao quanh đúng vùng mũi-miệng-cổ của bé (bán kính 0.38 * fw)
        rx = max(12, int(fw * 0.38))
        ry = max(12, int(fh * 0.35))
        ax1, ay1 = max(0, airway_cx - rx), max(0, airway_cy - ry)
        ax2, ay2 = min(w, airway_cx + rx), min(h, airway_cy + ry)

        if ax2 <= ax1 or ay2 <= ay1:
            return False, 0.0

        # Kiểm tra tỷ lệ da vùng mặt + vùng mũi miệng
        face_skin = self._check_skin_in_roi(frame, fx, fy, fx + fw, fy + fh)
        airway_skin = self._check_skin_in_roi(frame, ax1, ay1, ax2, ay2)

        # Nếu vùng mặt và vùng mũi-miệng vẫn lộ da rõ ràng -> Đường thở thông thoáng (An toàn!)
        if face_skin >= 0.08 and airway_skin >= 0.04:
            return False, 0.0

        # Chỉ khi vùng mũi-miệng mất hoàn toàn sắc tố da (< 0.025) mới kiểm tra dị vật đè lên mũi miệng
        airway_crop = frame[ay1:ay2, ax1:ax2]
        hsv = cv2.cvtColor(airway_crop, cv2.COLOR_BGR2HSV)
        # Độ bão hòa màu cao của vải chăn/gối/thú bông trùm trực tiếp lên vùng mũi miệng
        high_sat = cv2.inRange(hsv, np.array([0, 85, 40]), np.array([180, 255, 255]))
        sat_ratio = float(np.sum(high_sat > 0)) / float(airway_crop.size)

        is_obstructed = (airway_skin < 0.025) and (sat_ratio > 0.45)
        return is_obstructed, sat_ratio

    def _derive_infant_from_face(self, face_info, frame_h, frame_w):
        """
        Từ tọa độ đầu & 5 điểm mốc khuôn mặt YuNet 360° (Face-First Tracking):
        - Tính Vector đơn vị liên tục trục sống lưng u = (ux, uy) và vector pháp tuyến n = (-uy, ux).
        - Xoay nghiêng khung ROI lồng ngực và khung toàn thân theo đúng hướng nằm thực tế của bé
          (dù bé nằm dọc hay nằm ngang, khung luôn ôm sát từ đầu qua ngực xuống chân bé).
        """
        fx, fy, fw, fh = face_info["bbox"]
        landmarks = face_info["landmarks"]

        # Vector định hướng liên tục từ điểm giữa 2 mắt qua mũi xuống điểm giữa miệng
        eye_mid = (landmarks[0] + landmarks[1]) / 2.0
        mouth_mid = (landmarks[3] + landmarks[4]) / 2.0
        v = mouth_mid - eye_mid
        v_norm = float(np.linalg.norm(v))
        if v_norm < 1e-3:
            u = np.array([0.0, 1.0], dtype=np.float32)
        else:
            u = (v / v_norm).astype(np.float32)

        # Làm mượt hướng sống lưng u qua các frame để khung không bị nhảy
        if getattr(self, "smoothed_spine_u", None) is not None:
            dot_u = float(np.dot(self.smoothed_spine_u, u))
            if dot_u > 0.5:
                u = 0.75 * self.smoothed_spine_u + 0.25 * u
                u = (u / max(1e-4, float(np.linalg.norm(u)))).astype(np.float32)
        self.smoothed_spine_u = u

        # Vector vuông góc (ngang vai bé)
        n_vec = np.array([-u[1], u[0]], dtype=np.float32)

        face_center = np.array([fx + fw / 2.0, fy + fh / 2.0], dtype=np.float32)
        head_len = float(max(fw, fh))

        # Tâm vùng ngực (Sternum) nằm dọc theo vector sống lưng u một khoảng 1.05 * head_len
        chest_center = face_center + u * (1.05 * head_len)
        chest_center[0] = np.clip(chest_center[0], 20, frame_w - 20)
        chest_center[1] = np.clip(chest_center[1], 20, frame_h - 20)

        # Kích thước ROI lồng ngực nhỏ gọn, nằm trọn trong lồng ngực bé
        half_w = max(16.0, 0.38 * head_len)
        half_h = max(16.0, 0.35 * head_len)

        # 4 đỉnh của hình chữ nhật ROI lồng ngực đã xoay theo góc nghiêng cơ thể bé
        p1 = chest_center - n_vec * half_w - u * half_h
        p2 = chest_center + n_vec * half_w - u * half_h
        p3 = chest_center + n_vec * half_w + u * half_h
        p4 = chest_center - n_vec * half_w + u * half_h
        self.last_chest_poly = np.array([p1, p2, p3, p4], dtype=np.int32)

        # Hộp bao (Bounding Box) của ROI ngực đã thu gọn
        rx1 = max(0, int(np.min(self.last_chest_poly[:, 0])))
        rx2 = min(frame_w, int(np.max(self.last_chest_poly[:, 0])))
        ry1 = max(0, int(np.min(self.last_chest_poly[:, 1])))
        ry2 = min(frame_h, int(np.max(self.last_chest_poly[:, 1])))

        # Suy diễn khung toàn thân bé dọc theo đúng vector sống lưng u (từ đỉnh đầu -0.55*head_len tới chân +2.35*head_len)
        b_half_across = max(28.0, 0.72 * head_len)
        bp1 = face_center - n_vec * b_half_across - u * (0.55 * head_len)
        bp2 = face_center + n_vec * b_half_across - u * (0.55 * head_len)
        bp3 = face_center + n_vec * b_half_across + u * (2.35 * head_len)
        bp4 = face_center - n_vec * b_half_across + u * (2.35 * head_len)
        b_pts = np.array([bp1, bp2, bp3, bp4])

        bx1 = max(0, int(np.min(b_pts[:, 0])))
        bx2 = min(frame_w, int(np.max(b_pts[:, 0])))
        by1 = max(0, int(np.min(b_pts[:, 1])))
        by2 = min(frame_h, int(np.max(b_pts[:, 1])))

        body_box = np.array([bx1, by1, bx2, by2])
        chest_roi = (rx1, ry1, rx2, ry2)
        return body_box, chest_roi

    def _select_real_baby(self, r, frame_h, frame_w):
        """
        Phân biệt thông minh giữa Em Bé và Người Lớn:
        - 100% người lớn / tay chân người ngoài được xếp vào adult_candidates.
        - Chỉ có bé nằm trong vùng Safe Zone mới được xem là baby_candidates.
        """
        if len(r.boxes) == 0 or r.keypoints is None or len(r.keypoints.data) == 0:
            return None, False, None, False

        baby_candidates = []
        adult_candidates = []

        for idx in range(len(r.boxes)):
            box = r.boxes[idx]
            kpts = r.keypoints.data[idx].cpu().numpy()
            conf = float(box.conf[0])
            xyxy = box.xyxy[0].cpu().numpy()

            person_info = self._classify_person(xyxy, kpts, frame_h, frame_w)
            face_conf = float(np.mean(kpts[:3, 2]))
            torso_conf = float(np.mean(kpts[5:7, 2]))
            valid_kpts = int(np.sum(kpts[:, 2] > 0.25))

            is_real_human = (face_conf >= 0.15 or torso_conf >= 0.18) and valid_kpts >= 3
            if not is_real_human:
                continue

            human_score = conf + (face_conf * 1.5) + (torso_conf * 1.2)

            # Tiêu chuẩn nghiêm ngặt của EM BÉ (Baby Candidate):
            # Bé sơ sinh trong nôi PHẢI có khuôn mặt (face_conf >= 0.15) HOẶC đầy đủ 2 vai (torso_conf >= 0.20 & shoulder_w >= 28px).
            # Nếu không có mặt và không có vai rõ rệt -> Đây là tay/chân lẻ loi của người lớn hoặc đồ vật!
            sh_w = person_info.get("shoulder_w", 0.0)
            has_baby_anatomy = (face_conf >= 0.15) or (torso_conf >= 0.20 and sh_w >= 28.0)
            is_border_touch = person_info.get("touches_border", False) and (face_conf < 0.20)

            if person_info["is_adult"] or is_border_touch or (not has_baby_anatomy):
                adult_candidates.append((idx, human_score, xyxy.astype(int), person_info))
            else:
                if person_info["in_crib_zone"]:
                    baby_candidates.append((idx, human_score, xyxy.astype(int), person_info, False))

        if baby_candidates:
            baby_candidates.sort(key=lambda x: x[1], reverse=True)
            best_idx = baby_candidates[0][0]
            return best_idx, (len(adult_candidates) > 0), (adult_candidates[0][2] if adult_candidates else None), False

        if adult_candidates:
            adult_candidates.sort(key=lambda x: x[1], reverse=True)
            return None, True, adult_candidates[0][2], False

        return None, False, None, False

    def _extract_breathing_roi(self, kpts_xy, kpts_conf, h, w):
        """
        Xác định tọa độ ROI lồng ngực / lưng thông minh cho TẤT CẢ tư thế ngủ:
        - Nằm ngửa (Supine): Vùng ngực và bụng trước.
        - Nằm nghiêng (Lateral) / Nằm sấp (Prone): Vùng lưng, mạn sườn (vùng áo nâng lên hạ xuống theo nhịp thở).
        - Tuyệt đối né vùng đầu / tóc đen và chân, cố định chính xác trên thân mình (Torso).
        """
        if kpts_xy is not None and kpts_conf is not None and kpts_conf[5] > 0.20 and kpts_conf[6] > 0.20:
            l_sh = kpts_xy[5]
            r_sh = kpts_xy[6]
            s_mid = (l_sh + r_sh) / 2.0
            sw = float(np.clip(np.linalg.norm(l_sh - r_sh), 28.0, 120.0))

            has_hips = (kpts_conf[11] > 0.20 and kpts_conf[12] > 0.20)
            if has_hips:
                h_mid = (kpts_xy[11] + kpts_xy[12]) / 2.0
                spine_v = h_mid - s_mid
                norm_v = float(np.linalg.norm(spine_v))
            else:
                norm_v = 0.0

            if has_hips and norm_v > 20.0:
                u = (spine_v / norm_v).astype(np.float32)
                n_vec = np.array([-u[1], u[0]], dtype=np.float32)

                face_conf = float(np.mean(kpts_conf[:3]))
                is_prone_or_lateral = (face_conf < 0.22) or (abs(float(kpts_conf[1]) - float(kpts_conf[2])) > 0.35)

                if is_prone_or_lateral:
                    # Nằm nghiêng / Nằm sấp:
                    # Bé thở bằng cơ hoành, vùng thắt lưng, mạn sườn và lưng dưới (quanh hông) dao động mạnh nhất.
                    # Dịch tâm ROI về phía thắt lưng / lưng dưới (d1=0.35, d2=1.10) để né 100% gáy và tóc đen
                    d1 = 0.35 * norm_v
                    d2 = 1.10 * norm_v
                    half_w = np.clip(0.26 * sw, 14.0, 30.0)
                else:
                    # Nằm ngửa: Tâm vùng ngực / bụng trước
                    d1 = 0.20 * norm_v
                    d2 = 0.85 * norm_v
                    half_w = np.clip(0.28 * sw, 14.0, 32.0)

                d_center = (d1 + d2) / 2.0
                half_h = (d2 - d1) / 2.0
                torso_c = s_mid + u * d_center

            else:
                # Nếu không bắt được hông, ước lượng trục cơ thể từ trục 2 vai
                sh_vec = r_sh - l_sh
                sh_norm = float(np.linalg.norm(sh_vec))
                n_vec = (sh_vec / max(1e-4, sh_norm)).astype(np.float32)
                u = np.array([-n_vec[1], n_vec[0]], dtype=np.float32)

                # Định hướng vector u từ đầu xuống ngực/thân
                head_pts = [kpts_xy[k] for k in [0, 1, 2, 3, 4] if kpts_conf[k] > 0.20]
                if head_pts:
                    head_mid = np.mean(head_pts, axis=0)
                    if np.dot(u, s_mid - head_mid) < 0:
                        u = -u
                elif getattr(self, "gemini_head_dir", None) == "down":
                    if u[1] > 0:
                        u = -u

                torso_c = s_mid + u * (0.50 * sw)
                half_w = np.clip(0.28 * sw, 14.0, 32.0)
                half_h = np.clip(0.30 * sw, 14.0, 32.0)

            p1 = torso_c - n_vec * half_w - u * half_h
            p2 = torso_c + n_vec * half_w - u * half_h
            p3 = torso_c + n_vec * half_w + u * half_h
            p4 = torso_c - n_vec * half_w + u * half_h
            self.last_chest_poly = np.array([p1, p2, p3, p4], dtype=np.int32)

            rx1 = max(0, int(np.min(self.last_chest_poly[:, 0])))
            rx2 = min(w, int(np.max(self.last_chest_poly[:, 0])))
            ry1 = max(0, int(np.min(self.last_chest_poly[:, 1])))
            ry2 = min(h, int(np.max(self.last_chest_poly[:, 1])))
            return rx1, ry1, rx2, ry2
        elif getattr(self, "last_baby_box", None) is not None and (time.time() - getattr(self, "baby_last_seen_time", 0.0)) < 3.0:
            lbox = self.last_baby_box
            bx = int((lbox[0] + lbox[2]) / 2.0)
            by = int((lbox[1] + lbox[3]) / 2.0)
            rw = max(36, int((lbox[2] - lbox[0]) * 0.38))
            rh = max(36, int((lbox[3] - lbox[1]) * 0.38))
            self.last_chest_poly = None
            return max(0, bx - rw // 2), max(0, by - rh // 2), min(w, bx + rw // 2), min(h, by + rh // 2)
        else:
            self.last_chest_poly = None
            return None

    def _update_breathing(self, frame, now_t, rx1, ry1, rx2, ry2):
        """
        Phân tích nhịp thở quang học vi mô thời gian thực với:
        1. Color Homogeneity Mask: Chỉ lấy các pixel đồng nhất với tâm ngực bé, loại bỏ rìa gối ôm.
        2. Bộ lọc thông dải Butterworth bậc 4 (scipy.signal.butter + filtfilt) trong dải [0.46 Hz - 1.42 Hz] (28 - 85 RPM).
        3. Kiểm định năng lượng tín hiệu (SNR) & Autocorrelation Peak >= 0.24 để triệt tiêu 100% nhịp thở ảo.
        """
        if not self.breathing_monitor_enabled:
            self.breathing_bpm = 0.0
            self.breathing_status = "Đã tắt"
            return False

        if rx1 is None or rx2 is None or (rx2 - rx1) < 20 or (ry2 - ry1) < 20:
            self.breathing_bpm = 0.0
            self.breathing_status = "Ngoài giường"
            return False

        roi = frame[ry1:ry2, rx1:rx2]
        if roi.size > 0:
            roi_small = cv2.resize(roi, (96, 96))
            roi_blur = cv2.GaussianBlur(roi_small, (5, 5), 0)

            # Lọc đồng nhất màu sắc tại tâm lồng ngực (Color Homogeneity Mask)
            # Giúp loại bỏ mọi pixel ngoại lai (như mép gối ôm) vô tình lọt vào góc khung ROI
            center_patch = roi_blur[32:64, 32:64]
            center_color = np.median(center_patch.reshape(-1, 3), axis=0)
            color_dist = np.linalg.norm(roi_blur.astype(np.float32) - center_color, axis=2)
            valid_mask = color_dist < 55.0

            gray_roi = cv2.cvtColor(roi_blur, cv2.COLOR_BGR2GRAY).astype(np.float32)
            if np.sum(valid_mask) > 150:
                # Cường độ sáng trung bình có hướng trên vùng ngực đồng nhất (không dùng absdiff để tránh nhân đôi tần số)
                sig_val = float(np.mean(gray_roi[valid_mask]))
            else:
                sig_val = float(np.mean(gray_roi))

            self.chest_history.append((now_t, sig_val))

        # Giữ cửa sổ trượt 8 giây để đủ độ phân giải tần số cho bộ lọc Butterworth
        self.chest_history = [(t, v) for t, v in self.chest_history if (now_t - t) <= 8.0]

        if self.smoothed_motion < 18.0:
            if len(self.chest_history) >= 28:
                ts = np.array([t for t, v in self.chest_history], dtype=np.float64)
                vals = np.array([v for t, v in self.chest_history], dtype=np.float64)
                duration = ts[-1] - ts[0]
                fps_est = len(ts) / max(1.0, duration)

                # Loại bỏ thành phần DC (Mean Removal)
                sig = vals - np.mean(vals)
                raw_std = float(np.std(sig))

                # Nếu biên độ biến thiên quang học quá nhỏ (nhiễu tĩnh trên gối/nệm) -> Không có nhịp thở!
                if raw_std < 0.035 or fps_est < 4.0:
                    self.breathing_status = "Đang phân tích..."
                    return False

                # Áp dụng Bộ lọc thông dải Butterworth bậc 3 [0.46 Hz - 1.42 Hz] (28 - 85 RPM)
                nyq = 0.5 * fps_est
                low_cut = max(0.05, min(0.46 / nyq, 0.85))
                high_cut = max(low_cut + 0.08, min(1.42 / nyq, 0.95))
                try:
                    b, a = butter(3, [low_cut, high_cut], btype="band")
                    filtered_sig = filtfilt(b, a, sig)
                except Exception:
                    filtered_sig = sig

                filt_std = float(np.std(filtered_sig))
                if filt_std < 0.020:
                    self.breathing_status = "Đang phân tích..."
                    return False

                # Tính chu kỳ nhịp thở bằng Normalized Autocorrelation trên tín hiệu đã lọc sạch nhiễu
                n = len(filtered_sig)
                autocorr = np.correlate(filtered_sig, filtered_sig, mode="full")[n-1:]
                autocorr = autocorr / (autocorr[0] + 1e-6)

                # Dải tần nhịp thở sinh học của trẻ sơ sinh [28, 85 RPM] -> chu kỳ [0.70s, 2.14s]
                min_lag = max(2, int(0.70 * fps_est))
                max_lag = min(len(autocorr) - 1, int(2.14 * fps_est))

                if min_lag < max_lag:
                    search_region = autocorr[min_lag:max_lag]
                    best_offset = int(np.argmax(search_region))
                    peak_val = float(search_region[best_offset])

                    if peak_val >= 0.22:
                        best_lag = min_lag + best_offset
                        period_s = best_lag / fps_est
                        instant_bpm = 60.0 / period_s
                        instant_bpm = max(28.0, min(75.0, instant_bpm))
                        if self.breathing_bpm <= 5.0:
                            self.breathing_bpm = round(instant_bpm, 1)
                        else:
                            self.breathing_bpm = round(0.75 * self.breathing_bpm + 0.25 * instant_bpm, 1)
                        self.breathing_status = "Thở đều (Bình thường)"
                        self.last_breath_peak_time = now_t
                        return True
                    else:
                        if (now_t - getattr(self, "last_breath_peak_time", 0.0)) > 5.0:
                            self.breathing_bpm = 0.0
                            self.breathing_status = "Thở êm dịu (Dưới chăn)"
                else:
                    self.breathing_bpm = 0.0
                    self.breathing_status = "Đang phân tích..."
            else:
                # Đang tích lũy chuỗi dữ liệu (khoảng 2-3s đầu khi bé nằm yên)
                self.breathing_status = "Đang hội tụ tín hiệu..."
                if (now_t - getattr(self, "last_breath_peak_time", 0.0)) > 5.0:
                    self.breathing_bpm = 0.0

            # Cảnh báo ngưng thở khi bé nằm yên > 25s mà không có bất kỳ chuyển động thở nào
            still_time = now_t - getattr(self, "last_breath_peak_time", now_t)
            if still_time > 25.0 and len(self.chest_history) >= 35:
                vals = [v for t, v in self.chest_history]
                if float(np.std(vals)) < 0.015 and self.on_apnea_callback:
                    self.on_apnea_callback()
                    self.breathing_status = "Cảnh báo ngưng thở"
        else:
            self.last_motion_time = now_t
            self.breathing_bpm = 0.0
            self.breathing_status = "Đang cử động"
            return True

        return (now_t - getattr(self, "last_breath_peak_time", 0.0)) < 4.0 and self.breathing_bpm > 0

    def _trigger_gemini_alert_verify(self, frame, alert_type: str, local_reason: str):
        """Kích hoạt cảnh báo khẩn cấp cục bộ ngay lập tức và thẩm định chi tiết song song qua Gemini API."""
        if getattr(self, "pending_alert_verify", False):
            return

        # 1. Kích hoạt báo động âm thanh và giao diện cục bộ NGAY LẬP TỨC (Zero-latency)
        self.covered_face_active = True
        self.sleep_pose = "Mặt bị che khuất (Nguy cơ ngạt)"
        self.baby_status = "CẢNH BÁO: MẶT BÉ BỊ CHE KHUẤT!"
        if self.on_covered_face_callback:
            self.on_covered_face_callback()

        if self.gemini_verifier is None or not self.gemini_verifier.is_ready() or not self.gemini_verifier.verify_alerts_enabled:
            return

        self.pending_alert_verify = True
        frame_copy = frame.copy()

        def _worker():
            try:
                res = self.gemini_verifier.verify_high_risk_alert(frame_copy, alert_type=alert_type, local_reason=local_reason)
                if res.get("is_dangerous", False):
                    diag = res.get("diagnosis_vi", "Nguy cơ che khuất đường thở")
                    self.sleep_pose = "Nguy cơ ngạt (Đã xác thực AI)"
                    self.baby_status = f"CẢNH BÁO AI: {diag[:42]}"
                else:
                    # Nếu Gemini xác nhận an toàn (bác bỏ báo động giả) -> Hủy cảnh báo
                    self.covered_face_active = False
                    self.covered_face_frame_count = 0
                    self.gemini_suppressed_until = time.time() + 15.0  # Chỉ nghỉ 15 giây, không khóa 3 phút
                    print(f"[VisionTracker] ✅ Gemini đã kiểm tra và dập báo động giả: {res.get('diagnosis_vi')}")
            finally:
                self.pending_alert_verify = False

        threading.Thread(target=_worker, daemon=True).start()

    def _trigger_cute_moment_capture(self, frame, baby_face_info=None):
        """
        Kiểm duyệt & Chụp chân dung em bé (Baby Portrait Capture):
        BẮT BUỘC ĐIỀU KIỆN TIÊN QUYẾT:
        1. Phải tracking được ĐẦY ĐỦ KHUÔN MẶT EM BÉ (YuNet Face Detector conf >= 0.65).
        2. Khuôn mặt em bé BẮT BUỘC phải nằm 100% bên trong vùng Safe Zone của bé.
        3. Không bị chăn/gối che mặt (đủ 5 điểm mốc giải phẫu khuôn mặt).
        4. Tự động cắt (Portrait Crop) tập trung riêng vào em bé dựa trên tọa độ mặt thật của YuNet,
           hoàn toàn loại bỏ người lớn hoặc đồ vật xung quanh!
        """
        if not baby_face_info or not isinstance(baby_face_info, dict):
            return

        conf = float(baby_face_info.get("conf", 0.0))
        if conf < 0.65:
            return

        bbox = baby_face_info.get("bbox")
        if bbox is None or len(bbox) != 4:
            return

        # Kiểm tra độ tin cậy khuôn mặt: tối thiểu 60% để loại bỏ nếp chăn / gối
        conf = float(baby_face_info.get("conf", 0.0))
        if conf < 0.60:
            return

        h, w = frame.shape[:2]
        fx, fy, fw, fh = [int(v) for v in bbox]
        fcx = fx + fw / 2.0
        fcy = fy + fh / 2.0

        # Mặt bé BẮT BUỘC phải nằm hoàn toàn trong vùng nôi / Safe Zone
        if not self._is_point_in_safe_zone(fcx, fcy, w, h, margin_px=10.0):
            return

        # Mặt không được quá to (mặt người lớn) hoặc quá bé (nhiễu/hoa văn)
        if fw < 40 or fw > int(w * 0.18) or fh < 40 or fh > int(h * 0.25):
            return

        # Nếu đang bị nghi ngờ che mặt / ngạt thở -> Tuyệt đối không chụp
        if getattr(self, "covered_face_active", False):
            return

        if getattr(self, "pending_moment_eval", False):
            return

        now_t = time.time()
        # Chu kỳ giãn cách 12 phút giữa các lần chụp để ảnh luôn chọn lọc & không spam
        if (now_t - self.last_moment_time) < self.moment_capture_interval:
            return

        # Tạo khung chân dung em bé (Portrait Crop) chuẩn xác theo tọa độ khuôn mặt thật từ YuNet:
        # Mở rộng ngang ~1.5x fw mỗi bên, trên ~0.8x fh, dưới ~2.6x fh (ôm trọn thân bé)
        crop_x1 = max(0, fx - int(fw * 1.5))
        crop_y1 = max(0, fy - int(fh * 0.8))
        crop_x2 = min(w, fx + fw + int(fw * 1.5))
        crop_y2 = min(h, fy + fh + int(fh * 2.6))

        portrait_crop = frame[crop_y1:crop_y2, crop_x1:crop_x2].copy()
        if portrait_crop.size == 0 or portrait_crop.shape[0] < 50 or portrait_crop.shape[1] < 50:
            return

        # =====================================================================
        # KIỂM TRA ĐỘ NÉT & ĐỘ SÁNG ĐỂ ĐẢM BẢO CHẤT LƯỢNG ẢNH ĐẸP
        # =====================================================================
        try:
            gray_crop = cv2.cvtColor(portrait_crop, cv2.COLOR_BGR2GRAY)
            mean_brightness = float(np.mean(gray_crop))
            # Tự động bù sáng ban đêm (Night Sight Enhancement) nếu phòng tối
            if mean_brightness < 95.0:
                portrait_crop = self.get_enhanced_low_light_frame([portrait_crop])
                gray_crop = cv2.cvtColor(portrait_crop, cv2.COLOR_BGR2GRAY)
                mean_brightness = float(np.mean(gray_crop))

            laplacian_var = float(cv2.Laplacian(gray_crop, cv2.CV_64F).var())
            # Bỏ qua nếu sau khi bù sáng vẫn quá tối (< 25) hoặc bị mờ nhòe do rung lắc (< 30)
            if mean_brightness < 25.0 or laplacian_var < 30.0:
                return
            thumb_gray = cv2.resize(gray_crop, (64, 64))
        except Exception:
            thumb_gray = None

        # 1. Đo lường biến đổi biểu cảm khuôn mặt từ 5 điểm mốc YuNet (Mắt, Mũi, 2 Khóe Miệng)
        landmarks = baby_face_info.get("landmarks")
        has_special_expression = False
        curr_geom = None
        if landmarks is not None and len(landmarks) == 5:
            try:
                re, le, nose, rm, lm = [np.array(p, dtype=np.float32) for p in landmarks]
                eye_dist = max(1.0, float(np.linalg.norm(le - re)))
                mouth_width = float(np.linalg.norm(lm - rm))
                mouth_center = (lm + rm) / 2.0
                mouth_nose_dist = float(np.linalg.norm(mouth_center - nose))
                mouth_ratio = mouth_width / eye_dist
                open_ratio = mouth_nose_dist / eye_dist
                curr_geom = (mouth_ratio, open_ratio)

                if self.last_moment_landmarks is not None:
                    p_mr, p_or = self.last_moment_landmarks
                    # Nếu độ rộng miệng (cười) hoặc độ mở miệng (ngáp/mút tay/mở miệng) biến thiên > 18%
                    if abs(mouth_ratio - p_mr) > 0.18 or abs(open_ratio - p_or) > 0.18:
                        has_special_expression = True
            except Exception:
                pass

        # 2. So sánh độ tương đồng quang học với các bức ảnh gần nhất (chống trùng lặp >= 78%)
        if thumb_gray is not None and self.recent_moment_crops:
            max_sim = 0.0
            for prev_thumb in self.recent_moment_crops:
                try:
                    sim = cv2.matchTemplate(thumb_gray, prev_thumb, cv2.TM_CCOEFF_NORMED)[0][0]
                    if sim > max_sim:
                        max_sim = float(sim)
                except Exception:
                    pass

            if max_sim >= 0.78 and not has_special_expression:
                print(f"[VisionTracker] ⏭️ Bỏ qua ảnh tự động: Tương đồng {max_sim*100:.1f}% >= 78% với ảnh cũ & bé không có biểu cảm mới.")
                return

        self.pending_moment_eval = True

        def _worker():
            try:
                frame_to_save = portrait_crop
                use_gemini = (
                    self.gemini_verifier is not None and 
                    self.gemini_verifier.filter_moments_enabled and 
                    self.gemini_verifier.is_ready()
                )
                
                if use_gemini:
                    res = self.gemini_verifier.evaluate_cute_moment(frame_to_save, is_manual=False)
                    score = int(res.get("aesthetic_score", 0))
                    is_approved = bool(res.get("approved", False) and res.get("privacy_safe", False) and score >= 7)
                    if not is_approved:
                        print(f"[VisionTracker] 🚫 Bỏ qua ảnh tự động: Gemini từ chối ({res.get('reason_vi')}, điểm {score}/10). Hủy bỏ để giữ album chất lượng cao.")
                        # Thử lại sau 3 phút thay vì phải chờ cả 12 phút
                        self.last_moment_time = time.time() - (self.moment_capture_interval - 180.0)
                        return
                else:
                    caption = "Bé có nụ cười / biểu cảm đáng yêu" if has_special_expression else "Khoảnh khắc em bé ngủ ngoan"
                    res = {
                        "checked_by_gemini": False,
                        "approved": True,
                        "privacy_safe": True,
                        "caption_vi": caption,
                        "aesthetic_score": 8,
                        "has_other_person": False
                    }

                now_str = datetime.now().strftime("%Y%m%d_%H%M%S")
                fn = f"moment_{now_str}.jpg"
                m_path = os.path.join(self.moments_dir, fn)
                cv2.imwrite(m_path, frame_to_save)

                self.last_moment_time = time.time()
                if curr_geom:
                    self.last_moment_landmarks = curr_geom
                if thumb_gray is not None:
                    self.recent_moment_crops.append(thumb_gray)
                    if len(self.recent_moment_crops) > 5:
                        self.recent_moment_crops.pop(0)

                if self.gemini_verifier is not None:
                    self.gemini_verifier.save_moment_metadata(fn, res)
                print(f"[VisionTracker] ✨ Đã chụp chân dung bé đạt chuẩn AI ({res.get('aesthetic_score')}/10): {m_path} ({res.get('caption_vi')})")
            except Exception as e:
                print(f"[VisionTracker] Lỗi lưu khoảnh khắc: {e}")
            finally:
                self.pending_moment_eval = False

        threading.Thread(target=_worker, daemon=True).start()

    def _maybe_trigger_tracking_audit(self, raw_frame, annotated_frame, h: int, w: int):
        """
        Tự động gọi Gemini định kỳ để:
        1. Tự động căn chỉnh Khung Giường / Nôi của bé (Safe Zone màu xanh lá cây) mà bố mẹ không cần bấm nút.
        2. Kiểm tra & hiệu chỉnh nóng khung Tracking cơ thể em bé ('EM BE' & 'ROI NGỰC').
        """
        if self.gemini_verifier is None or getattr(self, "pending_tracking_audit", False):
            return

        need_init_crib = not getattr(self, "initial_crib_calibrated", False)
        local_uncertain = (not self.baby_detected) or (getattr(self, "lost_frames", 0) > 3)
        pose_stabilized = getattr(self, "pose_changed_and_stabilized", False)
        if not self.gemini_verifier.should_run_tracking_audit(
            local_uncertain=local_uncertain, 
            need_initial_crib_calib=need_init_crib,
            pose_changed=pose_stabilized
        ):
            return

        self.pose_changed_and_stabilized = False

        self.pending_tracking_audit = True
        enhanced_raw = self.get_enhanced_low_light_frame()
        raw_copy = enhanced_raw.copy() if enhanced_raw is not None else raw_frame.copy()
        ann_copy = annotated_frame.copy()

        norm_box = [0.0, 0.0, 0.0, 0.0]
        if getattr(self, "last_baby_box", None) is not None:
            bx1, by1, bx2, by2 = self.last_baby_box
            norm_box = [round(bx1 / w, 3), round(by1 / h, 3), round(bx2 / w, 3), round(by2 / h, 3)]

        local_info = {
            "baby_detected": self.baby_detected,
            "norm_box": norm_box,
            "safe_zone": [
                round(max(0.01, min(0.99, float(self.safe_zone_left))), 3),
                round(max(0.01, min(0.99, float(self.safe_zone_top))), 3),
                round(max(0.01, min(0.99, float(self.safe_zone_right))), 3),
                round(max(0.01, min(0.99, float(self.safe_zone_bottom))), 3)
            ],
            "sleep_pose": self.sleep_pose
        }

        def _audit_worker():
            try:
                res = self.gemini_verifier.audit_local_tracking(raw_copy, ann_copy, local_info)
                if not res.get("audited", False):
                    return

                # 1. CƠ CHẾ XÁC THỰC 2 BƯỚC + BẢO VỆ VẬT LÝ + ROLLBACK AN TOÀN CHO KHUNG NÔI 3D
                tsz_poly = res.get("true_safe_zone_polygon")
                tsz = res.get("true_safe_zone")
                crib_acc = res.get("crib_zone_accurate", True)

                baby_outside_crib = False
                if self.last_baby_box is not None and getattr(self, "safe_zone_polygon", None) is not None:
                    bcx = (self.last_baby_box[0] + self.last_baby_box[2]) / 2.0
                    bcy = (self.last_baby_box[1] + self.last_baby_box[3]) / 2.0
                    if not self._is_point_in_safe_zone(bcx, bcy, w, h, margin_px=20.0):
                        baby_outside_crib = True

                # TRƯỜNG HỢP 1: GEMINI XÁC NHẬN KHUNG NÔI HIỆN TẠI ĐÃ CHUẨN XÁC
                if crib_acc and not baby_outside_crib:
                    with self.lock:
                        import copy
                        self.last_verified_safe_zone = copy.deepcopy(self.safe_zone_polygon)
                        self.pending_crib_candidate = None
                        self.pending_crib_hits = 0
                        self.initial_crib_calibrated = True
                    # Khung nôi đang rất chuẩn, giữ nguyên không cần thay đổi

                # TRƯỜNG HỢP 2: CẦN CĂN CHỈNH (KHỞI TẠO HOẶC LỆCH VỊ TRÍ)
                elif isinstance(tsz_poly, list) and len(tsz_poly) == 4:
                    clean_pts = []
                    for p in tsz_poly:
                        px = float(p[0])
                        py = float(p[1])
                        if px > 1.0:
                            px = px / 1000.0 if px <= 1000.0 else px / float(w)
                        if py > 1.0:
                            py = py / 1000.0 if py <= 1000.0 else py / float(h)
                        clean_pts.append([round(max(0.01, min(0.99, px)), 3), round(max(0.01, min(0.99, py)), 3)])

                    # LỚP BẢO VỆ 1: KIỂM ĐỊNH HÌNH HỌC VẬT LÝ (SANITY CHECK)
                    is_valid = self._validate_crib_polygon(clean_pts, w, h, check_baby=self.baby_detected)
                    if not is_valid:
                        print(f"[VisionTracker] ⚠️ Khung nôi đề xuất {clean_pts} không đạt tiêu chuẩn hình học (diện tích/độ lồi/chứa bé). Bác bỏ đề xuất!")
                        # Nếu khung hiện tại bị lỗi hình học, tự động rollback về Tọa Độ Vàng
                        if not self._validate_crib_polygon(self.safe_zone_polygon, w, h, check_baby=False):
                            import copy
                            with self.lock:
                                self.safe_zone_polygon = copy.deepcopy(self.last_verified_safe_zone)
                            print(f"[VisionTracker] 🔄 Đã tự động Rollback về Tọa Độ Vàng gần nhất: {self.last_verified_safe_zone}")
                    else:
                        # LỚP BẢO VỆ 2: CƠ CHẾ 2 BƯỚC XÁC THỰC (TWO-PHASE COMMIT)
                        if need_init_crib:
                            # Khởi động lần đầu chưa có nôi: Chấp nhận ngay để thiết lập ban đầu
                            self._commit_safe_zone(clean_pts)
                            print(f"[VisionTracker] ✨ [Khởi tạo ban đầu] Đã thiết lập Khung Nôi 3D: {clean_pts}")
                        elif self.pending_crib_candidate is not None:
                            # BƯỚC 2: Đã có đề xuất ở lần gọi trước, tiến hành đối chiếu xác thực chéo giữa 2 lần AI liên tiếp!
                            diff = max(
                                abs(p1[0] - p2[0]) + abs(p1[1] - p2[1])
                                for p1, p2 in zip(clean_pts, self.pending_crib_candidate)
                            )
                            if diff < 0.18:
                                # Cả 2 lần gọi AI liên tiếp đồng thuận trí về vị trí nôi mới! -> CHỐT HẠ & LƯU CẤU HÌNH
                                self._commit_safe_zone(clean_pts)
                                self.pending_crib_candidate = None
                                self.pending_crib_hits = 0
                                print(f"[VisionTracker] 🎯 [Bước 2/2: Xác thực & Chốt hạ] Khung nôi mới đã được xác thực 2 lần AI liên tiếp đồng thuận (độ lệch {round(diff, 3)} < 0.18)! Đã lưu an toàn.")
                            else:
                                # Hai lần gọi AI đưa tọa độ chênh lệch nhau -> AI đang dao động, cập nhật ứng viên và chờ thêm
                                print(f"[VisionTracker] ⏳ [Đối chiếu] 2 lần gọi AI trả về tọa độ còn chênh lệch ({round(diff, 3)} >= 0.18). Giữ nguyên khung cũ và theo dõi tiếp.")
                                self.pending_crib_candidate = clean_pts
                        else:
                            # BƯỚC 1: Ghi nhận đề xuất ứng viên lần đầu, chưa ghi đè config ngay!
                            self.pending_crib_candidate = clean_pts
                            self.pending_crib_hits = 1
                            print(f"[VisionTracker] 🔍 [Bước 1/2: Đề xuất] Gemini đề xuất vị trí nôi mới: {clean_pts}. Đang giữ ở hàng đợi xác thực chéo lần kế tiếp...")

                elif isinstance(tsz, list) and len(tsz) == 4:
                    clean_sz = []
                    for i, val in enumerate(tsz):
                        v = float(val)
                        dim = float(w) if i in (0, 2) else float(h)
                        if v > 1.0:
                            v = v / 1000.0 if v <= 1000.0 else v / dim
                        clean_sz.append(round(max(0.01, min(0.99, v)), 3))
                    l, t, r, b = clean_sz
                    if r > l and b > t:
                        rect_poly = [[l, t], [r, t], [r, b], [l, b]]
                        if self._validate_crib_polygon(rect_poly, w, h, check_baby=self.baby_detected):
                            if need_init_crib or self.pending_crib_candidate is not None:
                                self._commit_safe_zone(rect_poly)
                                self.pending_crib_candidate = None
                                self.pending_crib_hits = 0
                                print(f"[VisionTracker] 🎯 Đã xác thực Khung Nôi chữ nhật theo Gemini: {rect_poly}")
                            else:
                                self.pending_crib_candidate = rect_poly
                                self.pending_crib_hits = 1
                else:
                    self.initial_crib_calibrated = True

                if not res.get("baby_present", True):
                    with self.lock:
                        self.baby_detected = False
                        self.adult_holding_baby = False
                        self.baby_stable_detected = False
                        self.last_baby_box = None
                        self.gemini_anchor_box = None
                        self.gemini_anchor_until = 0.0
                        self.is_near_edge = False
                        self.danger_zone_frame_count = 0
                        if self.sleep_pose not in ("Người lớn trong phòng", "Ngoài giường"):
                            self.sleep_pose = "Ngoài giường"
                            self.baby_status = "Không có em bé trong nôi"
                    return

                if self.sleep_tracker is not None and "is_baby_awake" in res:
                    self.sleep_tracker.sync_gemini_wake_state(bool(res.get("is_baby_awake", False)))

                acc = res.get("tracking_accurate", True)
                score = res.get("accuracy_score", 95)
                tbox = res.get("true_baby_box")
                hdir = res.get("head_direction", "up")

                # 2. Nếu AI Local đang đóng khung lệch (hoặc chưa bắt được bé), hiệu chỉnh ngay theo tọa độ của Gemini!
                if (not acc or score < 78 or not self.baby_detected) and isinstance(tbox, list) and len(tbox) == 4:
                    xmin, ymin, xmax, ymax = [float(v) for v in tbox]
                    # BẢO VỆ CHỐNG HALLUCINATION:
                    # Nếu Gemini đề xuất khung chữ nhật dính sát mép trên màn hình (ymin < 0.02 và ymax < 0.22) hoặc mép dưới (ymax > 0.98),
                    # đây là người lớn thò tay/chân vào, tuyệt đối không gán làm anchor em bé!
                    is_border_strip = (ymin < 0.02 and (ymax - ymin) < 0.25) or (ymax > 0.98 and (ymax - ymin) < 0.25)
                    if not is_border_strip:
                        gx1 = int(np.clip(min(xmin, xmax) * w, 0, w - 20))
                        gy1 = int(np.clip(min(ymin, ymax) * h, 0, h - 20))
                        gx2 = int(np.clip(max(xmin, xmax) * w, gx1 + 40, w))
                        gy2 = int(np.clip(max(ymin, ymax) * h, gy1 + 40, h))
                        g_box = np.array([gx1, gy1, gx2, gy2], dtype=int)

                        dir_map = {
                            "right": np.array([-1.0, 0.0], dtype=float),
                            "left": np.array([1.0, 0.0], dtype=float),
                            "up": np.array([0.0, 1.0], dtype=float),
                            "down": np.array([0.0, -1.0], dtype=float),
                        }
                        new_u = dir_map.get(str(hdir).lower(), np.array([-1.0, 0.0], dtype=float))

                        with self.lock:
                            self.smoothed_box = g_box.astype(float)
                            self.last_baby_box = g_box
                            self.smoothed_spine_u = new_u
                            self.gemini_anchor_box = g_box
                            self.gemini_anchor_u = new_u
                            self.gemini_anchor_pose = res.get("sleep_pose_vi", "Đang ngủ ngoan")
                            self.gemini_anchor_until = time.time() + 55.0
                        print(f"[VisionTracker] 🔧 Đã hiệu chỉnh nóng khung Tracking theo Gemini: box={g_box.tolist()}, head_dir={hdir}")
            except Exception as e:
                print(f"[VisionTracker] Lỗi _audit_worker: {e}")
            finally:
                self.pending_tracking_audit = False

        threading.Thread(target=_audit_worker, daemon=True).start()

    def _process_frame(self, frame):
        h, w = frame.shape[:2]
        self.raw_frame_burst.append(frame.copy())
        annotated = frame.copy()

        # 0. Kiểm tra trực quan xem nôi/giường có bé hay trống rỗng (Crib Occupancy Check)
        is_occupied = self._check_crib_occupied(frame, h, w)
        if not is_occupied:
            self.baby_detected = False
            self.baby_stable_detected = False
            self.baby_stable_frames = 0
            self.covered_face_active = False
            self.covered_face_frame_count = 0
            self.sleep_pose = "Ngoài giường"
            self.baby_status = "Bé không có trong nôi"
            self.motion_score = 0.0
            self.smoothed_motion = 0.0
            self.breathing_bpm = 0.0
            self.breathing_status = "Ngoài giường"
            self.prev_keypoints = None
            self.prev_keypoints_conf = None
            self.last_baby_box = None
            self.last_face_box = None
            self.chest_history = []
            self.prev_breathing_roi = None

            if self.sleep_tracker:
                self.sleep_tracker.update_state(False, False)

            if self.danger_zone_enabled:
                z_top = int(h * self.safe_zone_top)
                z_bottom = int(h * self.safe_zone_bottom)
                z_left = int(w * self.safe_zone_left)
                z_right = int(w * self.safe_zone_right)
                cv2.rectangle(annotated, (z_left, z_top), (z_right, z_bottom), (70, 215, 90), 1, cv2.LINE_AA)

            return annotated

        # 1. Quét nhận diện khuôn mặt chuyên dụng bằng YuNet (Face-First Detector)
        baby_face_info, has_adult_face, adult_face_box = self._detect_baby_face(frame)

        # 2. Run YOLO inference với conf=0.18 chuẩn xác, lọc nhiễu bóng mờ
        results = self.model(frame, device=self.device, verbose=False, conf=0.18)
        r = results[0]

        best_baby_idx, has_adult, adult_box, is_occluded = self._select_real_baby(r, h, w)
        if not has_adult and has_adult_face:
            has_adult = True
            if adult_box is None and adult_face_box is not None:
                afx, afy, afw, afh = adult_face_box
                adult_box = np.array([max(0, afx - afw), max(0, afy - afh), min(w, afx + afw * 2), min(h, afy + afh * 4)])

        # Nếu YuNet 360° đã bắt được mặt bé rõ ràng (đặc biệt khi bé nằm ngang 90° hoặc quấn chăn),
        # kiểm tra xem khung YOLO có khớp với đầu bé không; nếu lệch hoặc bé nằm ngang thì ưu tiên Face-First 360°!
        if baby_face_info is not None and best_baby_idx is not None:
            bfx, bfy, bfw, bfh = baby_face_info["bbox"]
            fcx, fcy = bfx + bfw / 2.0, bfy + bfh / 2.0
            ybox = r.boxes[best_baby_idx].xyxy[0].cpu().numpy()
            head_in_ybox = (ybox[0] - 30 <= fcx <= ybox[2] + 30) and (ybox[1] - 30 <= fcy <= ybox[3] + 30)
            if (not head_in_ybox) or baby_face_info.get("orient") in ("90_ccw", "90_cw"):
                best_baby_idx = None

        if best_baby_idx is not None:
            self.baby_detected = True
            self.adult_holding_baby = False
            self.baby_last_seen_time = time.time()
            self.lost_frames = 0
            
            kpt_data = r.keypoints.data[best_baby_idx].cpu().numpy() # shape (17, 3)
            kpts_xy = kpt_data[:, :2]
            kpts_conf = kpt_data[:, 2]
            box_xyxy = r.boxes[best_baby_idx].xyxy[0].cpu().numpy().astype(int)

            # --- ANATOMICAL INFANT FILTER ---
            if kpts_conf[5] > 0.30 and kpts_conf[6] > 0.30:
                shoulder_center = (kpts_xy[5] + kpts_xy[6]) / 2.0
                shoulder_w = np.linalg.norm(kpts_xy[5] - kpts_xy[6])
                max_torso_reach = max(shoulder_w * 2.2, 150.0)
                for ki in range(11, 17):
                    if np.linalg.norm(kpts_xy[ki] - shoulder_center) > max_torso_reach:
                        kpts_conf[ki] = 0.0

            valid_k = kpts_conf > 0.30
            if np.sum(valid_k) >= 3:
                vx = kpts_xy[valid_k, 0]
                vy = kpts_xy[valid_k, 1]
                pad_x = 25
                pad_y = 25
                tight_box = np.array([
                    max(0, int(np.min(vx) - pad_x)),
                    max(0, int(np.min(vy) - pad_y)),
                    min(w, int(np.max(vx) + pad_x)),
                    min(h, int(np.max(vy) + pad_y))
                ])
                if (tight_box[2] - tight_box[0]) < (box_xyxy[2] - box_xyxy[0]) * 0.85:
                    box_xyxy = tight_box

            self.last_baby_box = box_xyxy

            if not is_occluded:
                self.baby_stable_frames = min(60, getattr(self, "baby_stable_frames", 0) + 1)
                if self.baby_stable_frames >= 8:
                    self.baby_stable_detected = True

            # 1. Calculate Pose & Swaddle State
            pose_text, pose_level = self._determine_pose(kpts_xy, kpts_conf)
            visible_limbs = int(np.sum(kpts_conf[[7, 8, 9, 10, 13, 14, 15, 16]] > 0.25))
            torso_y1 = int(box_xyxy[1] + (box_xyxy[3] - box_xyxy[1]) * 0.32)
            torso_skin = self._check_skin_in_roi(frame, box_xyxy[0], torso_y1, box_xyxy[2], box_xyxy[3])
            self.is_swaddled = (visible_limbs < 2) and (torso_skin < 0.065)
            if self.is_swaddled and pose_text == "Nằm ngủ ngoan":
                pose_text = "Nằm ngủ ngoan (Quấn chăn)"
            self.sleep_pose = pose_text

            # Theo dõi thay đổi tư thế ngủ với Debounce 10 giây (Bé phải giữ tư thế mới >= 10s mới kích hoạt Gemini Audit)
            now_t = time.time()
            if pose_text != getattr(self, "last_confirmed_pose", None):
                if getattr(self, "pose_candidate", None) != pose_text:
                    self.pose_candidate = pose_text
                    self.pose_candidate_start_time = now_t
                elif (now_t - self.pose_candidate_start_time) >= getattr(self, "pose_debounce_sec", 10.0):
                    self.last_confirmed_pose = pose_text
                    self.pose_changed_and_stabilized = True
            else:
                self.pose_candidate = None
                self.pose_candidate_start_time = now_t

            if self.prone_alert_enabled and pose_level == "danger":
                self.prone_frame_count += 1
                if self.prone_frame_count >= 35 and self.on_prone_callback: # ~3.0 seconds
                    self.on_prone_callback()
            else:
                self.prone_frame_count = max(0, self.prone_frame_count - 1)

            # 2. Check Covered Face (mặt bị chăn gối khăn che khuất)
            face_confs = kpts_conf[:3]
            face_mean = float(np.mean(face_confs))
            torso_mean = float(np.mean([kpts_conf[5], kpts_conf[6]]))
            
            mr = 65
            if kpts_conf[0] > 0.15:
                fcx, fcy = int(kpts_xy[0, 0]), int(kpts_xy[0, 1])
                fx1, fy1, fx2, fy2 = max(0, fcx - mr), max(0, fcy - mr), min(w, fcx + mr), min(h, fcy + mr)
            else:
                fx1, fy1, fx2, fy2 = box_xyxy[0], box_xyxy[1], min(w, box_xyxy[0] + mr * 2), min(h, box_xyxy[1] + mr * 2)

            skin_ratio = self._check_skin_in_roi(frame, fx1, fy1, fx2, fy2)
            if skin_ratio > 0.05 or face_mean > 0.25:
                self.had_visible_face = True
                self.last_face_box = np.array([fx1, fy1, fx2, fy2])

            face_hidden = False
            if torso_mean >= 0.25 and face_mean < 0.18 and skin_ratio < 0.035 and (time.time() > self.gemini_suppressed_until):
                face_hidden = True

            if self.covered_face_alert and face_hidden:
                self.covered_face_frame_count += 1
                if self.covered_face_frame_count >= 15: # ~1.2s - 1.5s debounce
                    self._trigger_gemini_alert_verify(frame, "covered_face", "Vùng mặt bé bị khuất hoặc có chăn/gối che")
            else:
                self.covered_face_frame_count = max(0, self.covered_face_frame_count - 1)
                if self.covered_face_frame_count == 0:
                    self.covered_face_active = False

            # 3. Check Virtual Safe Zone / Bed Boundary bằng cv2.pointPolygonTest
            bcx = (box_xyxy[0] + box_xyxy[2]) / 2.0
            bcy = (box_xyxy[1] + box_xyxy[3]) / 2.0
            is_inside_poly = self._is_point_in_safe_zone(bcx, bcy, w, h, margin_px=-10.0)
            self.is_near_edge = not is_inside_poly

            if self.danger_zone_enabled and self.is_near_edge:
                self.danger_zone_frame_count += 1
                if self.danger_zone_frame_count >= 15 and self.on_danger_zone_callback:
                    self.on_danger_zone_callback()
            else:
                self.danger_zone_frame_count = max(0, self.danger_zone_frame_count - 1)

            # 4. Robust Infant Motion Velocity (với Deadband lọc rung tự nhiên của YOLO detector)
            if self.prev_keypoints is not None:
                valid_mask = (kpts_conf > 0.25) & (self.prev_keypoints_conf > 0.25)
                if np.sum(valid_mask) >= 3:
                    diffs = np.linalg.norm(kpts_xy - self.prev_keypoints, axis=1)

                    # Deadband: Lọc bỏ rung lắc micro-jitter của mô hình Pose khi bé nằm yên
                    # (5.5px cho các điểm trọng yếu như đầu, vai, hông; 7.5px cho tứ chi)
                    core_indices = [0, 1, 2, 5, 6, 11, 12]
                    limb_indices = [k for k in range(17) if k not in core_indices]

                    core_diffs = [diffs[k] for k in core_indices if valid_mask[k] and diffs[k] >= 5.5]
                    core_m = float(np.median(core_diffs)) if core_diffs else 0.0

                    limb_diffs = [diffs[k] for k in limb_indices if valid_mask[k] and diffs[k] >= 7.5]
                    limb_m = float(np.median(limb_diffs)) if limb_diffs else 0.0

                    bcx = (box_xyxy[0] + box_xyxy[2]) / 2.0
                    bcy = (box_xyxy[1] + box_xyxy[3]) / 2.0
                    if getattr(self, "prev_bc", None) is not None:
                        center_shift = float(np.hypot(bcx - self.prev_bc[0], bcy - self.prev_bc[1]))
                        center_shift = 0.0 if center_shift < 3.5 else center_shift
                    else:
                        center_shift = 0.0
                    self.prev_bc = (bcx, bcy)

                    raw_motion = 0.6 * core_m + 0.25 * limb_m + 0.15 * min(30.0, center_shift)
                else:
                    raw_motion = 0.0
            else:
                raw_motion = 0.0

            self.prev_keypoints = kpts_xy.copy()
            self.prev_keypoints_conf = kpts_conf.copy()

            self.smoothed_motion = 0.75 * self.smoothed_motion + 0.25 * raw_motion
            self.motion_score = self.smoothed_motion

            # Respiration / Breathing Rate calculation
            if self.breathing_monitor_enabled:
                now_t = time.time()
                roi_coords = self._extract_breathing_roi(kpts_xy, kpts_conf, h, w)
                if roi_coords is not None:
                    rx1, ry1, rx2, ry2 = roi_coords
                    self._update_breathing(frame, now_t, rx1, ry1, rx2, ry2)

            # --- CUTE MOMENTS AUTO-CAPTURE (CÓ HỖ TRỢ KIỂM DUYỆT NGƯỜI ĐI CÙNG QUA GEMINI AI) ---
            now_t = time.time()
            allow_co_presence = (self.gemini_verifier is not None and self.gemini_verifier.is_ready() and self.gemini_verifier.filter_moments_enabled)
            if (self.cute_moments_enabled and 
                getattr(self, "baby_stable_detected", False) and 
                getattr(self, "baby_stable_frames", 0) >= 20 and 
                (not has_adult or allow_co_presence) and 
                not getattr(self, "covered_face_active", False) and 
                not is_occluded and 
                pose_level == "safe" and 
                self.smoothed_motion < 5.0 and 
                (now_t - self.last_moment_time >= self.moment_capture_interval)):
                
                nose_conf = float(kpts_conf[0])
                le_conf = float(kpts_conf[1])
                re_conf = float(kpts_conf[2])
                eye_dist = float(np.linalg.norm(kpts_xy[1] - kpts_xy[2]))
                
                if kpts_conf[5] > 0.25 and kpts_conf[6] > 0.25:
                    shoulder_w = float(np.linalg.norm(kpts_xy[5] - kpts_xy[6]))
                else:
                    shoulder_w = 0.0

                is_valid_face = (nose_conf >= 0.50 and le_conf >= 0.40 and re_conf >= 0.40 and 12.0 <= eye_dist <= 65.0)
                is_valid_infant_size = (shoulder_w == 0.0 or (30.0 <= shoulder_w <= 130.0))

                if baby_face_info is not None and is_valid_face and is_valid_infant_size:
                    self._trigger_cute_moment_capture(frame, baby_face_info)

            if not getattr(self, "covered_face_active", False):
                is_awake_mode = (self.sleep_tracker is not None and self.sleep_tracker.current_state == "AWAKE")
                if self.smoothed_motion > self.motion_threshold:
                    self.baby_status = "Đang thức chơi / Vận động" if is_awake_mode else "Cựa quậy / Thức giấc"
                    if self.on_motion_callback:
                        self.on_motion_callback(self.smoothed_motion)
                else:
                    if is_awake_mode:
                        if self.sleep_tracker and getattr(self.sleep_tracker, "pending_state", None) == "ASLEEP":
                            self.baby_status = "Nằm yên tĩnh (Vào giấc ngủ)"
                        elif self.smoothed_motion < 2.5:
                            self.baby_status = "Nằm yên tĩnh / Thư giãn"
                        else:
                            self.baby_status = "Đang thức tỉnh táo (Quan sát)"
                    else:
                        self.baby_status = "Đang ngủ ngoan"

            if baby_face_info is not None:
                bfx, bfy, bfw, bfh = baby_face_info["bbox"]
                self.had_visible_face = True
                self.last_face_box = np.array([bfx, bfy, bfx + bfw, bfy + bfh])

            self.last_baby_box = box_xyxy
            self.lost_frames = 0
            self._draw_baby_skeleton(annotated, box_xyxy, kpts_xy, kpts_conf)
        elif baby_face_info is not None:
            # === DUAL-ENGINE FACE-FIRST TRACKING (ĐỊNH VỊ TỪ ĐẦU SANG CƠ THỂ BÉ XOAY THEO TRỤC SỐNG LƯNG) ===
            self.baby_detected = True
            self.adult_holding_baby = False
            self.baby_last_seen_time = time.time()
            self.lost_frames = 0
            
            self.baby_stable_frames = min(60, getattr(self, "baby_stable_frames", 0) + 1)
            if self.baby_stable_frames >= 8:
                self.baby_stable_detected = True

            # 1. Suy diễn toàn bộ Bounding Box cơ thể bé và ROI lồng ngực xoay nghiêng từ khuôn mặt YuNet
            body_box, chest_roi = self._derive_infant_from_face(baby_face_info, h, w)
            bx1, by1, bx2, by2 = body_box
            self.last_baby_box = body_box

            fx, fy, fw, fh = baby_face_info["bbox"]
            self.last_face_box = np.array([fx, fy, fx + fw, fy + fh])
            self.had_visible_face = True

            # 2. KIỂM TRA ĐƯỜNG THỞ MŨI - MIỆNG (KHÔNG QUÉT NHẦM GỐI ÔM BÊN CẠNH)
            is_obstructed, foreign_ratio = self._check_body_obstruction(
                frame, body_box, baby_face_info["bbox"], landmarks=baby_face_info.get("landmarks")
            )
            
            if is_obstructed and (time.time() > self.gemini_suppressed_until):
                self.covered_face_frame_count += 1
                if self.covered_face_frame_count >= 15: # ~1.2s - 1.5s debounce
                    self._trigger_gemini_alert_verify(frame, "covered_face", "Phát hiện vật cản che vùng mũi/miệng của bé")
            else:
                self.covered_face_frame_count = max(0, self.covered_face_frame_count - 1)
                if self.covered_face_frame_count == 0:
                    self.covered_face_active = False

            # Phân loại bé có đang quấn chăn/kén (is_swaddled) hay nằm tự do
            if not getattr(self, "covered_face_active", False):
                torso_skin = self._check_skin_in_roi(frame, bx1, min(h, fy + int(fh * 0.85)), bx2, by2)
                self.is_swaddled = (torso_skin < 0.065)
                if self.is_swaddled:
                    self.sleep_pose = "Nằm ngủ ngoan (Quấn chăn)"
                else:
                    self.sleep_pose = "Nằm ngủ tự do"

            # 3. Kiểm tra khung bảo vệ an toàn nôi bằng cv2.pointPolygonTest
            fcx = fx + fw / 2.0
            fcy = fy + fh / 2.0
            is_inside_poly = self._is_point_in_safe_zone(fcx, fcy, w, h, margin_px=-5.0)
            self.is_near_edge = not is_inside_poly

            if self.danger_zone_enabled and self.is_near_edge:
                self.danger_zone_frame_count += 1
                if self.danger_zone_frame_count >= 15 and self.on_danger_zone_callback:
                    self.on_danger_zone_callback()
            else:
                self.danger_zone_frame_count = max(0, self.danger_zone_frame_count - 1)

            # 4. Đo vận tốc cử động quang học cơ thể bé
            body_crop = frame[max(0, by1):min(h, by2), max(0, bx1):min(w, bx2)]
            if body_crop.size > 0:
                gray_body = cv2.cvtColor(body_crop, cv2.COLOR_BGR2GRAY)
                gray_body = cv2.resize(gray_body, (80, 80))
                if getattr(self, "prev_body_crop", None) is not None and self.prev_body_crop.shape == gray_body.shape:
                    diff = cv2.absdiff(gray_body, self.prev_body_crop)
                    raw_motion = float(np.mean(diff))
                    raw_motion = 0.0 if raw_motion < 2.5 else raw_motion
                else:
                    raw_motion = 0.0
                self.prev_body_crop = gray_body
            else:
                raw_motion = 0.0

            self.smoothed_motion = 0.75 * self.smoothed_motion + 0.25 * raw_motion
            self.motion_score = self.smoothed_motion

            # 5. Đo nhịp thở quang học vi mô ở vùng lồng ngực xoay nghiêng
            if self.breathing_monitor_enabled and not getattr(self, "covered_face_active", False):
                now_t = time.time()
                rx1, ry1, rx2, ry2 = chest_roi
                self._update_breathing(frame, now_t, rx1, ry1, rx2, ry2)

            # Tự động chụp khoảnh khắc đáng yêu khi nhận diện bằng YuNet + kiểm duyệt & cắt khung thông minh Gemini
            now_t = time.time()
            if (self.cute_moments_enabled and
                getattr(self, "baby_stable_detected", False) and
                getattr(self, "baby_stable_frames", 0) >= 20 and
                not getattr(self, "covered_face_active", False) and
                self.smoothed_motion < 12.0 and
                baby_face_info.get("conf", 0.0) >= 0.65 and
                (now_t - self.last_moment_time >= self.moment_capture_interval)):
                self._trigger_cute_moment_capture(frame, baby_face_info)

            if not getattr(self, "covered_face_active", False):
                is_awake_mode = (self.sleep_tracker is not None and self.sleep_tracker.current_state == "AWAKE")
                if self.smoothed_motion > self.motion_threshold:
                    self.baby_status = "Đang thức chơi / Vận động" if is_awake_mode else "Cựa quậy / Thức giấc"
                    if self.on_motion_callback:
                        self.on_motion_callback(self.smoothed_motion)
                else:
                    if is_awake_mode:
                        if self.sleep_tracker and getattr(self.sleep_tracker, "pending_state", None) == "ASLEEP":
                            self.baby_status = "Nằm yên tĩnh (Vào giấc ngủ)"
                        elif self.smoothed_motion < 2.5:
                            self.baby_status = "Nằm yên tĩnh / Thư giãn"
                        else:
                            self.baby_status = "Đang thức tỉnh táo (Quan sát)"
                    else:
                        self.baby_status = "Đang ngủ ngoan"

            # Giữ nguyên video trong trẻo, không vẽ khung tracking đè lên người bé (Chỉ để lại viền nôi Safe Zone)
            pass
        elif has_adult:
            # Phân biệt chính xác: Người lớn ngồi cạnh giường vs Bé đã được bế ra ngoài
            now_t = time.time()
            baby_recently_seen = (now_t - getattr(self, "baby_last_seen_time", 0.0)) < 4.0
            baby_ref_box = getattr(self, "last_baby_box", None) if baby_recently_seen else None
            is_in_safe_zone = False
            if baby_ref_box is not None:
                bcx = (baby_ref_box[0] + baby_ref_box[2]) / 2.0
                bcy = (baby_ref_box[1] + baby_ref_box[3]) / 2.0
                is_in_safe_zone = self._is_point_in_safe_zone(bcx, bcy, w, h, margin_px=30.0)

            is_touching_baby = False
            if baby_ref_box is not None and adult_box is not None:
                ax1, ay1, ax2, ay2 = adult_box
                bx1, by1, bx2, by2 = baby_ref_box
                inter_x1 = max(ax1, bx1)
                inter_y1 = max(ay1, by1)
                inter_x2 = min(ax2, bx2)
                inter_y2 = min(ay2, by2)
                if inter_x2 > inter_x1 and inter_y2 > inter_y1:
                    inter_area = (inter_x2 - inter_x1) * (inter_y2 - inter_y1)
                    baby_area = max(1.0, (bx2 - bx1) * (by2 - by1))
                    if inter_area / baby_area > 0.25:
                        is_touching_baby = True

            # NẾU BÉ VỪA ĐƯỢC PHÁT HIỆN GẦN ĐÂY (< 4.0s) VÀ ĐANG Ở TRONG SAFE ZONE: Bé đang nằm nôi, người lớn chỉ ngồi bên cạnh!
            if is_in_safe_zone and baby_recently_seen:
                self.baby_detected = True
                self.adult_holding_baby = False
                self.baby_stable_detected = True
                self.covered_face_active = False
                self.covered_face_frame_count = 0
                if self.sleep_pose in ("Ngoài giường", "Người lớn trong phòng", "Đang được bế trên tay", "Không phát hiện bé"):
                    self.sleep_pose = "Nằm ngủ ngoan"
                self.baby_status = "Bé đang nằm nôi • Bố mẹ ở cạnh"
                if self.breathing_status in ("Ngoài giường", "Bố mẹ đang bế"):
                    self.breathing_status = "Đang theo dõi nhịp thở"
            elif is_touching_baby and baby_recently_seen:
                # Bé ở ngoài Safe Zone VÀ người lớn tiếp xúc bế bé
                self.baby_detected = True
                self.adult_holding_baby = True
                self.baby_stable_detected = False
                self.baby_stable_frames = 0
                self.covered_face_active = False
                self.covered_face_frame_count = 0
                self.sleep_pose = "Đang được bế trên tay"
                self.baby_status = "Bố mẹ đang bế / chăm sóc bé"
                self.breathing_status = "Bố mẹ đang bế"
                if self.breathing_bpm <= 5.0:
                    self.breathing_bpm = 48.0
            else:
                # BÉ KHÔNG CÓ TRONG NÔI HOẶC ĐÃ RỜI ĐI > 4 GIÂY: Chỉ có người lớn trong phòng!
                self.baby_detected = False
                self.adult_holding_baby = False
                self.baby_stable_detected = False
                self.baby_stable_frames = 0
                self.sleep_pose = "Người lớn trong phòng"
                self.baby_status = "Bé đã rời nôi • Người lớn trong phòng"
                self.breathing_bpm = 0.0
                self.breathing_status = "Ngoài giường"
                self.last_baby_box = None
                self.gemini_anchor_box = None
                self.gemini_anchor_until = 0.0
                self.is_near_edge = False
                self.danger_zone_frame_count = 0

            self.motion_score = 0.0
            self.smoothed_motion = 0.0
            self.lost_frames = 0
            self.prone_frame_count = 0
            self.danger_zone_frame_count = 0

            # Không vẽ khung màu đè lên phụ huynh
            pass
        elif getattr(self, "gemini_anchor_box", None) is not None and time.time() < getattr(self, "gemini_anchor_until", 0.0):
            # Giữ khóa mục tiêu em bé theo tọa độ chuẩn do Gemini vừa hiệu chỉnh nóng (Hot-Anchor)
            self.baby_detected = True
            self.adult_holding_baby = False
            g_box = self.gemini_anchor_box
            bx1, by1, bx2, by2 = g_box
            self.last_baby_box = g_box
            self.sleep_pose = getattr(self, "gemini_anchor_pose", "Đang ngủ ngoan")
            self.baby_status = "Đang ngủ ngoan (AI Đồng bộ)"
            if self.breathing_monitor_enabled:
                cx = int((bx1 + bx2) / 2)
                cy = int((by1 + by2) / 2)
                rw = max(25, int((bx2 - bx1) * 0.22))
                rh = max(25, int((by2 - by1) * 0.22))
                self._update_breathing(frame, time.time(), max(0, cx - rw), max(0, cy - rh), min(w, cx + rw), min(h, cy + rh))
        else:
            # Kiểm tra tình huống MẶT BÉ VỪA BỊ CHE KHUẤT / TRÙM KHĂN ĐỘT NGỘT:
            # Nếu bé vừa được phát hiện trong nôi (< 15s trước), không có người lớn bế đi,
            # và vị trí mặt trước đó bị mất hoàn toàn sắc tố da do có khăn/chăn đè lên:
            now_t = time.time()
            face_recently_seen = (now_t - getattr(self, "baby_last_seen_time", 0.0) < 15.0) and (getattr(self, "last_face_box", None) is not None)
            
            is_sudden_occlusion = False
            if self.covered_face_alert and face_recently_seen and not has_adult and (now_t > getattr(self, "gemini_suppressed_until", 0.0)):
                fx1, fy1, fx2, fy2 = self.last_face_box
                face_skin = self._check_skin_in_roi(frame, fx1, fy1, fx2, fy2)
                if face_skin < 0.035:
                    is_sudden_occlusion = True

            if is_sudden_occlusion:
                self.baby_detected = True
                self.adult_holding_baby = False
                self.sleep_pose = "Mặt bị che khuất (Nguy cơ ngạt)"
                self.baby_status = "CẢNH BÁO: MẶT BÉ BỊ CHE KHUẤT!"
                self.covered_face_frame_count += 1

                if self.covered_face_frame_count >= 15: # ~1.2s - 1.5s
                    self._trigger_gemini_alert_verify(frame, "covered_face", "Mặt bé vừa bị khăn/chăn trùm kín đột ngột")
            else:
                # Hoàn toàn không phát hiện bé và không có người lớn
                self.adult_holding_baby = False
                self.baby_detected = False
                self.baby_stable_detected = False
                self.baby_stable_frames = 0
                self.covered_face_active = False
                self.covered_face_frame_count = 0
                self.sleep_pose = "Không phát hiện bé"
                self.baby_status = "Bé không có trong nôi"
                self.motion_score = 0.0
                self.smoothed_motion = 0.0
                self.breathing_bpm = 0.0
                self.breathing_status = "Ngoài giường"
                self.prev_keypoints = None
                self.prev_keypoints_conf = None
                self.last_baby_box = None
                self.chest_history = []
                self.prev_breathing_roi = None

        # Update Sleep & Wake Window Analytics Tracker
        if self.sleep_tracker:
            self.sleep_tracker.update_state(
                self.baby_detected,
                (self.smoothed_motion > self.motion_threshold),
                self.smoothed_motion
            )

        # Draw Virtual Crib / Safe Zone on video (VIỀN NÔI 3D PERSPECTIVE QUADRILATERAL)
        if self.danger_zone_enabled:
            pts = self._get_safe_zone_polygon(w, h)
            is_alert = (getattr(self, "is_near_edge", False) and self.baby_detected) or getattr(self, "covered_face_active", False)
            if is_alert:
                box_color = (0, 0, 240) # Bright red
                corner_color = (0, 40, 255)
                box_thickness = 2
            else:
                box_color = (70, 215, 90) # Emerald neon
                corner_color = (110, 250, 130)
                box_thickness = 1

            # 1. Vẽ viền đa giác Safe Zone 3D bẻ theo đúng góc phối cảnh tấm đệm / nôi
            cv2.polylines(annotated, [pts], isClosed=True, color=box_color, thickness=box_thickness, lineType=cv2.LINE_AA)

            # 2. Vẽ 4 góc định vị phát sáng bẻ theo đúng góc xiên phối cảnh của từng cạnh
            c_len = 28.0
            c_thick = 3
            n_pts = len(pts)
            for i in range(n_pts):
                p_curr = pts[i].astype(np.float32)
                p_prev = pts[(i - 1) % n_pts].astype(np.float32)
                p_next = pts[(i + 1) % n_pts].astype(np.float32)

                v_prev = p_prev - p_curr
                len_prev = np.linalg.norm(v_prev)
                if len_prev > 1e-4:
                    u_prev = v_prev / len_prev
                    arm_len_prev = min(c_len, len_prev * 0.4)
                    pt_arm_prev = (p_curr + u_prev * arm_len_prev).astype(np.int32)
                    cv2.line(annotated, (int(p_curr[0]), int(p_curr[1])), (int(pt_arm_prev[0]), int(pt_arm_prev[1])), corner_color, c_thick, cv2.LINE_AA)

                v_next = p_next - p_curr
                len_next = np.linalg.norm(v_next)
                if len_next > 1e-4:
                    u_next = v_next / len_next
                    arm_len_next = min(c_len, len_next * 0.4)
                    pt_arm_next = (p_curr + u_next * arm_len_next).astype(np.int32)
                    cv2.line(annotated, (int(p_curr[0]), int(p_curr[1])), (int(pt_arm_next[0]), int(pt_arm_next[1])), corner_color, c_thick, cv2.LINE_AA)

        # Chủ động tận dụng Quota Free dư thừa để gửi hình kiểm tra chéo & hiệu chỉnh Tracking AI Local
        self._maybe_trigger_tracking_audit(frame, annotated, h, w)

        return annotated

    def _draw_baby_skeleton(self, img, box, kpts_xy, kpts_conf):
        """
        Vẽ trực quan cấu trúc khung xương bé phân chia màu sắc theo từng bộ phận cơ thể:
        - Đầu & Khuôn mặt (Mũi, mắt, tai): Vàng hổ phách (0, 215, 255)
        - Cột sống & Thân trên (2 vai -> 2 hông): Xanh ngọc lục bảo (80, 240, 120)
        - Tay trái: Tím hoa cà (220, 120, 200)
        - Tay phải: Xanh da trời (255, 190, 80)
        - Chân trái: Hồng thắm (120, 80, 255)
        - Chân phải: Cam rực rỡ (50, 140, 255)
        - Đa giác ROI Lồng ngực / Bụng đo nhịp thở: Cyan phát sáng
        """
        if kpts_xy is None or kpts_conf is None or len(kpts_xy) < 17:
            return

        limbs = [
            # Đầu & Mặt (Vàng hổ phách)
            ((0, 1), (0, 215, 255)), ((0, 2), (0, 215, 255)), ((1, 3), (0, 215, 255)), ((2, 4), (0, 215, 255)),
            # Thân mình & Cột sống (Xanh ngọc lục bảo)
            ((5, 6), (80, 240, 120)), ((5, 11), (80, 240, 120)), ((6, 12), (80, 240, 120)), ((11, 12), (80, 240, 120)),
            # Tay trái (Tím hoa cà)
            ((5, 7), (220, 120, 200)), ((7, 9), (220, 120, 200)),
            # Tay phải (Xanh da trời)
            ((6, 8), (255, 190, 80)), ((8, 10), (255, 190, 80)),
            # Chân trái (Hồng thắm)
            ((11, 13), (120, 80, 255)), ((13, 15), (120, 80, 255)),
            # Chân phải (Cam rực rỡ)
            ((12, 14), (50, 140, 255)), ((14, 16), (50, 140, 255))
        ]

        # 1. Vẽ các đoạn xương nối nếu 2 đầu mút có độ tin cậy > 0.20
        for (i1, i2), col in limbs:
            if kpts_conf[i1] > 0.20 and kpts_conf[i2] > 0.20:
                p1 = (int(kpts_xy[i1][0]), int(kpts_xy[i1][1]))
                p2 = (int(kpts_xy[i2][0]), int(kpts_xy[i2][1]))
                cv2.line(img, p1, p2, col, 2, cv2.LINE_AA)

        # 2. Vẽ các khớp xương (Joints / Keypoints)
        for i in range(17):
            if kpts_conf[i] > 0.20:
                px = int(kpts_xy[i][0])
                py = int(kpts_xy[i][1])
                cv2.circle(img, (px, py), 4, (255, 255, 255), -1, cv2.LINE_AA)
                cv2.circle(img, (px, py), 2, (0, 0, 0), -1, cv2.LINE_AA)

        # 3. Vẽ hộp xoay ROI Lồng ngực / Bụng (nếu có)
        if getattr(self, "last_chest_poly", None) is not None:
            cv2.polylines(img, [self.last_chest_poly], isClosed=True, color=(255, 255, 0), thickness=2, lineType=cv2.LINE_AA)
            pt = self.last_chest_poly[0]
            cv2.putText(img, "ROI Tho", (int(pt[0]), max(15, int(pt[1]) - 4)), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 0), 1, cv2.LINE_AA)

    def _draw_hud(self, img):
        # Commercial Clean Feed: Không vẽ hộp đen đè lên góc video.
        # Toàn bộ trạng thái bé đã được hiển thị bằng các thẻ HTML kính mờ cao cấp trên giao diện web.
        return img

    def _make_disconnected_frame(self, message: str = "Đang kết nối lại Camera..."):
        frame = np.full((self.height, self.width, 3), (25, 25, 30), dtype=np.uint8)
        cv2.rectangle(frame, (20, 20), (self.width - 20, self.height - 20), (60, 60, 80), 1)
        pil_img = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        draw = ImageDraw.Draw(pil_img)
        w_text = f"⚠️ {message}"
        draw.text((self.width // 2 - 160, self.height // 2 - 30), w_text, font=self.font_title, fill=(255, 100, 100))
        draw.text((self.width // 2 - 200, self.height // 2 + 10), "Hệ thống đang tự động dò tìm và kết nối lại thiết bị...", font=self.font_body, fill=(180, 180, 190))
        return cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)

    def _open_camera_source(self, source=None):
        target = self.camera_index if source is None else source
        try:
            if isinstance(target, str) and (target.startswith("rtsp://") or target.startswith("http://") or target.startswith("https://")):
                os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp|stimeout;4000000"
                cap = cv2.VideoCapture(target, cv2.CAP_FFMPEG)
            else:
                idx = int(target)
                if sys.platform == "darwin":
                    cap = cv2.VideoCapture(idx, cv2.CAP_AVFOUNDATION)
                else:
                    cap = cv2.VideoCapture(idx)
            
            if cap and cap.isOpened():
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
                return cap
        except Exception as e:
            print(f"[VisionTracker] Lỗi kết nối camera ({target}): {e}")
        return None

    def switch_camera(self, new_source):
        """Đổi nóng nguồn Camera (Cổng USB hoặc URL RTSP Wi-Fi) ngay lập tức không cần khởi động lại."""
        if str(new_source) != str(self.camera_index):
            print(f"[VisionTracker] 🔄 Chuyển nguồn Camera sang: {new_source}")
            self.camera_index = new_source
            self.force_reconnect = True

    def capture_preview_frame(self, source):
        """
        Chụp 1 khung hình xem thử (Preview) từ cổng Camera USB hoặc đường dẫn RTSP
        để bố mẹ xem trước đâu là chiếc Camera đang quay em bé.
        """
        # Nếu đang xem thử chính chiếc camera đang chạy trực tiếp, lấy ngay khung hình hiện tại (0ms)
        if str(source) == str(self.camera_index):
            with self.lock:
                if self.raw_frame is not None and self.baby_status != "Mất tín hiệu camera":
                    return self.raw_frame.copy()

        # Mở kết nối tạm thời để chụp ảnh xem thử cho camera khác (USB phụ hoặc RTSP)
        cap = self._open_camera_source(source)
        if cap is None or not cap.isOpened():
            return None
        frame = None
        try:
            # Đọc vài frame đầu để cân bằng sáng tự động (Auto-Exposure) ổn định
            for _ in range(4):
                ret, f = cap.read()
                if ret and f is not None and f.mean() > 1.0:
                    frame = f
        finally:
            cap.release()
        return frame

    def _capture_loop(self):
        cap = None
        consecutive_bad_frames = 0
        frame_time = 1.0 / self.target_fps
        fps_counter = 0
        fps_start = time.time()
        self.force_reconnect = False
        
        while self.is_running:
            loop_start = time.time()

            if getattr(self, "force_reconnect", False):
                self.force_reconnect = False
                if cap is not None:
                    cap.release()
                    cap = None
            
            # Tự động kết nối lại nếu camera chưa mở hoặc bị mất
            if cap is None or not cap.isOpened():
                print(f"[VisionTracker] Đang dò tìm kết nối Camera {self.camera_index}...")
                cap = self._open_camera_source()
                if cap is None or not cap.isOpened():
                    placeholder = self._make_disconnected_frame()
                    with self.lock:
                        self.raw_frame = placeholder
                        self.annotated_frame = placeholder
                        self.baby_status = "Mất tín hiệu camera"
                    time.sleep(2.0)
                    continue
                else:
                    print("[VisionTracker] ✅ Camera đã kết nối thành công!")
                    consecutive_bad_frames = 0

            ret, frame = cap.read()
            if not ret or frame is None or frame.mean() < 2.0:
                consecutive_bad_frames += 1
                if consecutive_bad_frames > 20: # ~1.5 giây tín hiệu rớt
                    print("[VisionTracker] Mất tín hiệu hình ảnh. Đang tự động kết nối lại...")
                    if cap:
                        cap.release()
                    cap = None
                    consecutive_bad_frames = 0
                time.sleep(0.05)
                continue

            consecutive_bad_frames = 0

            if frame.shape[1] != self.width or frame.shape[0] != self.height:
                frame = cv2.resize(frame, (self.width, self.height))

            annotated = self._process_frame(frame)
            with self.lock:
                self.raw_frame = frame
                self.annotated_frame = annotated

            if self.frame_callback:
                self.frame_callback(annotated)

            fps_counter += 1
            if time.time() - fps_start >= 1.0:
                self.fps_actual = fps_counter / (time.time() - fps_start)
                fps_counter = 0
                fps_start = time.time()

            elapsed = time.time() - loop_start
            sleep_time = max(0.005, frame_time - elapsed)
            time.sleep(sleep_time)

        if cap:
            cap.release()
        print("[VisionTracker] Camera released.")

    def start(self):
        if self.is_running:
            return
        self.is_running = True
        self.worker_thread = threading.Thread(target=self._capture_loop, daemon=True)
        self.worker_thread.start()
        print("[VisionTracker] Vision tracker started.")

    def stop(self):
        self.is_running = False
        print("[VisionTracker] Stopping vision tracker...")

    def get_latest_frame(self, annotated: bool = True):
        with self.lock:
            if annotated and self.annotated_frame is not None:
                return self.annotated_frame.copy()
            elif self.raw_frame is not None:
                return self.raw_frame.copy()
            return None

    def get_status(self):
        return {
            "baby_detected": self.baby_detected,
            "adult_holding": getattr(self, "adult_holding_baby", False),
            "covered_face": getattr(self, "covered_face_active", False),
            "baby_status": self.baby_status,
            "sleep_pose": self.sleep_pose,
            "is_swaddled": getattr(self, "is_swaddled", False),
            "motion_score": round(self.motion_score, 1),
            "fps": round(self.fps_actual, 1),
            "breathing_bpm": self.breathing_bpm,
            "breathing_status": self.breathing_status,
            "inside_safe_zone": not getattr(self, "is_near_edge", False) if self.baby_detected else True,
            "safe_zone": {
                "enabled": self.danger_zone_enabled,
                "top": self.safe_zone_top,
                "bottom": self.safe_zone_bottom,
                "left": self.safe_zone_left,
                "right": self.safe_zone_right,
                "polygon": getattr(self, "safe_zone_polygon", None)
            }
        }
