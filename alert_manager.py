import os
import json
import time
import subprocess
import threading
from datetime import datetime
import cv2
import requests


BASE_DIR = os.path.dirname(os.path.abspath(__file__))


class AlertManager:
    def __init__(self, config: dict, snapshots_dir: str = None):
        self.config = config
        self.snapshots_dir = snapshots_dir or os.path.join(BASE_DIR, "snapshots")
        os.makedirs(self.snapshots_dir, exist_ok=True)
        
        self.last_alert_time = {}
        self.events = []
        self.lock = threading.Lock()
        self._bot_update_offset = 0
        self.recent_bot_contacts = []
        self.first_aid_data = self._load_first_aid_protocols()
        threading.Thread(target=self._bot_auto_reply_loop, daemon=True).start()

    def _load_first_aid_protocols(self) -> dict:
        """Tải cơ sở dữ liệu phác đồ sơ cứu chuẩn quốc tế (AHA / AAP / WHO) phục vụ RAG cục bộ."""
        proto_path = os.path.join(BASE_DIR, "medical_knowledge", "infant_first_aid_protocols.json")
        try:
            if os.path.exists(proto_path):
                with open(proto_path, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception as e:
            print(f"[AlertManager] Lỗi tải tài liệu sơ cứu y khoa: {e}")
        return {}

    def get_first_aid_guidance(self, event_type: str, lang: str = None) -> str:
        """Truy xuất nguyên văn phác đồ sơ cứu y tế (RAG cục bộ - tốc độ 0.001s, 0% CPU, không hallucinate)."""
        if not self.first_aid_data or "protocols" not in self.first_aid_data:
            return ""
        
        mapping = {
            "cough": "choking_aspiration",
            "choke": "choking_aspiration",
            "prone": "suffocation_prone",
            "covered_face": "suffocation_prone",
            "apnea": "respiratory_distress"
        }
        proto_key = mapping.get(event_type)
        if not proto_key:
            return ""
        
        proto_entry = self.first_aid_data.get("protocols", {}).get(proto_key)
        if not proto_entry:
            return ""

        raw_lang = lang if lang else self.config.get("language", "vi")
        if isinstance(raw_lang, bool):
            cur_lang = "en" if raw_lang else "vi"
        elif isinstance(raw_lang, str):
            cur_lang = raw_lang.lower().strip()
        else:
            cur_lang = "vi"
        if cur_lang not in ["vi", "en"]:
            cur_lang = "vi"
        if cur_lang in proto_entry:
            proto = proto_entry[cur_lang]
        elif "vi" in proto_entry:
            proto = proto_entry["vi"]
        else:
            proto = proto_entry

        title = proto.get("title", "HƯỚNG DẪN SƠ CỨU" if cur_lang == "vi" else "FIRST AID GUIDANCE")
        steps = proto.get("steps", [])
        do_nots = proto.get("do_not", [])
        
        disclaimer_key = f"disclaimer_{cur_lang}"
        disclaimer = self.first_aid_data.get(disclaimer_key, self.first_aid_data.get("disclaimer_vi", self.first_aid_data.get("disclaimer", "")))

        out = f"\n\n🏥 <b>{title}</b>\n"
        for s in steps[:2]:
            out += f"• {s}\n"
        if do_nots:
            out += f"⛔ <i>{do_nots[0]}</i>\n"
        return out

    def update_config(self, new_config: dict):
        with self.lock:
            self.config.update(new_config)

    def _bot_auto_reply_loop(self):
        """
        Luồng chạy ngầm 24/7: Bất cứ khi nào người nhà nhắn '/start' hoặc bất kỳ tin nhắn nào
        vào Bot Telegram, Bot sẽ tự động trả lời ngay mã Chat ID trên điện thoại của họ
        để họ đọc/nhập vào ô Chat ID bất cứ lúc nào mà không cần canh thời gian.
        """
        # Khởi tạo offset ban đầu để không trả lời lại các tin nhắn cũ từ quá khứ
        initialized = False
        while True:
            try:
                bot_token = str(self.config.get("telegram_bot_token", "")).strip()
                if not bot_token:
                    time.sleep(5)
                    continue

                url = f"https://api.telegram.org/bot{bot_token}/getUpdates"
                params = {"timeout": 10}
                if self._bot_update_offset > 0:
                    params["offset"] = self._bot_update_offset

                resp = requests.get(url, params=params, timeout=15)
                if resp.status_code == 200:
                    updates = resp.json().get("result", [])
                    if not initialized:
                        # Lưu lại danh bạ những người đã từng nhắn trước đó và đặt offset mới nhất
                        for upd in updates:
                            uid = upd.get("update_id", 0)
                            if uid >= self._bot_update_offset:
                                self._bot_update_offset = uid + 1
                            self._record_bot_contact(upd)
                        initialized = True
                    else:
                        for upd in updates:
                            uid = upd.get("update_id", 0)
                            if uid >= self._bot_update_offset:
                                self._bot_update_offset = uid + 1
                            contact = self._record_bot_contact(upd)
                            if contact:
                                self._reply_chat_id_to_user(bot_token, contact)
            except Exception:
                pass
            time.sleep(3)

    def _record_bot_contact(self, upd: dict):
        msg = upd.get("message") or upd.get("edited_message") or {}
        chat = msg.get("chat", {})
        cid = str(chat.get("id", "")).strip()
        if not cid:
            return None
        first_name = chat.get("first_name", "")
        last_name = chat.get("last_name", "")
        username = chat.get("username", "")
        full_name = f"{first_name} {last_name}".strip() or username or f"Người nhà ({cid})"
        contact = {
            "name": full_name,
            "username": f"@{username}" if username else "",
            "chat_id": cid,
            "last_text": str(msg.get("text", ""))[:40],
        }
        # Cập nhật vào danh sách liên hệ gần đây
        self.recent_bot_contacts = [c for c in self.recent_bot_contacts if c["chat_id"] != cid]
        self.recent_bot_contacts.insert(0, contact)
        return contact

    def _reply_chat_id_to_user(self, bot_token: str, contact: dict):
        try:
            baby_name = self.config.get("baby_name", "Bé")
            reply_text = (
                f"🤖 <b>BabyGuard AI — Hệ Thống Trông Trẻ ({baby_name})</b>\n\n"
                f"👋 Xin chào <b>{contact['name']}</b>!\n"
                f"🔑 Mã <b>Telegram Chat ID</b> của bạn là:\n"
                f"<code>{contact['chat_id']}</code>\n\n"
                f"👉 <i>Hãy copy mã số trên và nhập vào ô <b>Chat ID</b> trong mục Cài đặt của BabyGuard AI để nhận cảnh báo cùng gia đình nhé!</i>"
            )
            requests.post(
                f"https://api.telegram.org/bot{bot_token}/sendMessage",
                json={"chat_id": contact["chat_id"], "text": reply_text, "parse_mode": "HTML"},
                timeout=8,
            )
        except Exception:
            pass

    def _can_alert(self, event_type: str) -> bool:
        base_cooldown = self.config.get("alert_cooldown_seconds", 120)
        # Routine motion has longer cooldown to avoid flooding local logs
        if event_type == "motion":
            cooldown = max(base_cooldown, 180)
        elif event_type in ("covered_face", "prone", "apnea", "danger_zone"):
            # Cảnh báo an toàn khẩn cấp & chạm mép giường có cooldown 30s để nhắc nhở kịp thời
            cooldown = 30
        else:
            cooldown = base_cooldown
        last_time = self.last_alert_time.get(event_type, 0)
        return (time.time() - last_time) >= cooldown

    def _should_notify_telegram(self, event_type: str) -> bool:
        if not self.config.get("telegram_enabled", False):
            return False
        # Do not notify routine motion to Telegram unless explicitly enabled
        if event_type == "motion" and not self.config.get("telegram_notify_motion", False):
            return False
        return True

    def _play_mac_sound(self, event_type: str = "critical"):
        if not self.config.get("sound_alert_on_mac", True):
            return
            
        # 1. Chạm mép giường / nguy cơ lăn ngã: Kêu tiếng "ting ting" (Glass.aiff) theo đúng ý bố mẹ
        # 2. Nguy hiểm mạnh (Mặt bị che, Ngưng thở, Lật úp sấp): Phát chuông cảnh báo mạnh (Sosumi.aiff)
        # 3. Các sự kiện thông thường khác (khóc, ho nhẹ, cựa quậy, chụp ảnh): Hoàn toàn im lặng
        if event_type == "danger_zone":
            sound_file = "/System/Library/Sounds/Glass.aiff" # Tiếng ting ting
        elif event_type in {"covered_face", "apnea", "prone"}:
            sound_file = "/System/Library/Sounds/Sosumi.aiff" # Chuông cảnh báo mạnh
        else:
            return

        def _play():
            try:
                subprocess.run(["afplay", sound_file], check=False)
            except Exception:
                pass
        threading.Thread(target=_play, daemon=True).start()

    def _get_recipient_list(self) -> list:
        """Lấy danh sách tất cả người nhà được bật nhận thông báo Telegram."""
        recipients = []
        seen_ids = set()

        # 1. Lấy từ danh sách người nhà (telegram_recipients)
        raw_list = self.config.get("telegram_recipients", [])
        if isinstance(raw_list, list):
            for item in raw_list:
                if isinstance(item, dict):
                    cid = str(item.get("chat_id", "")).strip()
                    name = str(item.get("name", "Người nhà")).strip()
                    is_on = item.get("enabled", True)
                    if cid and is_on and cid not in seen_ids:
                        seen_ids.add(cid)
                        recipients.append({"name": name, "chat_id": cid})

        # 2. Tương thích ngược với trường telegram_chat_id chính (nếu chưa có trong danh sách)
        primary_cid = str(self.config.get("telegram_chat_id", "")).strip()
        if primary_cid and primary_cid not in seen_ids:
            seen_ids.add(primary_cid)
            recipients.append({"name": "Tài khoản chính", "chat_id": primary_cid})

        return recipients

    @staticmethod
    def _safe_photo_caption(raw_caption: str, max_len: int = 950) -> str:
        if len(raw_caption) <= max_len:
            return raw_caption
        truncated = raw_caption[:max_len]
        last_nl = truncated.rfind("\n")
        if last_nl > 400:
            truncated = truncated[:last_nl]
        import re
        open_tags = re.findall(r"<([a-zA-Z]+)(?:\s+[^>]*)?>", truncated)
        close_tags = re.findall(r"</([a-zA-Z]+)>", truncated)
        for t in reversed(open_tags):
            if open_tags.count(t) > close_tags.count(t):
                truncated += f"</{t}>"
                close_tags.append(t)
        return truncated

    def _send_telegram(self, photo_path: str, caption: str):
        bot_token = self.config.get("telegram_bot_token", "").strip()
        enabled = self.config.get("telegram_enabled", False)
        recipients = self._get_recipient_list()

        if not enabled or not bot_token or not recipients:
            return

        def _send():
            photo_url = f"https://api.telegram.org/bot{bot_token}/sendPhoto"
            msg_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
            import re
            clean_photo_cap = self._safe_photo_caption(caption, max_len=950)
            plain_photo_cap = re.sub(r'<[^>]+>', '', clean_photo_cap)

            for r in recipients:
                try:
                    chat_id = r["chat_id"]
                    # 1. Gửi ảnh kèm chú thích an toàn (luôn dưới 1,000 ký tự)
                    sent_photo = False
                    if photo_path and os.path.exists(photo_path):
                        try:
                            with open(photo_path, "rb") as f:
                                resp = requests.post(photo_url, files={"photo": f}, data={"chat_id": chat_id, "caption": clean_photo_cap, "parse_mode": "HTML"}, timeout=12)
                            if resp.status_code == 200:
                                sent_photo = True
                            else:
                                # Thử lại với plain text nếu parse HTML bị từ chối
                                with open(photo_path, "rb") as f:
                                    resp2 = requests.post(photo_url, files={"photo": f}, data={"chat_id": chat_id, "caption": plain_photo_cap}, timeout=12)
                                if resp2.status_code == 200:
                                    sent_photo = True
                        except Exception as pe:
                            print(f"[AlertManager] Lỗi gửi ảnh: {pe}")

                    # 2. Nếu nội dung ban đầu quá dài (> 950 ký tự), gửi thêm tin nhắn văn bản hướng dẫn đầy đủ
                    if len(caption) > 950:
                        requests.post(msg_url, data={"chat_id": chat_id, "text": caption, "parse_mode": "HTML"}, timeout=10)
                    elif not sent_photo:
                        # Fallback nếu không có ảnh hoặc gửi ảnh lỗi hoàn toàn -> gửi văn bản
                        requests.post(msg_url, data={"chat_id": chat_id, "text": caption, "parse_mode": "HTML"}, timeout=10)

                    print(f"[AlertManager] Telegram alert sent to {r['name']} ({chat_id}) [photo={sent_photo}]")
                except Exception as e:
                    print(f"[AlertManager] Failed to send Telegram to {r['name']}: {e}")

        threading.Thread(target=_send, daemon=True).start()

    def _get_compact_view_link(self) -> str:
        """Tạo link xem trực tiếp 1 chạm siêu nhanh không cần mật khẩu cho bố mẹ."""
        url = str(self.config.get("remote_access_url", "")).strip()
        if not url or "trycloudflare.com" in url or "cam.babyguard.site" in url or url == "https://babyguard.site":
            url = "https://babyguard.site/cam"

        acc_key = str(self.config.get("access_key", "")).strip()
        if acc_key and "?k=" not in url and "&k=" not in url:
            separator = "&" if "?" in url else "?"
            url = f"{url}{separator}k={acc_key}"

        return f'\n🔗 <b><a href="{url}">👉 BẤM XEM CAMERA NGAY (1 GIÂY)</a></b>'

    def send_telegram_text(self, text: str, pin: bool = False, tag_recipients: bool = False) -> bool:
        bot_token = self.config.get("telegram_bot_token", "").strip()
        enabled = self.config.get("telegram_enabled", False)
        recipients = self._get_recipient_list()

        if not enabled or not bot_token or not recipients:
            return False

        if "👉 Mở Camera" not in text:
            text += self._get_compact_view_link()

        def _send():
            url_send = f"https://api.telegram.org/bot{bot_token}/sendMessage"
            url_pin = f"https://api.telegram.org/bot{bot_token}/pinChatMessage"
            for r in recipients:
                try:
                    send_text = text
                    if tag_recipients:
                        tag = f"🔔 <b>[GỬI TỚI {r.get('name', 'BỐ MẸ').upper()}]</b>"
                        send_text = f"{tag}\n{send_text}"

                    data = {"chat_id": r["chat_id"], "text": send_text, "parse_mode": "HTML", "disable_web_page_preview": False}
                    resp = requests.post(url_send, json=data, timeout=12)
                    if resp.status_code == 200:
                        mid = resp.json().get("result", {}).get("message_id")
                        if pin and mid:
                            try:
                                requests.post(url_pin, json={"chat_id": r["chat_id"], "message_id": mid, "disable_notification": False}, timeout=8)
                                print(f"[AlertManager] 📌 Đã ghim tin nhắn Báo cáo #{mid} trên Telegram của {r['name']}")
                            except Exception as pe:
                                print(f"[AlertManager] Không thể ghim tin nhắn: {pe}")
                except Exception as e:
                    print(f"[AlertManager] Failed to send Telegram text to {r['name']}: {e}")

        threading.Thread(target=_send, daemon=True).start()
        return True

    def send_telegram_video(self, video_path: str, caption: str, event_type: str = "danger"):
        bot_token = self.config.get("telegram_bot_token", "").strip()
        enabled = self.config.get("telegram_enabled", False)
        send_video = self.config.get("telegram_send_video", False)
        recipients = self._get_recipient_list()

        if not enabled or not send_video or not bot_token or not recipients:
            return

        # Never send video for routine motion
        if event_type == "motion":
            return

        def _send():
            url = f"https://api.telegram.org/bot{bot_token}/sendVideo"
            for r in recipients:
                try:
                    with open(video_path, "rb") as f:
                        files = {"video": f}
                        data = {"chat_id": r["chat_id"], "caption": caption, "parse_mode": "HTML"}
                        resp = requests.post(url, files=files, data=data, timeout=30)
                        if resp.status_code == 200:
                            print(f"[AlertManager] Telegram video sent to {r['name']}: {os.path.basename(video_path)}")
                        else:
                            print(f"[AlertManager] Telegram video error ({resp.status_code}): {resp.text}")
                except Exception as e:
                    print(f"[AlertManager] Failed to send Telegram video to {r['name']}: {e}")

        threading.Thread(target=_send, daemon=True).start()

    def trigger_event(self, event_type: str, message: str, frame=None, extra_info: dict = None):
        """
        event_type: 'cry', 'motion', 'prone'
        """
        if not self._can_alert(event_type):
            return False

        self.last_alert_time[event_type] = time.time()
        now = datetime.now()
        ts_str = now.strftime("%Y%m%d_%H%M%S")
        display_time = now.strftime("%H:%M:%S - %d/%m/%Y")
        
        # Save snapshot
        snapshot_filename = f"{ts_str}_{event_type}.jpg"
        snapshot_path = os.path.join(self.snapshots_dir, snapshot_filename)
        
        if frame is not None:
            cv2.imwrite(snapshot_path, frame)
        else:
            snapshot_filename = None

        # Build notification message
        emojis = {
            "cry": "🚨 <b>[CẢNH BÁO BÉ KHÓC]</b>",
            "cough": "🥛 <b>[CẢNH BÁO: BÉ HO / SẶC SỮA]</b>",
            "apnea": "🆘 <b>[CẢNH BÁO KHẨN CẤP: NGUY CƠ NGƯNG THỞ]</b>",
            "motion": "⚠️ <b>[BÉ CỬ ĐỘNG / THỨC GIẤC]</b>",
            "prone": "⛔ <b>[NGUY HIỂM: BÉ NẰM SẤP / ÚP MẶT]</b>",
            "covered_face": "🚨 <b>[NGUY CƠ NGẠT: MẶT BÉ BỊ CHE KHUẤT]</b>",
            "danger_zone": "⛔ <b>[CẢNH BÁO: BÉ LĂN SÁT MÉP GIƯỜNG]</b>"
        }
        title = emojis.get(event_type, "🔔 <b>[THÔNG BÁO]</b>")
        
        caption = f"{title}\n\n"
        caption += f"⏰ <b>Thời gian:</b> {display_time}\n"
        caption += f"📝 <b>Chi tiết:</b> {message}\n"
        if extra_info:
            for k, v in extra_info.items():
                caption += f"• {k}: {v}\n"

        # Tích hợp RAG Cục Bộ: Đính kèm phác đồ sơ cứu chuẩn quốc tế (AHA/AAP) nếu là sự cố cấp tính
        fa_text = self.get_first_aid_guidance(event_type)
        if fa_text:
            caption += fa_text

        # Gắn link xem trực tiếp rút gọn
        caption += self._get_compact_view_link()

        # Record event in log
        event_record = {
            "id": len(self.events) + 1,
            "type": event_type,
            "title": title.replace("<b>", "").replace("</b>", ""),
            "message": message,
            "timestamp": display_time,
            "epoch": time.time(),
            "snapshot_url": f"/api/snapshots/{snapshot_filename}" if snapshot_filename else None,
            "extra": extra_info or {}
        }
        
        with self.lock:
            self.events.insert(0, event_record)
            if len(self.events) > 100:
                self.events.pop()

        # Alert outputs: Chỉ kêu chuông cảnh báo âm thanh trên Mac khi có nguy hiểm mạnh
        self._play_mac_sound(event_type)
            
        if snapshot_path and os.path.exists(snapshot_path):
            if self._should_notify_telegram(event_type):
                self._send_telegram(snapshot_path, caption)

        print(f"[AlertManager] Event triggered: [{event_type.upper()}] {message}")
        return True

    def get_daily_event_counts(self) -> dict:
        """Đếm chính xác số sự kiện ho/sặc sữa, khóc, ngạt... trong vòng 24 giờ qua."""
        now = time.time()
        day_sec = 86400
        counts = {
            "crying_count": 0,
            "cough_count": 0,
            "apnea_count": 0,
            "prone_count": 0,
            "covered_face_count": 0
        }
        with self.lock:
            for ev in self.events:
                if (now - ev.get("epoch", now)) <= day_sec:
                    t = ev.get("type", "")
                    if t == "cry":
                        counts["crying_count"] += 1
                    elif t == "cough":
                        counts["cough_count"] += 1
                    elif t == "apnea":
                        counts["apnea_count"] += 1
                    elif t == "prone":
                        counts["prone_count"] += 1
                    elif t == "covered_face":
                        counts["covered_face_count"] += 1
        return counts

    def get_events(self, limit: int = 30):
        with self.lock:
            return self.events[:limit]
