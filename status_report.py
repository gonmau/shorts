# -*- coding: utf-8 -*-
"""facts_db.json 현황 요약 (디스코드 알림 끝에 붙임). 단독 실행하면 화면에 출력."""
import argparse

from common import load_db

MIN_CHARS = 60


def rng(nums):
    """[116,117,118,120] -> '116~118, 120'"""
    out, i = [], 0
    while i < len(nums):
        j = i
        while j + 1 < len(nums) and nums[j + 1] == nums[j] + 1:
            j += 1
        out.append(str(nums[i]) if i == j else f"{nums[i]}~{nums[j]}")
        i = j + 1
    return ", ".join(out) or "-"


def summary(db, start=0):
    def has_narr(f):
        return len(str(f.get("narration") or "").strip()) >= MIN_CHARS

    def no_video(f):
        return not f.get("video_path_v6") and f.get("status_v6") != "video_done"

    idx = [(i, f) for i, f in enumerate(db) if i >= start]
    ready = [i for i, f in idx if no_video(f) and (
        f.get("status") in ("scripted", "tts_done")
        or (f.get("status") in ("unverified", "verified") and has_narr(f)))]
    need = [i for i, f in idx if not has_narr(f) and f.get("status") in ("unverified", "verified")]
    rej = [i for i, f in idx if f.get("status") == "rejected"]
    done = [i for i, f in idx if not no_video(f)]
    return (
        f"📊 현황 (start_index={start} 기준)\n"
        f"• render 바로 가능: {len(ready)}개 ({rng(ready)})\n"
        f"• prepare로 대본 만들 소재: {len(need)}개 ({rng(need)})\n"
        f"• 폐기(rejected): {len(rej)}개 ({rng(rej)}) → 번호! 로 되살림\n"
        f"• 영상 완료: {len(done)}개\n"
        f"권장: render count=3 정도씩, prepare count=5 정도부터"
    )


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", type=int, default=0)
    print(summary(load_db(), ap.parse_args().start))
