"""
세계 문화 상식 쇼츠 - 무료 Neural TTS V2

gTTS 대신 edge-tts를 사용합니다.
실제 음성의 SentenceBoundary 타이밍도 함께 저장하여
build_video 단계에서 자막과 장면 전환을 실제 음성에 맞춥니다.

설치:
    pip install -U edge-tts

사용:
    python generate_tts.py --index 0
    python generate_tts.py --limit 5
    python generate_tts.py --limit 5 --force        (이미 만든 항목도 다시 생성)
    python generate_tts.py --timeout 60 --retries 3

음성:
    기본: ko-KR-SunHiNeural
    예:   ko-KR-InJoonNeural
          ko-KR-JiMinNeural
          ko-KR-SeoHyeonNeural

속도:
    기본 -3%. 쇼츠에서 너무 급하게 들리지 않도록 약간 느리게 설정했습니다.

v2 변경점:
    - 서버가 응답하지 않아도 무한 대기하지 않도록 타임아웃/재시도 추가
    - 항목별 진행 로그, 항목 하나 끝날 때마다 DB 즉시 저장
    - 실패 시 반쯤 만들어진 mp3가 남지 않도록 임시 파일 후 교체
    - 이미 TTS가 끝난 항목은 건너뜀 (--force로 재생성)
"""

import argparse
import asyncio
import json
import re
import time
import unicodedata
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "facts_db.json"
AUDIO_DIR = BASE_DIR / "audio"

CONNECT_TIMEOUT = 15   # 서버 연결 대기(초)
RECEIVE_TIMEOUT = 45   # 데이터 수신 대기(초)


def log(msg=""):
    print(msg, flush=True)


def load_db():
    with open(DB_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_db(db):
    tmp = DB_PATH.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)
    tmp.replace(DB_PATH)


def safe_name(text):
    # 다른 스크립트(generate_visuals*.py, build_video)와 같은 방식으로 정규화
    text = unicodedata.normalize("NFKC", str(text)).strip()
    text = re.sub(r"\s+", " ", text)
    return re.sub(r'[<>:"/\\|?*]', "_", text).strip()


async def _synthesize(text, voice, rate, volume, pitch, audio_tmp):
    import edge_tts

    kwargs = dict(rate=rate, volume=volume, pitch=pitch, boundary="SentenceBoundary")
    try:
        communicate = edge_tts.Communicate(
            text, voice,
            connect_timeout=CONNECT_TIMEOUT,
            receive_timeout=RECEIVE_TIMEOUT,
            **kwargs,
        )
    except TypeError:
        # 구버전 edge-tts는 타임아웃 인자가 없음 (전체 타임아웃은 아래 wait_for가 담당)
        communicate = edge_tts.Communicate(text, voice, **kwargs)

    boundaries = []
    audio_bytes = 0

    with open(audio_tmp, "wb") as audio_file:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_file.write(chunk["data"])
                audio_bytes += len(chunk["data"])
            elif chunk["type"] == "SentenceBoundary":
                boundaries.append({
                    "start": chunk["offset"] / 10_000_000,
                    "end": (chunk["offset"] + chunk["duration"]) / 10_000_000,
                    "text": chunk["text"].strip(),
                })

    if audio_bytes < 1000:
        raise RuntimeError(f"오디오가 비어 있습니다 ({audio_bytes} bytes)")

    return boundaries


def generate_tts(text, audio_path, timing_path, voice, rate, volume, pitch,
                 timeout=90, retries=3):
    try:
        import edge_tts  # noqa: F401
    except ImportError:
        raise SystemExit(
            "edge-tts가 설치되어 있지 않습니다.\n"
            "먼저 실행하세요:\n"
            "    pip install -U edge-tts"
        )

    audio_tmp = audio_path.with_suffix(".part")
    last_error = None

    for attempt in range(1, retries + 1):
        try:
            boundaries = asyncio.run(
                asyncio.wait_for(
                    _synthesize(text, voice, rate, volume, pitch, audio_tmp),
                    timeout=timeout,
                )
            )
            audio_tmp.replace(audio_path)  # 성공했을 때만 최종 파일로 교체
            break
        except asyncio.TimeoutError:
            last_error = f"{timeout}초 안에 응답이 없습니다 (서버 무응답)"
        except Exception as e:
            last_error = f"{type(e).__name__}: {e}"

        if audio_tmp.exists():
            try:
                audio_tmp.unlink()
            except OSError:
                pass

        if attempt < retries:
            wait = 5 * attempt
            log(f"    [재시도 {attempt}/{retries}] {last_error} → {wait}초 후 다시 시도")
            time.sleep(wait)
    else:
        raise RuntimeError(last_error)

    timing_data = {
        "voice": voice,
        "rate": rate,
        "volume": volume,
        "pitch": pitch,
        "sentences": boundaries,
    }
    with open(timing_path, "w", encoding="utf-8") as f:
        json.dump(timing_data, f, ensure_ascii=False, indent=2)

    return len(boundaries)


def main():
    parser = argparse.ArgumentParser(
        description="무료 Neural 한국어 TTS + 실제 발화 타이밍 생성"
    )
    parser.add_argument("--index", type=int, default=None)
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--voice", default="ko-KR-SunHiNeural")
    parser.add_argument("--rate", default="-3%")
    parser.add_argument("--volume", default="+0%")
    parser.add_argument("--pitch", default="+0Hz")
    parser.add_argument("--timeout", type=int, default=90,
                        help="항목당 최대 대기 시간(초). 기본 90")
    parser.add_argument("--retries", type=int, default=3,
                        help="항목당 재시도 횟수. 기본 3")
    parser.add_argument("--force", action="store_true",
                        help="이미 TTS가 끝난 항목도 다시 생성")
    args = parser.parse_args()

    AUDIO_DIR.mkdir(exist_ok=True)
    db = load_db()

    if args.index is not None:
        if args.index < 0 or args.index >= len(db):
            raise SystemExit(f"--index {args.index} 범위 오류")
        targets = [(args.index, db[args.index])]
    else:
        targets = []
        for i, f in enumerate(db):
            if f.get("status") not in ("scripted", "tts_done"):
                continue  # video_done 등 이미 영상까지 끝난 항목은 건너뜀
            already = (
                f.get("status_tts_v2") == "done"
                and f.get("audio_path_v2")
                and Path(f["audio_path_v2"]).exists()
            )
            if already and not args.force:
                continue
            targets.append((i, f))
            if len(targets) >= args.limit:
                break

    if not targets:
        log("처리할 소재가 없습니다. (대본이 있고 TTS가 아직 안 된 항목이 없음)")
        return

    log(f"TTS V2 대상: {len(targets)}개")
    log(f"voice: {args.voice}")
    log(f"rate:  {args.rate}")
    log(f"timeout: {args.timeout}초 / retries: {args.retries}")

    ok = 0
    for n, (idx, fact) in enumerate(targets, start=1):
        country = fact.get("country", "Unknown")
        text = fact.get("narration", "").strip()

        log(f"\n[{n}/{len(targets)}] {idx:04d} {country} - 생성 중 ({len(text)}자)...")

        if not text:
            log(f"  실패: {idx} / narration 없음")
            continue

        name = safe_name(country)
        audio_path = AUDIO_DIR / f"{idx:04d}_{name}_v2.mp3"
        timing_path = AUDIO_DIR / f"{idx:04d}_{name}_v2_timing.json"

        started = time.time()
        try:
            count = generate_tts(
                text=text,
                audio_path=audio_path,
                timing_path=timing_path,
                voice=args.voice,
                rate=args.rate,
                volume=args.volume,
                pitch=args.pitch,
                timeout=args.timeout,
                retries=args.retries,
            )

            fact["audio_path_v2"] = str(audio_path)
            fact["timing_path_v2"] = str(timing_path)
            fact["tts_voice_v2"] = args.voice
            fact["status_tts_v2"] = "done"
            save_db(db)  # 항목마다 즉시 저장 (중간에 중지해도 진행분 보존)
            ok += 1

            log(f"  완료: {idx} / {country} ({time.time() - started:.1f}초)")
            log(f"    audio: {audio_path}")
            log(f"    timing: {timing_path}")
            log(f"    sentence boundaries: {count}")
            if count == 0:
                log("    [주의] 문장 타이밍이 0개입니다. 영상 제작 시 글자 수 비례로 대체됩니다.")

        except Exception as e:
            log(f"  실패: {idx} / {country} / {e}")

    log(f"\n완료: {ok}/{len(targets)}")
    log(f"DB: {DB_PATH}")


if __name__ == "__main__":
    main()
