# -*- coding: utf-8 -*-
"""디스코드 알림: 상태 + 아티팩트 링크 + 영상별 유튜브 제목/설명(각각 별도 메시지라 길게 눌러 바로 복사).

환경변수: DISCORD_WEBHOOK_URL, JOB_STATUS, STAGE, RUN_URL, ART_URL, REVIEW_URL
"""
import json
import os
import urllib.request
from pathlib import Path

import requests

from common import load_db, youtube_meta


def post(url, text):
    req = urllib.request.Request(
        url,
        data=json.dumps({"content": text[:1990]}).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": "culture-shorts-bot"},
    )
    try:
        urllib.request.urlopen(req, timeout=20)
    except Exception as e:
        print("디스코드 전송 실패:", e)


def post_image(url, path, text=""):
    """썸네일 PNG를 디스코드에 첨부 전송 (길게 눌러 저장)."""
    try:
        with open(path, "rb") as f:
            requests.post(url, data={"content": text[:1900]}, files={"file": (Path(path).name, f, "image/png")}, timeout=60)
    except Exception as e:
        print("썸네일 전송 실패:", e)


def built_items():
    out = []
    if not Path("videos").exists():
        return out
    names = {p.name for p in Path("videos").glob("*.mp4")}
    try:
        db = load_db()
    except Exception:
        return out
    for i, item in enumerate(db):
        vp = item.get("video_path_v6")
        if vp and Path(vp).name in names:
            out.append((Path(vp).name, item))
    return out


def main():
    url = os.environ["DISCORD_WEBHOOK_URL"]
    st, stage = os.environ.get("JOB_STATUS", ""), os.environ.get("STAGE", "")
    run_url = os.environ.get("RUN_URL", "")

    if st != "success":
        post(url, f"❌ 쇼츠 파이프라인 실패 ({stage})\n로그: {run_url}")
        return
    if stage == "prepare":
        post(url, f"📝 준비 완료 - review.txt에서 제목/핵심 문구를 고친 뒤 render 실행\n"
                  f"{os.environ.get('REVIEW_URL', '')}\n실행: {run_url}")
        return

    items = built_items()
    art = os.environ.get("ART_URL") or run_url
    post(url, f"✅ 영상 {len(items)}개 완료 ({stage})\n"
              f"다운로드(zip, 14일 보관): {art}\n실행: {run_url}")
    for name, item in items:
        title, desc = youtube_meta(item)
        post(url, f"🎬 {name} - 아래 두 메시지를 길게 눌러 '텍스트 복사'")
        post(url, title)   # 제목만
        post(url, desc)    # 설명만
        r = item.get("fact_risk")
        notes = item.get("fact_issues") or []
        if r or notes:
            icon = {"low": "🟢", "medium": "🟡", "high": "🔴"}.get(r, "⚪")
            post(url, f"{icon} 사실 검수 위험도: {r or '-'}" + ("\n⚠️ 고친/의심한 점:\n" + "\n".join(f"- {n}" for n in notes) if notes else "")
                 + (f"\n🔎 확인 검색어: {item['verify_note']}" if item.get("verify_note") else ""))
        th = Path("thumbnails") / (Path(name).stem + ".png")
        if th.exists():
            post_image(url, th, "🖼 썸네일 (길게 눌러 저장)")


if __name__ == "__main__":
    main()
