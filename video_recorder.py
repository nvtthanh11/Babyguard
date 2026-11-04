import os
import glob
import time
import shutil
import collections
import threading
import subprocess
import re
from datetime import datetime, timedelta
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
                date_folder = now.strftime("%Y-%m-%d")
                date_dir = os.path.join(self.recordings_dir, date_folder)
                os.makedirs(date_dir, exist_ok=True)

                # Tính khoảng thời gian clip video (từ mấy giờ đến mấy giờ)
                end_dt = now
                clip_duration_sec = len(frames_to_save) / max(1.0, float(self.fps))
                start_dt = end_dt - timedelta(seconds=clip_duration_sec)

                time_range_name = f"{start_dt.strftime('%Hh%Mp%S')}_den_{end_dt.strftime('%Hh%Mp%S')}_{event_type}"
                base_name = f"{date_folder}/{time_range_name}"
                mp4_path = os.path.join(date_dir, f"{time_range_name}.mp4")
                thumb_path = os.path.join(date_dir, f"{time_range_name}.jpg")

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
            for f in glob.glob(os.path.join(self.recordings_dir, "**", "*.mp4"), recursive=True):
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
                        parent = os.path.dirname(path)
                        if parent != self.recordings_dir and os.path.isdir(parent) and not os.listdir(parent):
                            os.rmdir(parent)
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
                    parent = os.path.dirname(path)
                    if parent != self.recordings_dir and os.path.isdir(parent) and not os.listdir(parent):
                        os.rmdir(parent)
                except Exception:
                    pass

        except Exception as e:
            print(f"[VideoRecorder] Retention error: {e}")

    def get_recordings(self, limit: int = 150):
        records = []
        files = glob.glob(os.path.join(self.recordings_dir, "**", "*.mp4"), recursive=True)
        files.sort(key=os.path.getmtime, reverse=True)
        
        today_str = datetime.now().strftime("%Y-%m-%d")
        yesterday_str = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

        for f in files[:limit]:
            rel_path = os.path.relpath(f, self.recordings_dir).replace("\\", "/")
            base = os.path.basename(f)
            size_mb = round(os.path.getsize(f) / (1024 * 1024), 2)
            mtime = os.path.getmtime(f)
            dt = datetime.fromtimestamp(mtime)
            
            # Determine date folder
            parent_dir = os.path.basename(os.path.dirname(f))
            if re.match(r"^\d{4}-\d{2}-\d{2}$", parent_dir):
                date_folder = parent_dir
            else:
                date_folder = dt.strftime("%Y-%m-%d")

            try:
                date_obj = datetime.strptime(date_folder, "%Y-%m-%d")
                d_formatted = date_obj.strftime("%d/%m/%Y")
            except Exception:
                d_formatted = date_folder

            if date_folder == today_str:
                date_display = f"Hôm nay ({d_formatted})"
            elif date_folder == yesterday_str:
                date_display = f"Hôm qua ({d_formatted})"
            else:
                date_display = d_formatted

            # Thumbnail check
            thumb_path = f.replace(".mp4", ".jpg")
            has_thumb = os.path.exists(thumb_path)
            rel_thumb = os.path.relpath(thumb_path, self.recordings_dir).replace("\\", "/") if has_thumb else None
            
            # Event type label
            evt = "Sự kiện"
            if "montage" in base:
                evt = "🎬 Video Kỷ Niệm"
            elif "cry" in base:
                evt = "🎙️ Tiếng khóc"
            elif "motion" in base:
                evt = "⚡ Cử động / thức giấc"
            elif "prone" in base:
                evt = "⚠️ Nằm sấp"
            elif "covered" in base:
                evt = "⚠️ Mặt bị che"
            elif "danger" in base:
                evt = "⚠️ Sát mép giường"
            elif "cough" in base:
                evt = "💨 Tiếng ho"
            elif "choke" in base:
                evt = "🥛 Sặc sữa"

            # Parse time range from filename if it has _den_
            den_match = re.search(r"(\d{2})h(\d{2})p(\d{2})_den_(\d{2})h(\d{2})p(\d{2})", base)
            if den_match:
                sh, sm, ss, eh, em, es = den_match.groups()
                time_range = f"Từ {sh}:{sm}:{ss} đến {eh}:{em}:{es}"
                title = f"{time_range} • {evt}"
            else:
                old_match = re.search(r"\d{8}_(\d{2})(\d{2})(\d{2})", base)
                if old_match:
                    eh, em, es = old_match.groups()
                    try:
                        end_t = datetime.strptime(f"{date_folder} {eh}:{em}:{es}", "%Y-%m-%d %H:%M:%S")
                        start_t = end_t - timedelta(seconds=30)
                        time_range = f"Từ {start_t.strftime('%H:%M:%S')} đến {end_t.strftime('%H:%M:%S')}"
                    except Exception:
                        time_range = f"{eh}:{em}:{es}"
                    title = f"{time_range} • {evt}"
                else:
                    time_range = dt.strftime("%H:%M:%S")
                    title = f"{time_range} • {evt}"

            records.append({
                "filename": rel_path,
                "name": base,
                "title": title,
                "time_range": time_range,
                "date_folder": date_folder,
                "date_display": date_display,
                "video_url": f"/api/recordings/{rel_path}",
                "thumbnail_url": f"/api/recordings/{rel_thumb}" if rel_thumb else None,
                "timestamp": dt.strftime("%H:%M:%S - %d/%m/%Y"),
                "size_mb": size_mb,
                "event_type": evt
            })
        return records

    def create_montage_video(self, image_paths: list = None, title: str = "Bé A Siu - Hành Trình Khôn Lớn", include_music: bool = True) -> dict:
        """
        Ghép các khoảnh khắc đáng yêu thành video MP4 kỷ niệm (Montage/Timelapse)
        kèm nhạc ru nhẹ nhàng và phụ đề thông tin ngày tháng.
        """
        if not image_paths:
            moments_dir = os.path.join(BASE_DIR, "moments")
            all_moments = sorted(glob.glob(os.path.join(moments_dir, "**", "*.jpg"), recursive=True), key=os.path.getmtime, reverse=True)
            all_moments = [p for p in all_moments if "rejected_backup" not in p]
            image_paths = all_moments[:24]

        valid_paths = [p for p in image_paths if os.path.exists(p)]
        if len(valid_paths) < 2:
            raise ValueError("Cần ít nhất 2 ảnh để tạo video kỷ niệm.")

        # Sort chronologically for nice progression
        valid_paths.sort(key=os.path.getmtime)

        now = datetime.now()
        ts_str = now.strftime("%Y%m%d_%H%M%S")
        tmp_dir = os.path.join(self.recordings_dir, f"_tmp_montage_{ts_str}")
        os.makedirs(tmp_dir, exist_ok=True)

        slides = []
        try:
            for idx, p in enumerate(valid_paths):
                img = cv2.imread(p)
                if img is None:
                    continue

                # 1280x720 canvas with dark gradient
                canvas = np.zeros((720, 1280, 3), dtype=np.uint8)
                for y in range(720):
                    val = int(14 + (y / 720) * 18)
                    canvas[y, :] = (val + 4, val, val)

                # Scale preserving aspect ratio inside (1200, 620)
                h, w = img.shape[:2]
                scale = min(1200.0 / w, 620.0 / h)
                nw, nh = int(w * scale), int(h * scale)
                resized = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_AREA)

                x_off = (1280 - nw) // 2
                y_off = 24 + (620 - nh) // 2
                canvas[y_off:y_off+nh, x_off:x_off+nw] = resized

                # Bottom banner overlay
                cv2.rectangle(canvas, (0, 650), (1280, 720), (10, 10, 18), -1)
                cv2.line(canvas, (0, 650), (1280, 650), (124, 58, 237), 2)

                mtime = os.path.getmtime(p)
                dt_str = datetime.fromtimestamp(mtime).strftime("%d/%m/%Y %H:%M")
                caption_left = f"{title}"
                caption_right = f"Khoanh khac: {dt_str}  |  BabyGuard AI"

                cv2.putText(canvas, caption_left, (36, 688), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (255, 255, 255), 2, cv2.LINE_AA)
                cv2.putText(canvas, caption_right, (36, 708), cv2.FONT_HERSHEY_SIMPLEX, 0.50, (148, 163, 184), 1, cv2.LINE_AA)

                slide_file = os.path.join(tmp_dir, f"slide_{idx:03d}.jpg")
                cv2.imwrite(slide_file, canvas, [cv2.IMWRITE_JPEG_QUALITY, 90])
                slides.append(slide_file)

            if len(slides) < 2:
                raise ValueError("Không thể xử lý đủ ảnh hợp lệ để tạo video.")

            # Create FFmpeg concat list
            duration_per_slide = 2.5
            concat_txt = os.path.join(tmp_dir, "concat.txt")
            with open(concat_txt, "w") as f:
                for s in slides:
                    f.write(f"file '{s}'\nduration {duration_per_slide}\n")
                f.write(f"file '{slides[-1]}'\n")

            total_duration = len(slides) * duration_per_slide
            date_folder = now.strftime("%Y-%m-%d")
            date_dir = os.path.join(self.recordings_dir, date_folder)
            os.makedirs(date_dir, exist_ok=True)
            out_base = f"montage_{ts_str}.mp4"
            out_mp4 = os.path.join(date_dir, out_base)
            out_thumb = os.path.join(date_dir, f"montage_{ts_str}.jpg")
            rel_mp4 = f"{date_folder}/{out_base}"
            rel_thumb = f"{date_folder}/montage_{ts_str}.jpg"

            # Save middle slide as thumbnail
            mid_idx = len(slides) // 2
            shutil.copyfile(slides[mid_idx], out_thumb)

            music_file = os.path.join(BASE_DIR, "music", "Nhac_ru_Brahms_Lullaby.wav")
            has_music = include_music and os.path.exists(music_file)

            # Build FFmpeg command
            cmd = [
                "ffmpeg", "-y",
                "-f", "concat", "-safe", "0", "-i", concat_txt
            ]

            if has_music:
                cmd.extend([
                    "-stream_loop", "-1", "-i", music_file,
                    "-vf", "format=yuv420p",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "22",
                    "-c:a", "aac", "-b:a", "128k",
                    "-t", str(total_duration),
                    "-af", f"afade=t=in:st=0:d=1,afade=t=out:st={max(0, total_duration - 2)}:d=2"
                ])
            else:
                cmd.extend([
                    "-vf", "format=yuv420p",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "22",
                    "-t", str(total_duration)
                ])

            cmd.append(out_mp4)

            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if res.returncode != 0 or not os.path.exists(out_mp4):
                err = res.stderr.decode("utf-8", errors="ignore")[:300]
                raise RuntimeError(f"FFmpeg error ({res.returncode}): {err}")

            size_mb = round(os.path.getsize(out_mp4) / (1024 * 1024), 2)
            print(f"[VideoRecorder] 🎬 Tạo video kỷ niệm thành công: {out_base} ({size_mb} MB, {len(slides)} ảnh)")

            return {
                "success": True,
                "filename": rel_mp4,
                "video_url": f"/api/recordings/{rel_mp4}",
                "thumbnail_url": f"/api/recordings/{rel_thumb}",
                "duration": round(total_duration, 1),
                "count": len(slides),
                "size_mb": size_mb,
                "timestamp": now.strftime("%H:%M:%S - %d/%m/%Y")
            }

        finally:
            # Clean up temp frames
            try:
                shutil.rmtree(tmp_dir, ignore_errors=True)
            except Exception:
                pass
