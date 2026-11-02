# -*- coding: utf-8 -*-
"""새로 만든 소재를 디스코드로 알린다 (번호·나라·주제 + 웹 UI 바로가기 링크).
  python notify_topics.py --before <소재 보충 전 소재 개수> --ch ko|en
환경변수: DISCORD_WEBHOOK_URL, WEB_UI_URL(웹 UI 주소, 없으면 GitHub DB 링크), GITHUB_REPOSITORY"""
import argparse
import json
import os

from notify_discord import post_long


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--before", type=int, required=True)
    ap.add_argument("--ch", default="ko")
    a = ap.parse_args()
    url = os.environ.get("DISCORD_WEBHOOK_URL", "")
    if not url:
        print("DISCORD_WEBHOOK_URL 없음 → 알림 생략"); return
    db = json.load(open("facts_db.json", encoding="utf-8"))
    new = [(i, f) for i, f in enumerate(db) if i >= a.before and f.get("status") == "unverified"]
    if not new:
        print("새 소재 없음 → 알림 생략"); return
    pend = sum(1 for f in db if f.get("status") == "unverified")
    ver = sum(1 for f in db if f.get("status") == "verified")
    lines = [f"📝 **새 소재 {len(new)}개** ({'한글' if a.ch == 'ko' else '영어'} 채널) · 승인 대기 {pend}개 · 승인됨 {ver}개"]
    for i, f in new[:25]:
        topic = " ".join(str(f.get("topic") or "").split())
        lines.append(f"`{i}` {f.get('label') or f.get('country', '')} — {topic[:70]}")
    if len(new) > 25:
        lines.append(f"… 외 {len(new) - 25}개")
    web = os.environ.get("WEB_UI_URL", "").strip()
    if web:
        lines.append(f"👉 검수·승인: {web.rstrip('/')}/?ch={a.ch}")
    else:
        repo = os.environ.get("GITHUB_REPOSITORY", "")
        lines.append(f"👉 DB: https://github.com/{repo}/blob/main/facts_db.json  (저장소 변수 WEB_UI_URL 에 웹 UI 주소를 넣으면 검수 링크가 나옵니다)")
    post_long(url, "\n".join(lines))
    print(f"새 소재 {len(new)}개 디스코드 알림 전송")


if __name__ == "__main__":
    main()
