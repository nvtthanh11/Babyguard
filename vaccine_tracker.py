"""
BabyGuard AI - National & Private Vaccination Schedule Tracker
Quản lý Lịch Tiêm Chủng Mở Rộng Quốc Gia (Bộ Y Tế - Thông tư 52/2025/TT-BYT)
và Danh mục Vắc-xin Dịch vụ thiết yếu (VNVC / Viện Pasteur).
Hỗ trợ tích chọn đã tiêm, thêm mũi tiêm ngoài lịch / kết hợp, ghi chú phản ứng sau tiêm,
và tự động cảnh báo chống quên qua Telegram & Pop-up màn hình.
"""

import os
import json
from datetime import datetime, date, timedelta

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
VACCINE_FILE = os.path.join(BASE_DIR, "baby_vaccines.json")

# Danh mục lịch tiêm chủng chuẩn quốc gia & dịch vụ theo mốc tuổi
STANDARD_MILESTONES = [
    {
        "id": "milestone_birth",
        "name": "Mốc 1: Sơ sinh (0 – 30 ngày tuổi)",
        "target_days": 1,
        "months": 0,
        "badge_color": "emerald",
        "description": "Bắt buộc tiêm càng sớm càng tốt sau khi bé chào đời",
        "vaccines": [
            {
                "id": "hepb_birth",
                "name": "Vắc-xin Viêm gan B (Liều sơ sinh)",
                "disease": "Phòng bệnh Viêm gan vi-rút B lây truyền từ mẹ sang con",
                "type": "Tiêm bắp (Đùi)",
                "category": "TCMR Bắt buộc",
                "schedule_hint": "Tiêm trong vòng 24 giờ đầu sau sinh"
            },
            {
                "id": "bcg_birth",
                "name": "Vắc-xin Lao (BCG)",
                "disease": "Phòng bệnh Lao sơ sinh và Lao màng não nguy hiểm",
                "type": "Tiêm trong da (Vai trái)",
                "category": "TCMR Bắt buộc",
                "schedule_hint": "Tiêm trong 30 ngày đầu sau sinh"
            }
        ]
    },
    {
        "id": "milestone_2m",
        "name": "Mốc 2: Đủ 2 tháng tuổi (Mốc quan trọng nhất năm đầu)",
        "target_days": 60,
        "months": 2,
        "badge_color": "purple",
        "description": "Giai đoạn bắt đầu phác đồ bảo vệ đa bệnh và đường tiêu hóa",
        "vaccines": [
            {
                "id": "6in1_m1",
                "name": "Vắc-xin 6 trong 1 (hoặc 5 trong 1) — Mũi 1",
                "disease": "Bạch hầu, Ho gà, Uốn ván, Bại liệt, Viêm gan B, Hib",
                "type": "Tiêm bắp (Đùi)",
                "category": "Khuyến nghị 6in1 (Hexaxim / Infanrix Hexa)",
                "schedule_hint": "Tiêm khi tròn 2 tháng tuổi"
            },
            {
                "id": "rota_m1",
                "name": "Vắc-xin Rota Virus — Liều 1",
                "disease": "Phòng Tiêu chảy cấp do Rota virus (mất nước nguy kịch)",
                "type": "Uống trực tiếp",
                "category": "Dịch vụ / TCMR mở rộng",
                "schedule_hint": "Uống khi tròn 2 tháng (Rotavin / Rotarix / Rotateq)"
            },
            {
                "id": "pneumo_m1",
                "name": "Vắc-xin Phế cầu khuẩn — Mũi 1",
                "disease": "Phòng Viêm phổi, Viêm màng não mủ, Viêm tai giữa cấp",
                "type": "Tiêm bắp (Synflorix / Prevenar 13)",
                "category": "Dịch vụ thiết yếu",
                "schedule_hint": "Có thể tiêm cùng ngày với mũi 6 trong 1 ở 2 đùi khác nhau"
            }
        ]
    },
    {
        "id": "milestone_3m",
        "name": "Mốc 3: Đủ 3 tháng tuổi",
        "target_days": 90,
        "months": 3,
        "badge_color": "indigo",
        "description": "Tiếp tục liều 2 củng cố kháng thể (cách mũi 1 ít nhất 28 ngày)",
        "vaccines": [
            {
                "id": "6in1_m2",
                "name": "Vắc-xin 6 trong 1 (hoặc 5 trong 1) — Mũi 2",
                "disease": "Bạch hầu, Ho gà, Uốn ván, Bại liệt, Viêm gan B, Hib",
                "type": "Tiêm bắp (Đùi)",
                "category": "Khuyến nghị 6in1",
                "schedule_hint": "Cách mũi 1 tối thiểu 1 tháng (28 ngày)"
            },
            {
                "id": "rota_m2",
                "name": "Vắc-xin Rota Virus — Liều 2",
                "disease": "Phòng Tiêu chảy cấp do Rota virus",
                "type": "Uống trực tiếp",
                "category": "Dịch vụ / TCMR",
                "schedule_hint": "Cách liều 1 tối thiểu 1 tháng"
            },
            {
                "id": "pneumo_m2",
                "name": "Vắc-xin Phế cầu khuẩn — Mũi 2",
                "disease": "Viêm phổi, Viêm màng não, Viêm tai giữa",
                "type": "Tiêm bắp (Đùi)",
                "category": "Dịch vụ thiết yếu",
                "schedule_hint": "Cách mũi 1 tối thiểu 1 tháng"
            }
        ]
    },
    {
        "id": "milestone_4m",
        "name": "Mốc 4: Đủ 4 tháng tuổi",
        "target_days": 120,
        "months": 4,
        "badge_color": "cyan",
        "description": "Hoàn tất phác đồ 3 liều cơ bản 6in1 trong năm đầu đời",
        "vaccines": [
            {
                "id": "6in1_m3",
                "name": "Vắc-xin 6 trong 1 (hoặc 5 trong 1) — Mũi 3",
                "disease": "Bạch hầu, Ho gà, Uốn ván, Bại liệt, Viêm gan B, Hib",
                "type": "Tiêm bắp (Đùi)",
                "category": "Khuyến nghị 6in1",
                "schedule_hint": "Cách mũi 2 tối thiểu 1 tháng"
            },
            {
                "id": "rota_m3",
                "name": "Vắc-xin Rota Virus — Liều 3 (Nếu dùng Rotateq)",
                "disease": "Phòng Tiêu chảy cấp do Rota virus",
                "type": "Uống trực tiếp",
                "category": "Dịch vụ (Rotateq)",
                "schedule_hint": "Rotateq dùng 3 liều; Rotarix chỉ cần 2 liều (đã xong ở mốc 3 tháng)"
            },
            {
                "id": "pneumo_m3",
                "name": "Vắc-xin Phế cầu khuẩn — Mũi 3",
                "disease": "Viêm phổi, Viêm màng não, Viêm tai giữa",
                "type": "Tiêm bắp (Đùi)",
                "category": "Dịch vụ thiết yếu",
                "schedule_hint": "Cách mũi 2 tối thiểu 1 tháng"
            }
        ]
    },
    {
        "id": "milestone_5_6m",
        "name": "Mốc 5: Đủ 5 – 6 tháng tuổi",
        "target_days": 180,
        "months": 6,
        "badge_color": "amber",
        "description": "Bổ sung miễn dịch bại liệt, cúm mùa và não mô cầu",
        "vaccines": [
            {
                "id": "ipv_m1",
                "name": "Bại liệt tiêm IPV (Nếu tiêm 5in1 TCMR)",
                "disease": "Phòng bại liệt týp 2 theo chuẩn TCMR",
                "type": "Tiêm bắp",
                "category": "TCMR (Trẻ đã tiêm 6in1 dịch vụ có thể bỏ qua)",
                "schedule_hint": "Tiêm khi tròn 5 tháng tuổi"
            },
            {
                "id": "mening_b",
                "name": "Não mô cầu B (Bexsero) hoặc B+C (Mengoc BC)",
                "disease": "Phòng Viêm màng não mủ do vi khuẩn não mô cầu nhóm B, C",
                "type": "Tiêm bắp",
                "category": "Dịch vụ khuyến nghị cao",
                "schedule_hint": "Bexsero tiêm từ 2 tháng; Mengoc BC tiêm từ 6 tháng (2 mũi cách 45 ngày)"
            },
            {
                "id": "flu_m1",
                "name": "Vắc-xin Cúm mùa — Mũi 1 (Vaxigrip Tetra / Influvac)",
                "disease": "Phòng 4 chủng cúm A (H1N1, H3N2) và cúm B",
                "type": "Tiêm bắp",
                "category": "Dịch vụ khuyến nghị cao",
                "schedule_hint": "Bắt đầu tiêm khi đủ 6 tháng; tiêm 2 mũi cách nhau 1 tháng"
            }
        ]
    },
    {
        "id": "milestone_9m",
        "name": "Mốc 6: Đủ 9 tháng tuổi",
        "target_days": 270,
        "months": 9,
        "badge_color": "rose",
        "description": "Kháng thể mẹ truyền bắt đầu cạn kiệt, cần bảo vệ Sởi & Não Nhật Bản",
        "vaccines": [
            {
                "id": "measles_m1",
                "name": "Vắc-xin Sởi đơn (MVVac)",
                "disease": "Phòng bệnh Sởi biến chứng viêm phổi, viêm não",
                "type": "Tiêm dưới da",
                "category": "TCMR Bắt buộc",
                "schedule_hint": "Tiêm khi trẻ đủ 9 tháng tuổi"
            },
            {
                "id": "je_imojev_m1",
                "name": "Viêm não Nhật Bản thế hệ mới (Imojev) — Mũi 1",
                "disease": "Phòng Viêm não Nhật Bản di chứng thần kinh",
                "type": "Tiêm dưới da",
                "category": "Dịch vụ thế hệ mới (từ 9 tháng)",
                "schedule_hint": "Tiêm mũi 1 lúc 9 tháng, nhắc lại mũi 2 sau 1-2 năm"
            },
            {
                "id": "mening_acyw_m1",
                "name": "Não mô cầu ACYW (Menactra) — Mũi 1",
                "disease": "Phòng viêm màng não do 4 nhóm A, C, Y, W-135",
                "type": "Tiêm bắp",
                "category": "Dịch vụ",
                "schedule_hint": "Tiêm từ 9 tháng tuổi; 2 liều cách nhau 3 tháng"
            }
        ]
    },
    {
        "id": "milestone_12m",
        "name": "Mốc 7: Đủ 12 tháng tuổi (1 tuổi)",
        "target_days": 365,
        "months": 12,
        "badge_color": "violet",
        "description": "Cột mốc sinh nhật đầu tiên: Thủy đậu, Viêm gan A, Sởi-Quai bị-Rubella",
        "vaccines": [
            {
                "id": "varicella_m1",
                "name": "Vắc-xin Thủy đậu (Varilrix / Varivax) — Mũi 1",
                "disease": "Phòng bệnh Trái rạ / Thủy đậu",
                "type": "Tiêm dưới da",
                "category": "Dịch vụ thiết yếu",
                "schedule_hint": "Tiêm khi trẻ đủ 12 tháng tuổi"
            },
            {
                "id": "mmr_m1",
                "name": "Vắc-xin Sởi - Quai bị - Rubella (MMR II / Priorix)",
                "disease": "Phòng 3 bệnh truyền nhiễm Sởi, Quai bị, Rubella",
                "type": "Tiêm dưới da",
                "category": "Dịch vụ",
                "schedule_hint": "Tiêm khi trẻ đủ 12 tháng tuổi"
            },
            {
                "id": "hepa_m1",
                "name": "Vắc-xin Viêm gan A (Avaxim 80U / Hiberix) — Mũi 1",
                "disease": "Phòng bệnh Viêm gan vi-rút A lây qua đường ăn uống",
                "type": "Tiêm bắp",
                "category": "Dịch vụ",
                "schedule_hint": "Tiêm từ 12 tháng tuổi; nhắc mũi 2 sau 6 tháng"
            },
            {
                "id": "je_jevax",
                "name": "Viêm não Nhật Bản B (Jevax) — Mũi 1 & 2 (Nếu dùng vắc-xin TCMR)",
                "disease": "Phòng Viêm não Nhật Bản B",
                "type": "Tiêm dưới da",
                "category": "TCMR Miễn phí",
                "schedule_hint": "Mũi 1 lúc 1 tuổi, mũi 2 sau mũi 1 từ 1-2 tuần"
            }
        ]
    },
    {
        "id": "milestone_18m",
        "name": "Mốc 8: Đủ 18 tháng tuổi",
        "target_days": 540,
        "months": 18,
        "badge_color": "emerald",
        "description": "Nhắc lại toàn diện để duy trì miễn dịch bền vững đến tuổi đi học",
        "vaccines": [
            {
                "id": "6in1_booster",
                "name": "Vắc-xin 6 trong 1 (hoặc DPT) — Mũi 4 nhắc lại",
                "disease": "Nhắc Bạch hầu, Ho gà, Uốn ván, Bại liệt, Hib",
                "type": "Tiêm bắp",
                "category": "TCMR (DPT) hoặc Dịch vụ (6in1)",
                "schedule_hint": "Tiêm khi trẻ đủ 18 tháng tuổi"
            },
            {
                "id": "mr_booster",
                "name": "Vắc-xin Sởi - Rubella (MR) — Mũi nhắc",
                "disease": "Phòng bệnh Sởi và Rubella",
                "type": "Tiêm dưới da",
                "category": "TCMR Bắt buộc",
                "schedule_hint": "Tiêm khi trẻ đủ 18 tháng tuổi"
            },
            {
                "id": "pneumo_booster",
                "name": "Phế cầu khuẩn — Mũi nhắc lại (Lần 4)",
                "disease": "Củng cố miễn dịch phế cầu khuẩn lâu dài",
                "type": "Tiêm bắp",
                "category": "Dịch vụ",
                "schedule_hint": "Tiêm cách mũi 3 ít nhất 6 tháng"
            }
        ]
    }
]


def add_months_to_date(source_date: date, months: int) -> date:
    """Cộng thêm tháng vào ngày sinh một cách chính xác theo lịch dương."""
    month = source_date.month - 1 + months
    year = source_date.year + month // 12
    month = month % 12 + 1
    # Xử lý trường hợp ngày cuối tháng (ví dụ 31 không có ở tháng 2)
    import calendar
    max_days = calendar.monthrange(year, month)[1]
    day = min(source_date.day, max_days)
    return date(year, month, day)


class VaccineTracker:
    def __init__(self, data_file: str = None):
        self.data_file = data_file or VACCINE_FILE
        self.data = self._load_data()

    def _load_data(self) -> dict:
        if os.path.exists(self.data_file):
            try:
                with open(self.data_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                print(f"[VaccineTracker] Lỗi đọc file {self.data_file}: {e}")
        return {
            "records": {
                # Mặc định bé sinh ra ở bệnh viện thường đã tiêm Viêm gan B sơ sinh & Lao
                "hepb_birth": {
                    "completed": True,
                    "injected_date": "2026-09-05",
                    "note": "Đã tiêm tại Bệnh viện trong 24h đầu sau sinh"
                },
                "bcg_birth": {
                    "completed": True,
                    "injected_date": "2026-09-15",
                    "note": "Đã tiêm phòng Lao sơ sinh (vết tiêm mưng mủ tốt)"
                }
            },
            "custom_vaccines": []
        }

    def _save_data(self):
        try:
            os.makedirs(os.path.dirname(self.data_file), exist_ok=True)
            with open(self.data_file, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[VaccineTracker] Lỗi ghi file {self.data_file}: {e}")

    def update_record(self, vaccine_id: str, completed: bool, injected_date: str = "", note: str = "") -> bool:
        """Cập nhật trạng thái đã chích / chưa chích của một mũi tiêm."""
        if "records" not in self.data:
            self.data["records"] = {}

        if not completed:
            # Nếu bỏ tích "Đã tiêm", giữ lại ghi chú cũ nếu có
            prev_note = self.data["records"].get(vaccine_id, {}).get("note", "")
            self.data["records"][vaccine_id] = {
                "completed": False,
                "injected_date": "",
                "note": note or prev_note
            }
        else:
            injected_d = str(injected_date).strip() if injected_date else date.today().strftime("%Y-%m-%d")
            self.data["records"][vaccine_id] = {
                "completed": True,
                "injected_date": injected_d,
                "note": str(note or "").strip()
            }

        # Nếu là custom vaccine, cập nhật trực tiếp trong custom_vaccines
        for item in self.data.get("custom_vaccines", []):
            if item.get("id") == vaccine_id:
                item["completed"] = bool(completed)
                item["injected_date"] = str(injected_date).strip() if completed else ""
                if note:
                    item["note"] = str(note).strip()

        self._save_data()
        return True

    def add_custom_vaccine(self, milestone_id: str, name: str, disease: str = "",
                           injected_date: str = "", note: str = "", completed: bool = False) -> dict:
        """Thêm mũi tiêm ngoài lịch hoặc tiêm kết hợp do bố mẹ chủ động nhập."""
        if "custom_vaccines" not in self.data:
            self.data["custom_vaccines"] = []

        now_ts = int(datetime.now().timestamp())
        item_id = f"custom_{now_ts}"
        new_item = {
            "id": item_id,
            "milestone_id": milestone_id or "milestone_2m",
            "name": str(name).strip(),
            "disease": str(disease or "Tiêm mũi phối hợp / vắc-xin ngoài lịch").strip(),
            "type": "Tiêm bắp / Uống",
            "category": "Mũi tiêm bổ sung / Kết hợp",
            "schedule_hint": "Bố mẹ tự thêm vào sổ tiêm",
            "completed": bool(completed),
            "injected_date": str(injected_date).strip() if completed else "",
            "note": str(note or "").strip(),
            "is_custom": True
        }
        self.data["custom_vaccines"].append(new_item)
        if completed:
            if "records" not in self.data:
                self.data["records"] = {}
            self.data["records"][item_id] = {
                "completed": True,
                "injected_date": new_item["injected_date"],
                "note": new_item["note"]
            }
        self._save_data()
        return new_item

    def delete_custom_vaccine(self, vaccine_id: str) -> bool:
        """Xóa mũi tiêm ngoài lịch do người dùng tạo."""
        cust = self.data.get("custom_vaccines", [])
        initial_len = len(cust)
        self.data["custom_vaccines"] = [item for item in cust if item.get("id") != vaccine_id]
        if vaccine_id in self.data.get("records", {}):
            del self.data["records"][vaccine_id]
        if len(self.data["custom_vaccines"]) < initial_len:
            self._save_data()
            return True
        return False

    def get_schedule(self, birth_date_str: str) -> dict:
        """
        Tính toán lịch tiêm chủng đầy đủ đối chiếu ngày sinh của bé:
        - Tính ngày đến hạn (due_date) cho từng mốc
        - Xác định trạng thái: 'completed' (đã chích), 'due' (đang đến hạn trong 5 ngày),
          'overdue' (quá hạn mà chưa chích), 'upcoming' (chưa tới ngày)
        """
        today = date.today()
        b_date = None
        for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
            try:
                b_date = datetime.strptime(str(birth_date_str).strip(), fmt).date()
                break
            except Exception:
                pass
        if not b_date:
            b_date = date(2026, 9, 5)

        age_days = (today - b_date).days
        records = self.data.get("records", {})
        custom_vaccines = self.data.get("custom_vaccines", [])

        milestones_result = []
        all_due_or_overdue = []
        total_vaccines_count = 0
        total_completed_count = 0

        for ms in STANDARD_MILESTONES:
            ms_id = ms["id"]
            ms_months = ms["months"]
            if ms_months == 0:
                due_d = b_date
            else:
                due_d = add_months_to_date(b_date, ms_months)

            due_date_str = due_d.strftime("%d/%m/%Y")
            days_diff = (due_d - today).days

            vac_list = []
            # 1. Các mũi chuẩn trong mốc
            for v in ms["vaccines"]:
                total_vaccines_count += 1
                vid = v["id"]
                rec = records.get(vid, {})
                is_comp = bool(rec.get("completed", False))
                inj_date = rec.get("injected_date", "")
                note = rec.get("note", "")

                if is_comp:
                    status = "completed"
                    status_text = "Đã tiêm"
                    status_badge = "emerald"
                    total_completed_count += 1
                elif days_diff < 0:
                    status = "overdue"
                    status_text = f"Quá hạn {abs(days_diff)} ngày"
                    status_badge = "rose"
                    all_due_or_overdue.append({
                        "id": vid,
                        "name": v["name"],
                        "disease": v["disease"],
                        "milestone_name": ms["name"],
                        "due_date": due_date_str,
                        "status": "overdue",
                        "days_overdue": abs(days_diff)
                    })
                elif days_diff <= 14:
                    status = "due"
                    if days_diff == 0:
                        status_text = "Đến hạn hôm nay"
                    elif days_diff < 0:
                        status_text = f"Quá hạn {abs(days_diff)} ngày"
                    else:
                        status_text = f"Đến hạn trong {days_diff} ngày"
                    status_badge = "amber"
                    all_due_or_overdue.append({
                        "id": vid,
                        "name": v["name"],
                        "disease": v["disease"],
                        "milestone_name": ms["name"],
                        "due_date": due_date_str,
                        "status": "due",
                        "days_left": days_diff
                    })
                else:
                    status = "upcoming"
                    status_text = f"Còn {days_diff} ngày"
                    status_badge = "slate"

                vac_list.append({
                    "id": vid,
                    "name": v["name"],
                    "disease": v["disease"],
                    "type": v["type"],
                    "category": v["category"],
                    "schedule_hint": v["schedule_hint"],
                    "completed": is_comp,
                    "injected_date": inj_date,
                    "note": note,
                    "due_date": due_date_str,
                    "status": status,
                    "status_text": status_text,
                    "status_badge": status_badge,
                    "is_custom": False
                })

            # 2. Các mũi tự tạo thuộc mốc này
            for cv in custom_vaccines:
                if cv.get("milestone_id") == ms_id:
                    total_vaccines_count += 1
                    cvid = cv["id"]
                    is_comp = bool(cv.get("completed", False))
                    inj_date = cv.get("injected_date", "")
                    note = cv.get("note", "")
                    if is_comp:
                        status = "completed"
                        status_text = "Đã tiêm"
                        status_badge = "emerald"
                        total_completed_count += 1
                    else:
                        status = "due" if days_diff <= 14 else "upcoming"
                        status_text = "Đến hạn" if days_diff <= 14 else f"Còn {days_diff} ngày"
                        status_badge = "amber" if days_diff <= 5 else "slate"

                    vac_list.append({
                        "id": cvid,
                        "name": cv["name"],
                        "disease": cv.get("disease", "Mũi tiêm bổ sung"),
                        "type": cv.get("type", "Tiêm bắp / Uống"),
                        "category": "Mũi tiêm bổ sung / Kết hợp",
                        "schedule_hint": "Bố mẹ tự thêm vào sổ tiêm",
                        "completed": is_comp,
                        "injected_date": inj_date,
                        "note": note,
                        "due_date": due_date_str,
                        "status": status,
                        "status_text": status_text,
                        "status_badge": status_badge,
                        "is_custom": True
                    })

            # Xác định trạng thái tổng quan của Mốc
            all_done = all(v["completed"] for v in vac_list) if vac_list else False
            has_overdue = any(v["status"] == "overdue" for v in vac_list)
            has_due = any(v["status"] == "due" for v in vac_list)

            if all_done:
                ms_status = "completed"
                ms_status_text = "Đã hoàn thành mốc này"
                ms_badge = "emerald"
            elif has_overdue:
                ms_status = "overdue"
                ms_status_text = "Có mũi chưa tiêm quá hạn"
                ms_badge = "rose"
            elif has_due:
                ms_status = "due"
                ms_status_text = "Đến lịch tiêm chủng"
                ms_badge = "amber"
            else:
                ms_status = "upcoming"
                ms_status_text = f"Dự kiến: {due_date_str}"
                ms_badge = "slate"

            milestones_result.append({
                "id": ms_id,
                "name": ms["name"],
                "months": ms_months,
                "due_date": due_date_str,
                "days_diff": days_diff,
                "description": ms["description"],
                "status": ms_status,
                "status_text": ms_status_text,
                "badge_color": ms_badge,
                "vaccines": vac_list
            })

        # Tìm mốc kế tiếp gần nhất cần tiêm
        next_due_milestone = None
        for ms in milestones_result:
            if ms["status"] in ("due", "overdue") or (ms["status"] == "upcoming" and ms["days_diff"] >= 0):
                if any(not v["completed"] for v in ms["vaccines"]):
                    next_due_milestone = ms
                    break

        return {
            "birth_date": b_date.strftime("%Y-%m-%d"),
            "birth_date_display": b_date.strftime("%d/%m/%Y"),
            "baby_age_days": age_days,
            "total_vaccines": total_vaccines_count,
            "total_completed": total_completed_count,
            "completion_pct": round((total_completed_count / max(1, total_vaccines_count)) * 100, 1),
            "due_or_overdue_vaccines": all_due_or_overdue,
            "has_urgent_due": len(all_due_or_overdue) > 0,
            "next_due_milestone": next_due_milestone,
            "milestones": milestones_result
        }

    def format_telegram_alert(self, birth_date_str: str, baby_name: str = "Bé A Siu") -> str:
        """
        Tạo đoạn văn bản cảnh báo tiêm chủng chuẩn đẹp để chèn vào Báo Cáo Buổi Sáng lúc 07:00
        và ghim lên Telegram. Nếu không có mũi nào đến hạn/quá hạn thì trả về chuỗi rỗng.
        """
        sched = self.get_schedule(birth_date_str)
        due_items = sched.get("due_or_overdue_vaccines", [])
        if not due_items:
            return ""

        next_ms = sched.get("next_due_milestone")
        ms_name = next_ms["name"] if next_ms else "Mốc tiêm sắp tới"
        due_date = next_ms["due_date"] if next_ms else ""

        lines = [
            "🚨 <b>LỊCH TIÊM CHỦNG ĐẾN HẠN — BỐ MẸ ĐỪNG QUÊN!</b>",
            f"⚠️ <b>{ms_name} (Dự kiến: {due_date}):</b>"
        ]
        for it in due_items[:4]:
            st = "🔴 Quá hạn" if it.get("status") == "overdue" else "⏰ Đến hạn"
            lines.append(f"• 💉 <b>{it['name']}</b> ({st})")

        lines.append("\n💡 <i>Lưu ý: Bố mẹ kiểm tra bé không sốt, không bú quá no trước khi đi tiêm. Sau khi tiêm xong, nhớ vào Web tích 'Đã chích' thì hệ thống mới tắt thông báo nhắc nhở này nhé!</i>")
        return "\n".join(lines)
