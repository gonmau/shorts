# -*- coding: utf-8 -*-
"""롱폼 썸네일(1280x720): 소재 사진 콜라주(기울어진 칸 + 나라 국기) + 가운데 지구본 + 큰 제목(빨간 붓터치 + 흰 글자 + 노란 개수).

make(db, members, title, out_path, IS_EN) -> 저장한 경로. 사진/국기가 없는 칸은 색 칸/국기 없이 만든다."""
import math
import random
import re
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageOps

import textfix  # noqa: F401
import country_codes
from layout import _font, _fit_font
import thumb_pop as TP

TW, TH = 1280, 720
YELLOW = (255, 226, 0)
RED = (226, 24, 36)


def _slots(n):
    """칸 배치 -> [(x0, y0, x1, y1)]  (1줄 또는 2줄, 기울임은 따로)"""
    gap = 8
    if n <= 4:
        rows = [n]
    else:
        top = math.ceil(n / 2)
        rows = [top, n - top]
    rh = TH / len(rows)
    out = []
    for r, k in enumerate(rows):
        cw = TW / k
        for c in range(k):
            out.append((c * cw + gap / 2, r * rh + gap / 2, (c + 1) * cw - gap / 2, (r + 1) * rh - gap / 2))
    return out


def _pick(members, cap=10):
    if len(members) <= cap:
        return list(members)
    step = len(members) / cap
    return [members[int(i * step)] for i in range(cap)]


def _first_photo(B, idx, item):
    try:
        for p in B.get_visual_paths(idx, item):
            if Path(p).exists():
                return Image.open(p).convert("RGB")
    except Exception:
        pass
    return None


def _panel(img, box, skew, color):
    """기울어진 칸에 사진을 넣어 RGBA 로"""
    x0, y0, x1, y1 = [int(v) for v in box]
    w, h = x1 - x0, y1 - y0
    if img is None:
        img = Image.new("RGB", (w, h), color)
    ph = ImageOps.fit(img, (w + skew, h), Image.Resampling.LANCZOS, centering=(0.5, 0.4))
    m = Image.new("L", (w + skew, h), 0)
    ImageDraw.Draw(m).polygon([(skew, 0), (w + skew, 0), (w, h), (0, h)], fill=255)
    out = Image.new("RGBA", (w + skew, h), (0, 0, 0, 0))
    out.paste(ph.convert("RGBA"), (0, 0), m)
    return out, (x0 - skew // 2, y0)


def _globe(r):
    s = r * 2 + 130
    im = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    glow = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse((s // 2 - r - 8, s // 2 - r - 8, s // 2 + r + 8, s // 2 + r + 8), fill=(60, 160, 255, 190))
    im.alpha_composite(glow.filter(ImageFilter.GaussianBlur(14)))
    body = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    bd = ImageDraw.Draw(body)
    c = s // 2
    for i in range(r, 0, -2):     # 안쪽이 밝은 파랑 그라데이션
        t = i / r
        bd.ellipse((c - i, c - i, c + i, c + i), fill=(int(20 + 40 * (1 - t)), int(70 + 90 * (1 - t)), int(190 + 50 * (1 - t)), 255))
    land = Image.new("L", (s, s), 0)
    ld = ImageDraw.Draw(land)
    rnd = random.Random(7)
    for _ in range(9):
        cx, cy = c + rnd.uniform(-r * .6, r * .6), c + rnd.uniform(-r * .55, r * .55)
        for _k in range(5):
            rr = rnd.uniform(r * .08, r * .24)
            ox, oy = rnd.uniform(-r * .2, r * .2), rnd.uniform(-r * .15, r * .15)
            ld.ellipse((cx + ox - rr, cy + oy - rr * .8, cx + ox + rr, cy + oy + rr * .8), fill=255)
    land = land.filter(ImageFilter.GaussianBlur(2)).point(lambda v: 255 if v > 120 else 0)
    green = Image.new("RGBA", (s, s), (92, 190, 110, 235))
    body.paste(green, (0, 0), land)
    for k in (-.5, 0, .5):        # 위도/경도 선
        bd.arc((c - r, c - r * abs(1 - abs(k)) - 1, c + r, c + r * abs(1 - abs(k)) + 1), 0, 360, fill=(255, 255, 255, 60), width=2)
    mask = Image.new("L", (s, s), 0)
    ImageDraw.Draw(mask).ellipse((c - r, c - r, c + r, c + r), fill=255)
    out = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    out.paste(body, (0, 0), mask)
    ImageDraw.Draw(out).ellipse((c - r, c - r, c + r, c + r), outline=(255, 255, 255, 230), width=5)
    im.alpha_composite(out)
    return im


def split_title(title, en):
    """제목 -> (붉은 띠 문구, 큰 흰 글자, 노란 개수)"""
    main = title.split("|")[0].strip()
    m = re.search(r"(\d+)\s*(가지|개)?", main)
    n = m.group(1) if m else ""
    unit = (m.group(2) or "가지") if m else ""
    rest = (main[:m.start()] + " " + main[m.end():]).strip() if m else main
    rest = re.sub(r"\s+", " ", rest)
    words = rest.split()
    if en:
        count = f"{n} FACTS" if n else ""
        rest_w = [w for w in words if w.lower() not in ("facts",)]
        banner = " ".join(rest_w[:2]).upper()
        big = " ".join(rest_w[2:]).upper() or banner
        if big == banner:
            banner = "KOREA A TO Z"
        return banner, big, count
    count = f"{n}{unit}" if n else ""
    if len(words) >= 3:
        banner, big = " ".join(words[:2]), " ".join(words[2:])
    elif len(words) == 2:
        banner, big = words[0], words[1]
    else:
        banner, big = "세계 문화", rest or main
    return banner, big, count


def make(db, members, title, out_path, en=False):
    import build_video as B
    sel = _pick(members)
    base = Image.new("RGBA", (TW, TH), (255, 255, 255, 255))
    slots = _slots(len(sel))
    skew = 46 if len(sel) > 1 else 0
    palette = [(60, 90, 200), (200, 80, 90), (60, 160, 120), (230, 160, 40), (140, 90, 200)]
    for k, (idx, box) in enumerate(zip(sel, slots)):
        item = db[idx]
        img = _first_photo(B, idx, item)
        panel, pos = _panel(img, box, skew, palette[k % len(palette)])
        base.alpha_composite(panel, (max(0, pos[0]) if pos[0] >= 0 else 0, pos[1]))
    # 가운데 어둡게 (글자 잘 보이게)
    vg = Image.new("L", (TW, TH), 0)
    ImageDraw.Draw(vg).ellipse((TW / 2 - 470, TH / 2 - 250, TW / 2 + 470, TH / 2 + 250), fill=140)
    vg = vg.filter(ImageFilter.GaussianBlur(70))
    base.alpha_composite(Image.merge("RGBA", (Image.new("L", (TW, TH), 0),) * 3 + (vg,)))
    # 국기
    d = ImageDraw.Draw(base)
    for k, (idx, box) in enumerate(zip(sel, slots)):
        country = str(db[idx].get("country", "")).strip()
        code = country_codes.country_code(country)
        fl = TP.get_flag(code) if (code and not en) else None
        if fl is not None:
            fb = TP.flag_badge(fl, width=86, angle=-5)
            base.alpha_composite(fb, (int(box[0]) + 2, int(box[1]) - 4))
    # 지구본 + 비행기 점선
    gl = _globe(190)
    base.alpha_composite(gl, (TW // 2 - gl.width // 2, TH // 2 - gl.height // 2 + 6))
    ov = Image.new("RGBA", (TW, TH), (0, 0, 0, 0))
    od = ImageDraw.Draw(ov)
    pts = [(TW // 2 + 140 + t * 4.4, TH // 2 + 170 - math.sin(t / 100 * math.pi) * 70 - t * 1.1) for t in range(0, 101, 4)]
    for i in range(0, len(pts) - 1, 2):
        od.line([pts[i], pts[i + 1]], fill=(255, 255, 255, 235), width=4)
    px, py = pts[-1]
    od.polygon([(px - 26, py + 6), (px + 30, py - 10), (px + 4, py + 10), (px - 10, py + 22)], fill=(255, 255, 255, 255))
    base.alpha_composite(ov)
    # 제목 (세로 가운데 정렬)
    banner, big, count = split_title(title, en)
    d = ImageDraw.Draw(base)
    fb = _fit_font(d, banner, 520, 74, 40)
    bt = TP.italic_text(banner, fb, (255, 255, 255), stroke=4, stroke_fill=(120, 0, 10), shear=0.18)
    bs = TP.brush(bt.width + 90, bt.height + 30, seed=len(banner) * 3 + 5)
    red = Image.new("RGBA", bs.size, RED + (255,))
    red.putalpha(bs.getchannel("A"))
    f1 = _fit_font(d, big, 760, 128, 56)
    f2 = _fit_font(d, count, 600, 150, 60) if count else None
    h1 = int(f1.size * 1.12)
    h2 = int(f2.size * 1.12) if f2 else 0
    total = red.height + 4 + h1 + h2
    by = max(24, (TH - total) // 2 - 10)
    base.alpha_composite(red, ((TW - red.width) // 2, by))
    base.alpha_composite(bt, ((TW - bt.width) // 2, by + (red.height - bt.height) // 2))
    d = ImageDraw.Draw(base)
    y1 = by + red.height + 4
    TP.stroke_text(d, big, TW // 2, y1, f1, (255, 255, 255), stroke=11)
    if count:
        TP.stroke_text(d, count, TW // 2, y1 + h1, f2, YELLOW, stroke=11)
    base.convert("RGB").save(out_path, quality=92)
    return out_path
