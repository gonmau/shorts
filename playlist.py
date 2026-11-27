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
