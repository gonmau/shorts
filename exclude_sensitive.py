# -*- coding: utf-8 -*-
"""아직 영상으로 만들지 않은 소재 중 성·민감 단어가 들어간 것을 rejected 로 돌린다 (이미 영상이 된 소재는 건드리지 않고 목록만 보여준다).
  python exclude_sensitive.py          # 실제로 제외
  python exclude_sensitive.py --dry    # 목록만 확인"""
import argparse
import json
from pathlib import Path

from sensitive import is_sensitive

DB = Path("facts_db.json")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()
    db = json.loads(DB.read_text(encoding="utf-8"))
    changed, made = 0, []
    for i, f in enumerate(db):
        w = is_sensitive(f)
        if not w:
            continue
        if f.get("confidence") == "user" or f.get("narration_user_edited"):
            continue          # 직접 쓴/고친 대본은 사용자가 정한 것이므로 건드리지 않음
        made_video = f.get("status") == "video_done" or f.get("youtube_id") or f.get("status_v6") == "video_done"
        if made_video:
            made.append((i, f, w))
        elif f.get("status") != "rejected":
            print(f"제외: [{i}] {f.get('country')} / {str(f.get('topic'))[:40]} (단어: {w})")
            if not a.dry:
                f["status"] = "rejected"
                f["reject_reason"] = f"성/민감 소재 자동 제외({w})"
            changed += 1
    if changed and not a.dry:
        DB.write_text(json.dumps(db, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"제외 {changed}개" + (" (dry-run)" if a.dry else ""))
    if made:
        print(f"참고: 이미 영상이 된 소재 중 해당 단어가 있는 것 {len(made)}개 (그대로 둠)")
        for i, f, w in made:
            print(f"  [{i}] {f.get('country')} / {str(f.get('topic'))[:40]} · {w} · {f.get('youtube_privacy', '-')}")


if __name__ == "__main__":
    main()
