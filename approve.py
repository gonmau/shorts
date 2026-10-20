# -*- coding: utf-8 -*-
"""미검증(unverified) 소재를 대본 생성 대상(verified)으로 승인합니다.
start 번호 이상, 대본이 아직 없는 소재 중 앞에서 limit개. (generate_script.py는 verified 소재만 대본을 만듭니다)

사용: python approve.py --limit 3 --start 183
"""
import argparse

from common import load_db, save_db

MIN_CHARS = 60


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=3)
    ap.add_argument("--start", type=int, default=0)
    args = ap.parse_args()

    db = load_db()
    k, done = 0, []
    # 이미 verified인데 대본이 없는 소재가 있으면 그것부터 대본 대상이 되므로, 그 개수만큼 덜 승인한다
    waiting = sum(1 for i, f in enumerate(db) if i >= args.start and f.get("status") == "verified"
                  and len(str(f.get("narration") or "").strip()) < MIN_CHARS)
    room = max(0, args.limit - waiting)
    for i, f in enumerate(db):
        if k >= room:
            break
        if i < args.start or f.get("status") != "unverified":
            continue
        if len(str(f.get("narration") or "").strip()) >= MIN_CHARS:
            continue  # 대본이 이미 있으면 promote_ready.py가 처리
        f["status"] = "verified"
        done.append(i)
        k += 1
    if k:
        save_db(db)
    print(f"자동 승인: {k}개 {done} (이미 대본 대기 중 {waiting}개)")


if __name__ == "__main__":
    main()
