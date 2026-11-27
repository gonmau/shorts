"""재생목록 생성/영상 추가.  (YT_* 시크릿 필요, 토큰에 youtube 권한 필요)
  python playlist.py create --title "제목" [--desc "설명"] [--privacy public|unlisted|private]
  python playlist.py add --playlist PLxxxx --videos id1,id2,...
"""
import argparse, sys
from upload_to_youtube import youtube


def create(yt, title, desc, privacy):
    r = yt.playlists().insert(part="snippet,status", body={
        "snippet": {"title": title, "description": desc},
        "status": {"privacyStatus": privacy}}).execute()
    print(f"✅ 재생목록 생성: {r['id']}  https://www.youtube.com/playlist?list={r['id']}")
    return r["id"]


def add(yt, pl, vids):
    for v in vids:
        try:
            yt.playlistItems().insert(part="snippet", body={"snippet": {
                "playlistId": pl, "resourceId": {"kind": "youtube#video", "videoId": v}}}).execute()
            print(f"  + {v}")
        except Exception as e:
            print(f"  ✗ {v}: {str(e)[:150]}")


_CACHE = {}


def find_or_create(yt, name, privacy="public", create_missing=True):
    """내 재생목록에서 제목이 같은 것을 찾고(없으면 만든다). ID 반환."""
    if name in _CACHE:
        return _CACHE[name]
    tok = None
    while True:
        r = yt.playlists().list(part="snippet", mine=True, maxResults=50, pageToken=tok).execute()
        for p in r.get("items", []):
            if p["snippet"]["title"].strip() == name.strip():
                _CACHE[name] = p["id"]; return p["id"]
        tok = r.get("nextPageToken")
        if not tok:
            break
    if not create_missing:
        return None
    _CACHE[name] = create(yt, name, "", privacy)
    return _CACHE[name]


def add_to_named(yt, name, video_id):
    """업로드 직후 호출: 이름으로 재생목록을 찾아 영상 추가. 실패해도 업로드는 영향 없음."""
    try:
        pid = find_or_create(yt, name)
        add(yt, pid, [video_id])
    except Exception as e:
        print(f"  ⚠ 재생목록 추가 실패({name}): {str(e)[:150]}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("cmd", choices=["create", "add"])
    ap.add_argument("--title", default=""); ap.add_argument("--desc", default="")
    ap.add_argument("--privacy", default="public"); ap.add_argument("--playlist", default="")
    ap.add_argument("--videos", default="")
    a = ap.parse_args(); yt = youtube()
    if a.cmd == "create":
        if not a.title: sys.exit("--title 필요")
        pid = create(yt, a.title, a.desc, a.privacy)
        if a.videos: add(yt, pid, [v.strip() for v in a.videos.split(",") if v.strip()])
    else:
        add(yt, a.playlist, [v.strip() for v in a.videos.split(",") if v.strip()])
