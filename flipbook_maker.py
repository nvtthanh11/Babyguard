"""
Flipbook Maker - Tạo video "cuốn sách lật liên tục" từ ảnh của bé.

- Cuốn album mở 2 trang: trang trái = ảnh trước, trang phải = ảnh hiện tại.
- Mỗi ảnh được lật trong FLIP_FRAMES khung hình (mặc định 6 khung @30fps = 0.2s => 5 ảnh/giây).
- Âm thanh lật trang được tổng hợp riêng cho từng lần lật và đặt đúng khung hình:
  tiếng "sột soạt" khi trang đang bay + tiếng "phạch" đúng lúc trang chạm trang trái.
"""
import os
import math
import subprocess
from datetime import datetime

import cv2
import numpy as np

try:
    from PIL import Image, ImageDraw, ImageFont
    HAS_PIL = True
except Exception:  # pragma: no cover
    HAS_PIL = False

FFMPEG = "/opt/homebrew/bin/ffmpeg" if os.path.exists("/opt/homebrew/bin/ffmpeg") else "ffmpeg"

W, H = 1280, 720
FPS = 30
FLIP_FRAMES = 12                    # 12 khung hình lật (~0.40s) cuộn góc lướt nhanh kiểu Apple Books
HOLD_FRAMES = 13                    # 13 khung hình giữ (~0.43s) ngắm ảnh rõ nét
# => Mỗi ảnh được hiển thị trọn vẹn ~0.83 giây (tăng tốc 120% so với bản trước)
SAMPLE_RATE = 44100

# Bố cục cuốn sách
SPINE_X = W // 2
PAGE_W = 560
PAGE_H = 600
PAGE_TOP = (H - PAGE_H) // 2 - 6
PAGE_BOT = PAGE_TOP + PAGE_H

FONT_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/Library/Fonts/Arial Unicode.ttf",
    "C:/Windows/Fonts/arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]


def _font(size):
    if not HAS_PIL:
        return None
    for f in FONT_CANDIDATES:
        if os.path.exists(f):
            try:
                return ImageFont.truetype(f, size)
            except Exception:
                pass
    return ImageFont.load_default()


def _draw_text(img_bgr, lines):
    """lines: list of (text, (x, y), size, (r,g,b), anchor). Hỗ trợ tiếng Việt có dấu qua PIL."""
    if not HAS_PIL:
        for text, (x, y), size, color, _ in lines:
            cv2.putText(img_bgr, text.encode("ascii", "ignore").decode(), (int(x) - 150, int(y)),
                        cv2.FONT_HERSHEY_SIMPLEX, size / 32.0, color[::-1], 1, cv2.LINE_AA)
        return img_bgr
    pil = Image.fromarray(cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB))
    d = ImageDraw.Draw(pil)
    for text, (x, y), size, color, anchor in lines:
        d.text((x, y), text, font=_font(size), fill=color, anchor=anchor)
    return cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2BGR)


# ---------------------------------------------------------------- Trang sách
def _paper(w=PAGE_W, h=PAGE_H):
    """Giấy màu kem có vân nhẹ."""
    rng = np.random.default_rng(7)
    base = np.full((h, w, 3), (226, 240, 248), dtype=np.float32)  # BGR kem
    noise = rng.normal(0, 3.0, (h, w, 1)).astype(np.float32)
    return np.clip(base + noise, 0, 255).astype(np.uint8)


def _make_page(img_path, caption):
    page = _paper()
    img = cv2.imread(img_path)
    if img is None:
        return None
    # khung ảnh
    max_w, max_h = PAGE_W - 60, PAGE_H - 110
    h, w = img.shape[:2]
    s = min(max_w / w, max_h / h)
    nw, nh = int(w * s), int(h * s)
    img = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_AREA)
    x0 = (PAGE_W - nw) // 2
    y0 = 30 + (max_h - nh) // 2
    # viền ảnh kiểu polaroid + bóng
    cv2.rectangle(page, (x0 - 8 + 4, y0 - 8 + 5), (x0 + nw + 8 + 4, y0 + nh + 8 + 5), (190, 205, 215), -1)
    cv2.rectangle(page, (x0 - 8, y0 - 8), (x0 + nw + 8, y0 + nh + 8), (255, 255, 255), -1)
    page[y0:y0 + nh, x0:x0 + nw] = img
    # Chữ ngày giờ to rõ, sắc nét
    page = _draw_text(page, [(caption, (PAGE_W // 2, PAGE_H - 45), 28, (60, 45, 35), "mm")])
    return page


def _make_cover_page(title, subtitle, quote=None):
    page = _paper()
    cv2.rectangle(page, (24, 24), (PAGE_W - 24, PAGE_H - 24), (160, 140, 120), 2)
    cv2.rectangle(page, (30, 30), (PAGE_W - 30, PAGE_H - 30), (190, 175, 160), 1)

    q1 = "Mỗi khoảnh khắc con khôn lớn là một món quà vô giá."
    q2 = "Hành trình vạn dặm bắt đầu từ từng giấc ngủ bình yên."
    if quote:
        q1 = quote
        q2 = ""

    lines = [
        ("NHẬT KÝ HÀNH TRÌNH", (PAGE_W // 2, 105), 17, (130, 110, 90), "mm"),
        (title, (PAGE_W // 2, 168), 34, (50, 35, 25), "mm"),
        (subtitle, (PAGE_W // 2, 222), 22, (100, 80, 65), "mm"),
        ("— ✦ —", (PAGE_W // 2, 270), 18, (150, 130, 110), "mm"),
        (f'"{q1}"', (PAGE_W // 2, 335), 20, (60, 45, 35), "mm"),
    ]
    if q2:
        lines.append((q2, (PAGE_W // 2, 375), 20, (60, 45, 35), "mm"))
    lines.extend([
        ("Yêu thương con từ hơi thở đầu tiên", (PAGE_W // 2, 450), 18, (120, 95, 80), "mm"),
        ("BabyGuard AI • Mắt Thần Bảo Vệ Bé", (PAGE_W // 2, PAGE_H - 40), 14, (150, 140, 130), "mm"),
    ])
    return _draw_text(page, lines)


def _make_end_page(motivational_quote=None):
    page = _paper()
    cv2.rectangle(page, (24, 24), (PAGE_W - 24, PAGE_H - 24), (160, 140, 120), 2)
    cv2.rectangle(page, (30, 30), (PAGE_W - 30, PAGE_H - 30), (190, 175, 160), 1)

    m1 = "Hãy cứ tự tin lớn khôn và mỉm cười rạng rỡ!"
    m2 = "Thế giới này bao la rộng lớn, và ba mẹ sẽ luôn là"
    m3 = "điểm tựa vững chãi nhất sau lưng con."
    if motivational_quote:
        m1 = motivational_quote
        m2 = ""
        m3 = ""

    lines = [
        ("LỜI NHẮN NHỦ GỬI CON YÊU", (PAGE_W // 2, 105), 17, (130, 110, 90), "mm"),
        ("Khép Lại Một Tháng Yêu Thương", (PAGE_W // 2, 168), 30, (50, 35, 25), "mm"),
        ("— ✦ —", (PAGE_W // 2, 222), 18, (150, 130, 110), "mm"),
        (f'"{m1}"', (PAGE_W // 2, 290), 20, (60, 45, 35), "mm"),
    ]
    if m2:
        lines.append((m2, (PAGE_W // 2, 335), 19, (60, 45, 35), "mm"))
    if m3:
        lines.append((m3, (PAGE_W // 2, 375), 19, (60, 45, 35), "mm"))
    lines.extend([
        ("Mãi yêu thương và tự hào về con!", (PAGE_W // 2, 450), 21, (160, 45, 45), "mm"),
        ("Còn rất nhiều trang tươi đẹp đang chờ con viết tiếp...", (PAGE_W // 2, PAGE_H - 40), 14, (140, 130, 120), "mm"),
    ])
    return _draw_text(page, lines)


def _background():
    bg = np.zeros((H, W, 3), dtype=np.uint8)
    for y in range(H):
        t = y / H
        bg[y, :] = (int(60 + 20 * t), int(75 + 25 * t), int(100 + 30 * t))  # gỗ ấm (BGR)
    # bìa sách (cứng) phía sau 2 trang
    cv2.rectangle(bg, (SPINE_X - PAGE_W - 18, PAGE_TOP - 14), (SPINE_X + PAGE_W + 18, PAGE_BOT + 14), (70, 40, 110), -1)
    # gáy dày (các trang xếp chồng)
    for i in range(6):
        c = 205 - i * 12
        cv2.rectangle(bg, (SPINE_X - PAGE_W - 6 + i, PAGE_TOP - 4 + i), (SPINE_X + PAGE_W + 6 - i, PAGE_BOT + 6 - i), (c, c + 10, c + 18), 1)
    return bg


def _spine_shade(canvas):
    """Bóng tối gần gáy sách cho chiều sâu."""
    x0, x1 = SPINE_X - 40, SPINE_X + 40
    region = canvas[PAGE_TOP:PAGE_BOT, x0:x1].astype(np.float32)
    xs = np.abs(np.arange(x1 - x0) - 40) / 40.0
    f = (0.72 + 0.28 * xs)[None, :, None]
    canvas[PAGE_TOP:PAGE_BOT, x0:x1] = (region * f).astype(np.uint8)


def _paste(canvas, page, x):
    canvas[PAGE_TOP:PAGE_BOT, x:x + PAGE_W] = page


# ---------------------------------------------------------------- Hiệu ứng Cuộn Góc Apple Books
SPREAD_W = 2 * PAGE_W + 40
SPREAD_H = PAGE_H + 40
SP_X0 = SPINE_X - PAGE_W - 20
SP_Y0 = PAGE_TOP - 20

# Tọa độ tiền xử lý (precomputed grids) để render siêu tốc
_GRID_YS, _GRID_XS = np.indices((PAGE_H, PAGE_W), dtype=np.float32)
_CAN_YS, _CAN_XS = np.indices((SPREAD_H, SPREAD_W), dtype=np.float32)
_CAN_LOC_X = _CAN_XS + (SP_X0 - SPINE_X)
_CAN_LOC_Y = _CAN_YS + (SP_Y0 - PAGE_TOP)

# Mặt sau trang giấy kem cao cấp
_BACK_TEXTURE = _paper()
cv2.rectangle(_BACK_TEXTURE, (18, 18), (PAGE_W - 18, PAGE_H - 18), (195, 185, 175), 1)
cv2.rectangle(_BACK_TEXTURE, (22, 22), (PAGE_W - 22, PAGE_H - 22), (210, 202, 195), 1)


def _render_peel_frame(front_page, back_page, next_page, left_page, t):
    """
    Hiệu ứng Cuộn Góc Chân Thực kiểu Apple Books (Realistic Diagonal Page Curl).
    t: tiến trình lật từ 0.0 (chưa lật) đến 1.0 (hoàn tất sang trang trái).
    """
    canvas = _background()
    _paste(canvas, left_page, SPINE_X - PAGE_W)
    _paste(canvas, next_page, SPINE_X)
    
    if t <= 0.005:
        _paste(canvas, front_page, SPINE_X)
        _spine_shade(canvas)
        return canvas
    if t >= 0.995:
        _paste(canvas, back_page, SPINE_X - PAGE_W)
        _spine_shade(canvas)
        return canvas

    ease_t = 0.5 - 0.5 * math.cos(math.pi * t)
    
    # Góc dưới phải xuất phát C(PAGE_W, PAGE_H)
    cx, cy = float(PAGE_W), float(PAGE_H)
    
    # Quỹ đạo cuộn góc P(x, y):
    px = PAGE_W - ease_t * (2.0 * PAGE_W)
    py = PAGE_H - 0.38 * PAGE_H * math.sin(math.pi * ease_t)
    
    mx, my = (cx + px) / 2.0, (cy + py) / 2.0
    vx, vy = px - cx, py - cy
    vlen = math.hypot(vx, vy)
    if vlen < 1e-4:
        _paste(canvas, front_page, SPINE_X)
        _spine_shade(canvas)
        return canvas
        
    nx, ny = vx / vlen, vy / vlen
    
    # 1. Trang phải: Vùng chưa bị cuộn (hướng về gáy sách) có dist >= 0
    dist = nx * (_GRID_XS - mx) + ny * (_GRID_YS - my)
    unpeeled_mask = dist >= 0
    
    right_buf = next_page.copy()
    right_buf[unpeeled_mask] = front_page[unpeeled_mask]
    
    # Bóng đổ mềm dưới nếp gấp trên trang kế tiếp
    shadow_mask = (dist < 0) & (dist > -80)
    if np.any(shadow_mask):
        shadow_f = np.clip(1.0 - 0.40 * (1.0 + dist[shadow_mask] / 80.0), 0.60, 1.0)[..., None]
        right_buf[shadow_mask] = (right_buf[shadow_mask].astype(np.float32) * shadow_f).astype(np.uint8)

    _paste(canvas, right_buf, SPINE_X)
    
    # 2. Vạt trang uốn cuộn (Curled Flap) phủ qua trang trái
    can_dist = nx * (_CAN_LOC_X - mx) + ny * (_CAN_LOC_Y - my)
    
    orig_x = _CAN_LOC_X - 2.0 * can_dist * nx
    orig_y = _CAN_LOC_Y - 2.0 * can_dist * ny
    
    flap_mask = (can_dist > 0) & (orig_x >= 0) & (orig_x < PAGE_W) & (orig_y >= 0) & (orig_y < PAGE_H)
    
    if np.any(flap_mask):
        map_x = np.where(flap_mask, (PAGE_W - 1 - orig_x), 0).astype(np.float32)
        map_y = np.where(flap_mask, orig_y, 0).astype(np.float32)
        
        flap_pixels = cv2.remap(_BACK_TEXTURE, map_x, map_y, interpolation=cv2.INTER_LINEAR)
        
        # Ánh sáng nổi khối 3D trên sống cuộn
        ridge_light = np.exp(-((can_dist - 14.0) ** 2) / 180.0) * 0.32
        flap_shade = np.clip(0.88 + ridge_light - 0.12 * (can_dist / (vlen + 1e-4)), 0.70, 1.3)[..., None]
        flap_shaded = np.clip(flap_pixels.astype(np.float32) * flap_shade, 0, 255).astype(np.uint8)
        
        target_roi = canvas[SP_Y0:SP_Y0 + SPREAD_H, SP_X0:SP_X0 + SPREAD_W]
        
        # Bóng đổ mờ lan tỏa dưới vạt cuộn
        flap_mask_u8 = flap_mask.astype(np.uint8) * 255
        flap_shadow = cv2.GaussianBlur(flap_mask_u8, (0, 0), 19).astype(np.float32) / 255.0
        shadow_darken = (1.0 - 0.35 * flap_shadow)[..., None]
        np.multiply(target_roi, shadow_darken, out=target_roi, casting="unsafe")
        
        target_roi[flap_mask] = flap_shaded[flap_mask]

    _spine_shade(canvas)
    return canvas


# ---------------------------------------------------------------- Âm thanh
def _flip_sound(rng, n_swish, flap_at):
    """Một tiếng lật trang: tiếng sột soạt (noise lọc) tăng dần + tiếng 'phạch' khi trang đáp xuống."""
    total = flap_at + int(0.08 * SAMPLE_RATE)
    out = np.zeros(total, dtype=np.float32)
    # swish: noise trắng lọc thông cao/thấp đơn giản, envelope dạng chuông
    noise = rng.normal(0, 1, n_swish).astype(np.float32)
    k = max(3, int(rng.integers(3, 7)))
    lp = np.convolve(noise, np.ones(k) / k, mode="same")
    hp = lp - np.convolve(lp, np.ones(40) / 40, mode="same")
    t = np.linspace(0, 1, n_swish, dtype=np.float32)
    env = (t ** 1.6) * np.exp(-((t - 0.75) ** 2) / 0.08)
    sw = hp * env
    start = max(0, flap_at - n_swish)
    out[start:start + n_swish] += sw[: total - start] * 0.55
    # flap: xung ngắn tắt nhanh
    n_flap = int(0.06 * SAMPLE_RATE)
    fn = rng.normal(0, 1, n_flap).astype(np.float32)
    fn = np.convolve(fn, np.ones(6) / 6, mode="same")
    fenv = np.exp(-np.linspace(0, 9, n_flap)).astype(np.float32)
    out[flap_at:flap_at + n_flap] += fn * fenv * 0.9
    return out


def _build_audio(n_flips, first_flip_frame, total_frames, music_file=None, seed=1):
    n_samples = int(total_frames / FPS * SAMPLE_RATE)
    track = np.zeros(n_samples, dtype=np.float32)
    rng = np.random.default_rng(seed)
    flip_len = FLIP_FRAMES / FPS
    cycle_frames = HOLD_FRAMES + FLIP_FRAMES
    for k in range(n_flips):
        f0 = first_flip_frame + k * cycle_frames + HOLD_FRAMES
        land_frame = f0 + FLIP_FRAMES - 1          # khung hình trang chạm hẳn bên trái
        land_s = int(land_frame / FPS * SAMPLE_RATE)
        n_swish = int(flip_len * 0.85 * SAMPLE_RATE)
        snd = _flip_sound(rng, n_swish, land_s - max(0, land_s - n_swish)) * rng.uniform(0.75, 1.0)
        st = max(0, land_s - n_swish)
        end = min(n_samples, st + len(snd))
        track[st:end] += snd[: end - st]
    peak = np.max(np.abs(track)) or 1.0
    track = track / peak * 0.8
    return track


# ---------------------------------------------------------------- Main
def make_flipbook_video(image_paths, out_mp4, title="Bé A Siu - Hành Trình Khôn Lớn",
                        subtitle=None, music_file=None, thumb_path=None):
    pages = []
    for p in image_paths:
        try:
            dt = datetime.fromtimestamp(os.path.getmtime(p)).strftime("%d/%m/%Y  %H:%M")
        except Exception:
            dt = ""
        pg = _make_page(p, dt)
        if pg is not None:
            pages.append(pg)
    if len(pages) < 2:
        raise ValueError("Không đủ ảnh hợp lệ để tạo video lật sách.")

    subtitle = subtitle or datetime.now().strftime("Tháng %m/%Y")
    cover = _make_cover_page(title, subtitle)
    end_page = _make_end_page()
    bg = _background()

    # Trình tự trang: cover(trái) | p0 (phải) -> lật p0 -> ... -> lật p_last -> end page (phải)
    # Trạng thái k: trái = left_seq[k], phải = right_seq[k]
    right_seq = pages + [end_page]
    left_seq = [cover] + pages

    INTRO = int(2.0 * FPS)
    OUTRO = int(3.0 * FPS)
    n_flips = len(pages)
    cycle_frames = HOLD_FRAMES + FLIP_FRAMES
    total_frames = INTRO + n_flips * cycle_frames + OUTRO

    if thumb_path:
        th = bg.copy()
        _paste(th, cover, SPINE_X - PAGE_W)
        _paste(th, pages[len(pages) // 2], SPINE_X)
        _spine_shade(th)
        cv2.imwrite(thumb_path, th, [cv2.IMWRITE_JPEG_QUALITY, 90])

    # Audio
    audio = _build_audio(n_flips, INTRO, total_frames)
    wav_path = out_mp4 + ".flip.raw"
    audio.astype(np.float32).tofile(wav_path)

    cmd = [FFMPEG, "-y", "-loglevel", "error",
           "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
           "-f", "f32le", "-ar", str(SAMPLE_RATE), "-ac", "1", "-i", wav_path]
    if music_file and os.path.exists(music_file):
        dur = total_frames / FPS
        cmd += ["-stream_loop", "-1", "-i", music_file,
                "-filter_complex",
                f"[2:a]volume=0.22,afade=t=in:st=0:d=1,afade=t=out:st={max(0, dur - 1.5)}:d=1.5[m];"
                f"[1:a][m]amix=inputs=2:duration=first:normalize=0[a]",
                "-map", "0:v", "-map", "[a]"]
    else:
        cmd += ["-map", "0:v", "-map", "1:a"]
    cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "160k", "-t", f"{(total_frames + 2) / FPS:.3f}",
            "-movflags", "+faststart", out_mp4]

    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        def emit(frame):
            try:
                proc.stdin.write(frame.tobytes())
            except (BrokenPipeError, OSError):
                pass

        def static(k):
            fr = bg.copy()
            _paste(fr, left_seq[k], SPINE_X - PAGE_W)
            _paste(fr, right_seq[k], SPINE_X)
            _spine_shade(fr)
            return fr

        intro_frame = static(0)
        for _ in range(INTRO):
            emit(intro_frame)

        for k in range(n_flips):
            # Giữ ảnh phẳng trong HOLD_FRAMES để người xem kịp ngắm nhìn
            cur_hold = static(k)
            for _ in range(HOLD_FRAMES):
                emit(cur_hold)

            # Cuộn góc lật trang mượt mà kiểu Apple Books trong FLIP_FRAMES
            front_p = right_seq[k]
            next_p = right_seq[k + 1]
            left_p = left_seq[k]
            back_p = left_seq[k + 1]

            for f in range(FLIP_FRAMES):
                t = (f + 1) / FLIP_FRAMES
                fr = _render_peel_frame(front_p, back_p, next_p, left_p, t)
                emit(fr)

        outro_frame = static(n_flips)
        for _ in range(OUTRO):
            emit(outro_frame)
        proc.stdin.close()
        err = proc.stderr.read().decode("utf-8", "ignore")
        proc.wait(timeout=300)
        if proc.returncode != 0 or not os.path.exists(out_mp4):
            raise RuntimeError(f"FFmpeg lỗi: {err[:300]}")
    finally:
        try:
            os.remove(wav_path)
        except Exception:
            pass

    return {"duration": round(total_frames / FPS, 1), "count": n_flips}
