#!/bin/bash
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
PROJECT_DIR="$( cd "$SCRIPT_DIR/.." >/dev/null 2>&1 && pwd )"
PLIST_PATH="$HOME/Library/LaunchAgents/com.babyguard.ai.plist"

mkdir -p "$HOME/Library/LaunchAgents"

cat <<EOF > "$PLIST_PATH"
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.babyguard.ai</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>$PROJECT_DIR/start.sh</string>
    </array>
    <key>WorkingDirectory</key>
    <string>$PROJECT_DIR</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <false/>
</dict>
</plist>
EOF

launchctl unload "$PLIST_PATH" 2>/dev/null
launchctl load "$PLIST_PATH" 2>/dev/null

echo "============================================================"
echo "✅ ĐÃ CÀI ĐẶT TỰ ĐỘNG CHẠY CÙNG MÁY TÍNH THÀNH CÔNG!"
echo "============================================================"
echo "Từ bây giờ, mỗi khi bạn bật máy Mac lên:"
echo "👉 BabyGuard AI sẽ TỰ ĐỘNG CHẠY NGẦM trông bé 24/7."
echo "👉 Bạn không cần phải bấm bất kỳ nút nào nữa!"
echo "============================================================"
read -p "Bấm phím Enter để đóng cửa sổ này..."
