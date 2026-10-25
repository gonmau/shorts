# -*- coding: utf-8 -*-
"""대본에 구독/좋아요 요청이 들어간 소재를 찾아서(점검), 필요하면 대본부터 다시 만들도록 되돌린다(--apply).

- 기본은 점검만 한다 (아무것도 바꾸지 않음).
- --apply : 아직 영상이 안 만들어진 소재만 되돌림 -> 다음 prepare/all 실행 때 새 대본(구독 문구 금지)으로 재생성.
- --include-rendered : 이미 영상이 만들어진 소재도 되돌림 (영상 다시 제작. 유튜브에 올라간 옛 영상은 직접 삭제해야 함).
"""
import argparse
import os

from common import load_db, save_db, split_sentences

WORDS = ("subscribe", "hit the like", "like and", "turn on notifications", "notification", "comment below", "follow for", "follow us", "follow me")
TTS_KEYS = ("status_tts_v2", "audio_path_v2", "timing_path_v2")
VIDEO_KEYS = ("status_v6", "video_path_v6")
EXTRA_KEYS = ("title_line1", "title_line2", "highlights", "image_queries", "image_source", "image_credits")


def find_cta(item):
    hits = [s for s in split_sentences(item.get("narration", "")) if any(w in s.lower() for w in WORDS)]
    return hits


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--include-rendered", action="store_true")
    args = ap.parse_args()

    db = load_db()
    lines, changed = [], 0
    for idx, item in enumerate(db):
        if idx < args.start:
            continue
        hits = find_cta(item)
        if not hits:
            continue
        rendered = bool(item.get("video_path_v6") or item.get("status_v6") == "video_done")
        tag = "영상 제작됨" if rendered else "미제작"
        lines.append(f"- [{idx}] {item.get('country', '')} ({tag}): {hits[-1]}")
        if not args.apply or (rendered and not args.include_rendered):
            continue
        item.pop("narration", None)
        for k in TTS_KEYS + EXTRA_KEYS + (VIDEO_KEYS if rendered else ()):
            item.pop(k, None)
        if rendered:
            item.pop("youtube_id", None)
            item.pop("uploaded_at", None)
        item["status"] = "verified"   # generate_script.py가 대본을 다시 만든다
        changed += 1

    report = [f"구독/좋아요 문구가 있는 소재: {len(lines)}개 (번호 {args.start} 이후)"] + lines
    if args.apply:
        save_db(db)
        report.append(f"-> {changed}개를 대본부터 다시 만들도록 되돌림")
    else:
        report.append("(점검만 했고 아무것도 바꾸지 않았습니다)")
    text = "\n".join(report)
    print(text)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write("### 구독 문구 점검\n```\n" + text + "\n```\n")


if __name__ == "__main__":
    main()
