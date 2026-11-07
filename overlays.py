# -*- coding: utf-8 -*-
"""영상 특정 시점에 넣는 문구(오버레이). facts_db.json 소재의 "overlays" 목록으로 저장합니다.

항목 하나(dict) 예:
  {"text": "놀라운 사실!", "start": 3.0, "dur": 2.5, "pos": "중앙", "x": 50, "y": 50,
   "size": 80, "color": "#FFFFFF", "stroke": "#000000", "bold": true, "effect": "팝", "bg": ""}

x, y : 문구 중심의 화면 가로·세로 위치(%). 0~100, 어디든 자유롭게 (50,50 = 정중앙). 화면은 1080x1920, 이미지 영역은 y 23%~76%
effect : 없음 / 페이드 / 슬라이드업 / 팝 / 타자기 / 깜빡임
"""
import os

import numpy as np
from PIL import Image, ImageDraw, ImageFont
import textfix  # noqa: F401  (글꼴에 없는 하이픈 등을 네모칸 대신 안전한 글자로)

W, H = 1080, 1920
PRESET_Y = {"화면맨위": 240, "상단": 560, "중앙": 950, "하단": 1120, "화면맨아래": 1700}   # 문구 중심 y(px)
POSITIONS = ["화면맨위", "상단", "중앙", "하단", "화면맨아래", "직접"]
EFFECTS = ["없음", "페이드", "슬라이드업", "팝", "타자기", "깜빡임"]
MAX_W = W - 120
MAX_OVERLAYS = 30

_FONTS = {}


def _font(size, bold, fid=""):
    import fonts as _F
    fp = _F.path(fid) if fid else _F.role_path("ovl")
    key = (size, bool(bold), fp)
    if key in _FONTS:
        return _FONTS[key]
    if fp:
        _FONTS[key] = ImageFont.truetype(fp, size)
        return _FONTS[key]
    if bold:
        cands = [r"C:\Windows\Fonts\malgunbd.ttf", r"C:\Windows\Fonts\NanumGothicBold.ttf",
                 "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc", "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc"]
    else:
        cands = [r"C:\Windows\Fonts\malgun.ttf", r"C:\Windows\Fonts\NanumGothic.ttf",
                 "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc"]
    f = None
    for p in cands:
        if os.path.exists(p):
            f = ImageFont.truetype(p, size)
            break
    _FONTS[key] = f or ImageFont.load_default()
    return _FONTS[key]


def _rgb(c, default=(255, 255, 255)):
    c = str(c or "").strip().lstrip("#")
    if len(c) == 3:
        c = "".join(ch * 2 for ch in c)
    try:
        return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4)) if len(c) == 6 else default
    except ValueError:
        return default


def _num(v, default, lo=None, hi=None):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return default
    if lo is not None:
        x = max(lo, x)
    if hi is not None:
        x = min(hi, x)
    return x


def normalize(o):
    """표에서 들어온 값을 안전한 형태로 정리. 문구가 비어 있으면 None."""
    text = str(o.get("text") or "").strip()
    if not text:
        return None
    # 위치는 x, y(화면 가로·세로 %, 문구 중심 기준)가 항상 우선. 예전 프리셋(pos)만 있고 y가 없으면 프리셋 높이로 환산
    y = o.get("y")
    if (y is None or y == "" or y != y) and o.get("pos") in PRESET_Y:
        y = PRESET_Y[o["pos"]] * 100.0 / H
    pos = "직접"
    eff = o.get("effect") if o.get("effect") in EFFECTS else "없음"
    return {
        "text": text, "start": _num(o.get("start"), 0.0, 0, 600), "dur": _num(o.get("dur"), 2.0, 0.2, 600),
        "pos": pos, "x": _num(o.get("x"), 50, 0, 100), "y": _num(y, 50, 0, 100),
        "size": int(_num(o.get("size"), 80, 20, 220)), "color": str(o.get("color") or "#FFFFFF"),
        "stroke": str(o.get("stroke") if o.get("stroke") is not None else "#000000"),
        "bold": bool(o.get("bold", True)), "font": str(o.get("font") or ""), "effect": eff, "bg": str(o.get("bg") or ""),
    }


def clean_list(items):
    out = []
    for o in (items or [])[:MAX_OVERLAYS]:
        n = normalize(o or {})
        if n:
            out.append(n)
    return out


def _wrap(draw, text, font, max_w):
    lines = []
    for para in str(text).split("\n"):
        cur = ""
        for ch in para:
            t = cur + ch
            if cur and draw.textlength(t, font=font) > max_w:
                # 공백에서 끊을 수 있으면 단어 단위로
                sp = cur.rfind(" ")
                if sp > 0 and ch != " ":
                    lines.append(cur[:sp])
                    cur = cur[sp + 1:] + ch
                else:
                    lines.append(cur)
                    cur = ch.lstrip() if ch == " " else ch
            else:
                cur = t
        lines.append(cur)
    return [l for l in lines if l is not None]


def render_text(o, reveal=None):
    """문구 이미지(RGBA)와 중심 좌표(px)를 돌려준다. reveal=글자 수면 앞에서 그만큼만 보이게(레이아웃은 전체 기준)."""
    font = _font(o["size"], o["bold"], o.get("font", ""))
    tmp = ImageDraw.Draw(Image.new("RGB", (4, 4)))
    lines = _wrap(tmp, o["text"], font, MAX_W)
    asc, desc = font.getmetrics()
    lh = asc + desc + max(4, o["size"] // 8)
    sw = max(0, min(14, o["size"] // 10)) if o["stroke"].strip() else 0
    pad = 14 + sw
    tw = int(max(tmp.textlength(l, font=font) for l in lines)) + 2 * pad
    th = lh * len(lines) + 2 * pad
    img = Image.new("RGBA", (tw, th), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if o["bg"].strip():
        d.rounded_rectangle((0, 0, tw - 1, th - 1), radius=18, fill=_rgb(o["bg"], (0, 0, 0)) + (170,))
    col, scol = _rgb(o["color"]), _rgb(o["stroke"], (0, 0, 0))
    shown = 0
    for i, line in enumerate(lines):
        if reveal is not None:
            take = max(0, min(len(line), reveal - shown))
            shown += len(line)
            txt = line[:take]
            if not txt:
                continue
        else:
            txt = line
        x = (tw - tmp.textlength(line, font=font)) / 2   # 줄 가운데 정렬 (레이아웃은 전체 줄 기준)
        kw = {"stroke_width": sw, "stroke_fill": scol} if sw else {}
        d.text((x, pad + i * lh), txt, font=font, fill=col, **kw)
    cx = W * o["x"] / 100.0
    cy = H * o["y"] / 100.0
    cx = min(max(cx, tw / 2), W - tw / 2)
    cy = min(max(cy, th / 2), H - th / 2)
    return img, cx, cy, sum(len(l) for l in lines)


def _clip(img, cx, cy, start, dur, opacity=None, scale=None, dy=None, dx=None):
    from moviepy.editor import ImageClip
    arr = np.array(img)
    rgb, alpha = arr[:, :, :3], arr[:, :, 3].astype(float) / 255.0
    c = ImageClip(rgb).set_duration(dur)
    mask = ImageClip(alpha, ismask=True).set_duration(dur)
    if opacity is not None:
        mask = mask.fl(lambda gf, t: gf(t) * opacity(t))
    c = c.set_mask(mask)
    w, h = img.size
    if scale is not None:
        c = c.resize(scale)
        c = c.set_position(lambda t: (cx - w * scale(t) / 2 + (dx(t) if dx else 0), cy - h * scale(t) / 2 + (dy(t) if dy else 0)))
    else:
        c = c.set_position(lambda t: (cx - w / 2 + (dx(t) if dx else 0), cy - h / 2 + (dy(t) if dy else 0)))
    return c.set_start(start)


def _ease(p):
    p = min(max(p, 0.0), 1.0)
    return 1 - (1 - p) ** 3


def make_clips(items, audio_duration):
    """moviepy 클립 목록. 음성 길이를 넘는 부분은 잘라낸다."""
    clips = []
    for o in clean_list(items):
        start = min(o["start"], max(0.0, audio_duration - 0.3))
        dur = max(0.2, min(o["dur"], audio_duration - start))
        eff = o["effect"]
        img, cx, cy, n_chars = render_text(o)
        fade = min(0.35, dur / 3)
        if eff == "없음":
            clips.append(_clip(img, cx, cy, start, dur))
        elif eff == "페이드":
            clips.append(_clip(img, cx, cy, start, dur,
                               opacity=lambda t, d=dur, f=fade: min(1.0, t / f, max(0.0, (d - t) / f))))
        elif eff == "슬라이드업":
            clips.append(_clip(img, cx, cy, start, dur,
                               opacity=lambda t, d=dur, f=fade: min(1.0, t / f, max(0.0, (d - t) / f)),
                               dy=lambda t: 70 * (1 - _ease(t / 0.45))))
        elif eff == "팝":
            def sc(t):
                if t < 0.18:
                    return 0.5 + 0.7 * _ease(t / 0.18)       # 0.5 -> 1.2
                if t < 0.36:
                    return 1.2 - 0.2 * _ease((t - 0.18) / 0.18)  # 1.2 -> 1.0
                return 1.0
            clips.append(_clip(img, cx, cy, start, dur, scale=sc,
                               opacity=lambda t, d=dur, f=fade: min(1.0, t / 0.12, max(0.0, (d - t) / f))))
        elif eff == "타자기":
            per = min(0.07, max(0.02, dur * 0.6 / max(1, n_chars)))
            steps = min(n_chars, 60)
            step_chars = max(1, -(-n_chars // steps))
            t = 0.0
            k = step_chars
            while k < n_chars and t < dur - 0.2:
                im_k, _, _, _ = render_text(o, reveal=k)
                clips.append(_clip(im_k, cx, cy, start + t, per * step_chars))
                t += per * step_chars
                k += step_chars
            clips.append(_clip(img, cx, cy, start + t, max(0.2, dur - t)))
        elif eff == "깜빡임":
            clips.append(_clip(img, cx, cy, start, dur,
                               opacity=lambda t: 1.0 if int(t / 0.35) % 2 == 0 else 0.0))
    return clips



# ---------------- 이미지 얹기 (근거 사진·캡처를 배경 장면 위에 추가) ----------------
IMG_EFFECTS = ["없음", "페이드", "슬라이드업", "슬라이드왼쪽", "슬라이드오른쪽", "팝", "줌인", "흔들림", "깜빡임"]
MAX_IMAGES = 20


def normalize_image(o):
    """이미지 얹기 항목 정리. 파일이 없으면 None.
    {"image": "overlay_images/12_1.png", "start": 3, "dur": 3, "x": 50, "y": 45, "width": 60(화면 가로 %),
     "opacity": 1.0, "rotate": 0, "border": "#FFFFFF", "bw": 6, "radius": 24, "shadow": true, "effect": "팝"}"""
    path = str(o.get("image") or "").strip()
    if not path:
        return None
    return {
        "image": path, "start": _num(o.get("start"), 0.0, 0, 600), "dur": _num(o.get("dur"), 3.0, 0.2, 600),
        "x": _num(o.get("x"), 50, 0, 100), "y": _num(o.get("y"), 45, 0, 100),
        "width": _num(o.get("width"), 60, 5, 100), "opacity": _num(o.get("opacity"), 1.0, 0.1, 1.0),
        "rotate": _num(o.get("rotate"), 0, -45, 45), "border": str(o.get("border") or ""),
        "bw": int(_num(o.get("bw"), 6, 0, 30)), "radius": int(_num(o.get("radius"), 24, 0, 200)),
        "shadow": bool(o.get("shadow", True)), "effect": o.get("effect") if o.get("effect") in IMG_EFFECTS else "없음",
        "crop_l": _num(o.get("crop_l"), 0, 0, 80), "crop_t": _num(o.get("crop_t"), 0, 0, 80),
        "crop_r": _num(o.get("crop_r"), 0, 0, 80), "crop_b": _num(o.get("crop_b"), 0, 0, 80),
    }


def clean_images(items):
    out = []
    for o in (items or [])[:MAX_IMAGES]:
        n = normalize_image(o or {})
        if n:
            out.append(n)
    return out


def render_image(o):
    """얹을 이미지(RGBA: 둥근 모서리·테두리·그림자·회전 적용)와 중심 좌표(px). 파일이 없으면 None."""
    from PIL import ImageFilter
    if not os.path.exists(o["image"]):
        return None
    src = Image.open(o["image"]).convert("RGBA")
    cl, ct, cr, cb = (o.get("crop_l", 0), o.get("crop_t", 0), o.get("crop_r", 0), o.get("crop_b", 0))
    if cl or ct or cr or cb:                      # 가장자리를 % 만큼 잘라냄 (일부만 확대해서 보여줄 때)
        box = (int(src.width * cl / 100), int(src.height * ct / 100), int(src.width * (100 - cr) / 100), int(src.height * (100 - cb) / 100))
        if box[2] - box[0] >= 8 and box[3] - box[1] >= 8:
            src = src.crop(box)
    tw = int(W * o["width"] / 100.0)
    th = int(src.height * tw / src.width)
    if th > int(H * 0.8):                       # 너무 길쭉하면 높이 기준으로 줄임
        th = int(H * 0.8)
        tw = int(src.width * th / src.height)
    src = src.resize((max(8, tw), max(8, th)), Image.LANCZOS)
    r = min(o["radius"], min(src.size) // 2)
    mask = Image.new("L", src.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, src.width - 1, src.height - 1), radius=r, fill=255)
    src.putalpha(Image.composite(src.getchannel("A"), Image.new("L", src.size, 0), mask))
    bw = o["bw"] if o["border"].strip() else 0
    pad = 30 if o["shadow"] else 0
    card = Image.new("RGBA", (src.width + 2 * bw + 2 * pad, src.height + 2 * bw + 2 * pad), (0, 0, 0, 0))
    if o["shadow"]:
        sh = Image.new("RGBA", card.size, (0, 0, 0, 0))
        ImageDraw.Draw(sh).rounded_rectangle((pad + 6, pad + 10, pad + src.width + 2 * bw + 6, pad + src.height + 2 * bw + 10),
                                              radius=r + bw, fill=(0, 0, 0, 150))
        card.alpha_composite(sh.filter(ImageFilter.GaussianBlur(14)))
    if bw:
        ImageDraw.Draw(card).rounded_rectangle((pad, pad, pad + src.width + 2 * bw - 1, pad + src.height + 2 * bw - 1),
                                                radius=r + bw, fill=_rgb(o["border"]) + (255,))
    card.alpha_composite(src, (pad + bw, pad + bw))
    if abs(o["rotate"]) > 0.1:
        card = card.rotate(o["rotate"], resample=Image.BICUBIC, expand=True)
    if o["opacity"] < 0.999:
        a = card.getchannel("A").point(lambda v: int(v * o["opacity"]))
        card.putalpha(a)
    cx = min(max(W * o["x"] / 100.0, card.width / 2), W - card.width / 2)
    cy = min(max(H * o["y"] / 100.0, card.height / 2), H - card.height / 2)
    return card, cx, cy


def make_image_clips(items, audio_duration):
    clips = []
    for o in clean_images(items):
        r = render_image(o)
        if r is None:
            print(f"  이미지 얹기: 파일 없음 - 건너뜀 ({o['image']})")
            continue
        img, cx, cy = r
        start = min(o["start"], max(0.0, audio_duration - 0.3))
        dur = max(0.2, min(o["dur"], audio_duration - start))
        eff = o["effect"]
        fade = min(0.35, dur / 3)
        fio = lambda t, d=dur, f=fade: min(1.0, t / f, max(0.0, (d - t) / f))
        if eff == "없음":
            clips.append(_clip(img, cx, cy, start, dur))
        elif eff == "페이드":
            clips.append(_clip(img, cx, cy, start, dur, opacity=fio))
        elif eff == "슬라이드업":
            clips.append(_clip(img, cx, cy, start, dur, opacity=fio, dy=lambda t: 90 * (1 - _ease(t / 0.45))))
        elif eff == "슬라이드왼쪽":      # 왼쪽에서 들어옴
            clips.append(_clip(img, cx, cy, start, dur, opacity=fio, dx=lambda t: -420 * (1 - _ease(t / 0.5))))
        elif eff == "슬라이드오른쪽":
            clips.append(_clip(img, cx, cy, start, dur, opacity=fio, dx=lambda t: 420 * (1 - _ease(t / 0.5))))
        elif eff == "팝":
            def sc(t):
                if t < 0.18:
                    return 0.5 + 0.7 * _ease(t / 0.18)
                if t < 0.36:
                    return 1.2 - 0.2 * _ease((t - 0.18) / 0.18)
                return 1.0
            clips.append(_clip(img, cx, cy, start, dur, scale=sc,
                               opacity=lambda t, d=dur, f=fade: min(1.0, t / 0.12, max(0.0, (d - t) / f))))
        elif eff == "줌인":               # 천천히 커짐 (강조)
            clips.append(_clip(img, cx, cy, start, dur, scale=lambda t, d=dur: 1.0 + 0.12 * min(1.0, t / d), opacity=fio))
        elif eff == "흔들림":             # 들어오면서 좌우로 흔들림
            clips.append(_clip(img, cx, cy, start, dur, opacity=lambda t, d=dur, f=fade: min(1.0, t / 0.12, max(0.0, (d - t) / f)),
                               dx=lambda t: 16 * np.sin(t * 38) * max(0.0, 1 - t / 0.8)))
        elif eff == "깜빡임":
            clips.append(_clip(img, cx, cy, start, dur, opacity=lambda t: 1.0 if int(t / 0.35) % 2 == 0 else 0.0))
    return clips



# ---------------- 도형 강조 (원 · 사각형 · 화살표) ----------------
SHAPES = ["원", "사각형", "화살표"]
SHAPE_EFFECTS = ["없음", "그리기", "페이드", "팝", "맥박", "깜빡임"]
MAX_SHAPES = 20


def normalize_shape(o):
    """{"type":"원","start":2,"dur":3,"x":50,"y":45,"w":30(화면 가로 %),"h":12(화면 세로 %),"angle":0(화살표 방향, 0=→ 90=↓),
        "color":"#FF3B30","thick":10,"effect":"그리기"}   화살표는 w가 길이."""
    typ = o.get("type") if o.get("type") in SHAPES else None
    if typ is None:
        return None
    return {
        "type": typ, "start": _num(o.get("start"), 0.0, 0, 600), "dur": _num(o.get("dur"), 3.0, 0.2, 600),
        "x": _num(o.get("x"), 50, 0, 100), "y": _num(o.get("y"), 45, 0, 100),
        "w": _num(o.get("w"), 30, 3, 100), "h": _num(o.get("h"), 12, 2, 100), "angle": _num(o.get("angle"), 0, -360, 360),
        "color": str(o.get("color") or "#FF3B30"), "thick": int(_num(o.get("thick"), 10, 2, 40)),
        "effect": o.get("effect") if o.get("effect") in SHAPE_EFFECTS else "없음",
    }


def clean_shapes(items):
    out = []
    for o in (items or [])[:MAX_SHAPES]:
        n = normalize_shape(o or {})
        if n:
            out.append(n)
    return out


def render_shape(o, p=1.0):
    """도형 이미지(RGBA)와 중심 좌표(px). p=0~1 이면 그 비율만큼만 그린 모습('그리기' 효과용)."""
    S = 2                                           # 2배로 그려 줄여서 가장자리를 부드럽게
    th = o["thick"] * S
    col = _rgb(o["color"], (255, 59, 48)) + (255,)
    typ = o["type"]
    if typ == "화살표":
        L = int(W * o["w"] / 100.0) * S
        head = max(34 * S, th * 4)
        cw, chh = L + 2 * S * 4, head * 2 + 2 * S * 4
        img = Image.new("RGBA", (cw, chh), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        my = chh // 2
        x0 = 4 * S
        shaft_end = x0 + (L - head * 0.8) * min(1.0, p / 0.85)
        d.line((x0, my, shaft_end, my), fill=col, width=th)
        if p >= 0.85:
            tip = x0 + L
            d.polygon([(tip, my), (tip - head, my - head * 0.62), (tip - head, my + head * 0.62)], fill=col)
    else:
        ww, hh = int(W * o["w"] / 100.0) * S, int(H * o["h"] / 100.0) * S
        pad = th + 4 * S
        img = Image.new("RGBA", (ww + 2 * pad, hh + 2 * pad), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        box = (pad, pad, pad + ww, pad + hh)
        if typ == "원":
            if p >= 0.999:
                d.ellipse(box, outline=col, width=th)
            elif p > 0:
                d.arc(box, start=-90, end=-90 + 360 * p, fill=col, width=th)
        else:
            if p >= 0.999:
                d.rounded_rectangle(box, radius=min(24 * S, hh // 4), outline=col, width=th)
            elif p > 0:
                pts = [(box[0], box[1]), (box[2], box[1]), (box[2], box[3]), (box[0], box[3]), (box[0], box[1])]
                segs = [(pts[i], pts[i + 1], abs(pts[i + 1][0] - pts[i][0]) + abs(pts[i + 1][1] - pts[i][1])) for i in range(4)]
                left = p * sum(sg[2] for sg in segs)
                for (a_, b_, ln) in segs:
                    if left <= 0:
                        break
                    f = min(1.0, left / ln)
                    d.line((a_[0], a_[1], a_[0] + (b_[0] - a_[0]) * f, a_[1] + (b_[1] - a_[1]) * f), fill=col, width=th)
                    left -= ln
    img = img.resize((max(4, img.width // S), max(4, img.height // S)), Image.LANCZOS)
    if typ == "화살표" and abs(o["angle"]) > 0.1:
        img = img.rotate(-o["angle"], resample=Image.BICUBIC, expand=True)   # 화면 기준 시계 방향
    cx = min(max(W * o["x"] / 100.0, img.width / 2), W - img.width / 2)
    cy = min(max(H * o["y"] / 100.0, img.height / 2), H - img.height / 2)
    return img, cx, cy


def make_shape_clips(items, audio_duration):
    clips = []
    for o in clean_shapes(items):
        img, cx, cy = render_shape(o)
        start = min(o["start"], max(0.0, audio_duration - 0.3))
        dur = max(0.2, min(o["dur"], audio_duration - start))
        eff = o["effect"]
        fade = min(0.3, dur / 3)
        if eff == "없음":
            clips.append(_clip(img, cx, cy, start, dur))
        elif eff == "그리기":
            dd = min(0.7, dur * 0.6)
            n = 12
            for k in range(1, n):
                im_k, cx_k, cy_k = render_shape(o, k / n)
                clips.append(_clip(im_k, cx, cy, start + (k - 1) * dd / n, dd / n))   # 중심은 완성본 기준으로 고정
            clips.append(_clip(img, cx, cy, start + (n - 1) * dd / n, max(0.2, dur - (n - 1) * dd / n)))
        elif eff == "페이드":
            clips.append(_clip(img, cx, cy, start, dur, opacity=lambda t, d=dur, f=fade: min(1.0, t / f, max(0.0, (d - t) / f))))
        elif eff == "팝":
            def sc(t):
                if t < 0.18:
                    return 0.4 + 0.8 * _ease(t / 0.18)
                if t < 0.36:
                    return 1.2 - 0.2 * _ease((t - 0.18) / 0.18)
                return 1.0
            clips.append(_clip(img, cx, cy, start, dur, scale=sc))
        elif eff == "맥박":                 # 커졌다 작아졌다 반복 (계속 주목시킴)
            clips.append(_clip(img, cx, cy, start, dur, scale=lambda t: 1.0 + 0.08 * np.sin(t * 2 * np.pi / 0.8)))
        elif eff == "깜빡임":
            clips.append(_clip(img, cx, cy, start, dur, opacity=lambda t: 1.0 if int(t / 0.35) % 2 == 0 else 0.0))
    return clips


def render_preview_video(text_items, image_items, shape_items, background, t0, t1, out_path, fps=15):
    """[t0,t1]초 구간만 짧은 mp4로 만들어 효과(움직임)를 확인한다. 배경은 정지 화면, 자막·음성은 없음. 해상도 절반."""
    from moviepy.editor import CompositeVideoClip, ImageClip
    total = max(t1 + 0.5, 1.0)
    base = ImageClip(np.array(background.convert("RGB"))).set_duration(total)
    clips = [base] + make_image_clips(image_items, total) + make_shape_clips(shape_items, total) + make_clips(text_items, total)
    comp = CompositeVideoClip(clips, size=(W, H)).set_duration(total).subclip(t0, min(t1, total))
    comp.resize(0.5).write_videofile(str(out_path), fps=fps, codec="libx264", audio=False, preset="ultrafast", logger=None)
    comp.close()


def grid(img, step=10):
    """미리보기용 격자(10% 간격)와 이미지 영역 테두리, 좌표 숫자를 그린다."""
    im = img.convert("RGBA")
    ov = Image.new("RGBA", im.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    f = _font(26, False)
    for k in range(0, 101, step):
        x, y = int(W * k / 100), int(H * k / 100)
        d.line((x, 0, x, H), fill=(255, 255, 255, 90), width=2)
        d.line((0, y, W, y), fill=(255, 255, 255, 90), width=2)
        d.text((x + 4, 4), str(k), font=f, fill=(255, 255, 0, 230))
        d.text((4, y + 2), str(k), font=f, fill=(0, 255, 255, 230))
    return Image.alpha_composite(im, ov).convert("RGB")


def preview(items, t, background, show_grid=False, images=None, shapes=None):
    """시점 t(초)에 보이는 문구를 background(PIL RGB 1080x1920)에 합성한 이미지(정지 화면, 효과는 최종 상태)."""
    bg = background.convert("RGBA")
    for o in clean_images(images):
        if o["start"] <= t < o["start"] + o["dur"]:
            r = render_image(o)
            if r:
                card, cx, cy = r
                bg.alpha_composite(card, (int(cx - card.size[0] / 2), int(cy - card.size[1] / 2)))
    for o in clean_shapes(shapes):
        if o["start"] <= t < o["start"] + o["dur"]:
            card, cx, cy = render_shape(o)
            bg.alpha_composite(card, (int(cx - card.size[0] / 2), int(cy - card.size[1] / 2)))
    for o in clean_list(items):
        if o["start"] <= t < o["start"] + o["dur"]:
            img, cx, cy, _ = render_text(o)
            bg.alpha_composite(img, (int(cx - img.size[0] / 2), int(cy - img.size[1] / 2)))
    out = bg.convert("RGB")
    return grid(out) if show_grid else out
