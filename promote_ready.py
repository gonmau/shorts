# -*- coding: utf-8 -*-
"""사람이 facts_db.json에 직접 넣은 소재(대본이 이미 있음)를 제작 대상(scripted)으로 인식시킵니다.

- 상태가 unverified/verified 인데 narration(대본)이 이미 있는 소재 -> scripted
  (Perplexity 등으로 검수한 대본/제목/핵심 문구/이미지 검색어를 JSON에 넣고 render만 돌리는 경우)
- 제목/핵심 문구/이미지 검색어가 비어 있으면 render 단계에서 대본 기준으로 자동 보충됩니다.
- 사실검수는 하지 않고 넣어 둔 내용을 그대로 씁니다. 폐기(rejected)된 소재는 건드리지 않습니다.
"""
import argparse

from common import load_db, save_db

MIN_CHARS = 60


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", type=int, default=0)
    args = ap.parse_args()

    db = load_db()
    n = 0
    for i, f in enumerate(db):
        if i < args.start:
            continue
        if f.get("status") not in ("unverified", "verified"):
            continue
        if f.get("video_path_v6") or f.get("status_v6") == "video_done":
            continue
        if len(str(f.get("narration") or "").strip()) < MIN_CHARS:
            continue
        f["status"] = "scripted"
        n += 1
        print(f"  [{i}] {f.get('country', '')}: 직접 넣은 대본 인식 -> 제작 대상")
    if n:
        save_db(db)
    print(f"직접 넣은 소재 인식: {n}개")


if __name__ == "__main__":
    main()
