# -*- coding: utf-8 -*-
"""이미 업로드된 영상의 설명란만 현재 DB 기준(사진 출처 포함)으로 다시 써서 수정합니다. 제목/태그/공개설정은 건드리지 않습니다.

사용: python update_description.py --indexes 109,110   (youtube_id 가 있는 소재만 처리)
필요: YT_CLIENT_ID, YT_CLIENT_SECRET, YT_REFRESH_TOKEN. 토큰에 영상 수정 권한(youtube 또는 youtube.force-ssl)이 있어야 합니다.
      업로드 전용 토큰(youtube.upload)이면 403이 나며, 그땐 출력된 설명을 YouTube Studio에서 직접 붙여넣으세요.
"""
import argparse
import json
import os
import sys
from pathlib import Path

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from common import youtube_meta

DB = Path("facts_db.json")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--indexes", required=True)
    args = ap.parse_args()
    idxs = [int(x) for x in args.indexes.split(",") if x.strip().isdigit()]
    db = json.loads(DB.read_text(encoding="utf-8"))
    creds = Credentials(None, refresh_token=os.environ["YT_REFRESH_TOKEN"], token_uri="https://oauth2.googleapis.com/token",
                        client_id=os.environ["YT_CLIENT_ID"], client_secret=os.environ["YT_CLIENT_SECRET"])
    yt = build("youtube", "v3", credentials=creds)
    bad = 0
    for i in idxs:
        item = db[i]
        vid = item.get("youtube_id")
        if not vid:
            print(f"{i}: 업로드 전이라 건너뜀 (업로드 때 새 설명이 자동 적용됩니다)")
            continue
        _, desc = youtube_meta(item)
        try:
            cur = yt.videos().list(part="snippet", id=vid).execute()["items"]
            if not cur:
                print(f"{i}: 유튜브에서 영상을 찾지 못함 ({vid})"); bad += 1; continue
            sn = cur[0]["snippet"]
            sn["description"] = desc
            yt.videos().update(part="snippet", body={"id": vid, "snippet": sn}).execute()
            print(f"{i} {item.get('country', '')}: 설명 수정 완료 ({vid})")
        except HttpError as e:
            bad += 1
            print(f"{i}: 실패 {e.resp.status} - 토큰에 영상 수정 권한이 없을 수 있습니다. 아래 설명을 Studio에서 직접 붙여넣으세요.\n---\n{desc}\n---")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
