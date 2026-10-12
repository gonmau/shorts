# -*- coding: utf-8 -*-
"""이미 만든 영상을 다시 만들 수 있게 되돌린다 (음성/영상 기록만 지움, 대본·제목은 유지).

예: python redo_videos.py --indexes 98,99
이후 render(또는 all) 실행 시 번호 순서대로 대기열 맨 앞에서 다시 제작된다.
유튜브에 이미 올린 소재는 youtube_id를 남겨 둬서 자동 업로드는 다시 하지 않는다(새 영상은 아티팩트에서 받아 수동 업로드).
"""
import argparse

from common import load_db, save_db

CLEAR = ("audio_path_v2", "timing_path_v2", "tts_voice_v2", "status_tts_v2", "video_path_v6", "status_v6")


SCRIPT_CLEAR = ("narration", "narration_original", "narration_user_edited", "title_line1", "title_line2",
                "highlights", "image_queries", "fact_checked", "fact_issues", "fact_risk", "fact_verifiability",
                "fact_applied", "reject_reason", "ko_title", "ko_description", "ko_narration", "ko_issues", "ko_src")


def redo_script(db, idxs):
    """대본부터 다시: 대본/제목/핵심 문구/검색어/팩트체크/번역/음성/영상 기록을 지우고 소재 단계(verified)로 되돌린다.
    폐기(rejected)된 소재도 다시 시도할 수 있다. 소재(hook/body/twist)는 그대로 둔다."""
    for i in idxs:
        if not (0 <= i < len(db)):
            print(f"  [{i}] 범위 밖 - 건너뜀")
            continue
        f = db[i]
        for k in CLEAR + SCRIPT_CLEAR:
            f.pop(k, None)
        f["status"] = "verified"
        print(f"  [{i}] {f.get('country', '')}: 대본부터 다시 생성 대기")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--indexes", default="", help="쉼표로 구분한 DB 번호 (예: 98,99)")
    ap.add_argument("--script", action="store_true", help="대본부터 다시 만들기")
    args = ap.parse_args()
    idxs = [int(x) for x in args.indexes.replace(" ", "").split(",") if x.strip().isdigit()]
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
        note = " (이미 유튜브에 업로드된 소재: 새 영상은 수동 업로드)" if f.get("youtube_id") else ""
        print(f"  [{i}] {f.get('country', '')}: 다시 제작 대기열로{note}")
    save_db(db)


if __name__ == "__main__":
    main()
