"""
local_ai_depth.py - Tái tạo không gian chiều sâu 3D từ Camera 2D
Sử dụng Depth Anything V2 Small (ONNX Runtime) để phát hiện trèo nôi, ranh giới 3D.
"""

import os
import cv2
import time
import numpy as np
from typing import Optional, Tuple, Dict, Any, List
import onnxruntime as ort

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

class LocalDepthEstimator:
    """Tái tạo không gian độ sâu 3D từ 1 camera 2D thông thường."""
    
    def __init__(self, model_path: Optional[str] = None):
        if not model_path:
            model_path = os.path.join(BASE_DIR, "models", "depth_anything_v2_small.onnx")
            
        self.model_path = model_path
        self.session = None
        self.input_name = "pixel_values"
        self.output_name = "predicted_depth"
        self.mean = np.array([0.485, 0.456, 0.406], dtype=np.float32)
        self.std = np.array([0.229, 0.224, 0.225], dtype=np.float32)
        
        # Target size divisible by 14
        self.infer_width = 518
        self.infer_height = 392
        
        if os.path.exists(self.model_path):
            try:
                opts = ort.SessionOptions()
                opts.intra_op_num_threads = 2
                opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
                self.session = ort.InferenceSession(self.model_path, sess_options=opts)
                print(f"[LocalDepthEstimator] Đã tải thành công Depth Anything V2 từ {self.model_path}")
            except Exception as e:
                print(f"[LocalDepthEstimator] Lỗi tải Depth Anything V2: {e}")
        else:
            print(f"[LocalDepthEstimator] Cảnh báo: Không tìm thấy {self.model_path}")

    def is_ready(self) -> bool:
        return self.session is not None

    def estimate_depth(self, frame: np.ndarray) -> Optional[np.ndarray]:
        """
        Dự đoán bản đồ độ sâu Z cho frame hình (giá trị chuẩn hóa 0.0 - 1.0).
        Càng gần camera giá trị càng lớn (1.0 = gần, 0.0 = xa).
        """
        if not self.is_ready() or frame is None:
            return None
            
        try:
            orig_h, orig_w = frame.shape[:2]
            # Resize về kích thước chuẩn chia hết cho 14
            resized = cv2.resize(frame, (self.infer_width, self.infer_height))
            rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
            norm = (rgb - self.mean) / self.std
            tensor_in = norm.transpose(2, 0, 1)[np.newaxis, ...].astype(np.float32)
            
            outputs = self.session.run([self.output_name], {self.input_name: tensor_in})
            depth_map = outputs[0][0] # (392, 518)
            
            # Chuẩn hóa về dải [0, 1]
            d_min = np.min(depth_map)
            d_max = np.max(depth_map)
            if d_max > d_min:
                depth_norm = (depth_map - d_min) / (d_max - d_min)
            else:
                depth_norm = np.zeros_like(depth_map)
                
            # Resize lại kích thước gốc của frame
            depth_full = cv2.resize(depth_norm, (orig_w, orig_h), interpolation=cv2.INTER_LINEAR)
            return depth_full
            
        except Exception as e:
            print(f"[LocalDepthEstimator] Lỗi tính bản đồ độ sâu: {e}")
            return None

    def check_climbing_risk_3d(self, depth_map: np.ndarray, baby_box: List[int], crib_box: Optional[List[int]]) -> Dict[str, Any]:
        """
        Kiểm tra nguy cơ trèo ngã theo không gian 3D.
        So sánh độ cao / khoảng cách Z của phần đầu/ngực bé so với mặt nôi.
        """
        if depth_map is None or not baby_box:
            return {"is_climbing": False, "elevation_score": 0.0, "reason": "Chưa có dữ liệu độ sâu"}
            
        bx1, by1, bx2, by2 = baby_box
        # Vùng nửa trên cơ thể bé (đầu, vai, tay bám)
        upper_h = max(10, int((by2 - by1) * 0.4))
        upper_box = depth_map[max(0, by1):min(depth_map.shape[0], by1 + upper_h), max(0, bx1):min(depth_map.shape[1], bx2)]
        
        if upper_box.size == 0:
            return {"is_climbing": False, "elevation_score": 0.0, "reason": "Vùng cơ thể ngoài khung hình"}
            
        baby_z = float(np.mean(upper_box))
        
        # Nếu có box nôi, so sánh với độ sâu nền nôi
        if crib_box:
            cx1, cy1, cx2, cy2 = crib_box
            crib_floor = depth_map[max(0, cy1):min(depth_map.shape[0], cy2), max(0, cx1):min(depth_map.shape[1], cx2)]
            floor_z = float(np.median(crib_floor)) if crib_floor.size > 0 else 0.5
            diff_z = baby_z - floor_z
        else:
            diff_z = baby_z - 0.5
            
        # Nếu phần trên của bé nhô cao đột biến về phía camera (diff_z > 0.28)
        is_climbing = diff_z > 0.28
        
        return {
            "is_climbing": is_climbing,
            "elevation_score": round(diff_z, 3),
            "baby_z": round(baby_z, 3),
            "reason": "Bé nhổm cao vượt thành nôi (nguy cơ ngã 3D)" if is_climbing else "An toàn trong lòng nôi"
        }
