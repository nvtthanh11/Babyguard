# 🍼 AI_CONTEXT.md - BẢN ĐỒ KIẾN TRÚC & HƯỚNG DẪN DÀNH CHO AI (BABYGUARD AI)

> **Dành cho bất kỳ Trợ lý AI nào (Claude, ChatGPT, Cursor, Copilot, DeepSeek, v.v.):**  
> Tài liệu này được thiết kế để bạn có thể đọc hiểu **toàn bộ 100% cấu trúc, tính năng, logic kinh doanh và triết lý sản phẩm** của dự án BabyGuard AI chỉ trong 1 lần đọc. Hãy tuân thủ nghiêm ngặt các quy tắc kiến trúc dưới đây khi phát triển tiếp dự án.

---

## 🧭 1. TỔNG QUAN DỰ ÁN (PROJECT OVERVIEW)

* **Tên sản phẩm:** BabyGuard AI (Smart AI Baby Monitor - Commercial Edition).
* **Tác giả / Nhà sáng lập:** Nguyễn Vũ Trường Thanh (Ba của bé Bé A Siu).
* **Sứ mệnh:** Biến webcam/laptop/máy tính cũ thành **Trợ lý Vệ sĩ & Bác sĩ Giấc ngủ AI** bảo vệ giấc ngủ và sinh mạng của bé yêu 24/7 với chi phí siêu tiết kiệm (199.000đ trọn đời thay vì mua camera ngoại 8 - 10 triệu đồng).
* **Triết lý kỹ thuật:**
  1. **Edge AI First (Xử lý cục bộ 100%):** Không đẩy video của bé lên cloud để đảm bảo quyền riêng tư tuyệt đối cho gia đình.
  2. **Hybrid Cloud (Gemini Pool Failover):** Chỉ gửi ảnh cắt vi mô ẩn danh lên Gemini để hội chẩn khi cần thẩm định cảnh báo giả (False Alarm Suppression), chấm điểm ảnh đẹp (Cute Moments) hoặc phân tích giấc ngủ nhi khoa.
  3. **Zero Maintenance Cost (Chi phí duy trì 0 VNĐ):** Dùng Cloudflare Quick Tunnel miễn phí, SePay Free Tier (50 tx/tháng), GitHub Pages + Fastly CDN, Gemini API Free Pool. Không cần thuê máy chủ đắt đỏ.
* **Nguyên tắc xưng hô bất di bất dịch:**  
  > ⚠️ **LUÔN DÙNG TỪ "BA" - TUYỆT ĐỐI KHÔNG DÙNG TỪ "BỐ"** trong toàn bộ giao diện, câu chuyện, tài liệu và thông báo.

---

## 🗂️ 2. BẢN ĐỒ TẬP TIN & CẤU TRÚC MÃ NGUỒN (SOURCE CODE MAP)

```text
baby_monitor/
├── main.py                     # Entrypoint: Khởi tạo đa luồng (Vision, Audio, Web, Sleep, Alert, Tunnel, Gemini)
├── web_server.py               # Máy chủ FastAPI: Stream video MJPEG, REST APIs, SePay IPN Webhook, Auto-Activation
├── vision_tracker.py           # AI Thị giác: YuNet Face, YOLOv8-pose MPS, chống lật úp, che mặt, đo nhịp thở RPM, căn nôi
├── audio_detector.py           # AI Thính giác: Google YAMNet TFLite phát hiện tiếng khóc, ho sặc, tiếng ồn
├── sleep_tracker.py            # AI Giấc ngủ: Cửa sổ 24h nhi khoa (tính từ 07:00 sáng theo chuẩn AAP/AASM), chu kỳ ngủ, điểm số
├── gemini_verifier.py          # Bộ hội chẩn Gemini: Quản lý Multi-Key Pool tự đảo model khi chạm quota, duyệt ảnh đẹp, RAG nhi
├── alert_manager.py            # Quản lý cảnh báo: Bắn tin Telegram (kèm ảnh/video), chống spam (cooldown), ghim tin khẩn
├── license_manager.py          # Quản lý bản quyền thương mại: HMAC-SHA256, dùng thử 14 ngày, khóa theo máy & Master Lifetime
├── tunnel_manager.py           # Trình quản lý Cloudflare Tunnel: Tự động cấp link xem từ xa 4G/5G HTTPS
├── google_drive_sync.py        # Tự động đồng bộ ảnh Cute Moments lên Google Drive gia đình
│
├── config.json                 # Cấu hình máy hoạt động (Camera, Telegram, License Key, Gemini Keys, Safe Crib...)
├── config.example.json         # Mẫu cấu hình an toàn để đưa lên Git
├── sepay_config.json           # Cấu hình thanh toán SePay (MBBank 1550107316004, 199.000đ, IPN Webhook URL)
├── sepay_transactions.json     # Nhật ký giao dịch thanh toán kiểm toán nội bộ
│
├── templates/
│   └── index.html              # Dashboard ứng dụng web: Đa ngôn ngữ (VI/EN), Live stream, Căn nôi, VietQR Modal
├── docs/
│   └── index.html              # Landing Page bán hàng chạy trên GitHub Pages (Fastly CDN, Bảng giá, Modal thanh toán)
│
├── models/                     # Thư mục chứa AI weights (yolov8n-pose.pt, yamnet.tflite, face_detection_yunet.onnx)
├── moments/                    # Ảnh kỷ niệm dễ thương AI chụp cho bé
├── recordings/                 # Video clip quay lại các sự kiện chuyển động/khóc (tự xoay vòng 14 ngày)
└── medical_knowledge/          # Phác đồ sơ cấp cứu nhi khoa (RAG Protocols) cho Gemini tra cứu
```

---

## ⚡ 3. HỆ THỐNG THƯƠNG MẠI & THANH TOÁN TỰ ĐỘNG (COMMERCIAL ARCHITECTURE)

### A. Chính Sách Bản Quyền:
* **Dùng thử miễn phí:** 14 ngày trải nghiệm trọn vẹn 100% tính năng AI.
* **Bản Tiêu Chuẩn (Việt Nam):** 199.000 VNĐ (Mua 1 lần vĩnh viễn trọn đời, không phí thuê bao).
* **Bản Quốc Tế (International):** $29 USD vĩnh viễn (hoặc $4.99/tháng) qua Stripe / Lemon Squeezy.
* **Chính sách hoàn tiền:** Cam kết hoàn tiền 100% trong 30 ngày nếu không hài lòng.

### B. Luồng Thanh Toán & Mở Khóa Tự Động 100% (Zero Friction):
Khách hàng **KHÔNG BAO GIỜ PHẢI NHẬP HAY NHẬN MÃ KEY THỦ CÔNG**:
1. Khách mở bảng Bản quyền trên App hoặc Web ➔ Hệ thống tự tạo mã **VietQR (Chuẩn NAPAS 247)**:
   * **Ngân hàng thụ hưởng:** MBBank (Ngân Hàng TMCP Quân Đội).
   * **Số tài khoản:** `1550107316004`
   * **Chủ tài khoản:** `Nguyen Vu Truong Thanh`
   * **Số tiền:** Khóa cứng `199.000 VNĐ`.
   * **Nội dung chuyển khoản:** `BG [MÃ_MÁY_KHÁCH]` (Ví dụ: `BG F7A7`).
2. Khách dùng bất kỳ app ngân hàng nào quét mã chuyển tiền.
3. Tiền về MBBank ➔ SePay bắt biến động số dư trong 2 giây ➔ Bắn Webhook HTTP POST tới:
   * **Endpoint:** `@app.post("/api/sepay/ipn")` trong `web_server.py`.
4. Máy chủ BabyGuard AI:
   * Kiểm tra giao dịch, ghi nhật ký vào `sepay_transactions.json`.
   * Tự sinh **Lifetime License Key** bằng hàm `generate_license_key(machine_id, tier="LIFETIME")`.
   * Lưu vào `config.json` và cập nhật `LicenseManager`.
   * **App của khách lập tức chuyển sang trạng thái "Đã Kích Hoạt Vĩnh Viễn" trong 1 giây**.
   * Bắn thông báo chúc mừng về Telegram của tác giả.

### C. Cơ Chế Tra Cứu & Hoàn Tiền (Refund Protocol):
* Toàn bộ lịch sử nhận tiền lưu tại:
  1. **App MBBank** (Bấm "Chuyển lại" để hoàn tiền trong 1 chạm).
  2. **SePay Dashboard (`my.sepay.vn`)** (Có bộ lọc tìm kiếm và nút Xuất Excel).
  3. **File `sepay_transactions.json`** trên máy chủ.
* Thu hồi bản quyền: Nếu khách xin hoàn tiền, chỉ cần xóa key khỏi `config.json` hoặc đưa mã máy vào blacklist.

---

## 🩺 4. CÁC TÍNH NĂNG AI CỐT LÕI (CORE AI ENGINE)

1. **Vệ Sĩ Thị Giác (Vision Tracker - `vision_tracker.py`):**
   * **YOLOv8-pose + YuNet:** Theo dõi 17 khớp xương và khuôn mặt bé.
   * **Chống nằm sấp (Prone Sleeping):** Phát hiện lật úp mặt xuống đệm để phòng chống đột tử sơ sinh (SIDS).
   * **Chống che mặt (Covered Face):** Phát hiện chăn gối che mũi miệng.
   * **Đo nhịp thở (Breathing RPM):** Phân tích quang sai chuyển động vi mô ngực (chuẩn 30 - 60 nhịp/phút), cảnh báo ngưng thở (>20s).
   * **Ranh giới nôi ảo (Safe Crib Zone):** Cho phép kéo thả trực tiếp vùng an toàn trên màn hình cảm ứng, cảnh báo khi bé leo trèo hoặc trườn ra ngoài.
2. **Bác Sĩ Thính Giác (Audio AI - `audio_detector.py`):**
   * **Google YAMNet TFLite:** Phát hiện tiếng khóc (Baby Cry) và tiếng ho/sặc sữa (Cough & Gasp).
   * **Tự động ru ngủ:** Tự bật nhạc ru / tiếng ồn trắng khi bé vừa khóc.
3. **Bác Sĩ Giấc Ngủ Nhi Khoa (Sleep Tracker - `sleep_tracker.py`):**
   * **Chu kỳ 24h Nhi khoa:** Mốc tính từ **07:00 sáng** hàng ngày theo chuẩn Viện Hàn Lâm Nhi Khoa Hoa Kỳ (AAP & AASM).
   * **Chấm điểm giấc ngủ (Sleep Score 0-100), Biểu đồ giấc ngủ 24h, Cửa sổ thức (Wake Window).**
   * **Gemini Clinical Sleep Summary:** Gemini phân tích cữ ngủ đêm và giấc ngủ ngày, đưa ra lời khuyên sinh hoạt EASY cho ba mẹ.
4. **Sổ Đo WHO & Lịch Tiêm Chủng:**
   * So sánh biểu đồ Z-Score tăng trưởng cân nặng, chiều cao theo chuẩn Tổ Chức Y Tế Thế Giới (WHO).
   * Lịch tiêm chủng từ sơ sinh đến 24 tháng tuổi theo Bộ Y Tế Việt Nam.
5. **Khoảnh Khắc Đáng Yêu (Cute Moments):**
   * AI tự chụp chân dung bé khi ngủ ngoan, tự chấm điểm thẩm mỹ (score ≥ 7) và đồng bộ Google Drive.

---

## 🛠️ 5. LỆNH VẬN HÀNH & PHÁT TRIỂN (COMMANDS)

* **Chạy ứng dụng:**
  ```bash
  cd /Volumes/SSD/WORK/baby_monitor
  python3.11 main.py
  ```
* **Dashboard ứng dụng cục bộ:** `http://localhost:8080`
* **Kiểm tra trạng thái bản quyền:** `GET http://localhost:8080/api/license/status`
* **Kiểm tra thông tin SePay & VietQR:** `GET http://localhost:8080/api/sepay/info`
* **Mô phỏng kích hoạt thanh toán test:** `POST http://localhost:8080/api/sepay/simulate-test-payment`
* **Git Repository:** `git@github.com:nvtthanh11/Babyguard.git` (nhánh `main`).
* **Landing Page:** Thư mục `docs/index.html` được host tự động tại `https://nvtthanh11.github.io/Babyguard/`.

---

## 📌 6. LƯU Ý SỐNG CÒN KHI NÂNG CẤP MÃ NGUỒN:
1. **Không làm hỏng file `config.json`:** Luôn đọc và ghi cấu hình an toàn qua cơ chế lock/tmp file.
2. **Không đổi cấu trúc URL Webhook SePay:** Luôn giữ nguyên endpoint `@app.post("/api/sepay/ipn")`.
3. **Bảo tồn tính năng Offline:** Mọi tính năng AI cơ bản (Pose, Face, Audio, Sleep) phải hoạt động trơn tru ngay cả khi mất kết nối Internet.
4. **Giữ gìn giọng văn ấm áp:** Mọi câu từ hướng dẫn phụ huynh phải ân cần, thấu hiểu, mang tình cảm của một người ba chăm sóc con.
