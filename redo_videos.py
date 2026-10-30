# -*- coding: utf-8 -*-
"""이미 만든 영상을 다시 만들 수 있게 되돌린다 (음성/영상 기록만 지움, 대본·제목은 유지).

예: python redo_videos.py --indexes 98,99
이후 render(또는 all) 실행 시 번호 순서대로 대기열 맨 앞에서 다시 제작된다.
유튜브에 이미 올린 소재는 youtube_id를 남겨 둬서 자동 업로드는 다시 하지 않는다(새 영상은 아티팩트에서 받아 수동 업로드).
"""
import argparse
import time

from common import load_db, save_db

CLEAR = ("audio_path_v2", "timing_path_v2", "tts_voice_v2", "status_tts_v2", "video_path_v6", "status_v6")


REVIVE = set()
SCRIPT_CLEAR = ("narration", "narration_original", "narration_user_edited", "title_line1", "title_line2",
                "highlights", "image_queries", "fact_checked", "fact_issues", "fact_risk", "fact_verifiability",
                "fact_applied", "reject_reason", "ko_title", "ko_description", "ko_narration", "ko_issues", "ko_src")


def revive(db, i):
    """폐기됐거나 다시 손보고 싶은 소재를 대본은 그대로 둔 채 검수 대기열(review.txt)로 되살린다.
    review.txt에서 대본/후크/본문/반전을 직접 고쳐 render 하면 된다(AI 검수가 덮어쓰지 않음)."""
    f = db[i]
    if not f.get("narration"):
        print(f"  [{i}] 대본이 없어 되살릴 수 없음 (번호만 넣어 대본부터 다시 만드세요)")
        return
    for k in CLEAR + ("reject_reason",):
        f.pop(k, None)
    f["status"] = "scripted"
    f["redo_ts"] = time.time()
    f["fact_verifiability"] = "user"
    f["fact_risk"] = "user-pending"
    print(f"  [{i}] {f.get('country', '')}: 검수 대기열로 되살림 (review.txt에서 직접 고치세요)")


def redo_script(db, idxs):
    """대본부터 다시: 대본/제목/핵심 문구/검색어/팩트체크/번역/음성/영상 기록을 지우고 소재 단계(verified)로 되돌린다.
    폐기(rejected)된 소재도 다시 시도할 수 있다. 소재(hook/body/twist)는 그대로 둔다."""
    for i in idxs:
        if not (0 <= i < len(db)):
            print(f"  [{i}] 범위 밖 - 건너뜀")
            continue
        if i in REVIVE:
            revive(db, i)
            continue
        f = db[i]
        for k in CLEAR + SCRIPT_CLEAR:
            f.pop(k, None)
        f["status"] = "verified"
        f["redo_ts"] = time.time()   # sync_db가 GitHub의 옛 상태(video_done)로 되돌리지 못하게 하는 표시
        print(f"  [{i}] {f.get('country', '')}: 대본부터 다시 생성 대기")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--indexes", default="", help="쉼표로 구분한 DB 번호 (예: 98,99)")
    ap.add_argument("--script", action="store_true", help="대본부터 다시 만들기")
    args = ap.parse_args()
    toks = [x.strip() for x in args.indexes.replace(" ", "").split(",") if x.strip()]
    idxs = [int(x.rstrip("!")) for x in toks if x.rstrip("!").isdigit()]
    REVIVE.update(int(x.rstrip("!")) for x in toks if x.endswith("!") and x.rstrip("!").isdigit())
    if not idxs:
        print("redo 대상 없음")
        return
    db = load_db()
    if args.script:
        redo_script(db, idxs)
        save_db(db)
        return
    for i in idxs:
        if not (0 <= i < len(db)):
            print(f"  [{i}] 범위 밖 - 건너뜀")
            continue
        f = db[i]
        if not f.get("narration"):
            print(f"  [{i}] 대본이 없어 건너뜀")
            continue
        for k in CLEAR:
            f.pop(k, None)
        f["status"] = "scripted"
        f["redo_ts"] = time.time()
        note = " (이미 유튜브에 업로드된 소재: 새 영상은 수동 업로드)" if f.get("youtube_id") else ""
        print(f"  [{i}] {f.get('country', '')}: 다시 제작 대기열로{note}")
    save_db(db)


if __name__ == "__main__":
    main()
