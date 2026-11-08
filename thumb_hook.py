# -*- coding: utf-8 -*-
"""'후크' 스타일 썸네일: 나라 이름·국기 없이 제목과 후크에 집중.

구성: 위 작은 채널 표시 / 가운데~아래 큰 제목 (1줄 흰색, 2줄 검정 글자+노란 붓터치 띠) / 제목 위 빨간 후크 태그(짧을 때만).
배경은 장면 이미지 중 가장 선명하고 색이 살아 있는 것을 자동 선택합니다 (소재에 thumb_scene=번호 가 있으면 그 장면).
"""
import re
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageOps, ImageStat
import textfix  # noqa: F401

from layout import W, H, _font, _fit_font, _circle_avatar
from common import visual_dir
import thumb_pop as TP

YELLOW = (255, 226, 0)
RED = (235, 20, 20)
BASE_DIR = Path(__file__).resolve().parent


def _score(path):
    """선명도(경계 세기) + 색감 - 너무 어둡거나 밝거나 단색인 이미지는 감점."""
    try:
        im = Image.open(path).convert("RGB")
    except Exception:
        return -1
    im.thumbnail((256, 256))
    g = im.convert("L")
    edges = ImageStat.Stat(g.filter(ImageFilter.FIND_EDGES)).mean[0]
    r, gg, b = im.split()
    rg, yb = ImageChops.difference(r, gg), ImageChops.difference(ImageChops.add(r, gg, 0.5), b)
    color = ImageStat.Stat(rg).mean[0] + ImageStat.Stat(yb).mean[0]
    lum = ImageStat.Stat(g).mean[0]
    contrast = ImageStat.Stat(g).stddev[0]
    s = edges * 1.0 + color * 0.35 + contrast * 0.5
    if lum < 40 or lum > 215:
        s *= 0.5
    if contrast < 18:
        s *= 0.4
    return s


def pick_scene(idx, item):
    folder = visual_dir(BASE_DIR, idx, item)
    files = sorted(folder.glob("scene_*.png"))
    want = item.get("thumb_scene")
    if want:
        p = folder / f"scene_{int(want):02d}.png"
        if p.exists():
            return p
    if not files:
        return None
    return max(files, key=_score)


def background(idx, item, fallback):
    p = pick_scene(idx, item)
    if p is not None:
        try:
            return ImageOps.fit(Image.open(p).convert("RGB"), (W, H), Image.LANCZOS, centering=(0.5, 0.42))
        except Exception:
            pass
    return fallback(idx, item)


def shade(im):
    """사진을 살리고 글자가 놓이는 가운데~아래만 어둡게 + 가장자리 비네팅."""
    over = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(over)
    for y in range(H):
        t = y / (H - 1)
        a = int(110 * max(0, 1 - t / 0.13)) if t < 0.13 else 0
        if t > 0.45:
            a = int(215 * min(1.0, (t - 0.45) / 0.35))
        d.line([(0, y), (W, y)], fill=(0, 0, 0, a))
    return Image.alpha_composite(im.convert("RGBA"), over)


def hook_tag(item):
    """후크의 첫 문장을 짧게 (20자 이하일 때만 태그로 사용)."""
    h = str(item.get("hook") or "").strip()
    if not h:
        return ""
    first = re.split(r"(?<=[.!?])\s+", h)[0].strip().rstrip(".")
    lim = 22 if re.search(r"[가-힣]", first) else 40   # 영어는 글자 수가 더 많아도 한 줄에 들어감
    return first if 4 <= len(first) <= lim else ""


def _hex(c, default):
    try:
        c = str(c).lstrip("#")
        return tuple(int(c[k:k + 2], 16) for k in (0, 2, 4))
    except Exception:
        return default


def _words_width(d, words, font):
    sp = d.textlength(" ", font=font)
    return sum(d.textlength(w, font=font) for w in words) + sp * max(0, len(words) - 1), sp


def draw_words(d, text, font, cx, y, colors, default, stroke=0, stroke_fill=(0, 0, 0)):
    """단어별 색상으로 가운데 정렬해 그림. colors = {단어 순번(문자열): '#rrggbb'}"""
    words = text.split()
    tw, sp = _words_width(d, words, font)
    x = cx - tw / 2
    for k, w in enumerate(words):
        col = _hex(colors.get(str(k)), default) if colors.get(str(k)) else default
        d.text((x, y), w, font=font, fill=col, stroke_width=stroke, stroke_fill=stroke_fill)
        x += d.textlength(w, font=font) + sp


def band_image(kind, w, h, color, seed, opacity=100, angle=-2.0):
    """2줄 뒤 띠. kind: brush(붓터치) / rect(사각) / round(둥근 알약) / skew(비스듬한 평행사변형)"""
    if kind == "brush":
        b = TP.brush(w, h, seed)
        a = b.getchannel("A")
        out = Image.new("RGBA", b.size, color + (255,))
        out.putalpha(a)
        out = out.rotate(angle + 2, resample=Image.BICUBIC, expand=True) if angle + 2 else out   # brush() 안에서 이미 -2° 회전
    else:
        pad = 40
        sc = 3                                                     # 가장자리를 매끈하게 3배로 그려 줄임
        im = Image.new("L", ((w + pad * 2) * sc, (h + pad * 2) * sc), 0)
        d = ImageDraw.Draw(im)
        x0, y0, x1, y1 = pad * sc, pad * sc, (pad + w) * sc, (pad + h) * sc
        if kind == "round":
            d.rounded_rectangle((x0, y0, x1, y1), radius=(y1 - y0) // 2, fill=255)
        elif kind == "skew":
            k = int(h * 0.28) * sc
            d.polygon([(x0 + k, y0), (x1 + k, y0), (x1 - k, y1), (x0 - k, y1)], fill=255)
        else:
            d.rectangle((x0, y0, x1, y1), fill=255)
        im = im.resize((w + pad * 2, h + pad * 2), Image.LANCZOS)
        out = Image.new("RGBA", im.size, color + (255,))
        out.putalpha(im)
        if angle:
            out = out.rotate(angle, resample=Image.BICUBIC, expand=True)
    if opacity < 100:
        out.putalpha(out.getchannel("A").point(lambda v: int(v * opacity / 100)))
    return out


def make(idx, item, channel, handle, avatar, fallback_background):
    """item['thumb_opts'] = {scale1, scale2 (글씨 크기 배율), angle (기울기°), dy (세로 이동 px),
    colors1, colors2 ({단어 순번: 색}), tag (후크 태그 on/off)}"""
    o = item.get("thumb_opts") or {}
    im = shade(background(idx, item, fallback_background))
    d = ImageDraw.Draw(im)

    # 상단 채널 표시 (작게)
    av = _circle_avatar(96, avatar if Path(avatar).exists() else None, channel[:1])
    im.alpha_composite(av, (46, 54))
    d.text((165, 62), channel, font=_font(42), fill=(255, 255, 255), stroke_width=4, stroke_fill=(0, 0, 0))
    d.text((165, 114), handle, font=_font(32, bold=False), fill=(230, 230, 230), stroke_width=3, stroke_fill=(0, 0, 0))

    t1 = str(item.get("title_line1") or item.get("topic") or "").strip()
    t2 = str(item.get("title_line2") or "").strip()
    import fonts as _F
    fp = _F.path(o.get("font")) or _F.role_path("thumb")
    s1, s2 = float(o.get("scale1", 1.0) or 1.0), float(o.get("scale2", 1.0) or 1.0)
    f1 = _font(max(20, int(_fit_font(d, t1, W - 60, 240, 80, font_path=fp).size * s1)), True, fp)
    f2 = _font(max(20, int(_fit_font(d, t2, W - 110, 220, 76, font_path=fp).size * s2)), True, fp) if t2 else None
    gap = 26
    h1 = int(f1.size * 1.18)
    h2 = int(f2.size * 1.5) if f2 else 0
    tag = hook_tag(item) if o.get("tag", True) else ""
    tag_h = 100 if tag else 0
    block = tag_h + (30 if tag else 0) + h1 + (gap + h2 if f2 else 0)
    y0 = int(H * 0.60) - block // 2 + 120 + int(o.get("dy", 0))

    lay = Image.new("RGBA", (W, H), (0, 0, 0, 0))     # 글자 덩어리를 따로 그려 한꺼번에 기울임
    ld = ImageDraw.Draw(lay)
    y = y0
    if tag:
        ft = _fit_font(ld, tag, W - 260, 56, 34)
        tw = ld.textlength(tag, font=ft)
        x0 = (W - tw) / 2 - 36
        ld.rounded_rectangle((x0, y, x0 + tw + 72, y + tag_h), radius=tag_h // 2, fill=RED, outline=(255, 255, 255), width=5)
        ld.text(((W - tw) / 2, y + (tag_h - ft.size) / 2 - 4), tag, font=ft, fill=(255, 255, 255))
        y += tag_h + 30

    draw_words(ld, t1, f1, W // 2, y, o.get("colors1") or {}, _hex(o.get("color1"), (255, 255, 255)) if o.get("color1") else (255, 255, 255), stroke=13)
    y += h1 + gap
    if f2:
        w2 = _words_width(ld, t2.split(), f2)[0]
        kind = o.get("band", "brush")
        if kind != "none":
            bw = max(60, int(w2) + int(o.get("band_w", 90)))
            bh = max(30, int(f2.size * 1.25 * float(o.get("band_h", 1.0))))
            bs = band_image(kind, bw, bh, _hex(o.get("band_color"), YELLOW) if o.get("band_color") else YELLOW,
                            idx * 11 + len(t2), int(o.get("band_opacity", 100)), float(o.get("band_angle", -2.0)))
            cy = y + 0.625 * f2.size + 18 + int(o.get("band_dy", 0))     # 띠 중심 (높이·기울기를 바꿔도 글자 중심은 그대로)
            lay.alpha_composite(bs, (int((W - bs.width) / 2), int(cy - bs.height / 2)))
        ld = ImageDraw.Draw(lay)
        draw_words(ld, t2, f2, W // 2, y + (f2.size * 1.25 - f2.size) / 2 - 18, o.get("colors2") or {},
                   _hex(o.get("color2"), (0, 0, 0)) if o.get("color2") else (0, 0, 0))
    ang = float(o.get("angle", 0) or 0)
    if ang:
        lay = lay.rotate(ang, resample=Image.BICUBIC, center=(W // 2, y0 + block // 2))
    im.alpha_composite(lay)
    return im.convert("RGB")
