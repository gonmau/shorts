# -*- coding: utf-8 -*-
"""롱폼(16:9) 새 화면: 사진을 화면 전체에 쓰고(천천히 확대/이동), 번호/나라/채널은 작은 표시로, 자막은 아래 가운데,
핵심 키워드 팝업, 비교 카드, 챕터 카드, 인트로(사진 몽타주), 마지막 요약 화면을 만든다.
build_longform.py 의 --style rich (기본) 에서 쓴다. (옛 'ppt 같은' 화면은 --style classic)"""
import json
import os
import re
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageOps
import textfix  # noqa: F401  (글꼴에 없는 하이픈 등을 네모칸 대신 안전한 글자로)

W, H = 1920, 1080
FPS = 24
PURPLE = (56, 189, 248)   # 하늘색 (예전 분홍/보라 대신. 변수 이름은 그대로)
YELLOW = (255, 226, 0)
INK = (14, 14, 22)
def _detect_en(base):
    """영어 채널 여부. 두 채널 파일이 섞인 폴더도 local_ui.py와 같은 규칙으로 판별 (channel.txt > 파일 구성 > generate_tts.py 내용)"""
    has_en, has_ko = (base / "generate_topics.py").exists(), (base / "generate_culture_facts.py").exists()
    if has_en and has_ko:
        try:
            return (base / "channel.txt").read_text(encoding="utf-8").strip().lower() == "en"
        except Exception:
            try:
                return "ko-KR-SunHiNeural" not in (base / "generate_tts.py").read_text(encoding="utf-8")
            except Exception:
                return False
    return has_en and not has_ko

IS_EN = _detect_en(Path(__file__).resolve().parent)
import ko_text as KT  # noqa: E402
_dc = (lambda x: str(x or "")) if IS_EN else KT.disp_country   # 화면에 보이는 나라 이름은 한국어 표기로
CAP_IMG_H = 190
CAP_W = 1560
L = {  # 화면 글자
    "recap": "Recap" if IS_EN else "오늘의 요약",
    "stories": (lambda n: f"{n} stories") if IS_EN else (lambda n: f"{n}가지 이야기"),
    "sub": "Subscribe · Like" if IS_EN else "구독 · 좋아요",
    "chapter": "Chapter" if IS_EN else "챕터",
}


# ---------------------------------------------------------------- 기본 도구
def font(size, bold=True):
    import build_video as B
    from PIL import ImageFont
    fp = B.find_font(size, bold=bold)
    return ImageFont.truetype(fp, size) if fp else ImageFont.load_default()


def new_layer():
    return Image.new("RGBA", (W, H), (0, 0, 0, 0))


def arr(im):
    return np.asarray(im, dtype=np.uint8).copy()


BRAND_FILE = Path(__file__).resolve().parent / "longform_brand.json"
BRAND_DEFAULT = {"channel": "", "handle": "", "avatar": "", "hud": True, "hud_avatar": True, "hud_name": True, "hud_handle": True,
                 "hud_text": "", "hud_pill": True, "intro_logo": True, "intro_name": True, "cta": "", "recap": True, "recap_cards": True}


def load_brand():
    """longform_brand.json (UI '채널 표시' 설정). 없거나 깨져도 기본값"""
    b = dict(BRAND_DEFAULT)
    try:
        b.update({k: v for k, v in json.loads(BRAND_FILE.read_text(encoding="utf-8")).items() if k in BRAND_DEFAULT})
    except Exception:
        pass
    return b


BRAND = load_brand()


def avatar_file(path=None):
    """쓸 채널 이미지 파일: 설정한 이미지 > 인자 > channel_avatar.png > avatar.png (코드 폴더/현재 폴더). 없으면 None"""
    base = Path(__file__).resolve().parent
    for c in (BRAND.get("avatar"), path, "channel_avatar.png", "avatar.png"):
        if not c:
            continue
        for q in (Path(c), base / c):
            if q.is_file():
                return str(q)
    return None


def avatar(path, size, label=""):
    f_ = avatar_file(path)
    if f_:
        try:
            im = ImageOps.fit(Image.open(f_).convert("RGB"), (size, size), Image.Resampling.LANCZOS)
        except Exception:
            f_ = None
    if not f_:        # 이미지가 없으면 파란 원 대신 채널 이름 첫 글자를 넣은 그라데이션 원
        im = Image.new("RGB", (size, size))
        px = np.zeros((size, size, 3), np.uint8)
        for c_, (a_, b_) in enumerate(zip((120, 70, 230), (60, 110, 255))):
            px[..., c_] = np.linspace(a_, b_, size)[:, None]
        im = Image.fromarray(px)
        ch = (str(label or BRAND.get("channel") or "?").strip() or "?")[0].upper()
        d_ = ImageDraw.Draw(im)
        ft = font(int(size * 0.55))
        tw = d_.textlength(ch, font=ft)
        d_.text(((size - tw) / 2, size * 0.14), ch, font=ft, fill="white")
    mask = Image.new("L", (size * 4, size * 4), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size * 4 - 1, size * 4 - 1), fill=255)
    out = im.convert("RGBA")
    out.putalpha(mask.resize((size, size), Image.Resampling.LANCZOS))
    return out


def fit_lines(d, text, width, start, min_size, max_lines, bold=True):
    """글자 크기를 줄여 가며 width 안에 max_lines 줄로 들어가는 (폰트, 줄 목록)"""
    for size in range(start, min_size - 1, -2):
        f = font(size, bold)
        lines, cur = [], ""
        for w in str(text).split():
            t = w if not cur else cur + " " + w
            if cur and d.textlength(t, font=f) > width:
                lines.append(cur)
                cur = w
            else:
                cur = t
        if cur:
            lines.append(cur)
        if len(lines) <= max_lines and all(d.textlength(x, font=f) <= width for x in lines):
            return f, lines
    f = font(min_size, bold)
    return f, [str(text)]


def rrect(layer, box, r, fill):
    ImageDraw.Draw(layer).rounded_rectangle(box, radius=r, fill=fill)


def text_c(d, cx, y, text, f, fill, stroke=0):
    tw = d.textlength(text, font=f)
    d.text((cx - tw / 2, y), text, font=f, fill=fill, stroke_width=stroke, stroke_fill=(0, 0, 0))


def exact_audio(path):
    """음성 파일의 '진짜' 길이를 쓰기 위해 wav로 풀어서 쓴다. edge-tts 등 mp3는 헤더 길이가 실제보다 짧게 읽혀
    (moviepy가 그 길이만큼만 쓰면) 문장 끝/인사말이 잘리는 일이 있다. 임시 폴더에 캐시."""
    import hashlib
    import shutil
    import subprocess
    import tempfile
    p = Path(path)
    try:
        key = hashlib.md5(f"{p.resolve()}|{p.stat().st_mtime_ns}|{p.stat().st_size}".encode()).hexdigest()[:16]
        out = Path(tempfile.gettempdir()) / "lf_wav" / f"{key}.wav"
        if out.exists() and out.stat().st_size > 1000:
            return str(out)
        out.parent.mkdir(exist_ok=True)
        exe = shutil.which("ffmpeg")
        if not exe:
            import imageio_ffmpeg
            exe = imageio_ffmpeg.get_ffmpeg_exe()
        r = subprocess.run([exe, "-y", "-loglevel", "error", "-i", str(p), "-ar", "44100", "-ac", "2", str(out)], capture_output=True)
        if r.returncode == 0 and out.exists() and out.stat().st_size > 1000:
            return str(out)
    except Exception:
        pass
    return str(p)


def silent(seconds):
    from moviepy.editor import AudioClip
    return AudioClip(lambda t: np.zeros((np.size(t), 2)) if np.ndim(t) else np.zeros(2), duration=seconds, fps=44100)


def padded_audio(audio, dur, start):
    """음성을 start초에 시작해 전체 길이를 dur로 맞춘 오디오 (뒤는 무음). 그냥 set_start 만 하면 시작이 밀리지 않고 길이도 어긋나
    이어붙일 때 앞 구간 음성이 잘리거나 소리가 먼저 나올 수 있다."""
    from moviepy.editor import CompositeAudioClip
    comp = CompositeAudioClip([silent(dur), audio.set_start(start)]).set_duration(dur)
    comp.fps = 44100
    return comp


MISSING = []          # (소재 번호, 나라, 실제 사진 수, 필요한 수) - 사진이 빠진 챕터 기록 (build_longform 이 끝에 알려줌)

STAGE = {"label": "", "n": 0, "total": 0}   # build_longform 이 진행 단계를 알려준다 (진행률 표시용)


def stage(label, step=None, total=None):
    STAGE["label"] = label
    if step is not None:
        STAGE["n"] = step
    if total is not None:
        STAGE["total"] = total


def _progress_logger(label):
    """moviepy 합성 중 10%마다 한 줄씩 진행률을 출력한다 (창이 멈춘 것처럼 보이지 않게)"""
    try:
        from proglog import ProgressBarLogger
    except Exception:
        return None
    import time as _t

    class P(ProgressBarLogger):
        def __init__(self):
            super().__init__()
            self.last, self.t0 = -1, _t.time()

        def bars_callback(self, bar, attr, value, old_value=None):
            if bar != "t" or attr != "index":
                return
            tot = max(1, self.bars[bar].get("total") or 1)
            pct = int(value * 100 / tot)
            if pct // 10 > self.last // 10 or (pct >= 100 and self.last < 100):
                self.last = pct
                el = _t.time() - self.t0
                eta = (el / max(value, 1) * (tot - value)) if value > 5 else 0
                n, total = STAGE["n"], STAGE["total"]
                head = f"[{n}/{total}] " if total else ""
                print(f"    ⏳ {head}{label} 렌더링 {pct}%" + (f" (남은 시간 약 {int(eta // 60)}분 {int(eta % 60)}초)" if eta > 5 and pct < 100 else ""), flush=True)
    return P()


def write_clip(clip, path, label=None):
    clip.write_videofile(str(path), fps=FPS, codec="libx264", audio_codec="aac", audio_fps=44100, preset="fast", threads=4,
                         ffmpeg_params=["-pix_fmt", "yuv420p", "-ac", "2"], logger=_progress_logger(label or STAGE["label"] or Path(path).stem))


def close_all(*cs):
    for c in cs:
        try:
            c.close()
        except Exception:
            pass


def placeholder(n, label):
    im = Image.new("RGB", (W, H))
    px = np.zeros((H, W, 3), np.uint8)
    base = [(70, 90, 200), (200, 80, 120), (40, 150, 140), (200, 140, 40), (110, 70, 190), (60, 130, 200)][n % 6]
    for c in range(3):
        px[..., c] = np.linspace(base[c] * 0.45, base[c], H)[:, None]
    im = Image.fromarray(px)
    d = ImageDraw.Draw(im)
    text_c(d, W // 2, H // 2 - 60, label[:30], font(120), (255, 255, 255), 3)
    return im


def load_sources(paths, label):
    """장면 이미지 -> 16:9 PIL 목록 (없거나 깨진 장면은 색 카드). (목록, 실제 사진 수)"""
    out, real = [], 0
    for n, p in enumerate(paths):
        try:
            if Path(p).exists():
                with Image.open(p) as im:
                    out.append(ImageOps.fit(im.convert("RGB"), (W, H), Image.Resampling.LANCZOS, centering=(0.5, 0.4)))
                real += 1
                continue
        except Exception as e:
            print(f"  이미지 읽기 실패 -> 색 카드: {p} ({e})", flush=True)
        out.append(placeholder(n, label))
    if not out:
        out.append(placeholder(0, label))
    return out, real


def motion_clip(srcs, dur, starts=None, zoom=0.10, xfade=0.5):
    import build_video as B
    c = B.make_image_box_clip(srcs, dur, zoom=zoom, xfade=xfade, starts=starts)
    return c.set_position((0, 0))


_VID = {}


def _vid_frame(path, t):
    """스톡 영상 한 프레임 (16:9로 채움). 짧으면 반복. 읽기 실패하면 None"""
    try:
        from moviepy.editor import VideoFileClip
        c = _VID.get(path)
        if c is None:
            c = _VID[path] = VideoFileClip(str(path), audio=False)
        d = max(0.5, float(c.duration) - 0.6)
        tt = 0.3 + (t % d)
        im = Image.fromarray(c.get_frame(min(tt, c.duration - 0.05)))
        return ImageOps.fit(im.convert("RGB"), (W, H), Image.Resampling.BILINEAR, centering=(0.5, 0.5))
    except Exception:
        return None


def close_videos():
    for c in list(_VID.values()):
        close_all(c)
    _VID.clear()


def hybrid_bg(entries, dur, starts, zoom=0.10, xfade=0.5):
    """entries: [("img", PIL, 번호) | ("vid", 경로)] 가 starts 시각에 바뀌는 배경. 사진은 확대/이동, 영상은 그대로 재생"""
    import build_video as B
    from moviepy.editor import VideoClip
    n = len(entries)
    ends = list(starts[1:]) + [dur]

    def one(i, local, sd):
        e = entries[i]
        if e[0] == "vid":
            im = _vid_frame(e[1], local)
            if im is not None:
                return im
            return Image.new("RGB", (W, H), (20, 20, 30))
        return B.render_motion_frame(e[1], e[2], min(local / max(sd, 0.01), 1.0), zoom)

    def frame(t):
        i = n - 1
        for k in range(n):
            if t < ends[k]:
                i = k
                break
        sd = max(ends[i] - starts[i], 0.01)
        local = t - starts[i]
        xf = min(max(xfade, 0.0), sd * 0.4)
        cur = one(i, local, sd)
        if i > 0 and xf > 0 and local < xf:
            psd = max(ends[i - 1] - starts[i - 1], 0.01)
            prev = one(i - 1, (ends[i - 1] - starts[i - 1]) + local, psd)
            cur = Image.blend(prev, cur, B._smooth(local / xf))
        return np.asarray(cur, dtype=np.uint8)
    return VideoClip(frame, duration=dur).set_position((0, 0))


# ---------------------------------------------------------------- 항상 보이는 표시 (HUD)
def make_hud(no, total, country, channel, handle, av_path, credit):
    ys = np.arange(H)
    bottom = np.clip((ys - (H - 430)) / 430.0, 0, 1) ** 1.6 * 205
    top = np.clip((230 - ys) / 230.0, 0, 1) ** 1.4 * 150
    base = np.zeros((H, W, 4), np.uint8)
    base[..., 3] = np.maximum(bottom, top)[:, None].astype(np.uint8)
    im = Image.fromarray(base, "RGBA")
    d = ImageDraw.Draw(im)
    # 왼쪽 위: 번호 / 나라
    nf, sf, cf = font(60), font(34, False), font(46)
    d.ellipse((56, 44, 56 + 104, 44 + 104), fill=PURPLE)
    text_c(d, 56 + 52, 62, f"{no}", nf, "white")
    d.text((184, 54), f"/ {total}", font=sf, fill=(235, 235, 245), stroke_width=2, stroke_fill=(0, 0, 0))
    d.text((184, 94), _dc(country)[:24], font=cf, fill="white", stroke_width=3, stroke_fill=(0, 0, 0))
    # 오른쪽 위: 채널 (이름 / 주소 / 이미지를 각각 켜고 끄고, 문구도 바꿀 수 있음 - UI '채널 표시')
    if BRAND.get("hud", True):
        show_av = BRAND.get("hud_avatar", True)
        if BRAND.get("hud_text"):
            name = str(BRAND["hud_text"]).strip()
        else:
            name = "  ".join(x for x in (channel if BRAND.get("hud_name", True) else "", handle if BRAND.get("hud_handle", True) else "") if x).strip()
        f2 = font(30, False)
        tw = d.textlength(name, font=f2) if name else 0
        right = W - 56
        left = right - (64 if show_av else 0) - ((16 if show_av else 0) + tw if name else 0)
        if BRAND.get("hud_pill", True) and (name or show_av):
            rrect(im, (int(left) - 22, 40, right + 18, 128), 44, (8, 8, 14, 150))
            d = ImageDraw.Draw(im)
        if show_av:
            av = avatar(av_path, 64, channel)
            im.paste(av, (right - 64, 52), av)
        if name:
            d.text((left, 66), name, font=f2, fill=(255, 255, 255, 240), stroke_width=2, stroke_fill=(0, 0, 0))
    # 아래: 진행 막대 + 사진 출처
    d.rectangle((0, H - 8, W, H), fill=(255, 255, 255, 60))
    d.rectangle((0, H - 8, int(W * no / max(1, total)), H), fill=PURPLE)
    for k in range(1, total):
        xx = int(W * k / total)
        d.rectangle((xx - 1, H - 8, xx + 1, H), fill=(0, 0, 0, 160))
    if credit:
        f3 = font(22, False)
        c = str(credit)[:70]
        d.text((W - 56 - d.textlength(c, font=f3), H - 40), c, font=f3, fill=(255, 255, 255, 170))
    return im


def lower_third(title1, title2):
    layer = new_layer()
    d = ImageDraw.Draw(layer)
    f1, l1 = fit_lines(d, title1, 1000, 56, 36, 2)
    f2, l2 = fit_lines(d, title2, 1000, 56, 36, 2) if str(title2 or "").strip() else (None, [])
    h1 = sum(f1.getmetrics()[0] + f1.getmetrics()[1] + 6 for _ in l1)
    h2 = sum(f2.getmetrics()[0] + f2.getmetrics()[1] + 6 for _ in l2) if f2 else 0
    wmax = max([d.textlength(x, font=f1) for x in l1] + ([d.textlength(x, font=f2) for x in l2] if f2 else [0]))
    bh = h1 + h2 + 36
    y0 = H - 36 - CAP_IMG_H - 24 - bh
    rrect(layer, (60, y0, 60 + int(wmax) + 80, y0 + bh), 22, (10, 10, 16, 190))
    layer2 = ImageDraw.Draw(layer)
    layer2.rectangle((60, y0 + 14, 70, y0 + bh - 14), fill=PURPLE)
    y = y0 + 18
    for x in l1:
        layer2.text((96, y), x, font=f1, fill="white")
        y += f1.getmetrics()[0] + f1.getmetrics()[1] + 6
    for x in l2:
        layer2.text((96, y), x, font=f2, fill=YELLOW)
        y += f2.getmetrics()[0] + f2.getmetrics()[1] + 6
    return layer


# ---------------------------------------------------------------- 자막
_DRAW = ImageDraw.Draw(Image.new("RGB", (4, 4)))


def _wrap(text, f, width):
    lines, cur = [], ""
    for w in str(text).split():
        t = w if not cur else cur + " " + w
        if cur and _DRAW.textlength(t, font=f) > width:
            lines.append(cur)
            cur = w
        else:
            cur = t
    if cur:
        lines.append(cur)
    return lines


def wide_cues(timings, dur):
    """[(시작, 끝, 텍스트)] 문장을 2줄에 들어가는 조각으로 나눠 글자 수 비율로 시간 배분"""
    f = font(54)
    cues = []
    for t in timings:
        st, en = float(t["start"]), float(t["end"])
        text = str(t["text"]).strip()
        if en <= st or not text:
            continue
        chunks, cur = [], ""
        for w in text.split():
            trial = (cur + " " + w).strip()
            if cur and len(_wrap(trial, f, CAP_W)) > 2:
                chunks.append(cur)
                cur = w
            else:
                cur = trial
        if cur:
            chunks.append(cur)
        wts = [max(1, len(re.sub(r"\s+", "", c))) for c in chunks]
        total, acc = float(sum(wts)), 0.0
        for c, wt in zip(chunks, wts):
            a = st + (en - st) * acc / total
            acc += wt
            b = st + (en - st) * acc / total
            cues.append([a, b, c])
    out = []
    for k, c in enumerate(cues):
        nxt = cues[k + 1][0] if k + 1 < len(cues) else dur
        end = nxt if nxt - c[1] < 0.6 else min(nxt, c[1] + 0.4)
        end = min(max(end, c[0] + 0.8), dur)
        if end > c[0]:
            out.append((c[0], end, c[2]))
    return out


def caption_img(text):
    f = font(54)
    lines = _wrap(text, f, CAP_W)[:2] or [""]
    asc, desc = f.getmetrics()
    lh = asc + desc + 8
    tw = max(_DRAW.textlength(x, font=f) for x in lines)
    pw, ph = int(min(W - 120, tw + 90)), int(lh * len(lines) + 34)
    im = Image.new("RGBA", (W, CAP_IMG_H), (0, 0, 0, 0))
    x0, y0 = (W - pw) // 2, CAP_IMG_H - ph - 4
    rrect(im, (x0, y0, x0 + pw, y0 + ph), 26, (8, 8, 14, 170))
    d = ImageDraw.Draw(im)
    y = y0 + 17
    for x in lines:
        d.text(((W - _DRAW.textlength(x, font=f)) / 2, y), x, font=f, fill="white", stroke_width=3, stroke_fill=(0, 0, 0))
        y += lh
    return arr(im)


# ---------------------------------------------------------------- 키워드 / 비교 카드
def keyword_img(text):
    layer = new_layer()
    d = ImageDraw.Draw(layer)
    f, lines = fit_lines(d, text, 760, 104, 56, 2)
    asc, desc = f.getmetrics()
    lh = asc + desc + 6
    wmax = max(d.textlength(x, font=f) for x in lines)
    bw, bh = int(wmax) + 110, lh * len(lines) + 56
    x0, y0 = W - 90 - bw, 260
    rrect(layer, (x0, y0, x0 + bw, y0 + bh), 30, (10, 10, 16, 215))
    d.rounded_rectangle((x0, y0, x0 + 16, y0 + bh), radius=8, fill=YELLOW)
    y = y0 + 28
    for x in lines:
        d.text((x0 + 62, y), x, font=f, fill=YELLOW, stroke_width=2, stroke_fill=(0, 0, 0))
        y += lh
    return layer, (x0, y0)


def compare_imgs(cmp_):
    """비교 카드 단계별 이미지 [행 0개 ... 행 N개] (줄이 하나씩 나타나게)"""
    rows = cmp_["rows"][:3]
    stages = []
    for k in range(len(rows) + 1):
        layer = Image.new("RGBA", (W, H), (6, 6, 12, 205))
        d = ImageDraw.Draw(layer)
        tf = font(60)
        text_c(d, W // 2, 96, cmp_.get("title") or f"{cmp_['left']} vs {cmp_['right']}", tf, "white", 3)
        colw, gap = 640, 40
        lx, rx = 120, W - 120 - colw
        hf = font(70)
        rrect(layer, (lx, 200, lx + colw, 300), 24, PURPLE + (255,))
        rrect(layer, (rx, 200, rx + colw, 300), 24, YELLOW + (255,))
        d.text((lx + colw // 2, 250), cmp_["left"][:16], font=hf, fill="white", anchor="mm")
        d.text((rx + colw // 2, 250), cmp_["right"][:16], font=hf, fill=(20, 20, 20), anchor="mm")
        d.text((W // 2, 250), "VS", font=font(56), fill=(255, 255, 255), anchor="mm")
        y = 330
        for i, r in enumerate(rows[:k]):
            for x0, who in ((lx, "left"), (rx, "right")):
                rrect(layer, (x0, y, x0 + colw, y + 150), 24, (255, 255, 255, 235))
                f, ls = fit_lines(d, r[who], colw - 60, 54, 32, 2)
                asc, desc = f.getmetrics()
                step = asc + desc + 4
                yy = y + 75 - step * len(ls) / 2 + step / 2
                for x in ls:
                    d.text((x0 + colw // 2, yy), x, font=f, fill=(20, 20, 28), anchor="mm")
                    yy += step
            lf, ll = fit_lines(d, r["label"], 360, 40, 26, 1)
            rrect(layer, (W // 2 - 190, y + 40, W // 2 + 190, y + 110), 20, (10, 10, 16, 255))
            d.text((W // 2, y + 75), ll[0], font=lf, fill="white", anchor="mm")
            y += 170
        stages.append(layer)
    return stages


# ---------------------------------------------------------------- 챕터 카드 / 인트로 / 요약
def blurred(img, dark=0.55):
    b = img.filter(ImageFilter.GaussianBlur(26))
    return Image.blend(b, Image.new("RGB", b.size, (8, 8, 14)), dark)


def chapter_card(no, total, country, title1, title2, bg_img, out_path, seconds=2.6):
    from moviepy.editor import ImageClip
    im = blurred(bg_img).convert("RGBA")
    d = ImageDraw.Draw(im)
    cx = W // 2
    d.ellipse((cx - 110, 150, cx + 110, 370), fill=PURPLE)
    text_c(d, cx, 188, f"{no}", font(150), "white")
    text_c(d, cx, 410, f"{no} / {total}", font(46, False), (235, 235, 245))
    f, ls = fit_lines(d, _dc(country), 1500, 150, 80, 1)
    text_c(d, cx, 480, ls[0], f, "white", 4)
    y = 480 + f.getmetrics()[0] + f.getmetrics()[1] + 24
    for t, col in ((title1, (235, 235, 245)), (title2, YELLOW)):
        if str(t or "").strip():
            tf, tl = fit_lines(d, t, 1500, 62, 38, 1)
            text_c(d, cx, y, tl[0], tf, col, 2)
            y += tf.getmetrics()[0] + tf.getmetrics()[1] + 10
    # 챕터 점
    gap = min(64, 1300 // max(1, total))
    x0 = cx - gap * (total - 1) / 2
    for k in range(total):
        r = 14 if k + 1 == no else 8
        d.ellipse((x0 + k * gap - r, 940 - r, x0 + k * gap + r, 940 + r), fill=PURPLE if k + 1 <= no else (255, 255, 255, 110))
    clip = ImageClip(arr(im.convert("RGB"))).set_duration(seconds).fadein(0.3).fadeout(0.25)
    write_clip(clip.set_audio(silent(seconds)), out_path)
    close_all(clip)
    return seconds


def intro(title_lines, n, imgs, audio_path, channel, handle, av_path, out_path):
    from moviepy.editor import AudioFileClip, CompositeVideoClip, ImageClip
    audio = AudioFileClip(exact_audio(audio_path)) if audio_path and Path(audio_path).exists() else None
    dur = max(10.0, (audio.duration if audio else 0) + 1.5)
    k = max(1, min(len(imgs), int(dur // 1.4)))
    cut = dur / k
    srcs = [imgs[i % len(imgs)] for i in range(k)]
    bg = motion_clip(srcs, dur, starts=[i * cut for i in range(k)], zoom=0.14, xfade=0.35)
    shade = np.zeros((H, W, 4), np.uint8)
    shade[..., 3] = 150
    layer = Image.fromarray(shade, "RGBA")
    d = ImageDraw.Draw(layer)
    if BRAND.get("intro_logo", True):
        av = avatar(av_path, 110, channel)
        layer.paste(av, (W // 2 - 55, 90), av)
    if BRAND.get("intro_name", True) and channel:
        text_c(d, W // 2, 218, channel, font(42), "white", 2)
    y = 380
    for j, t in enumerate(title_lines):
        f, ls = fit_lines(d, t, W - 300, 120, 62, 2)
        for x in ls:
            text_c(d, W // 2, y, x, f, "white" if j == 0 else YELLOW, 5)
            y += f.getmetrics()[0] + f.getmetrics()[1] + 10
    rrect(layer, (W // 2 - 190, y + 40, W // 2 + 190, y + 130), 40, PURPLE + (255,))
    text_c(d, W // 2, y + 56, L["stories"](n), font(52), "white")
    title_clip = ImageClip(arr(layer)).set_duration(dur - 0.6).set_start(0.6).crossfadein(0.5)
    final = CompositeVideoClip([bg, title_clip], size=(W, H)).set_duration(dur)
    final = final.set_audio(padded_audio(audio, dur, 0.5) if audio else silent(dur))
    write_clip(final, out_path)
    close_all(final, audio) if audio else close_all(final)
    return dur


def recap_screen(items, bg_img, audio_path, channel, handle, av_path, out_path, cards=True):
    """items = [(번호, 나라, 한 줄 요약)]"""
    from moviepy.editor import AudioFileClip, CompositeVideoClip, ImageClip
    audio = AudioFileClip(exact_audio(audio_path)) if audio_path and Path(audio_path).exists() else None
    dur = max(10.0, (audio.duration if audio else 0) + 4.0)
    bg = ImageClip(arr(blurred(bg_img, 0.62))).set_duration(dur)
    n = len(items)
    two = n > 6
    per = max(1, (n + 1) // 2) if two else n
    colw = 840 if two else 1500
    lh = min(112, (800 // max(1, per)))
    clips = []
    head = new_layer()
    if cards:
        text_c(ImageDraw.Draw(head), W // 2, 70, L["recap"], font(86), "white", 3)
    else:   # 요약 카드 없이 엔딩 멘트만: 흐린 배경 + 채널 이름
        text_c(ImageDraw.Draw(head), W // 2, H // 2 - 70, str(channel or ""), font(96), "white", 3)
        if handle:
            text_c(ImageDraw.Draw(head), W // 2, H // 2 + 50, str(handle), font(52), "white", 2)
    clips.append(ImageClip(arr(head)).set_duration(dur).crossfadein(0.4))
    t_line = max(1.2, (dur - 6.0) / max(1, n))
    for i, (no, country, line) in enumerate(items if cards else []):
        col, row = (i // per, i % per) if two else (0, i)
        x0 = (W - 2 * colw - 60) // 2 + col * (colw + 60) if two else (W - colw) // 2
        y0 = 210 + row * lh
        layer = new_layer()
        d = ImageDraw.Draw(layer)
        rrect(layer, (x0, y0, x0 + colw, y0 + lh - 14), 24, (10, 10, 18, 215))
        d.ellipse((x0 + 14, y0 + (lh - 14) // 2 - 32, x0 + 78, y0 + (lh - 14) // 2 + 32), fill=PURPLE)
        text_c(d, x0 + 46, y0 + (lh - 14) // 2 - 24, str(no), font(44), "white")
        f, ls = fit_lines(d, f"{_dc(country)}  ·  {line}", colw - 130, 44, 26, 2, bold=False)
        asc, desc = f.getmetrics()
        yy = y0 + (lh - 14 - (asc + desc) * len(ls)) // 2
        for x in ls:
            d.text((x0 + 100, yy), x, font=f, fill="white")
            yy += asc + desc
        clips.append(ImageClip(arr(layer)).set_start(0.8 + i * t_line).set_duration(max(0.5, dur - 0.8 - i * t_line)).crossfadein(0.35))
    cta = str(BRAND.get("cta") or "").strip()      # 마지막 구독/좋아요 띠는 직접 문구를 넣었을 때만 표시
    if cta:
        end = new_layer()
        de = ImageDraw.Draw(end)
        rrect(end, (W // 2 - 420, 900, W // 2 + 420, 1010), 50, PURPLE + (255,))
        text_c(de, W // 2, 918, cta, font(46), "white")
        clips.append(ImageClip(arr(end)).set_start(max(0.5, dur - 4.5)).set_duration(4.5).crossfadein(0.4))
    final = CompositeVideoClip([bg] + clips, size=(W, H)).set_duration(dur).fadeout(0.5)
    final = final.set_audio(padded_audio(audio, dur, 0.4) if audio else silent(dur))
    write_clip(final, out_path)
    close_all(final, audio) if audio else close_all(final)
    return dur


# ---------------------------------------------------------------- 빠른 합성 (본편)
class Ov:
    """시간 구간 동안 프레임 위에 얹는 작은 RGBA 조각 (투명 부분은 잘라내 계산량을 줄임)"""
    def __init__(self, layer, s, e, x=0, y=0, fi=0.0, fo=0.0, slide=0):
        if not isinstance(layer, Image.Image):
            layer = Image.fromarray(layer, "RGBA")
        bb = layer.getchannel("A").getbbox()
        if bb is None:
            bb = (0, 0, 1, 1)
        crop = np.asarray(layer.crop(bb), dtype=np.float32)
        self.rgb, self.a = crop[..., :3], crop[..., 3:4] / 255.0
        self.x, self.y = x + bb[0], y + bb[1]
        self.h, self.w = crop.shape[:2]
        self.s, self.e, self.fi, self.fo, self.slide = s, e, fi, fo, slide

    def apply(self, frame, t):
        if not (self.s <= t < self.e):
            return
        k = 1.0
        if self.fi and t - self.s < self.fi:
            k = (t - self.s) / self.fi
        if self.fo and self.e - t < self.fo:
            k = min(k, (self.e - t) / self.fo)
        dx = int((1 - min((t - self.s) / 0.3, 1.0)) ** 2 * self.slide) if self.slide else 0
        x0, y0 = self.x + dx, self.y
        xa, xb = max(0, x0), min(W, x0 + self.w)
        ya, yb = max(0, y0), min(H, y0 + self.h)
        if xb <= xa or yb <= ya:
            return
        rgb = self.rgb[ya - y0:yb - y0, xa - x0:xb - x0]
        a = self.a[ya - y0:yb - y0, xa - x0:xb - x0] * k
        reg = frame[ya:yb, xa:xb].astype(np.float32)
        frame[ya:yb, xa:xb] = (reg * (1 - a) + rgb * a).astype(np.uint8)


def segment(idx, item, rec, no, total, out_path, channel, handle, av_path, burn=True):
    """rec: dict(narration, audio, timing, keywords, compare). -> (길이, 자막 조각 목록, 첫 사진)"""
    import build_video as B
    from moviepy.editor import AudioFileClip, VideoClip
    country = B.safe_country(item)
    narr, ap, tp = rec["narration"], Path(rec["audio"]), (Path(rec["timing"]) if rec.get("timing") else None)
    audio = AudioFileClip(exact_audio(ap))
    dur = float(audio.duration)
    paths = B.get_visual_paths(idx, item)
    srcs, real = load_sources(paths, country)
    timings = B.load_timings(tp, dur, narr)
    starts = B.scene_starts(narr, timings, dur, len(srcs))
    print(f"  [{no}/{total}] {idx} {country}: {dur:.1f}초, 이미지 {real}/{len(srcs)}장, 키워드 {len(rec.get('keywords') or [])}, 비교 {'O' if rec.get('compare') else 'X'}", flush=True)
    t1, t2 = B.split_title(item)
    if str(rec.get("title1") or "").strip() or str(rec.get("title2") or "").strip():
        t1, t2 = str(rec.get("title1") or "").strip(), str(rec.get("title2") or "").strip()
    credit = (B.credit_label(item) if real else "") or ""

    sents = [x for x in re.split(r"(?<=[.!?。！？])\s+|\n+", narr.strip()) if x.strip()]
    total_chars = sum(len(re.sub(r"\s+", "", x)) for x in sents) or 1
    cum = [0]
    for x in sents:
        cum.append(cum[-1] + len(re.sub(r"\s+", "", x)))

    def sent_time(n_):
        return 0.0 if n_ <= 1 else B.time_at_fraction(cum[n_ - 1] / total_chars, timings)

    if real < len(srcs):
        MISSING.append((idx, country, real, len(srcs)))
    clips = [c for c in (rec.get("clips") or []) if c.get("path") and Path(c["path"]).exists() and c.get("use", True) is not False]
    entries = [("img", srcs[i], i) for i in range(len(srcs))]
    starts_bg = list(starts[:len(srcs)])
    cues_img = [c for c in (rec.get("images") or []) if isinstance(c, dict)]
    if cues_img:      # 사람이 지정한 '이 문장부터 이 사진/영상' 큐
        seq = []
        for c in sorted(cues_img, key=lambda c: int(c.get("sentence", 1) or 1)):
            try:
                s_ = int(c.get("sentence", 1))
            except (TypeError, ValueError):
                continue
            if not 1 <= s_ <= len(sents):
                continue
            if c.get("clip"):
                k_ = int(c["clip"])
                if 1 <= k_ <= len(rec.get("clips") or []) and (rec["clips"][k_ - 1] or {}).get("path") and Path(rec["clips"][k_ - 1]["path"]).exists() \
                        and (rec["clips"][k_ - 1] or {}).get("use", True) is not False:
                    seq.append((sent_time(s_), ("vid", rec["clips"][k_ - 1]["path"])))
            elif c.get("scene"):
                k_ = int(c["scene"])
                if 1 <= k_ <= len(srcs):
                    seq.append((sent_time(s_), ("img", srcs[k_ - 1], k_ - 1)))
        if seq:
            if seq[0][0] > 0.05:
                seq.insert(0, (0.0, ("img", srcs[0], 0)))
            seq[0] = (0.0, seq[0][1])
            for i in range(1, len(seq)):
                seq[i] = (max(seq[i][0], seq[i - 1][0] + 1.6), seq[i][1])
            seq = [x for x in seq if x[0] < dur - 1.0] or seq[:1]
            starts_bg, entries = [t for t, _ in seq], [e for _, e in seq]
    elif clips:       # 스톡 영상: 자동 배치 (사진 장면 몇 개를 영상으로 바꿈)
        n_img = len(entries)
        for j, c in enumerate(clips[:3]):
            pos = min(n_img - 1, max(1, round((j + 1) * n_img / (min(len(clips), 3) + 1))))
            entries[pos] = ("vid", c["path"])
    if any(e[0] == "vid" for e in entries):
        bg = hybrid_bg(entries, dur, starts_bg)
    else:
        bg = motion_clip([e[1] for e in entries], dur, starts=starts_bg)

    # 항상 보이는 표시(위/아래 그라데이션 포함)는 위·아래 띠 영역만 계산한다
    hud = np.asarray(make_hud(no, total, country, channel, handle, av_path, credit), dtype=np.float32)
    bands = [(0, 250), (H - 450, H)]
    hud_rgb = [hud[a:b, :, :3] for a, b in bands]
    hud_a = [hud[a:b, :, 3:4] / 255.0 for a, b in bands]

    ovs = [Ov(lower_third(t1, t2), 0.6, 0.6 + min(6.0, max(2.0, dur - 1)), fi=0.4, fo=0.4)]
    cmp_win = None
    cmp_ = rec.get("compare")
    if cmp_ and len(cmp_.get("rows") or []) >= 2 and dur > 25:
        t0 = B.time_at_fraction(0.55, timings)
        try:
            if int(rec.get("compare_at") or 0) >= 1:
                t0 = sent_time(min(int(rec["compare_at"]), len(sents)))
        except (TypeError, ValueError):
            pass
        cd = min(8.0, max(5.0, 2.2 * len(cmp_["rows"]) + 1.5))
        t0 = max(8.0, min(t0, dur - cd - 3.0))
        cmp_win = (t0, t0 + cd)
        stages = compare_imgs(cmp_)
        times = [t0] + [t0 + 0.8 + 1.1 * k for k in range(len(stages) - 1)]
        for k, st_ in enumerate(stages):
            e_ = times[k + 1] if k + 1 < len(stages) else t0 + cd
            ovs.append(Ov(st_, times[k], e_, fi=0.4 if k == 0 else 0.0, fo=0.4 if k == len(stages) - 1 else 0.0))

    last_end = 0.0
    for kw in sorted(rec.get("keywords") or [], key=lambda k: k["sentence"]):
        n_ = int(kw["sentence"])
        if not (1 <= n_ <= len(sents)):
            continue
        t0 = B.time_at_fraction(cum[n_ - 1] / total_chars, timings) + 0.25
        if t0 < last_end + 0.4 or t0 > dur - 2.0:
            continue
        if cmp_win and cmp_win[0] - 1.0 < t0 < cmp_win[1] + 0.3:
            continue
        layer, _pos = keyword_img(kw["text"])
        kd = min(2.8, dur - t0 - 0.2)
        ovs.append(Ov(layer, t0, t0 + kd, fi=0.25, fo=0.3, slide=90))
        last_end = t0 + kd

    cues = wide_cues(timings, dur)
    cap_y = H - 36 - CAP_IMG_H
    if burn:
        for a, b, text in cues:
            ovs.append(Ov(Image.fromarray(caption_img(text), "RGBA"), a, b, y=cap_y))

    def make_frame(t):
        t = min(t, max(0.0, dur - 1e-3))
        fr = bg.get_frame(t).copy()
        for (a0, b0), rgb, al in zip(bands, hud_rgb, hud_a):
            reg = fr[a0:b0].astype(np.float32)
            fr[a0:b0] = (reg * (1 - al) + rgb * al).astype(np.uint8)
        for o in ovs:
            o.apply(fr, t)
        return fr

    final = VideoClip(make_frame, duration=dur).set_audio(audio)
    write_clip(final, out_path)
    close_all(final, audio)
    close_videos()
    return dur, cues, srcs[0]
