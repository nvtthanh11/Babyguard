#!/bin/bash
echo "============================================================"
echo "🛑 ĐANG TẮT HỆ THỐNG BABYGUARD AI..."
echo "============================================================"
pkill -f "python.*main.py" 2>/dev/null
pkill -f "cloudflared tunnel" 2>/dev/null
sleep 1
echo "✅ Đã tắt hoàn toàn hệ thống và ngắt kết nối an toàn."
