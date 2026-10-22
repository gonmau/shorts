# -*- coding: utf-8 -*-
"""내 채널 영상 제목/공개 상태를 한 번에 정리해 CSV로 저장 (PC에서 실행, 읽기 전용).

사용법:  python list_channel_videos.py client_secret.json [--token token_ko.json] [--out videos_ko.csv]
 - 처음 한 번 브라우저가 열리면 '채널 주인 계정'으로 로그인/허용 (읽기 전용 권한 youtube.readonly)
 - 로그인 결과는 --token 파일에 저장돼 다음부터는 묻지 않음 (채널마다 다른 파일명을 쓰세요)
 - facts_db.json 이 같은 폴더에 있으면 소재 번호/국가도 같이 붙임
필요: pip install google-api-python-client google-auth-oauthlib
"""
import argparse
import csv
import json
import re
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/youtube.readonly"]
PRIV_KO = {"public": "공개", "private": "비공개", "unlisted": "일부공개"}


def get_creds(secret, token_path):
    creds = None
    tp = Path(token_path)
    if tp.exists():
        creds = Credentials.from_authorized_user_file(str(tp), SCOPES)
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    if not creds or not creds.valid:
        creds = InstalledAppFlow.from_client_secrets_file(secret, SCOPES).run_local_server(port=0)
    tp.write_text(creds.to_json(), encoding="utf-8")
    return creds


def fetch_all(yt):
    ch = yt.channels().list(part="contentDetails,snippet", mine=True).execute()["items"][0]
    print(f"채널: {ch['snippet']['title']}")
    pl = ch["contentDetails"]["relatedPlaylists"]["uploads"]
    ids, token = [], None
    while True:
        r = yt.playlistItems().list(part="contentDetails", playlistId=pl, maxResults=50, pageToken=token).execute()
        ids += [it["contentDetails"]["videoId"] for it in r["items"]]
        token = r.get("nextPageToken")
        if not token:
            break
    out = []
    for i in range(0, len(ids), 50):
        r = yt.videos().list(part="snippet,status,statistics,contentDetails", id=",".join(ids[i:i + 50])).execute()
        out += r["items"]
    return out


def secs(iso):
    m = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso or "")
    h, mi, s = (int(x or 0) for x in m.groups()) if m else (0, 0, 0)
    return h * 3600 + mi * 60 + s


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("secret")
    ap.add_argument("--token", default="yt_readonly_token.json")
    ap.add_argument("--out", default="videos.csv")
    ap.add_argument("--db", default="facts_db.json")
    a = ap.parse_args()

    items = fetch_all(build("youtube", "v3", credentials=get_creds(a.secret, a.token)))
    dbmap = {}
    if Path(a.db).exists():
        for i, f in enumerate(json.load(open(a.db, encoding="utf-8"))):
            if f.get("youtube_id"):
                dbmap[f["youtube_id"]] = (i, f.get("label") or f.get("country", ""))
    rows = []
    for v in items:
        st, sn = v["status"], v["snippet"]
        d = secs(v["contentDetails"].get("duration"))
        i, c = dbmap.get(v["id"], ("", ""))
        rows.append({
            "공개상태": PRIV_KO.get(st.get("privacyStatus"), st.get("privacyStatus")),
            "예약공개": st.get("publishAt", "")[:16].replace("T", " "),
            "제목": sn["title"], "업로드일": sn["publishedAt"][:10],
            "종류": "쇼츠" if d <= 180 else "롱폼", "길이(초)": d,
            "조회수": v.get("statistics", {}).get("viewCount", ""),
            "소재번호": i, "국가": c, "링크": f"https://youtu.be/{v['id']}", "영상ID": v["id"],
        })
    order = {"공개": 0, "일부공개": 1, "비공개": 2}
    rows.sort(key=lambda r: (order.get(r["공개상태"], 9), r["업로드일"]))
    with open(a.out, "w", newline="", encoding="utf-8-sig") as f:   # utf-8-sig: 엑셀에서 한글 안 깨짐
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else ["제목"])
        w.writeheader()
        w.writerows(rows)
    cnt = {}
    for r in rows:
        cnt[r["공개상태"]] = cnt.get(r["공개상태"], 0) + 1
    print(f"총 {len(rows)}개 · " + " · ".join(f"{k} {n}" for k, n in cnt.items()))
    cur = None
    for r in rows:
        if r["공개상태"] != cur:
            cur = r["공개상태"]
            print(f"\n=== {cur} ===")
        print(f"{r['업로드일']} [{r['종류']}] {r['제목']}" + (f"  (소재 {r['소재번호']})" if r["소재번호"] != "" else ""))
    print(f"\n저장: {a.out}")


if __name__ == "__main__":
    main()
