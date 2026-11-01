#!/bin/bash
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
cd "$DIR"

echo "============================================================"
echo "🚀 ĐANG KHỞI ĐỘNG BABYGUARD AI - BẢO MẪU THÔNG MINH..."
echo "============================================================"

mkdir -p "$DIR/logs"

# 1. Tìm phiên bản Python tương thích
if [ -f "/opt/homebrew/bin/python3.11" ]; then
    SYSTEM_PYTHON="/opt/homebrew/bin/python3.11"
elif command -v python3.11 &> /dev/null; then
    SYSTEM_PYTHON="python3.11"
elif command -v python3 &> /dev/null; then
    SYSTEM_PYTHON="python3"
else
    SYSTEM_PYTHON="python"
fi

# 1.1 Khởi tạo môi trường riêng .venv (Chống lỗi externally-managed-environment trên macOS Sonoma/Sequoia)
if [ ! -d "$DIR/.venv" ]; then
    echo "📦 Đang khởi tạo môi trường chạy riêng biệt cho BabyGuard AI..."
    $SYSTEM_PYTHON -m venv "$DIR/.venv" 2>/dev/null
fi

if [ -f "$DIR/.venv/bin/python" ]; then
    APP_PYTHON="$DIR/.venv/bin/python"
    APP_PIP="$DIR/.venv/bin/pip"
else
    APP_PYTHON="$SYSTEM_PYTHON"
    APP_PIP="$SYSTEM_PYTHON -m pip"
fi

# 1.2 Kiểm tra thư viện AI, thiếu cái gì tự động cài cái đó
echo "🔍 Đang kiểm tra các thư viện AI cần thiết..."
$APP_PYTHON -c "import fastapi, uvicorn, cv2, webview, ultralytics" 2>/dev/null
if [ $? -ne 0 ]; then
    echo "============================================================"
    echo "📦 ĐANG TỰ ĐỘNG CÀI ĐẶT THƯ VIỆN AI (CHỈ MẤT 1 - 2 PHÚT)..."
    echo "Hệ thống đang tự tải các gói cần thiết: FastAPI, OpenCV, WebView, Ultralytics..."
    echo "============================================================"
    $APP_PIP install --upgrade pip
    $APP_PIP install -r requirements.txt
    $APP_PIP install pywebview pyobjc-framework-WebKit
fi

# 2. Tìm công cụ xem từ xa Cloudflared
CLOUDFLARE_BIN=""
if [ -f "/opt/homebrew/bin/cloudflared" ]; then
    CLOUDFLARE_BIN="/opt/homebrew/bin/cloudflared"
elif command -v cloudflared &> /dev/null; then
    CLOUDFLARE_BIN="cloudflared"
fi

# 3. Kích hoạt Cloudflare Tunnel nếu có
if [ -n "$CLOUDFLARE_BIN" ]; then
    if ! pgrep -f "cloudflared tunnel" > /dev/null; then
        echo "🌐 Đang kích hoạt đường truyền xem từ xa Cloudflare..."
        $CLOUDFLARE_BIN tunnel --url http://localhost:8080 > "$DIR/logs/tunnel.log" 2>&1 &
        sleep 4
    fi
    REMOTE_URL=$(grep -o 'https://[a-zA-Z0-9.-]*\.trycloudflare\.com' "$DIR/logs/tunnel.log" | tail -n 1)
fi

# 4. Lấy địa chỉ IP nội bộ
LOCAL_IP=$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || hostname -I 2>/dev/null | awk '{print $1}')
[ -z "$LOCAL_IP" ] && LOCAL_IP="localhost"

echo "------------------------------------------------------------"
if [ -n "$REMOTE_URL" ]; then
    echo "📱 LINK XEM TỪ XA TRÊN ĐIỆN THOẠI (4G/5G/WiFi):"
    echo "👉 $REMOTE_URL"
    echo ""
fi
echo "💻 LINK XEM NỘI BỘ (ở nhà):"
echo "👉 http://$LOCAL_IP:8080"
echo "👉 http://$(hostname).local:8080  (Dùng trên iPhone/Mac không lo router đổi IP)"
echo "------------------------------------------------------------"

# 5. Khởi chạy Ứng dụng BabyGuard AI (Native Window)
echo "🚀 Đang mở Cửa sổ Ứng dụng BabyGuard AI..."
$APP_PYTHON main.py
