#!/bin/bash
# ============================================================
#   BABYGUARD AI - TRUNG TÂM BẬT / TẮT & ĐIỀU KHIỂN HỆ THỐNG
# ============================================================

APP_DIR="/Volumes/SSD/WORK/baby_monitor"
cd "$APP_DIR" || exit 1

# Tìm tiến trình đang chạy trên cổng 8080
PID=$(lsof -ti :8080 2>/dev/null | head -n 1)

# Mã màu hiển thị Terminal macOS
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

clear
echo -e "${CYAN}============================================================${NC}"
echo -e "${BOLD}       BABYGUARD AI - ĐIỀU KHIỂN BẬT / TẮT HỆ THỐNG${NC}"
echo -e "${CYAN}============================================================${NC}"

if [ -n "$PID" ]; then
    # ------------------------------------------------------------
    # TRƯỜNG HỢP 1: HỆ THỐNG ĐANG HOẠT ĐỘNG
    # ------------------------------------------------------------
    echo -e "Trạng thái hiện tại: ${GREEN}${BOLD}● ĐANG HOẠT ĐỘNG${NC} (PID: $PID)"
    echo -e "🌐 Địa chỉ Dashboard:  ${CYAN}http://localhost:8080${NC}"
    
    # Đọc link xem từ xa nếu có
    REMOTE_URL=$(grep -o 'https://[a-zA-Z0-9.-]*\.trycloudflare\.com' "$APP_DIR/logs/tunnel.log" 2>/dev/null | tail -n 1)
    if [ -n "$REMOTE_URL" ]; then
        echo -e "📱 Link xem từ xa 4G:  ${YELLOW}${BOLD}$REMOTE_URL${NC}"
    fi
    echo -e "${CYAN}------------------------------------------------------------${NC}"
    echo -e "${BOLD}BabyGuard AI đang mở. Chọn thao tác của bạn:${NC}"
    echo ""
    echo -e "  ${RED}${BOLD}[1] 🛑 TẮT HỆ THỐNG${NC} (Dừng camera & giải phóng máy)"
    echo -e "  ${YELLOW}[2] 🔄 Khởi động lại (Restart)${NC}"
    echo -e "  ${CYAN}[3] 🌐 Mở lại giao diện Web trên trình duyệt${NC}"
    echo -e "  ${BOLD}[0] ✕ Đóng cửa sổ này${NC} (Hệ thống vẫn tiếp tục chạy ngầm)"
    echo ""
    read -p "👉 Nhập lựa chọn [Mặc định bấm Enter để TẮT]: " choice
    choice=${choice:-1}

    case "$choice" in
        1)
            echo ""
            echo -e "${YELLOW}Đang tắt camera và máy chủ BabyGuard AI...${NC}"
            kill -15 "$PID" 2>/dev/null
            pkill -f "python.*main.py" 2>/dev/null
            pkill -f "cloudflared tunnel" 2>/dev/null
            sleep 1.5
            if ! lsof -ti :8080 >/dev/null 2>&1; then
                echo -e "${GREEN}${BOLD}✅ ĐÃ TẮT HOÀN TOÀN BABYGUARD AI!${NC}"
            else
                kill -9 $(lsof -ti :8080) 2>/dev/null
                echo -e "${GREEN}${BOLD}✅ ĐÃ DỪNG TIẾN TRÌNH THÀNH CÔNG!${NC}"
            fi
            echo ""
            read -t 2 -p "Cửa sổ sẽ đóng lại..." || true
            exit 0
            ;;
        2)
            echo ""
            echo -e "${YELLOW}Đang khởi động lại hệ thống...${NC}"
            kill -15 "$PID" 2>/dev/null
            pkill -f "python.*main.py" 2>/dev/null
            sleep 2
            exec "$APP_DIR/start.sh"
            ;;
        3)
            open "http://localhost:8080"
            echo -e "${GREEN}Đã mở trình duyệt!${NC}"
            exit 0
            ;;
        0)
            echo -e "Hệ thống vẫn tiếp tục chạy ngầm. Tạm biệt!"
            exit 0
            ;;
        *)
            echo "Lựa chọn không hợp lệ."
            exit 0
            ;;
    esac

else
    # ------------------------------------------------------------
    # TRƯỜNG HỢP 2: HỆ THỐNG ĐANG TẮT
    # ------------------------------------------------------------
    echo -e "Trạng thái hiện tại: ${RED}${BOLD}○ ĐANG TẮT${NC}"
    echo -e "${CYAN}------------------------------------------------------------${NC}"
    echo -e "${BOLD}Chọn thao tác của bạn:${NC}"
    echo ""
    echo -e "  ${GREEN}${BOLD}[1] 🚀 KHỞI ĐỘNG HỆ THỐNG${NC} (Bật camera, AI & mở Web Dashboard)"
    echo -e "  ${BOLD}[0] ✕ Thoát${NC}"
    echo ""
    read -p "👉 Nhập lựa chọn [Mặc định bấm Enter để BẬT]: " choice
    choice=${choice:-1}

    case "$choice" in
        1)
            echo ""
            echo -e "${GREEN}${BOLD}Đang khởi động BabyGuard AI...${NC}"
            exec "$APP_DIR/start.sh"
            ;;
        0)
            exit 0
            ;;
        *)
            echo "Lựa chọn không hợp lệ."
            exit 0
            ;;
    esac
fi
