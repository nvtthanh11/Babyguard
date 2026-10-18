# 🍼 BabyGuard AI - Smart AI Baby Monitor
> **Trợ lý Vệ sĩ & Bác sĩ Giấc ngủ AI Thông minh cho Bé yêu**  
> *Hệ thống AI giám sát thị giác & âm thanh cục bộ (Edge AI), bảo mật riêng tư 100%, tích hợp theo dõi nhịp thở, tư thế và chăm sóc giấc ngủ trẻ sơ sinh.*

---

## 🌟 1. Tính Năng Vượt Trội

### 🛡️ Vệ Sĩ Thị Giác (Vision AI - YOLOv8 Pose Estimation)
- **Cảnh báo Nằm sấp (Prone Sleeping):** Phát hiện tức thì khi bé lật úp mặt xuống đệm, giảm thiểu nguy cơ đột tử ở trẻ sơ sinh (SIDS).
- **Cảnh báo Che mặt / Ngạt thở (Covered Face):** Báo động khi chăn, gối, gấu bông hoặc tã che khuất vùng mặt của bé.
- **Ranh giới Cũi an toàn (Safe Zone):** Phụ huynh dùng ngón tay kéo thả trực tiếp khung nôi trên điện thoại. Khi bé bò đến mép hoặc có nguy cơ trèo ngã, còi báo động sẽ reo.
- **Giám sát Nhịp thở & Cảnh báo Ngưng thở (Apnea Alert):** Đo chuyển động vi mô lồng ngực với tần số hô hấp chuẩn y khoa (30–60 BPM). Cảnh báo đỏ nếu bé không thở quá 20 giây.

### 👂 Bác Sĩ Thính Giác (Audio AI - Google YAMNet)
- **Nhận diện Tiếng khóc (Baby Cry):** Phân biệt chính xác tiếng khóc, gắt ngủ, la hét với tạp âm xung quanh.
- **Cảnh báo Ho & Sặc sữa (Cough & Gasp):** Phát hiện tiếng ho khò khè, ho sặc hoặc thở dốc để cha mẹ hỗ trợ kịp thời.
- **Tự động Ru ngủ (Auto Soothing):** Tự động phát tiếng ồn trắng, nhịp tim mẹ hoặc nhạc chuông êm dịu khi bé vừa chớm khóc.

### 📊 Bác Sĩ Giấc Ngủ (Sleep Analytics & Wake Window)
- **Điểm chất lượng giấc ngủ (Sleep Score 0–100):** Đánh giá dựa trên thời lượng ngủ sâu, số lần cựa mình và nhịp thở.
- **Biểu đồ Chu kỳ Ngủ (Hypnogram):** Trực quan hóa giấc ngủ nông (Light/REM), ngủ sâu (Deep Sleep) và lúc thức dậy.
- **Dự đoán Cửa sổ Thức (Wake Window Predictor):** Tính toán chính xác thời điểm bé sẽ buồn ngủ tiếp theo, giúp cha mẹ rèn nếp sinh hoạt EASY chuẩn khoa học.

### 📸 Tự Động Bắt Trọn Khoảnh Khắc Đáng Yêu (Cute Moments)
- AI nhận diện nụ cười, ngáp ngủ hoặc mút tay của bé để tự động chụp ảnh độ nét cao và lưu vào album kỷ niệm gia đình.

### 📱 Trải Nghiệm Thân Thiện & Đàm Thoại 2 Chiều
- **Giao diện Apple Health / Nursery Pro:** Hỗ trợ Dark Mode dịu mắt ban đêm, tối ưu mượt mà trên iPhone/Android.
- **Cài đặt như App Native (PWA):** Bấm "Thêm vào màn hình chính" để dùng như ứng dụng App Store thực thụ.
- **Đàm thoại 2 chiều (Talkback):** Nhấn giữ để nói chuyện, vỗ về bé từ xa qua loa máy chủ.
- **Thông báo Telegram khẩn cấp:** Gửi tin nhắn kèm ảnh chụp thực tế ngay khi có sự kiện nguy hiểm.

---

## 💻 2. Cấu Hình Đề Xuất & Thiết Bị Tương Thích

| Thiết Bị | Yêu Cầu Tối Thiểu | Đề Xuất Tốt Nhất |
| :--- | :--- | :--- |
| **Máy chủ chạy AI** | Laptop/PC Core i5 (Gen 8+) hoặc M1 Mac | Mac Mini M1/M2/M4 hoặc PC có card đồ họa |
| **Hệ điều hành** | macOS 12+, Ubuntu 20.04+, Windows 10/11 | macOS Sonoma / Sequoia |
| **Camera** | Webcam USB 720p hoặc Camera IP RTSP | Ezviz C6N, Imou Ranger 2, Tapo C200 (1080p, hồng ngoại ban đêm) |
| **Microphone** | Mic tích hợp sẵn trong camera / laptop | Mic USB chống ồn |
| **Mạng Internet** | WiFi gia đình 2.4G/5GHz | Kết nối mạng LAN hoặc WiFi ổn định |

---

## 🚀 3. Hướng Dẫn Cài Đặt Nhanh (Dành cho Kỹ Thuật Viên)

### Bước 1: Chuẩn bị môi trường Python (Python 3.10 hoặc 3.11)
```bash
# Clone hoặc tải thư mục mã nguồn về máy
cd baby_monitor

# Cài đặt các thư viện phụ thuộc
pip install -r requirements.txt
```

### Bước 2: Cài đặt công cụ xem từ xa (Tùy chọn)
- Cài đặt **Cloudflare Tunnel** (miễn phí, không cần mở port modem):
  - macOS: `brew install cloudflared`
  - Windows/Linux: Tải binary từ trang chủ Cloudflare.
- Hoặc cài đặt **Tailscale** để kết nối mạng riêng ảo bảo mật cao.

### Bước 3: Cấu hình Telegram Bot (Để nhận thông báo về điện thoại)
1. Mở file `config.json`.
2. Điền `telegram_bot_token` (lấy từ `@BotFather`).
3. Điền `telegram_chat_id` (lấy từ `@userinfobot`).
4. Đặt `"telegram_enabled": true`.

---

## 🎯 4. Hướng Dẫn Sử Dụng 1-Click (Dành cho Khách Hàng)

### Khởi động hệ thống:
- **Trên máy Mac:** Bấm đúp chuột vào file **`Khoi_Dong_BabyGuard.command`**.
- **Trên Windows / Linux:** Chạy file `start.sh` hoặc lệnh:
  ```bash
  python main.py
  ```

Hệ thống sẽ tự động bật Camera, nạp mô hình AI, mở đường truyền bảo mật và bật trình duyệt giao diện.

### Kết nối với Điện thoại:
1. **Khi ở nhà:** Mở trình duyệt điện thoại (Safari hoặc Chrome), nhập địa chỉ hiển thị trên màn hình:
   ```text
   http://<IP_MÁY_CHỦ>:8080   (Ví dụ: http://192.168.1.21:8080)
   ```
2. **Khi đi làm / ra ngoài (4G/5G):** Nhấp vào đường link Cloudflare Tunnel được in ra trong cửa sổ khởi động (dạng `https://xxxx.trycloudflare.com`).
3. **Cài app ra màn hình chính:**
   - Trên **iPhone (Safari):** Bấm biểu tượng Chia sẻ $\rightarrow$ chọn **"Thêm vào MH chính" (Add to Home Screen)**.
   - Trên **Android (Chrome):** Bấm menu 3 chấm $\rightarrow$ chọn **"Cài đặt ứng dụng"** hoặc **"Thêm vào màn hình chính"**.

### Tắt hệ thống an toàn:
- Bấm đúp chuột vào file **`Tat_BabyGuard.command`** (hoặc nhấn `Ctrl + C` trong cửa sổ lệnh).

---

## 📁 5. Cấu Trúc Dự Án

```text
baby_monitor/
├── main.py                     # Entry point khởi động và điều phối toàn bộ hệ thống
├── vision_detector.py          # AI thị giác: Pose, chống sấp, ngạt mặt, nhịp thở, khoảnh khắc
├── audio_detector.py           # AI thính giác: YAMNet nhận diện tiếng khóc, ho, thở dốc
├── sleep_tracker.py            # Bác sĩ giấc ngủ: Sleep score, chu kỳ ngủ, Wake window
├── alert_manager.py            # Điều phối cảnh báo âm thanh loa & thông báo Telegram
├── video_recorder.py           # Ghi hình sự kiện cuốn chiếu (Rolling buffer 10s trước + 20s sau)
├── music_player.py             # Máy phát nhạc ru, tiếng ồn trắng, nhịp tim dỗ bé
├── web_server.py               # API Backend FastAPI tốc độ cao & truyền phát MJPEG
├── config.json                 # Cấu hình cài đặt cá nhân (tùy biến ngưỡng, camera, Telegram)
├── config.example.json         # File mẫu cấu hình ban đầu
├── sleep_data.json             # Dữ liệu phân tích giấc ngủ theo thời gian thực
├── requirements.txt            # Danh sách thư viện Python cần thiết
├── start.sh / stop.sh          # Scripts chạy / dừng hệ thống
├── Khoi_Dong_BabyGuard.command # Phím tắt 1-click khởi động cho macOS
├── Tat_BabyGuard.command       # Phím tắt 1-click dừng hệ thống cho macOS
│
├── docs/                       # Tài liệu kỹ thuật & kiến trúc AI
│   ├── BRAIN_BABY_TRACKING_BLUEPRINT.md # Hồ sơ giải trình kỹ thuật chuyên sâu (Y khoa & AI)
│   └── index.html              # Trang tài liệu giới thiệu hệ thống
├── logs/                       # Quản lý nhật ký hệ thống (app.log, tunnel.log)
├── models/                     # Trọng số mô hình AI (YOLOv8 pose, YuNet face, YAMNet)
├── moments/                    # Album lưu trữ ảnh khoảnh khắc đáng yêu
├── music/                      # Nhạc ru ngủ & âm thanh vỗ về bé (Heartbeat, White Noise, Lullabies)
├── recordings/                 # Lưu trữ video clip sự kiện tự động cuốn chiếu
├── scripts/                    # Các script tiện ích (Tự khởi động macOS, tạo nhạc)
│   ├── Cai_Dat_Tu_Khoi_Dong.command
│   ├── Huy_Tu_Khoi_Dong.command
│   └── generate_extra_tracks.py
├── snapshots/                  # Bộ nhớ đệm khung hình live stream
├── templates/                  # Giao diện Web Dashboard (index.html phong cách Apple Health)
└── tests/                      # Bộ mẫu kiểm thử & hình ảnh hiệu chuẩn
    └── samples/                # Ảnh và âm thanh mẫu test
```

---

## 🔒 6. Cam Kết Quyền Riêng Tư (Privacy First)
Khác với các camera thương mại gửi video lên server đám mây ở nước ngoài, **BabyGuard AI xử lý 100% hình ảnh và âm thanh ngay tại máy chủ gia đình bạn (On-Premises Edge AI)**. Không ai có thể theo dõi hoặc can thiệp vào cuộc sống riêng tư của bé và gia đình.
