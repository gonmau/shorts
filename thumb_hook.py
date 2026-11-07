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


def make(idx, item, channel, handle, avatar, fallback_background):
    im = shade(background(idx, item, fallback_background))
    d = ImageDraw.Draw(im)

    # 상단 채널 표시 (작게)
    av = _circle_avatar(96, avatar if Path(avatar).exists() else None, channel[:1])
    im.alpha_composite(av, (46, 54))
    d.text((165, 62), channel, font=_font(42), fill=(255, 255, 255), stroke_width=4, stroke_fill=(0, 0, 0))
    d.text((165, 114), handle, font=_font(32, bold=False), fill=(230, 230, 230), stroke_width=3, stroke_fill=(0, 0, 0))

    t1 = str(item.get("title_line1") or item.get("topic") or "").strip()
    t2 = str(item.get("title_line2") or "").strip()
    f1 = _fit_font(d, t1, W - 90, 190, 80)
    f2 = _fit_font(d, t2, W - 150, 170, 76) if t2 else None
    gap = 26
    h1 = int(f1.size * 1.18)
    h2 = int(f2.size * 1.5) if f2 else 0
    tag = hook_tag(item)
    tag_h = 100 if tag else 0
    block = tag_h + (30 if tag else 0) + h1 + (gap + h2 if f2 else 0)
    y0 = int(H * 0.60) - block // 2 + 120      # 가운데보다 약간 아래 (피드에서 글자가 잘 보이는 위치)

    y = y0
    if tag:
        ft = _fit_font(d, tag, W - 260, 56, 34)
        tw = d.textlength(tag, font=ft)
        x0 = (W - tw) / 2 - 36
        d.rounded_rectangle((x0, y, x0 + tw + 72, y + tag_h), radius=tag_h // 2, fill=RED, outline=(255, 255, 255), width=5)
        d.text(((W - tw) / 2, y + (tag_h - ft.size) / 2 - 4), tag, font=ft, fill=(255, 255, 255))
        y += tag_h + 30

    TP.stroke_text(d, t1, W // 2, y, f1, (255, 255, 255), stroke=13)
    y += h1 + gap
    if f2:
        w2 = d.textlength(t2, font=f2)
        bs = TP.brush(int(w2) + 90, int(f2.size * 1.25), seed=idx * 11 + len(t2))
        im.alpha_composite(bs, (int((W - bs.width) / 2), y - 22))
        d = ImageDraw.Draw(im)
        d.text(((W - w2) / 2, y + (f2.size * 1.25 - f2.size) / 2 - 18), t2, font=f2, fill=(0, 0, 0))
    return im.convert("RGB")
