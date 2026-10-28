#!/usr/bin/env python3
"""
Công cụ sinh mã bản quyền thương mại BabyGuard AI dành riêng cho tác giả/nhà phát triển.
Chạy công cụ này để tạo License Key giao cho khách hàng khi họ mua phần mềm.
"""

import sys
import os
import argparse

# Thêm đường dẫn gốc vào sys.path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from license_manager import generate_license_key, get_machine_fingerprint, verify_license_key


def main():
    parser = argparse.ArgumentParser(description="BabyGuard AI Commercial License Key Generator")
    parser.add_argument("--machine", "-m", default="UNIVERSAL", help="Mã máy tính của khách (vd: BG-MAC-XXXX-XXXX-XXXX hoặc 'UNIVERSAL' dùng cho mọi máy)")
    parser.add_argument("--tier", "-t", default="LIFETIME", choices=["LIFETIME", "PRO_ANNUAL", "PRO_MONTHLY", "CLINIC"], help="Gói bản quyền")
    parser.add_argument("--days", "-d", type=int, default=None, help="Số ngày có hiệu lực (để trống nếu là LIFETIME vĩnh viễn)")
    parser.add_argument("--email", "-e", default="", help="Email khách hàng (tùy chọn)")
    parser.add_argument("--current", action="store_true", help="Lấy mã máy tính hiện tại của máy này")

    args = parser.parse_args()

    if args.current:
        cur_mid = get_machine_fingerprint()
        print(f"Mã phần cứng máy này (Hardware ID): {cur_mid}")
        args.machine = cur_mid

    if args.tier == "PRO_ANNUAL" and not args.days:
        args.days = 365
    elif args.tier == "PRO_MONTHLY" and not args.days:
        args.days = 30

    key = generate_license_key(
        machine_id=args.machine,
        tier=args.tier,
        days_valid=args.days,
        customer_email=args.email
    )

    print("=" * 65)
    print("      BABYGUARD AI - COMMERCIAL LICENSE GENERATOR")
    print("=" * 65)
    print(f"Khách hàng:      {args.email or 'N/A'}")
    print(f"Gói bản quyền:   {args.tier}")
    print(f"Khóa vào máy:    {args.machine}")
    print(f"Thời hạn:        {f'{args.days} ngày' if args.days else 'Vĩnh viễn (Lifetime)'}")
    print("-" * 65)
    print(f"MÃ LICENSE KEY:  👉  {key}  👈")
    print("=" * 65)

    # Tự kiểm tra lại tính hợp lệ
    v = verify_license_key(key, args.machine if args.machine != "UNIVERSAL" else get_machine_fingerprint())
    if v.get("valid"):
        print("✅ Kiểm tra chữ ký mật mã: HỢP LỆ (Signature Verified)")
    else:
        print(f"⚠️ Cảnh báo: {v}")


if __name__ == "__main__":
    main()
