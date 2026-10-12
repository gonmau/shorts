# -*- coding: utf-8 -*-
"""Edge TTS가 막혔을 때(403 등) 쓰는 대체 음성: gTTS(구글 번역 음성).

문장별로 합성 -> 속도 조절 -> 이어 붙이고, 문장 길이로 타이밍(boundaries)을 만든다.
"""
import re
import shutil
import subprocess
import time
from pathlib import Path

from common import split_sentences


def lang_from_voice(voice):
    return (voice or "en-US").split("-")[0].lower() or "en"


def speed_from_rate(rate):
    m = re.match(r"^([+-]?\d+)%$", str(rate or "").strip())
    pct = int(m.group(1)) if m else 0
    return max(0.8, min(1.3, 1 + pct / 100))


def _run(cmd):
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _duration(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    return float(out)


def synthesize(text, audio_path, voice, rate, retries=3, tts_cls=None):
    """audio_path(mp3)를 만들고 [{start,end,text}] 문장 타이밍을 돌려준다."""
    if tts_cls is None:
        from gtts import gTTS as tts_cls
    lang = lang_from_voice(voice)
    speed = speed_from_rate(rate)
    audio_path = Path(audio_path)
    work = audio_path.parent / (audio_path.stem + "_parts")
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    sentences = split_sentences(text)
    if not sentences:
        raise RuntimeError("대본이 비어 있습니다")
    parts, bounds, t = [], [], 0.0
    try:
        for i, s in enumerate(sentences):
            raw, fixed = work / f"{i:03d}_raw.mp3", work / f"{i:03d}.mp3"
            for attempt in range(1, retries + 1):
                try:
                    kw = {"tld": "com"} if lang == "en" else {}
                    tts_cls(s, lang=lang, **kw).save(str(raw))
                    break
                except Exception:
                    if attempt == retries:
                        raise
                    time.sleep(3 * attempt)
            flt = f"atempo={speed:.3f}," if abs(speed - 1) > 0.01 else ""
            # 문장 뒤에 0.18초 숨을 둔다
            _run(["ffmpeg", "-y", "-i", str(raw), "-af", f"{flt}apad=pad_dur=0.18",
                  "-ar", "24000", "-ac", "1", "-b:a", "64k", str(fixed)])
            d = _duration(fixed)
            bounds.append({"start": round(t, 3), "end": round(t + d - 0.18, 3), "text": s})
            t += d
            parts.append(fixed)
        lst = work / "list.txt"
        lst.write_text("".join(f"file '{p.name}'\n" for p in parts), encoding="utf-8")
        _run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(audio_path)])
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return bounds
