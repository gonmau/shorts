# -*- coding: utf-8 -*-
"""SNS(레딧)에서 요즘 화제인 글을 모아 sns_candidates.json 에 저장한다 (소재 후보 발굴용). 글 내용은 소재로 쓰기 전에 사실 확인이 필요합니다.

  python discover_sns.py --subs todayilearned,travel --time week --limit 15

레딧 공개 JSON을 쓰고, 막히면 RSS로 대체합니다. 둘 다 막히면 해당 서브레딧은 건너뜁니다(사이트 정책/차단에 따라 실패할 수 있음).
다른 SNS(인스타/X/스레드/네이버 등)는 글을 복사해 UI의 '글 붙여넣기'로 소재를 만드세요.
"""
import argparse
import html
import json
import re
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import requests

OUT = Path("sns_candidates.json")
UA = {"User-Agent": "Mozilla/5.0 (compatible; shorts-discover/1.0; personal research)"}


def fetch_json(sub, period, limit):
    r = requests.get(f"https://www.reddit.com/r/{sub}/top.json", params={"t": period, "limit": limit, "raw_json": 1}, headers=UA, timeout=25)
    r.raise_for_status()
    out = []
    for ch in r.json()["data"]["children"]:
        d = ch["data"]
        if d.get("over_18") or d.get("stickied"):
            continue
        out.append({"source": f"r/{sub}", "title": d.get("title", ""), "text": (d.get("selftext") or "")[:1500],
                    "url": "https://www.reddit.com" + d.get("permalink", ""), "score": d.get("score", 0), "comments": d.get("num_comments", 0)})
    return out


def fetch_rss(sub, period, limit):
    r = requests.get(f"https://www.reddit.com/r/{sub}/top/.rss", params={"t": period, "limit": limit}, headers=UA, timeout=25)
    r.raise_for_status()
    ns = {"a": "http://www.w3.org/2005/Atom"}
    out = []
    for e in ET.fromstring(r.content).findall("a:entry", ns):
        title = (e.findtext("a:title", "", ns) or "").strip()
        link = e.find("a:link", ns)
        body = re.sub(r"<[^>]+>", " ", html.unescape(e.findtext("a:content", "", ns) or ""))
        out.append({"source": f"r/{sub}", "title": title, "text": " ".join(body.split())[:1500],
                    "url": link.get("href") if link is not None else "", "score": 0, "comments": 0})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--subs", default="todayilearned,travel")
    ap.add_argument("--time", default="week", choices=["day", "week", "month", "year"])
    ap.add_argument("--limit", type=int, default=15)
    a = ap.parse_args()
    cands, ok = [], 0
    for sub in [s.strip().lstrip("r/").strip("/") for s in a.subs.split(",") if s.strip()]:
        got = None
        for fn in (fetch_json, fetch_rss):
            try:
                got = fn(sub, a.time, a.limit)
                break
            except Exception as e:
                print(f"  r/{sub} {fn.__name__} 실패: {type(e).__name__} {str(e)[:80]}")
        if got is None:
            continue
        ok += 1
        print(f"r/{sub}: {len(got)}개")
        cands.extend(got)
        time.sleep(1.5)
    cands.sort(key=lambda c: (-c["score"], -c["comments"]))
    OUT.write_text(json.dumps(cands, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"후보 {len(cands)}개 저장 ({OUT.name})")
    if not ok:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
