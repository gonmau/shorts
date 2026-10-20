# -*- coding: utf-8 -*-
"""음성 미리듣기: 한 문장을 선택한 엔진/목소리로 만들어 파일로 저장 (UI 미리듣기용).

  python tts_preview.py --engine supertonic --text "안녕하세요" --out _preview.wav
  python tts_preview.py --engine edge --voice ko-KR-SunHiNeural --rate -3% --text "안녕하세요" --out _preview.mp3
"""
import argparse
import os
import sys
from pathlib import Path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", choices=["supertonic", "edge"], required=True)
    ap.add_argument("--text", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--lang", default="ko")
    ap.add_argument("--voice", default="")
    ap.add_argument("--rate", default="+0%")
    a = ap.parse_args()
    out = Path(a.out)
    if out.exists():
        out.unlink()
    if a.engine == "supertonic":
        from tts_fallback import speed_from_rate, supertonic_sentence
        supertonic_sentence(a.text, out, a.lang, speed_from_rate(a.rate))
    else:
        from generate_tts import _edge
        _edge(a.text, out, a.voice, a.rate, "+0%", "+0Hz", 40, 2)
    if not out.exists() or out.stat().st_size < 500:
        print("오디오가 만들어지지 않았습니다", file=sys.stderr)
        sys.exit(1)
    print("OK", out.stat().st_size)


if __name__ == "__main__":
    main()
