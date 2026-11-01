#!/usr/bin/env python3
"""Actions 커밋 단계용: 원격(PC에서 올린) facts_db.json 과 이번 실행 결과를 소재 단위로 병합해 facts_db.json 에 쓴다.
  python merge_remote_db.py <원격 DB 파일> <이번 실행 DB 파일>
충돌 칸은 원격(PC에서 직접 고친 값)을 따르고, 상태는 더 진행된 쪽, 폐기는 영상완료보다 우선 (sync_db 규칙)."""
import json, sys
import sync_db


def main():
    theirs, mine = sys.argv[1], sys.argv[2]
    try:
        G = json.load(open(theirs, encoding="utf-8"))
    except Exception as e:
        print(f"원격 DB 읽기 실패({e}) → 이번 실행 결과 그대로 둠"); return
    L = json.load(open(mine, encoding="utf-8"))
    merged, report, warns = sync_db.merge_all(G, L, "github", "github", "github")
    for w in warns:
        print("⚠️ " + w)
    n_conf = sum(len(c) for *_, c in report)
    print(f"병합: 원격 {len(G)}개 + 이번 실행 {len(L)}개 → {len(merged)}개 소재 (차이 {len(report)}개, 충돌 {n_conf}칸은 원격 값 사용)")
    json.dump(merged, open("facts_db.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
