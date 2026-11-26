# -*- coding: utf-8 -*-
"""랩 버전 쇼츠: 기존 소재의 대본을 '문장 1:1'로 랩 가사로 바꾼 복제 소재를 DB 끝에 만들고, 영상이 완성되면 비트를 깔아 준다.
 1) python rap_short.py make --index 649             -> 새 소재 번호 N 출력 (대본=랩 가사, 사실·숫자 유지, 이미지·핵심 문구 자리는 원본과 같음)
 2) 평소 파이프라인 그대로: fetch_images / generate_tts (TTS_RATE=+8% 권장) / build_video / make_thumbnail --index N
 3) python rap_short.py beat --index N [--bpm 92]    -> 영상 음성 밑에 합성 비트(킥·스네어·하이햇·베이스)를 깔고 video_path_v6 를 새 파일로 교체
원본 소재는 건드리지 않는다. 복제 소재는 제목 2줄째가 '랩으로 듣는 이야기', rap_of 에 원본 번호가 남는다."""
import argparse, json, os, re, subprocess, sys, tempfile
from pathlib import Path
from common import split_sentences

DROP = ["audio_path_v2", "timing_path_v2", "tts_voice_v2", "status_tts_v2", "srt_path", "video_path_v6", "status_v6", "youtube_id", "uploaded_at", "image_credits",
        "image_queries_done", "image_source", "thumb_scene", "review_needed", "review_ok", "curate_score", "curate_note", "history", "jp_title", "en_title"]

def numbers(s):
    return re.findall(r"\d[\d,\.]*", str(s))

def valid(orig, rap):
    if len(orig) != len(rap): return "줄 수 불일치"
    for o, r in zip(orig, rap):
        if not r.strip() or len(r) > max(50, len(o) * 1.5): return f"너무 긺: {r[:30]}"
        for n in numbers(o):
            if n.replace(",", "") not in r.replace(",", ""): return f"숫자 누락 {n}: {r[:30]}"
    return ""

PROMPT = """아래는 한국어 쇼츠 대본입니다(문장 {n}개). 사실은 그대로 두고 **한국어 랩 가사**로 바꿔 주세요.
규칙:
- 반드시 정확히 {n}줄. 원문 i번째 문장 -> 가사 i번째 줄 (1:1 대응).
- 원문의 연도, 숫자, 고유명사, 사실 관계는 빠뜨리거나 바꾸지 말 것. 새 사실·과장 금지.
- 줄마다 4박자 리듬으로 읽히게(대략 12~26자), 두세 줄마다 끝소리(라임)를 맞출 것. 첫 줄은 "Yo,"로 시작해도 좋고 마지막 줄은 짧은 마무리 한 마디.
- 욕설, 비속어 금지. 영어 추임새는 Yo, Yeah 정도만.
- 출력은 JSON 문자열 배열 하나만. 설명 금지.

원문:
{src}
"""

def make(a):
    from groq import Groq
    import generate_script as G
    db = G.load_db(); it = db[a.index]
    sents = split_sentences(it.get("narration", ""))
    if not sents: sys.exit("narration 이 없습니다")
    client = Groq(api_key=os.environ["GROQ_API_KEY"], timeout=90.0); models = G.pick_models(client)
    src = "\n".join(f"{i + 1}. {s}" for i, s in enumerate(sents)); err = {"e": ""}
    def parse(t):
        arr = G.extract_json(t)
        if not isinstance(arr, list): return None
        arr = [re.sub(r"^\d+[\.\)]\s*", "", str(x)).strip() for x in arr]
        err["e"] = valid(sents, arr)
        return arr if not err["e"] else None
    rap = G.ask_models(client, models, "당신은 사실에 충실한 한국어 랩 작사가입니다.", PROMPT.format(n=len(sents), src=src), 1800, 4, parse)
    if not rap: sys.exit(f"랩 가사 생성 실패 ({err['e'] or '응답 없음'})")
    new = {k: v for k, v in it.items() if k not in DROP}
    new.update(narration="\n".join(l if re.search(r"[.!?]$", l) else l + "." for l in rap), narration_original=it.get("narration", ""), status="scripted",
               rap=True, rap_of=a.index, title_line2="랩으로 듣는 이야기", review_ok=True)
    db.append(new); G.save_db(db); n = len(db) - 1
    print(f"랩 소재 생성: {n} (원본 {a.index})\n")
    for o, r in zip(sents, rap): print(f"  {o[:40]}\n  🎤 {r}\n")
    print(f"다음: fetch_images.py --index {n} / generate_tts.py --index {n} (TTS_RATE=+8%) / build_video.py --index {n} / make_thumbnail --start {n} ... 영상 후 rap_short.py beat --index {n}")

def beat_track(dur, sr, bpm, voice_rms):
    import numpy as np
    n = int(dur * sr); t = np.arange(n) / sr; out = np.zeros(n, dtype=np.float32); step = 60.0 / bpm; rnd = np.random.RandomState(7)
    def add(at, wave):
        i = int(at * sr)
        if i < n: out[i:i + len(wave)] += wave[:n - i]
    tk = np.arange(int(.25 * sr)) / sr; kick = (np.sin(2 * np.pi * (50 + 110 * np.exp(-tk * 28)) * tk) * np.exp(-tk * 9)).astype(np.float32)
    ts = np.arange(int(.18 * sr)) / sr; snare = ((rnd.randn(len(ts)) * 0.7 + np.sin(2 * np.pi * 190 * ts) * 0.4) * np.exp(-ts * 22)).astype(np.float32)
    th = np.arange(int(.05 * sr)) / sr; hat = (rnd.randn(len(th)) * np.exp(-th * 90) * 0.35).astype(np.float32)
    bass_notes = [55.0, 55.0, 65.41, 49.0]                 # A1 A1 C2 G1 — 단순한 마이너 진행
    bar = 0
    while bar * 4 * step < dur:
        b0 = bar * 4 * step
        for k in (0, 2.5): add(b0 + k * step, kick)         # 1박, 3박 반
        for k in (1, 3): add(b0 + k * step, snare)          # 2박, 4박
        for k in range(8): add(b0 + k * step / 2, hat * (1.0 if k % 2 == 0 else 0.6))
        f = bass_notes[bar % 4]; m = (t >= b0) & (t < b0 + 4 * step); tt = t[m] - b0
        out[m] += (np.sin(2 * np.pi * f * tt) * 0.5 * (0.6 + 0.4 * np.exp(-(tt % step) * 3))).astype(np.float32)
        bar += 1
    rms = float(np.sqrt((out ** 2).mean())) or 1.0
    return out * (voice_rms * 0.30 / rms)                   # 목소리 크기의 30% 수준으로 깔림

def beat(a):
    import numpy as np
    import generate_script as G
    db = G.load_db(); it = db[a.index]; vp = it.get("video_path_v6")
    if not vp or not Path(vp).exists(): sys.exit(f"영상 파일이 없습니다: {vp}")
    sr = 44100
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", vp, "-vn", "-ac", "2", "-ar", str(sr), "-f", "f32le", "-"], capture_output=True, check=True).stdout
    v = np.frombuffer(raw, dtype=np.float32).reshape(-1, 2); dur = len(v) / sr; rms = float(np.sqrt((v ** 2).mean())) or 0.1
    b = beat_track(dur, sr, a.bpm, rms)[:, None]; mix = np.clip(v + b, -1, 1).astype(np.float32)
    out = str(Path(vp).with_name(Path(vp).stem + "_rap.mp4"))
    with tempfile.NamedTemporaryFile(suffix=".raw", delete=False) as f: f.write(mix.tobytes()); tmp = f.name
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", vp, "-f", "f32le", "-ar", str(sr), "-ac", "2", "-i", tmp, "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", out], check=True)
    os.unlink(tmp); it["video_path_beatless"] = vp; it["video_path_v6"] = out; G.save_db(db); print(f"비트 입힘({a.bpm}bpm): {out}")

def main():
    ap = argparse.ArgumentParser(); sp = ap.add_subparsers(dest="cmd", required=True)
    m = sp.add_parser("make"); m.add_argument("--index", type=int, required=True)
    b = sp.add_parser("beat"); b.add_argument("--index", type=int, required=True); b.add_argument("--bpm", type=int, default=92)
    a = ap.parse_args(); {"make": make, "beat": beat}[a.cmd](a)
if __name__ == "__main__":
    main()
