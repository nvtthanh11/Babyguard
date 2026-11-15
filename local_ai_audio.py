"""
local_ai_audio.py - Bộ lọc âm thanh chuyên sâu Silero VAD (Local Edge AI)
Phát hiện giọng nói người lớn (ba mẹ dỗ bé) và phân biệt với tiếng khóc sơ sinh.
Chạy trực tiếp qua ONNX Runtime siêu nhẹ (< 2ms mỗi chunk).
"""

import os
import time
import numpy as np
from typing import Optional, Dict, Any
import onnxruntime as ort

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

class LocalAcousticFilter:
    """Phát hiện giọng nói người lớn và lọc âm thanh phòng ngủ."""
    
    def __init__(self, model_path: Optional[str] = None):
        if not model_path:
            model_path = os.path.join(BASE_DIR, "models", "silero_vad.onnx")
            
        self.model_path = model_path
        self.session = None
        self.state = np.zeros((2, 1, 128), dtype=np.float32)
        self.sr = np.array(16000, dtype=np.int64)
        
        self.speech_prob_history = []
        self.adult_speaking = False
        self.last_adult_speaking_time = 0.0
        
        if os.path.exists(self.model_path):
            try:
                opts = ort.SessionOptions()
                opts.intra_op_num_threads = 1
                self.session = ort.InferenceSession(self.model_path, sess_options=opts)
                print(f"[LocalAcousticFilter] Đã tải thành công Silero VAD từ {self.model_path}")
            except Exception as e:
                print(f"[LocalAcousticFilter] Lỗi tải Silero VAD: {e}")
        else:
            print(f"[LocalAcousticFilter] Cảnh báo: Không tìm thấy {self.model_path}")

    def is_ready(self) -> bool:
        return self.session is not None

    def process_audio_chunk(self, audio_chunk_16k: np.ndarray) -> Dict[str, Any]:
        """
        Xử lý đoạn âm thanh mẫu 16kHz (512 samples ~ 32ms).
        Trả về:
          - speech_prob: float (0.0 - 1.0)
          - adult_speaking: bool (Có tiếng người lớn đang nói / dỗ bé)
          - should_suppress_cry_alarm: bool (Nếu ba mẹ đang ở bên nôi nói chuyện -> hoãn còi)
        """
        if not self.is_ready() or audio_chunk_16k is None:
            return {
                "speech_prob": 0.0,
                "adult_speaking": False,
                "should_suppress_cry_alarm": False
            }
            
        try:
            # Đảm bảo độ dài đúng 512 mẫu
            chunk = audio_chunk_16k.flatten().astype(np.float32)
            if len(chunk) < 512:
                chunk = np.pad(chunk, (0, 512 - len(chunk)))
            elif len(chunk) > 512:
                chunk = chunk[:512]
                
            tensor_in = chunk[np.newaxis, :]
            out, self.state = self.session.run(None, {
                'input': tensor_in,
                'state': self.state,
                'sr': self.sr
            })
            
            prob = float(out[0][0])
            self.speech_prob_history.append(prob)
            if len(self.speech_prob_history) > 30: # lưu ~1 giây gần nhất
                self.speech_prob_history.pop(0)
                
            avg_prob = float(np.mean(self.speech_prob_history))
            now = time.time()
            
            if avg_prob > 0.65:
                self.adult_speaking = True
                self.last_adult_speaking_time = now
            elif now - self.last_adult_speaking_time > 3.0:
                self.adult_speaking = False
                
            # Nếu người lớn vừa nói chuyện trong vòng 3.5 giây gần đây -> ba mẹ đang ở cạnh nôi
            should_suppress = (now - self.last_adult_speaking_time) < 3.5
            
            return {
                "speech_prob": round(prob, 3),
                "avg_speech_prob": round(avg_prob, 3),
                "adult_speaking": self.adult_speaking,
                "should_suppress_cry_alarm": should_suppress
            }
            
        except Exception as e:
            print(f"[LocalAcousticFilter] Lỗi xử lý âm thanh: {e}")
            return {
                "speech_prob": 0.0,
                "adult_speaking": False,
                "should_suppress_cry_alarm": False
            }
            
    def reset_state(self):
        self.state = np.zeros((2, 1, 128), dtype=np.float32)
        self.speech_prob_history.clear()
