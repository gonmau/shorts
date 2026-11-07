# -*- coding: utf-8 -*-
"""이미 만든 대본에서 '발을 빼는 듯한' 면책·단서 문장(다를 수 있습니다 등)을 찾아 지운다.
  python clean_hedges.py            # 목록만 보기 (아무것도 안 바꿈)
  python clean_hedges.py --apply    # 영상이 아직 없는 소재의 대본에서 해당 문장을 지움 (음성도 지우므로 음성을 다시 만들어야 함)
영상이 이미 있는 소재는 목록에만 표시합니다. 고치려면 그 소재를 redo(번호만, 체크 해제)한 뒤 이 도구로 지우고 음성부터 다시 만드세요."""
import argparse
import re

from common import load_db, save_db
import generate_script as G


def split_keep(text):
    return [p for p in re.split(r"(?<=[.!?。！？])\s+|\n+", str(text or "").strip()) if p.strip()]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    db = load_db()
    hit_new, hit_video = [], []
    for i, f in enumerate(db):
        n = f.get("narration") or ""
        if not n or f.get("status") == "rejected":
            continue
        bad = [p for p in split_keep(n) if G._is_hedge(p)]
        if not bad:
            continue
        (hit_video if (f.get("video_path_v6") or f.get("youtube_id")) else hit_new).append((i, f, bad))
    for title, rows in (("영상 없음 (지울 수 있음)", hit_new), ("영상 있음 (목록만)", hit_video)):
        print(f"\n== {title}: {len(rows)}개")
        for i, f, bad in rows[:60]:
            print(f"[{i}] {f.get('country', '')}: " + " / ".join(b[:60] for b in bad))
    if not a.apply:
        print("\n미리보기입니다. 지우려면 --apply")
        return
    changed = 0
    for i, f, bad in hit_new:
        new = " ".join(p for p in split_keep(f["narration"]) if not G._is_hedge(p)).strip()
        if len(G.normalize_text(new)) < G.MIN_CHARS:
            print(f"[{i}] 지우면 너무 짧아져 건너뜀")
            continue
        f["narration"] = new
        for k in ("audio_path_v2", "timing_path_v2", "status_v2", "tts_voice_v2"):   # 음성은 대본과 맞지 않으므로 지움
            f.pop(k, None)
        if f.get("status") in ("tts_done",):
            f["status"] = "scripted"
        changed += 1
    save_db(db)
    print(f"\n{changed}개 대본에서 면책 문장을 지웠습니다. 해당 소재는 음성부터 다시 만드세요.")


if __name__ == "__main__":
    main()
