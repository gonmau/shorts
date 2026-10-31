# -*- coding: utf-8 -*-
"""한 유튜브 영상이 여러 소재에 연결된 경우(중복 소재/잘못된 연결)를 정리한다.

 python fix_shared_links.py            # 목록만 보기 (토큰이 있으면 채널 영상과 비교해 '남길 소재'를 제안)
- 남길 소재: 채널 영상의 제목·설명과 가장 잘 맞는 소재 (채널을 못 읽으면 폐기 안 된 소재 중 번호가 앞선 것)
- 나머지 소재는 (a) 폐기 + 업로드 기록 지움 (중복 소재일 때) 또는 (b) 업로드 기록만 지움 (다른 소재가 잘못 연결됐을 때: 미업로드로 돌아가 다시 올릴 수 있음)
- 영상 파일과 유튜브 영상은 건드리지 않습니다."""
import json
import os
from pathlib import Path

UP_KEYS = ("youtube_id", "youtube_privacy", "uploaded_at", "uploaded_manually", "publish_at")


def fetch_videos():
    """채널 영상 목록 {id: video}. 토큰이 없거나 실패하면 None."""
    if not all(os.environ.get(k) for k in ("YT_CLIENT_ID", "YT_CLIENT_SECRET", "YT_REFRESH_TOKEN")):
        return None
    try:
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
        from sync_uploads import list_videos
        c = Credentials(None, refresh_token=os.environ["YT_REFRESH_TOKEN"], token_uri="https://oauth2.googleapis.com/token",
                        client_id=os.environ["YT_CLIENT_ID"], client_secret=os.environ["YT_CLIENT_SECRET"],
                        scopes=["https://www.googleapis.com/auth/youtube.readonly"])
        yt = build("youtube", "v3", credentials=c, cache_discovery=False)
        return {v["id"]: v for v in list_videos(yt)}
    except Exception:
        return None


def find_groups(db, videos=None):
    """-> [{id, video, items:[{i, score, status}], keep}] 연결 소재가 2개 이상인 영상별 묶음."""
    by = {}
    for i, f in enumerate(db):
        if f.get("youtube_id"):
            by.setdefault(f["youtube_id"], []).append(i)
    out = []
    for yid, ix in by.items():
        if len(ix) < 2:
            continue
        v = (videos or {}).get(yid)
        items = []
        for i in ix:
            sc = None
            if v:
                try:
                    from sync_uploads import score
                    sc = round(score(db[i], v)[0], 2)
                except Exception:
                    sc = None
            items.append({"i": i, "score": sc, "status": db[i].get("status", "")})
        live = [x for x in items if x["status"] != "rejected"] or items
        try:                                            # 나라와 주제가 어긋난 소재(예: 네덜란드 + 영국 음식)는 남길 후보에서 뒤로 미룬다
            from check_country import analyze
            ok_ = [x for x in live if analyze(db[x["i"]])[0] == "ok"]
            live = ok_ or live
        except Exception:
            pass
        if v and any(x["score"] is not None for x in live):
            keep = max(live, key=lambda x: ((x["score"] or 0), -x["i"]))["i"]
        else:
            keep = min(x["i"] for x in live)
        out.append({"id": yid, "video": v, "items": items, "keep": keep})
    return out


def apply_plan(db, groups, keeps, reject=True):
    """keeps: {영상id: 남길 소재 번호}. 나머지 소재의 업로드 기록을 지우고(reject면 폐기도). 처리한 번호 목록을 돌려준다."""
    done = []
    for g in groups:
        keep = keeps.get(g["id"], g["keep"])
        for x in g["items"]:
            i = x["i"]
            if i == keep:
                continue
            f = db[i]
            for k in UP_KEYS:
                f.pop(k, None)
            if reject:
                f["status"] = "rejected"
                f["reject_reason"] = f"중복 소재 (영상 {g['id']} 은 [{keep}] 소재와 연결)"
            done.append(i)
    return done


def main():
    db = json.loads(Path("facts_db.json").read_text(encoding="utf-8"))
    vids = fetch_videos()
    gs = find_groups(db, vids)
    print(f"공유 연결 {len(gs)}개 (채널 비교: {'함' if vids else '못 함 - 번호 기준으로 제안'})")
    for g in gs:
        t = g["video"]["title"][:40] if g["video"] else ""
        print(f"- https://youtu.be/{g['id']} {t}")
        for x in g["items"]:
            f = db[x["i"]]
            print(f"    [{x['i']}] {f.get('country', '')} {str(f.get('topic', ''))[:30]} ({x['status']}, 일치 {x['score']}){'  ← 남김' if x['i'] == g['keep'] else ''}")


if __name__ == "__main__":
    main()
