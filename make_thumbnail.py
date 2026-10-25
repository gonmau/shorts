# -*- coding: utf-8 -*-
"""영상마다 세로(1080x1920) 썸네일 PNG를 thumbnails/<번호_국가>.png 로 만든다.

배경: 장면 이미지(scene_01 우선) 또는 색 그라데이션 / 위: 아바타+채널 / 아래: 큰 제목 2줄 + 나라 이름 띠.
영상 제작(build_video)이 끝난 소재(video_path_v6가 있는 것)가 대상.
"""
import argparse
import os
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageOps

import layout
from layout import W, H, _font, _fit_font, _circle_avatar
from common import load_db, visual_dir, safe_dirname, safe_country

BASE_DIR = Path(__file__).resolve().parent
OUT_DIR = BASE_DIR / "thumbnails"
YELLOW = (255, 226, 0)
GRADS = [((30, 60, 120), (10, 20, 50)), ((120, 30, 90), (40, 10, 40)),
         ((20, 100, 90), (8, 40, 45)), ((130, 70, 20), (50, 25, 10))]


def background(idx, item):
    folder = visual_dir(BASE_DIR, idx, item)
    for p in sorted(folder.glob("scene_*.png")):
        try:
            im = ImageOps.fit(Image.open(p).convert("RGB"), (W, H), Image.LANCZOS, centering=(0.5, 0.4))
            return im
        except Exception:
            continue
    c1, c2 = GRADS[idx % len(GRADS)]
    im = Image.new("RGB", (W, H))
    d = ImageDraw.Draw(im)
    for y in range(H):
        t = y / (H - 1)
        d.line([(0, y), (W, y)], fill=tuple(int(c1[i] * (1 - t) + c2[i] * t) for i in range(3)))
    return im


def shade(im):
    """글자가 잘 보이게 위/아래를 어둡게."""
    over = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(over)
    for y in range(H):
        t = y / (H - 1)
        a = int(150 * max(0, 1 - t / 0.2)) if t < 0.2 else (int(235 * (t - 0.42) / 0.58) if t > 0.42 else 0)
        d.line([(0, y), (W, y)], fill=(0, 0, 0, min(a, 235)))
    return Image.alpha_composite(im.convert("RGBA"), over)


def stroke_text(d, text, cx, y, font, fill, stroke=10):
    w = d.textlength(text, font=font)
    d.text((cx - w / 2, y), text, font=font, fill=fill, stroke_width=stroke, stroke_fill=(0, 0, 0))


def make(idx, item, channel, handle, avatar):
    im = shade(background(idx, item))
    d = ImageDraw.Draw(im)

    # 상단: 아바타 + 채널명
    av = _circle_avatar(110, avatar if Path(avatar).exists() else None, channel[:1])
    im.alpha_composite(av, (50, 60))
    d.text((185, 70), channel, font=_font(46), fill=(255, 255, 255), stroke_width=4, stroke_fill=(0, 0, 0))
    d.text((185, 128), handle, font=_font(34, bold=False), fill=(230, 230, 230), stroke_width=3, stroke_fill=(0, 0, 0))

    # 나라 이름 띠
    country = safe_country(item)
    f = _fit_font(d, country, W - 260, 70, 36)
    tw = d.textlength(country, font=f)
    x0, y0 = (W - tw) / 2 - 40, 1130
    d.rounded_rectangle((x0, y0, x0 + tw + 80, y0 + 120), radius=60, fill=YELLOW)
    d.text(((W - tw) / 2, y0 + 16), country, font=f, fill=(0, 0, 0))

    # 큰 제목 2줄
    t1 = str(item.get("title_line1") or item.get("topic") or country).strip()
    t2 = str(item.get("title_line2") or "").strip()
    f1 = _fit_font(d, t1, W - 100, 150, 70)
    stroke_text(d, t1, W // 2, 1300, f1, (255, 255, 255))
    if t2:
        f2 = _fit_font(d, t2, W - 100, 150, 70)
        stroke_text(d, t2, W // 2, 1300 + int(f1.size * 1.3), f2, YELLOW)
    return im.convert("RGB")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--channel", default="KoreaAtoZ")
    ap.add_argument("--handle", default="@KoreaA2Z")
    ap.add_argument("--avatar", default="avatar.png")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--start", type=int, default=0, help="이 번호 이상 소재의 썸네일만 만듦")
    ap.add_argument("--style", choices=["pop", "classic"], default=os.environ.get("THUMB_STYLE", "pop"),
                    help="pop: 국기+노란 붓터치 나라 이름 / classic: 예전 노란 띠")
    ap.add_argument("--only", default="", help="이 번호들(쉼표)의 썸네일만 만듦. 예: 183,184")
    args = ap.parse_args()

    OUT_DIR.mkdir(exist_ok=True)
    only = {int(x) for x in args.only.replace(" ", "").split(",") if x.isdigit()}
    n = 0
    for idx, item in enumerate(load_db()):
        if idx < args.start or (only and idx not in only):
            continue
        vp = item.get("video_path_v6")
        if not vp or not Path(vp).exists():
            continue
        out = OUT_DIR / f"{Path(vp).stem}.png"
        if out.exists() and not args.force:
            continue
        if args.style == "classic":
            im = make(idx, item, args.channel, args.handle, args.avatar)
        else:
            import thumb_pop
            im = thumb_pop.make(idx, item, args.channel, args.handle, args.avatar, background)
        im.save(out)
        print("썸네일:", out.name)
        n += 1
    print(f"완료: {n}개")


if __name__ == "__main__":
    main()
