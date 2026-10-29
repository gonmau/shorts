# -*- coding: utf-8 -*-
"""facts_db.json 현황 요약 (디스코드 알림 끝에 붙임). 단독 실행하면 화면에 출력."""
import argparse

from common import load_db, upload_state

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


def label(db, i, reason=False):
    f = db[i]
    t = " ".join(x for x in (f.get("title_line1"), f.get("title_line2")) if x) or str(f.get("topic") or "")
    t = " ".join(t.split())[:40]
    r = f" [{str(f.get('reject_reason'))[:25]}]" if reason and f.get("reject_reason") else ""
    return f"  {i} {f.get('label') or f.get('country', '')} - {t}{r}"


def listing(db, title, nums, reason=False, cap=30):
    if not nums:
        return ""
    lines = [label(db, i, reason) for i in nums[:cap]]
    if len(nums) > cap:
        lines.append(f"  ... 외 {len(nums) - cap}개")
    return f"\n{title}\n" + "\n".join(lines)


def summary(db, start=0, detail=True):
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
    def nums(x):                    # detail=False(디스코드 메시지)에는 번호를 빼고 개수만, 번호는 첨부 파일에
        return f" ({rng(x)})" if detail else ""
    head = (
        f"📊 현황 (start_index={start} 기준)\n"
        f"• render 바로 가능: {len(ready)}개{nums(ready)}\n"
        f"• prepare로 대본 만들 소재: {len(need)}개{nums(need)}\n"
        f"• 폐기(rejected): {len(rej)}개{nums(rej)} → 번호! 로 되살림\n"
        f"• 영상 완료: {len(done)}개 (업로드 {sum(1 for i in done if db[i].get('youtube_id'))} / 미업로드 {sum(1 for i in done if not db[i].get('youtube_id'))})\n"
        f"권장: render count=3 정도씩, prepare count=5 정도부터"
    )
    if not detail:
        return head
    return (head
            + listing(db, "▶ render 가능 소재", ready)
            + listing(db, "▶ 대본 만들 소재", need)
            + listing(db, "▶ 영상 완료했지만 아직 안 올린 소재", [i for i in done if not db[i].get("youtube_id")])
            + listing(db, "▶ 폐기 소재", rej, reason=True))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", type=int, default=0)
    print(summary(load_db(), ap.parse_args().start))
