"""
BabyGuard AI - Daily Meaningful Story & Character Building Module
"1 Ngày 1 Câu Chuyện Ý Nghĩa & Phương Pháp Dạy Con Thông Minh"

Hệ thống kể chuyện đạo đức & phát triển nhân cách đầu đời cho trẻ sơ sinh & trẻ nhỏ.
- 7 Trụ cột nhân cách tương ứng 7 ngày trong tuần (Không lặp lại chủ đề trong 7 ngày).
- Lưu vết lịch sử chủ đề (theme_history) trong baby_daily_stories.json để đảm bảo tính độc bản.
- Lời văn chuyên nghiệp, giàu chất văn học (350 - 550 từ), chia đoạn mạch lạc.
- Bài học giáo dục con sâu sắc từ tâm lý học phát triển & lời thủ thỉ êm dịu bên nôi.
"""

import os
import json
import time
from datetime import date, datetime, timedelta

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STORIES_FILE = os.path.join(BASE_DIR, "baby_daily_stories.json")
STORY_LOG_FILE = os.path.join(BASE_DIR, "logs", "daily_stories_history.log")

GLOBAL_BANNED_STORIES = [
    "sư tử và chuột",
    "sư tử và chú chuột",
    "chuột nhắt và sư tử",
    "sư tử và chuột nhắt",
    "lion and mouse",
    "lion and the mouse",
    "the lion and the mouse"
]

def is_banned_story(title: str = "", content: str = "") -> bool:
    """Kiểm tra xem câu chuyện có nằm trong danh sách cấm lặp (vd: Chú chuột & sư tử) hay không."""
    s = f"{title} {content[:250]}".lower()
    return any(b in s for b in GLOBAL_BANNED_STORIES)


# ==============================================================================
# 7 TRỤ CỘT NHÂN CÁCH TRONG TUẦN (7 DISTINCT THEMATIC PILLARS)
# Thứ 2 -> Chủ Nhật: Luân phiên theo chu kỳ nghiêm ngặt, không trùng lặp trong tuần
# ==============================================================================
WEEKLY_THEMES = [
    {
        "weekday": 0,  # Monday / Thứ Hai
        "id": "perseverance",
        "day_name": "Thứ Hai",
        "theme_name": "Lòng Kiên Trì & Tinh Thần Vượt Khó",
        "category": "Ngụ Ngôn Thế Giới & Tinh Thần Bền Bỉ",
        "description": "Dạy con không nản lòng trước vấp ngã, từng bước nhỏ bền bỉ tích lũy để làm nên việc lớn.",
        "keywords": ["kiên trì", "bền bỉ", "vượt khó", "nỗ lực", "ý chí", "nhẫn nại"]
    },
    {
        "weekday": 1,  # Tuesday / Thứ Ba
        "id": "kindness",
        "day_name": "Thứ Ba",
        "theme_name": "Lòng Nhân Ái & Sự Tử Tế Dịu Dàng",
        "category": "Bài Học Đạo Đức & Trái Tim Nhân Ái",
        "description": "Nuôi dưỡng trái tim trắc ẩn, biết lắng nghe, nâng đỡ và trao gửi tình thương dịu dàng đến muôn loài.",
        "keywords": ["nhân ái", "tử tế", "khoan dung", "yêu thương", "đồng cảm", "dịu dàng"]
    },
    {
        "weekday": 2,  # Wednesday / Thứ Tư
        "id": "integrity",
        "day_name": "Thứ Tư",
        "theme_name": "Tính Trung Thực & Lòng Tự Trọng",
        "category": "Nhân Cách Vàng & Lòng Tự Trọng",
        "description": "Sống chân thành, giữ lời hứa, dám nhận lỗi và trân trọng giá trị ngay thẳng của bản thân.",
        "keywords": ["trung thực", "ngay thẳng", "tự trọng", "giữ lời hứa", "chân thành"]
    },
    {
        "weekday": 3,  # Thursday / Thứ Năm
        "id": "gratitude",
        "day_name": "Thứ Năm",
        "theme_name": "Lòng Biết Ơn & Tình Cảm Gia Đình",
        "category": "Cội Nguồn Yêu Thương & Tình Mẫu Tử Phụ Tử",
        "description": "Trân trọng công ơn dưỡng dục của cha mẹ, gắn kết tình anh em và biết ơn từng giọt nắng, hạt cơm mỗi ngày.",
        "keywords": ["biết ơn", "hiếu thảo", "gia đình", "tình mẹ cha", "trân trọng"]
    },
    {
        "weekday": 4,  # Friday / Thứ Sáu
        "id": "courage",
        "day_name": "Thứ Sáu",
        "theme_name": "Lòng Dũng Cảm & Tự Tin Bản Thân",
        "category": "Nuôi Dưỡng Bản Lĩnh & Sự Tự Tin",
        "description": "Dám bước qua nỗi sợ, tin vào vẻ đẹp độc bản của chính mình, không tự ti trước sự khác biệt.",
        "keywords": ["dũng cảm", "tự tin", "bản lĩnh", "độc bản", "vượt qua sợ hãi"]
    },
    {
        "weekday": 5,  # Saturday / Thứ Bảy
        "id": "cooperation",
        "day_name": "Thứ Bảy",
        "theme_name": "Sự Sẻ Chia & Tinh Thần Hợp Tác",
        "category": "Trí Tuệ Cảm Xúc EQ & Sự Gắn Kết",
        "description": "Sức mạnh của sự đoàn kết, sẻ chia niềm vui cùng bạn bè và thấu hiểu rằng cùng nhau sẽ đi xa hơn.",
        "keywords": ["chia sẻ", "hợp tác", "đoàn kết", "cho đi", "đồng đội"]
    },
    {
        "weekday": 6,  # Sunday / Chủ Nhật
        "id": "wonder",
        "day_name": "Chủ Nhật",
        "theme_name": "Tình Yêu Thiên Nhiên & Trí Tò Mò Sáng Tạo",
        "category": "Khám Phá Thế Giới & Trí Tò Mò Khoa Học",
        "description": "Say mê ngắm nhìn thế giới bao la với đôi mắt lấp lánh kỳ thú, trân trọng cỏ cây muôn thú và khát khao hiểu biết.",
        "keywords": ["thiên nhiên", "tò mò", "khám phá", "sáng tạo", "vũ trụ", "vạn vật"]
    }
]

# ==============================================================================
# KHO TRUYỆN MẪU DÀI, CHUYÊN NGHIỆP, CHUẨN VĂN HỌC (7 MASTERCLASS STORIES)
# Mỗi câu chuyện 350 - 550 từ, giàu cảm xúc, chia làm 3-4 đoạn văn chuẩn mực
# ==============================================================================
CURATED_FALLBACK_STORIES = [
    {
        "id": "story_mon_perseverance",
        "weekday": 0,
        "theme_id": "perseverance",
        "theme_name": "Thứ Hai: Lòng Kiên Trì & Tinh Thần Vượt Khó",
        "title": "Rùa Và Thỏ - Bản Trường Ca Về Từng Bước Chân Kiên Định",
        "category": "Ngụ Ngôn Aesop & Tinh Thần Bền Bỉ",
        "source": "Truyện Ngụ Ngôn Aesop",
        "quote": "Kỳ tích không thuộc về người chạy nhanh nhất, mà thuộc về người không bao giờ bỏ cuộc.",
        "content": """Trong một khu rừng ngập tràn sắc hoa và ánh nắng mai, chú Thỏ trắng nổi tiếng với đôi chân thoăn thoắt luôn tự hào mình là sinh linh nhanh nhẹn nhất trần đời. Mỗi khi gặp bác Rùa già trầm mặc mang trên lưng chiếc mai nặng trĩu bước đi chậm rãi từng bước một, Thỏ lại cất tiếng trêu đùa: 'Này bác Rùa, với tốc độ ấy, có lẽ bác phải mất cả đời người chỉ để đi hết một vòng bìa rừng mất thôi!'. Bác Rùa không hề tự ti hay giận dữ, chỉ ngước nhìn Thỏ bằng ánh mắt hiền từ và mỉm cười: 'Ai đi nhanh hay chậm chưa biết được, chúng ta hãy thử thi chạy lên đỉnh đồi phong đỏ kia xem sao'.

Cuộc chạy đua kỳ thú bắt đầu trước sự chứng kiến của muôn loài. Vừa nghe hiệu lệnh, Thỏ phóng vụt đi như một mũi tên xé gió, chỉ trong chớp mắt đã bỏ lại Rùa một quãng đường xa tít tắp. Nhìn lại sau lưng không thấy bóng dáng đối thủ đâu, Thỏ ung dung tự nhủ: 'Rùa bò chậm như sên, mình cứ chợp mắt đánh một giấc dưới bóng cây sồi râm mát này, đợi khi nào tỉnh dậy chạy vài bước là tới đích thôi'. Nghĩ là làm, Thỏ cuộn tròn đánh một giấc ngủ say sưa giữa làn gió trưa hiu hiu thổi.

Trong khi Thỏ say giấc mộng, bác Rùa vẫn kiên trì lê từng bước chân nhọc nhằn dưới cái nắng gay gắt. Chiếc mai nặng trĩu, từng giọt mồ hôi ướt đẫm trán, nhưng ánh mắt Rùa chưa từng rời khỏi đỉnh đồi phía trước. Rùa không dừng lại uống nước hay nghỉ chân bên bờ suối, mỗi bước chân đều chứa đựng niềm tin son sắt và ý chí sắt đá. Khi vầng dương ngả bóng về tây, Thỏ giật mình tỉnh giấc vội vã phóng vút lên đỉnh đồi, nhưng đã quá muộn: Bác Rùa đã đứng hiên ngang nơi vạch đích từ lâu trong tiếng reo hò rộn rã của cả khu rừng.

Câu chuyện ngụ ngôn muôn đời này là bài học vô giá: Tố chất thông minh hay tài năng thiên bẩm sẽ trở nên vô nghĩa nếu thiếu đi tính kỷ luật và sự kiên trì. Ngược lại, dù xuất phát điểm có khiêm tốn đến đâu, một trái tim bền bỉ không ngừng bước tới sẽ luôn chạm đến những đỉnh vinh quang rực rỡ nhất.""",
        "parenting_lesson": """1. Về mặt tâm lý phát triển: Trẻ sơ sinh và trẻ nhỏ hình thành tính bền bỉ (Grit) không phải qua những bài học lý thuyết mà từ cách cha mẹ khuyến khích con vượt qua những khó khăn đầu đời như tập lẫy, tập bò và tập đứng dậy sau mỗi lần té ngã.
2. Phương pháp nuôi dạy của ba mẹ: Hãy khen ngợi sự nỗ lực và quá trình của con thay vì chỉ khen kết quả. Khi con gặp khó khăn, ba mẹ đừng vội vàng làm thay tất cả mà hãy kiên nhẫn đồng hành, cổ vũ con thử lại thêm một lần nữa. Đó là hạt mầm của một nhân cách tự lập và kiên định sau này.""",
        "baby_talk_prompt": """Bé yêu ngoan của ba mẹ ơi, nhìn ngắm con đang say giấc ngủ bình yên trong nôi, ba mẹ cảm thấy lòng mình tràn ngập niềm hạnh phúc. Mai sau trên đường đời rộng lớn, con hãy luôn nhớ rằng: Không quan trọng con đi nhanh hay chậm, chỉ cần con luôn kiên trì và vững tin vào chính mình, từng bước nhỏ hôm nay sẽ đưa con đến mọi bến bờ ước mơ. Ngủ thật ngon con nhé, ba mẹ yêu con vô cùng."""
    },
    {
        "weekday": 1,
        "theme_id": "kindness",
        "theme_name": "Thứ Ba: Lòng Nhân Ái & Sự Tử Tế Dịu Dàng",
        "title": "Hoàng Tử Hạnh Phúc Và Chú Chim Én Nhỏ - Trái Tim Bằng Vàng",
        "category": "Bài Học Đạo Đức & Trái Tim Nhân Ái",
        "source": "Truyện Cổ Tích Oscar Wilde",
        "quote": "Điều đẹp đẽ nhất trên thế gian chỉ có thể cảm nhận bằng trái tim yêu thương chân thành.",
        "content": """Trên đỉnh một cột đá cao sừng sững giữa quảng trường thành phố, bức tượng Hoàng Tử Hạnh Phúc đứng uy nghiêm ngắm nhìn nhân gian. Tượng được dát bằng những lá vàng ròng óng ánh, đôi mắt là hai viên ngọc bích xanh biếc và trên chuôi kiếm nạm một viên hồng ngọc đỏ rực rỡ. Ai đi qua cũng ngước nhìn tượng với lòng ngưỡng mộ và khen ngợi chàng là biểu tượng của niềm hạnh phúc vĩnh cửu.

Một đêm mùa thu lạnh giá, một chú chim Én nhỏ mải mê bay về phương nam tránh rét muộn ghé vào đậu nghỉ chân dưới chân tượng Hoàng Tử. Bỗng nhiên, những giọt nước ấm áp rơi tí tách lên cánh chim. Én ngước nhìn lên ngỡ ngàng: Bức tượng lộng lẫy kia đang rưng rưng rơi những giọt nước mắt xót xa. Hoàng Tử nghẹn ngào cất tiếng: 'Thuở còn sống trong cung điện nguy nga, ta chưa từng biết đến đau khổ hay nước mắt. Nhưng giờ đây khi đứng trên cao, ta nhìn thấy tất cả sự cơ cực, đói nghèo và lạnh lẽo của muôn người nơi phố nhỏ'.

Hoàng Tử tha thiết nhờ chim Én cạy viên hồng ngọc trên chuôi kiếm mang tặng người mẹ nghèo có đứa con thơ đang sốt mê man không có thuốc thang; rồi lại xin Én lấy từng viên ngọc bích nơi khóe mắt gửi cho chàng thi sĩ đói lả và cô bé bán diêm lạnh cóng giữa trời đông. Cuối cùng, Hoàng Tử bảo Én bóc từng lá vàng dát trên thân mình trao cho những đứa trẻ lang thang đang co ro góc chợ. Mùa đông băng giá kéo đến, Hoàng Tử chỉ còn lại thân hình chì xám xịt trơ trụi và đôi mắt mù lòa, nhưng từ bên trong chàng tỏa ra hơi ấm của tình yêu thương vô bờ bến.

Chú chim Én vì thương Hoàng Tử cô độc nên quyết định không bay về phương nam ấm áp nữa, ở lại bầu bạn và sưởi ấm cho chàng cho đến khi kiệt sức vì giá lạnh rồi trút hơi thở cuối cùng dưới chân tượng. Đúng lúc ấy, trái tim bằng chì của Hoàng Tử vỡ đôi ra trong một tiếng nấc nghẹn ngào. Khi Thượng Đế bảo thiên thần hãy mang về thiên đàng hai vật quý giá nhất của thành phố, thiên thần đã mang về trái tim bằng chì vỡ vụn và chú chim Én nhỏ. Tình yêu thương vị tha và lòng nhân ái trao đi trọn vẹn chính là viên ngọc quý giá nhất, bất tử trước mọi thời gian.""",
        "parenting_lesson": """1. Về mặt tâm lý phát triển: Trí tuệ cảm xúc (EQ) và lòng trắc ẩn của trẻ nhỏ được bồi đắp sâu sắc nhất thông qua các câu chuyện văn học giàu tính biểu tượng. Trẻ hiểu rằng giá trị của một con người không nằm ở vẻ ngoài lộng lẫy hay của cải vật chất mà ở khả năng thấu cảm và san sẻ nỗi đau với người xung quanh.
2. Phương pháp nuôi dạy của ba mẹ: Hãy cùng con thực hành những nghĩa cử tử tế giản dị: Chia sẻ đồ chơi với bạn, nhẹ nhàng vỗ về khi thấy ai đó buồn bã, và dạy con biết trân trọng những tấm lòng chân thành hơn là những hào nhoáng bề ngoài.""",
        "baby_talk_prompt": """Bé A Siu yêu thương của ba mẹ ơi, thế giới này có thể rộng lớn và đôi khi lạnh giá, nhưng chỉ cần trong tim con luôn rực sáng một ngọn lửa nhân ái và dịu dàng, con sẽ sưởi ấm cho chính mình và mang lại bình an cho những người xung quanh. Ba mẹ chúc con có một giấc ngủ thật êm đềm, luôn là thiên thần mang lại niềm vui cho cuộc đời này con nhé."""
    },
    {
        "weekday": 2,
        "theme_id": "integrity",
        "theme_name": "Thứ Tư: Lòng Trung Thực & Lòng Tự Trọng",
        "title": "Người Tiều Phu Và Lưỡi Rìu Vàng - Lòng Trung Thực Vô Giá",
        "category": "Nhân Cách Vàng & Lòng Tự Trọng",
        "source": "Truyện Ngụ Ngôn Aesop & Cổ Tích Thế Giới",
        "quote": "Trung thực là chương đầu tiên trong cuốn sách của sự thông thái.",
        "content": """Ngày xưa, tại một thung lũng xanh mướt bên bìa rừng, có một người tiều phu nghèo sống cùng gia đình nhỏ. Cả gia tài của anh chỉ là một túp lều tranh xiêu vẹo và chiếc rìu sắt cũ kỹ do người cha quá cố để lại. Mỗi ngày, anh phải dậy từ lúc trời còn tờ mờ sương, vào tận rừng sâu đốn củi đem đổi lấy gạo nuôi sống vợ con. Dù cuộc sống trăm bề cơ cực, người tiều phu chưa bao giờ tham lam hay lấy không của ai một cọng rơm ngọn cỏ.

Một buổi trưa hè oi ả, khi đang chặt một thân gỗ khô bên bờ suối sâu nước chảy cuồn cuộn, chiếc rìu sắt trơn tuột khỏi bàn tay ướt đẫm mồ hôi rơi thẳng xuống dòng nước sâu thẳm. Mất đi công cụ kiếm sống duy nhất, người tiều phu ngồi sụp xuống bờ đá ôm mặt khóc nức nở trong sự bất lực. Bỗng nhiên, từ giữa dòng nước sủi bọt trắng xóa, một vị Thần sông râu tóc bạc phơ hiện lên với vẻ mặt đôn hậu, hỏi han sự tình rồi hứa sẽ lặn xuống tìm lại chiếc rìu cho anh.

Lần thứ nhất ngoi lên mặt nước, Thần sông cầm trên tay một chiếc rìu bằng vàng ròng lấp lánh dưới ánh mặt trời. Người tiều phu lắc đầu xua tay thật thà: 'Thưa Thần, đây không phải rìu của tôi'. Lần thứ hai, Thần lại mang lên một chiếc rìu bằng bạc sáng loáng tuyệt đẹp, anh vẫn kiên quyết từ chối: 'Dạ bẩm Thần, chiếc rìu của tôi đã cũ mòn và làm bằng sắt thô sơ thôi ạ'. Đến lần thứ ba, khi Thần đưa lên chiếc rìu sắt rỉ sét quen thuộc, đôi mắt người tiều phu bừng sáng niềm vui tột cùng: 'Ôi đúng là chiếc rìu của tôi rồi! Cảm ơn Thần linh rất nhiều!'.

Cảm phục trước tấm lòng trung thực, không mảy may tham lam trước cám dỗ bạc vàng, Thần sông mỉm cười tặng cho người tiều phu cả hai chiếc rìu vàng và bạc quý giá làm phần thưởng cho lòng tự trọng cao quý. Lòng trung thực tuy không mang lại lợi lộc tức thời trong mắt kẻ gian xảo, nhưng nó là tấm kim bài bảo vệ lương tâm và mang lại sự bình an, phúc đức viên mãn suốt một đời.""",
        "parenting_lesson": """1. Về mặt tâm lý phát triển: Tính trung thực bắt nguồn từ sự an toàn tâm lý (Psychological Safety). Nếu trẻ bị phạt quá nặng khi mắc sai lầm, trẻ sẽ hình thành cơ chế nói dối để tự vệ. Ngược lại, nếu được đón nhận bằng sự thấu hiểu, trẻ sẽ dũng cảm nhận lỗi và sống thật với lòng mình.
2. Phương pháp nuôi dạy của ba mẹ: Hãy khen ngợi lòng dũng cảm khi con dám nói ra sự thật dù kết quả có làm vỡ một món đồ chơi. Ba mẹ cũng cần giữ lời hứa tuyệt đối với con từ những việc nhỏ nhất như giờ đi ngủ hay món quà cuối tuần để con học được chữ Tín ngay từ trong gia đình.""",
        "baby_talk_prompt": """Bé cưng của ba mẹ ơi, con đang say sưa trong những giấc mơ ngọt ngào đầu đời. Sau này lớn lên, dù cuộc đời có nhiều ngã rẽ và cám dỗ, ba mẹ chỉ mong con luôn giữ cho tâm hồn mình trong vắt như dòng suối mai, dám sống chân thật và ngẩng cao đầu tự hào về phẩm giá của chính mình. Ba mẹ sẽ luôn là điểm tựa bình yên cho con."""
    },
    {
        "weekday": 3,
        "theme_id": "gratitude",
        "theme_name": "Thứ Năm: Lòng Biết Ơn & Tình Cảm Gia Đình",
        "title": "Cây Táo Yêu Thương - Bản Tình Ca Về Tình Cha Nghĩa Mẹ",
        "category": "Cội Nguồn Yêu Thương & Tình Mẫu Tử Phụ Tử",
        "source": "Giai Thoại 'The Giving Tree' (Shel Silverstein)",
        "quote": "Lòng biết ơn là gốc rễ nâng đỡ mọi tán cây đức hạnh vươn tới trời cao.",
        "content": """Ngày xửa ngày xưa, giữa một quả đồi ngập tràn cỏ xanh, có một cây táo cổ thụ sum suê cành lá và một cậu bé nhỏ vô cùng yêu quý nhau. Ngày ngày, cậu bé chạy đến nhặt lá kết vương miện giả làm vua rừng xanh, trèo lên thân cây đu cành và thưởng thức những quả táo ngọt lịm thơm ngon. Cây táo râm ran reo vui trong gió mỗi khi nghe tiếng cười trong trẻo của cậu. Cây yêu cậu bé tha thiết và coi cậu như đứa con quý báu nhất của mình.

Thế nhưng thời gian trôi qua, cậu bé dần khôn lớn và ít ghé thăm cây hơn. Một ngày nọ, cậu quay lại với khuôn mặt âu sầu: 'Tôi cần tiền để mua đồ chơi hiện đại'. Cây táo dịu dàng bảo: 'Ta không có tiền, nhưng con hãy hái hết táo của ta mang ra chợ bán, con sẽ có tiền'. Cậu bé mừng rỡ hái sạch từng quả táo rồi vội vã rời đi. Năm tháng trôi qua, cậu trở thành một người đàn ông trung niên mang đầy gánh nặng: 'Tôi cần một ngôi nhà để che chở cho vợ con'. Cây táo không ngần ngại đáp: 'Hãy chặt hết cành nhánh của ta đi để dựng nhà'. Người đàn ông chặt hết các cành cây xanh tốt chỉ để lại thân cây trơ trụi, nhưng cây táo vẫn cảm thấy hạnh phúc vì được cho đi.

Nhiều năm sau nữa, một ông lão lưng còng, tóc bạc phơ với đôi mắt mỏi mệt trở về bên đồi. Cây táo buồn rầu cất tiếng thì thầm nghẹn ngào: 'Ta xin lỗi, ta chẳng còn quả ngọt để con ăn, chẳng còn cành mát để con đu, ta chỉ còn lại một gốc cây mục già cỗi vô dụng...'. Ông lão mệt mỏi lắc đầu đáp: 'Bây giờ ta già rồi, răng rụng không ăn được táo, tay yếu không trèo được cành, ta chỉ cần một nơi thật yên tĩnh để ngồi nghỉ ngơi mà thôi'. Cây táo rướn hết phần gốc còn lại của mình lên và reo vui: 'Gốc cây già này chính là nơi tốt nhất để con tựa lưng. Hãy ngồi xuống đây với ta và nghỉ ngơi đi!'.

Người đàn ông ngồi xuống tựa lưng vào gốc cây thân thương, và cây táo lại rưng rưng niềm hạnh phúc ngập tràn. Tình yêu thương của cha mẹ dành cho con cái cũng hệt như cây táo kia: Vô điều kiện, bao la như biển trời, trao đi trọn vẹn cả cuộc đời mà không mong cầu đền đáp. Bài học biết ơn cha mẹ là đạo lý thiêng liêng nhất nuôi dưỡng nên một con người tử tế.""",
        "parenting_lesson": """1. Về mặt tâm lý phát triển: Lòng biết ơn giúp trẻ xây dựng hệ miễn dịch tâm lý vững vàng trước những áp lực xã hội. Một đứa trẻ biết ơn sẽ không rơi vào bẫy đòi hỏi ích kỷ mà luôn trân trọng những điều giản dị, sống chan hòa và lạc quan.
2. Phương pháp nuôi dạy của ba mẹ: Hãy cùng con bày tỏ lòng biết ơn mỗi ngày: Cảm ơn bát cơm ấm, cảm ơn chiếc áo ấm, nói lời yêu thương ông bà cha mẹ. Hãy cho con thấy rằng sự chăm sóc của gia đình không phải là điều hiển nhiên mà là kết tinh của tình yêu thương vô bờ bến.""",
        "baby_talk_prompt": """Bé cưng ơi, nghe tiếng thở đều đặn và êm ái của con trong nôi, ba mẹ chỉ muốn thời gian ngừng lại. Dù sau này con lớn khôn có bay xa đến tận chân trời góc bể, vòng tay gia đình và tình yêu của ba mẹ sẽ mãi mãi là bến đỗ bình yên nhất che chở cho con suốt cuộc đời. Ngủ ngoan nhé hạt mầm bé bỏng của ba mẹ."""
    },
    {
        "weekday": 4,
        "theme_id": "courage",
        "theme_name": "Thứ Sáu: Lòng Dũng Cảm & Tự Tin Bản Thân",
        "title": "Chú Vịt Con Xấu Xí Hóa Thiên Nga - Bản Lĩnh Vượt Qua Định Kiến",
        "category": "Nuôi Dưỡng Bản Lĩnh & Sự Tự Tin",
        "source": "Truyện Cổ Tích Hans Christian Andersen",
        "quote": "Không quan trọng bạn sinh ra trong chuồng vịt, miễn là bạn nở ra từ một quả trứng thiên nga.",
        "content": """Vào một buổi sáng mùa hè rực rỡ bên bờ đầm lầy thanh vắng, đàn vịt con lần lượt mổ vỏ chui ra khỏi những quả trứng tròn xoe vàng óng. Nhưng quả trứng to nhất ấp mãi mới nở lại cho ra đời một chú vịt kỳ lạ: Lông màu xám xịt lốm đốm, thân hình thô kệch, tiếng kêu khàn đặc chẳng giống ai. Cả bầy vịt trong nông trại xúm lại chê bai, lũ gà bới đất mổ xua đuổi, ngay cả cô chủ trang trại cũng hắt hủi chú vịt con tội nghiệp. Quá đau lòng và tủi hổ, chú vịt con đành phải gục đầu lầm lũi trốn chạy khỏi nông trại, dấn thân vào hành trình cô độc giữa tự nhiên bao la.

Mùa đông giá buốt ập đến mang theo những trận bão tuyết dữ dội. Chú vịt con rét run cầm cập, chân bị đóng băng giữa mặt hồ lạnh buốt, phải tự mình chống chọi với đói khát và nỗi cô đơn đến thắt lòng. Đã có những lúc tuyệt vọng tưởng chừng không thể gượng dậy nổi, nhưng sâu thẳm bên trong chú vẫn âm ỉ một khát khao sống mãnh liệt và niềm tin mơ hồ vào một ngày mai rực sáng. Chú kiên cường vượt qua từng đêm đông lạnh giá nhất của cuộc đời.

Khi nàng xuân ấm áp gõ cửa làm tan chảy lớp băng dày trên mặt hồ, cỏ cây đâm chồi nảy lộc xanh mướt. Một đàn thiên nga trắng muốt với đôi cánh kiêu hãnh và chiếc cổ thanh tú lướt nhẹ trên mặt nước trong veo. Vịt con nhìn thấy lũ chim quý phái bèn cúi gầm mặt xuống mặt nước vì sợ hãi bị chế giễu. Nhưng than ôi, hình ảnh phản chiếu dưới làn nước biếc xanh không còn là một chú vịt con xấu xí vụng về ngày nào nữa: Đó là một chú Thiên Nga trắng muốt tuyệt mỹ, sở hữu đôi cánh dũng mãnh và bộ lông tinh khôi lấp lánh dưới nắng mai!

Đàn thiên nga dang rộng đôi cánh chào đón chú như một người bạn tri kỷ, lũ trẻ bên hồ hò reo vui sướng: 'Nhìn kìa, con thiên nga mới tới là con đẹp nhất đàn!'. Chú giang đôi cánh rộng bay vút lên bầu trời xanh thẳm, cất tiếng hót ngân vang hạnh phúc. Bài học vĩ đại từ Andersen dạy chúng ta rằng: Đừng bao giờ đánh giá thấp bản thân chỉ vì sự khác biệt; gian nan thử thách chính là lò lửa tôi luyện nên một tâm hồn kiên cường và kiệt xuất.""",
        "parenting_lesson": """1. Về mặt tâm lý phát triển: Sự tự tin cốt lõi (Self-worth) được hình thành từ niềm tin tuyệt đối của cha mẹ dành cho con ngay từ thuở lọt lòng. Khi con cảm nhận được mình được trân trọng với đúng bản sắc độc bản, con sẽ không bao giờ gục ngã trước những định kiến hay lời chê bai của người đời.
2. Phương pháp nuôi dạy của ba mẹ: Đừng bao giờ so sánh con với 'con nhà người ta'. Mỗi đứa trẻ là một bông hoa có thời điểm nở rộ riêng biệt. Hãy khen ngợi sự khác biệt, khuyến khích con dũng cảm bộc lộ cá tính và luôn là chỗ dựa vững chãi nhất khi con vấp phải nỗi sợ hãi đầu đời.""",
        "baby_talk_prompt": """Bé yêu quý của ba mẹ ơi, con là một điều kỳ diệu độc nhất vô nhị mà vũ trụ này ban tặng cho ba mẹ. Con không cần phải giống bất kỳ ai, hãy cứ lớn lên tự tin, can đảm và tỏa sáng rực rỡ theo cách của riêng con. Dù cả thế giới có nghi ngờ con, ba mẹ vẫn sẽ luôn tin tưởng và yêu thương con bằng trọn vẹn trái tim này. Ngủ ngoan con nhé."""
    },
    {
        "weekday": 5,
        "theme_id": "cooperation",
        "theme_name": "Thứ Bảy: Sự Sẻ Chia & Tinh Thần Hợp Tác",
        "title": "Nồi Cháo Nấu Bằng Đá - Phép Màu Của Sự Gắn Kết Và Sẻ Chia",
        "category": "Trí Tuệ Cảm Xúc EQ & Sự Gắn Kết",
        "source": "Truyện Cổ Tích Dân Gian Châu Âu (Stone Soup)",
        "quote": "Bàn tay biết mở ra để sẻ chia là bàn tay nắm giữ được hạnh phúc trọn vẹn nhất.",
        "content": """Vào một buổi chiều thu ảm đạm sau nhiều năm mất mùa đói kém, ba người lính mệt mỏi hành quân ghé vào một ngôi làng nọ. Vì lo sợ bị xin ăn, dân làng đã vội vã đóng chặt cửa nẻo, then cài cẩn thận và đem giấu hết khoai tây, lúa mạch và củ cải xuống hầm sâu. Họ nhìn những người lữ khách xa lạ bằng ánh mắt nghi ngại và lạnh lùng, lắc đầu xua tay bảo rằng làng chẳng còn một hạt gạo dính răng để thết đãi.

Ba người lính thông thái không hề giận dỗi hay nài ép. Họ mỉm cười chào bà con rồi nhóm một đống lửa lớn ngay giữa quảng trường làng, đặt lên đó một chiếc nồi đồng khổng lồ đổ đầy nước suối. Một người lính từ tốn lấy từ túi ra ba hòn đá cuội tròn nhẵn thả vào nồi, khuấy đều tay rồi nói thật to: 'Chà, chúng ta sắp có món Cháo Nấu Bằng Đá thơm ngon tuyệt đỉnh nhất thế gian rồi!'. Dân làng hiếu kỳ hé mở then cửa nhìn ra, một vài người đánh bạo bước tới hỏi xem cháo đá mùi vị ra sao.

Người lính nếm thử một muỗng nước rồi chép miệng: 'Vị đá rất ngọt lành, nhưng nếu có thêm một chút muối tiêu và vài củ khoai tây béo bùi thì nồi cháo này sẽ xứng đáng dâng lên nhà vua thưởng thức'. Một bà lão lập tức chạy về nhà mang ra một rổ khoai tây cất giấu. Người lính lại bảo: 'Tuyệt vời quá! Giá như có thêm vài cọng cà rốt và một miếng thịt khô thì hương vị sẽ hoàn hảo không gì sánh bằng'. Một bác thợ mộc liền hăng hái về hầm mang ra khúc thịt xông khói thơm nức mũi. Cứ thế, người góp bó rau, người góp nắm hành, người góp bánh mì khô...

Chẳng mấy chốc, nồi cháo đá sôi sùng sục tỏa hương thơm ngào ngạt khắp ngõ xóm. Dân làng cùng nhau kê bàn ghế ra giữa sân, đốt đuốc sáng rực và ngồi quây quần thưởng thức bữa tiệc thịnh soạn trong tiếng đàn hát rộn rã mà họ chưa từng có suốt bao năm qua. Ai nấy đều ngạc nhiên trầm trồ trước món 'cháo đá' thần kỳ. Sự thật là, không có viên đá nào nấu ra được cháo cả; chính tinh thần hợp tác, sự cởi mở và lòng sẻ chia đã biến sự nghèo nàn, nghi kỵ thành một bữa tiệc ấm áp tình người ngập tràn hạnh phúc.""",
        "parenting_lesson": """1. Về mặt tâm lý phát triển: Trẻ em học được sự đồng cảm và kỹ năng xã hội (Social Skills) nhanh nhất thông qua các hoạt động hợp tác nhóm và chia sẻ đồ chơi. Một đứa trẻ biết chia sẻ sẽ dễ dàng kết bạn, được mọi người yêu mến và trở thành một nhà lãnh đạo thấu cảm trong tương lai.
2. Phương pháp nuôi dạy của ba mẹ: Hãy tạo cơ hội cho con thực hành chia sẻ từ trong gia đình: Mời ông bà ăn hoa quả trước, chia phần bánh cho bạn nhỏ, cùng nhau dọn dẹp nhà cửa. Dạy con hiểu rằng niềm vui khi được cho đi luôn ngọt ngào và bền lâu hơn việc nắm giữ khư khư cho riêng mình.""",
        "baby_talk_prompt": """Bé ngoan của ba mẹ ơi, nhìn nụ cười chúm chím của con trong giấc ngủ say nồng, ba mẹ thấy cuộc đời này thật tươi đẹp biết bao. Khi lớn lên, ba mẹ mong con sẽ luôn là một người bạn chân thành, biết san sẻ niềm vui và nâng đỡ bạn bè khi khó khăn. Những vòng tay mở rộng sẽ luôn đón nhận được những cái ôm ấm áp nhất của cuộc đời. Ngủ ngoan nhé thiên thần nhỏ."""
    },
    {
        "weekday": 6,
        "theme_id": "wonder",
        "theme_name": "Chủ Nhật: Tình Yêu Thiên Nhiên & Trí Tò Mò Sáng Tạo",
        "title": "Thomas Edison Và Ngọn Đèn Tò Mò Thắp Sáng Cả Thế Giới",
        "category": "Khám Phá Thế Giới & Trí Tò Mò Khoa Học",
        "source": "Giai Thoại Danh Nhân & Lòng Hiếu Kỳ Vĩ Đại",
        "quote": "Trí tưởng tượng và lòng tò mò chính là đôi cánh đưa con người vươn tới các vì sao.",
        "content": """Ngày xửa ngày xưa, tại một thị trấn nhỏ yên bình ở nước Mỹ, có một cậu bé với đôi mắt to tròn lấp lánh tên là Thomas Edison. Ngay từ khi còn là một đứa trẻ chập chững biết đi, Thomas đã luôn tò mò về mọi chuyển động của thế giới xung quanh. Cậu có thể ngồi hàng giờ dưới bóng râm để ngắm nhìn đàn kiến nhỏ tha mồi, say mê ngắm nhìn dòng nước chảy dưới chân cầu và không ngừng đặt ra hàng vạn câu hỏi 'Tại sao?': Tại sao bầu trời lại màu xanh? Tại sao chim có thể bay mà con người lại không thể?

Một buổi chiều mùa xuân ấm áp, người mẹ đi tìm con khắp nơi thì bàng hoàng phát hiện Thomas đang ngồi xổm im phăng phắc trong chuồng ngỗng, dưới bụng cậu ủ cẩn thận mấy quả trứng ngỗng to tròn. Khi mẹ dịu dàng hỏi con đang làm gì, cậu bé ngước đôi mắt ngây thơ đáp: 'Con thấy ngỗng mẹ nằm lên trứng thì trứng nở ra ngỗng con, con cũng đang thử ấp xem chúng có nở ra những chú ngỗng xinh đẹp không mẹ ạ!'. Thay vì quát mắng hay cười nhạo con ngốc nghếch, người mẹ mỉm cười ôm con vào lòng và giải thích cặn kẽ về nhiệt độ cơ thể và sự diệu kỳ của tạo hóa.

Lớn lên một chút, Thomas bị nhà trường trả về vì cho rằng cậu quá hiếu động và hỏi những câu hỏi kỳ lạ làm gián đoạn lớp học. Nhưng mẹ của Thomas - một người phụ nữ với tình mẫu tử vĩ đại - đã tự tay dạy dỗ con tại nhà, khích lệ mọi trí tò mò khoa học của cậu. Bà biến căn gác xép nhỏ thành phòng thí nghiệm cho con tự do pha chế hóa chất và mày mò chế tạo máy móc. Chính ngọn lửa tò mò không bao giờ tắt cùng niềm tin vô điều kiện của mẹ đã nuôi dưỡng Thomas trở thành nhà phát minh vĩ đại nhất lịch sử nhân loại với hơn một ngàn sáng chế, trong đó có bóng đèn điện thắp sáng đêm đen cho toàn thế giới.

Tình yêu thiên nhiên và lòng hiếu kỳ khám phá chính là hạt mầm của mọi trí tuệ vĩ đại. Một đứa trẻ luôn ngạc nhiên trước vẻ đẹp của một chiếc lá rơi hay cánh bướm rập rờn sẽ luôn giữ được tâm hồn phong phú, sáng tạo và tràn đầy tình yêu đối với cuộc sống muôn màu.""",
        "parenting_lesson": """1. Về mặt tâm lý phát triển: Trí tò mò (Curiosity) là động lực tự nhiên mạnh mẽ nhất thúc đẩy sự phát triển các kết nối nơ-ron thần kinh ở não bộ trẻ sơ sinh và trẻ nhỏ. Khi trẻ chỉ trỏ, sờ nắm hoặc nhìn chăm chú vào một vật, trẻ đang tiến hành những 'thí nghiệm khoa học' đầu tiên để khám phá thế giới.
2. Phương pháp nuôi dạy của ba mẹ: Hãy tôn trọng và khích lệ trí tò mò của con: Dành thời gian đưa con ra công viên ngắm cỏ cây hoa lá, lắng nghe tiếng chim hót và trả lời các câu hỏi của con bằng sự kiên nhẫn. Đừng bao giờ dập tắt trí tưởng tượng hay biến sự tò mò trong sáng của con thành điều sai trái.""",
        "baby_talk_prompt": """Bé cưng của ba mẹ ơi, thế giới ngoài kia rộng lớn, rực rỡ và ẩn chứa biết bao bí mật diệu kỳ đang chờ đón đôi bàn chân nhỏ bé của con khám phá. Ba mẹ mong con lớn lên sẽ luôn giữ được đôi mắt lấp lánh sự tò mò và một trái tim yêu mến thiên nhiên vạn vật sâu sắc. Hãy ngủ một giấc thật ngon lành, mai này lớn khôn con sẽ thắp sáng ước mơ của chính mình con nhé."""
    }
]


class DailyStoryTracker:
    def __init__(self, data_file: str = None):
        self.data_file = data_file or STORIES_FILE
        self.data = self._load_data()
        self.init_story_history_log()

    def _load_data(self) -> dict:
        if os.path.exists(self.data_file):
            try:
                with open(self.data_file, "r", encoding="utf-8") as f:
                    content = json.load(f)
                    if "stories" not in content:
                        content["stories"] = {}
                    if "theme_history" not in content:
                        content["theme_history"] = []
                    return content
            except Exception as e:
                print(f"[DailyStoryTracker] Lỗi đọc {self.data_file}: {e}")
        return {"stories": {}, "theme_history": []}

    def _save_data(self):
        try:
            os.makedirs(os.path.dirname(self.data_file), exist_ok=True)
            with open(self.data_file, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[DailyStoryTracker] Lỗi ghi {self.data_file}: {e}")

    def format_telegram_story(self, story: dict, baby_name: str = "Bé A Siu") -> str:
        """Định dạng câu chuyện thành một tin nhắn độc lập chuẩn đẹp, trang nhã để gửi & ghim Telegram."""
        title = story.get("title", "1 Ngày 1 Câu Chuyện").strip()
        cat = story.get("category", "Nhân Cách & Đạo Đức").strip()
        src = story.get("source", "Kho tàng Văn học").strip()
        quote = story.get("quote", "").strip()
        content = story.get("content", "").strip()
        lesson = story.get("parenting_lesson", "").strip()
        prompt = story.get("baby_talk_prompt", "").strip()
        date_str = story.get("date", datetime.now().strftime("%Y-%m-%d"))
        theme_name = story.get("theme_name", cat).strip()

        msg = (
            f"📖 <b>1 NGÀY 1 CÂU CHUYỆN Ý NGHĨA CHO CON — {baby_name.upper()}</b>\n"
            f"📅 <i>Ngày: {date_str} | Trụ cột: {theme_name}</i>\n"
            f"━━━━━━━━━━━━━━━━━━━\n\n"
            f"✨ <b>{title.upper()}</b>\n"
            f"🏛 <i>Nguồn: {src}</i>\n"
        )
        if quote:
            msg += f"💬 <i>\"{quote}\"</i>\n\n"
        else:
            msg += "\n"

        msg += f"{content}\n\n"
        msg += f"━━━━━━━━━━━━━━━━━━━\n"
        if lesson:
            msg += f"🌱 <b>BÀI HỌC NUÔI DẠY CON DÀNH CHO BA MẸ:</b>\n{lesson}\n\n"
        if prompt:
            msg += f"🤱 <b>LỜI THỦ THỈ BÊN NÔI CHO {baby_name.upper()}:</b>\n<i>\"{prompt}\"</i>\n"

        return msg

    def log_story_history(self, story: dict, context: str = "System", telegram_pinned: bool = False):
        """Ghi nhận lịch sử câu chuyện vào tệp logs/daily_stories_history.log."""
        try:
            log_dir = os.path.dirname(STORY_LOG_FILE)
            os.makedirs(log_dir, exist_ok=True)
            
            t_now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            d_str = story.get("date", datetime.now().strftime("%Y-%m-%d"))
            title = story.get("title", "Không rõ tiêu đề")
            theme = story.get("theme_name", story.get("category", "Đạo đức"))
            source = story.get("source", "Văn học kinh điển")
            src_type = story.get("source_type", "Unknown")
            quote = story.get("quote", "")
            lesson = story.get("parenting_lesson", "")
            pin_status = "📌 ĐÃ GHIM LÊN TELEGRAM" if telegram_pinned else "💾 ĐÃ LƯU HỆ THỐNG"

            entry = (
                f"================================================================================\n"
                f"[{t_now}] 📖 CÂU CHUYỆN NGÀY {d_str} — {title.upper()}\n"
                f"• Chủ đề nhân cách: {theme}\n"
                f"• Nguồn tác phẩm: {source}\n"
                f"• Phân loại nguồn: {src_type} (Ngữ cảnh: {context})\n"
                f"• Trạng thái Telegram: {pin_status}\n"
            )
            if quote:
                entry += f"• Câu đúc kết: \"{quote}\"\n"
            if lesson:
                entry += f"--------------------------------------------------------------------------------\n"
                entry += f"[Bài học nuôi dạy con]:\n{lesson}\n"
            entry += f"================================================================================\n\n"

            with open(STORY_LOG_FILE, "a", encoding="utf-8") as f:
                f.write(entry)
        except Exception as e:
            print(f"[DailyStoryTracker] Lỗi ghi daily_stories_history.log: {e}")

    def init_story_history_log(self):
        """Khởi tạo file log nếu chưa có dữ liệu, đồng bộ toàn bộ lịch sử từ file JSON."""
        try:
            log_dir = os.path.dirname(STORY_LOG_FILE)
            os.makedirs(log_dir, exist_ok=True)
            if not os.path.exists(STORY_LOG_FILE) or os.path.getsize(STORY_LOG_FILE) < 50:
                header = (
                    "================================================================================\n"
                    "         NHẬT KÝ 1 NGÀY 1 CÂU CHUYỆN Ý NGHĨA & DẠY CON — BABYGUARD AI         \n"
                    "   Hệ thống tự động theo dõi, ghi vết và chống lặp nội dung cho bé A Siu       \n"
                    "================================================================================\n\n"
                )
                with open(STORY_LOG_FILE, "w", encoding="utf-8") as f:
                    f.write(header)

                stories = self.data.get("stories", {})
                for d_str in sorted(stories.keys()):
                    st = stories[d_str]
                    self.log_story_history(st, context="Lịch sử đồng bộ ban đầu", telegram_pinned=(d_str == "2026-11-02"))
        except Exception as e:
            print(f"[DailyStoryTracker] Lỗi khởi tạo story log: {e}")

    def get_recent_history(self, days: int = 7) -> list:
        """
        Lấy danh sách các câu chuyện và chủ đề đã được kể trong vòng N ngày gần nhất (mặc định 7 ngày).
        Dùng để truyền vào prompt làm negative constraint (tuyệt đối không lặp lại).
        """
        history = self.data.get("theme_history", [])
        if not history:
            # Fallback thu thập từ dict stories nếu theme_history chưa có
            stories_dict = self.data.get("stories", {})
            sorted_dates = sorted(stories_dict.keys(), reverse=True)
            derived = []
            for d_str in sorted_dates[:days]:
                item = stories_dict[d_str]
                derived.append({
                    "date": d_str,
                    "theme_name": item.get("theme_name") or item.get("category", ""),
                    "title": item.get("title", ""),
                    "source": item.get("source", "")
                })
            return derived
        return history[-days:]

    def get_target_pillar_for_today(self, force_refresh: bool = False) -> dict:
        """
        Xác định trụ cột nhân cách cho ngày hôm nay (0-6 tương ứng Thứ 2 -> Chủ Nhật).
        Nếu force_refresh=True và chủ đề hôm nay vừa được dùng, sẽ luân phiên sang chủ đề kế tiếp chưa xuất hiện trong tuần.
        """
        today_weekday = date.today().weekday()  # 0: Monday, 6: Sunday
        default_theme = WEEKLY_THEMES[today_weekday]

        if not force_refresh:
            return default_theme

        # Kiểm tra các chủ đề gần đây trong 7 ngày
        recent_history = self.get_recent_history(days=6)
        used_theme_ids = {h.get("theme_id") for h in recent_history if "theme_id" in h}

        # Nếu default_theme đã dùng, chọn theme khác chưa dùng
        if default_theme["id"] in used_theme_ids:
            for theme in WEEKLY_THEMES:
                if theme["id"] not in used_theme_ids:
                    return theme

        return default_theme

    def get_today_story(self, gemini_verifier=None, baby_name: str = "Bé A Siu",
                        age_display: str = "1 tháng 19 ngày", force_refresh: bool = False) -> dict:
        """
        Lấy câu chuyện ý nghĩa của ngày hôm nay.
        Đảm bảo độ dài sâu sắc (350-550 từ), không trùng lặp chủ đề trong 7 ngày qua.
        """
        today_str = date.today().strftime("%Y-%m-%d")
        existing = self.data.get("stories", {}).get(today_str)

        # Nếu đã có câu chuyện hôm nay và không yêu cầu refresh, trả về ngay
        # TUY NHIÊN: Nếu câu chuyện cũ quá ngắn (dưới 150 từ - tàn dư câu chuyện cũ), tự động refresh để nâng cấp!
        if existing and not force_refresh:
            content_text = existing.get("content", "")
            if len(content_text.split()) >= 150:
                return existing
            print(f"[DailyStoryTracker] Câu chuyện {today_str} quá ngắn ({len(content_text.split())} từ). Đang tự động nâng cấp...")
            force_refresh = True

        target_pillar = self.get_target_pillar_for_today(force_refresh=force_refresh)
        recent_history = self.get_recent_history(days=7)

        # 1. Nếu có Gemini AI hoạt động, gọi tạo câu chuyện độc bản chuyên nghiệp dài 350-550 từ
        if gemini_verifier and gemini_verifier.is_ready():
            try:
                story = self._generate_with_gemini(gemini_verifier, baby_name, age_display, target_pillar, recent_history)
                if story and story.get("content") and len(story.get("content", "").split()) >= 120:
                    story["date"] = today_str
                    story["created_at"] = datetime.now().strftime("%H:%M - %d/%m/%Y")
                    story["theme_id"] = target_pillar["id"]
                    story["theme_name"] = f"{target_pillar['day_name']}: {target_pillar['theme_name']}"
                    story["source_type"] = "Gemini AI"

                    self._record_story(today_str, story, target_pillar)
                    return story
            except Exception as e:
                print(f"[DailyStoryTracker] Lỗi gọi Gemini tạo truyện: {e}")

        # 2. Dự phòng bằng kho truyện mẫu dài chất lượng cao (Masterclass Library)
        weekday = target_pillar["weekday"]
        matched_fallback = None
        for fb in CURATED_FALLBACK_STORIES:
            if fb.get("weekday") == weekday:
                matched_fallback = fb.copy()
                break
        if not matched_fallback:
            matched_fallback = CURATED_FALLBACK_STORIES[0].copy()

        matched_fallback["date"] = today_str
        matched_fallback["created_at"] = datetime.now().strftime("%H:%M - %d/%m/%Y")
        matched_fallback["source_type"] = "Curated Library"
        matched_fallback["theme_name"] = f"{target_pillar['day_name']}: {target_pillar['theme_name']}"

        self._record_story(today_str, matched_fallback, target_pillar)
        return matched_fallback

    def _record_story(self, today_str: str, story: dict, target_pillar: dict):
        """Lưu câu chuyện vào danh sách và cập nhật theme_history để theo dõi tuần"""
        if "stories" not in self.data:
            self.data["stories"] = {}
        if "theme_history" not in self.data:
            self.data["theme_history"] = []

        self.data["stories"][today_str] = story

        # Thêm vào lịch sử chủ đề tuần
        history_entry = {
            "date": today_str,
            "day_name": target_pillar.get("day_name", ""),
            "theme_id": target_pillar.get("id", ""),
            "theme_name": target_pillar.get("theme_name", ""),
            "story_title": story.get("title", ""),
            "source": story.get("source", ""),
            "category": story.get("category", "")
        }
        # Tránh trùng lặp ngày trong history
        self.data["theme_history"] = [h for h in self.data["theme_history"] if h.get("date") != today_str]
        self.data["theme_history"].append(history_entry)

        # Giữ lại tối đa 30 ngày lịch sử
        if len(self.data["theme_history"]) > 30:
            self.data["theme_history"] = self.data["theme_history"][-30:]

        self._save_data()
        self.log_story_history(story, context="Hệ thống lưu câu chuyện mới", telegram_pinned=False)

    def _generate_with_gemini(self, gemini_verifier, baby_name: str, age_display: str,
                              target_pillar: dict, recent_history: list) -> dict:
        """Gọi Gemini sinh câu chuyện dài, giàu cảm xúc, loại trừ nghiêm ngặt các tác phẩm đã kể trong 7 ngày"""
        excluded_titles_str = ""
        if recent_history:
            lines = []
            for h in recent_history:
                t = h.get("title") or h.get("story_title", "")
                src = h.get("source", "")
                thm = h.get("theme_name", "")
                if t:
                    lines.append(f"- Tác phẩm: \"{t}\" ({src}) - Chủ đề: {thm}")
            if lines:
                excluded_titles_str = "\n".join(lines)
            else:
                excluded_titles_str = "(Chưa có câu chuyện nào trong tuần)"
        else:
            excluded_titles_str = "(Chưa có câu chuyện nào trong tuần)"

        prompt = f"""
Bạn là Chuyên gia Giáo Dục Nhân Cách & Kể Chuyện Thiếu Nhi Hàng Đầu của Hệ thống BabyGuard AI.
Nhiệm vụ của bạn là sáng tác hoặc chuyển thể "1 NGÀY 1 CÂU CHUYỆN Ý NGHĨA & PHƯƠNG PHÁP NUÔI DẠY CON THÔNG MINH" dành cho ba mẹ của bé {baby_name} ({age_display}).

================================================================================
1. CHỦ ĐỀ BẮT BUỘC HÔM NAY ({target_pillar['day_name']}):
Trụ cột: {target_pillar['theme_name']}
Ý nghĩa cốt lõi: {target_pillar['description']}
Từ khóa định hướng: {', '.join(target_pillar['keywords'])}

================================================================================
2. DANH SÁCH BẮT BUỘC LOẠI TRỪ (TUYỆT ĐỐI KHÔNG ĐƯỢC LẶP LẠI TRONG 7 NGÀY QUA):
Trong 7 ngày vừa qua, hệ thống ĐÃ KỂ các câu chuyện sau:
{excluded_titles_str}

LƯU Ý NGHIÊM NGẶT:
- TUYỆT ĐỐI KHÔNG CHỌN LẠI bất kỳ câu chuyện nào đã nêu ở danh sách trên!
- ĐẶC BIỆT: Không được dùng lại truyện "Sư Tử Và Chuột Nhỏ" hay các câu chuyện vừa kể.
- Hãy chọn một câu chuyện kinh điển HOÀN TOÀN MỚI phù hợp với chủ đề {target_pillar['theme_name']}.
- Gợi ý kho tàng văn học phong phú: Ngụ ngôn Aesop, truyện cổ Andersen, truyện Lev Tolstoy, ngụ ngôn La Fontaine, Thần thoại Hy Lạp, Hạt giống tâm hồn, truyện cổ tích Việt Nam, giai thoại vĩ nhân thế giới (Edison, Newton, Marie Curie, Gandhi...).

================================================================================
3. YÊU CẦU ĐỘ DÀI & ĐẲNG CẤP VĂN HỌC BẮT BUỘC:
- ĐỘ DÀI: Phần kể chuyện (content) phải đạt từ 350 ĐẾN 550 TỪ (tuyệt đối không được viết tóm tắt 3-5 câu hời hợt!).
- BỐ CỤC NARRATIVE (content): Chia làm 3 ĐẾN 4 ĐOẠN VĂN RÕ RÀNG bằng ký tự xuống dòng (\\n\\n):
  + Đoạn 1 (Bối cảnh): Giới thiệu không gian, thời gian nên thơ, nhân vật và tình huống ban đầu.
  + Đoạn 2 (Xung đột & Thử thách): Cao trào kịch tính nơi nhân vật phải đối mặt với khó khăn hoặc thử thách đạo đức.
  + Đoạn 3 (Hành động & Khúc quanh): Nhân vật đưa ra lựa chọn can đảm/tử tế/kiên định dẫn đến kết quả bất ngờ giàu tính nhân văn.
  + Đoạn 4 (Đúc kết triết lý): Thông điệp ngân vang như một nốt nhạc êm đềm đọng lại trong tâm trí.
- BÀI HỌC DẠY CON (parenting_lesson): 120 - 180 từ, chia làm 2 ý rõ ràng (1. Cơ sở tâm lý học phát triển EQ; 2. Hành động thực tế ba mẹ nêu gương hàng ngày).
- LỜI THỦ THỈ BÊN NÔI (baby_talk_prompt): 60 - 90 từ, êm ái, thơ mộng như một bài hát ru thì thầm bên tai bé {baby_name}.

================================================================================
Yêu cầu định dạng JSON bắt buộc (không chứa markdown backticks thừa ngoài JSON):
{{
  "title": "Tiêu đề câu chuyện kinh điển đầy đủ, lôi cuốn (dưới 15 chữ)",
  "category": "{target_pillar['category']}",
  "source": "Tên nguồn kinh điển cụ thể (ví dụ: 'Truyện ngụ ngôn Aesop', 'Truyện cổ Andersen', 'Lev Tolstoy')",
  "quote": "Một câu đúc kết nhân cách sâu sắc, giàu hình ảnh (dưới 25 chữ)",
  "content": "Lời kể câu chuyện đầy đủ 3-4 đoạn văn (350-550 từ, dùng \\n\\n phân đoạn). Văn phong trong sáng, giàu cảm xúc, chuẩn mực văn học.",
  "parenting_lesson": "Phân tích 2 ý cụ thể: 1. Tâm lý học trẻ nhỏ; 2. Phương pháp ba mẹ làm gương và tương tác thực tế.",
  "baby_talk_prompt": "Lời thủ thỉ dịu dàng ba mẹ nói bên nôi trước giờ ngủ, gọi tên {baby_name}..."
}}
"""
        resp = gemini_verifier._call_gemini_resilient(
            contents=prompt,
            call_type="daily_story",
            json_mode=True,
            temperature=0.35
        )
        if resp and resp.text:
            text = resp.text.strip()
            # Xử lý trường hợp Gemini bọc markdown codeblock
            if text.startswith("```json"):
                text = text[7:]
            if text.startswith("```"):
                text = text[3:]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()

            data = json.loads(text)
            if is_banned_story(data.get("title", ""), data.get("content", "")):
                print(f"[DailyStoryTracker] ⚠️ Phát hiện câu chuyện bị cấm lặp ({data.get('title')}). Hủy bỏ và chọn tác phẩm kinh điển khác.")
                return None
            data["source_type"] = "Gemini AI"
            return data
        return None
