import os
import sys
import json
import time
import hmac
import hashlib
import subprocess
import uuid
from datetime import datetime, timedelta

MASTER_SECRET = b"BabyGuardAI_Commercial_Proprietary_Salt_2026_SecureCore_x86_arm64"
TRIAL_DAYS = 14
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(BASE_DIR, ".babyguard_license_state")
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")


def get_machine_fingerprint() -> str:
    """
    Tạo mã định danh phần cứng duy nhất (Hardware Machine Fingerprint)
    cho máy tính Mac (dựa trên IOPlatformUUID và địa chỉ MAC).
    Không đổi ngay cả khi cài lại hệ điều hành hoặc đổi thư mục.
    """
    raw_id = ""
    # 1. Thử lấy IOPlatformUUID trên macOS
    if sys.platform == "darwin":
        try:
            out = subprocess.check_output(
                ["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"],
                stderr=subprocess.DEVNULL,
                timeout=3
            ).decode("utf-8")
            for line in out.splitlines():
                if "IOPlatformUUID" in line:
                    parts = line.split("=")
                    if len(parts) > 1:
                        raw_id = parts[1].strip().replace('"', '')
                        break
        except Exception:
            pass

    # 2. Dự phòng: lấy MAC address
    if not raw_id:
        try:
            mac_num = uuid.getnode()
            raw_id = ':'.join(('%012X' % mac_num)[i:i+2] for i in range(0, 12, 2))
        except Exception:
            raw_id = "GENERIC_MAC_NODE"

    # Tạo hash ngắn gọn 12 ký tự: BG-MAC-XXXX-XXXX
    h = hashlib.sha256(raw_id.encode("utf-8") + b"hardware_anchor").hexdigest().upper()
    return f"BG-MAC-{h[:4]}-{h[4:8]}-{h[8:12]}"


def _compute_state_hmac(install_time: float, machine_id: str) -> str:
    msg = f"{install_time:.4f}:{machine_id}".encode("utf-8")
    return hmac.new(MASTER_SECRET, msg, hashlib.sha256).hexdigest()


def _get_or_init_trial_state(machine_id: str) -> dict:
    now = time.time()
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            inst = data.get("installed_at", now)
            sig = data.get("signature", "")
            expected_sig = _compute_state_hmac(inst, machine_id)
            if hmac.compare_digest(sig, expected_sig):
                return {"installed_at": inst, "tampered": False}
            else:
                return {"installed_at": inst, "tampered": True}
        except Exception:
            pass

    # Tạo mới bản ghi dùng thử
    state = {
        "installed_at": now,
        "signature": _compute_state_hmac(now, machine_id)
    }
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f)
    except Exception:
        pass
    return {"installed_at": now, "tampered": False}


def generate_license_key(machine_id: str, tier: str = "LIFETIME", days_valid: int = None, customer_email: str = "") -> str:
    """
    Hàm sinh mã bản quyền dành riêng cho tác giả để cấp phép cho khách hàng khi bán.
    - machine_id: 'UNIVERSAL' hoặc mã định danh máy của khách ('BG-MAC-XXXX-XXXX-XXXX')
    - tier: 'LIFETIME' (Vĩnh viễn), 'PRO_ANNUAL' (1 năm), 'PRO_MONTHLY' (1 tháng), 'CLINIC' (Phòng khám/Nhà trẻ)
    """
    tier_clean = tier.upper().strip()
    if days_valid is not None and days_valid > 0:
        exp_timestamp = int((datetime.now() + timedelta(days=days_valid)).timestamp())
        exp_str = str(exp_timestamp)
    else:
        exp_str = "NEVER"

    target_machine = machine_id.strip().upper()
    raw_payload = f"{target_machine}|{tier_clean}|{exp_str}|{customer_email.strip().lower()}"
    sig = hmac.new(MASTER_SECRET, raw_payload.encode("utf-8"), hashlib.sha256).hexdigest().upper()
    
    # Định dạng key thương mại: BG-[TIER_CODE]-[EXP_HEX]-[MACHINE_SHORT]-[SIG_BLOCK]
    tier_codes = {
        "LIFETIME": "LFT",
        "PRO_ANNUAL": "PRO",
        "PRO_MONTHLY": "PRM",
        "CLINIC": "CLN"
    }
    tc = tier_codes.get(tier_clean, "STD")
    exp_code = hex(int(exp_str))[2:].upper() if exp_str != "NEVER" else "99999999"
    m_short = hashlib.md5(target_machine.encode()).hexdigest()[:4].upper()
    sig_block = sig[:8]

    # Cấu trúc: BG-LFT-99999999-ABCD-12345678
    license_key = f"BG-{tc}-{exp_code}-{m_short}-{sig_block}"
    return license_key


def verify_license_key(license_key: str, machine_id: str) -> dict:
    """
    Xác thực chữ ký mã bản quyền.
    """
    if not license_key:
        return {"valid": False, "reason": "empty"}

    parts = license_key.strip().split("-")
    if len(parts) != 5 or parts[0] != "BG":
        return {"valid": False, "reason": "invalid_format"}

    tier_code, exp_code, m_short, sig_block = parts[1], parts[2], parts[3], parts[4]
    
    tier_map = {
        "LFT": "LIFETIME",
        "PRO": "PRO_ANNUAL",
        "PRM": "PRO_MONTHLY",
        "CLN": "CLINIC"
    }
    tier = tier_map.get(tier_code, "UNKNOWN")

    # Kiểm tra hạn dùng
    if exp_code == "99999999":
        expires_at = None
        is_expired = False
    else:
        try:
            exp_ts = int(exp_code, 16)
            expires_at = datetime.fromtimestamp(exp_ts)
            is_expired = datetime.now() > expires_at
        except Exception:
            return {"valid": False, "reason": "invalid_expiry"}

    if is_expired:
        return {"valid": False, "reason": "expired", "expires_at": str(expires_at)}

    # Kiểm tra khớp máy (Hỗ trợ khóa theo máy hoặc khóa UNIVERSAL)
    candidates = [machine_id.strip().upper(), "UNIVERSAL"]
    verified = False
    matched_target = ""

    for cand in candidates:
        cand_short = hashlib.md5(cand.encode()).hexdigest()[:4].upper()
        if cand_short != m_short:
            continue
        exp_str = str(int(exp_code, 16)) if exp_code != "99999999" else "NEVER"
        # Thử xác minh signature với rỗng email hoặc bất kỳ
        # Tác giả khi sinh key có thể truyền email hoặc rỗng
        for email_cand in ["", "customer"]:
            raw_payload = f"{cand}|{tier}|{exp_str}|{email_cand}"
            sig = hmac.new(MASTER_SECRET, raw_payload.encode("utf-8"), hashlib.sha256).hexdigest().upper()
            if sig[:8] == sig_block:
                verified = True
                matched_target = cand
                break
        if verified:
            break

    if not verified:
        return {"valid": False, "reason": "signature_mismatch"}

    return {
        "valid": True,
        "tier": tier,
        "is_lifetime": (exp_code == "99999999"),
        "expires_at": str(expires_at) if expires_at else "Vĩnh viễn",
        "target_machine": matched_target
    }


class LicenseManager:
    """
    Bộ quản lý bản quyền thương mại BabyGuard AI:
    - Quản lý định danh phần cứng máy tính
    - Quản lý thời hạn dùng thử 14 ngày (Trial)
    - Kích hoạt bản quyền vĩnh viễn / gói đăng ký
    """
    def __init__(self, config: dict = None):
        self.config = config or {}
        self.machine_id = get_machine_fingerprint()

    def get_status(self) -> dict:
        stored_key = self.config.get("license_key", "").strip()
        
        # 1. Nếu có key, kiểm tra tính hợp lệ
        if stored_key:
            res = verify_license_key(stored_key, self.machine_id)
            if res.get("valid"):
                return {
                    "valid": True,
                    "status": "activated",
                    "tier": res.get("tier", "LIFETIME"),
                    "tier_display": "Bản quyền Thương Mại Vĩnh Viễn" if res.get("is_lifetime") else f"Gói Bản Quyền {res.get('tier')}",
                    "is_lifetime": res.get("is_lifetime", False),
                    "expires_at": res.get("expires_at", "Vĩnh viễn"),
                    "machine_id": self.machine_id,
                    "license_key": stored_key[:6] + "..." + stored_key[-4:] if len(stored_key) > 10 else stored_key
                }
            else:
                return {
                    "valid": False,
                    "status": "invalid_key",
                    "tier": "UNLICENSED",
                    "tier_display": "Mã Bản Quyền Không Hợp Lệ",
                    "reason": res.get("reason", "error"),
                    "machine_id": self.machine_id
                }

        # 2. Không có key -> Kiểm tra thời hạn Dùng thử (14 ngày)
        state = _get_or_init_trial_state(self.machine_id)
        if state.get("tampered"):
            return {
                "valid": False,
                "status": "tampered",
                "tier": "TRIAL",
                "tier_display": "Dùng Thử Bị Can Thiệp",
                "machine_id": self.machine_id,
                "days_left": 0
            }

        elapsed_days = (time.time() - state["installed_at"]) / 86400.0
        days_left = max(0, TRIAL_DAYS - int(elapsed_days))

        if days_left > 0:
            return {
                "valid": True,
                "status": "trial",
                "tier": "TRIAL",
                "tier_display": f"Bản Dùng Thử Miễn Phí (Còn {days_left} ngày)",
                "days_left": days_left,
                "machine_id": self.machine_id,
                "is_lifetime": False,
                "expires_at": f"Còn {days_left} ngày dùng thử"
            }
        else:
            return {
                "valid": False,
                "status": "trial_expired",
                "tier": "EXPIRED",
                "tier_display": "Hết Hạn Dùng Thử",
                "days_left": 0,
                "machine_id": self.machine_id,
                "is_lifetime": False
            }

    def activate_key(self, key_str: str) -> dict:
        key_clean = key_str.strip()
        res = verify_license_key(key_clean, self.machine_id)
        if res.get("valid"):
            self.config["license_key"] = key_clean
            # Cập nhật vào config.json
            try:
                cfg_path = CONFIG_PATH
                if os.path.exists(cfg_path):
                    with open(cfg_path, "r", encoding="utf-8") as f:
                        cfg = json.load(f)
                    cfg["license_key"] = key_clean
                    with open(cfg_path, "w", encoding="utf-8") as f:
                        json.dump(cfg, f, indent=4, ensure_ascii=False)
            except Exception as e:
                print(f"[LicenseManager] Lỗi lưu config: {e}")
            return {
                "success": True,
                "message": "Kích hoạt bản quyền thành công!",
                "tier": res.get("tier"),
                "status": self.get_status()
            }
        else:
            return {
                "success": False,
                "message": f"Mã bản quyền không hợp lệ hoặc không khớp với máy này (Mã máy: {self.machine_id}).",
                "reason": res.get("reason")
            }
