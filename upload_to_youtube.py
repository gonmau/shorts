# -*- coding: utf-8 -*-
"""완성된 영상을 유튜브에 '비공개(private)'로 업로드. 공개 전환은 아이폰 YouTube Studio에서 직접.

필요한 환경변수(GitHub Secrets): YT_CLIENT_ID, YT_CLIENT_SECRET, YT_REFRESH_TOKEN
"""
import argparse
import json
import os
from pathlib import Path

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

DB = Path("facts_db.json")


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
    args = ap.parse_args()

    db = json.loads(DB.read_text(encoding="utf-8"))
    yt = youtube()
    done = 0
    for item in db:
        if done >= args.limit:
            break
        path = item.get("video_path_v6")
        if item.get("status_v6") != "video_done" or item.get("youtube_id") or not path or not Path(path).exists():
            continue
        title = " ".join(filter(None, [item.get("title_line1"), item.get("title_line2")])) or item.get("topic", "")
        body = {
            "snippet": {
                "title": f"{title} #shorts"[:100],
                "description": f"{item.get('hook', '')}\n\n#shorts #세계문화 #상식",
                "categoryId": "27",
            },
            "status": {"privacyStatus": "private", "selfDeclaredMadeForKids": False},
        }
        media = MediaFileUpload(path, mimetype="video/mp4", resumable=True)
        res = yt.videos().insert(part="snippet,status", body=body, media_body=media).execute()
        item["youtube_id"] = res["id"]
        DB.write_text(json.dumps(db, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"업로드(비공개): {item.get('country')} -> {res['id']}")
        done += 1
    print(f"완료: {done}개")


if __name__ == "__main__":
    main()
