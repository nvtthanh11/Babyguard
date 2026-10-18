# 🍼 BABYGUARD AI - BẢO MẪU THÔNG MINH (COMMERCIAL EDITION)
### Sổ Tay Hướng Dẫn Cài Đặt & Sử Dụng Toàn Tập

---

## 1. GIỚI THIỆU TỔNG QUAN

**BabyGuard AI** là hệ thống giám sát và chăm sóc trẻ sơ sinh thông minh cao cấp, hoạt động hoàn toàn cục bộ (Edge AI) trên thiết bị trung tâm kết hợp với trí tuệ nhân tạo đa phương thức (Multimodal AI):

* 🫁 **Đo nhịp thở không tiếp xúc**: Giám sát lồng ngực bé qua thuật toán thị giác máy tính và quang sai vi mô, không cần đeo vòng hay cảm biến tiếp xúc lên người bé.
* 💤 **Theo dõi chu kỳ thức / ngủ 24/7**: Phân tích Wake Window (Cửa sổ thức) và Infant Sleep Cycle (Chu kỳ ngủ NREM/REM 50 phút).
* 🧠 **Hội chẩn bác sĩ AI buổi sáng (07:00 AM)**: Báo cáo phân tích chất lượng giấc ngủ đối chiếu theo tiêu chuẩn AAP & WHO.
* 🚨 **Cảnh báo khẩn cấp tức thì (Zero-Latency)**: Phát hiện trẻ lăn sát mép giường (nguy cơ ngã) và vật cản che mặt/mũi/miệng (nguy cơ ngạt thở).
* 🎵 **Hệ thống âm thanh dỗ bé tự động (Closed-Loop Soothing)**: Tự động phát Tiếng ồn trắng (White / Pink / Brown Noise) hoặc Nhạc ru không lời; tự động đo cường độ âm thanh trong phòng bé để điều chỉnh âm lượng vừa đủ chuẩn y khoa (~45-50 dB).
* 📸 **Album Khoảnh Khắc Đáng Yêu**: AI tự động lưu lại những nụ cười, cử chỉ ngộ nghĩnh của bé (đã qua kiểm duyệt bảo vệ quyền riêng tư); hỗ trợ chọn nhiều ảnh để tải về tệp ZIP hoặc xóa hàng loạt.
* 📱 **Thông báo Telegram khẩn cấp**: Gửi tin nhắn tức thì kèm ảnh chụp sự cố và video clip 30 giây chất lượng cao.

---

## 2. YÊU CẦU THIẾT BỊ & HỆ THỐNG

| Thành phần | Yêu cầu tối thiểu | Khuyên dùng tốt nhất |
| :--- | :--- | :--- |
| **Máy chủ xử lý** | Mac (M1/M2/M3/M4 hoặc Intel), PC Linux/Windows | **Mac mini (Apple Silicon M1/M2/M4)** chạy 24/7 siêu tiết kiệm điện |
| **Camera** | Webcam USB 720p 15 FPS | Webcam USB Full HD 1080p góc rộng hoặc Camera IP WiFi (RTSP) |
| **Microphone** | Mic tích hợp của máy / webcam | Mic định hướng USB thu âm phòng bé |
| **Loa** | Loa tích hợp máy tính | Loa máy tính hoặc loa ngoài đặt gần phòng bé |
| **Môi trường** | Python 3.10 hoặc 3.11 | Python 3.11 cài qua Homebrew trên macOS |

---

## 3. HƯỚNG DẪN CÀI ĐẶT LẦN ĐẦU (CHỈ 2 PHÚT)

### Bước 1: Mở Terminal và chuyển vào thư mục ứng dụng
```bash
cd /duong/dan/den/baby_monitor
```

### Bước 2: Cài đặt các thư viện Python
Chạy lệnh sau để cài đặt đầy đủ các thư viện cần thiết:
```bash
pip install -r requirements.txt
```

*(Khuyên dùng trên macOS)*: Cài đặt thêm `ffmpeg` để hệ thống đóng gói video kèm âm thanh mượt mà nhất:
```bash
brew install ffmpeg
```

---

## 4. CÁCH KHỞI ĐỘNG & SỬ DỤNG

### Cách 1: Khởi động 1-Click (Nhanh & Tiện lợi nhất)
Trong thư mục ứng dụng, chỉ cần **nhấp đúp chuột** vào file:
👉 **`Khoi_Dong_BabyGuard.command`**

* Hệ thống sẽ tự động tìm Python, kết nối camera, kích hoạt AI, và tự động mở trình duyệt web hiển thị bảng điều khiển trung tâm tại:
  **`http://localhost:8080`**

### Cách 2: Chạy bằng Terminal
```bash
./start.sh
```
hoặc:
```bash
python3 main.py
```

### Cách tắt ứng dụng:
* Nhấp đúp vào file **`Tat_BabyGuard.command`** hoặc nhấn tổ hợp phím **`Ctrl + C`** trong cửa sổ Terminal.

---

## 5. HƯỚNG DẪN XEM TRÊN ĐIỆN THOẠI & KẾT NỐI TỪ XA

### A. Khi ở nhà (Điện thoại và máy Mac cùng kết nối mạng Wi-Fi nhà)
1. Mở trình duyệt Safari hoặc Chrome trên điện thoại.
2. Nhập địa chỉ hiển thị khi khởi động máy (hoặc xem trong mục Cài đặt):
   * Ví dụ: `http://192.168.1.15:8080`
   * Hoặc: `http://ten-may-mac.local:8080`

---

### B. Khi ra ngoài (Dùng 4G/5G hoặc Wi-Fi cơ quan) qua TAILSCALE

> [!IMPORTANT]
> **Tại sao nên dùng Tailscale?**
> * **Bảo mật số 1**: Tạo mạng riêng ảo mã hóa đầu cuối (WireGuard Mesh VPN). Không cần mở cổng modem (Port Forwarding), ngăn chặn 100% nguy cơ hacker dò quét hay xem trộm hình ảnh phòng ngủ của bé.
> * **Tốc độ trực tiếp (Peer-to-Peer)**: Xem video 60 FPS cực mượt, không phụ thuộc vào máy chủ trung gian.
> * **Hoàn toàn miễn phí trọn đời**.

#### Các bước thiết lập Tailscale (Chỉ làm 1 lần):
1. **Trên máy chủ Mac mini**:
   * Tải app **Tailscale** từ App Store (hoặc `brew install tailscale`).
   * Mở app, đăng nhập bằng tài khoản Google hoặc Apple ID.
   * Tailscale sẽ cấp cho máy Mac một địa chỉ IP riêng (Ví dụ: `100.88.99.10`).
2. **Trên điện thoại của Bố/Mẹ (iPhone hoặc Android)**:
   * Tải app **Tailscale** từ App Store / Google Play.
   * Mở app và đăng nhập bằng **CÙNG tài khoản Google/Apple ID** đã dùng trên máy Mac.
   * Gạt công tắc bật kết nối (**Connected**).
3. **Mở xem camera**:
   * Mở Safari / Chrome trên điện thoại, gõ:
     👉 `http://100.88.99.10:8080` *(thay bằng IP Tailscale của máy Mac của bạn)*
   * **Mẹo hay**: Trên iPhone/Android, bấm vào biểu tượng chia sẻ trên trình duyệt -> chọn **"Thêm vào Màn hình chính (Add to Home Screen)"** để tạo biểu tượng ứng dụng BabyGuard AI riêng trên màn hình điện thoại như một App thực thụ!

---

## 6. CẤU HÌNH HỆ THỐNG & TÍNH NĂNG NỔI BẬT

Mọi thiết lập có thể thực hiện trực quan ngay trên giao diện web tại tab **⚙️ Cài Đặt**:

1. **Hồ sơ bé**: Điền tên bé và số tháng tuổi để AI tự động so sánh nhịp thở và chu kỳ giấc ngủ theo chuẩn Nhi khoa quốc tế.
2. **Thông báo Telegram**:
   * Nhập `Telegram Bot Token` và `Chat ID` để nhận cảnh báo tức thì kèm ảnh/video khi bé khóc, lật úp người, mặt bị che, hoặc chạm mép nôi.
3. **Bác sĩ AI Gemini (Miễn phí)**:
   * Nhập `Gemini API Key` (lấy miễn phí tại Google AI Studio) để kích hoạt tính năng Hội chẩn chuyên gia buổi sáng và bộ lọc khoảnh khắc đáng yêu.
4. **Căn chỉnh nôi (Safe Zone)**:
   * Hệ thống tự động căn chỉnh khung nôi bằng AI. Ngoài ra bạn có thể bấm nút **📐 Chỉnh Tay** trên video để kéo thả 4 cạnh nôi theo ý muốn.
5. **Bộ sưu tập Khoảnh khắc**:
   * Bấm nút **☑️ Chọn Nhiều** để chọn nhanh các bức ảnh yêu thích, tải về tệp `.zip` chỉ với 1 click hoặc xóa hàng loạt.

---

## 7. XỬ LÝ SỰ CỐ THƯỜNG GẶP (TROUBLESHOOTING)

* **Camera không lên hình**:
  * Kiểm tra quyền truy cập Camera trong macOS: *System Settings -> Privacy & Security -> Camera* -> Đảm bảo Terminal / Python được cấp quyền.
  * Nếu dùng nhiều camera, vào tab Cài Đặt để chọn đúng cổng USB Camera hoặc điền link RTSP.
* **Micro không nhận diện tiếng khóc**:
  * Kiểm tra quyền Microphone trong macOS: *System Settings -> Privacy & Security -> Microphone*.
  * Kiểm tra xem mục Micro trên Dashboard có nhảy thanh âm lượng % khi nói chuyện hay không.
* **Mất kết nối mạng**:
  * Hệ thống AI vẫn tự động ghi hình clip, phát hiện nguy hiểm và hú còi cảnh báo tại chỗ qua loa máy tính ngay cả khi mất internet hoàn toàn.
