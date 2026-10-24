# -*- coding: utf-8 -*-
"""쇼츠 여러 개를 묶어 가로(16:9) 롱폼 영상 1개로 만든다. (쇼츠 영상을 이어 붙이는 게 아니라 같은 재료로 새로 합성)

- 소재 선택: --mode auto (영상이 끝난 소재 중 아직 롱폼에 안 쓴 것을 번호순으로 / --theme 으로 분야 지정)
             --mode manual --indexes "109,110,115-118"
- 개수 제한: 3~30개 (--min/--max), 전체 예상 길이 40분 이하
- 음성/이미지는 소재마다 다시 만든다(Actions에는 예전 파일이 없으므로). facts_db.json 은 바꾸지 않아도 되고 커밋하지 않는다.
- 결과: longform_out/longform_<번호>.mp4 / .png(썸네일) / .txt(제목+설명+챕터), 기록은 longform_db.json (쇼츠 DB와 별도)
"""
import argparse
from scenes import item_scene_count
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps

BASE = Path(__file__).resolve().parent
LF_DB = BASE / "longform_db.json"
OUT = BASE / "longform_out"
WORK = BASE / "longform_work"
W, H = 1920, 1080
FPS = 30
BOX = (60, 40)                 # 이미지 박스 왼쪽 위 (1000x1000)
PANEL_X = 1120                 # 오른쪽 패널 시작 x
PANEL_W = W - PANEL_X - 60
BG = (250, 250, 252)
COLOR2 = (200, 0, 255)
MIN_N, MAX_N, MAX_MIN = 3, 30, 40   # 개수 3~30, 예상 길이 40분 이하
IS_EN = (BASE / "generate_topics.py").exists()


# ---------------------------------------------------------------- 선택
def load_json(path, default):
    if Path(path).exists():
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return default


def parse_indexes(text):
    out = []
    for part in re.split(r"[,\s]+", str(text or "").strip()):
        if not part:
            continue
        m = re.fullmatch(r"(\d+)-(\d+)", part)
        if m:
            a, b = int(m.group(1)), int(m.group(2))
            out.extend(range(min(a, b), max(a, b) + 1))
        elif part.isdigit():
            out.append(int(part))
        else:
            raise SystemExit(f"번호 형식 오류: '{part}' (예: 109,110,115-118)")
    seen, uniq = set(), []
    for i in out:
        if i not in seen:
            seen.add(i)
            uniq.append(i)
    return uniq


EST_SCALE = 1.0   # 롱폼 확장 대본은 쇼츠보다 길어서(약 2배) 길이 예상에 곱한다


def est_seconds(item):
    return _est_seconds(item) * EST_SCALE


def _est_seconds(item):
    # 음성이 이미 만들어져 있으면 실제 길이(타이밍 파일의 마지막 문장 끝)를 사용
    try:
        tp = item.get("timing_path_v2")
        if tp and os.path.exists(tp):
            sents = json.load(open(tp, encoding="utf-8")).get("sentences") or []
            if sents:
                return float(sents[-1]["end"]) + 0.5
    except Exception:
        pass
    n = len(re.sub(r"\s+", "", str(item.get("narration", ""))))
    return n / (6.0 if not IS_EN else 13.0)   # 한국어 약 6자/초, 영어 약 13자/초(공백 제외)


def used_indexes(lf_db):
    return {i for rec in lf_db for i in rec.get("members", [])}


def select_members(db, lf_db, mode, indexes, theme, count, start, lo, hi):
    if mode == "manual":
        idxs = parse_indexes(indexes)
        if not idxs:
            raise SystemExit("manual 모드는 번호(indexes)가 필요합니다. 예: 109,110,115-118")
        for i in idxs:
            if not (0 <= i < len(db)) or not str(db[i].get("narration", "")).strip():
                raise SystemExit(f"{i}번 소재가 없거나 대본이 없습니다.")
            if db[i].get("status") == "rejected":
                raise SystemExit(f"{i}번은 폐기(rejected)된 소재입니다.")
        if not (lo <= len(idxs) <= hi):
            raise SystemExit(f"한 번에 {lo}~{hi}개만 묶을 수 있습니다. (입력 {len(idxs)}개)")
        total = sum(est_seconds(db[i]) for i in idxs)
        if total > MAX_MIN * 60:
            raise SystemExit(f"예상 길이 {total / 60:.0f}분이 너무 깁니다 (최대 {MAX_MIN}분). 개수를 줄여 주세요.")
        return idxs

    count = max(lo, min(hi, int(count)))
    used = used_indexes(lf_db)
    pool = [i for i, f in enumerate(db)
            if i >= start and f.get("status") == "video_done" and str(f.get("narration", "")).strip() and i not in used]
    if theme:
        t = theme.strip().lower()
        pool = [i for i in pool if t in str(db[i].get("theme", "")).lower()
                or t in str(db[i].get("topic", "")).lower() or t in str(db[i].get("country", "")).lower()]
    chosen, total = [], 0.0
    for i in pool:
        s = est_seconds(db[i])
        if total + s > MAX_MIN * 60:
            break
        chosen.append(i)
        total += s
        if len(chosen) >= count:
            break
    if len(chosen) < lo:
        raise SystemExit(f"조건에 맞는 소재가 {len(chosen)}개뿐입니다 (최소 {lo}개 필요). "
                         f"영상이 끝나고 롱폼에 안 쓴 소재가 더 필요하거나 theme/start_index를 바꿔 주세요.")
    return chosen


def subtitles_mode():
    import subtitles
    return subtitles.caption_mode()


# ---------------------------------------------------------------- 재료 준비
def run_py(*args):
    print("  $ python", " ".join(args), flush=True)
    r = subprocess.run([sys.executable, *args], cwd=BASE)
    return r.returncode == 0


def prepare_assets(idx):
    """음성 + 이미지를 (다시) 만든다. 이미 있으면 각 스크립트가 알아서 건너뜀/재사용."""
    # 대본을 고쳐서 이미지 검색어가 지워진 소재는 새 대본 기준으로 검색어를 다시 만든다 (이미 있으면 그대로)
    run_py("generate_script.py", "--extras-only", "--index", str(idx))
    ok = run_py("generate_tts.py", "--index", str(idx))
    run_py("fetch_images.py", "--index", str(idx))   # 키가 없으면 대체 카드로 진행
    return ok


# ---------------------------------------------------------------- 화면 조각
def _font(size, bold=True):
    import build_video as B
    fp = B.find_font(size, bold=bold)
    return ImageFont.truetype(fp, size) if fp else ImageFont.load_default()


def _wrap_fit(draw, text, width, start, min_size=44, max_lines=3):
    for size in range(start, min_size - 1, -2):
        f = _font(size)
        lines, cur = [], ""
        for w in str(text).split():
            t = w if not cur else cur + " " + w
            if cur and draw.textlength(t, font=f) > width:
                lines.append(cur)
                cur = w
            else:
                cur = t
        if cur:
            lines.append(cur)
        if len(lines) <= max_lines and all(draw.textlength(l, font=f) <= width for l in lines):
            return f, lines
    f = _font(min_size)
    return f, [str(text)]


def _avatar(path, size):
    if path and os.path.exists(path):
        im = ImageOps.fit(Image.open(path).convert("RGB"), (size, size))
    else:
        im = Image.new("RGB", (size, size), (60, 90, 200))
    mask = Image.new("L", (size * 4, size * 4), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size * 4 - 1, size * 4 - 1), fill=255)
    out = im.convert("RGBA")
    out.putalpha(mask.resize((size, size), Image.Resampling.LANCZOS))
    return out


def segment_background(no, total, title1, title2, country, credit, channel, handle, avatar):
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    x0 = PANEL_X
    img.paste(_avatar(avatar, 96), (x0, 48), _avatar(avatar, 96))
    d.text((x0 + 116, 52), channel, font=_font(40), fill=(20, 20, 20))
    d.text((x0 + 116, 100), handle, font=_font(30, bold=False), fill=(110, 110, 120))
    # 번호 배지
    d.ellipse((x0, 220, x0 + 120, 340), fill=COLOR2)
    nf = _font(72)
    tw = d.textlength(str(no), font=nf)
    d.text((x0 + 60 - tw / 2, 236), str(no), font=nf, fill="white")
    d.text((x0 + 140, 262), f"/ {total}", font=_font(44, bold=False), fill=(120, 120, 130))
    # 제목 (1줄 검정, 2줄 강조색)
    y = 400
    for text, color in ((title1, (0, 0, 0)), (title2, COLOR2)):
        if not str(text or "").strip():
            continue
        f, lines = _wrap_fit(d, text, PANEL_W, 76, 46, 3)
        asc, desc = f.getmetrics()
        for l in lines:
            d.text((x0, y), l, font=f, fill=color)
            y += asc + desc + 8
        y += 16
    d.text((x0, H - 150), country, font=_font(40), fill=(60, 60, 70))
    if credit:
        d.text((x0, H - 90), credit[:60], font=_font(28, bold=False), fill=(130, 130, 140))
    return img


SEG_CUES = {}   # 구간 번호 -> 자막 조각 (롱폼 SRT 만들 때 사용)


def build_segment(idx, item, no, total, out_path, channel, handle, avatar):
    import build_video as B
    import subtitles
    from moviepy.editor import AudioFileClip, CompositeVideoClip, ImageClip
    from layout import make_corner_overlay

    country = B.safe_country(item)
    audio_path = B.get_audio_path(item, idx)
    if not audio_path:
        raise FileNotFoundError(f"오디오 없음: {idx}")
    srcs, real = B.load_scene_sources(B.get_visual_paths(idx, item), country, str(item.get("topic") or ""))
    audio = AudioFileClip(str(audio_path))
    dur = float(audio.duration)
    script = item.get("narration") or ""
    timings = B.load_timings(B.get_timing_path(item, idx), dur, script)
    starts = B.scene_starts(script, timings, dur, item_scene_count(item))
    n_scenes = len(starts)
    srcs = srcs[:n_scenes]
    print(f"  [{no}/{total}] {idx} {country}: {dur:.1f}초, 이미지 {real}/{item_scene_count(item)}장", flush=True)

    t1, t2 = B.split_title(item)
    credit = (B.credit_label(item) if real else "") or ""
    bg = ImageClip(np.array(segment_background(no, total, t1, t2, country, credit, channel, handle, avatar))).set_duration(dur)
    scene = B.make_image_box_clip(srcs, dur, starts=starts).set_position(BOX)
    corner = ImageClip(np.array(make_corner_overlay())).set_duration(dur).set_position(BOX)

    caps = []
    stats = [subtitles.region_stats(im) for im in srcs]
    cap_y = BOX[1] + 1000 - subtitles.CAP_H - 18
    cues = subtitles.make_cues(timings, dur)
    SEG_CUES[no] = cues
    for st, en, text in (cues if subtitles.caption_mode() != "srt" else []):   # 롱폼은 핵심 문구 방식이 없어 highlight도 대본 자막으로
        idxs = [k for k in range(n_scenes) if starts[k] < en and (k == n_scenes - 1 or starts[k + 1] > st)] or [0]
        luma = max(stats[k][0] for k in idxs)
        std = max(stats[k][1] for k in idxs)
        caps.append(ImageClip(subtitles.render_caption(text, luma, std)).set_start(st).set_duration(en - st)
                    .set_position((BOX[0], cap_y)))
    final = CompositeVideoClip([bg, scene, corner] + caps, size=(W, H)).set_duration(dur).set_audio(audio)
    write_clip(final, out_path)
    for c in (final, audio):
        try:
            c.close()
        except Exception:
            pass
    return dur


def write_clip(clip, path):
    clip.write_videofile(
        str(path), fps=FPS, codec="libx264", audio_codec="aac", audio_fps=44100, preset="medium", threads=4,
        ffmpeg_params=["-pix_fmt", "yuv420p", "-ac", "2"], logger=None,
    )


def build_intro(title_lines, subtitle, out_path, channel, handle, avatar, seconds=3.0):
    from moviepy.editor import AudioClip, ImageClip
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    av = _avatar(avatar, 120)
    img.paste(av, (W // 2 - 60, 150), av)
    cf = _font(44)
    tw = d.textlength(channel, font=cf)
    d.text((W // 2 - tw / 2, 290), channel, font=cf, fill=(20, 20, 20))
    y = 400
    for k, text in enumerate(title_lines):
        f, lines = _wrap_fit(d, text, W - 240, 96, 56, 2)
        asc, desc = f.getmetrics()
        for l in lines:
            tw = d.textlength(l, font=f)
            d.text((W // 2 - tw / 2, y), l, font=f, fill=(0, 0, 0) if k == 0 else COLOR2)
            y += asc + desc + 10
        y += 20
    if subtitle:
        sf = _font(44, bold=False)
        tw = d.textlength(subtitle, font=sf)
        d.text((W // 2 - tw / 2, y + 30), subtitle, font=sf, fill=(110, 110, 120))
    clip = ImageClip(np.array(img)).set_duration(seconds)
    silent = AudioClip(lambda t: np.zeros((np.size(t), 2)) if np.ndim(t) else np.zeros(2), duration=seconds, fps=44100)
    write_clip(clip.set_audio(silent), out_path)
    return seconds


def concat(parts, out_path):
    exe = shutil.which("ffmpeg")
    if not exe:
        import imageio_ffmpeg
        exe = imageio_ffmpeg.get_ffmpeg_exe()
    lst = WORK / "list.txt"
    lst.write_text("".join(f"file '{Path(p).resolve().as_posix()}'\n" for p in parts), encoding="utf-8")
    cmd = [exe, "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy",
           "-movflags", "+faststart", str(out_path)]
    r = subprocess.run(cmd)
    if r.returncode != 0:
        raise RuntimeError("ffmpeg concat 실패")


# ---------------------------------------------------------------- 제목/설명/썸네일
def fmt_time(sec):
    sec = int(round(sec))
    return f"{sec // 60:02d}:{sec % 60:02d}" if sec < 3600 else f"{sec // 3600}:{(sec % 3600) // 60:02d}:{sec % 60:02d}"


def make_title(db, members, theme, custom):
    if custom:
        return custom.strip()[:95]
    n = len(members)
    first = str(db[members[0]].get("country", "")).strip()
    if IS_EN:
        base = f"{n} {theme.title() + ' ' if theme else ''}Korean Culture Facts That Surprise Foreigners"
    elif theme:
        base = f"세계의 {theme} {n}가지 | {first} 외"
    else:
        base = f"세계 문화 상식 {n}가지 | {first}부터 {str(db[members[-1]].get('country', '')).strip()}까지"
    return base[:95]


def make_description(db, members, durations, intro_len, title, extra=None):
    import common
    lines = []
    t = intro_len
    chapters = [("00:00", "Intro" if IS_EN else "오프닝")]
    for no, (idx, dur) in enumerate(zip(members, durations), start=1):
        it = db[idx]
        t1, t2 = (it.get("title_line1") or "", it.get("title_line2") or "")
        name = f"{no}. {str(it.get('country', '')).strip()} - {(t1 + ' ' + t2).strip() or it.get('topic', '')}"
        chapters.append((fmt_time(t), name[:90]))
        t += dur
    for et, en_ in (extra or []):
        chapters.append((fmt_time(et), en_))
    lines.append("\n".join(f"{a} {b}" for a, b in chapters))
    credits, seen = [], set()
    for idx in members:
        for l in common.image_credit_lines(db[idx]):
            if l not in seen:
                seen.add(l)
                credits.append(l)
    if credits:
        lines.append("\n".join(credits))
    lines.append(common.CHANNEL_BLURB)
    tags = []
    for idx in members:
        for tg in common.youtube_tags(db[idx])[:2]:
            if tg not in tags:
                tags.append(tg)
    lines.append(" ".join("#" + x for x in (tags[:10] + list(common.FIXED_TAGS)[:3])))
    return "\n\n".join(lines)


def make_thumbnail(db, members, title, out_path):
    import build_video as B
    it = db[members[0]]
    paths = B.get_visual_paths(members[0], it)
    base = None
    for p in paths:
        if Path(p).exists():
            base = Image.open(p).convert("RGB")
            break
    if base is None:
        base = Image.new("RGB", (1280, 720), (60, 90, 200))
    base = ImageOps.fit(base, (1280, 720), Image.Resampling.LANCZOS, centering=(0.5, 0.4))
    shade = Image.new("RGBA", (1280, 720), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shade)
    for y in range(720):
        sd.line((0, y, 1280, y), fill=(0, 0, 0, int(170 * (y / 720) ** 1.5)))
    base = Image.alpha_composite(base.convert("RGBA"), shade)
    d = ImageDraw.Draw(base)
    f, lines = _wrap_fit(d, title.split("|")[0].strip(), 1160, 104, 56, 3)
    asc, desc = f.getmetrics()
    y = 720 - 40 - (asc + desc + 8) * len(lines)
    for l in lines:
        tw = d.textlength(l, font=f)
        d.text(((1280 - tw) / 2, y), l, font=f, fill=(255, 226, 0), stroke_width=8, stroke_fill=(0, 0, 0))
        y += asc + desc + 8
    base.convert("RGB").save(out_path)


# ---------------------------------------------------------------- 새 화면(rich) 파이프라인
def _next_info(db, members, k):
    if k + 1 >= len(members):
        return None
    it = db[members[k + 1]]
    return str(it.get("topic") or it.get("title_line1") or it.get("country") or "") if IS_EN else str(it.get("country") or "")


def run_rich(args, db, lf_db, members):
    import longform_render as R
    import longform_script as LS
    import build_video as B
    import subtitles as _sub
    OUT.mkdir(exist_ok=True)
    WORK.mkdir(exist_ok=True)
    t0 = time.time()
    client = models = None
    if args.no_expand:
        print("확장 대본 사용 안 함 (--no-expand): 쇼츠 대본과 음성을 그대로 사용합니다", flush=True)
    elif LS.enabled():
        try:
            client, models = LS.client_models()
        except Exception as e:
            print(f"AI 연결 실패 -> 쇼츠 대본으로 대신합니다 ({type(e).__name__}: {e})", flush=True)
    else:
        print("GROQ_API_KEY가 없거나 LF_EXPAND=0 -> 쇼츠 대본으로 대신합니다", flush=True)

    # 1) 이미지 + 확장 대본 + 음성
    recs, countries_all = {}, [str(db[i].get("country", "")).strip() for i in members]
    for k, idx in enumerate(members):
        print(f"\n== 재료 준비 {idx} {db[idx].get('country', '')}", flush=True)
        run_py("generate_script.py", "--extras-only", "--index", str(idx))
        run_py("fetch_images.py", "--index", str(idx))
        db = load_json(BASE / "facts_db.json", db)
        item = db[idx]
        rec = None
        if client:
            me = str(item.get("country", "")).strip()
            cands = (LS.EN_PARTNERS if IS_EN else [c for c in dict.fromkeys(countries_all) if c and c != me] + ([] if me == "한국" else ["한국"]))
            try:
                rec = LS.prepare_item(client, models, idx, item, _next_info(db, members, k), cands, force=args.regen)
            except Exception as e:
                print(f"  확장 대본 실패 ({type(e).__name__}: {e})", flush=True)
        if rec is None:
            if client:
                print("  확장 대본을 만들지 못해 이 소재는 쇼츠 대본으로 대신합니다", flush=True)
            if not run_py("generate_tts.py", "--index", str(idx)):
                pass
            db = load_json(BASE / "facts_db.json", db)
            item = db[idx]
            ap_ = item.get("audio_path_v2")
            if ap_ and Path(ap_).exists():
                rec = {"narration": item.get("narration", ""), "audio": ap_, "timing": item.get("timing_path_v2"),
                       "keywords": [], "compare": None,
                       "recap": (str(item.get("title_line1", "")) + " " + str(item.get("title_line2", ""))).strip()}
        if rec:
            recs[idx] = rec
        else:
            print(f"  !! {idx}: 음성이 없어 롱폼에서 제외합니다", flush=True)
    members = [i for i in members if i in recs]
    if len(members) < args.min:
        raise SystemExit(f"준비된 소재가 {len(members)}개뿐이라 롱폼을 만들 수 없습니다 (최소 {args.min}개).")
    total = len(members)
    countries = [str(db[i].get("country", "")).strip() for i in members]

    lf_id = (max([r.get("id", 0) for r in lf_db] or [0])) + 1
    title = make_title(db, members, args.theme, args.title)
    burn = _sub.caption_mode() != "srt"

    # 2) 인트로 (사진 몽타주 + 소개 음성)
    imgs = []
    for layer_n in range(3):
        for idx in members:
            paths = B.get_visual_paths(idx, db[idx])
            if layer_n < len(paths) and Path(paths[layer_n]).exists():
                try:
                    imgs.append(R.load_sources([paths[layer_n]], "")[0][0])
                except Exception:
                    pass
    if not imgs:
        imgs = [R.placeholder(0, countries[0])]
    intro_rec = LS.prepare_extra("lf_intro", LS.intro_text(countries, total, [str(((recs[i].get("compare") or {}).get("right") or "")) for i in members])) if (client or LS.enabled()) and not args.no_expand else None
    parts, durs, seg_cues = [], [], {}
    intro_path = WORK / "seg_00_intro.mp4"
    intro_len = R.intro([title.split("|")[0].strip()], total, imgs, (intro_rec or {}).get("audio"), args.channel, args.handle, args.avatar, intro_path)
    parts.append(intro_path)

    # 3) 챕터 카드 + 본편
    t_acc = intro_len
    chapter_starts, bg_last = [], imgs[0]
    for no, idx in enumerate(members, start=1):
        item = db[idx]
        t1, t2 = B.split_title(item)
        cp = WORK / f"seg_{no:02d}_card.mp4"
        sp = WORK / f"seg_{no:02d}.mp4"
        card_len = R.chapter_card(no, total, B.safe_country(item), t1, t2, imgs[(no - 1) % len(imgs)], cp)
        dur, cues, first_img = R.segment(idx, item, recs[idx], no, total, sp, args.channel, args.handle, args.avatar, burn=burn)
        bg_last = first_img
        parts += [cp, sp]
        durs.append(card_len + dur)
        seg_cues[no] = (t_acc + card_len, cues)
        t_acc += card_len + dur

    # 4) 요약 + 엔딩
    items = [(no, countries[no - 1], recs[idx].get("recap") or str(db[idx].get("topic", ""))) for no, idx in enumerate(members, start=1)]
    out_rec = LS.prepare_extra("lf_outro", LS.outro_text([x[2] for x in items])) if (client or LS.enabled()) and not args.no_expand else None
    rp = WORK / "seg_99_recap.mp4"
    recap_len = R.recap_screen(items, bg_last, (out_rec or {}).get("audio"), args.channel, args.handle, args.avatar, rp)
    parts.append(rp)
    recap_start = t_acc

    # 5) 합치기 + 설명/썸네일/자막
    out_mp4 = OUT / f"longform_{lf_id:03d}.mp4"
    concat(parts, out_mp4)
    desc = make_description(db, members, durs, intro_len, title, extra=[(recap_start, "요약" if not IS_EN else "Recap")])
    (OUT / f"longform_{lf_id:03d}.txt").write_text(f"{title}\n\n{desc}\n", encoding="utf-8")
    make_thumbnail(db, members, title, OUT / f"longform_{lf_id:03d}.png")
    chunks, n_no = [], 1
    for no in sorted(seg_cues):
        off, cs = seg_cues[no]
        chunks.append("\n".join(f"{n_no + k}\n{_sub._srt_time(a_ + off)} --> {_sub._srt_time(b_ + off)}\n{tx}\n" for k, (a_, b_, tx) in enumerate(cs)))
        n_no += len(cs)
    (OUT / f"longform_{lf_id:03d}.srt").write_text("\n".join(c for c in chunks if c), encoding="utf-8")
    total_len = intro_len + sum(durs) + recap_len
    lf_db.append({
        "id": lf_id, "mode": args.mode, "theme": args.theme, "members": members, "title": title, "style": "rich",
        "expanded": bool(client), "description": desc, "duration_sec": round(total_len, 1),
        "video": str(out_mp4.name), "status": "video_done", "created_at": datetime.now(timezone.utc).isoformat(),
    })
    with open(LF_DB, "w", encoding="utf-8") as f:
        json.dump(lf_db, f, ensure_ascii=False, indent=2)
    shutil.rmtree(WORK, ignore_errors=True)
    print(f"\n완료: {out_mp4} ({total_len / 60:.1f}분, {time.time() - t0:.0f}초 걸림)")
    print(f"제목: {title}")


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description="쇼츠를 묶어 가로 롱폼 만들기")
    ap.add_argument("--mode", choices=["auto", "manual"], default="auto")
    ap.add_argument("--indexes", default="", help="manual: 소재 번호 (예: 109,110,115-118)")
    ap.add_argument("--theme", default="", help="auto: 분야/주제/나라 키워드 (비우면 번호순)")
    ap.add_argument("--count", type=int, default=6, help="auto: 묶을 개수")
    ap.add_argument("--start", type=int, default=0, help="auto: 이 번호 이상만 후보")
    ap.add_argument("--title", default="", help="제목 직접 지정 (비우면 자동)")
    ap.add_argument("--min", type=int, default=MIN_N)
    ap.add_argument("--max", type=int, default=MAX_N)
    ap.add_argument("--channel", default="채널명")
    ap.add_argument("--handle", default="@handle")
    ap.add_argument("--avatar", default="avatar.png")
    ap.add_argument("--style", choices=["rich", "classic"], default=os.environ.get("LF_STYLE", "rich"),
                    help="rich: 풀스크린 사진+챕터 카드+키워드+비교 카드+인트로/요약 (기본) / classic: 예전 화면(오른쪽 흰 패널)")
    ap.add_argument("--no-expand", action="store_true", help="rich 인데 확장 대본을 쓰지 않고 쇼츠 대본/음성을 그대로 사용")
    ap.add_argument("--regen", action="store_true", help="저장된 확장 대본이 있어도 다시 만든다")
    ap.add_argument("--dry-run", action="store_true", help="고른 소재만 보여주고 끝")
    args = ap.parse_args()
    global EST_SCALE
    if args.style == "rich" and not args.no_expand and os.environ.get("GROQ_API_KEY", "").strip() and os.environ.get("LF_EXPAND", "1") != "0":
        EST_SCALE = 2.2

    db = load_json(BASE / "facts_db.json", [])
    lf_db = load_json(LF_DB, [])
    members = select_members(db, lf_db, args.mode, args.indexes, args.theme, args.count, args.start,
                             args.min, args.max)
    total_est = sum(est_seconds(db[i]) for i in members)
    print(f"롱폼 소재 {len(members)}개 (예상 약 {total_est / 60:.1f}분): " +
          ", ".join(f"{i} {db[i].get('country', '')}" for i in members), flush=True)
    if args.dry_run:
        return
    if args.style == "rich":
        return run_rich(args, db, lf_db, members)

    OUT.mkdir(exist_ok=True)
    WORK.mkdir(exist_ok=True)
    t0 = time.time()
    # 1) 재료 (음성/이미지) 다시 만들기
    ready = []
    for idx in members:
        print(f"\n== 재료 준비 {idx} {db[idx].get('country', '')}", flush=True)
        prepare_assets(idx)
        db = load_json(BASE / "facts_db.json", db)   # 자식 프로세스가 갱신한 경로 반영
        ap_ = db[idx].get("audio_path_v2")
        if ap_ and Path(ap_).exists():
            ready.append(idx)
        else:
            print(f"  !! {idx}: 음성이 없어 롱폼에서 제외합니다")
    if len(ready) < args.min:
        raise SystemExit(f"음성이 준비된 소재가 {len(ready)}개뿐이라 롱폼을 만들 수 없습니다 (최소 {args.min}개).")
    members = ready

    # 2) 조각 영상
    lf_id = (max([r.get("id", 0) for r in lf_db] or [0])) + 1
    title = make_title(db, members, args.theme, args.title)
    parts, durations = [], []
    intro_path = WORK / "seg_00_intro.mp4"
    sub = (f"{len(members)} stories" if IS_EN else f"{len(members)}가지 이야기")
    intro_len = build_intro([title.split("|")[0].strip()], sub, intro_path, args.channel, args.handle, args.avatar)
    parts.append(intro_path)
    for no, idx in enumerate(members, start=1):
        p = WORK / f"seg_{no:02d}.mp4"
        durations.append(build_segment(idx, db[idx], no, len(members), p, args.channel, args.handle, args.avatar))
        parts.append(p)

    # 3) 이어 붙이기 + 제목/설명/썸네일
    out_mp4 = OUT / f"longform_{lf_id:03d}.mp4"
    concat(parts, out_mp4)
    desc = make_description(db, members, durations, intro_len, title)
    (OUT / f"longform_{lf_id:03d}.txt").write_text(f"{title}\n\n{desc}\n", encoding="utf-8")
    make_thumbnail(db, members, title, OUT / f"longform_{lf_id:03d}.png")
    if True:
        import subtitles as _sub
        t_off, n_no, chunks = intro_len, 1, []
        for no, dur in enumerate(durations, start=1):
            cs = SEG_CUES.get(no, [])
            chunks.append(_sub.to_srt(cs, offset=t_off, start_no=n_no))
            n_no += len(cs)
            t_off += dur
        (OUT / f"longform_{lf_id:03d}.srt").write_text("\n".join(c for c in chunks if c), encoding="utf-8")
        print(f"자막 파일(SRT): longform_{lf_id:03d}.srt")

    lf_db.append({
        "id": lf_id, "mode": args.mode, "theme": args.theme, "members": members, "title": title,
        "description": desc, "duration_sec": round(intro_len + sum(durations), 1),
        "video": str(out_mp4.name), "status": "video_done",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    with open(LF_DB, "w", encoding="utf-8") as f:
        json.dump(lf_db, f, ensure_ascii=False, indent=2)
    shutil.rmtree(WORK, ignore_errors=True)
    print(f"\n완료: {out_mp4} ({(intro_len + sum(durations)) / 60:.1f}분, {time.time() - t0:.0f}초 걸림)")
    print(f"제목: {title}")


if __name__ == "__main__":
    main()
