# -*- coding: utf-8 -*-
"""롱폼 소재 고르기 키워드 해석: 나라 / 분야 / 자유 키워드를 구분해서 맞춘다.
  - '나라:일본' → 소재의 나라 칸이 일본인 것만 (제목·주제에 일본이 언급된 다른 나라 소재는 제외)
  - '분야:음식' → 소재의 분야(theme) 칸에 '음식'이 들어간 것 (여러 나라가 섞임)
  - 접두사 없이 '일본'만 적으면: 나라 이름이면 나라로, 분야 이름이면 분야로, 둘 다 아니면 자유 키워드(나라·분야·주제·제목 어디든 포함)로 본다
  - 서로 다른 종류를 같이 고르면 모두 맞아야 한다(AND). 같은 종류 안에서는 하나만 맞아도 된다(OR)
  - 나라 없이 분야/자유 키워드만 고르면 나라가 골고루 섞이게 뽑는다(나라별로 번갈아)"""
import re

try:
    from country_codes import country_code
except Exception:   # pragma: no cover
    country_code = lambda x: None


def _ccode(x):
    s = str(x or "").strip()
    try:
        return country_code(s) or country_code(re.sub(r"\(.*?\)", "", s).strip()) or s.lower()
    except Exception:
        return s.lower()


def split_tokens(theme):
    # 분야 이름에 '/'가 들어 있어서(예: 축제/의례) '/'는 구분자로 쓰지 않는다 (쉼표·세미콜론·| 또는 앞뒤가 띄어진 ' / ')
    return [x.strip() for x in re.split(r"[,;|]|\s/\s", str(theme or "")) if x.strip()]


def parse(theme, db):
    """-> {'countries': [...], 'fields': [...], 'free': [...]}"""
    known_c = {_ccode(f.get("country")) for f in db if f.get("country")}
    known_t = {str(f.get("theme", "")).strip().lower() for f in db if f.get("theme")}
    out = {"countries": [], "fields": [], "free": []}
    for t in split_tokens(theme):
        m = re.match(r"^(나라|분야|country|field)\s*[:：]\s*(.+)$", t, re.I)
        if m:
            (out["countries"] if m.group(1).lower() in ("나라", "country") else out["fields"]).append(m.group(2).strip())
        elif _ccode(t) in known_c and t.lower() not in known_t:
            out["countries"].append(t)
        elif t.lower() in known_t:
            out["fields"].append(t)
        else:
            out["free"].append(t)
    return out


def match(f, g):
    if g["countries"]:
        cc = _ccode(f.get("country"))
        if not any(_ccode(c) == cc for c in g["countries"]):
            return False
    if g["fields"]:
        th = str(f.get("theme", "")).lower()
        if not any(x.lower() in th for x in g["fields"]):
            return False
    if g["free"]:
        hay = " ".join(str(f.get(k, "")) for k in ("theme", "topic", "country", "title_line1", "title_line2")).lower()
        if not any(x.lower() in hay for x in g["free"]):
            return False
    return True


def spread(pool, db):
    """나라별로 번갈아 뽑는 순서 (같은 나라 안에서는 원래 번호순)"""
    groups, order = {}, []
    for i in pool:
        k = _ccode(db[i].get("country"))
        if k not in groups:
            groups[k] = []
            order.append(k)
        groups[k].append(i)
    out = []
    while any(groups.values()):
        for k in order:
            if groups[k]:
                out.append(groups[k].pop(0))
    return out


def select(pool, db, theme):
    """pool(번호 목록)을 키워드로 거르고 순서를 정한다. 키워드가 없으면 그대로"""
    if not str(theme or "").strip():
        return list(pool)
    g = parse(theme, db)
    res = [i for i in pool if match(db[i], g)]
    if not g["countries"]:
        res = spread(res, db)
    return res


def label(theme):
    """제목 등에 쓸 표시용 키워드 (접두사 제거)"""
    return ", ".join(re.sub(r"^(나라|분야|country|field)\s*[:：]\s*", "", t, flags=re.I) for t in split_tokens(theme))
