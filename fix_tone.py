# -*- coding: utf-8 -*-
"""딱딱한 어투('~한다.' 체)의 쇼츠 대본을 존댓말 구어체로 고친다 (한국어 채널 전용).
  python fix_tone.py --list [--start 0]                 # 딱딱한 대본 목록만
  python fix_tone.py --indexes 24,178 [--dry-run]       # 그 소재만 고침
  python fix_tone.py --all [--start 106] [--limit 20]   # 딱딱한 대본 전부(개수 제한)
고치면 apply_review.py 와 같은 경로로 저장되어, 그 소재의 음성은 지워지고(다시 만들기 필요) 이미지 검색어는 새 대본 기준으로 다시 만들어집니다.
사실·문장 수·순서는 그대로, 말투만 바뀝니다. 문장 수가 달라지거나 AI가 실패하면 원본을 그대로 둡니다."""
import argparse
import os
import subprocess
import sys

import ko_text as KT
import longform_script as LS
from common import load_db


def stiff_list(db, start=0, thr=0.3):
    return [(i, KT.plain_ratio(f.get("narration", ""))) for i, f in enumerate(db)
            if i >= start and f.get("status") != "rejected" and str(f.get("narration", "")).strip() and KT.plain_ratio(f.get("narration", "")) >= thr]


def main():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--indexes", default="")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--limit", type=int, default=20)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    if LS.IS_EN:
        raise SystemExit("한국어 채널 전용입니다.")
    db = load_db()
    found = stiff_list(db, a.start)
    if a.list or not (a.indexes or a.all):
        print(f"딱딱한 어투 대본 {len(found)}개 (start {a.start} 이상, '~한다.' 체 문장 30% 이상):")
        for i, r in found:
            print(f"  {i} {db[i].get('country', '')} - {db[i].get('topic', '')}  ({r:.0%})")
        return
    if a.indexes:
        from build_longform import parse_indexes
        targets = [i for i in parse_indexes(a.indexes) if 0 <= i < len(db) and str(db[i].get("narration", "")).strip()]
    else:
        targets = [i for i, _ in found][:a.limit]
    client, models = LS.client_models()
    if not client:
        raise SystemExit("GROQ_API_KEY가 없어 고칠 수 없습니다.")
    blocks, skipped = [], []
    for i in targets:
        old = db[i]["narration"]
        new = LS.soften(client, models, old)
        if new == old:
            skipped.append(i)
            print(f"  {i}: 고치지 못함 (문장 수가 달라지거나 AI 실패) - 원본 유지")
            continue
        print(f"  {i} {db[i].get('country', '')}: {KT.plain_ratio(old):.0%} -> {KT.plain_ratio(new):.0%}")
        print(f"      전: {old[:80]}...\n      후: {new[:80]}...")
        blocks.append(f"=== [{i}] ===\n" + "\n".join(f"대본[{n}]: {t}" for n, t in enumerate(LS.split_sentences(new), 1)))
    if a.dry_run or not blocks:
        print(f"\n{'(dry-run) ' if a.dry_run else ''}고칠 대본 {len(blocks)}개, 못 고친 것 {len(skipped)}개")
        return
    with open("review_tmp_edit.txt", "w", encoding="utf-8") as f:
        f.write("\n\n".join(blocks) + "\n")
    r = subprocess.run([sys.executable, "apply_review.py", "--file", "review_tmp_edit.txt"], capture_output=True, text=True, encoding="utf-8",
                       errors="replace", env=dict(os.environ, PYTHONIOENCODING="utf-8"))
    try:
        os.remove("review_tmp_edit.txt")
    except OSError:
        pass
    print((r.stdout + r.stderr).strip()[-600:])
    print(f"\n✅ {len(blocks)}개 대본을 존댓말로 고쳐 저장했습니다. 음성/영상은 다시 만들어야 합니다 (redo). 못 고친 것 {len(skipped)}개")


if __name__ == "__main__":
    main()
