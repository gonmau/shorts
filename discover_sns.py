# -*- coding: utf-8 -*-
"""SNS(레딧)에서 요즘 화제인 글을 모아 sns_candidates.json 에 저장한다 (소재 후보 발굴용). 글 내용은 소재로 쓰기 전에 사실 확인이 필요합니다.

  python discover_sns.py --subs todayilearned,travel --time week --limit 15 [--mastodon-tags culture,travel] [--youtube "keyword1,keyword2"] [--curate]

소스: 레딧(키 없음) / 마스토돈 공개 해시태그(키 없음) / 유튜브(환경변수 YOUTUBE_API_KEY 필요, 무료 발급).
--curate: Groq로 후보를 한국어로 번역하고 채널 주제 적합도(0~10)를 매겨 높은 순으로 정렬합니다.

레딧 공개 JSON을 쓰고, 막히면 RSS로 대체합니다. 둘 다 막히면 해당 서브레딧은 건너뜁니다(사이트 정책/차단에 따라 실패할 수 있음).
다른 SNS(인스타/X/스레드/네이버 등)는 글을 복사해 UI의 '글 붙여넣기'로 소재를 만드세요.
"""
import argparse
import os
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


def strip_html(t):
    return " ".join(re.sub(r"<[^>]+>", " ", html.unescape(t or "")).split())


def fetch_mastodon(tag, limit):
    r = requests.get(f"https://mastodon.social/api/v1/timelines/tag/{tag}", params={"limit": min(limit, 40)}, headers=UA, timeout=25)
    r.raise_for_status()
    out = []
    for st_ in r.json():
        txt = strip_html(st_.get("content"))
        if len(txt) < 80 or st_.get("sensitive"):
            continue
        out.append({"source": f"mastodon #{tag}", "title": txt[:90], "text": txt[:1500], "url": st_.get("url", ""),
                    "score": st_.get("favourites_count", 0) + st_.get("reblogs_count", 0), "comments": st_.get("replies_count", 0)})
    return out


def fetch_youtube(query, limit):
    key = os.environ.get("YOUTUBE_API_KEY", "").strip()
    if not key:
        raise RuntimeError("YOUTUBE_API_KEY 환경변수가 없습니다")
    r = requests.get("https://www.googleapis.com/youtube/v3/search", params={
        "part": "snippet", "q": query, "type": "video", "order": "viewCount", "maxResults": min(limit, 25),
        "videoDuration": "short", "key": key}, timeout=25)
    r.raise_for_status()
    return [{"source": f"youtube '{query}'", "title": i["snippet"]["title"], "text": i["snippet"].get("description", "")[:600],
             "url": "https://www.youtube.com/watch?v=" + i["id"]["videoId"], "score": 0, "comments": 0} for i in r.json().get("items", [])]


def curate(cands, channel_ko, channel_en):
    """Groq로 한국어 번역 + 채널 적합도(0~10) 평가. 실패하면 그대로 돌려준다."""
    try:
        from groq import Groq
        key = os.environ.get("GROQ_API_KEY", "").strip()
        if not key:
            print("  GROQ_API_KEY가 없어 번역/적합도 평가를 건너뜁니다")
            return cands
        client = Groq(api_key=key)
        mod = __import__("generate_topics" if channel_en else "generate_culture_facts")
        model = mod.pick_model(client)
    except Exception as e:
        print(f"  번역/평가 준비 실패: {type(e).__name__}")
        return cands
    topic_desc = ("한국의 문화/일상/음식/예절/언어/현대 생활 중 외국인이 흥미로워할 사실" if channel_en
                  else "세계 각국의 문화·관습·금기·생활 규칙 같은 '어? 정말?' 싶은 문화 상식")
    B = 8
    for s0 in range(0, len(cands), B):
        chunk = cands[s0:s0 + B]
        blocks = "\n".join(f"[{i}] {c['title'][:150]} | {c['text'][:260]}" for i, c in enumerate(chunk))
        prompt = f"""아래 SNS 글 {len(chunk)}개를 한국어로 번역하고, 유튜브 쇼츠 채널 주제({topic_desc})에 맞는 정도를 0~10으로 평가해줘.
정치/종교 논쟁/연예 가십/광고/질문글/개인 일상이면 낮게. 구체적인 사실이나 관습이 있으면 높게.
{blocks}
JSON 배열로만 응답: [{{"i": 0, "ko_title": "한국어 제목", "ko_summary": "한국어 요약 1~2문장", "fit": 0, "reason": "한 줄 이유"}}]"""
        try:
            c = client.chat.completions.create(model=model, messages=[{"role": "user", "content": prompt}],
                                               max_completion_tokens=2500, temperature=0.2)
            t = c.choices[0].message.content or ""
            for r in json.loads(t[t.find("["):t.rfind("]") + 1]):
                x = chunk[int(r["i"])]
                x["ko_title"], x["ko_summary"], x["fit"], x["reason"] = r.get("ko_title", ""), r.get("ko_summary", ""), int(r.get("fit", 0)), r.get("reason", "")
        except Exception as e:
            print(f"  번역/평가 일부 실패: {type(e).__name__} {str(e)[:80]}")
        time.sleep(2)
    return cands


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--subs", default="todayilearned,travel")
    ap.add_argument("--time", default="week", choices=["day", "week", "month", "year"])
    ap.add_argument("--limit", type=int, default=15)
    ap.add_argument("--mastodon-tags", default="")
    ap.add_argument("--youtube", default="", help="쉼표로 구분한 검색어 (YOUTUBE_API_KEY 필요)")
    ap.add_argument("--curate", action="store_true", help="한국어 번역 + 채널 적합도 평가(Groq)")
    a = ap.parse_args()
    cands, ok = [], 0
    for tag in [t.strip().lstrip("#") for t in a.mastodon_tags.split(",") if t.strip()]:
        try:
            got = fetch_mastodon(tag, a.limit)
            ok += 1; cands.extend(got); print(f"mastodon #{tag}: {len(got)}개")
        except Exception as e:
            print(f"  mastodon #{tag} 실패: {type(e).__name__} {str(e)[:80]}")
    for q in [t.strip() for t in a.youtube.split(",") if t.strip()]:
        try:
            got = fetch_youtube(q, a.limit)
            ok += 1; cands.extend(got); print(f"youtube '{q}': {len(got)}개")
        except Exception as e:
            print(f"  youtube '{q}' 실패: {type(e).__name__} {str(e)[:80]}")
    for sub in [re.sub(r"^/?r/", "", s.strip()).strip("/") for s in a.subs.split(",") if s.strip()]:
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
    if a.curate and cands:
        cands = curate(cands, True, Path("generate_culture_facts.py").exists() is False)
    cands.sort(key=lambda c: (-c.get("fit", -1), -c["score"], -c["comments"]))
    OUT.write_text(json.dumps(cands, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"후보 {len(cands)}개 저장 ({OUT.name})")
    if not ok:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
