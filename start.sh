#!/bin/bash
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
cd "$DIR"

echo "============================================================"
echo "🚀 ĐANG KHỞI ĐỘNG BABYGUARD AI - BẢO MẪU THÔNG MINH..."
echo "============================================================"

mkdir -p "$DIR/logs"

# 1. Tìm phiên bản Python tương thích
if [ -f "/opt/homebrew/bin/python3.11" ]; then
    PYTHON_BIN="/opt/homebrew/bin/python3.11"
elif command -v python3.11 &> /dev/null; then
    PYTHON_BIN="python3.11"
elif command -v python3 &> /dev/null; then
    PYTHON_BIN="python3"
else
    PYTHON_BIN="python"
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

# 5. Tự động mở Safari/Chrome khi khởi chạy
if [[ "$OSTYPE" == "darwin"* ]]; then
    (sleep 3 && open "http://localhost:8080") &
fi

# 6. Chạy ứng dụng chính
$PYTHON_BIN main.py
