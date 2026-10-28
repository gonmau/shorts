# -*- coding: utf-8 -*-
"""채널에 이미 올라간 영상(수동 업로드 포함)을 facts_db.json 의 '미업로드' 소재와 연결한다.

- 채널 업로드 목록(비공개 포함)을 읽어 제목/설명으로 소재를 찾고 youtube_id, youtube_privacy, uploaded_at 을 채운다.
- 확실한 것(설명에 훅 문장이 그대로 있거나 제목이 거의 같음)만 연결하고, 애매한 것은 목록으로만 보여준다.
- 이미 연결된 소재는 공개 상태(youtube_privacy)만 새로 고친다.
  python sync_uploads.py            # 연결하고 저장
  python sync_uploads.py --dry      # 보기만
필요: YT_CLIENT_ID, YT_CLIENT_SECRET, YT_REFRESH_TOKEN (youtube.readonly 권한 포함)"""
import argparse
import difflib
import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

DB = Path("facts_db.json")
KST = timezone(timedelta(hours=9))


def n(s):
    return re.sub(r"[^0-9a-z가-힣]", "", str(s or "").lower())


def score(item, v):
    """(점수, 이유). 1.0 = 설명에 훅이 그대로 있음."""
    desc = n(v.get("description"))
    hook = n(item.get("hook"))
    if len(hook) >= 12 and hook[:40] in desc:
        return 1.0, "설명에 훅 일치"
    t1 = n((item.get("title_line1") or "") + (item.get("title_line2") or ""))
    yt = re.sub(r"^korea", "", n(v.get("title")))
    cands = [t1, n(item.get("topic")), n(item.get("title"))]
    best = max((difflib.SequenceMatcher(None, c, yt).ratio() for c in cands if c), default=0.0)
    return best, "제목 유사"


def match(db, vids, thr=0.75, margin=0.1):
    have = {f.get("youtube_id") for f in db if f.get("youtube_id")}
    free = [v for v in vids if v["id"] not in have]
    todo = [(i, f) for i, f in enumerate(db)
            if not f.get("youtube_id") and (f.get("status_v6") == "video_done" or f.get("status") == "video_done")]
    pairs = []
    for i, f in todo:
        sc = sorted(((score(f, v)[0], v) for v in free), key=lambda x: -x[0])
        if sc:
            pairs.append((sc[0][0], i, sc[0][1], sc[1][0] if len(sc) > 1 else 0.0))
    pairs.sort(key=lambda p: -p[0])
    used, ok, unsure = set(), [], []
    for s, i, v, second in pairs:
        if s >= thr and s - second >= margin and v["id"] not in used:
            used.add(v["id"])
            ok.append((i, v, s))
        elif s >= 0.5:
            unsure.append((i, v, s))
    return ok, unsure


def list_videos(yt):
    ch = yt.channels().list(part="contentDetails", mine=True).execute()["items"][0]
    pl = ch["contentDetails"]["relatedPlaylists"]["uploads"]
    ids, tok = [], None
    while True:
        r = yt.playlistItems().list(part="contentDetails", playlistId=pl, maxResults=50, pageToken=tok).execute()
        ids += [x["contentDetails"]["videoId"] for x in r["items"]]
        tok = r.get("nextPageToken")
        if not tok:
            break
    out = []
    for k in range(0, len(ids), 50):
        r = yt.videos().list(part="snippet,status", id=",".join(ids[k:k + 50])).execute()
        for x in r["items"]:
            sn, st = x["snippet"], x["status"]
            out.append({"id": x["id"], "title": sn.get("title", ""), "description": sn.get("description", ""),
                        "published": sn.get("publishedAt", ""), "privacy": st.get("privacyStatus", ""),
                        "publishAt": st.get("publishAt", "")})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()
    for k in ("YT_CLIENT_ID", "YT_CLIENT_SECRET", "YT_REFRESH_TOKEN"):
        if not os.environ.get(k):
            raise SystemExit(f"{k} 가 없습니다 (GitHub Secrets 확인)")
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    c = Credentials(None, refresh_token=os.environ["YT_REFRESH_TOKEN"], token_uri="https://oauth2.googleapis.com/token",
                    client_id=os.environ["YT_CLIENT_ID"], client_secret=os.environ["YT_CLIENT_SECRET"],
                    scopes=["https://www.googleapis.com/auth/youtube.readonly"])
    yt = build("youtube", "v3", credentials=c, cache_discovery=False)
    vids = list_videos(yt)
    print(f"채널 영상 {len(vids)}개")
    db = json.loads(DB.read_text(encoding="utf-8"))
    by_id = {v["id"]: v for v in vids}

    changed = 0
    for f in db:                                   # 이미 연결된 소재: 공개 상태 새로 고침
        v = by_id.get(f.get("youtube_id"))
        if v and f.get("youtube_privacy") != v["privacy"]:
            f["youtube_privacy"] = v["privacy"]
            changed += 1
    ok, unsure = match(db, vids)
    for i, v, s in ok:
        f = db[i]
        f["youtube_id"] = v["id"]
        f["youtube_privacy"] = v["privacy"]
        try:
            f["uploaded_at"] = datetime.fromisoformat(v["published"].replace("Z", "+00:00")).astimezone(KST).strftime("%Y-%m-%d")
        except ValueError:
            f["uploaded_at"] = ""
        f["uploaded_manually"] = True
        print(f"연결: [{i}] {f.get('country')} / {f.get('title_line1', '')} {f.get('title_line2', '')} -> {v['id']} ({v['privacy']}, 일치도 {s:.2f})")
    if unsure:
        print(f"\n애매해서 연결하지 않은 것 {len(unsure)}개 (직접 확인):")
        for i, v, s in unsure:
            print(f"  [{i}] {db[i].get('country')} / {db[i].get('title_line1', '')} {db[i].get('title_line2', '')} ?= {v['title'][:40]} ({v['id']}, {s:.2f})")
    left = sum(1 for f in db if not f.get("youtube_id") and (f.get("status_v6") == "video_done" or f.get("status") == "video_done"))
    print(f"\n연결 {len(ok)}개 · 공개상태 갱신 {changed}개 · 아직 연결 안 된 완성 소재 {left}개")
    if (ok or changed) and not a.dry:
        DB.write_text(json.dumps(db, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
