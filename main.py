import os
import sys
import json
import time
import signal
import threading
import uvicorn

from vision_detector import VisionTracker
from audio_detector import AudioCryDetector
from alert_manager import AlertManager
from video_recorder import VideoRecorder
from music_player import MusicPlayer
from sleep_tracker import SleepTracker
from gemini_verifier import GeminiHybridVerifier
from tunnel_manager import TunnelManager
from web_server import create_app
from auto_updater import AutoUpdateWorker

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
YAMNET_MODEL_PATH = os.path.join(BASE_DIR, "models", "yamnet.tflite")
YOLO_MODEL_PATH = os.path.join(BASE_DIR, "models", "yolov8n-pose.pt")
MUSIC_DIR = os.path.join(BASE_DIR, "music")
SLEEP_DATA_PATH = os.path.join(BASE_DIR, "sleep_data.json")
LOGS_DIR = os.path.join(BASE_DIR, "logs")
os.makedirs(LOGS_DIR, exist_ok=True)


def load_config():
    if not os.path.exists(CONFIG_PATH):
        example_cfg = os.path.join(BASE_DIR, "config.example.json")
        if os.path.exists(example_cfg):
            import shutil
            shutil.copyfile(example_cfg, CONFIG_PATH)
        else:
            default_cfg = {
                "camera_index": 0, "camera_width": 1280, "camera_height": 720, "fps": 15,
                "audio_device_index": 0, "cry_threshold": 0.3, "cough_threshold": 0.25,
                "motion_threshold": 18.0, "alert_cooldown_seconds": 120, "telegram_enabled": False,
                "sound_alert_on_mac": True, "record_on_event": True, "prone_alert_enabled": True,
                "covered_face_alert": True, "danger_zone_enabled": True, "breathing_monitor_enabled": True,
                "sleep_analytics_enabled": True, "wake_window_predictor": True, "cute_moments_enabled": True,
                "web_port": 8080, "web_host": "0.0.0.0"
            }
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(default_cfg, f, indent=4)
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def main():
    print("=" * 60)
    print("   BABYGUARD AI - SMART BABY MONITOR (COMMERCIAL EDITION)   ")
    print("=" * 60)

    config = load_config()

    # 1. Alert Manager & Recorders & Media & Gemini Hybrid Verifier
    alert_manager = AlertManager(config)
    video_recorder = VideoRecorder(config)
    music_player = MusicPlayer(music_dir=MUSIC_DIR)
    music_player.configure_adaptive(
        max_volume=float(config.get("lullaby_max_volume", 0.65)),
        adaptive_mic_mode=bool(config.get("lullaby_adaptive_mic", True)),
        target_mic_pct=int(config.get("lullaby_target_mic_pct", 32)),
        selected_track=config.get("selected_lullaby", "Tieng_on_trang_White_Noise.wav")
    )
    sleep_tracker = SleepTracker(data_path=SLEEP_DATA_PATH)
    gemini_verifier = GeminiHybridVerifier(config)

    # 2. Vision Tracker
    vision_tracker = None

    def handle_video_completion(mp4_path, thumb_path, base_name, event_type="danger"):
        caption = f"📹 <b>[CLIP QUAY LẠI SỰ KIỆN]</b>\nFile: <code>{base_name}.mp4</code>"
        alert_manager.send_telegram_video(mp4_path, caption, event_type=event_type)

    def on_motion(velocity):
        frame = vision_tracker.get_latest_frame(annotated=True)
        msg = f"Bé đang cựa quậy / thức giấc (Mức độ: {velocity:.1f} px)"
        # Tự động kích hoạt mềm Tiếng Ồn Trắng / Nhạc Không Lời (từ 4% tăng dần theo Mic) khi bé trằn trọc cựa quậy
        cur_cfg = load_config()
        if cur_cfg.get("auto_lullaby_on_cry", False) and not music_player.is_playing:
            track = cur_cfg.get("selected_lullaby", "Tieng_on_trang_White_Noise.wav")
            print(f"[BabyGuard AI] 🌊 Bé cựa quậy chuyển cữ -> Khởi động mềm Tiếng Ồn Trắng / Nhạc không lời (từ 4%): {track}")
            music_player.play_track(track, loop=True)

        if alert_manager.trigger_event(
            event_type="motion",
            message=msg,
            frame=frame,
            extra_info={"Tư thế": vision_tracker.sleep_pose, "Vận tốc cử động": f"{velocity:.1f} px"}
        ):
            video_recorder.trigger_recording(
                "motion",
                msg,
                on_complete_callback=lambda p, t, b: handle_video_completion(p, t, b, event_type="motion")
            )

    def on_prone():
        frame = vision_tracker.get_latest_frame(annotated=True)
        msg = "CẢNH BÁO NGUY HIỂM: Phát hiện bé nằm sấp / úp mặt xuống đệm!"
        if alert_manager.trigger_event(
            event_type="prone",
            message=msg,
            frame=frame,
            extra_info={"Tư thế": "Nằm sấp (Nguy cơ ngạt)", "Trạng thái": "Cần kiểm tra ngay"}
        ):
            video_recorder.trigger_recording("prone", msg, on_complete_callback=handle_video_completion)

    def on_covered_face():
        frame = vision_tracker.get_latest_frame(annotated=True)
        ai_note = gemini_verifier.last_consultation.get("summary_vi", "Cần kiểm tra bé ngay!")
        msg = f"CẢNH BÁO KHẨN CẤP: Mặt bé bị che khuất! ({ai_note})"
        sleep_tracker.record_health_event("covered_face", msg, severity="WARNING")
        if alert_manager.trigger_event(
            event_type="covered_face",
            message=msg,
            frame=frame,
            extra_info={"Nguy cơ": "Ngạt thở do vật che mặt", "Chẩn đoán AI": ai_note}
        ):
            video_recorder.trigger_recording("covered_face", msg, on_complete_callback=handle_video_completion)

    def on_danger_zone():
        frame = vision_tracker.get_latest_frame(annotated=True)
        msg = "CẢNH BÁO NGUY HIỂM: Bé đang lăn/di chuyển sát mép giường (nguy cơ ngã)!"
        sleep_tracker.record_health_event("danger_zone", msg, severity="WARNING")
        if alert_manager.trigger_event(
            event_type="danger_zone",
            message=msg,
            frame=frame,
            extra_info={"Vị trí": "Sát mép giường", "Hành động": "Bế hoặc chắn bé lại ngay"}
        ):
            video_recorder.trigger_recording("danger_zone", msg, on_complete_callback=handle_video_completion)

    def on_apnea():
        if not config.get("breathing_monitor_enabled", True):
            return
        frame = vision_tracker.get_latest_frame(annotated=True)
        msg = "CẢNH BÁO KHẨN CẤP: Không phát hiện nhịp thở lồng ngực bé quá 20 giây!"
        sleep_tracker.record_health_event("apnea", msg, severity="URGENT")
        if alert_manager.trigger_event(
            event_type="apnea",
            message=msg,
            frame=frame,
            extra_info={"Trạng thái": "Nguy cơ ngưng thở khi ngủ", "Hành động": "Kiểm tra bé ngay lập tức!"}
        ):
            video_recorder.trigger_recording("apnea", msg, on_complete_callback=handle_video_completion)

    active_cam_source = config.get("camera_index", 0)
    if config.get("camera_source_type") == "rtsp" and str(config.get("camera_rtsp_url", "")).strip():
        active_cam_source = str(config.get("camera_rtsp_url")).strip()

    vision_tracker = VisionTracker(
        model_path=YOLO_MODEL_PATH,
        camera_index=active_cam_source,
        width=config.get("camera_width", 1280),
        height=config.get("camera_height", 720),
        fps=config.get("fps", 15),
        motion_threshold=config.get("motion_threshold", 18.0),
        on_motion_callback=on_motion,
        on_prone_callback=on_prone,
        on_covered_face_callback=on_covered_face,
        on_danger_zone_callback=on_danger_zone,
        on_apnea_callback=on_apnea,
        frame_callback=video_recorder.add_video_frame,
        sleep_tracker=sleep_tracker,
        gemini_verifier=gemini_verifier,
        prone_alert_enabled=config.get("prone_alert_enabled", True),
        danger_zone_enabled=config.get("danger_zone_enabled", True),
        safe_zone_top=config.get("safe_zone_top", 0.08),
        safe_zone_bottom=config.get("safe_zone_bottom", config.get("danger_zone_y_percent", 0.98)),
        safe_zone_left=config.get("safe_zone_left", 0.01),
        safe_zone_right=config.get("safe_zone_right", config.get("danger_zone_x_percent", 0.99)),
        safe_zone_polygon=config.get("safe_zone_polygon"),
        covered_face_alert=config.get("covered_face_alert", True),
        breathing_monitor_enabled=config.get("breathing_monitor_enabled", True),
        cute_moments_enabled=config.get("cute_moments_enabled", True),
        moments_dir=os.path.join(BASE_DIR, "moments")
    )

    # 3. Audio Cry, Cough & Choke Detector
    def on_cry(*args, **kwargs):
        # Trích xuất Telemetry âm học (hỗ trợ cả dict và tuple cũ)
        if len(args) == 1 and isinstance(args[0], dict):
            telem = args[0]
            prob = float(telem.get("cry_probability", 0.5))
            volume = float(telem.get("volume", 0.02))
            top_label = telem.get("top_label", "Bé khóc")
        elif len(args) >= 3:
            prob, volume, top_label = args[0], args[1], args[2]
            telem = {
                "cry_probability": prob,
                "volume": volume,
                "volume_pct": round(volume * 100, 1),
                "continuous_seconds": 4.5,
                "duty_cycle_12s": 60.0,
                "recent_whimpers_60s": 1,
                "volume_trend": "ổn định",
                "top_label": top_label
            }
        else:
            return

        cur_cfg = load_config()

        # Multi-modal gate: Nếu camera xác định nôi trống và không có bé (Bé đã rời nôi / Ngoài giường),
        # triệt tiêu cảnh báo khóc giả lập tức để không làm phiền phụ huynh
        if (not vision_tracker.baby_detected) and (not getattr(vision_tracker, "adult_holding_baby", False)):
            return

        # Tạo Bức Ảnh Ghép 4 Ô (Composite 4-Panel Mosaic: T-3.5s, T-1.5s, T-0s, Cận cảnh Mặt/Thân)
        mosaic_frame = vision_tracker.create_cry_audit_mosaic()

        # Gửi lên Chuyên Gia Nhi Khoa Gemini AI Hội Chẩn & Kiểm Tra Chéo (Double-Check Sentinel)
        verify_res = {}
        if gemini_verifier and gemini_verifier.is_ready():
            verify_res = gemini_verifier.verify_crying_alert(
                mosaic_frame,
                cry_telemetry=telem,
                baby_pose=vision_tracker.sleep_pose
            )
        else:
            is_urg = float(telem.get("continuous_seconds", 4.5)) >= 5.5
            verify_res = {
                "verified_by_gemini": False,
                "should_alert": is_urg,
                "is_real_distress": is_urg,
                "baby_state": "distress_crying" if is_urg else "physiological_fussing",
                "diagnosis_vi": f"Phát hiện tiếng khóc ({top_label})" if is_urg else "Bé ọ ẹ sinh lý trong giấc ngủ",
                "clinical_advice_vi": "Quan sát bé qua camera nếu cần",
                "confidence": 75
            }

        should_alert = verify_res.get("should_alert", True)
        diag_vi = verify_res.get("diagnosis_vi", f"Phát hiện tiếng khóc em bé ({top_label})")
        baby_state = verify_res.get("baby_state", "distress_crying")
        advice_vi = verify_res.get("clinical_advice_vi", "")

        # TRƯỜNG HỢP A: BÉ CHỈ Ọ Ẹ SINH LÝ / CỰA MÌNH REM / TỰ TRẤN AN (should_alert == False)
        if not should_alert:
            print(f"[BabyGuard AI] 👶 Gemini dập cảnh báo khóc giả: {diag_vi} [{baby_state}]")
            sleep_tracker.record_health_event("fussing", f"Bé ọ ẹ sinh lý: {diag_vi}", {
                "state": baby_state,
                "confidence": f"{verify_res.get('confidence', 90)}%",
                "continuous_sec": telem.get("continuous_seconds")
            }, severity="INFO")
            # Tự động mở mềm Tiếng Ồn Trắng / Nhạc Không Lời (từ 4%) để hỗ trợ bé ngủ sâu lại
            if cur_cfg.get("auto_lullaby_on_cry", False) and not music_player.is_playing:
                track = cur_cfg.get("selected_lullaby", "Tieng_on_trang_White_Noise.wav")
                print(f"[BabyGuard AI] 🌊 Bé ọ ẹ chuyển giấc -> Mở mềm Tiếng Ồn Trắng hỗ trợ ngủ sâu: {track}")
                music_player.play_track(track, loop=True)
            return

        # TRƯỜNG HỢP B: BÉ THỰC SỰ ĐANG QUẤY KHÓC / ĐAU ĐỚN (should_alert == True)
        print(f"[BabyGuard AI] 🚨 Gemini XÁC THỰC BÉ KHÓC: {diag_vi} [{baby_state}]")

        if cur_cfg.get("auto_lullaby_on_cry", False) and not music_player.is_playing:
            track = cur_cfg.get("selected_lullaby", "Tieng_on_trang_White_Noise.wav")
            print(f"[BabyGuard AI] 🌊 Bé khóc -> Khởi động mềm Tiếng Ồn Trắng / Nhạc không lời (từ 4%): {track}")
            music_player.play_track(track, loop=True)

        if not cur_cfg.get("cry_alert_enabled", True):
            return

        msg = f"CẢNH BÁO: {diag_vi}"
        sleep_tracker.record_health_event("cry", msg, {
            "confidence": f"{verify_res.get('confidence', int(prob*100))}%",
            "duration_seconds": telem.get("continuous_seconds", 5.0),
            "state": baby_state,
            "advice": advice_vi
        })

        extra_info = {
            "Hội chẩn AI": diag_vi,
            "Trạng thái": baby_state,
            "Duy trì": f"{telem.get('continuous_seconds', 0.0)}s",
            "Âm lượng": f"{telem.get('volume_pct', round(volume*100, 1))}%",
            "Tư thế bé": vision_tracker.sleep_pose
        }
        if advice_vi:
            extra_info["Lời khuyên Nhi khoa"] = advice_vi

        # Gửi cảnh báo Telegram đính kèm BỨC ẢNH GHÉP 4 Ô để phụ huynh nhìn rõ toàn bộ diễn tiến!
        if alert_manager.trigger_event(
            event_type="cry",
            message=msg,
            frame=mosaic_frame,
            extra_info=extra_info
        ):
            video_recorder.trigger_recording("cry", msg, on_complete_callback=handle_video_completion)

    def on_cough(prob, volume, top_label):
        cur_cfg = load_config()
        if not cur_cfg.get("cough_alert_enabled", True):
            return
        frame = vision_tracker.get_latest_frame(annotated=True)
        msg = f"CẢNH BÁO: Phát hiện bé ho ({top_label})!"
        sleep_tracker.record_health_event("cough", msg, {"confidence": f"{prob*100:.1f}%", "volume": f"{volume*100:.1f}%"}, severity="INFO")
        if alert_manager.trigger_event(
            event_type="cough",
            message=msg,
            frame=frame,
            extra_info={
                "Độ tin cậy AI": f"{prob*100:.1f}%",
                "Âm lượng": f"{volume*100:.1f}%",
                "Hành động": "Quan sát xem bé có bị khẹc họng hoặc trào ngược sữa không"
            }
        ):
            video_recorder.trigger_recording("cough", msg, on_complete_callback=handle_video_completion)

    def on_choke(prob, volume, top_label):
        cur_cfg = load_config()
        if not cur_cfg.get("choke_alert_enabled", True):
            return
        frame = vision_tracker.get_latest_frame(annotated=True)
        msg = f"CẢNH BÁO KHẨN: Phát hiện dấu hiệu bé sặc sữa / ọc trớ ({top_label})!"
        sleep_tracker.record_health_event("choke", msg, {"confidence": f"{prob*100:.1f}%", "volume": f"{volume*100:.1f}%"}, severity="WARNING")
        if alert_manager.trigger_event(
            event_type="choke",
            message=msg,
            frame=frame,
            extra_info={
                "Độ tin cậy AI": f"{prob*100:.1f}%",
                "Âm lượng": f"{volume*100:.1f}%",
                "Hành động": "Kiểm tra ngay: Nghiêng đầu bé sang một bên, vỗ lưng nhẹ hoặc dùng dụng cụ hút sạch sữa trớ"
            }
        ):
            video_recorder.trigger_recording("choke", msg, on_complete_callback=handle_video_completion)

    def on_whimper(whimper_entry):
        """Ghi nhận âm thầm tiếng ọ ẹ / trở mình sinh lý REM để đối chiếu quy chuẩn quốc tế (AAP/Nelson)."""
        msg = whimper_entry.get("note", "Bé ọ ẹ / trở mình (Sinh lý)")
        dur = whimper_entry.get("duration_seconds", 1.0)
        vol = whimper_entry.get("volume", 0.0)
        sleep_tracker.record_health_event(
            "whimper",
            msg,
            {"duration_seconds": dur, "volume": f"{vol*100:.1f}%"},
            severity="INFO"
        )
        alert_manager.trigger_event("whimper", msg, extra_info=whimper_entry)

    audio_detector = AudioCryDetector(
        model_path=YAMNET_MODEL_PATH,
        device_index=config.get("audio_device_index", None),
        cry_threshold=config.get("cry_threshold", 0.30),
        cough_threshold=config.get("cough_threshold", 0.25),
        choke_threshold=config.get("choke_threshold", 0.20),
        on_cry_callback=on_cry,
        on_cough_callback=on_cough,
        on_choke_callback=on_choke,
        on_whimper_callback=on_whimper,
        audio_callback=video_recorder.add_audio_samples,
        cry_alert_enabled=config.get("cry_alert_enabled", True),
        cough_alert_enabled=config.get("cough_alert_enabled", True),
        choke_alert_enabled=config.get("choke_alert_enabled", True)
    )
    music_player.attach_audio_detector(audio_detector)

    # Start AI Workers
    vision_tracker.start()
    audio_detector.start()

    port = config.get("web_port", 8080)
    host = config.get("web_host", "0.0.0.0")

    # 4. Remote Access Tunnel Manager (Cloudflare Quick Tunnel)
    _last_notified_tunnel_url = [None]
    def on_tunnel_ready(url):
        alert_manager.update_config({"remote_access_url": url})
        print(f"[BabyGuard AI] 🌐 Link xem từ xa (4G/5G) đã sẵn sàng: {url}")
        if _last_notified_tunnel_url[0] != url:
            _last_notified_tunnel_url[0] = url
            msg = (
                "🍼 <b>BABYGUARD AI — KẾT NỐI TỪ XA ĐÃ SẴN SÀNG!</b>\n\n"
                f"📱 <b>Link xem camera từ xa trên 4G/5G:</b>\n👉 <a href='{url}'>{url}</a>\n\n"
                f"🏠 <b>Link xem tại nhà (WiFi):</b>\n👉 http://localhost:{port}\n\n"
                "<i>Ba mẹ có thể bấm trực tiếp vào link trên điện thoại khi ở ngoài để xem bé mọi lúc mọi nơi!</i>"
            )
            alert_manager.send_telegram_text(msg)

    tunnel_manager = TunnelManager(CONFIG_PATH, port=port, on_tunnel_ready=on_tunnel_ready)
    tunnel_manager.start()

    # 4.1 Auto Update Engine (Over-The-Air from official domain https://babyguard.site)
    auto_updater = AutoUpdateWorker(base_dir=BASE_DIR, alert_manager=alert_manager)
    auto_updater.start()

    # 5. Web Application
    app = create_app(
        vision_tracker, audio_detector, alert_manager, video_recorder,
        music_player, sleep_tracker, CONFIG_PATH,
        gemini_verifier=gemini_verifier, tunnel_manager=tunnel_manager
    )

    print(f"\n[BabyGuard AI] Dashboard running at: http://localhost:{port}")
    print(f"[BabyGuard AI] Local network IP access: http://0.0.0.0:{port}")
    print(f"[BabyGuard AI] Lưu trữ video quấn chiếu tại: {os.path.join(BASE_DIR, 'recordings')}")
    print(f"[BabyGuard AI] Thư mục nhạc ru: {MUSIC_DIR}")
    print("Nhấn Ctrl+C để dừng hệ thống.\n")

    def shutdown_handler(sig, frame):
        print("\n[BabyGuard AI] Đang tắt các tiến trình...")
        auto_updater.stop()
        tunnel_manager.stop()
        vision_tracker.stop()
        audio_detector.stop()
        music_player.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown_handler)
    signal.signal(signal.SIGTERM, shutdown_handler)

    is_headless = "--headless" in sys.argv or "--server-only" in sys.argv or os.environ.get("HEADLESS") == "1"

    if is_headless:
        try:
            uvicorn.run(app, host=host, port=port, log_level="warning")
        finally:
            auto_updater.stop()
            tunnel_manager.stop()
            vision_tracker.stop()
            audio_detector.stop()
            music_player.stop()
    else:
        # GUI Desktop Mode: Mở Cửa Sổ Ứng Dụng Độc Lập Native (Không mở trình duyệt Safari/Chrome)
        server_thread = threading.Thread(
            target=lambda: uvicorn.run(app, host=host, port=port, log_level="warning"),
            daemon=True
        )
        server_thread.start()
        time.sleep(1.2)

        try:
            import webview
            print("[BabyGuard AI] 🚀 Đang khởi chạy Cửa Sổ Ứng Dụng Độc Lập Native...")
            window = webview.create_window(
                title="BabyGuard AI • Vệ Sĩ & Bác Sĩ Giấc Ngủ Cho Bé",
                url=f"http://127.0.0.1:{port}/app",
                width=1280,
                height=820,
                min_size=(960, 600),
                text_select=False
            )
            webview.start()
        except Exception as e:
            print(f"[BabyGuard AI] Ghi chú cửa sổ GUI: {e}. Đang duy trì chế độ chạy liên tục.")
            while True:
                time.sleep(1)
        finally:
            auto_updater.stop()
            tunnel_manager.stop()
            vision_tracker.stop()
            audio_detector.stop()
            music_player.stop()


if __name__ == "__main__":
    main()
