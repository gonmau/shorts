# -*- coding: utf-8 -*-
"""이미 업로드한 영상의 썸네일만 다시 만들어 그 영상에 바로 적용한다 (GitHub Actions 'culture-thumbnail' 용, 폰에서 실행 가능).

사용: python thumb_redo.py --indexes 495,496 [--font blackhan] [--text1 "..."] [--text2 "..."] [--tag-text "..."] [--style hook] [--no-upload]
- 글꼴·문구를 주면 이번 실행에서만 적용(DB 저장 안 함). 주지 않으면 영상별 설정(thumb_opts)과 기본 설정(FONT_THUMB)을 따른다.
- 배경: 직접 올린 배경 > thumb_bg/번호.jpg(영상 제작 때 보관) > 장면 이미지. 없으면 단색 배경이 되므로 만들지 않고 건너뛴다.
- 결과 PNG는 디스코드로도 보낸다 (DISCORD_WEBHOOK_URL)."""
import argparse
import io
import os
import time
from pathlib import Path

from common import load_db, visual_dir
import make_thumbnail as mt

BASE = Path(__file__).resolve().parent


def has_background(idx, item):
    if (item.get("thumb_image") and Path(item["thumb_image"]).exists()) or (BASE / "thumb_bg" / f"{idx:03d}.jpg").exists():
        return True
    return bool(sorted(visual_dir(BASE, idx, item).glob("scene_*.png")))


def to_jpeg(png):
    from PIL import Image
    im = Image.open(png).convert("RGB")
    buf = io.BytesIO(); q = 92
    while True:
        buf.seek(0); buf.truncate(); im.save(buf, "JPEG", quality=q)
        if buf.tell() < 1_900_000 or q <= 50:
            break
        q -= 10
    out = Path(png).with_suffix(".jpg"); out.write_bytes(buf.getvalue())
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--indexes", required=True)
    ap.add_argument("--channel", default=os.environ.get("CHANNEL_NAME") or "gonmauY")
    ap.add_argument("--handle", default="@gonmauY")
    ap.add_argument("--style", default=os.environ.get("THUMB_STYLE", "hook"), choices=["hook", "pop", "classic"])
    ap.add_argument("--font", default="")
    ap.add_argument("--text1", default="")
    ap.add_argument("--text2", default="")
    ap.add_argument("--tag-text", default="")
    ap.add_argument("--no-upload", action="store_true")
    a = ap.parse_args()
    idxs = [int(x) for x in a.indexes.replace(" ", "").split(",") if x.isdigit()]
    db = load_db()
    mt.OUT_DIR.mkdir(exist_ok=True)
    yt = None
    results = []
    for idx in idxs:
        if idx >= len(db):
            print(f"[{idx}] 번호가 없습니다"); continue
        item = db[idx]
        vid = item.get("youtube_id")
        if not vid and not a.no_upload:
            print(f"[{idx}] 업로드된 영상이 아닙니다 (youtube_id 없음) → 건너뜀"); continue
        if not has_background(idx, item):
            print(f"[{idx}] 배경 이미지가 없어(thumb_bg/장면 이미지 없음) 만들지 않습니다. 이 영상은 PC UI '6 업로드'에서 썸네일을 만드세요."); continue
        o = dict(item.get("thumb_opts") or {})
        if a.font: o["font"] = a.font
        if a.text1: o["text1"] = a.text1
        if a.text2: o["text2"] = a.text2
        if a.tag_text: o["tag_text"] = a.tag_text
        item["thumb_opts"] = o
        if a.style == "classic":
            im = mt.make(idx, item, a.channel, a.handle, "avatar.png")
        elif a.style == "hook":
            import thumb_hook
            im = thumb_hook.make(idx, item, a.channel, a.handle, "avatar.png", mt.background)
        else:
            import thumb_pop
            im = thumb_pop.make(idx, item, a.channel, a.handle, "avatar.png", mt.background)
        vp = item.get("video_path_v6")
        out = mt.OUT_DIR / f"{Path(vp).stem if vp else idx}.png"
        im.save(out)
        print(f"[{idx}] 썸네일 생성: {out.name}")
        ok = False
        if not a.no_upload:
            if yt is None:
                import upload_to_youtube as up
                yt = up.youtube()
            from googleapiclient.http import MediaFileUpload
            jp = to_jpeg(out)
            for t in range(3):     # 처리 중 덮어쓰기 대비: 간격을 두고 다시 설정
                if t:
                    time.sleep(45)
                try:
                    yt.thumbnails().set(videoId=vid, media_body=MediaFileUpload(str(jp), mimetype="image/jpeg")).execute()
                    ok = True
                    print(f"[{idx}] 유튜브 썸네일 적용 {t + 1}/3 ({vid})")
                except Exception as e:
                    print(f"[{idx}] 유튜브 적용 실패: {str(e)[:300]}")
                    break
        results.append((idx, out, ok, item))
    url = os.environ.get("DISCORD_WEBHOOK_URL", "")
    if url:
        from notify_discord import post_image
        for idx, out, ok, item in results:
            post_image(url, out, f"🖼 썸네일 다시 만듦 [{idx}] {item.get('title_line1', '')} — " + ("유튜브에 적용함" if ok else "유튜브 적용 안 함/실패"))
    print(f"완료: {len(results)}개")


if __name__ == "__main__":
    main()
