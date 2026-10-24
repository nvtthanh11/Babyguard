import os
import time
import queue
import threading
import numpy as np
import sounddevice as sd
from scipy.signal import butter, sosfilt

try:
    from ai_edge_litert.interpreter import Interpreter
except ImportError:
    try:
        from tensorflow.lite.python.interpreter import Interpreter
    except ImportError:
        import tflite_runtime.interpreter as tflite
        Interpreter = tflite.Interpreter

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


class AudioCryDetector:
    def __init__(self, model_path: str, device_index: int = None, sample_rate: int = 16000, 
                 cry_threshold: float = 0.30, cough_threshold: float = 0.25,
                 on_cry_callback=None, on_cough_callback=None, audio_callback=None,
                 cry_alert_enabled: bool = True, cough_alert_enabled: bool = True):
        self.model_path = model_path
        self.sample_rate = sample_rate
        self.cry_threshold = cry_threshold
        self.cough_threshold = cough_threshold
        self.on_cry_callback = on_cry_callback
        self.on_cough_callback = on_cough_callback
        self.audio_callback = audio_callback
        self.device_index = device_index
        self.cry_alert_enabled = cry_alert_enabled
        self.cough_alert_enabled = cough_alert_enabled
        
        # Audio buffer (holds 15600 samples = ~0.975s for YAMNet)
        self.buffer_size = 15600
        self.audio_buffer = np.zeros(self.buffer_size, dtype=np.float32)
        self.lock = threading.Lock()
        
        # Bộ lọc thông dải Butterworth bậc 4 [250 Hz - 3800 Hz]:
        # Loại bỏ hoàn toàn tiếng ù quạt máy / điều hòa (< 200 Hz) và nhiễu tần số cao
        self.bp_sos = butter(4, [250.0, 3800.0], btype="bandpass", fs=self.sample_rate, output="sos")
        
        # Status variables
        self.current_volume = 0.0
        self.raw_cry_probability = 0.0
        self.cry_probability = 0.0
        self.cough_probability = 0.0
        self.cry_consecutive_frames = 0
        self.top_sound_label = "Yên tĩnh"
        self.is_running = False
        self.stream = None
        self.worker_thread = None
        
        # Target classes in YAMNet (0-indexed)
        # 11: Screaming, 19: Crying, sobbing, 20: Baby cry, infant cry, 21: Whimper, 22: Wail, moan
        self.target_classes = [11, 19, 20, 21, 22]
        # 39: Gasp, 42: Cough, 43: Throat clearing
        self.cough_classes = [39, 42, 43]
        # Speech & vocal classes (tiếng người lớn nói chuyện, dỗ bé)
        self.speech_classes = [0, 1, 2, 3, 5, 65]
        # Laughter / Giggle / Baby laughter (13, 14, 15, 16)
        self.laughter_classes = [13, 14, 15, 16]
        # Music / Lullaby / Singing (24, 25, 132, 133)
        self.music_classes = [24, 25, 132, 133]
        
        # Load YAMNet labels
        self.labels = self._load_labels()
        
        # Initialize TFLite Interpreter
        self.interpreter = Interpreter(model_path=self.model_path)
        self.interpreter.allocate_tensors()
        self.input_details = self.interpreter.get_input_details()
        self.output_details = self.interpreter.get_output_details()

    def _load_labels(self):
        try:
            csv_path = os.path.join(BASE_DIR, "models", "yamnet_class_map.csv")
            with open(csv_path) as f:
                import csv
                return [r["display_name"] for r in csv.DictReader(f)]
        except Exception:
            return ["Sound"] * 521

    def _audio_callback(self, indata, frames, time_info, status):
        """Called by sounddevice for each chunk of incoming microphone audio."""
        if status:
            pass
        # Calculate instant volume (RMS)
        audio_mono = indata[:, 0] if indata.ndim > 1 else indata
        rms = float(np.sqrt(np.mean(audio_mono ** 2)))
        
        with self.lock:
            self.current_volume = rms
            # Shift buffer left and append new samples
            n = len(audio_mono)
            if n >= self.buffer_size:
                self.audio_buffer = audio_mono[-self.buffer_size:].astype(np.float32)
            else:
                self.audio_buffer = np.roll(self.audio_buffer, -n)
                self.audio_buffer[-n:] = audio_mono.astype(np.float32)

            # Phát âm thanh thời gian thực (16-bit PCM) cho người nghe qua Web
            if getattr(self, "audio_subscribers", None):
                pcm_bytes = (np.clip(audio_mono, -1.0, 1.0) * 32767).astype(np.int16).tobytes()
                for q in self.audio_subscribers:
                    if not q.full():
                        q.put_nowait(pcm_bytes)

        if self.audio_callback:
            self.audio_callback(audio_mono)

    def subscribe_audio(self):
        """Đăng ký kênh nhận luồng âm thanh phòng bé thời gian thực."""
        q = queue.Queue(maxsize=100)
        with self.lock:
            if not hasattr(self, "audio_subscribers"):
                self.audio_subscribers = []
            self.audio_subscribers.append(q)
        return q

    def unsubscribe_audio(self, q):
        """Hủy đăng ký nhận luồng âm thanh."""
        with self.lock:
            if hasattr(self, "audio_subscribers") and q in self.audio_subscribers:
                self.audio_subscribers.remove(q)

    @staticmethod
    def _calibrate_cry(raw_score: float) -> float:
        """Chuẩn hóa xác suất khóc của trẻ từ đầu ra sigmoid của YAMNet:
        - raw <= 0.10: Nhiễu nền phòng / tiếng nói chuyện nhẹ / tiếng thở dài -> Khóa cứng 0%
        - 0.10 -> 0.20: Bé cựa mình / rên nhẹ -> 5% -> 25% (dưới ngưỡng báo động 30%)
        - 0.20 -> 0.35: Bé bắt đầu khóc / khóc rõ -> 30% -> 75%
        - >= 0.35: Bé khóc to / gào thét -> 75% -> 100%
        """
        if raw_score <= 0.10:
            return 0.0
        elif raw_score <= 0.20:
            return 0.05 + (raw_score - 0.10) / 0.10 * 0.20
        elif raw_score <= 0.35:
            return 0.30 + (raw_score - 0.20) / 0.15 * 0.45
        else:
            return min(1.0, 0.75 + (raw_score - 0.35) * 0.8)

    @staticmethod
    def _calibrate_cough(raw_score: float) -> float:
        if raw_score <= 0.08:
            return 0.0
        elif raw_score <= 0.25:
            return (raw_score - 0.08) / 0.17 * 0.70
        else:
            return min(1.0, 0.70 + (raw_score - 0.25) * 1.0)

    def _inference_loop(self):
        """Background thread running YAMNet inference 2 times per second with DSP Bandpass & Envelope Follower."""
        while self.is_running:
            start_time = time.time()
            with self.lock:
                waveform = self.audio_buffer.copy()

            # Lọc thông dải [250Hz - 3800Hz] loại bỏ tiếng quạt / điều hòa tần số thấp
            try:
                filtered_wave = sosfilt(self.bp_sos, waveform).astype(np.float32)
            except Exception:
                filtered_wave = waveform

            # Đo độ lớn âm thanh thực tế trên dải tần giọng người/trẻ sơ sinh
            vol = float(np.sqrt(np.mean(filtered_wave ** 2)))
            self.current_volume = vol

            # Chỉ chạy inference khi năng lượng âm thanh vượt ngưỡng nền yên tĩnh
            if vol > 0.0045:
                try:
                    self.interpreter.set_tensor(self.input_details[0]["index"], waveform)
                    self.interpreter.invoke()
                    scores = self.interpreter.get_tensor(self.output_details[0]["index"])[0]

                    # Điểm số thô của các nhóm âm thanh trong phòng ngủ
                    raw_cry = float(max(scores[c] for c in self.target_classes))
                    infant_cry = float(scores[20])  # YAMNet class 20: Baby cry, infant cry
                    raw_cough = float(max(scores[c] for c in self.cough_classes))
                    raw_speech = float(max(scores[c] for c in self.speech_classes))
                    raw_laugh = float(max(scores[c] for c in self.laughter_classes))
                    raw_music = float(max(scores[c] for c in self.music_classes))

                    self.raw_cry_probability = raw_cry

                    # BỘ LỌC CHỐNG BÁO ĐỘNG GIẢ TIẾNG NGƯỜI LỚN NÓI CHUYỆN:
                    # Khi người lớn trò chuyện, YAMNet thường rò rỉ nhẹ sang class 21 (Whimper) hoặc 22 (Wail) ~ 0.12 - 0.16.
                    # Nếu tiếng nói rõ ràng (raw_speech >= 0.20) và lớn hơn hoặc xấp xỉ tiếng khóc, đồng thời không có infant_cry đặc hiệu:
                    is_adult_speech = (raw_speech >= 0.20) and (raw_speech >= raw_cry * 0.90) and (infant_cry < 0.12)

                    if is_adult_speech:
                        cal_cry = 0.0
                        self.cry_consecutive_frames = 0
                        self.cry_probability = max(0.0, self.cry_probability - 0.08)
                    else:
                        cal_cry = self._calibrate_cry(raw_cry)
                        if cal_cry >= self.cry_threshold or infant_cry >= 0.12:
                            self.cry_consecutive_frames += 1
                        else:
                            self.cry_consecutive_frames = max(0, self.cry_consecutive_frames - 1)

                    cal_cough = self._calibrate_cough(raw_cough)

                    # --- PEAK-HOLD ENVELOPE FOLLOWER ---
                    if cal_cry > self.cry_probability:
                        self.cry_probability = 0.80 * cal_cry + 0.20 * self.cry_probability
                    else:
                        self.cry_probability = max(0.0, self.cry_probability - 0.06)
                        if self.cry_probability < 0.05:
                            self.cry_probability = 0.0

                    if cal_cough > self.cough_probability:
                        self.cough_probability = 0.85 * cal_cough + 0.15 * self.cough_probability
                    else:
                        self.cough_probability = max(0.0, self.cough_probability - 0.05)
                        if self.cough_probability < 0.05:
                            self.cough_probability = 0.0

                    # --- GÁN NHÃN ÂM THANH PHÒNG NGỦ CHÍNH XÁC ---
                    if is_adult_speech:
                        top_label = "Tiếng trò chuyện"
                    elif self.cry_probability >= self.cry_threshold and self.cry_consecutive_frames >= 2:
                        top_label = "Bé đang khóc" if (raw_cry >= 0.25 or infant_cry >= 0.15) else "Bé khóc thút thít"
                    elif self.cough_probability >= 0.30 or raw_cough >= 0.20:
                        top_label = "Tiếng thở gấp" if scores[39] >= 0.20 else "Tiếng ho / sặc"
                    elif raw_laugh >= 0.25:
                        top_label = "Tiếng bé cười"
                    elif raw_speech >= 0.22:
                        top_label = "Tiếng trò chuyện"
                    elif raw_music >= 0.25:
                        top_label = "Nhạc ru ngủ"
                    elif vol < 0.012:
                        top_label = "Yên tĩnh"
                    else:
                        top_label = "Tiếng động nhẹ trong phòng"

                    self.top_sound_label = top_label

                    # Kích hoạt callback cảnh báo khi tiếng khóc DUY TRÌ LIÊN TỤC >= 2 FRAME (>= 1.0 giây)
                    if self.cry_alert_enabled and self.cry_probability >= self.cry_threshold and self.cry_consecutive_frames >= 2 and self.on_cry_callback:
                        self.on_cry_callback(self.cry_probability, vol, top_label)

                    if self.cough_alert_enabled and self.cough_probability >= self.cough_threshold and self.on_cough_callback:
                        self.on_cough_callback(self.cough_probability, vol, top_label)

                except Exception as e:
                    print(f"[AudioDetector] Inference error: {e}")
            else:
                self.cry_consecutive_frames = 0
                self.cry_probability = max(0.0, self.cry_probability - 0.05)
                self.cough_probability = max(0.0, self.cough_probability - 0.05)
                self.top_sound_label = "Yên tĩnh"

            # Sleep remaining time to maintain ~2Hz frequency
            elapsed = time.time() - start_time
            time.sleep(max(0.1, 0.5 - elapsed))

    def start(self):
        if self.is_running:
            return
        self.is_running = True
        
        # Determine audio device index if not explicitly passed
        device = self.device_index
        if device is None:
            # Auto-detect Brio 100
            for idx, dev in enumerate(sd.query_devices()):
                if "Brio" in dev["name"] and dev["max_input_channels"] > 0:
                    device = idx
                    break

        print(f"[AudioDetector] Starting audio stream on device {device} at {self.sample_rate}Hz...")
        self.stream = sd.InputStream(
            device=device,
            channels=1,
            samplerate=self.sample_rate,
            blocksize=int(self.sample_rate * 0.2), # 200ms blocks
            callback=self._audio_callback
        )
        self.stream.start()

        self.worker_thread = threading.Thread(target=self._inference_loop, daemon=True)
        self.worker_thread.start()
        print("[AudioDetector] Audio detector started.")

    def stop(self):
        self.is_running = False
        if self.stream:
            self.stream.stop()
            self.stream.close()
        print("[AudioDetector] Audio detector stopped.")

    def switch_device(self, new_device_index: int):
        """Đổi nóng cổng Micro thu âm ngay lập tức."""
        if new_device_index == self.device_index:
            return
        try:
            print(f"[AudioDetector] 🔄 Chuyển cổng Micro sang thiết bị số {new_device_index}...")
            if self.stream:
                try:
                    self.stream.stop()
                    self.stream.close()
                except Exception:
                    pass
            self.device_index = int(new_device_index)
            self.stream = sd.InputStream(
                device=self.device_index,
                channels=1,
                samplerate=self.sample_rate,
                blocksize=int(self.sample_rate * 0.2),
                callback=self._audio_callback
            )
            self.stream.start()
            print(f"[AudioDetector] ✅ Đã kết nối Micro số {self.device_index} thành công!")
        except Exception as e:
            print(f"[AudioDetector] ⚠️ Lỗi chuyển cổng Micro ({new_device_index}): {e}")

    def get_status(self):
        return {
            "volume": round(self.current_volume * 100, 1),
            "cry_probability": round(self.cry_probability * 100, 1),
            "is_crying": bool(self.cry_probability >= self.cry_threshold and getattr(self, "cry_consecutive_frames", 0) >= 2),
            "cough_probability": round(self.cough_probability * 100, 1),
            "is_coughing": self.cough_probability >= self.cough_threshold,
            "top_sound": self.top_sound_label
        }
