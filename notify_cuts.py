# -*- coding: utf-8 -*-
"""쇼츠 컷 시트/후보 사진 시트를 디스코드로 보낸다 (cuts_out/). 환경변수: DISCORD_WEBHOOK_URL, RUN_URL"""
import os
from pathlib import Path

from notify_discord import post, post_file, post_image, post_long


def main():
    url = os.environ["DISCORD_WEBHOOK_URL"]
    out = Path("cuts_out")
    post(url, "✂️ 쇼츠 이미지 컷 시트 (컷 이름 = 소재번호_컷번호)")
    f = out / "cutsheet.txt"
    if f.exists():
        post_long(url, f.read_text(encoding="utf-8"))
    if (out / "cutsheet.csv").exists():
        post_file(url, out / "cutsheet.csv", "컷 시트 (엑셀로 열기)")
    post(url, "🖼 컷별 후보 사진 (사진 위 번호가 후보 번호). 고른 것은 Actions의 pick 칸에 `117_3=2, 118_1=5` 처럼 적고 stage=render 로 실행하세요. 직접 올릴 사진은 my_images 폴더에 `117_03.jpg`로.")
    for p in sorted(out.glob("cands_*.jpg"), key=lambda p: int(p.stem.rsplit("_", 1)[1])):
        post_image(url, p, p.stem.rsplit("_", 1)[1] + "번 소재 후보")
    post(url, "로그: " + os.environ.get("RUN_URL", ""))


if __name__ == "__main__":
    main()
