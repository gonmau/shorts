# build_video.py (클라우드용: 정사각형 이미지 + 헐코리아 스타일 레이아웃, 이미지 없으면 대체 카드)
# -*- coding: utf-8 -*-

import argparse
import json
import os
import re
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

# Pillow compatibility
if not hasattr(Image, "ANTIALIAS"):
    try:
        Image.ANTIALIAS = Image.Resampling.LANCZOS
    except AttributeError:
        pass

from moviepy.editor import (
    AudioFileClip,
    CompositeVideoClip,
    ImageClip,
    VideoClip,
)

from layout import IMG_BOX, SUBTITLE_Y, make_template, make_corner_overlay
from common import split_sentences, strip_marks, visual_dir


BASE_DIR = Path(__file__).resolve().parent
FACTS_DB = BASE_DIR / "facts_db.json"

VIDEO_DIR = BASE_DIR / "videos"
AUDIO_DIR = BASE_DIR / "audio"
VISUAL_DIR = BASE_DIR / "visuals"

W, H = 1080, 1920
FPS = 30
SCENE_COUNT = 6

# 레이아웃 설정 (CLI 인자로 덮어씀)
LAYOUT_CFG = {
    "channel": "채널명",
    "handle": "@handle",
    "avatar": None,
    "credit": "",    # 비우면 country 사용
}


def split_title(item):
    """제목을 2줄로 나눈다. item에 title_line1/title_line2가 있으면 그대로 사용."""
    l1, l2 = item.get("title_line1"), item.get("title_line2")
    if l1 and l2:
        return str(l1), str(l2)

    # 제목이 없을 때: 한글이 있는 후보를 우선 사용 (topic/hook이 영어인 항목 대비)
    def has_hangul(x):
        return bool(re.search(r"[가-힣]", str(x or "")))

    cand = next((item.get(k) for k in ("title", "topic", "hook") if has_hangul(item.get(k))), None)
    if not cand:
        narr = " ".join(str(item.get("narration") or "").split())
        first = re.split(r"(?<=[.!?。！？])\s+", narr)[0] if narr else ""
        cand = first[:24] if first else (item.get("topic") or safe_country(item))
    t = " ".join(str(cand).split())
    words = t.split(" ")
    if len(words) >= 2:
        best = min(
            range(1, len(words)),
            key=lambda i: abs(len(" ".join(words[:i])) - len(" ".join(words[i:]))),
        )
        return " ".join(words[:best]), " ".join(words[best:])
    half = (len(t) + 1) // 2
    return t[:half], t[half:]


def load_db():
    if not FACTS_DB.exists():
        raise FileNotFoundError(f"facts_db.json 없음: {FACTS_DB}")

    with open(FACTS_DB, "r", encoding="utf-8") as f:
        return json.load(f)


def save_db(db):
    with open(FACTS_DB, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)


def get_items(db):
    if isinstance(db, list):
        return db
    if isinstance(db, dict):
        if isinstance(db.get("facts"), list):
            return db["facts"]
        if isinstance(db.get("items"), list):
            return db["items"]
    raise ValueError("facts_db.json의 구조를 찾을 수 없습니다.")


def safe_country(item):
    raw = str(
        item.get("country")
        or item.get("나라")
        or item.get("title")
        or "unknown"
    ).strip()
    # NFKC 정규화로 특수 공백류(좁은 줄바꿈방지공백 등)를 일반 공백으로 통일
    # (generate_visuals*.py의 folder_name()과 동일한 방식으로 맞춰야 폴더를 찾음)
    import unicodedata
    normalized = unicodedata.normalize("NFKC", raw).strip()
    return re.sub(r"\s+", " ", normalized)


def safe_filename(text):
    return re.sub(r'[<>:"/\\|?*]', "_", str(text)).strip()


def get_audio_path(item, idx):
    p = item.get("audio_path_v2")
    if p and Path(p).exists():
        return Path(p)

    candidates = [
        AUDIO_DIR / f"{idx:04d}_{safe_country(item)}_v2.mp3",
        AUDIO_DIR / f"{idx:04d}_{safe_country(item)}.mp3",
    ]

    for c in candidates:
        if c.exists():
            return c

    # Windows 경로가 DB에 저장되어 있어도 파일명만 맞으면 찾는다.
    for c in AUDIO_DIR.glob(f"{idx:04d}_*.mp3"):
        if "_v2" in c.stem or not any("_v2" in x.stem for x in AUDIO_DIR.glob(f"{idx:04d}_*.mp3")):
            return c

    return None


def get_timing_path(item, idx):
    p = item.get("timing_path_v2")
    if p and Path(p).exists():
        return Path(p)

    c = AUDIO_DIR / f"{idx:04d}_{safe_country(item)}_v2_timing.json"
    if c.exists():
        return c

    for c in AUDIO_DIR.glob(f"{idx:04d}_*_v2_timing.json"):
        return c

    return None


def get_visual_paths(idx, item):
    """scene_01~06.png 경로 목록 (없는 파일도 경로는 돌려줌 - 장면별로 대체 카드 사용)."""
    d = visual_dir(BASE_DIR, idx, item)
    for cand in (d, d.parent / (d.name + "_clean")):
        paths = [cand / f"scene_{n:02d}.png" for n in range(1, SCENE_COUNT + 1)]
        if all(p.exists() for p in paths):
            return paths
    return [d / f"scene_{n:02d}.png" for n in range(1, SCENE_COUNT + 1)]


def load_timings(path, audio_duration, script_text):
    if path and path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)

            sentences = data.get("sentences", [])
            result = []

            for s in sentences:
                start = float(s.get("start", 0))
                end = float(s.get("end", 0))
                text = str(s.get("text", "")).strip()

                if end > start and text:
                    result.append({
                        "start": max(0.0, start),
                        "end": min(audio_duration, end),
                        "text": text,
                    })

            if result:
                return result
        except Exception as e:
            print(f"timing JSON 읽기 실패 → fallback: {e}")

    # timing JSON이 없을 경우 문장 길이 기반 fallback
    import re

    parts = [
        x.strip()
        for x in re.split(r"(?<=[.!?。！？])\s+|\n+", script_text or "")
        if x.strip()
    ]

    if not parts:
        parts = [script_text or ""]

    weights = [max(1, len(x)) for x in parts]
    total = sum(weights)

    result = []
    cur = 0.0

    for i, text in enumerate(parts):
        dur = audio_duration * weights[i] / total
        end = audio_duration if i == len(parts) - 1 else cur + dur

        result.append({
            "start": cur,
            "end": end,
            "text": text,
        })
        cur = end

    return result


def short_caption(text, max_chars=25):
    text = " ".join(str(text).split())

    # 이미 짧으면 그대로
    if len(text) <= max_chars:
        return text

    # 쉼표/조사 등에서 자연스럽게 줄이기
    for sep in ["。", ".", "!", "?", "！", "？", ",", "，"]:
        if sep in text:
            left = text.split(sep)[0].strip()
            if 8 <= len(left) <= max_chars:
                return left

    return text[:max_chars].rstrip() + "…"


def find_font(size, bold=False):
    candidates = []

    if bold:
        candidates += [
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
            "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
            r"C:\Windows\Fonts\malgunbd.ttf",
        ]
    else:
        candidates += [
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
            r"C:\Windows\Fonts\malgun.ttf",
        ]

    for p in candidates:
        if os.path.exists(p):
            return p

    return None


HL_COLOR = (255, 226, 0)      # 강조 단어 (노랑)
HL_BASE = (255, 255, 255)     # 나머지 단어 (흰색)
CAP_W, CAP_H = IMG_BOX[2] - IMG_BOX[0], 360


def parse_marked(text):
    """'길에서 *사자* 키우면?' -> [('길에서', False), ('사자', True), ('키우면?', False)]"""
    words = []
    for part in re.split(r"(\*[^*]+\*)", str(text)):
        if not part:
            continue
        hl = len(part) > 2 and part.startswith("*") and part.endswith("*")
        for w in part.strip("*").split():
            words.append((w, hl))
    return words


def make_highlight_image(text):
    """핵심 문구를 크게 (최대 2줄, 글자 수가 달라도 자동으로 크기 조절) 그린 RGBA 배열.
    *별표* 단어는 노랑, 나머지는 흰색 (별표가 없으면 전부 노랑). 굵은 검정 테두리."""
    img = Image.new("RGBA", (CAP_W, CAP_H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    words = parse_marked(text)
    if not words:
        return np.array(img)

    any_hl = any(hl for _, hl in words)
    max_w = CAP_W - 110

    def wrap(font, items, space):
        lines, cur, cur_w = [], [], 0.0
        for w, hl in items:
            ww = draw.textlength(w, font=font)
            add = ww if not cur else space + ww
            if cur and cur_w + add > max_w:
                lines.append(cur)
                cur, cur_w = [(w, hl)], ww
            else:
                cur.append((w, hl))
                cur_w += add
        if cur:
            lines.append(cur)
        return lines

    font, size, lines, space = None, 0, [], 0
    for size in range(124, 55, -4):
        fp = find_font(size, bold=True)
        font = ImageFont.truetype(fp, size) if fp else ImageFont.load_default()
        space = draw.textlength(" ", font=font)
        lines = wrap(font, words, space)
        if len(lines) <= 2 and all(draw.textlength(w, font=font) <= max_w for w, _ in words):
            break
    else:
        # 공백 없이 아주 긴 문구: 글자 단위로 줄바꿈
        space = 0
        lines = wrap(font, [(ch, hl) for w, hl in words for ch in w], 0)[:2]

    stroke = max(7, size // 9)
    asc, desc = font.getmetrics()
    lh = asc + desc + 6
    y = CAP_H - lh * len(lines) - 16  # 아래쪽 기준으로 정렬 (1줄/2줄 모두 바닥선 일정)

    for line in lines:
        total = sum(draw.textlength(w, font=font) for w, _ in line) + space * (len(line) - 1)
        x = (CAP_W - total) / 2
        for w, hl in line:
            color = HL_COLOR if (hl or not any_hl) else HL_BASE
            draw.text((x, y), w, font=font, fill=color + (255,),
                      stroke_width=stroke, stroke_fill=(0, 0, 0, 255))
            x += draw.textlength(w, font=font) + space
        y += lh
    return np.array(img)


def make_scrim(h=470, max_alpha=165):
    """이미지 아래쪽을 살짝 어둡게 (사진이 밝아도 큰 글자가 읽히도록)."""
    bw = IMG_BOX[2] - IMG_BOX[0]
    arr = np.zeros((h, bw, 4), dtype=np.uint8)
    alpha = (np.linspace(0, 1, h) ** 1.7 * max_alpha).astype(np.uint8)
    arr[..., 3] = alpha[:, None]
    return arr


def _nospace(t):
    return len(re.sub(r"\s+", "", str(t)))


def time_at_fraction(frac, timings):
    """대본 글자 수 비율(0~1) -> 실제 음성 시간(초). TTS 문장 경계 안에서는 선형 보간."""
    total = sum(_nospace(t["text"]) for t in timings)
    if total == 0 or not timings:
        return 0.0
    target, acc = frac * total, 0
    for t in timings:
        n = _nospace(t["text"])
        if acc + n >= target and n > 0:
            return t["start"] + (target - acc) / n * (t["end"] - t["start"])
        acc += n
    return timings[-1]["end"]


def highlight_cues(item, timings, audio_duration, narration):
    """[(시작, 끝, 문구)] 목록. highlights가 있으면 그 문구가 해당 문장이 읽히는 동안 나온다.
    highlights가 아예 없으면(None) 문장을 짧게 줄여 대체하고, 빈 리스트([])면 표시하지 않는다."""
    hl = item.get("highlights")
    if hl is None:
        print("  핵심 문구 없음 -> 대본 문장을 짧게 줄여 표시")
        return [
            (max(0.0, t["start"]), min(audio_duration, t["end"]), short_caption(t["text"], 14))
            for t in timings if t["end"] > t["start"]
        ]
    if not hl:
        return []

    sents = split_sentences(narration)
    total = sum(_nospace(x) for x in sents) or 1
    cum = [0]
    for x in sents:
        cum.append(cum[-1] + _nospace(x))

    cues = []
    for h in sorted(hl, key=lambda h: h["s"]):
        n = h["s"]
        if not (1 <= n <= len(sents)):
            continue
        st = time_at_fraction(cum[n - 1] / total, timings)
        en = time_at_fraction(cum[n] / total, timings)
        cues.append([st, en, h["text"]])

    for k, c in enumerate(cues):  # 최소 1.4초는 보이게, 다음 문구 시작 전까지
        nxt = cues[k + 1][0] if k + 1 < len(cues) else audio_duration
        c[1] = min(max(c[1], c[0] + 1.4), nxt, audio_duration)
    return [tuple(c) for c in cues if c[1] > c[0]]


def prepare_scene_image(path):
    """이미지를 IMG_BOX(정사각형) 크기로 중앙 크롭한 RGB 배열로 변환."""
    if not path.exists():
        raise FileNotFoundError(f"이미지 없음: {path}")

    from PIL import ImageOps
    bw, bh = IMG_BOX[2] - IMG_BOX[0], IMG_BOX[3] - IMG_BOX[1]

    with Image.open(path) as im:
        im = im.convert("RGB")
        # 세로 이미지는 얼굴이 위쪽에 있는 경우가 많아 크롭 중심을 약간 위로
        im = ImageOps.fit(im, (bw, bh), Image.Resampling.LANCZOS, centering=(0.5, 0.35))
        return np.asarray(im, dtype=np.uint8).copy()


# ------------------------------------------------------------------
# 이미지 박스 모션 (Ken Burns 강화 + 장면 간 크로스페이드)
# ------------------------------------------------------------------
# 줌 크기: 0.12 = 최대 12% 확대 (눈에 띄는 정도). 0이면 정지 화면.
ZOOM = 0.12
# 장면 전환 크로스페이드 길이(초). 0이면 하드컷.
XFADE = 0.4

# (줌 시작, 줌 끝, 팬X 시작, 팬X 끝, 팬Y 시작, 팬Y 끝)
#  - 줌 값은 ZOOM에 대한 비율(0~1), 팬 값은 -1~1 (좌/위 = -1, 우/아래 = +1)
MOTIONS = [
    (0, 1, 0, 0, 0, 0),     # 중앙 줌인
    (1, 1, -1, 1, 0, 0),    # 좌 -> 우 팬
    (1, 0, 0, 0, 0, 0),     # 중앙 줌아웃
    (0, 1, 0, 0, 1, -1),    # 줌인 + 위로 이동
    (1, 1, 1, -1, 0, 0),    # 우 -> 좌 팬
    (1, 0, 0, 0, -1, 1),    # 줌아웃 + 아래로 이동
]


def _smooth(p):
    p = min(max(p, 0.0), 1.0)
    return p * p * (3 - 2 * p)


def render_motion_frame(src, scene_index, p, zoom):
    """src(PIL, 박스 크기)에서 진행도 p(0~1)에 해당하는 크롭 프레임을 만든다."""
    bw, bh = src.size
    za, zb, pxa, pxb, pya, pyb = MOTIONS[scene_index % len(MOTIONS)]
    e = _smooth(p)
    s = 1.0 + zoom * (za + (zb - za) * e)
    px = pxa + (pxb - pxa) * e
    py = pya + (pyb - pya) * e

    cw, ch = bw / s, bh / s
    sx, sy = (bw - cw) / 2, (bh - ch) / 2
    l = min(max(sx * (1 + px), 0.0), bw - cw)
    t = min(max(sy * (1 + py), 0.0), bh - ch)
    return src.resize((bw, bh), Image.Resampling.BICUBIC, box=(l, t, l + cw, t + ch))


PLACEHOLDER_COLORS = [
    ((40, 60, 140), (110, 70, 200)),
    ((20, 110, 120), (40, 170, 140)),
    ((150, 60, 90), (220, 110, 90)),
    ((50, 80, 60), (110, 150, 80)),
    ((90, 50, 140), (190, 80, 170)),
    ((30, 70, 110), (60, 140, 190)),
]


def make_placeholder_scene(n, country, topic):
    """장면 이미지가 없을 때 쓰는 그라데이션 카드 (국가명 + 주제)."""
    bw, bh = IMG_BOX[2] - IMG_BOX[0], IMG_BOX[3] - IMG_BOX[1]
    c1, c2 = PLACEHOLDER_COLORS[(n - 1) % len(PLACEHOLDER_COLORS)]
    t = np.linspace(0, 1, bh, dtype=np.float32)[:, None, None]
    grad = (np.array(c1, np.float32) * (1 - t) + np.array(c2, np.float32) * t)
    arr = np.repeat(grad, bw, axis=1).astype(np.uint8)
    im = Image.fromarray(arr)
    d = ImageDraw.Draw(im)

    def fit(text, start, bold=True):
        size = start
        while size > 30:
            fp = find_font(size, bold)
            f = ImageFont.truetype(fp, size) if fp else ImageFont.load_default()
            if d.textlength(text, font=f) <= bw - 120:
                return f
            size -= 4
        return f

    f1 = fit(country, 150)
    d.text(((bw - d.textlength(country, font=f1)) / 2, bh * 0.14), country, font=f1,
           fill=(255, 255, 255), stroke_width=3, stroke_fill=(0, 0, 0))
    if topic:
        f2 = fit(topic, 60, bold=False)
        d.text(((bw - d.textlength(topic, font=f2)) / 2, bh * 0.14 + 180), topic, font=f2,
               fill=(235, 235, 245))
    return im


def load_scene_sources(visual_paths, country, topic):
    """장면마다 이미지가 있으면 사용하고, 없거나 깨졌으면 그 장면만 대체 카드로 채운다."""
    srcs, real = [], 0
    for n, p in enumerate(visual_paths, start=1):
        if p.exists():
            try:
                srcs.append(Image.fromarray(prepare_scene_image(p)))
                real += 1
                continue
            except Exception as e:
                print(f"  scene_{n:02d} 이미지 읽기 실패 -> 대체 카드: {e}")
        srcs.append(make_placeholder_scene(n, country, topic))
    return srcs, real


def make_image_box_clip(srcs, audio_duration, zoom=None, xfade=None):
    """6장면 전체를 하나의 클립으로 만든다 (장면별 모션 + 장면 전환 크로스페이드)."""
    zoom = ZOOM if zoom is None else zoom
    xfade = XFADE if xfade is None else xfade

    n = len(srcs)
    sd = audio_duration / n
    xf = min(max(xfade, 0.0), sd * 0.4)

    def frame(t):
        i = min(int(t / sd), n - 1)
        local = t - i * sd
        cur = render_motion_frame(srcs[i], i, local / sd, zoom)
        if i > 0 and xf > 0 and local < xf:
            w = _smooth(local / xf)
            prev = render_motion_frame(srcs[i - 1], i - 1, 1.0, zoom)
            cur = Image.blend(prev, cur, w)
        return np.asarray(cur, dtype=np.uint8)

    return (
        VideoClip(frame, duration=audio_duration)
        .set_start(0)
        .set_position((IMG_BOX[0], IMG_BOX[1]))
    )


def build_one(idx, item):
    country = safe_country(item)

    print(f"\n[{idx}] {country}")

    audio_path = get_audio_path(item, idx)
    if not audio_path:
        raise FileNotFoundError(f"오디오 파일을 찾지 못했습니다: {idx:04d}")

    timing_path = get_timing_path(item, idx)
    visual_paths = get_visual_paths(idx, item)

    print(f"오디오: {audio_path}")
    print(f"타이밍: {timing_path}")
    srcs, real_images = load_scene_sources(
        visual_paths, country, str(item.get("topic") or "")
    )
    print(f"이미지: {real_images}/{SCENE_COUNT}장 사용 (나머지는 대체 카드)")

    audio = AudioFileClip(str(audio_path))
    audio_duration = float(audio.duration)

    script = (
        item.get("script")
        or item.get("narration")
        or item.get("대본")
        or item.get("text")
        or ""
    )

    timings = load_timings(timing_path, audio_duration, script)

    # 6개 장면을 정확히 전체 오디오에 배분
    scene_duration = audio_duration / SCENE_COUNT

    print(f"오디오 길이: {audio_duration:.2f}초")
    print(f"장면당 길이: {scene_duration:.2f}초")
    print(f"모션: 줌 {ZOOM*100:.0f}% / 크로스페이드 {XFADE:.2f}초")

    for i in range(SCENE_COUNT):
        start = i * scene_duration
        end = audio_duration if i == SCENE_COUNT - 1 else start + scene_duration
        print(f"  장면 {i+1}: {start:.2f}s ~ {end:.2f}s")

    scene_clips = [make_image_box_clip(srcs, audio_duration)]

    # 배경 템플릿(프로필/제목/크레딧/하단바) + 이미지 박스 + 모서리 오버레이
    title1, title2 = split_title(item)
    template = make_template(
        title1, title2,
        LAYOUT_CFG["credit"]
        or ("Photos: Pixabay" if (item.get("image_source") == "pixabay" and real_images) else country),
        None,
        channel_name=LAYOUT_CFG["channel"],
        handle=LAYOUT_CFG["handle"],
        avatar_path=LAYOUT_CFG["avatar"],
    )
    bg_clip = ImageClip(np.array(template)).set_duration(audio_duration)
    corner = (
        ImageClip(np.array(make_corner_overlay()))
        .set_duration(audio_duration)
        .set_position((IMG_BOX[0], IMG_BOX[1]))
    )

    scrim_arr = make_scrim()
    scrim = (
        ImageClip(scrim_arr)
        .set_duration(audio_duration)
        .set_position((IMG_BOX[0], IMG_BOX[3] - scrim_arr.shape[0]))
    )

    base = CompositeVideoClip(
        [bg_clip] + scene_clips + [scrim, corner],
        size=(W, H),
    ).set_duration(audio_duration)

    # 핵심 문구 (대본 문장 대신, 눈에 띄게)
    caption_clips = []
    cues = highlight_cues(item, timings, audio_duration, script)
    for start, end, text in cues:
        print(f"  문구 {start:5.1f}s~{end:5.1f}s: {strip_marks(text)}")
        cc = (
            ImageClip(make_highlight_image(text))
            .set_start(start)
            .set_duration(end - start)
            .set_position((IMG_BOX[0], IMG_BOX[3] - CAP_H - 20))
            .crossfadein(0.1)
        )
        caption_clips.append(cc)

    final = CompositeVideoClip(
        [base] + caption_clips,
        size=(W, H),
    ).set_duration(audio_duration)

    final = final.set_audio(audio)

    VIDEO_DIR.mkdir(exist_ok=True)

    out_path = VIDEO_DIR / f"{idx:04d}_{safe_filename(country)}.mp4"

    print(f"렌더링 시작: {out_path}")

    final.write_videofile(
        str(out_path),
        fps=FPS,
        codec="libx264",
        audio_codec="aac",
        preset="medium",
        threads=4,
        ffmpeg_params=[
            "-pix_fmt",
            "yuv420p",
        ],
    )

    # DB 업데이트
    item["video_path_v6"] = str(out_path)
    item["status"] = "video_done"
    item["status_v6"] = "video_done"

    # 리소스 정리
    final.close()
    base.close()
    audio.close()
    for c in (scrim, corner, bg_clip):
        try:
            c.close()
        except Exception:
            pass

    for c in scene_clips:
        try:
            c.close()
        except Exception:
            pass

    for c in caption_clips:
        try:
            c.close()
        except Exception:
            pass

    return out_path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--index", type=int, default=None)
    parser.add_argument("--start", type=int, default=0,
                        help="이 번호 이후의 소재만 처리 (PC에서 이미 만든 옛 소재 건너뛰기)")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--channel", default=LAYOUT_CFG["channel"], help="채널명")
    parser.add_argument("--handle", default=LAYOUT_CFG["handle"], help="@핸들")
    parser.add_argument("--avatar", default="avatar.png", help="프로필 이미지 경로 (기본: avatar.png)")
    parser.add_argument("--credit", default="", help="이미지 아래 크레딧 (기본: country)")
    parser.add_argument("--zoom", type=float, default=None,
                        help="Ken Burns 최대 확대 비율 (기본 0.12 = 12%%, 0이면 정지)")
    parser.add_argument("--xfade", type=float, default=None,
                        help="장면 전환 크로스페이드 초 (기본 0.4, 0이면 하드컷)")
    args = parser.parse_args()
    global ZOOM, XFADE
    if args.zoom is not None:
        ZOOM = max(0.0, min(args.zoom, 0.3))
    if args.xfade is not None:
        XFADE = max(0.0, args.xfade)
    LAYOUT_CFG.update(channel=args.channel, handle=args.handle, avatar=args.avatar,
                      credit=args.credit)

    db = load_db()
    items = get_items(db)

    targets = []

    if args.index is not None:
        if args.index < 0 or args.index >= len(items):
            raise IndexError(f"index 범위 오류: {args.index}")
        targets = [(args.index, items[args.index])]
    else:
        for idx, item in enumerate(items):
            if idx < args.start:
                continue
            if (
                item.get("status_tts_v2") == "done"
                and item.get("status_v6") != "video_done"
                and not item.get("video_path_v6")
                and get_audio_path(item, idx)  # 오디오가 실제로 있는 소재만
            ):
                targets.append((idx, item))

        if args.limit:
            targets = targets[:args.limit]

    if not targets:
        print("처리할 항목이 없습니다.")
        return

    success = 0

    for idx, item in targets:
        try:
            out = build_one(idx, item)
            save_db(db)
            print(f"성공: {idx} / {out}")
            success += 1
        except Exception as e:
            print(f"실패: {idx} / {type(e).__name__}: {e}")

    save_db(db)
    print(f"\n완료: {success} / {len(targets)}")


if __name__ == "__main__":
    main()
