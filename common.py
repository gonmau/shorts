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


FIXED_TAGS = ["세계문화", "해외여행", "이색상식", "문화차이", "세계여행"]
CHANNEL_BLURB = "🌍 세계 각국의 놀라운 문화와 이색 정보를 짧고 재미있게 만나보세요!"


def _tagify(text):
    return re.sub(r"[^0-9A-Za-z가-힣]", "", str(text or ""))


def youtube_tags(item):
    """해시태그 목록(# 없이): 나라 + 주제 키워드 + 고정 태그, 중복 제거."""
    tags = [_tagify(item.get("country"))]
    for w in str(item.get("topic", "")).replace("/", " ").replace(",", " ").split():
        w = _tagify(w)
        if len(w) >= 2:
            tags.append(w)
    tags += FIXED_TAGS
    out, seen = [], set()
    for t in tags:
        if t and t.lower() not in seen and len(t) <= 30:
            seen.add(t.lower())
            out.append(t)
    return out[:9]


def youtube_meta(item):
    """유튜브에 올릴 제목/설명. 자동 업로드와 디스코드 알림이 같은 문구를 쓴다.
    제목: 나라 이름이 없으면 앞에 붙여 검색에 걸리게 함. 설명: 훅 -> 본문 -> 반전 -> 채널 소개 -> 해시태그.
    """
    title = " ".join(filter(None, [item.get("title_line1"), item.get("title_line2")])) or item.get("topic", "")
    country = str(item.get("country", "")).strip()
    if country and country not in title:
        title = f"{country} {title}"
    title = f"{title[:88].rstrip()} #Shorts"

    parts = []
    if item.get("hook"):
        parts.append(f"🎯 {item['hook']}")
    if item.get("body"):
        parts.append(str(item["body"]).strip())
    if item.get("twist"):
        parts.append(f"💡 {str(item['twist']).strip()}")
    parts.append(CHANNEL_BLURB)
    if item.get("image_source") == "pixabay":
        parts.append("Photos: Pixabay (pixabay.com)")
    tags = youtube_tags(item)
    parts.append(" ".join("#" + t for t in tags) + " #Shorts")
    return title, "\n\n".join(parts)
