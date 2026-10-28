# -*- coding: utf-8 -*-
"""완성된 영상을 유튜브에 '비공개(private)'로 업로드. 공개 전환은 YouTube Studio에서 직접,
또는 환경변수 PUBLISH_SLOTS(한국시간, 예: 07:00,19:30)를 주면 그 시각에 자동 공개되도록 예약(publishAt)합니다.
PUBLISH_SLOTS=off 이면 예약 없이 비공개로만 올립니다.

필요한 환경변수(GitHub Secrets): YT_CLIENT_ID, YT_CLIENT_SECRET, YT_REFRESH_TOKEN
"""
import argparse
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from common import youtube_meta, youtube_tags

DB = Path("facts_db.json")

def parse_slots(text):
    """'07:00,19:30' (한국시간) -> [(7, 0), (19, 30)]. 비었거나 off 면 예약 공개를 쓰지 않음(비공개로만 올림)."""
    out = []
    for t in str(text or "").replace(" ", "").split(","):
        if not t or t.lower() == "off":
            continue
        try:
            h, m = t.split(":")
            out.append((int(h), int(m)))
        except ValueError:
            print(f"예약 시각 형식 오류(무시): {t}")
    return sorted(out)


def next_slot(slots, used, now, kst):
    """지금부터 15분 이후의 가장 이른 빈 슬롯(한국시간)을 UTC ISO 문자열로. 이미 쓴 슬롯은 건너뜀."""
    for add in range(0, 8):
        day = (now + timedelta(days=add)).astimezone(kst).date()
        for h, m in slots:
            t = datetime(day.year, day.month, day.day, h, m, tzinfo=kst)
            iso = t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
            if t > now + timedelta(minutes=15) and iso not in used:
                return iso
    return None


def youtube():
    creds = Credentials(
        None,
        refresh_token=os.environ["YT_REFRESH_TOKEN"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=os.environ["YT_CLIENT_ID"],
        client_secret=os.environ["YT_CLIENT_SECRET"],
        scopes=["https://www.googleapis.com/auth/youtube.upload"],
    )
    return build("youtube", "v3", credentials=creds)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=5)
    ap.add_argument("--daily-max", type=int, default=2, help="하루(한국시간) 최대 업로드 수")
    args = ap.parse_args()

    db = json.loads(DB.read_text(encoding="utf-8"))
    yt = youtube()
    done = 0
    kst = timezone(timedelta(hours=9))
    today = datetime.now(kst).strftime("%Y-%m-%d")
    slots = parse_slots(os.environ.get("PUBLISH_SLOTS", ""))
    now = datetime.now(kst)
    used = {str(f.get("publish_at")) for f in db if f.get("publish_at")}
    already = sum(1 for f in db if str(f.get("uploaded_at", "")).startswith(today))
    room = max(0, args.daily_max - already)
    print(f"오늘 업로드 {already}개 / 상한 {args.daily_max}개 -> 추가 가능 {room}개")
    limit = min(args.limit, room)
    for item in db:
        if done >= limit:
            break
        path = item.get("video_path_v6")
        if item.get("status_v6") != "video_done" or item.get("youtube_id") or not path or not Path(path).exists():
            continue
        title, description = youtube_meta(item)
        body = {
            "snippet": {"title": title, "description": description, "categoryId": "27", "tags": youtube_tags(item)},
            "status": {"privacyStatus": "private", "selfDeclaredMadeForKids": False,
                       "containsSyntheticMedia": True,                                   # '변경되거나 합성된 콘텐츠(AI 사용)': 예
                       "paidProductPlacementDetails": {"hasPaidProductPlacement": False}},   # 유료 프로모션: 아니요
        }
        slot = next_slot(slots, used, now, kst) if slots else None
        if slot:
            body["status"]["publishAt"] = slot      # private + publishAt = 그 시각에 자동 공개
        media = MediaFileUpload(path, mimetype="video/mp4", resumable=True)
        res = yt.videos().insert(part="snippet,status", body=body, media_body=media).execute()
        item["youtube_id"] = res["id"]
        item["uploaded_at"] = datetime.now(kst).isoformat()
        if slot:
            item["publish_at"] = slot
            used.add(slot)
        DB.write_text(json.dumps(db, ensure_ascii=False, indent=2), encoding="utf-8")
        when = f" (예약 공개 {datetime.fromisoformat(slot.replace('Z', '+00:00')).astimezone(kst):%m-%d %H:%M} KST)" if slot else ""
        print(f"업로드(비공개{'→예약' if slot else ''}): {item.get('country')} -> {res['id']}{when}")
        done += 1
    print(f"완료: {done}개")


if __name__ == "__main__":
    main()
