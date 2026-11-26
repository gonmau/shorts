# -*- coding: utf-8 -*-
"""랩 버전 쇼츠: 기존 소재의 대본을 '문장 1:1'로 랩 가사로 바꾼 복제 소재를 DB 끝에 만들고, 영상이 완성되면 비트를 깔아 준다.
 1) python rap_short.py make --index 649             -> 새 소재 번호 N 출력 (대본=랩 가사, 사실·숫자 유지, 이미지·핵심 문구 자리는 원본과 같음)
 2) 평소 파이프라인 그대로: fetch_images / generate_tts (TTS_RATE=+8% 권장) / build_video / make_thumbnail --index N
 2.5) python rap_short.py align --index N [--bpm 92]  (음성 만든 직후, 영상 합성 전: 줄을 비트 격자에 맞춰 늘이고/여백 줄 - 이게 있어야 랩 박자가 남)
 3) python rap_short.py beat --index N [--bpm 92]    -> 영상 음성 밑에 합성 비트(킥·스네어·하이햇·베이스)를 깔고 video_path_v6 를 새 파일로 교체
원본 소재는 건드리지 않는다. 복제 소재는 제목 2줄째가 '랩으로 듣는 이야기', rap_of 에 원본 번호가 남는다."""
import argparse, json, os, re, subprocess, sys, tempfile
from pathlib import Path
from common import split_sentences

DROP = ["audio_path_v2", "timing_path_v2", "tts_voice_v2", "status_tts_v2", "srt_path", "video_path_v6", "status_v6", "youtube_id", "uploaded_at", "image_credits",
        "image_queries_done", "image_source", "thumb_scene", "review_needed", "review_ok", "curate_score", "curate_note", "history", "jp_title", "en_title"]

def numbers(s):
    return re.findall(r"\d[\d,\.]*", str(s))

KO1 = {"1": "한일하나첫", "2": "두이둘", "3": "세삼셋", "4": "네사넷", "5": "다섯오", "6": "여섯육", "7": "일곱칠", "8": "여덟팔", "9": "아홉구", "0": "영공제로"}


def _vow(ch):
    c = ord(ch) - 0xAC00
    if not 0 <= c < 11172: return None
    j = (c % 588) // 28                                              # 중성(모음) 번호
    return {1: 5, 3: 7, 10: 5, 11: 5, 15: 5}.get(j, j)               # ㅐ·ㅔ·ㅙ·ㅚ·ㅞ 는 같은 소리로 취급

def tail_vowels(line, k=2):
    syl = [c for c in re.sub(r"[^가-힣]", "", line)]
    v = [_vow(c) for c in syl[-k:]]
    return tuple(v) if len(v) == k else None

def rhyme_report(rap):
    """2줄씩 짝(1-2, 3-4 ...)의 끝 두 글자 모음이 같은지. 맞는 쌍 비율과 틀린 쌍 목록"""
    bad, tot = [], 0
    for i in range(0, len(rap) - 1, 2):
        tot += 1
        if tail_vowels(rap[i]) is None or tail_vowels(rap[i]) != tail_vowels(rap[i + 1]): bad.append((i + 1, i + 2))
    return (1 - len(bad) / tot if tot else 1.0), bad

def valid(orig, rap):
    if len(orig) != len(rap): return f"줄 수 불일치(원문 {len(orig)}줄, 가사 {len(rap)}줄)"
    for o, r in zip(orig, rap):
        if not r.strip() or len(r) > max(50, len(o) * 1.5): return f"너무 긺: {r[:30]}"
        bad = [w for w in ("라임", "운율", "박자", "4박", "가사", "비트", "리듬", "랩으로", "rhyme") if w in r and w not in o]
        if bad: return f"작성 지시어({bad[0]})가 가사에 섞임: {r[:30]} -> 이야기 내용만 쓰고 '라임/박자' 같은 말은 쓰지 마세요"
        for n in numbers(o):
            nn = n.replace(",", "").rstrip(".")
            if nn in r.replace(",", ""): continue
            if len(nn) == 1 and any(w in r for w in KO1.get(nn, "")): continue      # 한 자리 숫자는 '세/두/한' 같은 우리말 수사도 인정
            return f"숫자 누락 {n}: {r[:30]}"
    ratio, bad = rhyme_report(rap)
    if ratio < 0.7: return "라임 부족: 줄 " + ", ".join(f"{a}-{b}" for a, b in bad[:5]) + " 쌍의 끝 두 글자 모음이 서로 달라요. 각 쌍이 같은 소리로 끝나게(예: ~했네/~됐네, ~섬에/~점에) 끝말을 고쳐 다시 쓰세요"
    return ""

PROMPT = """아래는 한국어 쇼츠 대본입니다(문장 {n}개). 사실은 그대로 두고 **한국어 랩 가사**로 바꿔 주세요.
규칙:
- 반드시 정확히 {n}줄. 원문 i번째 문장 -> 가사 i번째 줄 (1:1 대응).
- 원문의 연도, 숫자, 고유명사, 사실 관계는 빠뜨리거나 바꾸지 말 것. 새 사실·과장 금지.
- 줄마다 4박자로 읽히게(대략 12~26자).
- **진짜 압운**: 2줄씩 짝(1-2줄, 3-4줄, 5-6줄 ...)으로 묶고, 짝을 이루는 두 줄은 **끝 두 글자의 모음이 같아야** 합니다. 먼저 짝마다 끝말을 정하세요. 예) '쐈네 / 죽였네'(ㅐ네), '섬에서 / 점령해서'(ㅓ에서), '1859년 / 한 방에 전쟁 직전'. 어색하면 문장 순서는 두고 말만 바꿔서라도 맞춥니다.
- 첫 줄은 "Yo,"로 시작해도 좋고 마지막 줄은 짧은 마무리 한 마디.
- 가사에 '라임', '박자', '가사', '비트' 같은 작성 지시어를 쓰지 말 것(이야기 내용만).
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
    rap, fb = None, ""
    for tries in range(3):       # 실패 사유를 알려 주며 다시 요청
        prompt = PROMPT.format(n=len(sents), src=src) + (f"\n\n[이전 시도의 문제] {fb}\n위 문제를 고쳐서 다시 작성하세요. 원문의 연도·숫자는 그대로 쓰고, 줄 수는 정확히 {len(sents)}줄입니다." if fb else "")
        rap = G.ask_models(client, models, "당신은 사실에 충실한 한국어 랩 작사가입니다.", prompt, 1800, 2, parse)
        if rap: break
        fb = err["e"] or "JSON 배열 형식이 아님"; print(f"  가사 검증 실패({tries + 1}/3): {fb}")
    if not rap: sys.exit(f"랩 가사 생성 실패 ({fb})")
    new = {k: v for k, v in it.items() if k not in DROP}
    new.update(narration="\n".join(l if re.search(r"[.!?]$", l) else l + "." for l in rap), narration_original=it.get("narration", ""), status="scripted",
               rap=True, rap_of=a.index, title_line2="랩으로 듣는 이야기", review_ok=True)
    db.append(new); G.save_db(db); n = len(db) - 1
    print(f"랩 소재 생성: {n} (원본 {a.index})\n")
    for o, r in zip(sents, rap): print(f"  {o[:40]}\n  🎤 {r}\n")
    print(f"다음: fetch_images.py --index {n} / generate_tts.py --index {n} (TTS_RATE=+8%) / build_video.py --index {n} / make_thumbnail --start {n} ... 영상 후 rap_short.py beat --index {n}")

def beat_track(dur, sr, bpm, voice_rms):
    import numpy as np
    n = int(dur * sr); t = np.arange(n) / sr; out = np.zeros(n, dtype=np.float32); bt = 60.0 / bpm; rnd = np.random.RandomState(7)
    def add(at, wave, g=1.0):
        i = int(at * sr)
        if i < n: out[i:i + len(wave)] += wave[:n - i] * g
    tk = np.arange(int(.30 * sr)) / sr; kick = (np.sin(2 * np.pi * (45 + 130 * np.exp(-tk * 30)) * tk) * np.exp(-tk * 8) * 1.3).astype(np.float32)
    ts = np.arange(int(.22 * sr)) / sr; snare = ((rnd.randn(len(ts)) * 0.8 + np.sin(2 * np.pi * 185 * ts) * 0.5) * np.exp(-ts * 20)).astype(np.float32)
    th = np.arange(int(.045 * sr)) / sr; hat = (rnd.randn(len(th)) * np.exp(-th * 100) * 0.4).astype(np.float32)
    bass = [55.0, 55.0, 65.41, 49.0]                       # A1 A1 C2 G1 (마이너)
    bars = int(dur / (4 * bt)) + 2
    for bar in range(bars):
        b0 = bar * 4 * bt
        for k in (0, 1.5, 2.5): add(b0 + k * bt, kick)      # 붐뱁 킥: 1, 2.5, 3.5박
        for k in (1, 3): add(b0 + k * bt, snare)            # 2, 4박 스네어
        for k in range(16): add(b0 + k * bt / 4 + (0.012 if k % 2 else 0), hat, 1.0 if k % 4 == 0 else (0.7 if k % 2 == 0 else 0.45))   # 16분 하이햇 + 스윙
        f = bass[bar % 4]; m = (t >= b0) & (t < b0 + 4 * bt); tt = t[m] - b0
        env = 0.55 + 0.45 * np.exp(-(tt % (2 * bt)) * 2.5)
        out[m] += (np.sin(2 * np.pi * f * tt) * 0.55 * env).astype(np.float32)
    # 로파이 코드 패드(전자피아노 느낌의 FM) + 약한 바이닐 노이즈
    chords = [(220.0, 261.63, 329.63), (220.0, 261.63, 329.63), (261.63, 329.63, 392.0), (196.0, 246.94, 293.66)]   # Am Am C G
    pad = np.zeros(n, dtype=np.float32)
    for bar in range(bars):
        b0 = bar * 4 * bt; m = (t >= b0) & (t < b0 + 4 * bt); tt = t[m] - b0; env = np.exp(-tt * 1.1) * 0.6 + 0.4
        for f in chords[bar % 4]:
            pad[m] += (np.sin(2 * np.pi * f * tt + 1.5 * np.sin(2 * np.pi * f * 2 * tt) * np.exp(-tt * 3)) * env * 0.18).astype(np.float32)
    k = np.ones(int(sr * 0.0004) + 1) / (int(sr * 0.0004) + 1); pad = np.convolve(pad, k, "same").astype(np.float32)
    vinyl = (rnd.randn(n) * 0.02 * (rnd.rand(n) > 0.995)).astype(np.float32)
    rms = float(np.sqrt((out ** 2).mean())) or 1.0
    out = out * (voice_rms * 0.55 / rms); prms = float(np.sqrt((pad ** 2).mean())) or 1.0
    return out + pad * (voice_rms * 0.22 / prms) + vinyl * voice_rms

def align(a):
    """각 가사 줄을 비트 격자(2박 단위)에 맞게 늘이고/줄이고 줄 사이에 비트용 여백을 둬서 박자에 올라타게 한다. 음성 파일과 timing json 을 덮어쓴다(원본은 _orig 로 보관)."""
    import numpy as np, shutil
    import generate_script as G
    db = G.load_db(); it = db[a.index]; ap = Path(it["audio_path_v2"]); tp = Path(it["timing_path_v2"]); sr = 44100; U = 2 * 60.0 / a.bpm
    if not ap.exists(): sys.exit(f"음성 파일 없음: {ap}")
    bk = ap.with_name(ap.stem + "_orig" + ap.suffix); tbk = tp.with_name(tp.stem + "_orig.json")
    src = bk if bk.exists() else ap; tsrc = tbk if tbk.exists() else tp      # 다시 돌려도 원본 기준
    if not bk.exists(): shutil.copy(ap, bk)
    if not tbk.exists(): shutil.copy(tp, tbk)
    data = json.load(open(tsrc, encoding="utf-8")); chunks = []; new = []; pos = 0.0
    for s_ in data["sentences"]:
        st, en = float(s_["start"]), float(s_["end"]); d = max(0.3, en - st)
        u = max(1, round(d / U)); r = d / (u * U * 0.94)
        while r > 1.45: u += 1; r = d / (u * U * 0.94)
        while r < 0.80 and u > 1: u -= 1; r = d / (u * U * 0.94)
        r = min(max(r, 0.75), 1.6); T = u * U
        af = f"atempo={r:.4f},acompressor=threshold=-18dB:ratio=3:attack=5:release=60,aecho=0.8:0.5:90:0.18,apad=whole_dur={T:.4f}"
        raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{st:.3f}", "-t", f"{d:.3f}", "-i", str(src), "-af", af, "-t", f"{T:.4f}", "-ac", "1", "-ar", str(sr), "-f", "f32le", "-"],
                             capture_output=True, check=True).stdout
        x = np.frombuffer(raw, dtype=np.float32); need = int(round(T * sr)); x = np.pad(x, (0, max(0, need - len(x))))[:need]; chunks.append(x)
        new.append({"start": round(pos, 3), "end": round(pos + min(T, d / r), 3), "text": s_["text"]}); pos += T
    y = np.concatenate(chunks); y = y / max(1.0, float(np.abs(y).max()) / 0.95)
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "f32le", "-ar", str(sr), "-ac", "1", "-i", "-", "-b:a", "192k", str(ap)], input=y.astype(np.float32).tobytes(), check=True)
    data["sentences"] = new; data["rap_bpm"] = a.bpm; json.dump(data, open(tp, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"박자 맞춤({a.bpm}bpm, 2박={U:.2f}초 단위): {len(new)}줄, 총 {pos:.1f}초)")

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
    al = sp.add_parser("align"); al.add_argument("--index", type=int, required=True); al.add_argument("--bpm", type=int, default=92)
    b = sp.add_parser("beat"); b.add_argument("--index", type=int, required=True); b.add_argument("--bpm", type=int, default=92)
    a = ap.parse_args(); {"make": make, "align": align, "beat": beat}[a.cmd](a)
if __name__ == "__main__":
    main()
