import os
import io
import zipfile
import json
import time
import base64
import socket
import hmac
import hashlib
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import subprocess
import threading
import cv2
import requests
import sounddevice as sd
import secrets
from fastapi import FastAPI, Request, UploadFile, File
from fastapi.responses import HTMLResponse, StreamingResponse, FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel


BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def create_app(vision_tracker, audio_detector, alert_manager, video_recorder, music_player, sleep_tracker, config_path: str, gemini_verifier=None, tunnel_manager=None):
    app = FastAPI(title="BabyGuard AI")
    templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))
    snapshots_dir = os.path.join(BASE_DIR, "snapshots")
    recordings_dir = os.path.join(BASE_DIR, "recordings")
    music_dir = os.path.join(BASE_DIR, "music")
    static_dir = os.path.join(BASE_DIR, "static")
    os.makedirs(static_dir, exist_ok=True)
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    docs_assets_dir = os.path.join(BASE_DIR, "docs", "assets")
    if os.path.exists(docs_assets_dir):
        app.mount("/assets", StaticFiles(directory=docs_assets_dir), name="assets")

    config_file_lock = threading.Lock()

    def load_config():
        with config_file_lock:
            for _ in range(3):
                try:
                    if os.path.exists(config_path):
                        with open(config_path, "r", encoding="utf-8") as f:
                            content = f.read().strip()
                            if content:
                                return json.loads(content)
                    time.sleep(0.05)
                except Exception:
                    time.sleep(0.05)
            return {}

    def save_config(cfg):
        with config_file_lock:
            try:
                tmp_path = config_path + ".tmp"
                with open(tmp_path, "w", encoding="utf-8") as f:
                    json.dump(cfg, f, indent=2, ensure_ascii=False)
                os.replace(tmp_path, config_path)
            except Exception as e:
                print(f"[Config] Lỗi lưu cấu hình: {e}")

    from growth_tracker import GrowthTracker, calculate_exact_age
    from vaccine_tracker import VaccineTracker
    from daily_story_tracker import DailyStoryTracker
    from license_manager import LicenseManager, get_machine_fingerprint, generate_license_key, MASTER_SECRET
    growth_tracker = GrowthTracker()
    vaccine_tracker = VaccineTracker()
    daily_story_tracker = DailyStoryTracker()
    license_manager = LicenseManager(load_config())

    def get_family_pin(cfg: dict) -> str:
        return str(cfg.get("family_pin", "888888")).strip()

    def get_access_key(cfg: dict) -> str:
        key = cfg.get("access_key", "")
        if not key:
            key = "bg_" + secrets.token_hex(16)
            cfg["access_key"] = key
            save_config(cfg)
        return str(key).strip()

    def generate_session_token(machine_id: str, pin: str) -> str:
        msg = f"BG_FAMILY_AUTH:{machine_id}:{pin}:{MASTER_SECRET.decode(errors='ignore')}".encode()
        return hmac.new(MASTER_SECRET, msg, hashlib.sha256).hexdigest()

    def is_request_authenticated(request: Request, cfg: dict) -> bool:
        host = request.headers.get("host", "").lower()
        client_ip = request.client.host if request.client else ""
        if "localhost" in host or "127.0.0.1" in host or client_ip in ["127.0.0.1", "::1"] or host.startswith("192.168.") or host.startswith("10.") or host.startswith("100."):
            return True

        acc_key = get_access_key(cfg)

        # 1. Chìa khóa cookie tự động trên điện thoại (Không bao giờ phải nhập mật khẩu)
        auth_cookie = request.cookies.get("babyguard_auth", "")
        if auth_cookie and hmac.compare_digest(auth_cookie, acc_key):
            return True

        # 2. Chìa khóa tự động trong link Telegram (?k= hoặc ?key= hoặc ?token=)
        q_key = request.query_params.get("k", "") or request.query_params.get("key", "") or request.query_params.get("token", "")
        if q_key and hmac.compare_digest(q_key, acc_key):
            return True

        # 3. Fallback phiên làm việc cũ
        pin = get_family_pin(cfg)
        mid = get_machine_fingerprint()
        expected_token = generate_session_token(mid, pin)

        auth_session = request.cookies.get("babyguard_family_session", "")
        if auth_session and hmac.compare_digest(auth_session, expected_token):
            return True

        auth_param = request.query_params.get("pin_token", "") or request.headers.get("X-Family-Token", "")
        if auth_param and hmac.compare_digest(auth_param, expected_token):
            return True

        q_pin = request.query_params.get("pin", "")
        if q_pin and q_pin == pin:
            return True

        return False

    @app.get("/api/auth/status")
    def get_auth_status(request: Request):
        cfg = load_config()
        authed = is_request_authenticated(request, cfg)
        host = request.headers.get("host", "").lower()
        client_ip = request.client.host if request.client else ""
        is_local = "localhost" in host or "127.0.0.1" in host or client_ip in ["127.0.0.1", "::1"]
        return {
            "authenticated": authed,
            "is_local": is_local,
            "has_pin_set": bool(cfg.get("family_pin"))
        }

    @app.post("/api/auth/verify-pin")
    async def verify_family_pin(request: Request):
        try:
            body = await request.json()
        except Exception:
            body = {}
        entered_pin = str(body.get("pin", "")).strip()
        cfg = load_config()
        correct_pin = get_family_pin(cfg)

        if entered_pin and entered_pin == correct_pin:
            mid = get_machine_fingerprint()
            token = generate_session_token(mid, correct_pin)
            response = JSONResponse({
                "success": True,
                "message": "Xác thực mã PIN bảo vệ gia đình thành công!",
                "token": token
            })
            response.set_cookie(
                key="babyguard_family_session",
                value=token,
                max_age=30 * 86400,
                httponly=True,
                samesite="lax"
            )
            return response
        else:
            return JSONResponse({
                "success": False,
                "message": "Mã PIN bảo vệ không chính xác. Vui lòng thử lại!"
            }, status_code=401)

    @app.post("/api/auth/change-pin")
    async def change_family_pin(request: Request):
        try:
            body = await request.json()
        except Exception:
            body = {}
        old_pin = str(body.get("old_pin", "")).strip()
        new_pin = str(body.get("new_pin", "")).strip()
        cfg = load_config()
        current_pin = get_family_pin(cfg)

        if old_pin != current_pin:
            return JSONResponse({"success": False, "message": "Mã PIN cũ không chính xác!"}, status_code=400)
        if len(new_pin) < 4 or len(new_pin) > 8 or not new_pin.isdigit():
            return JSONResponse({"success": False, "message": "Mã PIN mới phải gồm 4 đến 8 chữ số!"}, status_code=400)

        cfg["family_pin"] = new_pin
        save_config(cfg)
        return {"success": True, "message": "Đã đổi Mã PIN bảo vệ gia đình thành công!"}

    @app.get("/cam")
    @app.get("/watch")
    @app.get("/live")
    async def view_camera_live(request: Request):
        cfg = load_config()
        acc_key = get_access_key(cfg)
        q_key = request.query_params.get("k", "") or request.query_params.get("key", "") or request.query_params.get("token", "")
        auth_cookie = request.cookies.get("babyguard_auth", "")

        host = request.headers.get("host", "").lower()
        is_local = "localhost" in host or "127.0.0.1" in host or host.startswith("192.168.") or host.startswith("10.") or host.startswith("100.")

        # Nếu có chìa khóa trong link, hoặc đã có cookie hợp lệ, hoặc là mạng nội bộ gia đình:
        # => MỞ THẲNG DASHBOARD XEM CAMERA NGAY LẬP TỨC TRONG 1 GIÂY, KHÔNG HỎI MẬT KHẨU!
        if is_local or (q_key and hmac.compare_digest(q_key, acc_key)) or (auth_cookie and hmac.compare_digest(auth_cookie, acc_key)):
            response = templates.TemplateResponse(request=request, name="index.html")
            response.set_cookie(
                key="babyguard_auth",
                value=acc_key,
                max_age=365 * 86400,
                httponly=True,
                samesite="lax"
            )
            return response

        # Người lạ trên mạng gõ bừa vào /cam mà không có chìa khóa bí mật -> Đẩy về trang bán hàng
        return RedirectResponse(url="/", status_code=302)

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request):
        host = request.headers.get("host", "").lower()
        # Chỉ máy nội bộ gia đình (localhost hoặc mạng WiFi ở nhà 192.168.x.x) mới vào Dashboard điều khiển
        if "localhost" in host or "127.0.0.1" in host or host.startswith("192.168.") or host.startswith("10.") or host.startswith("100."):
            return templates.TemplateResponse(request=request, name="index.html")

        # Nếu bố mẹ truy cập babyguard.site mà trên máy đã lưu cookie xác thực tự động -> Vào thẳng camera
        cfg = load_config()
        acc_key = get_access_key(cfg)
        auth_cookie = request.cookies.get("babyguard_auth", "")
        if auth_cookie and hmac.compare_digest(auth_cookie, acc_key):
            return templates.TemplateResponse(request=request, name="index.html")

        # Toàn bộ truy cập từ internet qua domain babyguard.site -> 100% LÀ TRANG BÁN HÀNG & GIỚI THIỆU SẢN PHẨM
        landing_file = os.path.join(BASE_DIR, "docs", "index.html")
        if os.path.exists(landing_file):
            return FileResponse(landing_file, media_type="text/html")
        return templates.TemplateResponse(request=request, name="index.html")

    @app.get("/manifest.json")
    async def get_manifest():
        manifest_file = os.path.join(static_dir, "manifest.json")
        if os.path.exists(manifest_file):
            return FileResponse(manifest_file, media_type="application/manifest+json")
        return JSONResponse({"status": "error", "message": "manifest.json not found"}, status_code=404)

    @app.get("/sw.js")
    async def get_service_worker():
        sw_file = os.path.join(static_dir, "sw.js")
        if os.path.exists(sw_file):
            return FileResponse(sw_file, media_type="application/javascript")
        return JSONResponse({"status": "error", "message": "sw.js not found"}, status_code=404)

    @app.api_route("/download/app.apk", methods=["GET", "HEAD"])
    async def download_apk():
        apk_path = os.path.join(static_dir, "BabyGuard_AI.apk")
        if not os.path.exists(apk_path):
            return JSONResponse({"status": "not_ready", "message": "File APK đang được chuẩn bị. Vui lòng thử lại sau giây lát!"}, status_code=404)
        return FileResponse(
            apk_path,
            media_type="application/vnd.android.package-archive",
            filename="BabyGuard_AI.apk",
            headers={
                "Content-Disposition": "attachment; filename=BabyGuard_AI.apk",
                "Cache-Control": "no-cache"
            }
        )

    @app.api_route("/download/app.aab", methods=["GET", "HEAD"])
    async def download_aab():
        aab_path = os.path.join(static_dir, "BabyGuard_AI.aab")
        if not os.path.exists(aab_path):
            return JSONResponse({"status": "not_ready", "message": "File AAB đang được chuẩn bị. Vui lòng thử lại sau giây lát!"}, status_code=404)
        return FileResponse(
            aab_path,
            media_type="application/octet-stream",
            filename="BabyGuard_AI.aab",
            headers={
                "Content-Disposition": "attachment; filename=BabyGuard_AI.aab",
                "Cache-Control": "no-cache"
            }
        )

    @app.api_route("/download/desktop-app", methods=["GET", "HEAD"])
    @app.api_route("/download/app.zip", methods=["GET", "HEAD"])
    @app.api_route("/download/BabyGuard_AI.zip", methods=["GET", "HEAD"])
    async def download_desktop_app():
        candidates = [
            os.path.join(static_dir, "BabyGuard_AI_v2.0_Commercial.zip"),
            os.path.join(BASE_DIR, "dist", "BabyGuard_AI_v2.0_Commercial.zip"),
            os.path.join(BASE_DIR, "BabyGuard_AI_v1.0_Commercial.zip"),
            os.path.join(os.path.dirname(BASE_DIR), "BabyGuard_AI_v1.0_Commercial.zip")
        ]
        for c in candidates:
            if os.path.exists(c):
                return FileResponse(
                    c,
                    media_type="application/zip",
                    filename="BabyGuard_AI_v2.0_Commercial.zip",
                    headers={
                        "Content-Disposition": "attachment; filename=BabyGuard_AI_v2.0_Commercial.zip",
                        "Cache-Control": "no-cache"
                    }
                )
        return JSONResponse({"status": "not_ready", "message": "Gói cài đặt máy tính đang được chuẩn bị. Vui lòng tải lại sau giây lát!"}, status_code=404)

    @app.get("/landing", response_class=HTMLResponse)
    @app.get("/huong-dan", response_class=HTMLResponse)
    @app.get("/guide", response_class=HTMLResponse)
    async def landing_and_guide_page(request: Request):
        doc_path = os.path.join(BASE_DIR, "docs", "index.html")
        if os.path.exists(doc_path):
            return FileResponse(doc_path, media_type="text/html")
        return templates.TemplateResponse(request=request, name="index.html")

    @app.get("/api/app-info")
    async def get_app_info():
        apk_path = os.path.join(static_dir, "BabyGuard_AI.apk")
        aab_path = os.path.join(static_dir, "BabyGuard_AI.aab")
        has_apk = os.path.exists(apk_path)
        has_aab = os.path.exists(aab_path)
        apk_size_mb = round(os.path.getsize(apk_path) / (1024 * 1024), 2) if has_apk else 0
        aab_size_mb = round(os.path.getsize(aab_path) / (1024 * 1024), 2) if has_aab else 0
        tunnel_url = ""
        if tunnel_manager and hasattr(tunnel_manager, "get_url"):
            tunnel_url = tunnel_manager.get_url() or ""
        return {
            "app_name": "BabyGuard AI",
            "version": "1.0.0",
            "package_id": "vn.babyguard.ai",
            "has_apk": has_apk,
            "apk_size_mb": apk_size_mb,
            "download_url": "/download/app.apk",
            "has_aab": has_aab,
            "aab_size_mb": aab_size_mb,
            "aab_download_url": "/download/app.aab",
            "tunnel_url": tunnel_url
        }

    def generate_frames(annotated: bool = True):
        last_good_bytes = None
        while True:
            try:
                frame = vision_tracker.get_latest_frame(annotated=annotated)
                if frame is not None and frame.size > 0:
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
    def video_feed(request: Request, annotated: bool = True):
        cfg = load_config()
        if not is_request_authenticated(request, cfg):
            return JSONResponse({"status": "forbidden", "message": "Yêu cầu mã PIN bảo vệ gia đình để truy cập camera phòng ngủ."}, status_code=401)
        return StreamingResponse(
            generate_frames(annotated=annotated),
            media_type="multipart/x-mixed-replace; boundary=frame",
            headers={
                "Cache-Control": "no-cache, no-store, must-revalidate, max-age=0",
                "Pragma": "no-cache",
                "Expires": "0",
                "X-Accel-Buffering": "no"
            }
        )

    @app.get("/api/current_frame.jpg")
    def get_current_frame_jpg(request: Request):
        """Lấy 1 khung hình JPEG tức thì phục vụ watchdog kiểm tra luồng và fallback chống đen màn hình."""
        cfg = load_config()
        if not is_request_authenticated(request, cfg):
            return JSONResponse({"status": "forbidden", "message": "Yêu cầu mã PIN bảo vệ gia đình để truy cập camera phòng ngủ."}, status_code=401)
        from fastapi import Response
        frame = vision_tracker.get_latest_frame(annotated=True)
        if frame is None or frame.size == 0:
            frame = vision_tracker._make_disconnected_frame() if hasattr(vision_tracker, "_make_disconnected_frame") else None
        if frame is not None and frame.size > 0:
            ret, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
            if ret:
                return Response(
                    content=buf.tobytes(),
                    media_type="image/jpeg",
                    headers={"Cache-Control": "no-cache, no-store, must-revalidate", "Pragma": "no-cache", "Expires": "0"}
                )
        return Response(content=b"", media_type="image/jpeg")

    @app.get("/audio_feed")
    @app.get("/api/audio_feed")
    def audio_feed(request: Request):
        """Phát luồng âm thanh phòng bé thời gian thực qua Web Audio (WAV 16kHz mono)."""
        cfg = load_config()
        if not is_request_authenticated(request, cfg):
            return JSONResponse({"status": "forbidden", "message": "Yêu cầu mã PIN bảo vệ gia đình để nghe âm thanh phòng ngủ."}, status_code=401)
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
        t_url = cfg.get("remote_access_url", "")
        tunnel_info = tunnel_manager.get_status() if tunnel_manager else {"active": bool(t_url), "url": t_url, "type": "config"}
        if not tunnel_info.get("url") and t_url:
            tunnel_info["url"] = t_url
            tunnel_info["active"] = True

        vaccine_summary = {}
        if vaccine_tracker:
            b_date = cfg.get("baby_birth_date", "2026-09-05")
            v_sched = vaccine_tracker.get_schedule(b_date)
            vaccine_summary = {
                "has_urgent_due": v_sched.get("has_urgent_due", False),
                "due_count": len(v_sched.get("due_or_overdue_vaccines", [])),
                "items": v_sched.get("due_or_overdue_vaccines", [])[:3],
                "next_milestone_name": v_sched.get("next_due_milestone", {}).get("name", "") if v_sched.get("next_due_milestone") else "",
                "next_due_date": v_sched.get("next_due_milestone", {}).get("due_date", "") if v_sched.get("next_due_milestone") else ""
            }

        return {
            "vision": vis_st,
            "audio": aud_st,
            "music": music_player.get_status(),
            "sleep": sleep_st,
            "gemini": gemini_verifier.get_status() if gemini_verifier else {},
            "tunnel": tunnel_info,
            "vaccine_alert": vaccine_summary,
            "baby_profile": {
                "name": cfg.get("baby_name", "Bé Siu"),
                "age_months": cfg.get("baby_age_months", 3),
                "setup_completed": cfg.get("setup_completed", False)
            }
        }

    @app.get("/api/tunnel-status")
    def get_tunnel_status():
        cfg = load_config()
        t_url = cfg.get("remote_access_url", "")
        if tunnel_manager is not None:
            st = tunnel_manager.get_status()
            if not st.get("url") and t_url:
                st["url"] = t_url
                st["active"] = True
            return st
        return {"active": bool(t_url), "url": t_url, "type": "config"}

    @app.post("/api/tunnel/restart")
    def restart_tunnel():
        if tunnel_manager is None:
            return {"success": False, "error": "Chưa kích hoạt Tunnel Manager"}
        new_url = tunnel_manager.restart()
        if new_url:
            alert_manager.update_config({"remote_access_url": new_url})
            return {"success": True, "url": new_url}
        return {"success": False, "error": "Không thể lấy link mới lúc này"}

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

    def _enrich_summary_with_health_metrics(summary_dict: dict) -> dict:
        cfg = load_config()
        b_date = cfg.get("baby_birth_date", "2026-09-05")
        gender = cfg.get("baby_gender", "boy")
        age_info = calculate_exact_age(b_date)
        summary_dict["baby_name"] = cfg.get("baby_name", "Bé")
        summary_dict["age_display"] = age_info["age_display"]
        summary_dict["age_stage"] = age_info["age_stage"]

        growth_eval = growth_tracker.evaluate_growth(b_date, gender)
        if growth_eval.get("has_data") and growth_eval.get("latest_record"):
            summary_dict["growth_data"] = {
                "weight_kg": growth_eval["latest_record"].get("weight_kg"),
                "height_cm": growth_eval["latest_record"].get("height_cm"),
                "weight_status": growth_eval.get("weight_status"),
                "length_status": growth_eval.get("length_status"),
                "growth_velocity": growth_eval.get("growth_velocity")
            }

        daily_counts = alert_manager.get_daily_event_counts() if alert_manager else {}
        summary_dict["crying_count"] = daily_counts.get("crying_count", 0)
        summary_dict["cough_count"] = daily_counts.get("cough_count", 0)
        summary_dict["apnea_count"] = daily_counts.get("apnea_count", 0)

        # Bổ sung Cụm Biến Động Ban Ngày (Hourly Cluster Delta Summary)
        if hasattr(sleep_tracker, "get_health_cluster_summary"):
            summary_dict["delta_summary"] = sleep_tracker.get_health_cluster_summary()

        vis_st = vision_tracker.get_status() if vision_tracker else {}
        summary_dict["avg_bpm"] = vis_st.get("breathing_bpm", 36.0)

        hist = summary_dict.get("daily_history", [])
        if hist and len(hist) > 0:
            summary_dict["yesterday_sleep"] = hist[0]

        # Bổ sung cảnh báo Lịch Tiêm Chủng Quốc Gia & Dịch Vụ
        if vaccine_tracker:
            v_alert = vaccine_tracker.format_telegram_alert(b_date, cfg.get("baby_name", "Bé"))
            if v_alert:
                summary_dict["vaccine_alert_text"] = v_alert

        # Bổ sung 1 Ngày 1 Câu Chuyện Ý Nghĩa & Dạy Con
        if daily_story_tracker:
            try:
                story = daily_story_tracker.get_today_story(
                    gemini_verifier=gemini_verifier,
                    baby_name=cfg.get("baby_name", "Bé"),
                    age_display=age_info.get("age_display", "")
                )
                if story:
                    summary_dict["daily_story"] = story
            except Exception as e:
                print(f"[WebServer] Lỗi lấy câu chuyện ngày: {e}")

        return summary_dict

    def _trigger_morning_ai_sleep_report(summary_snapshot: dict):
        if _ai_sleep_State["generating"] or gemini_verifier is None or not gemini_verifier.is_ready():
            return
        _ai_sleep_State["generating"] = True

        def _bg():
            try:
                enriched = _enrich_summary_with_health_metrics(summary_snapshot.copy())
                res = gemini_verifier.generate_daily_sleep_report(enriched)
                if res.get("success") and res.get("report"):
                    sleep_tracker.save_daily_ai_report(res["report"])
                    _ai_sleep_State["last_auto_date"] = summary_snapshot.get("today_date", "")
                    tele_text = res["report"].get("telegram_text")
                    if tele_text and alert_manager is not None:
                        alert_manager.send_telegram_text(tele_text, pin=True, tag_recipients=True)
                        print("[WebServer] 📌 Đã gửi và ghim Báo cáo Sức khỏe Buổi sáng lên Telegram!")
            finally:
                _ai_sleep_State["generating"] = False

        threading.Thread(target=_bg, daemon=True).start()

    # Luồng chạy ngầm điều phối Bác Sĩ Nhi Khoa 07:00 Sáng & Giám sát Cụm Bất Thường Ban Ngày
    def _start_background_pediatric_scheduler():
        last_anomaly_check_time = 0.0
        while True:
            try:
                time.sleep(20)
                now_dt = datetime.now()
                now_t = time.time()

                # 1. Đúng 07:00 sáng: Thu thập dữ liệu 24h & kích hoạt Gemini chấm điểm gửi Telegram
                if now_dt.hour == 7 and 0 <= now_dt.minute <= 15:
                    cur_cycle = getattr(sleep_tracker, "today_date", "")
                    if _ai_sleep_State.get("last_auto_date") != cur_cycle:
                        has_rep = (
                            sleep_tracker.daily_ai_report is not None
                            and sleep_tracker.daily_ai_report.get("date") == cur_cycle
                        )
                        if not has_rep and not _ai_sleep_State["generating"]:
                            _ai_sleep_State["last_auto_date"] = cur_cycle
                            cfg = load_config()
                            age_m = int(cfg.get("baby_age_months", 1))
                            vis_st = vision_tracker.get_status() if vision_tracker else {}
                            aud_st = audio_detector.get_status() if audio_detector else {}
                            snap = sleep_tracker.get_summary(
                                adult_holding=vis_st.get("adult_holding", False),
                                is_crying=aud_st.get("is_crying", False),
                                age_months=age_m
                            )
                            print("[WebServer] ⏰ ĐÚNG 07:00 SÁNG: Kích hoạt Bác Sĩ AI tổng hợp bệnh án 24h...")
                            _trigger_morning_ai_sleep_report(snap)

                # 2. Giám sát Cụm Biến Động Khẩn Cấp trong ngày (Micro-Triage)
                if (now_t - last_anomaly_check_time) >= 90.0:
                    last_anomaly_check_time = now_t
                    if hasattr(sleep_tracker, "check_health_cluster_anomaly"):
                        anomaly = sleep_tracker.check_health_cluster_anomaly(window_minutes=30)
                        if anomaly.get("has_anomaly") and anomaly.get("severity") in ["CRITICAL", "HIGH"]:
                            print(f"[WebServer] 🚨 PHÁT HIỆN CỤM BẤT THƯỜNG: {anomaly.get('reason')}")
                            # Nếu có nguy cơ sặc hoặc ngưng thở, AlertManager đã có sẵn cooldown nội bộ
                            if alert_manager:
                                alert_manager.trigger_event("cough", message=anomaly.get("reason"), extra_info=anomaly.get("counts"))
            except Exception as se:
                print(f"[WebServer] Lỗi background pediatric scheduler: {se}")

    threading.Thread(target=_start_background_pediatric_scheduler, daemon=True).start()

    @app.get("/api/sleep_summary")
    def get_sleep_summary():
        vis_st = vision_tracker.get_status() if vision_tracker else {}
        aud_st = audio_detector.get_status() if audio_detector else {}
        cfg = load_config()
        age_m = int(cfg.get("baby_age_months", 1))
        summary = sleep_tracker.get_summary(
            adult_holding=vis_st.get("adult_holding", False),
            is_crying=aud_st.get("is_crying", False),
            age_months=age_m
        )
        b_date = cfg.get("baby_birth_date", "2026-09-05")
        summary["age_info"] = calculate_exact_age(b_date)
        summary["baby_name"] = cfg.get("baby_name", "Bé")
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
        enriched = _enrich_summary_with_health_metrics(summary)
        res = gemini_verifier.generate_daily_sleep_report(enriched)
        if res.get("success") and res.get("report"):
            sleep_tracker.save_daily_ai_report(res["report"])
            tele_text = res["report"].get("telegram_text")
            if tele_text and alert_manager is not None:
                alert_manager.send_telegram_text(tele_text, pin=True, tag_recipients=True)
            return {
                "success": True,
                "report": res["report"],
                "summary": sleep_tracker.get_summary(
                    adult_holding=vis_st.get("adult_holding", False),
                    is_crying=aud_st.get("is_crying", False)
                )
            }
        return {"success": False, "error": res.get("error", "Không thể tạo báo cáo AI")}

    @app.post("/api/sleep/pin-telegram")
    def pin_sleep_report_to_telegram():
        if alert_manager is None:
            return {"success": False, "error": "Chưa khởi tạo Alert Manager"}
        report = sleep_tracker.daily_ai_report
        tele_text = report.get("telegram_text") if report else None
        if not tele_text:
            if gemini_verifier is None or not gemini_verifier.is_ready():
                return {"success": False, "error": "Chưa có báo cáo và chưa cấu hình Gemini API Key"}
            vis_st = vision_tracker.get_status()
            aud_st = audio_detector.get_status()
            summary = sleep_tracker.get_summary(
                adult_holding=vis_st.get("adult_holding", False),
                is_crying=aud_st.get("is_crying", False)
            )
            enriched = _enrich_summary_with_health_metrics(summary)
            res = gemini_verifier.generate_daily_sleep_report(enriched)
            if res.get("success") and res.get("report"):
                sleep_tracker.save_daily_ai_report(res["report"])
                tele_text = res["report"].get("telegram_text")
            else:
                return {"success": False, "error": res.get("error", "Không thể tạo báo cáo")}

        ok = alert_manager.send_telegram_text(tele_text, pin=True, tag_recipients=True)
        if ok:
            return {"success": True, "message": "Đã gửi và ghim Báo cáo Giấc ngủ Nhi khoa lên Telegram!"}
        return {"success": False, "error": "Không gửi được qua Telegram. Vui lòng kiểm tra lại Bot Token và Chat ID trong Cài đặt."}

    # --- CUTE MOMENTS ALBUM APIS (CÓ GIÁM KHẢO THẨM MỸ & KIỂM DUYỆT NGƯỜI ĐI CÙNG QUA GEMINI) ---
    moments_dir = os.path.join(BASE_DIR, "moments")
    os.makedirs(moments_dir, exist_ok=True)

    @app.post("/api/take-snapshot")
    def take_snapshot():
        # 1. Lấy khung hình an toàn qua get_snapshot_frame (không gọi OpenCV detect đồng thời gây deadlock)
        frame = None
        face_info = None
        if hasattr(vision_tracker, "get_snapshot_frame"):
            frame, face_info = vision_tracker.get_snapshot_frame()
        if frame is None:
            frame = vision_tracker.get_latest_frame(annotated=False)
        if frame is None:
            frame = vision_tracker.get_latest_frame(annotated=True)
        if frame is None:
            return {"success": False, "error": "Không lấy được khung hình từ camera"}

        # 2. Ảnh chụp thủ công của bố mẹ: Luôn luôn lưu khung hình chất lượng cao đầy đủ góc nhìn gia đình
        frame_to_save = frame.copy()
        ts_moment = datetime.now().strftime("%Y%m%d_%H%M%S")
        moment_fn = f"moment_{ts_moment}.jpg"
        moment_path = os.path.join(moments_dir, moment_fn)
        snapshot_path = os.path.join(snapshots_dir, moment_fn)

        # Lưu tệp đĩa ngay lập tức (chỉ mất ~0.003s)
        cv2.imwrite(moment_path, frame_to_save)
        cv2.imwrite(snapshot_path, frame_to_save)

        # Gán metadata ban đầu để giao diện hiển thị ngay lập tức
        base_caption = f"Khoảnh khắc kỷ niệm của bé ({datetime.now().strftime('%H:%M:%S')})"
        base_meta = {
            "checked_by_gemini": False,
            "approved": True,
            "privacy_safe": True,
            "baby_face_clear": True,
            "caption_vi": base_caption,
            "aesthetic_score": 9,
            "has_other_person": True,
            "is_manual": True
        }
        if gemini_verifier is not None:
            gemini_verifier.save_moment_metadata(moment_fn, base_meta)

        # 3. ĐẨY XỬ LÝ NẶNG (Gemini Chú Thích & Đồng Bộ Google Drive) SANG THREAD CHẠY NGẦM
        # Tuyệt đối không chặn luồng camera và HTTP stream /video_feed của người dùng!
        def _bg_snapshot_tasks(m_path, m_fn, img_data):
            try:
                cfg = load_config()
                # A. Tự động đồng bộ lên Google Drive nếu đã bật
                from google_drive_sync import save_moment_to_google_drive
                save_moment_to_google_drive(img_data, cfg)

                # B. Gọi Gemini sinh câu chú thích ấm áp trong nền
                if gemini_verifier is not None and gemini_verifier.is_ready():
                    eval_res = gemini_verifier.evaluate_cute_moment(img_data, is_manual=True)
                    if eval_res and isinstance(eval_res, dict):
                        eval_res["approved"] = True
                        eval_res["is_manual"] = True
                        gemini_verifier.save_moment_metadata(m_fn, eval_res)
                        caption_final = eval_res.get("caption_vi", base_caption)
                        alert_manager.trigger_event("manual", caption_final, frame=img_data)
            except Exception as ex:
                print(f"[Snapshot BG] Lỗi xử lý nền: {ex}")

        threading.Thread(target=_bg_snapshot_tasks, args=(moment_path, moment_fn, frame_to_save), daemon=True).start()

        return {
            "success": True,
            "filename": moment_fn,
            "url": f"/api/moments/{moment_fn}",
            "caption_vi": base_caption,
            "checked_by_gemini": True,
            "auto_cropped": False
        }

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

    @app.get("/api/settings/google-drive")
    def get_google_drive_settings():
        cfg = load_config()
        from google_drive_sync import get_google_drive_status
        return get_google_drive_status(cfg)

    @app.post("/api/settings/google-drive/scan")
    def scan_google_drive_settings():
        from google_drive_sync import detect_macos_google_drive_path
        detected = detect_macos_google_drive_path()
        return {
            "success": bool(detected),
            "detected_path": detected,
            "message": f"Đã tìm thấy Google Drive: {detected}" if detected else "Chưa phát hiện ứng dụng Google Drive trên máy."
        }

    @app.post("/api/settings/google-drive")
    def update_google_drive_settings(payload: dict):
        cfg = load_config()
        if "enabled" in payload:
            cfg["google_drive_enabled"] = bool(payload["enabled"])
        if "path" in payload:
            cfg["google_drive_path"] = str(payload["path"]).strip()
        save_config(cfg)
        from google_drive_sync import get_google_drive_status
        return {
            "success": True,
            "status": get_google_drive_status(cfg)
        }

    @app.get("/api/license/status")
    def get_license_status():
        cfg = load_config()
        lm = LicenseManager(cfg)
        return lm.get_status()

    @app.post("/api/license/activate")
    def activate_license(payload: dict):
        key = str(payload.get("license_key", "")).strip()
        cfg = load_config()
        lm = LicenseManager(cfg)
        res = lm.activate_key(key)
        return res

    @app.post("/api/license/self-activate")
    def self_activate_license():
        """Dành riêng cho tác giả/nhà phát triển: tự sinh và kích hoạt Master Lifetime Key cho máy hiện tại."""
        mid = get_machine_fingerprint()
        key = generate_license_key(mid, tier="LIFETIME")
        cfg = load_config()
        cfg["license_key"] = key
        cfg["developer_mode"] = True
        save_config(cfg)
        lm = LicenseManager(cfg)
        return {
            "success": True,
            "message": "Đã tự kích hoạt quyền Tác Giả (Developer Master Lifetime) thành công!",
            "license_key": key,
            "status": lm.get_status()
        }

    @app.get("/api/license/auto-check")
    def auto_check_license():
        """
        Endpoint kiểm tra trạng thái kích hoạt tự động theo thời gian thực cho popup thanh toán.
        Tự động truy vấn cloud verify trên babyguard.site nếu là máy khách hàng chưa kích hoạt.
        """
        cfg = load_config()
        lm = LicenseManager(cfg)
        status = lm.get_status()

        # Nếu chưa kích hoạt vĩnh viễn, thử kiểm tra xác thực qua babyguard.site
        if not status.get("is_lifetime") and status.get("status") != "activated":
            mid = get_machine_fingerprint()
            short_id = mid.split("-")[-1] if "-" in mid else mid[:6]
            
            # 1. Kiểm tra trong paid_licenses.json nội bộ trước (nếu là server chính)
            paid_path = os.path.join(BASE_DIR, "paid_licenses.json")
            if os.path.exists(paid_path):
                try:
                    with open(paid_path, "r", encoding="utf-8") as pf:
                        paid_data = json.load(pf)
                    if short_id in paid_data or mid in paid_data:
                        rec = paid_data.get(short_id) or paid_data.get(mid)
                        new_key = rec.get("license_key") or generate_license_key(mid, tier="LIFETIME")
                        cfg["license_key"] = new_key
                        cfg["license_activated_via"] = "cloud_sepay_auto"
                        cfg["license_activated_at"] = datetime.now().isoformat()
                        save_config(cfg)
                        lm = LicenseManager(cfg)
                        status = lm.get_status()
                except Exception as e:
                    print(f"[LicenseAutoCheck] Lỗi kiểm tra file cục bộ: {e}")

            # 2. Nếu vẫn chưa kích hoạt và không phải chính babyguard.site thì gọi cloud API
            if not status.get("is_lifetime") and cfg.get("remote_access_url") != "https://babyguard.site":
                try:
                    import urllib.request
                    cloud_url = f"https://babyguard.site/api/license/cloud-verify?short_id={short_id}&machine_id={mid}"
                    req = urllib.request.Request(cloud_url, headers={"User-Agent": "BabyGuard-Client/2.0"})
                    with urllib.request.urlopen(req, timeout=2.5) as resp:
                        if resp.status == 200:
                            cdata = json.loads(resp.read().decode("utf-8"))
                            if cdata.get("valid") and cdata.get("license_key"):
                                new_key = cdata["license_key"]
                                cfg["license_key"] = new_key
                                cfg["license_activated_via"] = "cloud_sepay_remote"
                                cfg["license_activated_at"] = datetime.now().isoformat()
                                save_config(cfg)
                                lm = LicenseManager(cfg)
                                status = lm.get_status()
                except Exception:
                    pass

        return {
            "valid": status.get("valid", False),
            "tier": status.get("tier", "TRIAL"),
            "is_lifetime": status.get("is_lifetime", False),
            "status": status.get("status", "trial"),
            "machine_id": status.get("machine_id", ""),
            "license_key": cfg.get("license_key", "")
        }

    @app.get("/api/license/cloud-verify")
    def cloud_verify_license(short_id: str = "", machine_id: str = ""):
        """
        Dịch vụ Xác thực Giấy phép Đám mây (Cloud Licensing Verification) trên babyguard.site:
        Khách hàng ở bất kỳ đâu chuyển khoản 49k, máy tính của họ sẽ gọi về đây để nhận License Key tự động.
        """
        short_id = short_id.strip().upper()
        machine_id = machine_id.strip().upper()
        if not short_id and not machine_id:
            return {"valid": False, "reason": "missing_id"}

        paid_path = os.path.join(BASE_DIR, "paid_licenses.json")
        paid_data = {}
        if os.path.exists(paid_path):
            try:
                with open(paid_path, "r", encoding="utf-8") as pf:
                    paid_data = json.load(pf)
            except Exception:
                paid_data = {}

        # Tra cứu theo short_id hoặc machine_id
        matched_rec = None
        for k, v in paid_data.items():
            k_up = str(k).upper()
            if (short_id and (short_id in k_up or k_up in short_id)) or (machine_id and (machine_id in k_up or k_up in machine_id)):
                matched_rec = v
                break

        if matched_rec:
            target_mid = machine_id or f"BG-MAC-{short_id}"
            key = matched_rec.get("license_key") or generate_license_key(target_mid, tier="LIFETIME")
            return {
                "valid": True,
                "status": "activated",
                "tier": "LIFETIME",
                "is_lifetime": True,
                "license_key": key,
                "amount_paid": matched_rec.get("amount", 49000),
                "message": "Xác thực thanh toán 49.000đ thành công. Đã cấp bản quyền Vĩnh Viễn!"
            }

        return {
            "valid": False,
            "status": "pending_payment",
            "message": "Chưa ghi nhận thanh toán cho mã máy này. Vui lòng quét mã VietQR và chờ 3-5 giây."
        }

    @app.get("/api/sepay/info")
    def get_sepay_info():
        mid = get_machine_fingerprint()
        short_id = mid.split("-")[-1] if "-" in mid else mid[:6]
        transfer_content = f"BG {short_id}"
        
        cfg = load_config()
        sepay_cfg_path = os.path.join(BASE_DIR, "sepay_config.json")
        sepay_cfg = {}
        if os.path.exists(sepay_cfg_path):
            try:
                with open(sepay_cfg_path, "r", encoding="utf-8") as f:
                    sepay_cfg = json.load(f)
            except Exception:
                pass

        merchant_id = sepay_cfg.get("merchant_id", "SP-TEST-NV5B9824")
        amount = int(sepay_cfg.get("default_amount", 49000))
        tunnel_url = cfg.get("remote_access_url", "https://babyguard.site")
        ipn_url = f"{tunnel_url.rstrip('/')}/api/sepay/ipn"

        bank_bin = sepay_cfg.get("bank_bin", "970422")
        acc_num = sepay_cfg.get("account_number", "1550107316004")
        acc_name = sepay_cfg.get("account_name", "Nguyen Vu Truong Thanh")
        encoded_name = acc_name.replace(" ", "%20")
        encoded_content = transfer_content.replace(" ", "%20")

        return {
            "merchant_id": merchant_id,
            "machine_id": mid,
            "short_id": short_id,
            "transfer_content": transfer_content,
            "amount": amount,
            "currency": "VND",
            "bank_name": "MBBank",
            "account_number": acc_num,
            "account_name": acc_name,
            "ipn_url": ipn_url,
            "checkout_url": f"https://my.sepay.vn/pg/checkout?merchant_id={merchant_id}&amount={amount}&order_id=INV-{short_id}",
            "vietqr_url": f"https://img.vietqr.io/image/{bank_bin}-{acc_num}-compact2.png?amount={amount}&addInfo={encoded_content}&accountName={encoded_name}"
        }

    @app.get("/api/sepay/ipn")
    def sepay_ipn_health():
        return {
            "status": "online",
            "service": "BabyGuard AI SePay IPN Webhook Receiver",
            "method_required": "POST",
            "endpoint": "/api/sepay/ipn",
            "time": datetime.now().isoformat()
        }

    @app.post("/api/sepay/ipn")
    async def sepay_ipn_webhook(request: Request):
        """
        Nhận thông báo thanh toán tức thì (IPN / Webhook) từ SePay.
        Hỗ trợ cả 2 định dạng:
        1. Cổng thanh toán SePay PG (ORDER_PAID)
        2. Webhook biến động số dư SePay Hub (transferType: in)
        3. Test webhook từ SePay dashboard (Gửi test)
        Tự động tạo Key Vĩnh Viễn, lưu vào cấu hình máy và gửi thông báo Telegram.
        """
        try:
            body = await request.json()
        except Exception:
            body = {}

        print(f"[SePay IPN] Nhận webhook từ SePay: {body}")

        # Kiểm tra nếu là webhook test rỗng hoặc ping
        if body.get("test") is True or body.get("notification_type") == "TEST":
            return {"success": True, "message": "Test ping acknowledged by BabyGuard AI"}

        # Trích xuất dữ liệu giao dịch
        amount = 0
        order_code = ""
        trans_id = str(body.get("id") or body.get("transaction_id") or int(time.time()))

        if "order" in body or body.get("notification_type") == "ORDER_PAID":
            order_data = body.get("order", {})
            amount = float(order_data.get("order_amount", 0) or order_data.get("amount", 0) or 49000)
            order_code = str(order_data.get("order_invoice_number") or order_data.get("id") or "")
        elif "transferAmount" in body or body.get("transferType") == "in":
            amount = float(body.get("transferAmount", 0) or 49000)
            order_code = str(body.get("code") or body.get("content") or "")
        else:
            amount = float(body.get("amount", 0) or body.get("transferAmount", 0) or 49000)
            order_code = str(body.get("content") or body.get("description") or "BabyGuard Lifetime")

        # Trích xuất Machine Short ID nếu có trong nội dung chuyển khoản (VD: 'BG F7A7' hoặc 'BG 29BF')
        import re
        target_short_id = ""
        m_match = re.search(r'BG[\s_-]?([A-Za-z0-9]{4,16})', order_code, re.IGNORECASE)
        if m_match:
            target_short_id = m_match.group(1).upper()
        else:
            # Tìm trong cả raw payload
            raw_str = json.dumps(body)
            m_raw = re.search(r'BG[\s_-]?([A-Za-z0-9]{4,16})', raw_str, re.IGNORECASE)
            if m_raw:
                target_short_id = m_raw.group(1).upper()

        # Lưu lịch sử giao dịch SePay
        sepay_history_path = os.path.join(BASE_DIR, "sepay_transactions.json")
        history = []
        if os.path.exists(sepay_history_path):
            try:
                with open(sepay_history_path, "r", encoding="utf-8") as f:
                    history = json.load(f)
            except Exception:
                history = []

        tx_record = {
            "timestamp": datetime.now().isoformat(),
            "transaction_id": trans_id,
            "amount": amount,
            "order_code": order_code,
            "matched_short_id": target_short_id,
            "raw_payload": body
        }
        history.append(tx_record)
        try:
            with open(sepay_history_path, "w", encoding="utf-8") as f:
                json.dump(history[-100:], f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"[SePay IPN] Lỗi lưu lịch sử: {e}")

        # TỰ ĐỘNG TẠO VÀ LƯU BẢN QUYỀN VĨNH VIỄN VÀO CLOUD REGISTRY
        mid = get_machine_fingerprint()
        local_short_id = mid.split("-")[-1] if "-" in mid else mid[:6]
        
        target_machine_for_key = f"BG-MAC-{target_short_id}" if target_short_id else mid
        customer_lifetime_key = generate_license_key(target_machine_for_key, tier="LIFETIME")
        universal_key = generate_license_key("UNIVERSAL", tier="LIFETIME")

        # Ghi nhận vào paid_licenses.json để mọi máy khách hàng có thể gọi về lấy
        paid_path = os.path.join(BASE_DIR, "paid_licenses.json")
        paid_data = {}
        if os.path.exists(paid_path):
            try:
                with open(paid_path, "r", encoding="utf-8") as pf:
                    paid_data = json.load(pf)
            except Exception:
                paid_data = {}

        key_anchor = target_short_id or local_short_id
        paid_data[key_anchor] = {
            "short_id": key_anchor,
            "amount": amount,
            "transaction_id": trans_id,
            "order_code": order_code,
            "license_key": customer_lifetime_key,
            "universal_key": universal_key,
            "paid_at": datetime.now().isoformat()
        }
        try:
            with open(paid_path, "w", encoding="utf-8") as pf:
                json.dump(paid_data, pf, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"[SePay IPN] Lỗi ghi paid_licenses: {e}")

        # Nếu là thanh toán cho máy hiện tại (hoặc không chỉ định thì mặc định active máy hiện tại)
        if not target_short_id or target_short_id == local_short_id or target_short_id in mid:
            cfg = load_config()
            cfg["license_key"] = customer_lifetime_key
            cfg["license_activated_via"] = "sepay_auto"
            cfg["license_activated_at"] = datetime.now().isoformat()
            cfg["last_payment"] = {
                "amount": amount,
                "transaction_id": trans_id,
                "order_code": order_code,
                "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            save_config(cfg)
            LicenseManager(cfg)

        # Gửi thông báo chúc mừng tới Telegram của phụ huynh / Tác giả
        tele_msg = (
            f"🎉 <b>[ĐÃ NHẬN THANH TOÁN 49.000đ - BABYGUARD AI]</b>\n\n"
            f"💰 <b>Số tiền:</b> {amount:,.0f} VNĐ\n"
            f"📋 <b>Mã GD / Nội dung:</b> <code>{order_code or trans_id}</code>\n"
            f"🆔 <b>Mã Máy Khách:</b> <code>{target_short_id or local_short_id}</code>\n"
            f"🔑 <b>Key Vĩnh Viễn:</b> <code>{customer_lifetime_key}</code>\n"
            f"🌐 <b>Key Toàn Năng:</b> <code>{universal_key}</code>\n\n"
            f"✨ <i>Hệ thống đã TỰ ĐỘNG CẤP BẢN QUYỀN VĨNH VIỄN! Khách hàng có thể sử dụng trọn đời không giới hạn.</i> ❤️"
        )
        if alert_manager is not None:
            try:
                alert_manager.send_telegram_text(tele_msg, pin=True, tag_recipients=True)
            except Exception as e:
                print(f"[SePay IPN] Lỗi gửi telegram: {e}")

        return {
            "success": True,
            "message": "Payment verified and lifetime license activated successfully!",
            "status": "LICENSE_ACTIVATED",
            "license_key": customer_lifetime_key,
            "transaction_id": trans_id
        }

    @app.post("/api/sepay/simulate-test-payment")
    def simulate_sepay_test_payment():
        """Cho phép trải nghiệm luồng tự động kích hoạt tức thì 100% trong 1 click."""
        mid = get_machine_fingerprint()
        lifetime_key = generate_license_key(mid, tier="LIFETIME")
        cfg = load_config()
        cfg["license_key"] = lifetime_key
        cfg["license_activated_via"] = "sepay_simulated_test"
        cfg["license_activated_at"] = datetime.now().isoformat()
        save_config(cfg)
        lm = LicenseManager(cfg)

        tele_msg = (
            f"🧪 <b>[KIỂM THỬ KÍCH HOẠT TỰ ĐỘNG - SEPAY TEST]</b>\n\n"
            f"💰 <b>Số tiền mô phỏng:</b> 199,000 VNĐ\n"
            f"🔑 <b>Key Bản Quyền:</b> <code>{lifetime_key}</code>\n"
            f"✅ <i>Hệ thống đã tự động kích hoạt vĩnh viễn thành công mà không cần gõ key!</i>"
        )
        if alert_manager is not None:
            try:
                alert_manager.send_telegram_text(tele_msg, pin=False)
            except Exception as e:
                print(f"[SePay IPN] Lỗi gửi telegram: {e}")

        return {
            "success": True,
            "message": "Mô phỏng thanh toán thành công! Bản quyền đã được kích hoạt vĩnh viễn tự động.",
            "license_key": lifetime_key,
            "status": lm.get_status()
        }

    @app.get("/api/system/audit")
    def run_system_audit():
        cfg = load_config()
        lm = LicenseManager(cfg)
        lic_stat = lm.get_status()

        # 1. Camera check
        cam_ok = vision_tracker is not None and getattr(vision_tracker, "is_running", False)
        # 2. Audio check
        audio_ok = audio_detector is not None and getattr(audio_detector, "is_running", False)
        # 3. Models check
        yolo_path = os.path.join(BASE_DIR, "models", "yolov8n-pose.pt")
        yamnet_path = os.path.join(BASE_DIR, "models", "yamnet.tflite")
        models_ok = os.path.exists(yolo_path) and os.path.exists(yamnet_path)
        # 4. Gemini check
        gemini_key = str(cfg.get("gemini_api_key", "")).strip()
        gemini_ok = bool(gemini_key and len(gemini_key) > 10)
        # 5. Telegram check
        tg_token = str(cfg.get("telegram_bot_token", "")).strip()
        tg_chat = str(cfg.get("telegram_chat_id", "")).strip()
        tg_ok = bool(tg_token and tg_chat)
        # 6. Medical RAG check
        proto_path = os.path.join(BASE_DIR, "medical_knowledge", "infant_first_aid_protocols.json")
        rag_ok = os.path.exists(proto_path)
        # 7. Drive check
        from google_drive_sync import get_google_drive_status
        drive_stat = get_google_drive_status(cfg)

        return {
            "timestamp": datetime.now().isoformat(),
            "overall_healthy": cam_ok and audio_ok and models_ok and lic_stat.get("valid", False),
            "license": lic_stat,
            "subsystems": {
                "camera_stream": {"status": "online" if cam_ok else "offline", "healthy": cam_ok},
                "audio_detector": {"status": "online" if audio_ok else "offline", "healthy": audio_ok},
                "ai_models": {"status": "loaded" if models_ok else "missing", "healthy": models_ok},
                "gemini_hybrid_cloud": {"status": "configured" if gemini_ok else "not_configured", "healthy": gemini_ok},
                "telegram_alerts": {"status": "configured" if tg_ok else "unpaired", "healthy": tg_ok},
                "medical_rag_protocols": {"status": "ready" if rag_ok else "missing", "healthy": rag_ok},
                "google_drive_sync": drive_stat
            }
        }

    class ConfigToggle(BaseModel):
        key: str
        value: bool

    @app.post("/api/config/toggle")
    def toggle_config(payload: ConfigToggle):
        cfg = load_config()
        if payload.key == "language":
            val = "en" if payload.value is True else ("vi" if payload.value is False else str(payload.value))
            cfg["language"] = val
        else:
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

    # --- PEDIATRIC GROWTH TRACKING & MONTHLY REMINDER APIS ---
    @app.get("/api/growth")
    def get_growth_api():
        cfg = load_config()
        b_date = cfg.get("baby_birth_date", "2026-09-05")
        gender = cfg.get("baby_gender", "boy")
        growth_eval = growth_tracker.evaluate_growth(b_date, gender)
        return {
            "success": True,
            "baby_name": cfg.get("baby_name", "Bé"),
            "baby_birth_date": b_date,
            "baby_gender": gender,
            "age_info": calculate_exact_age(b_date),
            "growth_evaluation": growth_eval,
            "ai_analysis": growth_tracker.get_latest_ai_analysis(),
            "monthly_reminder": growth_tracker.should_trigger_monthly_reminder()
        }

    class GrowthRecordPayload(BaseModel):
        weight_kg: float
        height_cm: float
        head_circ_cm: float | None = None
        date: str | None = None
        note: str | None = ""

    @app.post("/api/growth")
    def add_growth_api(payload: GrowthRecordPayload):
        rec = growth_tracker.add_record(
            weight_kg=payload.weight_kg,
            height_cm=payload.height_cm,
            head_circ_cm=payload.head_circ_cm,
            record_date_str=payload.date,
            note=payload.note
        )
        cfg = load_config()
        b_date = cfg.get("baby_birth_date", "2026-09-05")
        gender = cfg.get("baby_gender", "boy")
        growth_eval = growth_tracker.evaluate_growth(b_date, gender)

        # Gọi Gemini AI so sánh lần này với lần trước & đưa ra đề xuất cho ba mẹ
        ai_analysis = None
        if gemini_verifier is not None and gemini_verifier.is_ready():
            try:
                prev_rec = None
                history = growth_eval.get("history", [])
                for idx, r in enumerate(history):
                    if r.get("date") == rec.get("date") and idx > 0:
                        prev_rec = history[idx - 1]
                        break
                if not prev_rec and len(history) >= 2:
                    prev_rec = history[-2]

                ai_res = gemini_verifier.consult_growth_progress(
                    baby_name=cfg.get("baby_name", "Bé"),
                    age_display=growth_eval.get("age_info", {}).get("age_display", "1.5 tháng tuổi"),
                    gender="Bé Trai" if gender == "boy" else "Bé Gái",
                    current_rec=rec,
                    prev_rec=prev_rec,
                    who_standard=growth_eval.get("who_standards")
                )
                if ai_res.get("success"):
                    ai_analysis = ai_res.get("analysis")
                    growth_tracker.save_ai_analysis(ai_analysis)
            except Exception as e:
                print(f"[Growth] Lỗi gọi Gemini hội chẩn tăng trưởng: {e}")

        if not ai_analysis:
            ai_analysis = growth_tracker.get_latest_ai_analysis()

        return {
            "success": True,
            "record": rec,
            "growth_evaluation": growth_eval,
            "ai_analysis": ai_analysis,
            "monthly_reminder": growth_tracker.should_trigger_monthly_reminder()
        }

    @app.delete("/api/growth/{date_str}")
    def delete_growth_api(date_str: str):
        success = growth_tracker.delete_record(date_str)
        cfg = load_config()
        b_date = cfg.get("baby_birth_date", "2026-09-05")
        gender = cfg.get("baby_gender", "boy")
        growth_eval = growth_tracker.evaluate_growth(b_date, gender)
        return {
            "success": success,
            "growth_evaluation": growth_eval,
            "ai_analysis": growth_tracker.get_latest_ai_analysis(),
            "monthly_reminder": growth_tracker.should_trigger_monthly_reminder()
        }

    # =========================================================================
    # VACCINE TRACKER REST APIS (LỊCH TIÊM CHỦNG QUỐC GIA & DỊCH VỤ)
    # =========================================================================
    class VaccineUpdateRequest(BaseModel):
        vaccine_id: str
        completed: bool
        injected_date: str = ""
        note: str = ""

    class VaccineAddRequest(BaseModel):
        milestone_id: str = "milestone_2m"
        name: str
        disease: str = ""
        injected_date: str = ""
        note: str = ""
        completed: bool = False

    @app.get("/api/vaccines")
    def get_vaccines():
        cfg = load_config()
        b_date = cfg.get("baby_birth_date", "2026-09-05")
        sched = vaccine_tracker.get_schedule(b_date)
        sched["baby_name"] = cfg.get("baby_name", "Bé A Siu")
        return sched

    @app.post("/api/vaccines/update")
    def update_vaccine_status(req: VaccineUpdateRequest):
        success = vaccine_tracker.update_record(
            vaccine_id=req.vaccine_id,
            completed=req.completed,
            injected_date=req.injected_date,
            note=req.note
        )
        cfg = load_config()
        b_date = cfg.get("baby_birth_date", "2026-09-05")
        return {
            "success": success,
            "schedule": vaccine_tracker.get_schedule(b_date)
        }

    @app.post("/api/vaccines/add")
    def add_custom_vaccine(req: VaccineAddRequest):
        new_item = vaccine_tracker.add_custom_vaccine(
            milestone_id=req.milestone_id,
            name=req.name,
            disease=req.disease,
            injected_date=req.injected_date,
            note=req.note,
            completed=req.completed
        )
        cfg = load_config()
        b_date = cfg.get("baby_birth_date", "2026-09-05")
        return {
            "success": True,
            "item": new_item,
            "schedule": vaccine_tracker.get_schedule(b_date)
        }

    @app.delete("/api/vaccines/{vaccine_id}")
    def delete_custom_vaccine(vaccine_id: str):
        success = vaccine_tracker.delete_custom_vaccine(vaccine_id)
        cfg = load_config()
        b_date = cfg.get("baby_birth_date", "2026-09-05")
        return {
            "success": success,
            "schedule": vaccine_tracker.get_schedule(b_date)
        }

    # =========================================================================
    # DAILY STORY REST APIS (1 NGÀY 1 CÂU CHUYỆN Ý NGHĨA & DẠY CON)
    # =========================================================================
    @app.get("/api/daily-story")
    def get_daily_story():
        cfg = load_config()
        b_date = cfg.get("baby_birth_date", "2026-09-05")
        age_info = calculate_exact_age(b_date)
        story = daily_story_tracker.get_today_story(
            gemini_verifier=gemini_verifier,
            baby_name=cfg.get("baby_name", "Bé"),
            age_display=age_info.get("age_display", "")
        )
        return {"success": True, "story": story}

    @app.post("/api/daily-story/refresh")
    def refresh_daily_story():
        cfg = load_config()
        b_date = cfg.get("baby_birth_date", "2026-09-05")
        age_info = calculate_exact_age(b_date)
        story = daily_story_tracker.get_today_story(
            gemini_verifier=gemini_verifier,
            baby_name=cfg.get("baby_name", "Bé"),
            age_display=age_info.get("age_display", ""),
            force_refresh=True
        )
        return {"success": True, "story": story}

    class ConfigUpdate(BaseModel):
        baby_name: str = None
        baby_age_months: int = None
        baby_birth_date: str = None
        baby_gender: str = None
        remote_access_url: str = None
        safe_zone_polygon: list = None
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
        google_drive_enabled: bool = None
        google_drive_path: str = None
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

        def _clean_coord_val(val, default_val, max_d):
            try:
                v = float(val) if val is not None else default_val
                if v > 1.0:
                    v = v / 1000.0 if v <= 1000.0 else v / max_d
                return round(max(0.01, min(0.99, v)), 3)
            except Exception:
                return default_val

        if "safe_zone_polygon" in update_data and isinstance(update_data["safe_zone_polygon"], list) and len(update_data["safe_zone_polygon"]) == 4:
            clean_poly = []
            for p in update_data["safe_zone_polygon"]:
                clean_poly.append([
                    _clean_coord_val(p[0], 0.15, 1280.0),
                    _clean_coord_val(p[1], 0.18, 720.0)
                ])
            vision_tracker.safe_zone_polygon = clean_poly
            xs = [p[0] for p in vision_tracker.safe_zone_polygon]
            ys = [p[1] for p in vision_tracker.safe_zone_polygon]
            vision_tracker.safe_zone_left = round(min(xs), 3)
            vision_tracker.safe_zone_right = round(max(xs), 3)
            vision_tracker.safe_zone_top = round(min(ys), 3)
            vision_tracker.safe_zone_bottom = round(max(ys), 3)
            cfg["safe_zone_left"] = vision_tracker.safe_zone_left
            cfg["safe_zone_right"] = vision_tracker.safe_zone_right
            cfg["safe_zone_top"] = vision_tracker.safe_zone_top
            cfg["safe_zone_bottom"] = vision_tracker.safe_zone_bottom
            cfg["safe_zone_polygon"] = vision_tracker.safe_zone_polygon
            save_config(cfg)
        else:
            if "safe_zone_top" in update_data:
                vision_tracker.safe_zone_top = _clean_coord_val(cfg.get("safe_zone_top"), 0.18, 720.0)
                cfg["safe_zone_top"] = vision_tracker.safe_zone_top
            if "safe_zone_bottom" in update_data:
                vision_tracker.safe_zone_bottom = _clean_coord_val(cfg.get("safe_zone_bottom"), 0.95, 720.0)
                cfg["safe_zone_bottom"] = vision_tracker.safe_zone_bottom
                vision_tracker.danger_zone_y_percent = vision_tracker.safe_zone_bottom
            if "safe_zone_left" in update_data:
                vision_tracker.safe_zone_left = _clean_coord_val(cfg.get("safe_zone_left"), 0.15, 1280.0)
                cfg["safe_zone_left"] = vision_tracker.safe_zone_left
            if "safe_zone_right" in update_data:
                vision_tracker.safe_zone_right = _clean_coord_val(cfg.get("safe_zone_right"), 0.92, 1280.0)
                cfg["safe_zone_right"] = vision_tracker.safe_zone_right
                vision_tracker.danger_zone_x_percent = vision_tracker.safe_zone_right
            save_config(cfg)
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
        frame = vision_tracker.get_enhanced_low_light_frame() if hasattr(vision_tracker, "get_enhanced_low_light_frame") else None
        if frame is None:
            frame = vision_tracker.get_latest_frame(annotated=False)
        if frame is None:
            return {"success": False, "error": "Chưa nhận được khung hình từ camera."}
        res = gemini_verifier.auto_calibrate_crib(frame)
        if res.get("success") and "safe_zone" in res:
            sz = res["safe_zone"]
            if "polygon" in sz and isinstance(sz["polygon"], list) and len(sz["polygon"]) == 4:
                clean_poly = [[round(max(0.01, min(0.99, float(p[0]))), 3),
                               round(max(0.01, min(0.99, float(p[1]))), 3)] for p in sz["polygon"]]
                h, w = frame.shape[:2]
                if hasattr(vision_tracker, "_validate_crib_polygon") and not vision_tracker._validate_crib_polygon(clean_poly, w=w, h=h, check_baby=False):
                    return {"success": False, "error": "Khung nôi AI đề xuất không đạt tiêu chuẩn diện tích/hình học. Giữ nguyên an toàn."}
                if hasattr(vision_tracker, "_commit_safe_zone"):
                    vision_tracker._commit_safe_zone(clean_poly)
                else:
                    cfg = load_config()
                    cfg["safe_zone_polygon"] = clean_poly
                    cfg["safe_zone_top"] = round(min(p[1] for p in clean_poly), 3)
                    cfg["safe_zone_bottom"] = round(max(p[1] for p in clean_poly), 3)
                    cfg["safe_zone_left"] = round(min(p[0] for p in clean_poly), 3)
                    cfg["safe_zone_right"] = round(max(p[0] for p in clean_poly), 3)
                    save_config(cfg)
            else:
                cfg = load_config()
                cfg["safe_zone_top"] = round(max(0.01, min(0.99, float(sz["top"]))), 3)
                cfg["safe_zone_bottom"] = round(max(0.01, min(0.99, float(sz["bottom"]))), 3)
                cfg["safe_zone_left"] = round(max(0.01, min(0.99, float(sz["left"]))), 3)
                cfg["safe_zone_right"] = round(max(0.01, min(0.99, float(sz["right"]))), 3)
                save_config(cfg)
                vision_tracker.safe_zone_top = cfg["safe_zone_top"]
                vision_tracker.safe_zone_bottom = cfg["safe_zone_bottom"]
                vision_tracker.safe_zone_left = cfg["safe_zone_left"]
                vision_tracker.safe_zone_right = cfg["safe_zone_right"]
        return res

    @app.post("/api/gemini/audit-tracking")
    def manual_audit_tracking():
        """Kiểm tra chéo & hiệu chỉnh nóng khung Tracking của AI Local ngay lập tức bằng Gemini."""
        if gemini_verifier is None or not gemini_verifier.is_ready():
            return {"success": False, "error": "Vui lòng cấu hình Gemini API Key còn hạn trước."}
        raw_frame = vision_tracker.get_enhanced_low_light_frame() if hasattr(vision_tracker, "get_enhanced_low_light_frame") else None
        if raw_frame is None:
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
            "safe_zone": [
                round(max(0.01, min(0.99, float(vision_tracker.safe_zone_left))), 3),
                round(max(0.01, min(0.99, float(vision_tracker.safe_zone_top))), 3),
                round(max(0.01, min(0.99, float(vision_tracker.safe_zone_right))), 3),
                round(max(0.01, min(0.99, float(vision_tracker.safe_zone_bottom))), 3)
            ],
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

