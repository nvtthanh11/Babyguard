#!/bin/bash
PLIST_PATH="$HOME/Library/LaunchAgents/com.babyguard.ai.plist"

if [ -f "$PLIST_PATH" ]; then
    launchctl unload "$PLIST_PATH" 2>/dev/null
    rm -f "$PLIST_PATH"
    echo "============================================================"
    echo "✅ Đã hủy tính năng tự khởi động cùng máy tính."
    echo "============================================================"
else
    echo "Hệ thống chưa cài đặt tự khởi động."
fi
read -p "Bấm phím Enter để đóng cửa sổ..."
