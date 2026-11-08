import os
import time
import queue
import threading
from collections import deque
import numpy as np
import sounddevice as sd
from scipy.signal import butter, sosfilt

try:
    from ai_edge_litert.interpreter import Interpreter
except ImportError:
    try:
        from tensorflow.lite.python.interpreter import Interpreter
    except ImportError:
        try:
            import tflite_runtime.interpreter as tflite
            Interpreter = tflite.Interpreter
        except ImportError:
            Interpreter = None

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


class AudioCryDetector:
    def __init__(self, model_path: str, device_index: int = None, sample_rate: int = 16000, 
                 cry_threshold: float = 0.30, cough_threshold: float = 0.25, choke_threshold: float = 0.20,
                 on_cry_callback=None, on_cough_callback=None, on_choke_callback=None, on_whimper_callback=None, audio_callback=None,
                 cry_alert_enabled: bool = True, cough_alert_enabled: bool = True, choke_alert_enabled: bool = True):
        self.model_path = model_path
        self.sample_rate = sample_rate
        self.cry_threshold = cry_threshold
        self.cough_threshold = cough_threshold
        self.choke_threshold = choke_threshold
        self.on_cry_callback = on_cry_callback
        self.on_cough_callback = on_cough_callback
        self.on_choke_callback = on_choke_callback
        self.on_whimper_callback = on_whimper_callback
        self.audio_callback = audio_callback
        self.device_index = device_index
        self.cry_alert_enabled = cry_alert_enabled
        self.cough_alert_enabled = cough_alert_enabled
        self.choke_alert_enabled = choke_alert_enabled
        
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
        self.choke_probability = 0.0
        self.cry_consecutive_frames = 0
        self.top_sound_label = "Yên tĩnh"
        self.is_running = False
        self.stream = None
        self.worker_thread = None

        # --- BỘ TÍCH LŨY ÂM HỌC & PHÂN BIỆT Ọ Ẹ VS KHÓC (Acoustic Temporal Accumulator) ---
        # Ngưỡng thời gian tối thiểu (giây) khóc liên tục để loại trừ hoàn toàn các tiếng ọ ẹ sinh lý 1-2 tiếng
        self.min_sustained_cry_seconds = 4.0
        self.cry_start_time = None
        self.continuous_cry_seconds = 0.0
        self.last_sound_active_time = 0.0
        self.last_cry_callback_trigger_time = 0.0
        self.last_cough_callback_time = 0.0
        self.last_choke_callback_time = 0.0
        self.whimper_history = deque(maxlen=30)         # Lưu timestamp các lần ọ ẹ ngắn (< 4s) trong 60s
        self.acoustic_sliding_window = deque(maxlen=24) # Bộ đệm 12 giây gần nhất (@ 2Hz) để tính duty-cycle & xu hướng âm lượng
        self.acoustic_event_log = deque(maxlen=40)      # Nhật ký tiến trình âm thanh gần nhất chuyển cho Gemini thẩm định
        
        # Target classes in YAMNet (0-indexed)
        # 11: Screaming, 19: Crying, sobbing, 20: Baby cry, infant cry, 21: Whimper, 22: Wail, moan
        self.target_classes = [11, 19, 20, 21, 22]
        # Nhóm Ho & Viêm Họng: 42: Cough, 43: Throat clearing, 37: Wheeze
        self.cough_classes = [42, 43, 37]
        # Nhóm Sặc Sữa & Nguy Cơ Ngạt: Chỉ giữ class 39 (Gasp - thở hắt/ngộp thở); loại bỏ 34 (Grunt) và 41 (Snort) về nhóm sinh lý
        self.choke_classes = [39]
        self.physiological_classes = [34, 41]
        # Speech & vocal classes (tiếng người lớn nói chuyện, dỗ bé)
        self.speech_classes = [0, 1, 2, 3, 5, 65]
        # Laughter / Giggle / Baby laughter (13, 14, 15, 16)
        self.laughter_classes = [13, 14, 15, 16]
        # Music / Lullaby / Singing (24, 25, 132, 133)
        self.music_classes = [24, 25, 132, 133]
        
        # Load YAMNet labels
        self.labels = self._load_labels()
        
        # Initialize TFLite Interpreter
        if Interpreter is not None:
            try:
                self.interpreter = Interpreter(model_path=self.model_path)
                self.interpreter.allocate_tensors()
                self.input_details = self.interpreter.get_input_details()
                self.output_details = self.interpreter.get_output_details()
            except Exception as e:
                print(f"[AudioDetector] Warning: Could not initialize TFLite model: {e}")
                self.interpreter = None
        else:
            self.interpreter = None

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
        if raw_score <= 0.035:
            return 0.0
        elif raw_score <= 0.18:
            return (raw_score - 0.035) / 0.145 * 0.70
        else:
            return min(1.0, 0.70 + (raw_score - 0.18) * 1.0)

    @staticmethod
    def _calibrate_choke(raw_score: float) -> float:
        if raw_score <= 0.035:
            return 0.0
        elif raw_score <= 0.18:
            return (raw_score - 0.035) / 0.145 * 0.70
        else:
            return min(1.0, 0.70 + (raw_score - 0.18) * 1.0)

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

            # Chỉ chạy inference khi năng lượng âm thanh vượt ngưỡng nền yên tĩnh và model đã sẵn sàng
            if vol > 0.0035 and self.interpreter is not None:
                try:
                    self.interpreter.set_tensor(self.input_details[0]["index"], waveform)
                    self.interpreter.invoke()
                    scores = self.interpreter.get_tensor(self.output_details[0]["index"])[0]

                    # Điểm số thô của các nhóm âm thanh trong phòng ngủ
                    raw_cry = float(max(scores[c] for c in self.target_classes))
                    infant_cry = float(scores[20])   # YAMNet class 20: Baby cry, infant cry
                    raw_scream = float(scores[11])   # YAMNet class 11: Screaming
                    raw_whimper = float(scores[21])  # YAMNet class 21: Whimper (tiếng ọ ẹ / khóc thút thít)
                    raw_grunt = float(max(scores[34], scores[41]))  # YAMNet class 34 (Grunt) & 41 (Snort) - âm thanh sinh lý
                    raw_cough = float(max(scores[c] for c in self.cough_classes))
                    raw_choke = float(max(scores[c] for c in self.choke_classes))
                    raw_speech = float(max(scores[c] for c in self.speech_classes))
                    raw_laugh = float(max(scores[c] for c in self.laughter_classes))
                    raw_music = float(max(scores[c] for c in self.music_classes))

                    self.raw_cry_probability = raw_cry
                    now_t = time.time()

                    # BỘ LỌC CHỐNG BÁO ĐỘNG GIẢ TIẾNG NGƯỜI LỚN NÓI CHUYỆN:
                    is_adult_speech = (raw_speech >= 0.20) and (raw_speech >= raw_cry * 0.88) and (infant_cry < 0.12)

                    if is_adult_speech:
                        cal_cry = 0.0
                        cal_cough = 0.0
                        cal_choke = 0.0
                        is_genuine_cry_sound = False
                        is_whimper_sound = False
                        self.cry_consecutive_frames = 0
                        self.continuous_cry_seconds = 0.0
                        self.cry_start_time = None
                        self.cry_probability = max(0.0, self.cry_probability - 0.08)
                        self.cough_probability = max(0.0, self.cough_probability - 0.08)
                        self.choke_probability = max(0.0, self.choke_probability - 0.08)
                    else:
                        cal_cry = self._calibrate_cry(raw_cry)
                        cal_cough = self._calibrate_cough(raw_cough)
                        cal_choke = self._calibrate_choke(raw_choke)
                        is_genuine_cry_sound = (cal_cry >= self.cry_threshold or infant_cry >= 0.14 or raw_scream >= 0.18)
                        is_whimper_sound = (raw_whimper >= 0.12 or raw_grunt >= 0.12 or (0.10 <= cal_cry < self.cry_threshold))

                        if is_genuine_cry_sound or is_whimper_sound:
                            if self.cry_start_time is None:
                                self.cry_start_time = now_t
                            self.continuous_cry_seconds = now_t - self.cry_start_time
                            self.last_sound_active_time = now_t

                            if is_genuine_cry_sound:
                                self.cry_consecutive_frames += 1
                            else:
                                self.cry_consecutive_frames = max(0, self.cry_consecutive_frames - 1)
                        else:
                            # Frame này yên tĩnh hoặc không phát hiện âm thanh khóc
                            if self.cry_start_time is not None:
                                silence_gap = now_t - self.last_sound_active_time
                                if silence_gap > 1.2:
                                    # Kết thúc chuỗi âm thanh: Đánh giá độ dài đợt âm thanh vừa qua
                                    total_sound_dur = self.last_sound_active_time - self.cry_start_time
                                    if 0.4 <= total_sound_dur < self.min_sustained_cry_seconds:
                                        # BÉ CHỈ Ọ Ẹ 1-2 TIẾNG RỒI TỰ NÍN (Sinh lý REM) -> Lưu log, tuyệt đối không báo động!
                                        self.whimper_history.append(now_t)
                                        whimper_entry = {
                                            "time": time.strftime("%H:%M:%S"),
                                            "epoch": now_t,
                                            "type": "whimper",
                                            "duration_seconds": round(total_sound_dur, 1),
                                            "volume": round(vol, 4),
                                            "peak_cry_prob": round(float(self.cry_probability), 2),
                                            "note": f"Bé ọ ẹ nhẹ {total_sound_dur:.1f}s (Cựa mình REM, tự ngủ lại)"
                                        }
                                        self.acoustic_event_log.append(whimper_entry)
                                        print(f"[AudioDetector] 👶 Bé vừa ọ ẹ nhẹ {total_sound_dur:.1f}s (Sinh lý REM, không báo động)")
                                        if self.on_whimper_callback:
                                            try:
                                                self.on_whimper_callback(whimper_entry)
                                            except Exception as we:
                                                print(f"[AudioDetector] Lỗi on_whimper_callback: {we}")
                                    self.cry_start_time = None
                                    self.continuous_cry_seconds = 0.0
                                    self.cry_consecutive_frames = 0

                    # --- BỘ TÍNH TOÁN CỬA SỔ TRƯỢT 12 GIÂY & DUTY-CYCLE & XU HƯỚNG ÂM LƯỢNG ---
                    self.acoustic_sliding_window.append({
                        "timestamp": now_t,
                        "is_cry": is_genuine_cry_sound if not is_adult_speech else False,
                        "is_whimper": is_whimper_sound if not is_adult_speech else False,
                        "vol": vol,
                        "cal_cry": cal_cry
                    })
                    cry_frames_12s = sum(1 for f in self.acoustic_sliding_window if f.get("is_cry"))
                    duty_cycle_12s = cry_frames_12s / max(1, len(self.acoustic_sliding_window))
                    whimpers_60s = sum(1 for t in self.whimper_history if (now_t - t) <= 60.0)

                    # Đánh giá xu hướng biên độ âm lượng (RMS envelope trend)
                    if len(self.acoustic_sliding_window) >= 8:
                        r_vols = [f["vol"] for f in list(self.acoustic_sliding_window)[-4:]]
                        o_vols = [f["vol"] for f in list(self.acoustic_sliding_window)[:-4]]
                        avg_r = sum(r_vols) / len(r_vols)
                        avg_o = sum(o_vols) / len(o_vols)
                        if avg_r > avg_o * 1.35 and avg_r > 0.02:
                            vol_trend = "leo thang dồn dập (escalating)"
                        elif avg_r < avg_o * 0.70:
                            vol_trend = "giảm dần / lắng dịu (decaying)"
                        else:
                            vol_trend = "ổn định (stable)"
                    else:
                        vol_trend = "khởi phát (initial)"

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

                    if cal_choke > self.choke_probability:
                        self.choke_probability = 0.85 * cal_choke + 0.15 * self.choke_probability
                    else:
                        self.choke_probability = max(0.0, self.choke_probability - 0.05)
                        if self.choke_probability < 0.05:
                            self.choke_probability = 0.0

                    # --- XÁC ĐỊNH TRẠNG THÁI & GÁN NHÃN ÂM THANH PHÒNG NGỦ CHÍNH XÁC ---
                    is_sustained_crying = (self.continuous_cry_seconds >= self.min_sustained_cry_seconds) or (duty_cycle_12s >= 0.50 and self.continuous_cry_seconds >= 3.0)

                    if is_adult_speech:
                        top_label = "Tiếng trò chuyện"
                    elif is_sustained_crying:
                        top_label = "Bé đang khóc dồn dập" if (vol >= 0.025 or infant_cry >= 0.18 or raw_scream >= 0.20) else "Bé khóc thút thít dai dẳng"
                    elif self.continuous_cry_seconds > 0.0:
                        top_label = f"Bé ọ ẹ / cựa mình ({self.continuous_cry_seconds:.1f}s)"
                    elif raw_whimper >= 0.12 or raw_grunt >= 0.12:
                        top_label = "Bé ọ ẹ / rặn sinh lý"
                    elif self.choke_probability >= self.choke_threshold or raw_choke >= 0.16:
                        if scores[39] >= 0.10:
                            top_label = "Tiếng thở hắt / sặc sữa"
                        elif scores[41] >= 0.12:
                            top_label = "Tiếng khụt khịt / sữa lên mũi"
                        else:
                            top_label = "Tiếng rặn ọ ẹ / khó chịu"
                    elif self.cough_probability >= self.cough_threshold or raw_cough >= 0.16:
                        if scores[43] >= 0.12:
                            top_label = "Tiếng khẹc họng vướng sữa"
                        elif scores[37] >= 0.15:
                            top_label = "Tiếng thở khò khè / rít"
                        else:
                            top_label = "Tiếng ho của bé"
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

                    # --- KÍCH HOẠT CALLBACK THẨM ĐỊNH TIẾNG KHÓC ---
                    # Chỉ kích hoạt khi thỏa mãn tính liên tục / chu kỳ dồn dập (loại bỏ dứt điểm tiếng ọ ẹ 1-2 tiếng)
                    if self.cry_alert_enabled and is_sustained_crying and self.cry_probability >= self.cry_threshold and self.on_cry_callback:
                        if (now_t - self.last_cry_callback_trigger_time) >= 15.0:
                            self.last_cry_callback_trigger_time = now_t
                            cry_telemetry = {
                                "cry_probability": round(float(self.cry_probability), 3),
                                "raw_cry": round(float(raw_cry), 3),
                                "infant_cry": round(float(infant_cry), 3),
                                "whimper_score": round(float(raw_whimper), 3),
                                "grunt_score": round(float(raw_grunt), 3),
                                "volume": round(float(vol), 4),
                                "volume_pct": round(float(vol * 100), 1),
                                "continuous_seconds": round(float(self.continuous_cry_seconds), 1),
                                "duty_cycle_12s": round(float(duty_cycle_12s * 100), 1),
                                "recent_whimpers_60s": int(whimpers_60s),
                                "volume_trend": vol_trend,
                                "top_label": top_label,
                                "summary": f"Khóc duy trì {self.continuous_cry_seconds:.1f}s, chu kỳ {duty_cycle_12s*100:.0f}%, âm lượng {vol*100:.1f}% ({vol_trend}), {whimpers_60s} lần ọ ẹ trong 60s"
                            }
                            self.acoustic_event_log.append({
                                "time": time.strftime("%H:%M:%S"),
                                "epoch": now_t,
                                "type": "cry_sustained",
                                "duration_seconds": round(float(self.continuous_cry_seconds), 1),
                                "volume": round(float(vol), 4),
                                "note": top_label
                            })
                            # Chuyển đầy đủ dữ liệu âm học cho bộ điều phối thẩm định
                            try:
                                self.on_cry_callback(cry_telemetry)
                            except TypeError:
                                # Tương thích ngược nếu callback cũ nhận (prob, vol, label)
                                self.on_cry_callback(self.cry_probability, vol, top_label)

                    if self.cough_alert_enabled and self.cough_probability >= self.cough_threshold and self.on_cough_callback:
                        if (now_t - self.last_cough_callback_time) >= 20.0:
                            self.last_cough_callback_time = now_t
                            self.on_cough_callback(self.cough_probability, vol, top_label)

                    if self.choke_alert_enabled and self.choke_probability >= self.choke_threshold and self.on_choke_callback:
                        if (now_t - self.last_choke_callback_time) >= 30.0:
                            self.last_choke_callback_time = now_t
                            self.on_choke_callback(self.choke_probability, vol, top_label)

                except Exception as e:
                    print(f"[AudioDetector] Inference error: {e}")
            else:
                now_t = time.time()
                if self.cry_start_time is not None:
                    silence_gap = now_t - self.last_sound_active_time
                    if silence_gap > 1.2:
                        total_sound_dur = self.last_sound_active_time - self.cry_start_time
                        if 0.4 <= total_sound_dur < self.min_sustained_cry_seconds:
                            self.whimper_history.append(now_t)
                            wh_item = {
                                "time": time.strftime("%H:%M:%S"),
                                "epoch": now_t,
                                "type": "whimper",
                                "duration_seconds": round(total_sound_dur, 1),
                                "volume": round(float(vol), 4),
                                "note": f"Bé ọ ẹ nhẹ {total_sound_dur:.1f}s (Sinh lý REM)"
                            }
                            self.acoustic_event_log.append(wh_item)
                            if self.on_whimper_callback:
                                try:
                                    self.on_whimper_callback(wh_item)
                                except Exception as we:
                                    print(f"[AudioDetector] Lỗi on_whimper_callback: {we}")
                        self.cry_start_time = None
                        self.continuous_cry_seconds = 0.0
                self.cry_consecutive_frames = 0
                self.cry_probability = max(0.0, self.cry_probability - 0.05)
                self.cough_probability = max(0.0, self.cough_probability - 0.05)
                self.choke_probability = max(0.0, self.choke_probability - 0.05)
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
        now_t = time.time()
        whimpers_60s = sum(1 for t in self.whimper_history if (now_t - t) <= 60.0)
        is_sustained = bool(self.continuous_cry_seconds >= self.min_sustained_cry_seconds)
        is_fussing = bool((0.0 < self.continuous_cry_seconds < self.min_sustained_cry_seconds) or ("ọ ẹ" in self.top_sound_label))
        return {
            "volume": round(self.current_volume * 100, 1),
            "cry_probability": round(self.cry_probability * 100, 1),
            "is_crying": is_sustained,
            "is_fussing": is_fussing,
            "continuous_cry_seconds": round(self.continuous_cry_seconds, 1),
            "recent_whimpers_60s": whimpers_60s,
            "cough_probability": round(self.cough_probability * 100, 1),
            "is_coughing": self.cough_probability >= self.cough_threshold,
            "choke_probability": round(getattr(self, "choke_probability", 0.0) * 100, 1),
            "is_choking": getattr(self, "choke_probability", 0.0) >= getattr(self, "choke_threshold", 0.20),
            "top_sound": self.top_sound_label,
            "acoustic_events": list(self.acoustic_event_log)[-5:]
        }
