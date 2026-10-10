# -*- coding: utf-8 -*-
"""파이프라인 공통 함수 (DB 입출력, 문장 분리, 폴더 이름 등)."""
import json
import re
import unicodedata
from pathlib import Path

DB_PATH = Path("facts_db.json")


def load_db():
    with DB_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_db(db):
    tmp = DB_PATH.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)
    tmp.replace(DB_PATH)


def split_sentences(text):
    """대본을 문장 단위로 나눈다. 핵심 문구의 문장 번호(1부터)가 이 분리 기준을 따른다."""
    parts = re.split(r"(?<=[.!?。！？])\s+|\n+", str(text or "").strip())
    return [p.strip() for p in parts if p.strip()]


def strip_marks(text):
    """핵심 문구의 *강조* 표시를 제거한 글자 수 계산용 텍스트."""
    return str(text or "").replace("*", "").strip()


def safe_country(item):
    raw = str(item.get("country") or item.get("나라") or item.get("title") or "unknown").strip()
    normalized = unicodedata.normalize("NFKC", raw).strip()
    return re.sub(r"\s+", " ", normalized)


def safe_dirname(text):
    return re.sub(r'[<>:"/\\|?*]', "_", str(text)).strip()


def visual_dir(base_dir, idx, item):
    """장면 이미지 폴더: visuals/0056_국가명"""
    return Path(base_dir) / "visuals" / f"{idx:04d}_{safe_dirname(safe_country(item))}"


def pending_render(db, start=0):
    """영상이 아직 안 만들어진, 대본이 끝난 소재의 (index, item) 목록 (DB 순서)."""
    out = []
    for i, f in enumerate(db):
        if i < start:
            continue
        if f.get("video_path_v6") or f.get("status_v6") == "video_done":
            continue
        if f.get("status") not in ("scripted", "tts_done"):
            continue
        out.append((i, f))
    return out


def youtube_meta(item):
    """유튜브에 올릴 제목/설명 (자동 업로드와 디스코드 알림이 같은 문구를 쓴다)."""
    title = " ".join(filter(None, [item.get("title_line1"), item.get("title_line2")])) or item.get("topic", "")
    desc = f"{item.get('hook', '')}\n\n"
    if item.get("image_source") == "pixabay":
        desc += "Photos: Pixabay (pixabay.com)\n"
    desc += "#shorts #세계문화 #상식"
    return f"{title} #shorts"[:100], desc
