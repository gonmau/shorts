# -*- coding: utf-8 -*-
"""'팝' 스타일 썸네일: 위 왼쪽 채널 / 위 오른쪽 국기 / 노란 붓터치 영어 나라 이름 + 빨간 밑줄 / 굵은 제목 2줄(흰색+노랑) + 반짝 선.

국기: flags/<코드>.png 를 우선 쓰고, 없으면 flagcdn.com에서 받아 flags/ 에 저장합니다. 못 받으면 국기 없이 만듭니다.
"""
import math
import random
from pathlib import Path

import requests
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageOps
import textfix  # noqa: F401  (글꼴에 없는 하이픈 등을 네모칸 대신 안전한 글자로)

from layout import W, H, _font, _fit_font, _circle_avatar
from common import safe_country
import country_codes

BASE_DIR = Path(__file__).resolve().parent
FLAG_DIR = BASE_DIR / "flags"
YELLOW = (255, 226, 0)
RED = (235, 20, 20)


def get_flag(code):
    if not code:
        return None
    p = FLAG_DIR / f"{code.lower()}.png"
    if not p.exists():
        try:
            r = requests.get(f"https://flagcdn.com/w640/{code.lower()}.png", timeout=20,
                             headers={"User-Agent": "shorts-thumb/1.0"})
            r.raise_for_status()
            FLAG_DIR.mkdir(exist_ok=True)
            p.write_bytes(r.content)
        except Exception as e:
            print(f"  국기 받기 실패({code}): {type(e).__name__} -> 국기 없이 만듭니다")
            return None
    try:
        return Image.open(p).convert("RGBA")
    except Exception:
        return None


def flag_badge(flag, width=300, angle=-8):
    """둥근 모서리 + 흰 테두리 + 그림자 + 살짝 기울임."""
    h = int(width * flag.height / flag.width)
    fl = flag.resize((width, h), Image.LANCZOS)
    pad = 12
    base = Image.new("RGBA", (width + pad * 2, h + pad * 2), (0, 0, 0, 0))
    m = Image.new("L", base.size, 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, base.width - 1, base.height - 1), radius=18, fill=255)
    white = Image.new("RGBA", base.size, (255, 255, 255, 255))
    base.paste(white, (0, 0), m)
    fm = Image.new("L", fl.size, 0)
    ImageDraw.Draw(fm).rounded_rectangle((0, 0, fl.width - 1, fl.height - 1), radius=10, fill=255)
    base.paste(fl, (pad, pad), fm)
    sh = Image.new("RGBA", (base.width + 60, base.height + 60), (0, 0, 0, 0))
    sm = Image.new("L", sh.size, 0)
    sm.paste(m, (30, 38))
    sm = sm.filter(ImageFilter.GaussianBlur(10)).point(lambda v: int(v * 0.55))
    sh.paste(Image.new("RGBA", sh.size, (0, 0, 0, 255)), (0, 0), sm)
    sh.alpha_composite(base, (30, 30))
    return sh.rotate(angle, resample=Image.BICUBIC, expand=True)


def brush(w, h, seed):
    """노란 붓터치 띠 (양 끝이 거칠게 퍼짐)."""
    rnd = random.Random(seed)
    pad = 40
    im = Image.new("L", (w + pad * 2, h + pad * 2), 0)
    d = ImageDraw.Draw(im)
    pts = []
    n = 26
    for i in range(n + 1):  # 위쪽 가장자리
        x = pad + w * i / n
        pts.append((x, pad + rnd.uniform(-7, 7) + (0 if 0 < i < n else rnd.uniform(6, 16))))
    for i in range(n, -1, -1):  # 아래쪽 가장자리
        x = pad + w * i / n
        pts.append((x, pad + h + rnd.uniform(-7, 7) - (0 if 0 < i < n else rnd.uniform(6, 16))))
    d.polygon(pts, fill=255)
    for side in (0, 1):  # 끝부분 붓털 자국
        for _ in range(7):
            y = pad + rnd.uniform(8, h - 8)
            L = rnd.uniform(20, 55)
            x0 = pad - 8 - L * 0.4 if side == 0 else pad + w + 8 - L * 0.6
            d.line((x0, y, x0 + L, y + rnd.uniform(-3, 3)), fill=255, width=rnd.randint(3, 6))
    im = im.filter(ImageFilter.GaussianBlur(2.2)).point(lambda v: 255 if v > 110 else 0).filter(ImageFilter.GaussianBlur(1.2))
    out = Image.new("RGBA", im.size, YELLOW + (255,))
    out.putalpha(im)
    return out.rotate(-2, resample=Image.BICUBIC, expand=True)


def italic_text(text, font, fill, stroke=0, stroke_fill=(0, 0, 0), shear=0.22):
    tmp = Image.new("RGBA", (int(font.size * len(text) * 0.9) + 80, int(font.size * 1.8)), (0, 0, 0, 0))
    d = ImageDraw.Draw(tmp)
    d.text((40, 20), text, font=font, fill=fill, stroke_width=stroke, stroke_fill=stroke_fill)
    bb = tmp.getbbox() or (0, 0, 1, 1)
    tmp = tmp.crop(bb)
    w, h = tmp.size
    return tmp.transform((w + int(h * shear), h), Image.AFFINE, (1, shear, -h * shear, 0, 1, 0), resample=Image.BICUBIC)


def sparkles(d, cx, cy, flip=False):
    """제목 위 양옆의 반짝 선 3개."""
    s = -1 if flip else 1
    for ang, ln in ((-62, 66), (-25, 62), (14, 52)):
        a = math.radians(ang)
        x0, y0 = cx + s * math.cos(a) * 28, cy + math.sin(a) * 28
        x1, y1 = cx + s * math.cos(a) * (28 + ln), cy + math.sin(a) * (28 + ln)
        d.line((x0, y0, x1, y1), fill=YELLOW, width=12, joint="curve")
        for (px, py) in ((x0, y0), (x1, y1)):
            d.ellipse((px - 6, py - 6, px + 6, py + 6), fill=YELLOW)


def stroke_text(d, text, cx, y, font, fill, stroke=11):
    w = d.textlength(text, font=font)
    d.text((cx - w / 2, y), text, font=font, fill=fill, stroke_width=stroke, stroke_fill=(0, 0, 0))


def light_shade(im):
    """사진을 살리면서 글자 뒤만 살짝 어둡게."""
    over = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(over)
    for y in range(H):
        t = y / (H - 1)
        a = int(90 * max(0, 1 - t / 0.14)) if t < 0.14 else (int(120 * (t - 0.55) / 0.45) if t > 0.55 else 0)
        d.line([(0, y), (W, y)], fill=(0, 0, 0, a))
    return Image.alpha_composite(im.convert("RGBA"), over)


def make(idx, item, channel, handle, avatar, background):
    im = light_shade(background(idx, item))
    d = ImageDraw.Draw(im)
    country = safe_country(item)

    av = _circle_avatar(110, avatar if Path(avatar).exists() else None, channel[:1])
    im.alpha_composite(av, (50, 60))
    d.text((185, 70), channel, font=_font(46), fill=(255, 255, 255), stroke_width=4, stroke_fill=(0, 0, 0))
    d.text((185, 128), handle, font=_font(34, bold=False), fill=(230, 230, 230), stroke_width=3, stroke_fill=(0, 0, 0))

    flag = get_flag(country_codes.country_code(country))
    if flag is not None:
        fb = flag_badge(flag)
        im.alpha_composite(fb, (W - fb.width - 20, 36))

    # 노란 붓터치 + 영어 나라 이름 + 빨간 밑줄
    label = country_codes.english_name(country)
    f = _fit_font(d, label, 520, 130, 60)
    txt = italic_text(label, f, (0, 0, 0))
    bw, bh = txt.width + 150, int(txt.height + 90)
    bw = max(bw, 360)
    bs = brush(bw, bh, seed=idx * 7 + len(label))
    bx, by = (W - bs.width) // 2, 1100
    im.alpha_composite(bs, (bx, by))
    tx, ty = (W - txt.width) // 2, by + (bs.height - txt.height) // 2 - 12
    im.alpha_composite(txt, (tx, ty))
    ul = Image.new("RGBA", im.size, (0, 0, 0, 0))
    ud = ImageDraw.Draw(ul)
    uy = ty + txt.height + 14
    ud.line([(tx + 6, uy + 4), (tx + txt.width * 0.5, uy + 9), (tx + txt.width - 6, uy)], fill=RED, width=11, joint="curve")
    im.alpha_composite(ul)
    d = ImageDraw.Draw(im)

    # 큰 제목 2줄 + 반짝 선
    t1 = str(item.get("title_line1") or item.get("topic") or country).strip()
    t2 = str(item.get("title_line2") or "").strip()
    f1 = _fit_font(d, t1, W - 100, 160, 70)
    y1 = by + bs.height + 20
    stroke_text(d, t1, W // 2, y1, f1, (255, 255, 255))
    if t2:
        f2 = _fit_font(d, t2, W - 100, 160, 70)
        stroke_text(d, t2, W // 2, y1 + int(f1.size * 1.28), f2, YELLOW)
    sparkles(d, 95, y1 - 20)
    sparkles(d, W - 95, y1 - 20, flip=True)
    return im.convert("RGB")
