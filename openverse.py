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
    sa = os.environ.get("ALLOW_SA", "1") != "0"
    okl = ("cc0", "pdm", "by") + (("by-sa",) if sa else ())
    params = {"q": query[:100], "license": ",".join(okl), "page_size": 20, "mature": "false", "category": "photograph"}
    r = session.get(API, params=params, headers=h, timeout=30)
    if r.status_code != 200:
        return []
    out = []
    for x in r.json().get("results") or []:
        oid = f"o:{x.get('id')}"
        lic = str(x.get("license") or "").lower()
        url = x.get("url")
        if oid in used or not url or lic not in okl:
            continue
        if (x.get("width") or 0) < 800 or re.search(r"\.(svg|gif|tif|tiff)$", url, re.I):
            continue
        creator = str(x.get("creator") or "").strip()
        if lic in ("by", "by-sa") and not creator:
            continue
        out.append({"id": oid, "url": url, "thumb": x.get("thumbnail") or url, "title": str(x.get("title") or "")[:120],
                    "artist": creator[:80], "license": {"by": "CC BY", "by-sa": "CC BY-SA"}.get(lic) or ("CC0" if lic == "cc0" else "Public Domain"),
                    "page": x.get("foreign_landing_url") or ""})
        if len(out) >= limit:
            break
    return out
