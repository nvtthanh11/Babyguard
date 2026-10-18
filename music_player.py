import os
import glob
import time
import wave
import threading
import subprocess
import numpy as np

try:
    import sounddevice as sd
    HAS_SOUNDDEVICE = True
except Exception:
    HAS_SOUNDDEVICE = False


BASE_DIR = os.path.dirname(os.path.abspath(__file__))

TRACK_CATALOG_META = {
    "Tieng_on_trang_White_Noise.wav": {
        "display_name": "🌊 Tiếng Ồn Trắng (Mô phỏng buồng ối mẹ)",
        "category": "white_noise",
        "desc": "Che lấp tiếng động giật mình, giúp bé sơ sinh ngủ sâu"
    },
    "Tieng_on_hong_Pink_Noise.wav": {
        "display_name": "🌸 Tiếng Ồn Hồng (Tần số ấm dịu nhẹ)",
        "category": "white_noise",
        "desc": "Giảm tần số cao, hỗ trợ kéo dài pha Ngủ Sâu NREM"
    },
    "Tieng_on_nau_Brown_Noise.wav": {
        "display_name": "🤎 Tiếng Ồn Nâu (Trầm ấm ru ngủ sâu)",
        "category": "white_noise",
        "desc": "Âm trầm êm ái, rất hiệu quả khi bé trằn trọc chuyển cữ"
    },
    "Nhip_tim_me_Heartbeat.wav": {
        "display_name": "💓 Nhịp Tim Mẹ (68 BPM chống giật mình)",
        "category": "white_noise",
        "desc": "Nhịp đập đều đặn giúp trấn an phản xạ giật mình Moro"
    },
    "Tieng_mua_roi_Rain_Sound.wav": {
        "display_name": "🌧️ Tiếng Mưa Rào Êm Dịu (Nature White Noise)",
        "category": "white_noise",
        "desc": "Âm thanh mưa rơi đều đặn tạo không gian yên bình"
    },
    "Tieng_suoi_chay_Water_Stream.wav": {
        "display_name": "💧 Tiếng Suối Chảy Róc Rách",
        "category": "white_noise",
        "desc": "Âm thanh thiên nhiên thư giãn nhẹ nhàng"
    },
    "Song_bien_vo_Ocean_Waves.wav": {
        "display_name": "🌊 Sóng Biển Rì Rào Nhịp Nhàng",
        "category": "white_noise",
        "desc": "Nhịp sóng vỗ đồng điệu với nhịp thở của bé"
    },
    "Nhac_ru_Brahms_Lullaby.wav": {
        "display_name": "🎹 Nhạc Không Lời: Brahms Lullaby",
        "category": "instrumental",
        "desc": "Giai điệu hộp nhạc cổ điển êm dịu ru bé vào giấc ngủ"
    },
    "Nhac_ru_Twinkle_Chime.wav": {
        "display_name": "🎵 Nhạc Không Lời: Twinkle Music Box",
        "category": "instrumental",
        "desc": "Tiếng chuông ngân tần số thấp nhẹ nhàng cho bé"
    }
}


class MusicPlayer:
    """
    Bộ Phát Tiếng Ồn Trắng & Nhạc Không Lời Thông Minh (Commercial Adaptive Closed-Loop Audio):
    1. KHỞI ĐỘNG MỀM (Soft Fade-In):
       - Khi tự động kích hoạt (hoặc bấm phát), âm lượng bắt đầu từ mức cực nhỏ (4%) rồi tăng dần
         mượt mà từng chút một (+2%/giây) để không bao giờ làm bé giật mình.
    2. TỰ CÂN BẰNG ÂM LƯỢNG QUA MICRO (Closed-Loop Mic Calibration):
       - Liên tục đọc cường độ âm thanh thực tế thu được từ Micro tại vị trí nôi của bé (`mic_volume`).
       - Khi cường độ tại Micro chạm "Ngưỡng vừa đủ an toàn tại nôi" (`target_mic_pct`, mặc định 32% ~ 45 dB
         theo chuẩn an toàn thính giác nhi khoa AAP <= 50 dB), hệ thống TỰ ĐỘNG KHÓA / GIỮ NGUYÊN mức âm lượng
         loa đó, hoặc tự giảm nhẹ nếu âm lượng phòng vượt ngưỡng.
    3. TỰ ĐỘNG NHỎ DẦN KHI BÉ NGỦ SÂU (Soft Fade-Out):
       - Sau khi vỗ về bé yên giấc (mặc định 4 phút), âm lượng giảm dần từ từ về 0% trước khi tắt.
    """

    def __init__(self, music_dir: str = None):
        self.music_dir = music_dir or os.path.join(BASE_DIR, "music")
        os.makedirs(self.music_dir, exist_ok=True)

        self.current_process = None
        self.current_track = "Tieng_on_trang_White_Noise.wav"
        self.is_playing = False
        self.should_loop = True

        # Điều khiển âm lượng & Vòng lặp phản hồi Micro
        self.max_volume_cap = 0.65       # Giới hạn âm lượng loa tối đa (0.05 -> 1.0)
        self.current_gain = 0.04         # Âm lượng thực tế đang phát ra loa (bắt đầu từ 4%)
        self.adaptive_mic_mode = True    # Tự động đo bằng Mic để giữ mức vừa đủ
        self.target_mic_pct = 32         # Ngưỡng cường độ thu tại Mic mong muốn (32% ~ 45 dB SPL chuẩn AAP)
        self.measured_mic_pct = 0.0      # Cường độ thực tế Mic đang đo được (0 - 100%)
        self.is_baby_crying_now = False  # Cờ báo bé đang khóc to (để không nhầm tiếng khóc với tiếng loa)
        self.calibration_state_vi = "Đang chờ kích hoạt"
        self.play_started_at = 0.0
        self.auto_fadeout_seconds = 240.0  # Tự động nhỏ dần sau 4 phút vỗ về

        self.audio_detector_ref = None
        self.lock = threading.Lock()
        self.worker_thread = None

    def attach_audio_detector(self, audio_detector):
        """Gắn tham chiếu tới Micro (`AudioCryDetector`) để đo cường độ âm thanh vòng kín thời gian thực."""
        self.audio_detector_ref = audio_detector

    def configure_adaptive(self, max_volume: float = None, adaptive_mic_mode: bool = None,
                           target_mic_pct: int = None, selected_track: str = None):
        with self.lock:
            if max_volume is not None:
                self.max_volume_cap = float(np.clip(max_volume, 0.05, 1.0))
                if not self.adaptive_mic_mode and self.is_playing:
                    self.current_gain = self.max_volume_cap
            if adaptive_mic_mode is not None:
                self.adaptive_mic_mode = bool(adaptive_mic_mode)
            if target_mic_pct is not None:
                self.target_mic_pct = int(np.clip(target_mic_pct, 15, 65))
            if selected_track:
                self.current_track = selected_track

    def get_playlist(self):
        extensions = ("*.wav", "*.mp3", "*.m4a", "*.aac", "*.flac")
        tracks = []
        for ext in extensions:
            tracks.extend(glob.glob(os.path.join(self.music_dir, ext)))

        # Ưu tiên sắp xếp Tiếng Ồn Trắng & Nhịp Tim lên đầu danh sách
        priority_order = list(TRACK_CATALOG_META.keys())
        tracks.sort(key=lambda p: (
            priority_order.index(os.path.basename(p))
            if os.path.basename(p) in priority_order else 999,
            os.path.basename(p)
        ))

        result = []
        for t in tracks:
            base = os.path.basename(t)
            size_mb = round(os.path.getsize(t) / (1024 * 1024), 2)
            meta = TRACK_CATALOG_META.get(base, {})
            result.append({
                "filename": base,
                "name": meta.get("display_name") or base.rsplit(".", 1)[0].replace("_", " "),
                "category": meta.get("category", "instrumental"),
                "desc": meta.get("desc", "Âm thanh vỗ về giấc ngủ cho bé"),
                "size_mb": size_mb
            })
        return result

    def _update_closed_loop_gain(self, dt: float):
        """
        Thuật toán Điều Khiển Âm Lượng Vòng Kín Qua Micro (Closed-Loop Acoustic Soothing):
        - Khởi động ở mức 4% (Soft Fade-In).
        - Đọc cường độ thu âm thực tế từ Micro (`measured_mic_pct`).
        - Tăng dần cho tới khi cường độ tại Micro chạm `target_mic_pct` (vừa đủ nghe tại nôi ~45 dB)
          hoặc chạm trần `max_volume_cap`.
        - Tự động giảm dần (Soft Fade-Out) trong 20 giây cuối sau khi đã vỗ về bé ngủ yên.
        """
        if self.audio_detector_ref is not None:
            st = self.audio_detector_ref.get_status()
            raw_mic = float(st.get("volume", 0.0))
            self.measured_mic_pct = round(0.7 * self.measured_mic_pct + 0.3 * raw_mic, 1)
            self.is_baby_crying_now = bool(st.get("is_crying", False))

        elapsed = time.time() - self.play_started_at

        # Kiểm tra giai đoạn Soft Fade-Out cuối chu kỳ vỗ về (nếu bé đã nín khóc)
        if self.should_loop and self.auto_fadeout_seconds > 0 and elapsed > self.auto_fadeout_seconds and not self.is_baby_crying_now:
            fade_elapsed = elapsed - self.auto_fadeout_seconds
            if fade_elapsed >= 18.0:
                self.is_playing = False
                self.calibration_state_vi = "Đã tự tắt êm sau khi bé ngủ sâu"
                return
            self.current_gain = max(0.02, self.current_gain - 0.025 * dt)
            self.calibration_state_vi = "🌙 Bé đã yên giấc • Đang nhỏ dần tắt êm (Fade-Out)..."
            return

        # Nếu tắt chế độ Tự cân bằng theo Mic -> Tăng mượt (Fade-In) tới đúng mức âm lượng bố mẹ chọn
        if not self.adaptive_mic_mode:
            if self.current_gain < self.max_volume_cap - 0.01:
                self.current_gain = min(self.max_volume_cap, self.current_gain + 0.03 * dt)
                self.calibration_state_vi = f"🌱 Đang tăng dần êm dịu lên {int(self.max_volume_cap * 100)}%..."
            else:
                self.current_gain = self.max_volume_cap
                self.calibration_state_vi = f"🔊 Đang phát cố định ở mức {int(self.current_gain * 100)}%"
            return

        # CHẾ ĐỘ TỰ CÂN BẰNG ÂM LƯỢNG BẰNG MICRO (CLOSED-LOOP MIC CALIBRATION)
        # Nếu bé đang khóc to (tiếng khóc làm Mic vọt cao), tăng mượt lên mức trấn an an toàn (75% của max_cap)
        if self.is_baby_crying_now:
            soothe_cap = min(self.max_volume_cap, max(0.25, self.max_volume_cap * 0.85))
            if self.current_gain < soothe_cap:
                self.current_gain = min(soothe_cap, self.current_gain + 0.03 * dt)
            self.calibration_state_vi = "🤱 Bé đang khóc • Phát mức trấn an êm dịu, sẽ tự hạ khi bé dịu lại"
            return

        # Khi phòng không có tiếng khóc: Dùng chính cường độ thu được từ Micro để canh mức âm lượng "Vừa Đủ"!
        target = float(self.target_mic_pct)
        measured = float(self.measured_mic_pct)
        deadband = 3.5  # Sai số cho phép +/- 3.5% để âm lượng ổn định mượt mà

        if measured < (target - deadband):
            # Âm thanh thu tại Mic còn nhỏ hơn ngưỡng vừa đủ -> Tăng nhẹ loa lên (+2.2% mỗi giây)
            if self.current_gain < self.max_volume_cap:
                self.current_gain = min(self.max_volume_cap, self.current_gain + 0.022 * dt)
                if self.current_gain >= self.max_volume_cap - 0.01:
                    self.calibration_state_vi = f"🔒 Đã chạm trần an toàn bố mẹ đặt ({int(self.max_volume_cap * 100)}%)"
                else:
                    self.calibration_state_vi = f"🌱 Đang tăng dần từ nhỏ -> vừa đủ (Mic: {int(measured)}% / Mục tiêu: {int(target)}%)"
            else:
                self.calibration_state_vi = f"🔒 Đã chạm trần an toàn ({int(self.max_volume_cap * 100)}%)"
        elif measured > (target + deadband + 4.0):
            # Âm thanh thu tại Mic lớn hơn mức vừa đủ -> Tự động hạ nhỏ loa xuống để bảo vệ thính giác bé!
            self.current_gain = max(0.04, self.current_gain - 0.025 * dt)
            self.calibration_state_vi = f"🔉 Tự giảm nhẹ để giữ mức êm dịu tại nôi (Mic: {int(measured)}%)"
        else:
            # Đã đạt đúng vùng "Vừa Đủ Nghe" tại vị trí Micro của bé! Giữ nguyên âm lượng!
            self.calibration_state_vi = f"✅ Đã khóa ở mức vừa đủ tại nôi (Loa {int(self.current_gain * 100)}% • Mic {int(measured)}%)"

    def play_track(self, filename: str = None, loop: bool = True, volume: float = None,
                   adaptive_mic: bool = None):
        if not filename:
            filename = self.current_track or "Tieng_on_trang_White_Noise.wav"
        file_path = os.path.join(self.music_dir, filename)
        if not os.path.exists(file_path):
            # Fallback về Tiếng Ồn Trắng nếu file không tồn tại
            fallback = os.path.join(self.music_dir, "Tieng_on_trang_White_Noise.wav")
            if os.path.exists(fallback):
                file_path = fallback
                filename = "Tieng_on_trang_White_Noise.wav"
            else:
                print(f"[MusicPlayer] File not found: {file_path}")
                return False

        self.stop()

        with self.lock:
            self.current_track = filename
            self.should_loop = loop
            if volume is not None:
                self.max_volume_cap = float(np.clip(volume, 0.05, 1.0))
            if adaptive_mic is not None:
                self.adaptive_mic_mode = bool(adaptive_mic)
            # Khởi động mềm từ mức rất nhỏ 4% (Soft Fade-In)
            self.current_gain = min(0.04, self.max_volume_cap)
            self.play_started_at = time.time()
            self.is_playing = True
            self.calibration_state_vi = "🌱 Khởi động mềm từ 4% (Chống giật mình)..."

        if file_path.lower().endswith(".wav") and HAS_SOUNDDEVICE:
            self.worker_thread = threading.Thread(
                target=self._stream_wav_realtime, args=(file_path,), daemon=True
            )
        else:
            self.worker_thread = threading.Thread(
                target=self._play_fallback_process, args=(file_path,), daemon=True
            )
        self.worker_thread.start()
        return True

    def _stream_wav_realtime(self, file_path: str):
        """
        Phát file WAV bằng luồng PCM thời gian thực (`sounddevice.OutputStream`),
        cho phép điều chỉnh âm lượng mượt từng 50ms theo phản hồi của Micro!
        """
        try:
            with wave.open(file_path, "rb") as wf:
                channels = wf.getnchannels()
                rate = wf.getframerate()
                raw_bytes = wf.readframes(wf.getnframes())
                samples = np.frombuffer(raw_bytes, dtype=np.int16).astype(np.float32) / 32768.0
                if channels > 1:
                    samples = samples.reshape(-1, channels)
                else:
                    samples = samples.reshape(-1, 1)

            chunk_size = int(rate * 0.05)  # 50ms mỗi bước cập nhật âm lượng
            total_frames = len(samples)
            cursor = 0
            last_gain_ts = time.time()

            with sd.OutputStream(samplerate=rate, channels=channels, dtype="float32") as stream:
                while self.is_playing:
                    now = time.time()
                    dt = max(0.01, min(0.25, now - last_gain_ts))
                    last_gain_ts = now
                    with self.lock:
                        if not self.is_playing:
                            break
                        self._update_closed_loop_gain(dt)
                        gain = float(self.current_gain)

                    end_idx = cursor + chunk_size
                    if end_idx <= total_frames:
                        chunk = samples[cursor:end_idx] * gain
                        cursor = end_idx
                    else:
                        if self.should_loop:
                            part1 = samples[cursor:]
                            rem = chunk_size - len(part1)
                            part2 = samples[:rem]
                            chunk = np.vstack((part1, part2)) * gain
                            cursor = rem
                        else:
                            chunk = samples[cursor:] * gain
                            stream.write(chunk)
                            break

                    stream.write(chunk)
        except Exception as e:
            print(f"[MusicPlayer] Stream fallback ({e}), switching to process player...")
            if self.is_playing:
                self._play_fallback_process(file_path)
        finally:
            with self.lock:
                self.is_playing = False

    def _play_fallback_process(self, file_path: str):
        while self.is_playing:
            with self.lock:
                self._update_closed_loop_gain(1.0)
                vol_arg = str(round(min(1.0, max(0.04, self.current_gain)), 2))
            cmd = ["afplay", "-v", vol_arg, file_path]
            with self.lock:
                if not self.is_playing:
                    break
                self.current_process = subprocess.Popen(cmd)
            self.current_process.wait()
            with self.lock:
                if not self.is_playing or not self.should_loop:
                    self.is_playing = False
                    break

    def stop(self):
        with self.lock:
            self.is_playing = False
            self.calibration_state_vi = "Đang dừng"
            if self.current_process:
                try:
                    self.current_process.terminate()
                    self.current_process.kill()
                except Exception:
                    pass
                self.current_process = None

    def delete_track(self, filename: str):
        if self.current_track == filename and self.is_playing:
            self.stop()
        file_path = os.path.join(self.music_dir, filename)
        if os.path.exists(file_path):
            os.remove(file_path)
            return True
        return False

    def get_status(self):
        with self.lock:
            meta = TRACK_CATALOG_META.get(self.current_track or "", {})
            friendly_name = meta.get("display_name") or (
                self.current_track.rsplit(".", 1)[0].replace("_", " ") if self.current_track else "Tiếng Ồn Trắng"
            )
            # Ước tính mức dB SPL tương đương tại nôi (30 dB phòng tĩnh -> ~50 dB ở mức Mic 42%)
            est_db = int(round(32 + (self.measured_mic_pct * 0.42)))
            return {
                "is_playing": self.is_playing,
                "current_track": self.current_track,
                "current_track_label": friendly_name,
                "loop": self.should_loop,
                "volume": round(self.current_gain, 2),
                "current_volume_pct": int(round(self.current_gain * 100)),
                "max_volume_pct": int(round(self.max_volume_cap * 100)),
                "adaptive_mic_mode": self.adaptive_mic_mode,
                "target_mic_pct": self.target_mic_pct,
                "measured_mic_pct": round(self.measured_mic_pct, 1),
                "estimated_db": est_db,
                "calibration_state_vi": self.calibration_state_vi if self.is_playing else "Đang dừng (Sẵn sàng kích hoạt mềm từ 4%)"
            }
