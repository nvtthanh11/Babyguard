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
from web_server import create_app

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

    # 3. Audio Cry & Cough Detector
    def on_cry(prob, volume, top_label):
        cur_cfg = load_config()
        # Tự động phát mềm Tiếng Ồn Trắng / Nhạc Không Lời khi bé khóc (kể cả khi tắt báo động còi)
        if cur_cfg.get("auto_lullaby_on_cry", False) and not music_player.is_playing:
            track = cur_cfg.get("selected_lullaby", "Tieng_on_trang_White_Noise.wav")
            print(f"[BabyGuard AI] 🌊 Bé khóc -> Khởi động mềm Tiếng Ồn Trắng / Nhạc không lời (từ 4%): {track}")
            music_player.play_track(track, loop=True)

        if not cur_cfg.get("cry_alert_enabled", True):
            return
        frame = vision_tracker.get_latest_frame(annotated=True)
        msg = f"Phát hiện tiếng khóc / la hét em bé ({top_label})"
        if alert_manager.trigger_event(
            event_type="cry",
            message=msg,
            frame=frame,
            extra_info={
                "Độ tin cậy AI": f"{prob*100:.1f}%",
                "Âm lượng": f"{volume*100:.1f}%",
                "Tư thế bé": vision_tracker.sleep_pose
            }
        ):
            video_recorder.trigger_recording("cry", msg, on_complete_callback=handle_video_completion)

    def on_cough(prob, volume, top_label):
        if not config.get("cough_alert_enabled", True):
            return
        frame = vision_tracker.get_latest_frame(annotated=True)
        msg = f"CẢNH BÁO: Phát hiện bé ho / sặc sữa ({top_label})!"
        if alert_manager.trigger_event(
            event_type="cough",
            message=msg,
            frame=frame,
            extra_info={
                "Độ tin cậy AI": f"{prob*100:.1f}%",
                "Âm lượng": f"{volume*100:.1f}%",
                "Hành động": "Kiểm tra xem bé có bị trớ sặc sữa không"
            }
        ):
            video_recorder.trigger_recording("cough", msg, on_complete_callback=handle_video_completion)

    audio_detector = AudioCryDetector(
        model_path=YAMNET_MODEL_PATH,
        device_index=config.get("audio_device_index", None),
        cry_threshold=config.get("cry_threshold", 0.30),
        cough_threshold=config.get("cough_threshold", 0.25),
        on_cry_callback=on_cry,
        on_cough_callback=on_cough,
        audio_callback=video_recorder.add_audio_samples,
        cry_alert_enabled=config.get("cry_alert_enabled", True),
        cough_alert_enabled=config.get("cough_alert_enabled", True)
    )
    music_player.attach_audio_detector(audio_detector)

    # Start AI Workers
    vision_tracker.start()
    audio_detector.start()

    # 4. Web Application
    app = create_app(vision_tracker, audio_detector, alert_manager, video_recorder, music_player, sleep_tracker, CONFIG_PATH, gemini_verifier=gemini_verifier)

    port = config.get("web_port", 8080)
    host = config.get("web_host", "0.0.0.0")

    def notify_startup_links():
        time.sleep(4)
        tunnel_url = None
        log_file = os.path.join(LOGS_DIR, "tunnel.log")
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
                                    tunnel_url = p
            except Exception:
                pass
        
        msg = "🍼 <b>BABYGUARD AI ĐÃ KHỞI ĐỘNG!</b>\n\n"
        if tunnel_url:
            msg += f"📱 <b>Link xem từ xa trên điện thoại:</b>\n👉 <a href='{tunnel_url}'>{tunnel_url}</a>\n\n"
        msg += f"🏠 <b>Link xem tại nhà:</b>\n👉 http://localhost:{port}\n\n"
        msg += "<i>Bố mẹ bấm vào link trên để xem trực tiếp bé nhé. Vệ sĩ AI đang túc trực!</i>"
        alert_manager.send_telegram_text(msg)

    threading.Thread(target=notify_startup_links, daemon=True).start()

    print(f"\n[BabyGuard AI] Dashboard running at: http://localhost:{port}")
    print(f"[BabyGuard AI] Local network IP access: http://0.0.0.0:{port}")
    print(f"[BabyGuard AI] Lưu trữ video quấn chiếu tại: {os.path.join(BASE_DIR, 'recordings')}")
    print(f"[BabyGuard AI] Thư mục nhạc ru: {MUSIC_DIR}")
    print("Nhấn Ctrl+C để dừng hệ thống.\n")

    def shutdown_handler(sig, frame):
        print("\n[BabyGuard AI] Đang tắt các tiến trình...")
        vision_tracker.stop()
        audio_detector.stop()
        music_player.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown_handler)
    signal.signal(signal.SIGTERM, shutdown_handler)

    try:
        uvicorn.run(app, host=host, port=port, log_level="warning")
    finally:
        vision_tracker.stop()
        audio_detector.stop()
        music_player.stop()


if __name__ == "__main__":
    main()
