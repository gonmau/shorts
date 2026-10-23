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


def upload_state(item):
    """업로드 구분: 업로드(공개/비공개/일부공개) · 영상완료(미업로드) · '' (영상 없음)"""
    if item.get("youtube_id"):
        pv = {"public": "공개", "private": "비공개", "unlisted": "일부공개"}.get(item.get("youtube_privacy"), "")
        return f"업로드({pv})" if pv else "업로드"
    if item.get("video_path_v6") or item.get("status_v6") == "video_done":
        return "영상완료(미업로드)"
    return ""


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


def license_url(lic):
    """CC 라이선스 이름('CC BY 2.0', 'CC BY-SA 4.0')을 라이선스 문서 링크로. CC0/퍼블릭도메인/모르면 빈 문자열."""
    m = re.match(r"\s*cc[ -]by(?:[ -](\d\.\d))?", str(lic or ""), re.I)
    if m:
        return f"https://creativecommons.org/licenses/by/{m.group(1) or '4.0'}/"
    if str(lic or "").lower().startswith("cc0"):
        return "https://creativecommons.org/publicdomain/zero/1.0/"
    return ""


def image_credit_lines(item):
    """유튜브 설명란에 넣을 사진 출처. Pixabay는 한 줄, Wikimedia Commons는 사진마다 작성자/라이선스/링크."""
    cr = (item.get("image_credits") or []) + (item.get("edit_credits") or [])
    has_pix = any(c.get("source", "pixabay") == "pixabay" for c in cr) or (not cr and item.get("image_source") == "pixabay")
    com = sorted((c for c in cr if c.get("source") == "commons"), key=lambda c: c.get("scene", 0))
    lines = []
    if has_pix:
        lines.append("Photos: Pixabay (pixabay.com)")
    if com:
        lines.append("Photos from Wikimedia Commons (cropped/zoomed):")
        for c in com:
            lic = c.get("license", "")
            lic_url = license_url(lic)
            lines.append(f'- "{c.get("title", "")}" by {c.get("user", "")}, {lic}' + (f" ({lic_url})" if lic_url else "")
                         + f' - {c.get("page", "")}')
    return lines


def credit_label(item):
    """영상 화면(이미지 아래)에 쓸 짧은 출처 문구. 사진 출처가 없으면 빈 문자열."""
    cr = (item.get("image_credits") or []) + (item.get("edit_credits") or [])
    names = []
    if any(c.get("source", "pixabay") == "pixabay" for c in cr) or (not cr and item.get("image_source") == "pixabay"):
        names.append("Pixabay")
    if any(c.get("source") == "commons" for c in cr):
        names.append("Wikimedia Commons")
    return ("Photos: " + " · ".join(names)) if names else ""


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
    title = title[:100].rstrip()   # 제목에는 #Shorts 를 붙이지 않는다 (설명 끝 해시태그에만 둔다)

    parts = []
    if item.get("hook"):
        parts.append(f"🎯 {item['hook']}")
    if item.get("body"):
        parts.append(str(item["body"]).strip())
    if item.get("twist"):
        parts.append(f"💡 {str(item['twist']).strip()}")
    parts.append(CHANNEL_BLURB)
    credit = image_credit_lines(item)
    if credit:
        parts.append("\n".join(credit))
    tags = youtube_tags(item)
    parts.append(" ".join("#" + t for t in tags) + " #Shorts")
    return title, "\n\n".join(parts)
