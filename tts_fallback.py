# -*- coding: utf-8 -*-
"""Edge TTS가 막혔을 때(403 등) 쓰는 대체 음성: gTTS(구글 번역 음성).

문장별로 합성 -> 속도 조절 -> 이어 붙이고, 문장 길이로 타이밍(boundaries)을 만든다.
"""
import base64
import os
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


DEFAULT_GOOGLE_VOICES = {"ko": "ko-KR-Neural2-A", "en": "en-US-Neural2-D"}  # 한국어=여성(SunHi 대응), 영어=남성(Andrew 대응)
LANG_CODES = {"ko": "ko-KR", "en": "en-US"}


def google_available():
    return bool(os.environ.get("GOOGLE_TTS_API_KEY"))


def google_sentence(text, out_path, lang, speed):
    """Google Cloud Text-to-Speech(REST, API 키)로 한 문장을 mp3로 저장."""
    import requests
    voice = os.environ.get("GOOGLE_TTS_VOICE") or DEFAULT_GOOGLE_VOICES.get(lang, DEFAULT_GOOGLE_VOICES["en"])
    body = {
        "input": {"text": text},
        "voice": {"languageCode": "-".join(voice.split("-")[:2]), "name": voice},
        "audioConfig": {"audioEncoding": "MP3", "speakingRate": round(speed, 3)},
    }
    r = requests.post(
        "https://texttospeech.googleapis.com/v1/text:synthesize",
        params={"key": os.environ["GOOGLE_TTS_API_KEY"]}, json=body, timeout=30,
    )
    if r.status_code != 200:
        raise RuntimeError(f"Google TTS {r.status_code}: {r.text[:200]}")
    Path(out_path).write_bytes(base64.b64decode(r.json()["audioContent"]))


_ST = {}  # Supertonic 모델은 한 번만 불러온다
DEFAULT_ST_VOICES = {"ko": "F1", "en": "M1"}  # 한국어=여성, 영어=남성 (SUPERTONIC_VOICE_KO/EN 으로 변경)


def supertonic_sentence(text, out_path, lang, speed):
    """Supertonic 3(키 불필요, CPU에서 직접 합성)로 한 문장을 wav로 저장."""
    if "tts" not in _ST:
        from supertonic import TTS
        _ST["tts"] = TTS(auto_download=True)
    tts = _ST["tts"]
    name = os.environ.get(f"SUPERTONIC_VOICE_{lang.upper()}") or DEFAULT_ST_VOICES.get(lang, "M1")
    style = _ST.setdefault("style_" + name, tts.get_voice_style(voice_name=name))
    wav, _ = tts.synthesize(text, voice_style=style, lang=lang, speed=round(1.05 * speed, 3))
    tts.save_audio(wav, str(out_path))


def synthesize(text, audio_path, voice, rate, retries=3, tts_cls=None, engine="gtts"):
    """audio_path(mp3)를 만들고 [{start,end,text}] 문장 타이밍을 돌려준다.
    engine: "google"(Google Cloud TTS, 키 필요) 또는 "gtts"(키 없음)."""
    if tts_cls is None and engine == "gtts":
        from gtts import gTTS as tts_cls
    lang = lang_from_voice(voice)
    speed = speed_from_rate(rate)
    if engine in ("google", "supertonic"):
        speed_atempo = 1.0  # 속도는 각 엔진의 speed 인자로 처리
    else:
        speed_atempo = speed
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
            raw = work / (f"{i:03d}_raw.wav" if engine == "supertonic" else f"{i:03d}_raw.mp3")
            fixed = work / f"{i:03d}.mp3"
            for attempt in range(1, retries + 1):
                try:
                    if engine == "google":
                        google_sentence(s, raw, lang, speed)
                    elif engine == "supertonic":
                        supertonic_sentence(s, raw, lang, speed)
                    else:
                        kw = {"tld": "com"} if lang == "en" else {}
                        tts_cls(s, lang=lang, **kw).save(str(raw))
                    break
                except Exception:
                    if attempt == retries:
                        raise
                    time.sleep(3 * attempt)
            flt = f"atempo={speed_atempo:.3f}," if abs(speed_atempo - 1) > 0.01 else ""
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
