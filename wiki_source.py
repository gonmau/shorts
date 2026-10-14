# -*- coding: utf-8 -*-
"""위키백과에서 소재 후보(나라 x 분야)를 찾는다. LLM이 기억으로 소재를 만들 때의 쏠림/오류를 줄이기 위한 근거 자료.

- 분야(THEMES)는 채널 주제(문화/관습/법/음식/언어/축제/생활)로 고정해 일관성을 유지한다.
- 나라는 여러 번 나와도 되지만, 같은 위키 문서(wiki_title)나 같은 주제는 다시 쓰지 않는다.
- 위키백과 API 하나만 쓴다(키 불필요).
"""
import random
import re
import time

import requests

API = "https://en.wikipedia.org/w/api.php"
UA = "culture-shorts-bot/1.0 (https://github.com/gonmau/shorts; personal educational use)"

# 한국어 이름 -> 위키 검색용 영어 이름
COUNTRIES = {
    "일본": "Japan", "핀란드": "Finland", "아이슬란드": "Iceland", "몽골": "Mongolia", "스위스": "Switzerland",
    "이탈리아": "Italy", "독일": "Germany", "아르헨티나": "Argentina", "스페인": "Spain", "부탄": "Bhutan",
    "노르웨이": "Norway", "싱가포르": "Singapore", "스웨덴": "Sweden", "덴마크": "Denmark", "네덜란드": "Netherlands",
    "벨기에": "Belgium", "프랑스": "France", "영국": "United Kingdom", "아일랜드": "Ireland", "포르투갈": "Portugal",
    "그리스": "Greece", "터키": "Turkey", "러시아": "Russia", "폴란드": "Poland", "체코": "Czech Republic",
    "헝가리": "Hungary", "루마니아": "Romania", "불가리아": "Bulgaria", "에스토니아": "Estonia", "조지아": "Georgia (country)",
    "인도": "India", "네팔": "Nepal", "태국": "Thailand", "베트남": "Vietnam", "인도네시아": "Indonesia",
    "필리핀": "Philippines", "말레이시아": "Malaysia", "중국": "China", "대만": "Taiwan", "카자흐스탄": "Kazakhstan",
    "이란": "Iran", "이스라엘": "Israel", "요르단": "Jordan", "이집트": "Egypt", "모로코": "Morocco",
    "에티오피아": "Ethiopia", "케냐": "Kenya", "탄자니아": "Tanzania", "남아프리카공화국": "South Africa", "가나": "Ghana",
    "나이지리아": "Nigeria", "마다가스카르": "Madagascar", "멕시코": "Mexico", "과테말라": "Guatemala", "쿠바": "Cuba",
    "자메이카": "Jamaica", "콜롬비아": "Colombia", "페루": "Peru", "볼리비아": "Bolivia", "칠레": "Chile",
    "브라질": "Brazil", "에콰도르": "Ecuador", "캐나다": "Canada", "미국": "United States", "호주": "Australia",
    "뉴질랜드": "New Zealand", "피지": "Fiji", "사모아": "Samoa", "파푸아뉴기니": "Papua New Guinea",
}
EN2KO = {v.lower(): k for k, v in COUNTRIES.items()}

# (분야 이름, 위키 검색에 붙일 영어 단어)
THEMES = [
    ("관습/예절", "social etiquette custom tradition"),
    ("법/제도", "unusual law regulation legal"),
    ("음식문화", "traditional food dish eating custom"),
    ("언어/이름", "naming language greeting custom"),
    ("축제/의례", "festival ritual tradition celebration"),
    ("생활문화", "everyday life tradition practice"),
]

SKIP_TITLE = re.compile(
    r"^(list|history|politics|economy|demographics|geography|outline|index|culture|cuisine|religion|education|languages?|"
    r"public holidays|human rights|foreign relations|military|transport|tourism|media|sport) (of|in|by)\b"
    r"|\b(war|massacre|genocide|terror\w*|politic\w*|election\w*|crime|sexual\w*|slavery|holocaust|disambiguation)\b", re.I)


def _norm(s):
    return re.sub(r"[^0-9a-z가-힣]", "", str(s).lower())


def used_titles(db):
    return {_norm(f.get("wiki_title")) for f in db if f.get("wiki_title")}


def pick_targets(db, n, rng=random):
    """(한국어 나라, 영어 나라, 분야, 검색어) n개. 덜 쓴 나라/분야를 더 자주 고르되 같은 나라가 다시 나와도 된다."""
    by_country, by_pair = {}, {}
    for f in db:
        c = str(f.get("country", "")).strip()
        by_country[c] = by_country.get(c, 0) + 1
        by_pair[(c, f.get("theme"))] = by_pair.get((c, f.get("theme")), 0) + 1
    pairs = []
    for ko in COUNTRIES:
        for theme, terms in THEMES:
            w = 1.0 / (1 + by_country.get(ko, 0)) / (1 + 2 * by_pair.get((ko, theme), 0))
            pairs.append((w, ko, theme, terms))
    out, seen = [], set()
    tries = 0
    while len(out) < n and tries < n * 20:
        tries += 1
        w_total = sum(p[0] for p in pairs)
        r = rng.random() * w_total
        acc = 0
        for p in pairs:
            acc += p[0]
            if acc >= r:
                break
        if (p[1], p[2]) in seen:
            continue
        seen.add((p[1], p[2]))
        out.append((p[1], COUNTRIES[p[1]], p[2], p[3]))
    return out


def search(session, country_en, terms, skip_titles, limit=10):
    """위키백과에서 country+분야 검색 -> 소개문 발췌가 있는 문서 후보 목록(검색 순위순)."""
    params = {
        "action": "query", "format": "json", "generator": "search", "gsrsearch": f"{country_en} {terms}",
        "gsrlimit": limit, "gsrnamespace": 0, "prop": "extracts|info", "exintro": 1, "explaintext": 1,
        "exchars": 900, "exlimit": "max", "inprop": "url", "redirects": 1,
    }
    r = session.get(API, params=params, headers={"User-Agent": UA}, timeout=30)
    r.raise_for_status()
    pages = (r.json().get("query") or {}).get("pages") or {}
    out = []
    for p in sorted(pages.values(), key=lambda x: x.get("index", 999)):
        title = p.get("title", "")
        ext = " ".join(str(p.get("extract", "")).split())
        if not title or len(ext) < 250 or SKIP_TITLE.search(title) or _norm(title) in skip_titles:
            continue
        if "may refer to" in ext[:200] or "disambiguation" in ext[:200].lower():
            continue
        out.append({"title": title, "url": p.get("fullurl", ""), "extract": ext})
    return out


def gather(session, db, count, rng=random, sleep=0.6):
    """count개 정도의 후보(서로 다른 문서)를 모은다. 실패/없음은 건너뛴다."""
    skip = used_titles(db)
    cands, errors = [], 0
    for ko, en, theme, terms in pick_targets(db, count * 3, rng):
        if len(cands) >= count * 2:
            break
        try:
            hits = search(session, en, terms, skip)
        except Exception as e:
            errors += 1
            print(f"  위키 검색 실패 ({ko}/{theme}): {type(e).__name__}")
            if errors >= 3 and not cands:
                raise
            time.sleep(sleep)
            continue
        if hits:
            h = hits[0]
            skip.add(_norm(h["title"]))
            cands.append({**h, "country": ko, "theme": theme})
        time.sleep(sleep)
    return cands
