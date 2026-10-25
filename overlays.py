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


def _font(size, bold):
    key = (size, bool(bold))
    if key in _FONTS:
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
        "bold": bool(o.get("bold", True)), "effect": eff, "bg": str(o.get("bg") or ""),
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
    font = _font(o["size"], o["bold"])
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


def _clip(img, cx, cy, start, dur, opacity=None, scale=None, dy=None):
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
        c = c.set_position(lambda t: (cx - w * scale(t) / 2, cy - h * scale(t) / 2 + (dy(t) if dy else 0)))
    else:
        c = c.set_position(lambda t: (cx - w / 2, cy - h / 2 + (dy(t) if dy else 0)))
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


def preview(items, t, background, show_grid=False):
    """시점 t(초)에 보이는 문구를 background(PIL RGB 1080x1920)에 합성한 이미지(정지 화면, 효과는 최종 상태)."""
    bg = background.convert("RGBA")
    for o in clean_list(items):
        if o["start"] <= t < o["start"] + o["dur"]:
            img, cx, cy, _ = render_text(o)
            bg.alpha_composite(img, (int(cx - img.size[0] / 2), int(cy - img.size[1] / 2)))
    out = bg.convert("RGB")
    return grid(out) if show_grid else out
