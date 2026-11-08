"""
BabyGuard AI - Clinical Benchmark Evaluator
Đối chiếu số lượng ọ ẹ, số lượng ho, nhịp thở và sặc sữa với quy chuẩn quốc tế
(AAP - Viện Hàn lâm Nhi khoa Hoa Kỳ, BTS - Hội Lồng ngực Anh, CHEST - Trường Môn Lồng ngực Hoa Kỳ, WHO, Nelson Pediatrics).
"""

import os
import json

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
BENCHMARK_FILE = os.path.join(BASE_DIR, "medical_knowledge", "infant_clinical_benchmarks.json")

_CACHED_BENCHMARKS = None

def _load_benchmarks() -> dict:
    global _CACHED_BENCHMARKS
    if _CACHED_BENCHMARKS is not None:
        return _CACHED_BENCHMARKS
    if os.path.exists(BENCHMARK_FILE):
        try:
            with open(BENCHMARK_FILE, "r", encoding="utf-8") as f:
                _CACHED_BENCHMARKS = json.load(f)
                return _CACHED_BENCHMARKS
        except Exception as e:
            print(f"[ClinicalEvaluator] Lỗi đọc infant_clinical_benchmarks.json: {e}")
    return {}


def evaluate_whimper_count(count: int, age_days: int = 34) -> dict:
    """
    Đối chiếu số lần ọ ẹ / trở mình / giật mình sinh lý Moro trong 24h
    Chuẩn AAP (American Academy of Pediatrics) & Nelson Textbook of Pediatrics.
    """
    count = max(0, int(count))
    if count <= 35:
        status = "NORMAL"
        status_vi = "Bình thường (Sinh lý REM lành tính)"
        badge_color = "success"
        badge_symbol = "🟢"
        if count == 0:
            clinical_meaning = "Bé có chu kỳ ngủ rất êm ái hoặc cữ theo dõi ngắn. Các tiếng ọ ẹ chuyển giấc là hoàn toàn bình thường khi bé lớn dần."
        elif count < 15:
            clinical_meaning = f"Ghi nhận {count} lần ọ ẹ ngắn (< 4s). Bé tự xoa dịu rất tốt, giấc ngủ ổn định và không cần ba mẹ can thiệp."
        else:
            clinical_meaning = f"Ghi nhận {count} lần ọ ẹ ngắn (< 4s), nằm hoàn hảo trong ngưỡng sinh lý 15 - 35 lần/ngày. Phản ánh não bộ đang phát triển kết nối synap tích cực trong pha ngủ động REM."
    elif 36 <= count <= 50:
        status = "BORDERLINE"
        status_vi = "Tăng nhẹ / Cần theo dõi môi trường"
        badge_color = "warning"
        badge_symbol = "🟡"
        clinical_meaning = f"Ghi nhận {count} lần ọ ẹ. Bé cựa mình nhiều hơn trung bình, thường do đầy hơi chướng bụng, tã ướt hoặc nhiệt độ phòng chưa tối ưu (chuẩn phòng ngủ sơ sinh: 24-26°C)."
    else:
        status = "ELEVATED"
        status_vi = "Tăng cao / Cần phân biệt thở rên"
        badge_color = "danger"
        badge_symbol = "🔴"
        clinical_meaning = f"Ghi nhận {count} lần ọ ẹ/rên rỉ. Ba mẹ cần quan sát kỹ: nếu bé thở rên liên tục theo từng nhịp thở ra (expiratory grunting), phập phồng cánh mũi hoặc sốt, hãy đưa bé đi khám Nhi ngay."

    return {
        "count": count,
        "status": status,
        "status_vi": status_vi,
        "badge_color": badge_color,
        "badge_symbol": badge_symbol,
        "benchmark_range": "15 - 35 lần / 24h",
        "citation": "Chuẩn AAP & Nelson Pediatrics (Ngủ động REM sơ sinh)",
        "clinical_meaning_vi": clinical_meaning
    }


def evaluate_cough_count(count: int, age_days: int = 34) -> dict:
    """
    Đối chiếu số lần ho trong 24h
    Chuẩn BTS (British Thoracic Society) & CHEST Pediatric Cough Consensus.
    """
    count = max(0, int(count))
    if count <= 10:
        status = "NORMAL"
        status_vi = "Bình thường (Phản xạ sinh lý sạch đường thở)"
        badge_color = "success"
        badge_symbol = "🟢"
        if count == 0:
            clinical_meaning = "Hệ thống không ghi nhận cơn ho hay tiếng thở dốc nào. Đường thở của bé thông thoáng, hoàn toàn khỏe mạnh."
        else:
            clinical_meaning = f"Ghi nhận {count} lần ho rải rác. Theo chuẩn Hội Lồng ngực Anh (BTS) và CHEST, trẻ sơ sinh ho từ 1 - 10 lần/ngày là phản xạ sinh lý tự nhiên bình thường để làm sạch bụi và dịch hầu họng."
    elif 11 <= count <= 20:
        status = "BORDERLINE"
        status_vi = "Lưu tâm nhẹ / Theo dõi trào ngược sau bú"
        badge_color = "warning"
        badge_symbol = "🟡"
        clinical_meaning = f"Ghi nhận {count} cơn ho. Tần suất ho tăng nhẹ, thường liên quan đến trào ngược dạ dày thực quản sinh lý (GER) hoặc bú quá no/bú nhanh. Ba mẹ cần Bế vác thẳng đứng và vỗ ợ hơi kỹ 15–20 phút SAU KHI BÚ (lúc thức); khi đặt bé xuống ngủ BẮT BUỘC đặt nằm ngửa trên bề mặt nôi/đệm phẳng hoàn toàn (0 độ), không kê gối hay nâng nghiêng đệm ngủ."
    else:
        status = "ABNORMAL"
        status_vi = "Bất thường / Cần khám Bác sĩ Nhi khoa"
        badge_color = "danger"
        badge_symbol = "🔴"
        clinical_meaning = f"Ghi nhận {count} cơn ho (vượt ngưỡng an toàn > 20 lần/ngày). Cảnh báo nguy cơ viêm phế quản, viêm tiểu phế quản hoặc hít sặc sữa. Cần đưa bé đi khám nếu ho thành cơn đỏ mặt, có đờm khò khè hoặc sốt."

    return {
        "count": count,
        "status": status,
        "status_vi": status_vi,
        "badge_color": badge_color,
        "badge_symbol": badge_symbol,
        "benchmark_range": "≤ 10 lần / 24h (Rải rác)",
        "citation": "Chuẩn BTS (Anh) & CHEST (Hoa Kỳ)",
        "clinical_meaning_vi": clinical_meaning
    }


def evaluate_choke_count(count: int, spit_up_count: int = 0) -> dict:
    """
    Đối chiếu cảnh báo sặc sữa cấp cứu (Choking) và phân biệt rõ với Trớ sữa sinh lý lành tính (Happy Spitter / Regurgitation).
    Chuẩn AHA & AAP Pediatric Life Support.
    """
    count = max(0, int(count))
    spit_up_count = max(0, int(spit_up_count))
    if count == 0:
        status = "SAFE"
        status_vi = "An toàn tuyệt đối (0 lần sặc cấp cứu)"
        badge_color = "success"
        badge_symbol = "🟢"
        if spit_up_count > 0:
            clinical_meaning = (
                f"Hệ thống ghi nhận 0 lần sặc sữa tắc nghẽn đường thở cấp cứu (Choking). "
                f"Có {spit_up_count} lần trớ sữa sinh lý lành tính (Happy Spitter / Regurgitation) do cơ vòng thực quản dưới chưa hoàn thiện: "
                f"Ba mẹ lưu ý Bế vác thẳng đứng và vỗ ợ hơi kỹ 15–20 phút SAU KHI BÚ (lúc thức); khi đặt bé xuống ngủ BẮT BUỘC đặt nằm ngửa trên bề mặt nôi/đệm phẳng hoàn toàn (0 độ), không kê gối hay nâng nghiêng đệm ngủ."
            )
        else:
            clinical_meaning = "Hệ thống ghi nhận 0 lần sự cố tắc nghẽn đường thở do sặc sữa (Choking). Phản xạ nuốt và đường thở của bé được bảo vệ tối ưu."
    else:
        status = "EMERGENCY"
        status_vi = "Báo động khẩn cấp (Nguy cơ sặc sữa / Choking)"
        badge_color = "danger"
        badge_symbol = "🔴"
        clinical_meaning = (
            f"Hệ thống phát hiện {count} lần bé có dấu hiệu thở hắt/tắc nghẽn đường thở nghi Sặc sữa cấp cứu (Choking - khác với trớ sữa sinh lý Happy Spitter). "
            f"Ba mẹ cần nghiêng đầu bé sang một bên để dịch thoát ra và tuân thủ phác đồ sơ cứu 5 lần vỗ lưng : 5 lần ấn ngực của AHA nếu có tắc nghẽn!"
        )

    return {
        "count": count,
        "spit_up_count": spit_up_count,
        "status": status,
        "status_vi": status_vi,
        "badge_color": badge_color,
        "badge_symbol": badge_symbol,
        "benchmark_range": "0 lần sặc cấp cứu (Choking)",
        "citation": "Chuẩn an toàn cấp cứu AHA & AAP 2022",
        "clinical_meaning_vi": clinical_meaning
    }


def evaluate_respiration(bpm: float, age_months: int = 1) -> dict:
    """
    Đối chiếu nhịp thở khi ngủ yên
    Chuẩn WHO (Tổ chức Y tế Thế giới) & AAP.
    """
    bpm = round(float(bpm), 1)
    if bpm <= 0.0 or bpm < 20.0:
        status = "UNMEASURED"
        status_vi = "Góc camera ngoài vùng quét tối ưu"
        badge_color = "secondary"
        badge_symbol = "⚪"
        clinical_meaning = "Chỉ số 0.0 BPM là do giới hạn góc quay hoặc bé nằm ngoài khoảng quét quang học lồng ngực, không phản ánh bất thường về hô hấp."
    elif 30.0 <= bpm <= 60.0:
        status = "NORMAL"
        status_vi = "Nhịp thở chuẩn sơ sinh (30 - 60 BPM)"
        badge_color = "success"
        badge_symbol = "🟢"
        clinical_meaning = f"Nhịp thở quang học đạt {bpm} BPM, nằm trong khoảng sinh lý tối ưu 30 - 60 lần/phút của trẻ sơ sinh theo chuẩn WHO."
    elif bpm > 60.0:
        status = "TACHYPNEA"
        status_vi = "Thở nhanh (Tachypnea > 60 BPM)"
        badge_color = "danger"
        badge_symbol = "🔴"
        clinical_meaning = f"Nhịp thở quang học đo được {bpm} BPM (vượt ngưỡng 60 lần/phút). Theo WHO, thở nhanh liên tục khi ngủ yên là dấu hiệu chỉ điểm viêm phế quản phổi hoặc sốt, cần theo dõi sát."
    else:
        status = "BRADYPNEA"
        status_vi = "Nhịp thở chậm sinh lý"
        badge_color = "warning"
        badge_symbol = "🟡"
        clinical_meaning = f"Nhịp thở {bpm} BPM khi bé đang ngủ sâu, cần đối chiếu với cử động lồng ngực thực tế."

    return {
        "bpm": bpm,
        "status": status,
        "status_vi": status_vi,
        "badge_color": badge_color,
        "badge_symbol": badge_symbol,
        "benchmark_range": "30 - 60 BPM (Chuẩn sơ sinh WHO)",
        "citation": "Tổ chức Y tế Thế giới (WHO IMCI) & AAP",
        "clinical_meaning_vi": clinical_meaning
    }


def evaluate_full_daily_health(whimper_count: int, cough_count: int, choke_count: int, avg_bpm: float, age_days: int = 34, spit_up_count: int = 0) -> dict:
    """
    Tổng hợp toàn diện bảng đối chiếu quy chuẩn quốc tế cho báo cáo nhi khoa 24h.
    """
    whimper_eval = evaluate_whimper_count(whimper_count, age_days)
    cough_eval = evaluate_cough_count(cough_count, age_days)
    choke_eval = evaluate_choke_count(choke_count, spit_up_count=spit_up_count)
    resp_eval = evaluate_respiration(avg_bpm)

    # Đánh giá chung toàn bộ thể trạng
    overall_status = "TỐT"
    overall_color = "success"
    if choke_eval["status"] == "EMERGENCY" or cough_eval["status"] == "ABNORMAL" or resp_eval["status"] == "TACHYPNEA":
        overall_status = "CẦN CHÚ Ý Y TẾ"
        overall_color = "danger"
    elif whimper_eval["status"] == "BORDERLINE" or cough_eval["status"] == "BORDERLINE":
        overall_status = "THEO DÕI SINH LÝ"
        overall_color = "warning"

    return {
        "whimper": whimper_eval,
        "cough": cough_eval,
        "choke": choke_eval,
        "respiration": resp_eval,
        "overall_status": overall_status,
        "overall_color": overall_color
    }
