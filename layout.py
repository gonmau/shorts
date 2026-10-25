"""
숏츠 화면 레이아웃 (헐코리아 스타일)
- 상단: 채널 프로필 + 채널명/핸들
- 제목: 2줄 (1줄 검정 / 2줄 강조색)
- 중앙: 이미지 (꽉 채우지 않고 정사각형 박스에 크롭)
- 이미지 아래: 출처/크레딧
- 하단: 비워둠 (유튜브 쇼츠가 채널명/구독/제목을 자동으로 얹는 영역)

사용법
    from layout import make_frame, make_template, IMG_BOX, SUBTITLE_Y

    # 1) 정지 프레임 한 장 (이미지 포함)
    make_frame("scene1.png", "세계 문화 상식", "이건 몰랐지?", "@mychannel",
               "out/frame1.png", channel_name="채널명", handle="@handle",
               avatar_path="avatar.png")

    # 2) 배경 템플릿만 (이미지 자리는 비워둠) -> moviepy 등에서 이미지에
    #    줌/패닝 효과를 주며 IMG_BOX 위치에 합성할 때 사용
    make_template(... , out_path="out/template.png")
"""
import os
from PIL import Image, ImageDraw, ImageFont, ImageOps
import textfix  # noqa: F401  (글꼴에 없는 하이픈 등을 네모칸 대신 안전한 글자로)

W, H = 1080, 1920
IMG_BOX = (40, 450, 1040, 1450)      # (x0, y0, x1, y1) 이미지 영역 1000x1000
IMG_RADIUS = 24
SUBTITLE_Y = 1270                    # 자막 중심 y (이미지 하단 안쪽)
BG = (250, 250, 252)
TITLE_COLOR_1 = (0, 0, 0)
TITLE_COLOR_2 = (200, 0, 255)        # 2줄 강조색 (보라/마젠타)

FONT_CANDIDATES_BOLD = [
    r"C:\Windows\Fonts\malgunbd.ttf",
    r"C:\Windows\Fonts\NanumGothicBold.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
]
FONT_CANDIDATES_REG = [
    r"C:\Windows\Fonts\malgun.ttf",
    r"C:\Windows\Fonts\NanumGothic.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
]


def _font(size, bold=True, font_path=None):
    paths = ([font_path] if font_path else []) + (
        FONT_CANDIDATES_BOLD if bold else FONT_CANDIDATES_REG)
    for p in paths:
        if p and os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def _fit_font(draw, text, max_w, start, min_size=40, bold=True, font_path=None):
    size = start
    while size > min_size:
        f = _font(size, bold, font_path)
        if draw.textlength(text, font=f) <= max_w:
            return f
        size -= 2
    return _font(min_size, bold, font_path)


def _centered(draw, text, y, font, fill, cx=W // 2):
    w = draw.textlength(text, font=font)
    draw.text((cx - w / 2, y), text, font=font, fill=fill)


def _circle_avatar(size, avatar_path=None, fallback_text="C"):
    if avatar_path and os.path.exists(avatar_path):
        im = ImageOps.fit(Image.open(avatar_path).convert("RGB"), (size, size))
    else:
        im = Image.new("RGB", (size, size), (60, 90, 200))
        d = ImageDraw.Draw(im)
        f = _font(int(size * 0.5))
        tw = d.textlength(fallback_text, font=f)
        d.text(((size - tw) / 2, size * 0.22), fallback_text, font=f, fill="white")
    mask = Image.new("L", (size * 4, size * 4), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size * 4 - 1, size * 4 - 1), fill=255)
    mask = mask.resize((size, size), Image.LANCZOS)
    out = Image.new("RGBA", (size, size))
    out.paste(im, (0, 0))
    out.putalpha(mask)
    return out


def make_template(title1, title2, credit, out_path=None, *, channel_name="채널명",
                  handle="@handle", avatar_path=None,
                  title_color_2=TITLE_COLOR_2, font_path=None):
    """이미지 자리가 비어 있는 배경 템플릿 (RGB) 생성."""
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)

    # --- 상단 헤더: 아바타 + 채널명/핸들 ---
    av = _circle_avatar(130, avatar_path, channel_name[:1])
    img.paste(av, (110, 55), av)
    d.text((265, 62), channel_name, font=_font(52, True, font_path), fill=(20, 20, 20))
    d.text((265, 128), handle, font=_font(44, False, font_path), fill=(90, 90, 90))

    # --- 제목 2줄 ---
    max_w = W - 100
    f1 = _fit_font(d, title1, max_w, 88, font_path=font_path)
    f2 = _fit_font(d, title2, max_w, 88, font_path=font_path)
    _centered(d, title1, 215, f1, TITLE_COLOR_1)
    _centered(d, title2, 315, f2, title_color_2)

    # --- 이미지 영역(자리표시) ---
    x0, y0, x1, y1 = IMG_BOX
    d.rounded_rectangle(IMG_BOX, radius=IMG_RADIUS, fill=(225, 225, 228))

    # --- 크레딧 ---
    _centered(d, credit, y1 + 30, _font(42, True, font_path), (70, 70, 70))

    # 하단(약 1500px 아래)은 유튜브 쇼츠 UI(채널명/구독/제목)가 덮는 영역이라 비워둔다

    if out_path:
        os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
        img.save(out_path)
    return img


def fit_into_box(image_path):
    """이미지를 IMG_BOX 크기로 중앙 크롭 + 둥근 모서리 (RGBA)."""
    x0, y0, x1, y1 = IMG_BOX
    bw, bh = x1 - x0, y1 - y0
    im = ImageOps.fit(Image.open(image_path).convert("RGB"), (bw, bh), Image.LANCZOS)
    mask = Image.new("L", (bw, bh), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, bw - 1, bh - 1),
                                           radius=IMG_RADIUS, fill=255)
    im = im.convert("RGBA")
    im.putalpha(mask)
    return im


def make_corner_overlay():
    """이미지 박스 위에 얹어 모서리를 둥글게 보이게 하는 RGBA 오버레이 (Ken Burns 확대 시에도 유지)."""
    x0, y0, x1, y1 = IMG_BOX
    bw, bh = x1 - x0, y1 - y0
    ov = Image.new("RGBA", (bw, bh), BG + (255,))
    hole = Image.new("L", (bw * 4, bh * 4), 0)
    ImageDraw.Draw(hole).rounded_rectangle((0, 0, bw * 4 - 1, bh * 4 - 1),
                                           radius=IMG_RADIUS * 4, fill=255)
    hole = hole.resize((bw, bh), Image.LANCZOS)
    ov.putalpha(hole.point(lambda v: 255 - v))
    return ov


def make_frame(image_path, title1, title2, credit, out_path=None, **kwargs):
    """템플릿 + 이미지 합성 프레임 1장 (1080x1920 RGB)."""
    base = make_template(title1, title2, credit, None, **kwargs)
    im = fit_into_box(image_path)
    base.paste(im, (IMG_BOX[0], IMG_BOX[1]), im)
    if out_path:
        os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
        base.save(out_path)
    return base


if __name__ == "__main__":
    # 간단 테스트: python layout.py 이미지경로
    import sys
    src = sys.argv[1] if len(sys.argv) > 1 else None
    if src:
        make_frame(src, "한국에서 애 키우면", "외국인도 똑같아짐", "@credit",
                   "test_frame.png", channel_name="채널명", handle="@handle")
        print("saved test_frame.png")
