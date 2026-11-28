"""
local_ai_face.py - Bộ nhận diện Trạng thái Mắt & Nụ cười Bé (Local Edge AI)
Sử dụng OpenCV YuNet & Phân tích hình học 5 điểm mốc khuôn mặt:
- Mắt phải (Right Eye), Mắt trái (Left Eye)
- Đỉnh mũi (Nose Tip)
- Khóe môi phải (Right Mouth Corner), Khóe môi trái (Left Mouth Corner)
"""

import os
import cv2
import time
import numpy as np
from typing import Optional, Dict, Any, List

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

class LocalFaceAnalyzer:
    """Phân tích khuôn mặt: Phát hiện nụ cười & Trạng thái thức/ngủ."""
    
    def __init__(self, model_path: Optional[str] = None):
        if not model_path:
            model_path = os.path.join(BASE_DIR, "models", "face_detection_yunet.onnx")
            
        self.model_path = model_path
        self.detector = None
        self.last_smile_time = 0.0
        self.smile_hold_seconds = 4.0 # Giữ trạng thái cười để lưu ảnh khoảnh khắc
        self.current_smile_detected = False
        
        if os.path.exists(self.model_path) and hasattr(cv2, "FaceDetectorYN"):
            try:
                self.detector = cv2.FaceDetectorYN.create(
                    model=self.model_path,
                    config="",
                    input_size=(640, 480),
                    score_threshold=0.35,
                    nms_threshold=0.3
                )
                print(f"[LocalFaceAnalyzer] Đã tải thành công YuNet từ {self.model_path}")
            except Exception as e:
                print(f"[LocalFaceAnalyzer] Lỗi khởi tạo YuNet: {e}")
        else:
            print(f"[LocalFaceAnalyzer] Cảnh báo: Không tìm thấy {self.model_path}")

    def is_ready(self) -> bool:
        return self.detector is not None

    def analyze_from_landmarks(self, frame: np.ndarray, bbox: Any = None, landmarks: Any = None, conf: float = 0.8) -> Dict[str, Any]:
        """
        Phân tích nhanh trạng thái mắt và nụ cười trực tiếp từ 5 điểm mốc (landmarks) đã phát hiện.
        Tốc độ siêu nhanh (< 0.2ms), không cần quét lại YuNet.
        """
        default_res = {
            "face_detected": True,
            "is_smiling": False,
            "smile_score": 0.0,
            "eye_status": "Không rõ",
            "is_awake": False,
            "face_box": None,
            "landmarks": None
        }
        if frame is None or landmarks is None:
            return default_res
            
        try:
            h, w = frame.shape[:2]
            if len(landmarks) >= 5:
                re = np.array(landmarks[0], dtype=np.float32)
                le = np.array(landmarks[1], dtype=np.float32)
                nt = np.array(landmarks[2], dtype=np.float32)
                rc = np.array(landmarks[3], dtype=np.float32)
                lc = np.array(landmarks[4], dtype=np.float32)
            else:
                return default_res

            if bbox is not None and len(bbox) == 4:
                # Kiểm tra định dạng bbox [x, y, w, h] hay [x1, y1, x2, y2]
                if bbox[2] > bbox[0] and bbox[3] > bbox[1] and bbox[2] > 100:
                    fx, fy, fw, fh = int(bbox[0]), int(bbox[1]), int(bbox[2] - bbox[0]), int(bbox[3] - bbox[1])
                else:
                    fx, fy, fw, fh = int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3])
            else:
                fx, fy, fw, fh = int(min(re[0], le[0]) - 20), int(min(re[1], le[1]) - 20), 80, 80

            eye_dist = float(np.linalg.norm(re - le))
            mouth_width = float(np.linalg.norm(rc - lc))
            smile_score = 0.0
            is_smiling = False

            if eye_dist > 8.0:
                ratio = mouth_width / eye_dist
                mouth_center_y = (rc[1] + lc[1]) / 2.0
                nose_mouth_dist = mouth_center_y - nt[1]
                if ratio > 0.68 and nose_mouth_dist > 4.0:
                    smile_score = min(1.0, (ratio - 0.65) / 0.25)
                    if smile_score > 0.40:
                        is_smiling = True
                        self.last_smile_time = time.time()

            eye_status = "Nhắm mắt / Ngủ"
            is_awake = False

            if is_smiling:
                is_awake = True
                eye_status = "Bé đang cười 😊"
            else:
                rad = max(8, int(eye_dist * 0.35))
                # Crop mắt phải
                rx1, rx2 = max(0, int(re[0] - rad)), min(w, int(re[0] + rad))
                ry1, ry2 = max(0, int(re[1] - rad)), min(h, int(re[1] + rad))
                r_crop = frame[ry1:ry2, rx1:rx2]
                r_lap = float(cv2.Laplacian(cv2.cvtColor(r_crop, cv2.COLOR_BGR2GRAY), cv2.CV_64F).var()) if r_crop.size > 0 else 0.0

                # Crop mắt trái
                lx1, lx2 = max(0, int(le[0] - rad)), min(w, int(le[0] + rad))
                ly1, ly2 = max(0, int(le[1] - rad)), min(h, int(le[1] + rad))
                l_crop = frame[ly1:ly2, lx1:lx2]
                l_lap = float(cv2.Laplacian(cv2.cvtColor(l_crop, cv2.COLOR_BGR2GRAY), cv2.CV_64F).var()) if l_crop.size > 0 else 0.0

                max_lap = max(r_lap, l_lap)
                # Chỉ cần 1 trong 2 mắt mở (hoặc cả 2 mắt mở) có viền mi / tròng đen rõ rệt (> 45.0) -> Báo THỨC ngay!
                if max_lap > 45.0 and conf > 0.35:
                    eye_status = "Mở mắt (Đang thức)"
                    is_awake = True
                else:
                    eye_status = "Nhắm mắt (Đang ngủ)"
                    is_awake = False

            return {
                "face_detected": True,
                "is_smiling": is_smiling,
                "smile_score": round(smile_score, 3),
                "eye_status": eye_status,
                "is_awake": is_awake,
                "face_box": [fx, fy, fx + fw, fy + fh],
                "landmarks": {
                    "right_eye": [float(re[0]), float(re[1])],
                    "left_eye": [float(le[0]), float(le[1])],
                    "nose_tip": [float(nt[0]), float(nt[1])],
                    "right_mouth": [float(rc[0]), float(rc[1])],
                    "left_mouth": [float(lc[0]), float(lc[1])]
                }
            }
        except Exception as e:
            return default_res

    def analyze_face(self, frame: np.ndarray, baby_box: Optional[List[int]] = None) -> Dict[str, Any]:
        """
        Quét khuôn mặt bé trong frame hình hoặc trong vùng baby_box.
        Trả về:
          - face_detected: bool
          - is_smiling: bool (Bé đang mỉm cười)
          - smile_score: float (0.0 - 1.0)
          - eye_status: "Mở mắt" | "Nhắm mắt / Ngủ" | "Không rõ"
          - face_box: [x1, y1, x2, y2]
          - landmarks: dict các điểm mốc
        """
        default_res = {
            "face_detected": False,
            "is_smiling": False,
            "smile_score": 0.0,
            "eye_status": "Không rõ",
            "is_awake": False,
            "face_box": None,
            "landmarks": None
        }
        
        if not self.is_ready() or frame is None:
            return default_res
            
        try:
            h, w = frame.shape[:2]
            self.detector.setInputSize((w, h))
            
            _, faces = self.detector.detect(frame)
            if faces is None or len(faces) == 0:
                return default_res
                
            # Nếu có baby_box, ưu tiên chọn khuôn mặt nằm bên trong baby_box
            best_face = None
            if baby_box:
                bx1, by1, bx2, by2 = baby_box
                for face in faces:
                    fx, fy, fw, fh = face[0:4]
                    fcx, fcy = fx + fw / 2, fy + fh / 2
                    if bx1 <= fcx <= bx2 and by1 <= fcy <= by2:
                        best_face = face
                        break
            if best_face is None:
                best_face = faces[0]
                
            fx, fy, fw, fh = [int(v) for v in best_face[0:4]]
            re = np.array([best_face[4], best_face[5]], dtype=np.float32)  # Mắt phải
            le = np.array([best_face[6], best_face[7]], dtype=np.float32)  # Mắt trái
            nt = np.array([best_face[8], best_face[9]], dtype=np.float32)  # Đỉnh mũi
            rc = np.array([best_face[10], best_face[11]], dtype=np.float32) # Khóe môi phải
            lc = np.array([best_face[12], best_face[13]], dtype=np.float32) # Khóe môi trái
            conf = float(best_face[14])
            
            lms_list = [
                [float(re[0]), float(re[1])],
                [float(le[0]), float(le[1])],
                [float(nt[0]), float(nt[1])],
                [float(rc[0]), float(rc[1])],
                [float(lc[0]), float(lc[1])]
            ]
            return self.analyze_from_landmarks(frame, bbox=[fx, fy, fw, fh], landmarks=lms_list, conf=conf)
            
        except Exception as e:
            print(f"[LocalFaceAnalyzer] Lỗi phân tích mặt: {e}")
            return default_res
