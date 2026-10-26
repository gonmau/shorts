# -*- coding: utf-8 -*-
"""Openverse(openverse.org) 사진 검색 - 후보 사진용. 라이선스는 CC0 / 퍼블릭 도메인 / CC BY 만 허용 (SA·NC·ND 제외).
API 키 없이도 되지만 호출 한도가 낮다 (OPENVERSE_TOKEN 이 있으면 사용)."""
import os
import re

API = "https://api.openverse.org/v1/images/"
UA = "culture-shorts-bot/1.0 (https://github.com/gonmau)"


def search(session, query, used=(), limit=3):
    """조건에 맞는 사진 최대 limit개: dict(id,url,thumb,title,artist,license,page)"""
    h = {"User-Agent": UA}
    if os.environ.get("OPENVERSE_TOKEN"):
        h["Authorization"] = "Bearer " + os.environ["OPENVERSE_TOKEN"]
    params = {"q": query[:100], "license": "cc0,pdm,by", "page_size": 20, "mature": "false", "category": "photograph"}
    r = session.get(API, params=params, headers=h, timeout=30)
    if r.status_code != 200:
        return []
    out = []
    for x in r.json().get("results") or []:
        oid = f"o:{x.get('id')}"
        lic = str(x.get("license") or "").lower()
        url = x.get("url")
        if oid in used or not url or lic not in ("cc0", "pdm", "by"):
            continue
        if (x.get("width") or 0) < 800 or re.search(r"\.(svg|gif|tif|tiff)$", url, re.I):
            continue
        creator = str(x.get("creator") or "").strip()
        if lic == "by" and not creator:
            continue
        out.append({"id": oid, "url": url, "thumb": x.get("thumbnail") or url, "title": str(x.get("title") or "")[:120],
                    "artist": creator[:80], "license": "CC BY" if lic == "by" else ("CC0" if lic == "cc0" else "Public Domain"),
                    "page": x.get("foreign_landing_url") or ""})
        if len(out) >= limit:
            break
    return out
