# -*- coding: utf-8 -*-
"""Wikimedia Commons 사진 검색 (Pixabay에서 소재 사진을 못 찾을 때만 보조로 사용).

안전 기준 (영상/수익화 채널에서 쓰기 위해 보수적으로):
- 라이선스: CC0, 퍼블릭 도메인, CC BY 만 허용. CC BY-SA(동일조건), NC, ND 는 제외.
- 별도 제한(Restrictions: 초상권/상표 등)이 표시된 파일, 비자유(NonFree) 파일, 작성자 표기가 없는 CC BY 파일은 제외.
- 로고/지도/깃발/도표 같은 파일 이름은 제외, JPEG/PNG 만 사용.
사용한 사진의 작성자/라이선스/링크는 image_credits에 저장되어 유튜브 설명란에 자동으로 들어간다.
"""
import html
import re
import time

API = "https://commons.wikimedia.org/w/api.php"
UA = "culture-shorts-bot/1.0 (https://github.com/gonmau; shorts automation)"
BAD_TITLE = re.compile(r"\b(logo|map|flag|coat of arms|diagram|chart|icon|poster|screenshot|stamp|banknote|coin|signature)\b", re.I)
STOP = {"the", "and", "with", "for", "from", "near", "view", "japan", "traditional"}


def _clean(s, n=120):
    s = re.sub(r"<[^>]+>", " ", str(s or ""))
    s = html.unescape(s)
    return " ".join(s.split())[:n]


def license_ok(name):
    """CC0 / 퍼블릭 도메인 / CC BY(동일조건·비영리·변경금지 아님)만 True."""
    n = (name or "").lower().strip()
    if not n:
        return False
    if n.startswith("cc0") or "public domain" in n or n.startswith("pd ") or n == "pd" or n.startswith("pdm"):
        return True
    tokens = re.split(r"[^a-z0-9]+", n)
    if tokens[:2] == ["cc", "by"]:
        return not any(t in ("sa", "nc", "nd") for t in tokens)
    return False


def _key_words(query):
    return [w for w in re.findall(r"[a-z0-9]+", query.lower()) if len(w) >= 4 and w not in STOP]


def search(session, query, used=(), limit=15):
    """조건에 맞는 첫 사진을 dict(id,url,title,artist,license,page)로. 없으면 None."""
    params = {
        "action": "query", "format": "json", "generator": "search", "gsrnamespace": 6,
        "gsrsearch": f"{query} filetype:bitmap", "gsrlimit": limit,
        "prop": "imageinfo", "iiprop": "url|size|mime|extmetadata", "iiurlwidth": 1400,
    }
    r = session.get(API, params=params, headers={"User-Agent": UA}, timeout=30)
    if r.status_code == 429:
        time.sleep(10)
        r = session.get(API, params=params, headers={"User-Agent": UA}, timeout=30)
    r.raise_for_status()
    pages = (r.json().get("query") or {}).get("pages") or {}
    kws = _key_words(query)
    for p in sorted(pages.values(), key=lambda x: x.get("index", 0)):
        info = (p.get("imageinfo") or [{}])[0]
        meta = info.get("extmetadata") or {}
        cid = f"c:{p.get('pageid')}"
        title = _clean(p.get("title", "").replace("File:", ""), 90)
        if cid in used or not info.get("thumburl"):
            continue
        if info.get("mime") not in ("image/jpeg", "image/png"):
            continue
        if int(info.get("width") or 0) < 900 or int(info.get("height") or 0) < 600:
            continue
        if BAD_TITLE.search(title):
            continue
        lic = _clean((meta.get("LicenseShortName") or {}).get("value"), 40)
        if not license_ok(lic):
            continue
        if _clean((meta.get("Restrictions") or {}).get("value")):
            continue
        if str((meta.get("NonFree") or {}).get("value", "")).lower() == "true":
            continue
        artist = _clean((meta.get("Artist") or {}).get("value"), 80)
        if lic.lower().startswith("cc by") and not artist:
            continue
        text = (title + " " + _clean((meta.get("ImageDescription") or {}).get("value"), 300)).lower()
        if kws and not any(w in text for w in kws):
            continue  # 검색어 핵심 단어가 제목/설명에 없으면 엉뚱한 사진일 가능성이 커서 제외
        return {"id": cid, "url": info["thumburl"], "title": title, "artist": artist or "Public domain / CC0",
                "license": lic, "page": info.get("descriptionurl", "")}
    return None
