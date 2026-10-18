import os
import glob
import time
import shutil
import collections
import threading
import subprocess
from datetime import datetime
import cv2
import numpy as np


BASE_DIR = os.path.dirname(os.path.abspath(__file__))


class VideoRecorder:
    def __init__(self, config: dict, recordings_dir: str = None):
        self.config = config
        self.recordings_dir = recordings_dir or os.path.join(BASE_DIR, "recordings")
        os.makedirs(self.recordings_dir, exist_ok=True)
        
        self.fps = config.get("fps", 15)
        self.pre_roll_seconds = config.get("pre_roll_seconds", 10)
        self.post_roll_seconds = config.get("post_roll_seconds", 20)
        self.sample_rate = 16000
        
        self.max_video_buffer_len = int(self.fps * self.pre_roll_seconds)
        self.max_audio_buffer_len = int(self.sample_rate * self.pre_roll_seconds)
        
        # Ring buffers for pre-roll in RAM
        self.video_buffer = collections.deque(maxlen=self.max_video_buffer_len)
        self.audio_buffer = collections.deque(maxlen=self.max_audio_buffer_len)
        self.lock = threading.Lock()
        
        # Active recording state
        self.is_recording = False
        self.recording_lock = threading.Lock()
        self.active_video_frames = []
        self.active_audio_samples = []
        self.record_thread = None

    def update_config(self, new_cfg: dict):
        self.config.update(new_cfg)
        self.fps = self.config.get("fps", 15)
        self.pre_roll_seconds = self.config.get("pre_roll_seconds", 10)
        self.post_roll_seconds = self.config.get("post_roll_seconds", 20)
        self.max_video_buffer_len = int(self.fps * self.pre_roll_seconds)
        self.max_audio_buffer_len = int(self.sample_rate * self.pre_roll_seconds)
        with self.lock:
            self.video_buffer = collections.deque(self.video_buffer, maxlen=self.max_video_buffer_len)
            self.audio_buffer = collections.deque(self.audio_buffer, maxlen=self.max_audio_buffer_len)

    def add_video_frame(self, frame):
        with self.lock:
            self.video_buffer.append(frame.copy())
            
        with self.recording_lock:
            if self.is_recording:
                self.active_video_frames.append(frame.copy())

    def add_audio_samples(self, samples: np.ndarray):
        # samples: 1D float32 numpy array
        samples_list = samples.tolist() if isinstance(samples, np.ndarray) else list(samples)
        with self.lock:
            self.audio_buffer.extend(samples_list)
            
        with self.recording_lock:
            if self.is_recording:
                self.active_audio_samples.extend(samples_list)

    def trigger_recording(self, event_type: str, description: str, on_complete_callback=None):
        if not self.config.get("record_on_event", True):
            return

        with self.recording_lock:
            if self.is_recording:
                return
            self.is_recording = True
            
            with self.lock:
                self.active_video_frames = list(self.video_buffer)
                self.active_audio_samples = list(self.audio_buffer)

        def _record_worker():
            try:
                target_duration = self.post_roll_seconds
                time.sleep(target_duration)

                with self.recording_lock:
                    frames_to_save = list(self.active_video_frames)
                    audio_to_save = np.array(self.active_audio_samples, dtype=np.float32)
                    self.is_recording = False
                    self.active_video_frames = []
                    self.active_audio_samples = []

                if not frames_to_save:
                    return

                now = datetime.now()
                ts_str = now.strftime("%Y%m%d_%H%M%S")
                base_name = f"{ts_str}_{event_type}"
                mp4_path = os.path.join(self.recordings_dir, f"{base_name}.mp4")
                thumb_path = os.path.join(self.recordings_dir, f"{base_name}.jpg")

                # Save thumbnail
                mid_idx = len(frames_to_save) // 2
                cv2.imwrite(thumb_path, frames_to_save[mid_idx])

                # Encode video + audio synchronized to MP4
                self._encode_video_and_audio(frames_to_save, audio_to_save, mp4_path)

                # Quấn chiếu tự động
                self.enforce_retention_policy()

                if on_complete_callback and os.path.exists(mp4_path):
                    on_complete_callback(mp4_path, thumb_path, base_name)
                    
            except Exception as e:
                print(f"[VideoRecorder] Error in recording worker: {e}")
                with self.recording_lock:
                    self.is_recording = False
                    self.active_video_frames = []
                    self.active_audio_samples = []

        self.record_thread = threading.Thread(target=_record_worker, daemon=True)
        self.record_thread.start()

    def _encode_video_and_audio(self, frames, audio_samples, output_path: str):
        if not frames:
            return
        h, w = frames[0].shape[:2]
        
        # Write temporary raw audio file
        raw_audio_path = f"/tmp/rec_audio_{int(time.time()*1000)}.raw"
        has_audio = len(audio_samples) > 0
        if has_audio:
            audio_samples.tofile(raw_audio_path)

        cmd = [
            "/opt/homebrew/bin/ffmpeg", "-y",
            "-f", "rawvideo",
            "-vcodec", "rawvideo",
            "-s", f"{w}x{h}",
            "-pix_fmt", "bgr24",
            "-r", str(self.fps),
            "-i", "-"
        ]
        
        if has_audio:
            cmd.extend([
                "-f", "f32le",
                "-ar", str(self.sample_rate),
                "-ac", "1",
                "-i", raw_audio_path,
                "-c:a", "aac",
                "-b:a", "128k"
            ])
            
        cmd.extend([
            "-c:v", "h264_videotoolbox",
            "-b:v", "1500k",
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            output_path
        ])

        try:
            proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            for f in frames:
                proc.stdin.write(f.tobytes())
            proc.stdin.close()
            proc.wait(timeout=20)
            print(f"[VideoRecorder] Saved clip with AUDIO ({len(frames)} frames, {len(audio_samples)/self.sample_rate:.1f}s audio): {output_path}")
        except Exception as e:
            print(f"[VideoRecorder] Encoding failed: {e}")
            if proc:
                proc.kill()
        finally:
            if has_audio and os.path.exists(raw_audio_path):
                try:
                    os.remove(raw_audio_path)
                except Exception:
                    pass

    def enforce_retention_policy(self):
        try:
            max_days = self.config.get("max_retention_days", 14)
            max_gb = self.config.get("max_storage_gb", 30.0)
            max_bytes = max_gb * 1024 * 1024 * 1024
            cutoff_time = time.time() - (max_days * 86400)

            files = []
            for f in glob.glob(os.path.join(self.recordings_dir, "*.mp4")):
                mtime = os.path.getmtime(f)
                size = os.path.getsize(f)
                files.append((f, mtime, size))

            files.sort(key=lambda x: x[1])

            remaining_files = []
            for path, mtime, size in files:
                if mtime < cutoff_time:
                    try:
                        os.remove(path)
                        thumb = path.replace(".mp4", ".jpg")
                        if os.path.exists(thumb):
                            os.remove(thumb)
                        print(f"[VideoRecorder] Đã xóa video hết hạn (> {max_days} ngày): {os.path.basename(path)}")
                    except Exception:
                        pass
                else:
                    remaining_files.append((path, mtime, size))

            total_size = sum(x[2] for x in remaining_files)
            for path, mtime, size in remaining_files:
                if total_size <= max_bytes:
                    break
                try:
                    os.remove(path)
                    thumb = path.replace(".mp4", ".jpg")
                    if os.path.exists(thumb):
                        os.remove(thumb)
                    total_size -= size
                    print(f"[VideoRecorder] Quấn chiếu: Xóa {os.path.basename(path)} để giữ dưới {max_gb}GB.")
                except Exception:
                    pass

        except Exception as e:
            print(f"[VideoRecorder] Retention error: {e}")

    def get_recordings(self, limit: int = 50):
        records = []
        files = glob.glob(os.path.join(self.recordings_dir, "*.mp4"))
        files.sort(key=os.path.getmtime, reverse=True)
        
        for f in files[:limit]:
            base = os.path.basename(f)
            size_mb = round(os.path.getsize(f) / (1024 * 1024), 2)
            mtime = os.path.getmtime(f)
            dt_str = datetime.fromtimestamp(mtime).strftime("%H:%M:%S - %d/%m/%Y")
            thumb_name = base.replace(".mp4", ".jpg")
            has_thumb = os.path.exists(os.path.join(self.recordings_dir, thumb_name))
            
            evt = "Sự kiện"
            if "cry" in base:
                evt = "Tiếng khóc"
            elif "motion" in base:
                evt = "Cử động"
            elif "prone" in base:
                evt = "Nằm sấp"

            records.append({
                "filename": base,
                "video_url": f"/api/recordings/{base}",
                "thumbnail_url": f"/api/recordings/{thumb_name}" if has_thumb else None,
                "timestamp": dt_str,
                "size_mb": size_mb,
                "event_type": evt
            })
        return records
