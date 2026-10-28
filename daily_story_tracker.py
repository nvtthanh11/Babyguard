"""
BabyGuard AI - Daily Meaningful Story & Character Building Module
"1 Ngày 1 Câu Chuyện Ý Nghĩa & Phương Pháp Dạy Con Thông Minh"
Cung cấp mỗi ngày một câu chuyện tích cực, câu chuyện ngụ ngôn, trích đoạn Kinh Thánh,
triết lý Phật giáo, hoặc các phương pháp giáo dục sớm từ sách nuôi dạy con.
Giúp ba mẹ có đề tài thủ thỉ, trò chuyện kích thích ngôn ngữ bên nôi cùng bé,
đồng thời gieo mầm nhân cách thiện lương, dũng cảm và biết yêu thương.
"""

import os
import json
import time
from datetime import date, datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STORIES_FILE = os.path.join(BASE_DIR, "baby_daily_stories.json")

# Kho tàng các câu chuyện ý nghĩa mẫu chất lượng cao (dự phòng khi không có mạng hoặc chưa cấu hình Gemini)
CURATED_FALLBACK_STORIES = [
    {
        "id": "story_01",
        "title": "Ngọn Đèn Của Lòng Nhân Ái",
        "category": "Truyện Ngụ Ngôn & Giáo Dục Lối Sống",
        "source": "Truyện cổ tích & Bài học cuộc sống",
        "quote": "Cho đi tình thương là cách tốt nhất để sưởi ấm tâm hồn chính mình.",
        "content": "Có một người mù đi bộ trong đêm tối, tay luôn cầm theo một chiếc đèn lồng sáng rực. Người qua đường thấy lạ bèn hỏi: 'Bác mù rồi, sao còn cầm đèn làm gì cho mất công?'. Người mù mỉm cười đáp: 'Chiếc đèn này tôi không thắp cho mắt tôi, mà thắp để những người đi trong đêm nhìn thấy tôi mà không va phải tôi, đồng thời soi sáng một đoạn đường cho họ'.",
        "parenting_lesson": "Dạy con biết suy nghĩ cho người khác ngay từ những việc nhỏ bé. Người biết quan tâm và mang lại ánh sáng cho xung quanh sẽ luôn được đón nhận bình an và tôn trọng.",
        "baby_talk_prompt": "Con yêu ơi, sau này khôn lớn, bố mẹ mong con sẽ là một ngọn đèn nhỏ ấm áp, luôn biết chia sẻ nụ cười và sự tử tế với mọi người xung quanh nhé."
    },
    {
        "id": "story_02",
        "title": "Hạt Cải Nhỏ Và Tình Thương Không Biên Giới",
        "category": "Triết Lý Phật Giáo & Nuôi Dưỡng Tâm Hồn",
        "source": "Kinh Phật giảng giải về Lòng Từ Bi & Sự Biết Ơn",
        "quote": "Tâm từ bi là gốc rễ của mọi sự may mắn và thanh thản.",
        "content": "Một đệ tử hỏi sư phụ: 'Lòng từ bi có hình thù như thế nào?'. Sư phụ đặt vào tay chú một hạt cải bé xíu rồi nói: 'Hạt cải này tuy nhỏ xíu, nhưng nếu con gieo xuống đất ẩm bằng sự nâng niu, tưới tắm bằng tình yêu thương mỗi ngày, nó sẽ lớn thành cây xum xuê che bóng mát cho đàn chim nhỏ trú ngụ. Lòng từ bi cũng vậy, bắt đầu từ những cử chỉ dịu dàng nhất'.",
        "parenting_lesson": "Nuôi dưỡng cho con tình yêu thiên nhiên, loài vật và sự kính trọng đối với ông bà, cha mẹ. Đứa trẻ được tắm mình trong tình thương bao dung sẽ luôn có trái tim kiên cường trước sóng gió.",
        "baby_talk_prompt": "Bé ngoan của bố mẹ ơi, con chính là mầm cây quý giá nhất của cả gia đình. Bố mẹ sẽ luôn ở bên che chở và dạy con lớn lên bằng tất cả tình thương êm đềm nhất."
    },
    {
        "id": "story_03",
        "title": "Người Cha Và Bó Đũa - Sức Mạnh Đoàn Kết",
        "category": "Truyện Cổ Tích Việt Nam",
        "source": "Kho tàng Cổ tích Việt Nam",
        "quote": "Một cây làm chẳng nên non, ba cây chụm lại nên hòn núi cao.",
        "content": "Một người cha già trước khi nhắm mắt đã gọi các con lại và đưa cho mỗi người một chiếc đũa, ai cũng bẻ gãy dễ dàng. Nhưng khi người cha bó cả bó đũa lại và bảo bẻ, không ai có thể làm gãy được. Người cha ân cần dặn: 'Các con là anh em một nhà, nếu chia rẽ thì yếu ớt, nhưng nếu biết yêu thương đùm bọc lẫn nhau thì không khó khăn nào quật ngã được'.",
        "parenting_lesson": "Dạy con quý trọng tình cảm gia đình, anh chị em và bạn bè. Tinh thần đồng đội và sự gắn kết là chìa khóa vàng cho mọi thành công trong đời sống.",
        "baby_talk_prompt": "A Siu ơi, gia đình mình luôn là bến đỗ bình yên nhất của con. Sau này dù đi đâu làm gì, con hãy luôn nhớ yêu thương và gắn kết cùng những người thân yêu nhé."
    },
    {
        "id": "story_04",
        "title": "Người Samaritan Nhân Hậu",
        "category": "Kinh Thánh & Đạo Đức Kitô Giáo",
        "source": "Kinh Thánh Tân Ước (Phúc Âm Lu-ca)",
        "quote": "Ai là người lân cận của con? Hãy mở lòng với bất kỳ ai đang cần sự giúp đỡ.",
        "content": "Một người lữ khách đi đường bị cướp đánh trọng thương nằm bên vệ đường. Nhiều người có học thức đi qua nhưng đều vội vã tránh xa. Chỉ có một người Samaritan nghèo đi ngang qua, động lòng trắc ẩn, đã dừng lại băng bó vết thương, đỡ người kia lên lưng lừa và đưa vào quán trọ, trả tiền chữa trị chu đáo cho người xa lạ.",
        "parenting_lesson": "Dạy con sự công bằng, lòng nhân hậu không phân biệt sang hèn, màu da hay xuất thân. Lòng trắc ẩn đối với người yếu thế chính là thước đo giá trị cao quý nhất của một con người.",
        "baby_talk_prompt": "Con trai nhỏ ơi, bố mẹ chúc con luôn có một trái tim can đảm và biết đồng cảm, luôn sẵn lòng dang tay an ủi những người gặp khó khăn trong cuộc đời."
    },
    {
        "id": "story_05",
        "title": "Cậu Bé Thomas Edison Và Bức Thư Của Mẹ",
        "category": "Sách Dạy Con Thông Minh & Nhân Cách Vĩ Nhân",
        "source": "Giai thoại danh nhân thế giới & Giáo dục tích cực",
        "quote": "Lời động viên đúng lúc của cha mẹ có thể thay đổi cả cuộc đời một đứa trẻ.",
        "content": "Ngày nhỏ, Thomas Edison mang về cho mẹ bức thư của nhà trường bảo cậu quá khờ khạo và từ chối dạy tiếp. Mẹ cậu đọc to thư trong nước mắt: 'Con trai bà là một thiên tài, trường chúng tôi không đủ giáo viên giỏi để dạy cậu bé. Xin bà hãy tự dạy con tại nhà'. Nhờ niềm tin mãnh liệt đó của mẹ, Edison đã tự học và phát minh ra bóng đèn điện soi sáng cả nhân loại.",
        "parenting_lesson": "Lời nói của cha mẹ có sức mạnh định hình tương lai con trẻ. Hãy luôn khen ngợi nỗ lực của con, chấp nhận sự khác biệt và không bao giờ dán nhãn tiêu cực lên con yêu.",
        "baby_talk_prompt": "A Siu yêu quý, con là món quà độc nhất vô nhị mà thượng đế ban tặng cho bố mẹ. Bố mẹ sẽ luôn tin tưởng và đồng hành cùng mọi ước mơ của con."
    }
]


class DailyStoryTracker:
    def __init__(self, data_file: str = None):
        self.data_file = data_file or STORIES_FILE
        self.data = self._load_data()

    def _load_data(self) -> dict:
        if os.path.exists(self.data_file):
            try:
                with open(self.data_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                print(f"[DailyStoryTracker] Lỗi đọc {self.data_file}: {e}")
        return {"stories": {}}

    def _save_data(self):
        try:
            os.makedirs(os.path.dirname(self.data_file), exist_ok=True)
            with open(self.data_file, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[DailyStoryTracker] Lỗi ghi {self.data_file}: {e}")

    def get_today_story(self, gemini_verifier=None, baby_name: str = "Bé A Siu",
                        age_display: str = "1 tháng 19 ngày", force_refresh: bool = False) -> dict:
        """
        Lấy câu chuyện ý nghĩa của ngày hôm nay. Nếu chưa có hoặc force_refresh=True,
        sẽ ưu tiên gọi Gemini tạo câu chuyện mới truyền cảm hứng sâu sắc.
        """
        today_str = date.today().strftime("%Y-%m-%d")
        existing = self.data.get("stories", {}).get(today_str)

        if existing and not force_refresh:
            return existing

        # Nếu có Gemini AI, gọi tạo câu chuyện độc bản cho ngày hôm nay
        if gemini_verifier and gemini_verifier.is_ready():
            try:
                story = self._generate_with_gemini(gemini_verifier, baby_name, age_display)
                if story:
                    story["date"] = today_str
                    story["created_at"] = datetime.now().strftime("%H:%M - %d/%m/%Y")
                    if "stories" not in self.data:
                        self.data["stories"] = {}
                    self.data["stories"][today_str] = story
                    self._save_data()
                    return story
            except Exception as e:
                print(f"[DailyStoryTracker] Lỗi gọi Gemini tạo truyện: {e}")

        # Dự phòng bằng kho truyện mẫu luân phiên theo ngày trong năm
        day_of_year = date.today().timetuple().tm_yday
        fallback = CURATED_FALLBACK_STORIES[day_of_year % len(CURATED_FALLBACK_STORIES)].copy()
        fallback["date"] = today_str
        fallback["created_at"] = datetime.now().strftime("%H:%M - %d/%m/%Y")
        fallback["source_type"] = "Curated Library"

        if "stories" not in self.data:
            self.data["stories"] = {}
        self.data["stories"][today_str] = fallback
        self._save_data()
        return fallback

    def _generate_with_gemini(self, gemini_verifier, baby_name: str, age_display: str) -> dict:
        prompt = f"""
Bạn là Chuyên gia Giáo Dục Nhân Cách & Kể Chuyện Thiếu Nhi Thế Giới của BabyGuard AI.
Nhiệm vụ của bạn là chọn lựa hoặc chuyển thể "1 NGÀY 1 CÂU CHUYỆN Ý NGHĨA & BÀI HỌC ĐẠO ĐỨC ĐẦU ĐỜI" dành cho ba mẹ của bé {baby_name} ({age_display}).

NGUYÊN TẮC TUYỂN CHỌN & PHÂN TÍCH BẮT BUỘC (TUYỆT ĐỐI TUÂN THỦ):
1. ƯU TIÊN CÂU CHUYỆN KINH ĐIỂN THẾ GIỚI:
   - Ưu tiên các tác phẩm kinh điển giàu tính nhân văn: Ngụ ngôn Aesop, truyện cổ Hans Christian Andersen, Lev Tolstoy, truyện cổ tích thế giới, Hạt giống tâm hồn.
   - TUYỆT ĐỐI TRÁNH BỊA ĐẶT các câu chuyện khó hiểu, kỳ quặc, viển vông hoặc giáo điều nặng nề.
2. MỤC TIÊU NUÔI DẠY ĐẠO ĐỨC TỐT NHẤT:
   - Mục đích tối thượng là nuôi dưỡng đạo đức đầu đời cho trẻ: Lòng nhân ái, sự biết ơn cha mẹ, đức tính trung thực, lòng dũng cảm, sự sẻ chia và khiêm nhường.
3. PHÂN TÍCH GIẢN DỊ, DỄ HIỂU:
   - Lời văn trong sáng, ấm áp, câu từ giản dị để ba mẹ dễ đọc hoặc thì thầm cùng bé bên nôi trước giờ ngủ.

Yêu cầu định dạng JSON bắt buộc:
{{
  "title": "Tiêu đề câu chuyện kinh điển ngắn gọn (dưới 10 chữ)",
  "category": "Ngụ Ngôn Thế Giới (Aesop / Andersen)" | "Bài Học Đạo Đức Đầu Đời" | "Hạt Giống Tâm Hồn",
  "source": "Tên nguồn kinh điển cụ thể (ví dụ: 'Truyện ngụ ngôn Aesop', 'Truyện cổ Andersen', 'Lev Tolstoy')",
  "quote": "Một câu đúc kết nhân cách giản dị, sâu sắc (1 câu ngắn)",
  "content": "Lời kể câu chuyện kinh điển ngắn gọn, văn phong ấm áp, trong sáng (khoảng 3-5 câu ngắn gọn)",
  "parenting_lesson": "Phân tích bài học nhân cách giản dị: Ba mẹ làm gương và dạy con đức tính tốt này như thế nào trong đời sống (2-3 câu dễ hiểu)",
  "baby_talk_prompt": "Lời thủ thỉ yêu thương dịu dàng ba mẹ nói bên nôi trước giờ bé ngủ (ví dụ: '{baby_name} ngoan ơi, sau này con lớn...')"
}}
"""
        resp = gemini_verifier._call_gemini_resilient(
            contents=prompt,
            call_type="daily_story",
            json_mode=True,
            temperature=0.3
        )
        if resp and resp.text:
            data = json.loads(resp.text)
            data["source_type"] = "Gemini AI"
            return data
        return None
