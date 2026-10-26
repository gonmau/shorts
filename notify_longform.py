# -*- coding: utf-8 -*-
"""롱폼 완료/실패를 디스코드로 알린다: 제목, 설명(챕터 포함), 썸네일을 각각 별도 메시지로 (길게 눌러 복사).
환경변수: DISCORD_WEBHOOK_URL, JOB_STATUS, RUN_URL, ART_URL"""
import json
import os
from pathlib import Path

from notify_discord import post, post_file, post_image, post_long


def main():
    url = os.environ["DISCORD_WEBHOOK_URL"]
    run_url = os.environ.get("RUN_URL", "")
    pvw = os.environ.get("PREVIEW", "") or ("list" if os.environ.get("DRY_RUN", "") == "true" else "")
    if pvw:
        out = Path("longform_out")
        names = {"list": "목록", "script": "대본", "images": "사진", "voice": "음성"}
        if os.environ.get("JOB_STATUS", "") != "success":
            post(url, f"❌ 롱폼 {names.get(pvw, pvw)} 미리 보기 실패 (조건에 맞는 소재가 부족하거나 키 확인 필요)\n로그: {run_url}")
            return
        art = os.environ.get("ART_URL", "")
        if pvw == "list":
            pv = out / "longform_preview.txt"
            if not pv.exists():
                post(url, f"❌ 목록 파일이 없습니다\n로그: {run_url}")
                return
            post(url, "📋 롱폼 목록 (영상은 만들지 않았습니다)")
            post_long(url, pv.read_text(encoding="utf-8"))
        elif pvw == "script":
            post(url, "📝 롱폼 대본 미리 보기 (영상은 만들지 않았습니다. 대본은 저장되어 이후 영상 제작에 그대로 쓰입니다)")
            for n_, h_ in (("preview_script.txt", "대본"), ("preview_scenario.txt", "시나리오")):
                f_ = out / n_
                if f_.exists():
                    if n_ == "preview_script.txt":
                        post_long(url, f_.read_text(encoding="utf-8"))
                    else:
                        post_file(url, f_, "시나리오 (문장별 화면·효과)")
        elif pvw == "images":
            post(url, "🖼 롱폼 사진 미리 보기 (소재별 장면 사진. 마음에 안 들면 UI에서 교체 후 영상 제작)")
            for f_ in sorted(out.glob("preview_images_*.jpg"), key=lambda p: int(p.stem.rsplit("_", 1)[1])):
                post_image(url, f_, f_.stem.rsplit("_", 1)[1] + "번 소재")
            if art:
                post(url, f"원본 사진 받기: {art}")
        elif pvw == "voice":
            post(url, "🔊 롱폼 음성 미리 보기 (소재별 mp3)")
            sc = out / "preview_script.txt"
            for f_ in sorted(out.glob("preview_voice_*.mp3"), key=lambda p: int(p.stem.rsplit("_", 1)[1])):
                post_file(url, f_, f_.stem.rsplit("_", 1)[1] + "번 소재 음성")
            if art:
                post(url, f"전체 파일: {art}")
        post(url, f"로그: {run_url}")
        return
    if os.environ.get("JOB_STATUS", "") != "success":
        post(url, f"❌ 롱폼 만들기 실패\n로그: {run_url}")
        return
    db = json.load(open("longform_db.json", encoding="utf-8")) if Path("longform_db.json").exists() else []
    if not db:
        post(url, f"⚠️ 롱폼 기록이 없습니다\n로그: {run_url}")
        return
    rec = db[-1]
    mins = rec.get("duration_sec", 0) / 60
    art = os.environ.get("ART_URL", "")
    post(url, f"🎞 롱폼 #{rec['id']} 완료 ({len(rec['members'])}개 묶음, {mins:.1f}분)\n영상 받기: {art or run_url}")
    post(url, rec["title"])
    post(url, rec["description"])
    sc = Path("longform_out") / f"longform_{rec['id']:03d}_script.txt"
    if sc.exists():
        post(url, "📝 대본 (오프닝 · 챕터별 · 엔딩)")
        post_long(url, sc.read_text(encoding="utf-8"))
    sn = Path("longform_out") / f"longform_{rec['id']:03d}_scenario.txt"
    if sn.exists():
        post_file(url, sn, "시나리오 (문장별 화면·효과)")
    png = Path("longform_out") / f"longform_{rec['id']:03d}.png"
    if png.exists():
        post_image(url, png, "썸네일")


if __name__ == "__main__":
    main()
