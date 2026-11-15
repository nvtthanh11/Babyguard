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
            
            # 1. Tính toán nụ cười qua tỷ số hình học
            eye_dist = np.linalg.norm(re - le)
            mouth_width = np.linalg.norm(rc - lc)
            
            smile_score = 0.0
            is_smiling = False
            
            if eye_dist > 10.0:
                # Tỷ số độ rộng miệng so với khoảng cách 2 mắt
                # Trẻ sơ sinh bình thường: 0.50 - 0.60; khi cười kéo khóe môi sang 2 bên: > 0.72
                ratio = mouth_width / eye_dist
                # Kiểm tra góc nâng khóe môi so với mũi (khi cười khóe môi nâng lên)
                mouth_center_y = (rc[1] + lc[1]) / 2.0
                nose_mouth_dist = mouth_center_y - nt[1]
                
                if ratio > 0.68 and nose_mouth_dist > 5.0:
                    smile_score = min(1.0, (ratio - 0.65) / 0.25)
                    if smile_score > 0.45:
                        is_smiling = True
                        self.last_smile_time = time.time()
                        
            # 2. Phân tích trạng thái mắt (EAR & độ tương phản vùng mắt)
            # Crop vùng mắt để kiểm tra độ sáng & chuyển động
            eye_status = "Nhắm mắt / Ngủ"
            is_awake = False
            
            # Nếu phát hiện nụ cười rõ ràng -> bé đang thức hoặc cười trong mơ
            if is_smiling:
                is_awake = True
                eye_status = "Bé đang cười"
            else:
                # Kiểm tra diện tích mắt
                eye_y = int((re[1] + le[1]) / 2)
                eye_x1 = max(0, int(min(re[0], le[0]) - eye_dist * 0.2))
                eye_x2 = min(w, int(max(re[0], le[0]) + eye_dist * 0.2))
                eye_crop_h = max(6, int(eye_dist * 0.35))
                eye_crop = frame[max(0, eye_y - eye_crop_h):min(h, eye_y + eye_crop_h), eye_x1:eye_x2]
                
                if eye_crop.size > 0:
                    gray_eye = cv2.cvtColor(eye_crop, cv2.COLOR_BGR2GRAY)
                    # Tính độ sắc nét / độ biến thiên Laplacian vùng mắt
                    lap_var = cv2.Laplacian(gray_eye, cv2.CV_64F).var()
                    # Mắt mở có tròng đen, viền mi rõ -> Laplacian var cao (> 45)
                    if lap_var > 55.0 and conf > 0.5:
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
            print(f"[LocalFaceAnalyzer] Lỗi phân tích mặt: {e}")
            return default_res
