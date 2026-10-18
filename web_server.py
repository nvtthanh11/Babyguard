import os
import io
import zipfile
import json
import time
import base64
import socket
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import subprocess
import threading
import cv2
import requests
import sounddevice as sd
from fastapi import FastAPI, Request, UploadFile, File
from fastapi.responses import HTMLResponse, StreamingResponse, FileResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel


BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def create_app(vision_tracker, audio_detector, alert_manager, video_recorder, music_player, sleep_tracker, config_path: str, gemini_verifier=None):
    app = FastAPI(title="BabyGuard AI")
    templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))
    snapshots_dir = os.path.join(BASE_DIR, "snapshots")
    recordings_dir = os.path.join(BASE_DIR, "recordings")
    music_dir = os.path.join(BASE_DIR, "music")

    def load_config():
        with open(config_path, "r") as f:
            return json.load(f)

    def save_config(cfg):
        with open(config_path, "w") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request):
        return templates.TemplateResponse(request=request, name="index.html")

    def generate_frames(annotated: bool = True):
        last_good_bytes = None
        while True:
            try:
                frame = vision_tracker.get_latest_frame(annotated=annotated)
                if frame is not None:
                    if frame.mean() > 2.0:
                        ret, buffer = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
                        if ret:
                            last_good_bytes = buffer.tobytes()

                if last_good_bytes is not None:
                    yield (b"--frame\r\n"
                           b"Content-Type: image/jpeg\r\n\r\n" + last_good_bytes + b"\r\n")
                
                time.sleep(1.0 / 20.0)
            except (GeneratorExit, BrokenPipeError, ConnectionResetError):
                break
            except Exception:
                time.sleep(0.05)

    @app.get("/video_feed")
    def video_feed(annotated: bool = True):
        return StreamingResponse(
            generate_frames(annotated=annotated),
            media_type="multipart/x-mixed-replace; boundary=frame"
        )

    @app.get("/audio_feed")
    @app.get("/api/audio_feed")
    def audio_feed():
        """Phát luồng âm thanh phòng bé thời gian thực qua Web Audio (WAV 16kHz mono)."""
        def generate_wav_stream():
            import struct
            header = bytearray(44)
            header[0:4] = b'RIFF'
            struct.pack_into('<I', header, 4, 0x7FFFFFFF)
            header[8:12] = b'WAVE'
            header[12:16] = b'fmt '
            struct.pack_into('<I', header, 16, 16)
            struct.pack_into('<H', header, 20, 1)
            struct.pack_into('<H', header, 22, 1)
            struct.pack_into('<I', header, 24, 16000)
            struct.pack_into('<I', header, 28, 32000)
            struct.pack_into('<H', header, 32, 2)
            struct.pack_into('<H', header, 34, 16)
            header[36:40] = b'data'
            struct.pack_into('<I', header, 40, 0x7FFFFFFF)
            yield bytes(header)

            if not hasattr(audio_detector, "subscribe_audio"):
                return

            q = audio_detector.subscribe_audio()
            try:
                while True:
                    try:
                        chunk = q.get(timeout=2.0)
                        yield chunk
                    except Exception:
                        yield b'\x00' * 320
            finally:
                if hasattr(audio_detector, "unsubscribe_audio"):
                    audio_detector.unsubscribe_audio(q)

        return StreamingResponse(
            generate_wav_stream(),
            media_type="audio/wav",
            headers={
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Pragma": "no-cache",
                "Expires": "0"
            }
        )

    @app.get("/api/status")
    def api_status():
        vis_st = vision_tracker.get_status()
        aud_st = audio_detector.get_status()
        sleep_st = sleep_tracker.get_summary(
            adult_holding=vis_st.get("adult_holding", False),
            is_crying=aud_st.get("is_crying", False)
        )
        cfg = load_config()
        return {
            "vision": vis_st,
            "audio": aud_st,
            "music": music_player.get_status(),
            "sleep": sleep_st,
            "gemini": gemini_verifier.get_status() if gemini_verifier else {},
            "baby_profile": {
                "name": cfg.get("baby_name", "Bé Siu"),
                "age_months": cfg.get("baby_age_months", 3),
                "setup_completed": cfg.get("setup_completed", False)
            }
        }

    @app.get("/api/events")
    def api_events():
        return alert_manager.get_events()

    @app.get("/api/snapshots/{filename}")
    def get_snapshot(filename: str):
        file_path = os.path.join(snapshots_dir, filename)
        if os.path.exists(file_path):
            return FileResponse(file_path)
        return JSONResponse({"error": "File not found"}, status_code=404)

    @app.get("/api/recordings")
    def api_recordings():
        return video_recorder.get_recordings()

    @app.get("/api/recordings/{filename}")
    def get_recording_file(filename: str):
        file_path = os.path.join(recordings_dir, filename)
        if os.path.exists(file_path):
            media_type = "video/mp4" if filename.endswith(".mp4") else "image/jpeg"
            return FileResponse(file_path, media_type=media_type)
        return JSONResponse({"error": "File not found"}, status_code=404)

    # --- TWO-WAY AUDIO TALKBACK ---
    @app.post("/api/talkback")
    async def talkback(audio_file: UploadFile = File(...)):
        try:
            ts = int(time.time() * 1000)
            temp_in = f"/tmp/talkback_in_{ts}.webm"
            temp_out = f"/tmp/talkback_out_{ts}.wav"

            content = await audio_file.read()
            with open(temp_in, "wb") as f:
                f.write(content)

            subprocess.run([
                "/opt/homebrew/bin/ffmpeg", "-y", "-i", temp_in,
                "-ar", "44100", "-ac", "2", temp_out
            ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)

            def _play():
                try:
                    subprocess.run(["afplay", temp_out], check=False)
                finally:
                    for p in (temp_in, temp_out):
                        if os.path.exists(p):
                            try: os.remove(p)
                            except: pass

            threading.Thread(target=_play, daemon=True).start()
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}

    # --- WHITE NOISE & INSTRUMENTAL LULLABY PLAYER APIS (CLOSED-LOOP MIC CALIBRATION) ---
    @app.get("/api/music/list")
    def get_music_list():
        return music_player.get_playlist()

    class PlayMusicRequest(BaseModel):
        filename: str = "Tieng_on_trang_White_Noise.wav"
        loop: bool = True
        volume: float | None = None
        adaptive_mic: bool | None = None

    @app.post("/api/music/play")
    def play_music(req: PlayMusicRequest):
        cfg = load_config()
        cfg["selected_lullaby"] = req.filename
        if req.volume is not None:
            cfg["lullaby_max_volume"] = float(req.volume)
        if req.adaptive_mic is not None:
            cfg["lullaby_adaptive_mic"] = bool(req.adaptive_mic)
        save_config(cfg)
        success = music_player.play_track(
            req.filename, loop=req.loop, volume=req.volume, adaptive_mic=req.adaptive_mic
        )
        return {"success": success, "status": music_player.get_status()}

    class MusicConfigRequest(BaseModel):
        max_volume_pct: int | None = None
        target_mic_pct: int | None = None
        adaptive_mic_mode: bool | None = None
        selected_lullaby: str | None = None

    @app.post("/api/music/config")
    def update_music_config(req: MusicConfigRequest):
        cfg = load_config()
        max_vol = None
        if req.max_volume_pct is not None:
            max_vol = max(0.05, min(1.0, float(req.max_volume_pct) / 100.0))
            cfg["lullaby_max_volume"] = round(max_vol, 2)
        if req.target_mic_pct is not None:
            cfg["lullaby_target_mic_pct"] = int(req.target_mic_pct)
        if req.adaptive_mic_mode is not None:
            cfg["lullaby_adaptive_mic"] = bool(req.adaptive_mic_mode)
        if req.selected_lullaby:
            cfg["selected_lullaby"] = req.selected_lullaby
        save_config(cfg)
        music_player.configure_adaptive(
            max_volume=max_vol,
            adaptive_mic_mode=req.adaptive_mic_mode,
            target_mic_pct=req.target_mic_pct,
            selected_track=req.selected_lullaby
        )
        return {"success": True, "status": music_player.get_status()}

    @app.post("/api/music/stop")
    def stop_music():
        music_player.stop()
        return {"success": True, "status": music_player.get_status()}

    @app.post("/api/music/upload")
    async def upload_music(files: list[UploadFile] = File(None), file: UploadFile = File(None)):
        uploaded = []
        all_files = []
        if files:
            all_files.extend(files)
        if file:
            all_files.append(file)
        for f in all_files:
            if not f.filename:
                continue
            safe_name = os.path.basename(f.filename).replace(" ", "_")
            dest = os.path.join(music_dir, safe_name)
            content = await f.read()
            with open(dest, "wb") as fp:
                fp.write(content)
            uploaded.append(safe_name)
        return {"success": True, "uploaded": uploaded, "playlist": music_player.get_playlist()}

    @app.delete("/api/music/{filename}")
    def delete_music(filename: str):
        success = music_player.delete_track(filename)
        return {"success": success, "playlist": music_player.get_playlist()}

    # --- SLEEP ANALYTICS & MORNING 07:00 PEDIATRIC AI REPORT APIS ---
    _ai_sleep_State = {"generating": False, "last_auto_date": ""}

    def _trigger_morning_ai_sleep_report(summary_snapshot: dict):
        if _ai_sleep_State["generating"] or gemini_verifier is None or not gemini_verifier.is_ready():
            return
        _ai_sleep_State["generating"] = True

        def _bg():
            try:
                res = gemini_verifier.generate_daily_sleep_report(summary_snapshot)
                if res.get("success") and res.get("report"):
                    sleep_tracker.save_daily_ai_report(res["report"])
                    _ai_sleep_State["last_auto_date"] = summary_snapshot.get("today_date", "")
            finally:
                _ai_sleep_State["generating"] = False

        threading.Thread(target=_bg, daemon=True).start()

    @app.get("/api/sleep_summary")
    def get_sleep_summary():
        vis_st = vision_tracker.get_status()
        aud_st = audio_detector.get_status()
        summary = sleep_tracker.get_summary(
            adult_holding=vis_st.get("adult_holding", False),
            is_crying=aud_st.get("is_crying", False)
        )
        # Tự động tổng hợp Bảng Phân Tích Giấc Ngủ Đêm Qua & 24h vào 07:00 sáng hôm sau (hoặc lần đầu mở trong ngày)
        now_dt = datetime.now()
        today_str = summary.get("today_date", "")
        has_gemini_report = (
            sleep_tracker.daily_ai_report is not None
            and sleep_tracker.daily_ai_report.get("date") == today_str
        )
        if not has_gemini_report and now_dt.hour >= 7 and _ai_sleep_State["last_auto_date"] != today_str:
            _trigger_morning_ai_sleep_report(summary)
        return summary

    @app.post("/api/sleep/analyze-ai")
    def analyze_sleep_with_ai():
        if gemini_verifier is None or not gemini_verifier.is_ready():
            return {"success": False, "error": "Chưa cấu hình hoặc chưa sẵn sàng Gemini API Key"}
        vis_st = vision_tracker.get_status()
        aud_st = audio_detector.get_status()
        summary = sleep_tracker.get_summary(
            adult_holding=vis_st.get("adult_holding", False),
            is_crying=aud_st.get("is_crying", False)
        )
        res = gemini_verifier.generate_daily_sleep_report(summary)
        if res.get("success") and res.get("report"):
            sleep_tracker.save_daily_ai_report(res["report"])
            return {
                "success": True,
                "report": res["report"],
                "summary": sleep_tracker.get_summary(
                    adult_holding=vis_st.get("adult_holding", False),
                    is_crying=aud_st.get("is_crying", False)
                )
            }
        return {"success": False, "error": res.get("error", "Không thể tạo báo cáo AI")}

    # --- CUTE MOMENTS ALBUM APIS (CÓ GIÁM KHẢO THẨM MỸ & KIỂM DUYỆT NGƯỜI ĐI CÙNG QUA GEMINI) ---
    moments_dir = os.path.join(BASE_DIR, "moments")
    os.makedirs(moments_dir, exist_ok=True)

    @app.post("/api/take-snapshot")
    def take_snapshot():
        frame = vision_tracker.get_latest_frame(annotated=False)
        if frame is not None:
            frame_to_save = frame
            eval_res = {
                "checked_by_gemini": False,
                "approved": True,
                "caption_vi": "Khoảnh khắc đáng yêu của bé",
                "aesthetic_score": 8,
                "has_other_person": False
            }
            if gemini_verifier is not None and gemini_verifier.is_ready() and gemini_verifier.filter_moments_enabled:
                eval_res = gemini_verifier.evaluate_cute_moment(frame, is_manual=True)
                if not eval_res.get("approved", False):
                    return {
                        "success": False,
                        "rejected_by_ai": True,
                        "error": eval_res.get("reason_vi", "Ảnh không đạt tiêu chuẩn thẩm mỹ hoặc quyền riêng tư.")
                    }
                frame_to_save = gemini_verifier.apply_smart_crop(frame, eval_res)

            ts_moment = datetime.now().strftime("%Y%m%d_%H%M%S")
            moment_fn = f"moment_{ts_moment}.jpg"
            moment_path = os.path.join(moments_dir, moment_fn)
            cv2.imwrite(moment_path, frame_to_save)

            if gemini_verifier is not None:
                gemini_verifier.save_moment_metadata(moment_fn, eval_res)

            alert_manager.trigger_event("manual", eval_res.get("caption_vi", "Chụp ảnh lưu khoảnh khắc"), frame=frame_to_save)
            return {
                "success": True,
                "filename": moment_fn,
                "url": f"/api/moments/{moment_fn}",
                "caption_vi": eval_res.get("caption_vi", "Khoảnh khắc đáng yêu của bé"),
                "checked_by_gemini": eval_res.get("checked_by_gemini", False),
                "auto_cropped": eval_res.get("auto_cropped", False)
            }
        return {"success": False, "error": "Không lấy được khung hình từ camera"}

    @app.get("/api/moments")
    def get_moments():
        files = []
        meta_map = gemini_verifier.load_moments_metadata() if gemini_verifier else {}
        if os.path.exists(moments_dir):
            for f in sorted(os.listdir(moments_dir), reverse=True):
                if f.endswith((".jpg", ".png")):
                    p = os.path.join(moments_dir, f)
                    st = os.stat(p)
                    m_info = meta_map.get(f, {})
                    files.append({
                        "filename": f,
                        "url": f"/api/moments/{f}",
                        "timestamp": datetime.fromtimestamp(st.st_mtime).strftime("%H:%M:%S - %d/%m/%Y"),
                        "size_kb": round(st.st_size / 1024, 1),
                        "caption_vi": m_info.get("caption_vi", "Khoảnh khắc đáng yêu của bé"),
                        "aesthetic_score": m_info.get("aesthetic_score", None),
                        "has_other_person": m_info.get("has_other_person", False),
                        "checked_by_gemini": m_info.get("checked_by_gemini", False)
                    })
        return files

    @app.get("/api/moments/{filename}")
    def get_moment_file(filename: str):
        p = os.path.join(moments_dir, filename)
        if os.path.exists(p):
            return FileResponse(p, media_type="image/jpeg")
        return JSONResponse({"error": "File not found"}, status_code=404)

    @app.delete("/api/moments/{filename}")
    def delete_moment(filename: str):
        p = os.path.join(moments_dir, filename)
        if os.path.exists(p):
            try:
                os.remove(p)
                return {"success": True}
            except Exception as e:
                return {"success": False, "error": str(e)}
        return JSONResponse({"error": "File not found"}, status_code=404)

    @app.post("/api/moments/batch-delete")
    async def batch_delete_moments(request: Request):
        try:
            data = await request.json()
            filenames = data.get("filenames", [])
            deleted = []
            for fn in filenames:
                safe_fn = os.path.basename(fn)
                p = os.path.join(moments_dir, safe_fn)
                if os.path.exists(p):
                    try:
                        os.remove(p)
                        deleted.append(safe_fn)
                    except Exception as e:
                        print(f"[Moments] Lỗi xóa file {safe_fn}: {e}")
            return {"success": True, "deleted_count": len(deleted), "deleted": deleted}
        except Exception as e:
            return JSONResponse({"success": False, "error": str(e)}, status_code=500)

    @app.post("/api/moments/batch-download")
    async def batch_download_moments(request: Request):
        try:
            data = await request.json()
            filenames = data.get("filenames", [])
            if not filenames:
                return JSONResponse({"error": "Không có ảnh nào được chọn"}, status_code=400)
            
            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
                for fn in filenames:
                    safe_fn = os.path.basename(fn)
                    p = os.path.join(moments_dir, safe_fn)
                    if os.path.exists(p):
                        zip_file.write(p, arcname=safe_fn)
            
            zip_buffer.seek(0)
            now_str = datetime.now().strftime("%Y%m%d_%H%M%S")
            zip_filename = f"khoanh_khac_be_{now_str}.zip"
            
            return StreamingResponse(
                zip_buffer,
                media_type="application/zip",
                headers={
                    "Content-Disposition": f'attachment; filename="{zip_filename}"',
                    "Access-Control-Expose-Headers": "Content-Disposition"
                }
            )
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)

    @app.get("/api/download/full-package")
    def download_full_package():
        zip_path = os.path.join(BASE_DIR, "BabyGuard_AI_v1.0_Commercial.zip")
        if not os.path.exists(zip_path):
            zip_path = os.path.join(os.path.dirname(BASE_DIR), "BabyGuard_AI_v1.0_Commercial.zip")
        if os.path.exists(zip_path):
            return FileResponse(
                zip_path,
                media_type="application/zip",
                filename="BabyGuard_AI_v1.0_Commercial.zip"
            )
        return JSONResponse({"error": "Chưa tìm thấy tệp nén cài đặt"}, status_code=404)

    @app.get("/api/tunnel_url")
    def get_tunnel_url():
        log_file = os.path.join(BASE_DIR, "logs", "tunnel.log")
        if not os.path.exists(log_file):
            log_file = os.path.join(BASE_DIR, "tunnel.log")
        if os.path.exists(log_file):
            try:
                with open(log_file, "r") as f:
                    for line in f:
                        if ".trycloudflare.com" in line:
                            parts = line.strip().split()
                            for p in parts:
                                if "trycloudflare.com" in p and p.startswith("http"):
                                    return {"url": p}
            except Exception:
                pass
        return {"url": "https://statistical-study-jewellery-citations.trycloudflare.com"}

    @app.get("/api/config")
    def get_config():
        return load_config()

    class ConfigToggle(BaseModel):
        key: str
        value: bool

    @app.post("/api/config/toggle")
    def toggle_config(payload: ConfigToggle):
        cfg = load_config()
        cfg[payload.key] = payload.value
        save_config(cfg)
        
        alert_manager.update_config(cfg)
        video_recorder.update_config(cfg)
        if gemini_verifier is not None:
            gemini_verifier.update_config(cfg)
        if hasattr(vision_tracker, payload.key):
            setattr(vision_tracker, payload.key, payload.value)
        if hasattr(audio_detector, payload.key):
            setattr(audio_detector, payload.key, payload.value)
        print(f"[BabyGuard AI] Toggle updated: {payload.key} = {payload.value}")
        return {"success": True, "key": payload.key, "value": payload.value, "config": cfg}

    class ConfigUpdate(BaseModel):
        baby_name: str = None
        baby_age_months: int = None
        gemini_api_key: str = None
        gemini_enabled: bool = None
        gemini_verify_alerts: bool = None
        gemini_filter_moments: bool = None
        gemini_model: str = None
        setup_completed: bool = None
        camera_source_type: str = None
        camera_rtsp_url: str = None
        camera_index: int = None
        audio_device_index: int = None
        telegram_enabled: bool = None
        telegram_bot_token: str = None
        telegram_chat_id: str = None
        telegram_recipients: list = None
        telegram_send_video: bool = None
        telegram_notify_motion: bool = None
        sound_alert_on_mac: bool = None
        cry_threshold: float = None
        cough_threshold: float = None
        motion_threshold: float = None
        alert_cooldown_seconds: int = None
        record_on_event: bool = None
        pre_roll_seconds: int = None
        post_roll_seconds: int = None
        max_storage_gb: float = None
        max_retention_days: int = None
        prone_alert_enabled: bool = None
        covered_face_alert: bool = None
        danger_zone_enabled: bool = None
        cry_alert_enabled: bool = None
        cough_alert_enabled: bool = None
        breathing_monitor_enabled: bool = None
        sleep_analytics_enabled: bool = None
        wake_window_predictor: bool = None
        cute_moments_enabled: bool = None
        auto_soothing_enabled: bool = None
        safe_zone_top: float = None
        safe_zone_bottom: float = None
        safe_zone_left: float = None
        safe_zone_right: float = None
        danger_zone_y_percent: float = None
        danger_zone_x_percent: float = None
        auto_lullaby_on_cry: bool = None
        selected_lullaby: str = None

    @app.post("/api/config")
    def update_config(payload: ConfigUpdate):
        cfg = load_config()
        raw_dict = payload.dict(exclude_unset=True)
        update_data = {k: v for k, v in raw_dict.items() if v is not None}

        if "telegram_bot_token" in update_data and not str(update_data["telegram_bot_token"]).strip():
            update_data.pop("telegram_bot_token", None)
        if "telegram_chat_id" in update_data and not str(update_data["telegram_chat_id"]).strip():
            update_data.pop("telegram_chat_id", None)

        cfg.update(update_data)
        save_config(cfg)
        
        alert_manager.update_config(cfg)
        video_recorder.update_config(cfg)
        if gemini_verifier is not None:
            gemini_verifier.update_config(cfg)

        # Đổi nóng nguồn Camera (USB hoặc RTSP Wi-Fi) nếu người dùng thay đổi
        src_type = cfg.get("camera_source_type", "usb")
        rtsp_url = str(cfg.get("camera_rtsp_url", "")).strip()
        if src_type == "rtsp" and rtsp_url:
            vision_tracker.switch_camera(rtsp_url)
        elif "camera_index" in update_data or "camera_source_type" in update_data:
            vision_tracker.switch_camera(int(cfg.get("camera_index", 0)))

        # Đổi nóng cổng Micro thu âm nếu người dùng thay đổi
        if "audio_device_index" in update_data and hasattr(audio_detector, "switch_device"):
            audio_detector.switch_device(int(cfg.get("audio_device_index", 0)))

        if "cry_threshold" in update_data:
            audio_detector.cry_threshold = cfg.get("cry_threshold", 0.3)
        if "cough_threshold" in update_data:
            audio_detector.cough_threshold = cfg.get("cough_threshold", 0.25)
        if "motion_threshold" in update_data:
            vision_tracker.motion_threshold = cfg.get("motion_threshold", 18.0)
            
        for k in ["prone_alert_enabled", "covered_face_alert", "danger_zone_enabled",
                  "breathing_monitor_enabled", "cute_moments_enabled"]:
            if k in update_data and hasattr(vision_tracker, k):
                setattr(vision_tracker, k, update_data[k])
                
        for k in ["cry_alert_enabled", "cough_alert_enabled"]:
            if k in update_data and hasattr(audio_detector, k):
                setattr(audio_detector, k, update_data[k])
                
        if "safe_zone_top" in update_data:
            vision_tracker.safe_zone_top = cfg.get("safe_zone_top", 0.08)
        if "safe_zone_bottom" in update_data:
            vision_tracker.safe_zone_bottom = cfg.get("safe_zone_bottom", 0.98)
            vision_tracker.danger_zone_y_percent = vision_tracker.safe_zone_bottom
        if "safe_zone_left" in update_data:
            vision_tracker.safe_zone_left = cfg.get("safe_zone_left", 0.01)
        if "safe_zone_right" in update_data:
            vision_tracker.safe_zone_right = cfg.get("safe_zone_right", 0.99)
            vision_tracker.danger_zone_x_percent = vision_tracker.safe_zone_right
        return {"success": True, "config": cfg}

    # --- HARDWARE DISCOVERY (USB UVC CHIP DESCRIPTOR + AVFOUNDATION), WIFI RTSP/OUI SCANNER & LIVE PREVIEW ---
    USB_VENDOR_MAP = {
        "1133": "Logitech",
        "046d": "Logitech",
        "1452": "Apple",
        "05ac": "Apple",
        "1356": "Sony",
        "054c": "Sony",
        "3141": "Sonix / USB HD",
        "0c45": "Sonix / USB HD",
        "7119": "Sunplus",
        "1bcf": "Sunplus",
        "1118": "Microsoft",
        "045e": "Microsoft",
        "1008": "HP",
        "0bda": "Realtek USB"
    }

    @app.get("/api/hardware/devices")
    def get_hardware_devices():
        """
        Đọc trực tiếp thông tin phần cứng từ chip USB UVC (VendorID/ProductID) và AVFoundation
        để chỉ hiển thị ĐÚNG những chiếc Camera thực sự đang cắm vào máy (không tạo cổng ảo).
        """
        cameras = []
        sp_meta = {}
        try:
            out = subprocess.check_output(["system_profiler", "SPCameraDataType", "-json"], timeout=3)
            sp_data = json.loads(out).get("SPCameraDataType", [])
            for item in sp_data:
                raw_name = item.get("_name") or "USB Camera"
                model_id = item.get("spcamera_model-id", "")
                vendor_brand = ""
                for vid_key, brand_name in USB_VENDOR_MAP.items():
                    if f"VendorID_{vid_key}" in model_id or vid_key in model_id.lower():
                        vendor_brand = brand_name
                        break
                conn_type = "iPhone Continuity / Apple" if "apple" in model_id.lower() or vendor_brand == "Apple" else "USB UVC"
                full_title = f"{vendor_brand} {raw_name}".strip() if (vendor_brand and vendor_brand.lower() not in raw_name.lower()) else raw_name
                sp_meta[raw_name] = {
                    "full_title": full_title,
                    "conn_type": conn_type,
                    "model_id": model_id
                }
        except Exception:
            pass

        # Lấy danh sách index chính xác từ AVFoundation (bỏ qua "Capture screen")
        av_video_devices = []
        try:
            proc = subprocess.run(
                ["/opt/homebrew/bin/ffmpeg", "-f", "avfoundation", "-list_devices", "true", "-i", ""],
                capture_output=True, text=True, timeout=3
            )
            lines = (proc.stderr or "").splitlines()
            in_video_section = False
            for line in lines:
                if "AVFoundation video devices:" in line:
                    in_video_section = True
                    continue
                if "AVFoundation audio devices:" in line:
                    break
                if in_video_section and "[" in line and "]" in line:
                    # Ví dụ: [AVFoundation indev @ ...] [0] Brio 100
                    parts = line.split("]")
                    if len(parts) >= 3:
                        idx_str = parts[-2].split("[")[-1].strip()
                        dev_name = parts[-1].strip()
                        if idx_str.isdigit() and not dev_name.lower().startswith("capture screen"):
                            av_video_devices.append((int(idx_str), dev_name))
        except Exception:
            pass

        if not av_video_devices:
            # Fallback nếu không gọi được ffmpeg: dùng danh sách từ system_profiler
            for idx, (raw_name, info) in enumerate(sp_meta.items()):
                av_video_devices.append((idx, raw_name))

        for idx, raw_name in av_video_devices:
            meta = sp_meta.get(raw_name, {})
            full_title = meta.get("full_title", raw_name)
            conn_type = meta.get("conn_type", "USB Camera")
            is_active = (str(vision_tracker.camera_index) == str(idx))
            cameras.append({
                "index": idx,
                "name": full_title,
                "conn_type": conn_type,
                "label": f"📷 Cổng {idx}: {full_title} ({conn_type})" + (" — Đang dùng" if is_active else ""),
                "is_active": is_active
            })

        microphones = []
        try:
            devs = sd.query_devices()
            for idx, d in enumerate(devs):
                if d.get("max_input_channels", 0) > 0:
                    is_active = (audio_detector.device_index == idx)
                    dev_name = d.get("name", f"Micro {idx}")
                    microphones.append({
                        "index": idx,
                        "name": dev_name,
                        "label": f"🎙️ Cổng {idx}: {dev_name}" + (" — Đang dùng" if is_active else ""),
                        "is_active": is_active
                    })
        except Exception:
            pass

        return {
            "success": True,
            "cameras": cameras,
            "microphones": microphones
        }

    # Bảng nhận diện hãng sản xuất Camera Wi-Fi qua địa chỉ phần cứng MAC (OUI Prefix)
    MAC_OUI_CAMERA_BRANDS = {
        "c0:56:e3": ("Ezviz / Hikvision", "ezviz"),
        "4c:bd:8f": ("Ezviz / Hikvision", "ezviz"),
        "bc:ad:28": ("Ezviz / Hikvision", "ezviz"),
        "a4:14:37": ("Ezviz / Hikvision", "ezviz"),
        "28:57:be": ("Ezviz / Hikvision", "ezviz"),
        "e0:50:8b": ("Imou / Dahua", "imou"),
        "e4:24:6c": ("Imou / Dahua / KBVision", "imou"),
        "f4:b1:c2": ("Nomi / Imou (IPC-A22E)", "imou"),
        "3c:ef:8c": ("Imou / Dahua", "imou"),
        "90:02:a9": ("Imou / Dahua", "imou"),
        "a0:bd:1d": ("Imou / Dahua", "imou"),
        "50:c7:bf": ("TP-Link Tapo", "tapo"),
        "60:32:b1": ("TP-Link Tapo", "tapo"),
        "b0:95:75": ("TP-Link Tapo", "tapo"),
        "54:af:97": ("TP-Link Tapo", "tapo")
    }

    def _inspect_rtsp_and_mac(ip: str, port: int):
        """
        Gửi gói tin RTSP OPTIONS Handshake và tra cứu bảng MAC ARP / Hostname để biết chính xác
        chiếc Camera Wi-Fi tại địa chỉ IP đó thuộc hãng nào, tên máy và mã Serial là gì.
        """
        import re as _re
        banner_brand = None
        brand_code = "auto"
        device_serial = ""
        hostname_hint = ""

        # 1. Đọc tên thiết bị (Hostname) và địa chỉ MAC từ bảng ARP của Router
        try:
            arp_out = subprocess.check_output(["arp", ip], text=True, timeout=1.0).strip()
            arp_lower = arp_out.lower()
            # Lấy hostname nếu có (vd: nomi-ipc-a22e-h-v2.lan (192.168.1.203) at ...)
            first_token = arp_out.split(" ")[0].strip()
            if first_token and first_token != "?" and not first_token.startswith("("):
                hostname_hint = first_token.replace(".lan", "").replace(".local", "").upper()

            for oui, (b_label, b_code) in MAC_OUI_CAMERA_BRANDS.items():
                if oui in arp_lower:
                    banner_brand = f"Camera {b_label}"
                    brand_code = b_code
                    break
        except Exception:
            pass

        # 2. Hỏi trực tiếp RTSP Server Banner & Digest Realm Serial
        if port in (554, 8554):
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(0.45)
                sock.connect((ip, port))
                req = f"OPTIONS rtsp://{ip}:{port}/ RTSP/1.0\r\nCSeq: 1\r\nUser-Agent: BabyGuardAI\r\n\r\n"
                sock.sendall(req.encode("utf-8"))
                resp_raw = sock.recv(512).decode("utf-8", errors="ignore")
                sock.close()
                resp = resp_raw.lower()

                # Trích xuất mã Serial trong realm="Login to XXXXX" (Đặc trưng của Imou / Dahua / Nomi / KBVision)
                m_realm = _re.search(r'realm="login to ([a-zA-Z0-9_-]+)"', resp_raw, _re.IGNORECASE)
                if m_realm:
                    device_serial = m_realm.group(1)
                    if not banner_brand:
                        banner_brand = "Camera Imou / Dahua / Nomi"
                    brand_code = "imou"
                elif "hikvision" in resp or "ezviz" in resp or "dnvrs" in resp:
                    banner_brand = "Camera Ezviz / Hikvision"
                    brand_code = "ezviz"
                elif "dahua" in resp or "imou" in resp:
                    banner_brand = "Camera Imou / Dahua"
                    brand_code = "imou"
                elif "tp-link" in resp or "tapo" in resp:
                    banner_brand = "Camera TP-Link Tapo"
                    brand_code = "tapo"
                elif "yoosee" in resp or "gwell" in resp:
                    banner_brand = "Camera Yoosee / CareCam"
                    brand_code = "yoosee"
            except Exception:
                pass

        # Ghép thêm Tên máy (Hostname) và Mã thiết bị (Serial) để khách dễ phân biệt từng chiếc
        details = []
        if hostname_hint:
            details.append(hostname_hint)
        if device_serial:
            details.append(f"Mã máy: {device_serial[:8]}...")
        suffix = f" ({' • '.join(details)})" if details else ""

        final_label = f"{banner_brand or 'Camera Wi-Fi Chuẩn Quốc Tế RTSP'}{suffix}"
        return final_label, brand_code, device_serial

    @app.get("/api/hardware/scan-wifi-cameras")
    def scan_wifi_cameras():
        """Quét mạng Wi-Fi nội bộ (LAN) kết hợp RTSP Handshake & MAC OUI để nhận diện hãng Camera IP."""
        local_ip = "192.168.1.1"
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]
            s.close()
        except Exception:
            pass

        parts = local_ip.split(".")
        subnet = f"{parts[0]}.{parts[1]}.{parts[2]}" if len(parts) == 4 else "192.168.1"

        cam_ports = [
            (554, "Camera Wi-Fi Chuẩn Quốc Tế RTSP", "auto"),
            (8554, "Camera Wi-Fi RTSP (Cổng 8554)", "auto"),
            (8000, "Camera Ezviz / Hikvision", "ezviz"),
            (37777, "Camera Imou / Dahua", "imou"),
            (2020, "Camera TP-Link Tapo (ONVIF)", "tapo")
        ]

        found_cameras = []

        def _probe_host(host_idx: int):
            ip = f"{subnet}.{host_idx}"
            if ip == local_ip:
                return None
            for port, default_label, default_code in cam_ports:
                try:
                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    sock.settimeout(0.22)
                    res = sock.connect_ex((ip, port))
                    sock.close()
                    if res == 0:
                        detected_label, detected_code, serial = _inspect_rtsp_and_mac(ip, port)
                        return {
                            "ip": ip,
                            "port": port,
                            "brand_hint": detected_label or default_label,
                            "brand_code": detected_code or default_code,
                            "serial": serial
                        }
                except Exception:
                    pass
            return None

        with ThreadPoolExecutor(max_workers=64) as executor:
            results = list(executor.map(_probe_host, range(2, 255)))
            seen_serials = set()
            for r in results:
                if r is not None:
                    sn = r.get("serial", "")
                    if sn and sn in seen_serials:
                        continue
                    if sn:
                        seen_serials.add(sn)
                    found_cameras.append(r)

        return {
            "success": True,
            "local_ip": local_ip,
            "subnet": f"{subnet}.x",
            "cameras": found_cameras
        }

    def _fast_rtsp_auth_match(ip: str, port: int, user: str, pwd: str) -> bool:
        """
        Kiểm tra siêu tốc (15ms) xem Mã Xác Thực / Mật khẩu (pwd) có thuộc về chiếc Camera ở địa chỉ IP này không
        bằng giao thức RTSP Digest Authentication (RFC 2617).
        Nếu khớp mật khẩu, Camera trả về 'RTSP/1.0 200 OK'. Nếu sai mật khẩu, trả về '401 Unauthorized'.
        """
        import hashlib as _hashlib
        import re as _re
        if not pwd:
            return False
        uri = f"rtsp://{ip}:{port}/"
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(0.5)
            sock.connect((ip, port))
            req1 = f"OPTIONS {uri} RTSP/1.0\r\nCSeq: 1\r\nUser-Agent: BabyGuardAI\r\n\r\n"
            sock.sendall(req1.encode("utf-8"))
            resp1 = sock.recv(1024).decode("utf-8", errors="ignore")

            if "200 OK" in resp1 and "WWW-Authenticate" not in resp1:
                sock.close()
                return True

            m_realm = _re.search(r'realm="([^"]+)"', resp1, _re.IGNORECASE)
            m_nonce = _re.search(r'nonce="([^"]+)"', resp1, _re.IGNORECASE)
            if m_realm and m_nonce:
                realm = m_realm.group(1)
                nonce = m_nonce.group(1)
                ha1 = _hashlib.md5(f"{user}:{realm}:{pwd}".encode("utf-8")).hexdigest()
                ha2 = _hashlib.md5(f"OPTIONS:{uri}".encode("utf-8")).hexdigest()
                digest_resp = _hashlib.md5(f"{ha1}:{nonce}:{ha2}".encode("utf-8")).hexdigest()

                auth_header = (
                    f'Digest username="{user}", realm="{realm}", nonce="{nonce}", '
                    f'uri="{uri}", response="{digest_resp}"'
                )
                req2 = f"OPTIONS {uri} RTSP/1.0\r\nCSeq: 2\r\nAuthorization: {auth_header}\r\nUser-Agent: BabyGuardAI\r\n\r\n"
                sock.sendall(req2.encode("utf-8"))
                resp2 = sock.recv(1024).decode("utf-8", errors="ignore")
                sock.close()
                if "200 OK" in resp2:
                    return True
            else:
                sock.close()
        except Exception:
            pass
        return False

    def _build_rtsp_candidates(brand: str, user: str, pwd: str, ip: str, raw_url: str = "") -> list:
        """
        Tạo danh sách đường dẫn RTSP cho MỌI HÃNG CAMERA trên thị trường.
        Nếu khách chọn 'auto' hoặc hãng không có trong danh sách, hệ thống tự động thử lần lượt
        các chuẩn đường dẫn phổ biến nhất (Imou/Dahua/Nomi/KBVision, Ezviz/Hikvision, Tapo, Yoosee, Xiaomi/Viettel...).
        """
        if brand == "custom" and raw_url:
            return [raw_url]
        if not ip and raw_url:
            return [raw_url]

        brand_map = {
            "imou": f"rtsp://{user}:{pwd}@{ip}:554/cam/realmonitor?channel=1&subtype=0",
            "ezviz": f"rtsp://{user}:{pwd}@{ip}:554/h264/ch1/main/av_stream",
            "hikvision": f"rtsp://{user}:{pwd}@{ip}:554/Streaming/Channels/101",
            "tapo": f"rtsp://{user}:{pwd}@{ip}:554/stream1",
            "yoosee": f"rtsp://{user}:{pwd}@{ip}:554/onvif1",
            "viettel": f"rtsp://{user}:{pwd}@{ip}:554/live/ch0",
        }

        candidates = []
        if brand in brand_map:
            candidates.append(brand_map[brand])

        # Luôn bổ sung các chuẩn RTSP phổ biến khác để tự động dò nếu khách không biết hãng Camera của mình
        for key in ["imou", "ezviz", "hikvision", "tapo", "yoosee", "viettel"]:
            url = brand_map[key]
            if url not in candidates:
                candidates.append(url)
        return candidates

    class CameraPreviewRequest(BaseModel):
        source_type: str = "usb"  # "usb" hoặc "rtsp"
        camera_index: int = 0
        brand: str = "auto"       # "auto", "ezviz", "imou", "tapo", "yoosee", "viettel", "custom"
        ip: str = ""
        username: str = "admin"
        password: str = ""
        rtsp_url: str = ""
        scanned_cameras: list = None  # Danh sách các Camera đã quét để tự động dò khớp theo Mã Xác Thực / Serial

    @app.post("/api/hardware/preview-camera")
    def preview_camera(req: CameraPreviewRequest):
        """
        Chụp 1 bức ảnh trực tiếp từ chiếc Camera được chọn (cổng USB hoặc Camera Wi-Fi).
        Đặc biệt: Nếu nhà có nhiều Camera trong danh sách quét và khách chỉ nhập Mã Xác Thực (Mật khẩu)
        hoặc Mã Serial của chiếc Camera phòng bé (không cần biết IP nào), hệ thống sẽ TỰ ĐỘNG DÒ
        trong danh sách đã quét để bắt đúng chiếc Camera khớp với mã đó!
        """
        resolved_source = req.camera_index
        frame = None
        matched_ip = (req.ip or "").strip()
        matched_brand = req.brand or "auto"

        if req.source_type == "rtsp":
            raw_url = (req.rtsp_url or "").strip()
            user = (req.username or "admin").strip() or "admin"
            pwd = (req.password or "").strip()
            scanned_list = req.scanned_cameras if isinstance(req.scanned_cameras, list) else []

            # Nếu khách chưa biết IP nào nhưng có danh sách vừa quét + đã nhập Mã Xác Thực / Mật khẩu:
            # hoặc khách nhập Mã Serial vào ô IP / Mật khẩu -> Tự động dò trong danh sách quét!
            ip_Pool = []
            if matched_ip:
                # Kiểm tra xem khách có gõ nhầm Mã Serial (vd: E70C852C) vào ô IP không
                for cam in scanned_list:
                    cam_sn = str(cam.get("serial", "")).upper()
                    cam_hint = str(cam.get("brand_hint", "")).upper()
                    if cam_sn and matched_ip.upper() in cam_sn or matched_ip.upper() in cam_hint:
                        matched_ip = cam.get("ip", matched_ip)
                        matched_brand = cam.get("brand_code", matched_brand)
                        break
                ip_Pool.append((matched_ip, matched_brand))

            # Nếu có danh sách Camera đã quét và khách đã nhập Mã Xác Thực (pwd),
            # dùng thuật toán _fast_rtsp_auth_match (15ms/cam) để tìm đúng chiếc Camera nhận mật khẩu này!
            if pwd and scanned_list:
                for cam in scanned_list:
                    c_ip = str(cam.get("ip", "")).strip()
                    c_port = int(cam.get("port", 554) or 554)
                    c_brand = str(cam.get("brand_code", "auto"))
                    if c_ip and _fast_rtsp_auth_match(c_ip, c_port, user, pwd):
                        # Đưa chiếc Camera khớp mật khẩu lên đầu danh sách ưu tiên!
                        if (c_ip, c_brand) in ip_Pool:
                            ip_Pool.remove((c_ip, c_brand))
                        ip_Pool.insert(0, (c_ip, c_brand))

                # Bổ sung các camera còn lại trong danh sách quét làm dự phòng
                for cam in scanned_list:
                    c_ip = str(cam.get("ip", "")).strip()
                    c_brand = str(cam.get("brand_code", "auto"))
                    if c_ip and all(x[0] != c_ip for x in ip_Pool):
                        ip_Pool.append((c_ip, c_brand))

            if not ip_Pool and not raw_url:
                return {
                    "success": False,
                    "error": "Vui lòng bấm '🔍 Quét Camera trong nhà' hoặc nhập Mã xác thực / Địa chỉ IP của Camera."
                }

            if raw_url and not ip_Pool:
                f = vision_tracker.capture_preview_frame(raw_url)
                if f is not None:
                    frame = f
                    resolved_source = raw_url
            else:
                for test_ip, test_brand in ip_Pool:
                    candidates = _build_rtsp_candidates(test_brand, user, pwd, test_ip, raw_url)
                    for candidate_url in candidates:
                        f = vision_tracker.capture_preview_frame(candidate_url)
                        if f is not None:
                            frame = f
                            resolved_source = candidate_url
                            matched_ip = test_ip
                            matched_brand = test_brand
                            break
                    if frame is not None:
                        break
        else:
            resolved_source = int(req.camera_index)
            frame = vision_tracker.capture_preview_frame(resolved_source)

        if frame is None:
            if req.source_type == "rtsp":
                return {
                    "success": False,
                    "error": "Không tìm thấy chiếc Camera nào trong danh sách khớp với Mã Xác Thực / Mật khẩu này. Hãy kiểm tra lại 6 chữ cái Safety Code in dưới đáy chiếc Camera quay em bé (hoặc mật khẩu trong App)!"
                }
            return {
                "success": False,
                "error": f"Không tìm thấy tín hiệu hình ảnh ở Cổng Camera #{req.camera_index}."
            }

        h, w = frame.shape[:2]
        ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
        if not ok:
            return {"success": False, "error": "Lỗi mã hóa khung hình xem thử."}

        b64_img = base64.b64encode(buf.tobytes()).decode("utf-8")
        return {
            "success": True,
            "image_base64": f"data:image/jpeg;base64,{b64_img}",
            "resolution": f"{w}x{h}",
            "resolved_source": resolved_source,
            "matched_ip": matched_ip,
            "matched_brand": matched_brand
        }

    # --- MULTI-RECIPIENT FAMILY TELEGRAM APIS ---
    class TelegramTest(BaseModel):
        token: str
        chat_id: str = ""
        name: str = "Người nhà"
        recipients: list = None

    @app.post("/api/test-telegram")
    def test_telegram(payload: TelegramTest):
        token = (payload.token or "").strip()
        if not token:
            return {"success": False, "error": "Vui lòng nhập Bot Token trước."}

        targets = []
        if payload.chat_id and payload.chat_id.strip():
            targets.append({"name": payload.name or "Người nhận", "chat_id": payload.chat_id.strip()})
        elif payload.recipients:
            for r in payload.recipients:
                if isinstance(r, dict) and r.get("chat_id") and r.get("enabled", True):
                    targets.append({"name": r.get("name", "Người nhà"), "chat_id": str(r["chat_id"]).strip()})

        if not targets:
            return {"success": False, "error": "Chưa có người nhận nào trong danh sách."}

        sent_count = 0
        last_err = ""
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        for t in targets:
            try:
                data = {
                    "chat_id": t["chat_id"],
                    "text": f"👶 <b>BabyGuard AI:</b> Xin chào <b>{t['name']}</b>! Điện thoại của bạn đã được kết nối vào danh sách gia đình để nhận cảnh báo an toàn của bé.",
                    "parse_mode": "HTML"
                }
                resp = requests.post(url, json=data, timeout=8)
                if resp.status_code == 200:
                    sent_count += 1
                else:
                    last_err = resp.text
            except Exception as e:
                last_err = str(e)

        if sent_count > 0:
            return {"success": True, "sent_count": sent_count}
        return {"success": False, "error": last_err or "Không gửi được tin nhắn."}

    class TelegramDiscoverRequest(BaseModel):
        token: str

    @app.post("/api/telegram/discover-family")
    def discover_telegram_family(payload: TelegramDiscoverRequest):
        """
        Tự động dò tìm những người nhà vừa bấm /start hoặc nhắn tin cho Bot Telegram
        để bố mẹ thêm vào danh sách dùng chung chỉ bằng 1 cú nhấp chuột (không cần tự mò Chat ID).
        """
        token = (payload.token or "").strip()
        if not token:
            return {"success": False, "error": "Vui lòng nhập Telegram Bot Token trước."}
        try:
            url = f"https://api.telegram.org/bot{token}/getUpdates"
            resp = requests.get(url, timeout=8)
            if resp.status_code != 200:
                return {"success": False, "error": "Bot Token không hợp lệ hoặc không kết nối được Telegram."}
            data = resp.json()
            found = {}
            # 1. Lấy từ bộ nhớ liên hệ gần đây của AlertManager (do luồng auto-reply 24/7 đã lưu lại)
            for c in getattr(alert_manager, "recent_bot_contacts", []):
                cid = str(c.get("chat_id", "")).strip()
                if cid:
                    found[cid] = {
                        "name": c.get("name", f"Người nhà ({cid})"),
                        "chat_id": cid,
                        "last_text": c.get("last_text", "")
                    }
            # 2. Quét thêm từ getUpdates hiện tại
            for upd in data.get("result", []):
                msg = upd.get("message") or upd.get("edited_message") or upd.get("my_chat_member", {})
                chat = msg.get("chat", {})
                cid = str(chat.get("id", "")).strip()
                if not cid:
                    continue
                first = chat.get("first_name", "")
                last = chat.get("last_name", "")
                title = chat.get("title", "")
                uname = chat.get("username", "")
                full_name = (f"{first} {last}".strip() or title or uname or f"Người nhà ({cid})")
                if uname:
                    full_name = f"{full_name} (@{uname})"
                found[cid] = {
                    "name": full_name,
                    "chat_id": cid,
                    "last_text": str(msg.get("text", ""))[:40]
                }
            res_list = list(found.values())
            return {
                "success": True,
                "members": res_list,
                "users": res_list
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    class GeminiTestRequest(BaseModel):
        api_key: str = ""

    @app.post("/api/test-gemini")
    def test_gemini(payload: GeminiTestRequest):
        if gemini_verifier is None:
            return {"success": False, "error": "Module Gemini chưa được khởi tạo."}
        return gemini_verifier.test_connection(payload.api_key)

    @app.post("/api/gemini/auto-calibrate")
    def auto_calibrate_crib():
        if gemini_verifier is None:
            return {"success": False, "error": "Module Gemini chưa được khởi tạo."}
        frame = vision_tracker.get_latest_frame(annotated=False)
        if frame is None:
            return {"success": False, "error": "Chưa nhận được khung hình từ camera."}
        res = gemini_verifier.auto_calibrate_crib(frame)
        if res.get("success") and "safe_zone" in res:
            sz = res["safe_zone"]
            cfg = load_config()
            cfg["safe_zone_top"] = sz["top"]
            cfg["safe_zone_bottom"] = sz["bottom"]
            cfg["safe_zone_left"] = sz["left"]
            cfg["safe_zone_right"] = sz["right"]
            save_config(cfg)
            vision_tracker.safe_zone_top = sz["top"]
            vision_tracker.safe_zone_bottom = sz["bottom"]
            vision_tracker.safe_zone_left = sz["left"]
        return res

    @app.post("/api/gemini/audit-tracking")
    def manual_audit_tracking():
        """Kiểm tra chéo & hiệu chỉnh nóng khung Tracking của AI Local ngay lập tức bằng Gemini."""
        if gemini_verifier is None or not gemini_verifier.is_ready():
            return {"success": False, "error": "Vui lòng cấu hình Gemini API Key còn hạn trước."}
        raw_frame = vision_tracker.get_latest_frame(annotated=False)
        ann_frame = vision_tracker.get_latest_frame(annotated=True)
        if raw_frame is None or ann_frame is None:
            return {"success": False, "error": "Chưa lấy được khung hình từ camera."}

        h, w = raw_frame.shape[:2]
        norm_box = [0.0, 0.0, 0.0, 0.0]
        if getattr(vision_tracker, "last_baby_box", None) is not None:
            bx1, by1, bx2, by2 = vision_tracker.last_baby_box
            norm_box = [round(bx1 / w, 3), round(by1 / h, 3), round(bx2 / w, 3), round(by2 / h, 3)]

        local_info = {
            "baby_detected": vision_tracker.baby_detected,
            "norm_box": norm_box,
            "sleep_pose": vision_tracker.sleep_pose
        }
        res = gemini_verifier.audit_local_tracking(raw_frame, ann_frame, local_info)
        if not res.get("audited", False):
            return {"success": False, "error": res.get("error", "Không thể kiểm tra Tracking lúc này.")}

        # Áp dụng hiệu chỉnh nóng nếu Gemini phát hiện lệch
        if res.get("baby_present", True):
            acc = res.get("tracking_accurate", True)
            score = res.get("accuracy_score", 95)
            tbox = res.get("true_baby_box")
            hdir = res.get("head_direction", "up")
            if (not acc or score < 80 or not vision_tracker.baby_detected) and isinstance(tbox, list) and len(tbox) == 4:
                import numpy as np
                xmin, ymin, xmax, ymax = [float(v) for v in tbox]
                gx1 = int(np.clip(min(xmin, xmax) * w, 0, w - 20))
                gy1 = int(np.clip(min(ymin, ymax) * h, 0, h - 20))
                gx2 = int(np.clip(max(xmin, xmax) * w, gx1 + 40, w))
                gy2 = int(np.clip(max(ymin, ymax) * h, gy1 + 40, h))
                g_box = np.array([gx1, gy1, gx2, gy2], dtype=int)
                dir_map = {
                    "right": np.array([-1.0, 0.0], dtype=float),
                    "left": np.array([1.0, 0.0], dtype=float),
                    "up": np.array([0.0, 1.0], dtype=float),
                    "down": np.array([0.0, -1.0], dtype=float),
                }
                new_u = dir_map.get(str(hdir).lower(), np.array([-1.0, 0.0], dtype=float))
                with vision_tracker.lock:
                    vision_tracker.smoothed_box = g_box.astype(float)
                    vision_tracker.last_baby_box = g_box
                    vision_tracker.smoothed_spine_u = new_u
                    vision_tracker.gemini_anchor_box = g_box
                    vision_tracker.gemini_anchor_u = new_u
                    vision_tracker.gemini_anchor_pose = res.get("sleep_pose_vi", "Đang ngủ ngoan")
                    vision_tracker.gemini_anchor_until = time.time() + 55.0

        return {
            "success": True,
            "tracking_accurate": res.get("tracking_accurate", True),
            "accuracy_score": res.get("accuracy_score", 95),
            "feedback_vi": res.get("feedback_vi", ""),
            "usage": gemini_verifier.get_usage_stats()
        }

    return app

