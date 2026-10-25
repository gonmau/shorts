# -*- coding: utf-8 -*-
"""대본 자막: 음성 속도에 맞춰 문장을 알맞은 길이로 나눠 보여준다.

- 글자 크기는 일정(너무 크지도 작지도 않게). 한 화면은 최대 2줄이라 잘리지 않는다. 긴 문장은 여러 장으로 나눈다.
- 각 조각이 나오는 시각은 TTS 문장 시간(start/end) 안에서 글자 수 비율로 정한다 (읽는 속도와 맞음).
- 배경 사진의 밝기/복잡도를 보고 글자 뒤 반투명 패널의 진하기를 조절한다 (흰 글자 + 검은 테두리 + 패널).
"""
import os
import re

import numpy as np
from PIL import Image, ImageDraw, ImageFont
import textfix  # noqa: F401  (글꼴에 없는 하이픈 등을 네모칸 대신 안전한 글자로)

BOX_W = 1000            # 이미지 박스 폭
FONT_SIZE = 58
MAX_LINES = 2
PAD_X, PAD_Y = 38, 22   # 패널 안쪽 여백
MAX_TEXT_W = BOX_W - 2 * 64
LINE_GAP = 8
MIN_SHOW = 0.85         # 한 조각 최소 표시 시간(초)
_FONT_CACHE = {}


def _font(size=FONT_SIZE):
    if size in _FONT_CACHE:
        return _FONT_CACHE[size]
    cands = [
        r"C:\Windows\Fonts\malgunbd.ttf", r"C:\Windows\Fonts\NanumGothicBold.ttf",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc", "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
    ]
    f = None
    for p in cands:
        if os.path.exists(p):
            f = ImageFont.truetype(p, size)
            break
    _FONT_CACHE[size] = f or ImageFont.load_default()
    return _FONT_CACHE[size]


_DRAW = ImageDraw.Draw(Image.new("RGB", (4, 4)))
_asc, _desc = _font().getmetrics()
CAP_H = MAX_LINES * (_asc + _desc + LINE_GAP) + 2 * PAD_Y + 14   # 2줄 패널이 잘리지 않는 높이


def _w(text, font=None):
    return _DRAW.textlength(text, font=font or _font())


def wrap(text, max_w=MAX_TEXT_W, font=None):
    """공백 단위로 줄바꿈. 한 단어가 한 줄보다 길면 글자 단위로 자른다."""
    font = font or _font()
    lines, cur = [], ""
    for word in str(text).split():
        pieces = [word]
        if _w(word, font) > max_w:
            pieces, buf = [], ""
            for ch in word:
                if _w(buf + ch, font) > max_w and buf:
                    pieces.append(buf)
                    buf = ch
                else:
                    buf += ch
            pieces.append(buf)
        for pc in pieces:
            trial = pc if not cur else cur + " " + pc
            if cur and _w(trial, font) > max_w:
                lines.append(cur)
                cur = pc
            else:
                cur = trial
    if cur:
        lines.append(cur)
    return lines


def _nospace(t):
    return len(re.sub(r"\s+", "", str(t)))


def split_chunks(sentence, max_lines=MAX_LINES):
    """문장을 (최대 max_lines줄에 들어가는) 자막 조각으로 나눈다. 쉼표 등 끊어 읽는 곳을 우선한다."""
    words = str(sentence).split()
    chunks, cur = [], []
    for w in words:
        trial = cur + [w]
        if cur and len(wrap(" ".join(trial))) > max_lines:
            chunks.append(cur)
            cur = [w]
        elif cur and re.search(r"[,，、;:]$", cur[-1]) and _nospace(" ".join(cur)) >= 12:
            chunks.append(cur)   # 쉼표에서 끊어도 앞 조각이 너무 짧지 않으면 거기서 나눈다
            cur = [w]
        else:
            cur = trial
    if cur:
        chunks.append(cur)
    # 마지막 조각이 너무 짧으면(외톨이) 앞 조각의 끝 단어를 가져와 균형을 맞춘다
    while len(chunks) >= 2 and _nospace(" ".join(chunks[-1])) < 9 and len(chunks[-2]) > 1:
        moved = chunks[-2][-1]
        if _nospace(" ".join(chunks[-2][:-1])) < 9:
            break
        chunks[-2] = chunks[-2][:-1]
        chunks[-1] = [moved] + chunks[-1]
    out = [" ".join(c) for c in chunks]
    if len(out) >= 2 and _nospace(out[-1]) < 6 and len(wrap(out[-2] + " " + out[-1])) <= max_lines:
        out[-2:] = [out[-2] + " " + out[-1]]
    return out


def make_cues(timings, audio_duration):
    """[(시작, 끝, 텍스트)]. timings = [{start,end,text}] (TTS 문장 시간)."""
    cues = []
    for t in timings:
        st, en = float(t["start"]), float(t["end"])
        if en <= st or not str(t["text"]).strip():
            continue
        chunks = split_chunks(t["text"])
        weights = [max(1, _nospace(c)) for c in chunks]
        total, acc = float(sum(weights)), 0.0
        for c, wt in zip(chunks, weights):
            a = st + (en - st) * acc / total
            acc += wt
            b = st + (en - st) * acc / total
            cues.append([a, b, c, st, en])
    # 너무 짧게 지나가는 조각은 같은 문장의 다음 조각과 합친다 (합쳐도 2줄 이하일 때)
    merged = []
    i = 0
    while i < len(cues):
        c = cues[i]
        while (c[1] - c[0] < MIN_SHOW and i + 1 < len(cues) and cues[i + 1][3] == c[3]
               and len(wrap(c[2] + " " + cues[i + 1][2])) <= MAX_LINES):
            n = cues[i + 1]
            c = [c[0], n[1], c[2] + " " + n[2], c[3], c[4]]
            i += 1
        merged.append(c)
        i += 1
    # 끝 시각: 다음 조각 시작까지 이어 붙이되, 긴 침묵 뒤에는 잠깐만 남긴다. 최소 표시 시간 보장
    out = []
    for k, c in enumerate(merged):
        nxt = merged[k + 1][0] if k + 1 < len(merged) else audio_duration
        end = c[1]
        end = nxt if nxt - end < 0.6 else min(nxt, end + 0.4)
        end = max(end, min(c[0] + MIN_SHOW, nxt))
        end = min(end, audio_duration)
        if end > c[0]:
            out.append((c[0], end, c[2]))
    return out


def region_stats(img, box_h=CAP_H + 40):
    """자막이 놓이는 사진 아래쪽의 평균 밝기(0~255)와 복잡도(표준편차)."""
    if img is None:
        return 90.0, 30.0
    im = img.convert("L")
    w, h = im.size
    crop = im.crop((0, max(0, h - box_h), w, h)).resize((64, 16))
    a = np.asarray(crop, dtype=np.float32)
    return float(a.mean()), float(a.std())


def panel_alpha(luma, std):
    """사진이 밝거나 복잡할수록 패널을 진하게 (0.5 ~ 0.86)."""
    a = 0.50 + 0.28 * (luma / 255.0) + 0.14 * min(1.0, std / 70.0)
    return max(0.5, min(0.86, a))


def render_caption(text, luma=90.0, std=30.0):
    """BOX_W x CAP_H RGBA 배열. 패널은 아래쪽 기준으로 놓여 1줄/2줄 모두 바닥선이 같다."""
    font = _font()
    lines = wrap(text)[:MAX_LINES] or [""]
    asc, desc = font.getmetrics()
    lh = asc + desc + LINE_GAP
    tw = max(_w(l, font) for l in lines)
    pw = int(min(BOX_W - 8, tw + 2 * PAD_X))
    ph = int(lh * len(lines) + 2 * PAD_Y - LINE_GAP)
    scale = 3
    panel = Image.new("L", (pw * scale, ph * scale), 0)
    ImageDraw.Draw(panel).rounded_rectangle((0, 0, pw * scale - 1, ph * scale - 1), radius=26 * scale, fill=255)
    panel = panel.resize((pw, ph), Image.Resampling.LANCZOS)
    img = Image.new("RGBA", (BOX_W, CAP_H), (0, 0, 0, 0))
    x0, y0 = (BOX_W - pw) // 2, CAP_H - ph - 6
    alpha = int(255 * panel_alpha(luma, std))
    shade = Image.new("RGBA", (pw, ph), (10, 10, 14, 255))
    shade.putalpha(panel.point(lambda v: v * alpha // 255))
    img.alpha_composite(shade, (x0, y0))
    d = ImageDraw.Draw(img)
    y = y0 + PAD_Y
    for l in lines:
        x = (BOX_W - _w(l, font)) / 2
        d.text((x, y), l, font=font, fill=(255, 255, 255, 255), stroke_width=4, stroke_fill=(0, 0, 0, 255))
        y += lh
    return np.asarray(img, dtype=np.uint8).copy()


# ------------------------------------------------------------------ SRT / 자막 모드
def caption_mode():
    """CAPTION_MODE: script(영상에 자막 입힘, 기본) / srt(.srt 파일만, 영상엔 자막 없음) / both(둘 다) / highlight(예전 핵심 문구)"""
    import os
    m = (os.environ.get("CAPTION_MODE") or "script").strip().lower()
    return m if m in ("script", "srt", "both", "highlight") else "script"


def burn_in(mode):
    return mode in ("script", "both")


def _srt_time(t):
    ms = int(round(max(0.0, t) * 1000))
    h, ms = divmod(ms, 3600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def to_srt(cues, offset=0.0, start_no=1):
    """[(시작, 끝, 텍스트)] -> SRT 문자열 (자막은 최대 2줄)."""
    out = []
    for n, (a, b, text) in enumerate(cues, start=start_no):
        lines = wrap(text)[:MAX_LINES] or [str(text)]
        out.append(f"{n}\n{_srt_time(a + offset)} --> {_srt_time(b + offset)}\n" + "\n".join(lines) + "\n")
    return "\n".join(out)
