"""
local_ai_crib.py - Bộ nhận diện Nôi, Ba Mẹ & Vật dụng xung quanh Bé
Sử dụng YOLOv8 Object Detection (yolov8n.pt) chạy trực tiếp trên Apple Metal GPU / CPU.
"""

import os
import time
import numpy as np
from typing import Optional, Dict, Any, List
from ultralytics import YOLO

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

class LocalCribDetector:
    """Nhận diện Nôi (class 57: bed), Người lớn (class 0: person), Thú cưng, Bình sữa."""
    
    def __init__(self, model_path: Optional[str] = None, device: str = "auto"):
        if not model_path:
            model_path = os.path.join(BASE_DIR, "models", "yolov8n.pt")
        
        self.model_path = model_path
        self.device = device
        self.model = None
        self.last_detection_time = 0.0
        self.last_results = {
            "crib_found": False,
            "crib_box": None,          # [x1, y1, x2, y2]
            "crib_conf": 0.0,
            "adults_near": [],         # danh sách box người lớn
            "pets_near": [],           # chó/mèo gần nôi
            "detected_objects": []
        }
        
        if os.path.exists(self.model_path):
            try:
                self.model = YOLO(self.model_path)
                print(f"[LocalCribDetector] Đã tải thành công YOLOv8 Object Detection từ {self.model_path}")
            except Exception as e:
                print(f"[LocalCribDetector] Lỗi khởi tạo YOLOv8: {e}")
        else:
            print(f"[LocalCribDetector] Cảnh báo: Không tìm thấy file model {self.model_path}")

    def is_ready(self) -> bool:
        return self.model is not None

    def detect_crib_and_objects(self, frame: np.ndarray, min_conf: float = 0.25) -> Dict[str, Any]:
        """
        Quét frame hình để tìm Nôi và các đối tượng liên quan.
        COCO Classes:
          0: person
          15: cat, 16: dog
          39: bottle
          57: bed (giường / nôi)
        """
        if not self.is_ready() or frame is None:
            return self.last_results
            
        try:
            h, w = frame.shape[:2]
            results = self.model.predict(
                frame, 
                classes=[0, 15, 16, 39, 57], 
                conf=min_conf, 
                verbose=False,
                device="mps" if self.device == "auto" else self.device
            )
            
            best_crib_box = None
            best_crib_conf = 0.0
            adults = []
            pets = []
            objects = []
            
            if results and len(results) > 0:
                boxes = results[0].boxes
                for box in boxes:
                    cls_id = int(box.cls[0].item())
                    conf = float(box.conf[0].item())
                    xyxy = box.xyxy[0].cpu().numpy().tolist()
                    x1, y1, x2, y2 = [int(v) for v in xyxy]
                    
                    obj_info = {
                        "class_id": cls_id,
                        "conf": round(conf, 3),
                        "box": [x1, y1, x2, y2]
                    }
                    
                    if cls_id == 57: # bed (nôi / giường)
                        obj_info["name"] = "Nôi / Giường"
                        # Chọn box nôi có độ tự tin cao nhất và diện tích hợp lý
                        area = (x2 - x1) * (y2 - y1)
                        if area > (w * h * 0.05) and conf > best_crib_conf:
                            best_crib_conf = conf
                            best_crib_box = [x1, y1, x2, y2]
                    elif cls_id == 0: # person
                        obj_info["name"] = "Người"
                        adults.append([x1, y1, x2, y2])
                    elif cls_id in (15, 16): # thú cưng
                        obj_info["name"] = "Thú cưng"
                        pets.append([x1, y1, x2, y2])
                    elif cls_id == 39: # bình sữa
                        obj_info["name"] = "Bình sữa"
                        
                    objects.append(obj_info)
                    
            self.last_results = {
                "crib_found": best_crib_box is not None,
                "crib_box": best_crib_box,
                "crib_conf": round(best_crib_conf, 3),
                "adults_near": adults,
                "pets_near": pets,
                "detected_objects": objects,
                "timestamp": time.time()
            }
            self.last_detection_time = time.time()
            return self.last_results
            
        except Exception as e:
            print(f"[LocalCribDetector] Lỗi quét nôi/vật thể: {e}")
            return self.last_results
