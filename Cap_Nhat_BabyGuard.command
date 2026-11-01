#!/bin/bash
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
cd "$DIR"

echo "============================================================"
echo "🔄 BABYGUARD AI - CÔNG CỤ TỰ ĐỘNG CẬP NHẬT PHIÊN BẢN MỚI"
echo "============================================================"
echo "🔒 An toàn: Dữ liệu cữ ngủ, bản quyền và video được bảo vệ 100%!"
echo ""

if [ -d "$DIR/.git" ]; then
    echo "📦 Đang đồng bộ phiên bản mới nhất từ kho mã nguồn Git..."
    git pull origin main
    echo ""
    echo "✅ Đã cập nhật thành công!"
else
    echo "🌐 Đang kết nối máy chủ chính thức https://babyguard.site..."
    if command -v python3 &> /dev/null; then
        python3 -c "import urllib.request, json; data=json.loads(urllib.request.urlopen('https://babyguard.site/version.json', timeout=5).read().decode('utf-8')); print('✨ Phiên bản mới nhất trên babyguard.site:', data.get('version', '2.1.0'))" 2>/dev/null
    fi
    echo "💡 Mẹo: Ba chỉ cần mở BabyGuard AI, hệ thống sẽ tự động tải và cập nhật phiên bản mới nhất trong nền!"
    echo "Hoặc ba có thể bấm 'Kiểm Tra Cập Nhật' ngay trong phần Cài Đặt trên giao diện."
fi

echo ""
echo "============================================================"
echo "🎉 Hoàn tất! Nhấn Enter để thoát..."
read -r
