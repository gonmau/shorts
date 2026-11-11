# -*- coding: utf-8 -*-
"""트렌드·벤치마크 조사: 잘 터진 쇼츠/채널, 위키 조회수 급증, 레딧 화제글을 모아 trend_data.json 에 캐시한다.

  python trend_research.py --yt "라오스 문화,세계 금기" --days 30          # 키워드로 터진 쇼츠 (유튜브 검색 100유닛/키워드)
  python trend_research.py --channels "@handle,UCxxxx"                    # 경쟁 채널 최근 영상 중 평균을 크게 넘은 영상 (약 3유닛/채널)
  python trend_research.py --wiki                                         # 위키 조회수 급증 문서 (무료, 키 불필요)
  python trend_research.py --reddit "todayilearned,travel"                # 레딧 인기글 (키 불필요)
  python trend_research.py --analyze                                      # 모은 데이터를 Groq로 분석 -> 패턴/니즈/소재 추천

- 유튜브는 환경변수 YOUTUBE_API_KEY 가 필요하다 (무료 한도 하루 10,000유닛). 사용량은 trend_data.json 의 quota 에 기록되고
  --max-units(기본 3000)를 넘기면 멈춘다.
- 같은 검색어를 이미 오늘 조회했으면 캐시를 쓴다 (--fresh 로 무시).
- 다른 코드에서는 trend_hints() 로 대본/소재 프롬프트에 넣을 짧은 글을 얻는다."""
import argparse
import datetime as dt
import json
import os
import re
import statistics
import time
from pathlib import Path

import requests

FILE = Path("trend_data.json")
EN = Path("generate_topics.py").exists()
UA = {"User-Agent": "Mozilla/5.0 (compatible; shorts-trend/1.0; personal research)"}
API = "https://www.googleapis.com/youtube/v3/"
COST = {"search": 100, "videos": 1, "channels": 1, "playlistItems": 1}


def load():
    try:
        d = json.load(open(FILE, encoding="utf-8"))
    except Exception:
        d = {}
    d.setdefault("videos", []); d.setdefault("channels", []); d.setdefault("wiki", []); d.setdefault("reddit", [])
    d.setdefault("analysis", {}); d.setdefault("searched", {}); d.setdefault("quota", {})
    return d


def save(d):
    d["updated"] = dt.datetime.now().isoformat(timespec="seconds")
    tmp = FILE.with_suffix(".tmp")
    json.dump(d, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    os.replace(tmp, FILE)


# ---------------- YouTube ----------------
class YT:
    def __init__(self, data, max_units):
        self.key = os.environ.get("YOUTUBE_API_KEY", "").strip()
        if not self.key:
            raise SystemExit("YOUTUBE_API_KEY 가 없습니다 (UI의 트렌드 화면에서 입력하거나 환경변수로 설정)")
        self.d, self.max_units = data, max_units
        today = dt.date.today().isoformat()
        q = data["quota"]
        if q.get("date") != today:
            data["quota"] = q = {"date": today, "used": 0}
        self.q = q

    def call(self, kind, **params):
        cost = COST[kind]
        if self.q["used"] + cost > self.max_units:
            raise SystemExit(f"오늘 사용량 제한({self.max_units}유닛)에 도달해 멈춥니다 (사용 {self.q['used']})")
        r = requests.get(API + kind, params=dict(params, key=self.key), timeout=30)
        if r.status_code != 200:
            try:
                msg = r.json()["error"]["message"]
            except Exception:
                msg = r.text[:200]
            raise SystemExit(f"YouTube API 오류 {r.status_code}: {msg}")
        self.q["used"] += cost
        return r.json()

    def videos(self, ids):
        out = []
        for i in range(0, len(ids), 50):
            out += self.call("videos", part="snippet,statistics,contentDetails", id=",".join(ids[i:i + 50])).get("items", [])
        return out

    def subs(self, cids):
        res = {}
        cids = list(dict.fromkeys(cids))
        for i in range(0, len(cids), 50):
            for it in self.call("channels", part="statistics,snippet", id=",".join(cids[i:i + 50])).get("items", []):
                s = it.get("statistics", {})
                res[it["id"]] = {"subs": None if s.get("hiddenSubscriberCount") else int(s.get("subscriberCount", 0)), "title": it["snippet"]["title"],
                                 "handle": it["snippet"].get("customUrl", "")}
        return res


def secs(iso):
    m = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso or "")
    h, mi, s = (int(x or 0) for x in m.groups()) if m else (0, 0, 0)
    return h * 3600 + mi * 60 + s


def vrow(it, subs, kw="", src="search"):
    sn, st = it["snippet"], it.get("statistics", {})
    views = int(st.get("viewCount", 0))
    sc = subs.get(sn["channelId"], {}).get("subs")
    return {"id": it["id"], "title": sn["title"], "channel": sn["channelTitle"], "channel_id": sn["channelId"], "views": views,
            "likes": int(st.get("likeCount", 0)), "comments": int(st.get("commentCount", 0)), "subs": sc,
            "ratio": round(views / max(sc, 100), 2) if sc is not None else None, "secs": secs(it["contentDetails"].get("duration")),
            "published": sn["publishedAt"][:10], "url": "https://www.youtube.com/shorts/" + it["id"], "kw": kw, "src": src,
            "tags": (sn.get("tags") or [])[:8]}


def do_search(yt, data, kws, days, limit, max_sec, fresh):
    since = (dt.datetime.utcnow() - dt.timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    today = dt.date.today().isoformat()
    have = {v["id"]: v for v in data["videos"]}
    for kw in kws:
        key = f"{kw}|{days}|{'en' if EN else 'ko'}"
        if not fresh and data["searched"].get(key) == today:
            print(f"  '{kw}': 오늘 이미 조회해 캐시를 사용합니다")
            continue
        r = yt.call("search", part="id", q=kw, type="video", order="viewCount", maxResults=min(limit, 50), videoDuration="short",
                    publishedAfter=since, regionCode="US" if EN else "KR", relevanceLanguage="en" if EN else "ko")
        ids = [i["id"]["videoId"] for i in r.get("items", [])]
        items = yt.videos(ids) if ids else []
        subs = yt.subs([i["snippet"]["channelId"] for i in items])
        n = 0
        for it in items:
            row = vrow(it, subs, kw)
            if row["secs"] and row["secs"] > max_sec:
                continue
            have[row["id"]] = dict(have.get(row["id"], {}), **row)
            n += 1
        data["searched"][key] = today
        print(f"  '{kw}': {n}개 (사용 {yt.q['used']}유닛)")
        time.sleep(0.3)
    data["videos"] = sorted(have.values(), key=lambda v: -(v.get("views") or 0))[:400]


def resolve_channel(yt, ref):
    ref = ref.strip()
    m = re.search(r"youtube\.com/(?:channel/)?(UC[\w-]{20,})", ref)
    if m or re.fullmatch(r"UC[\w-]{20,}", ref):
        return (m.group(1) if m else ref)
    h = re.search(r"youtube\.com/(@[\w.%-]+)", ref)
    handle = h.group(1) if h else ref
    if not handle.startswith("@"):
        handle = "@" + handle
    r = yt.call("channels", part="id", forHandle=handle)
    its = r.get("items", [])
    if not its:
        raise ValueError(f"채널을 찾지 못함: {ref}")
    return its[0]["id"]


def do_channels(yt, data, refs, max_sec, per, mult):
    chans = {c["id"]: c for c in data["channels"]}
    have = {v["id"]: v for v in data["videos"]}
    for ref in refs:
        try:
            cid = resolve_channel(yt, ref)
            pl = "UU" + cid[2:]
            ids = [i["contentDetails"]["videoId"] for i in yt.call("playlistItems", part="contentDetails", playlistId=pl, maxResults=min(per, 50)).get("items", [])]
            subs = yt.subs([cid])
            items = yt.videos(ids)
        except SystemExit:
            raise
        except Exception as e:
            print(f"  {ref}: 실패 ({e})")
            continue
        rows = [vrow(it, subs, src="channel") for it in items]
        rows = [r for r in rows if not r["secs"] or r["secs"] <= max_sec]
        views = [r["views"] for r in rows]
        med = int(statistics.median(views)) if views else 0
        for r in rows:
            r["x_median"] = round(r["views"] / med, 2) if med else None
            have[r["id"]] = dict(have.get(r["id"], {}), **r)
        info = subs.get(cid, {})
        chans[cid] = {"id": cid, "title": info.get("title", ref), "handle": info.get("handle", ""), "subs": info.get("subs"), "median_views": med,
                      "n": len(rows), "hits": [r["id"] for r in rows if med and r["views"] >= med * mult], "ref": ref, "checked": dt.date.today().isoformat()}
        print(f"  {info.get('title', ref)}: 쇼츠 {len(rows)}개, 중앙값 {med:,}회, 평균의 {mult}배↑ {len(chans[cid]['hits'])}개 (사용 {yt.q['used']}유닛)")
    data["channels"] = list(chans.values())
    data["videos"] = sorted(have.values(), key=lambda v: -(v.get("views") or 0))[:400]


# ---------------- 위키 / 레딧 ----------------
SKIP = re.compile(r"^(Main_Page|Special:|특수:|위키백과:|Wikipedia:|파일:|File:|분류:|Category:|포털:|Portal:|Help:|도움말:|Talk:|-$)")


def wiki_top(lang, day):
    u = f"https://wikimedia.org/api/rest_v1/metrics/pageviews/top/{lang}.wikipedia/all-access/{day:%Y/%m/%d}"
    r = requests.get(u, headers=UA, timeout=25)
    r.raise_for_status()
    arts = r.json()["items"][0]["articles"]
    return [(a["article"], a["views"]) for a in arts if not SKIP.match(a["article"])]


def do_wiki(data, limit):
    lang = "en" if EN else "ko"
    day = dt.date.today() - dt.timedelta(days=2)
    cur = None
    for back in (0, 1, 2):
        try:
            cur = wiki_top(lang, day - dt.timedelta(days=back)); day = day - dt.timedelta(days=back); break
        except Exception:
            continue
    if cur is None:
        raise SystemExit("위키 조회수를 가져오지 못했습니다 (네트워크 확인)")
    try:
        prev = wiki_top(lang, day - dt.timedelta(days=7))
    except Exception:
        prev = []
    prank = {t: i + 1 for i, (t, _) in enumerate(prev)}
    rows = []
    for i, (t, v) in enumerate(cur[:300]):
        pr = prank.get(t)
        rows.append({"title": t.replace("_", " "), "views": v, "rank": i + 1, "prev_rank": pr, "new": pr is None,
                     "jump": (pr - (i + 1)) if pr else 999, "url": f"https://{lang}.wikipedia.org/wiki/{t}", "day": day.isoformat()})
    rows.sort(key=lambda r: (-(r["jump"]), r["rank"]))
    data["wiki"] = rows[:limit]
    print(f"  위키({lang}) {day}: 급상승 {len(data['wiki'])}개 (1주 전 상위권에 없던 문서 {sum(r['new'] for r in data['wiki'])}개)")


def do_reddit(data, subs, period, limit):
    import discover_sns as D
    out = []
    for s in subs:
        try:
            try:
                out += D.fetch_json(s, period, limit)
            except Exception:
                out += D.fetch_rss(s, period, limit)
        except Exception as e:
            print(f"  r/{s}: 실패 ({type(e).__name__})")
        time.sleep(1.5)
    out.sort(key=lambda x: -(x.get("score") or 0))
    data["reddit"] = [{k: x[k] for k in ("source", "title", "url", "score", "comments")} for x in out[:60]]
    print(f"  레딧 {len(data['reddit'])}개")


# ---------------- 분석 ----------------
def do_analyze(data, top):
    from groq import Groq
    key = os.environ.get("GROQ_API_KEY", "").strip()
    if not key:
        raise SystemExit("GROQ_API_KEY 가 없습니다")
    client = Groq(api_key=key)
    mod = __import__("generate_topics" if EN else "generate_culture_facts")
    model = mod.pick_model(client)
    vids = [v for v in data["videos"] if v.get("views")]
    vids.sort(key=lambda v: -((v.get("ratio") or 0) * 3 + (v["views"] ** 0.5) / 100))
    vids = vids[:top]
    if not vids and not data["wiki"] and not data["reddit"]:
        raise SystemExit("분석할 데이터가 없습니다. 먼저 조사를 실행하세요")
    vt = "\n".join(f"[{n}] {v['title']} (조회 {v['views']:,}, 구독자 {v['subs'] if v['subs'] is not None else '?'}, {v['secs']}초)" for n, v in enumerate(vids))
    wt = ", ".join(r["title"] for r in data["wiki"][:25])
    rt = "\n".join(f"- {r['title'][:100]} ({r['score']})" for r in data["reddit"][:15])
    ch = ("한국의 문화·일상·음식·예절·언어를 외국인에게 알려주는 영어 쇼츠 채널 'KoreaAtoZ'" if EN else "세계 각국의 문화·관습·금기·생활 규칙을 알려주는 한국어 쇼츠 채널 '세계 문화 상식'")
    try:
        from common import load_db
        db = load_db()
    except Exception:
        db = []
    done = "\n".join(f"- {str(o.get('country', ''))[:20]} {str(o.get('topic', ''))[:40]}" for o in db[-200:] if o.get("topic"))
    prompt = f"""너는 유튜브 쇼츠 기획자다. 우리 채널: {ch}.
아래는 최근 잘 터진 쇼츠, 위키 급상승 문서, 레딧 화제글이다. 이를 분석해 JSON만 응답해라 (한국어로).
[터진 쇼츠]
{vt or '(없음)'}
[위키 급상승 문서]
{wt or '(없음)'}
[레딧 화제]
{rt or '(없음)'}
[이미 만든 소재 — 이것과 같거나 비슷한 주제는 추천하지 마라]
{done or '(없음)'}

형식: {{"patterns":[{{"name":"제목 패턴 이름","desc":"어떤 구조인지 한 줄","example":"예시 제목"}}],
"hooks":["첫 문장 후크 유형 3~6개 (예: 금지/반전/숫자/공감 질문)"],
"needs":[{{"need":"시청자 니즈 (호기심/공감/놀람/정보/웃음/자랑스러움 등)","evidence":"어떤 영상/글에서 보이는지"}}],
"topic_ideas":[{{"title":"우리 채널에 맞는 소재 제목","why":"왜 지금 먹힐지(근거)","need":"충족하는 니즈","emotion":"유발 감정","source":"근거가 된 영상/문서/글", "src_idx":[근거가 된 [터진 쇼츠] 번호들, 없으면 빈 배열]}}]}}
topic_ideas는 8개. 터진 영상의 제목·문장을 그대로 따라 쓰지 말고, 같은 주제라도 우리 채널의 새로운 각도로 제목을 지어라. 근거 없이 지어내지 말고, 위 자료에 있는 신호만 근거로 써라. 정치·종교 논쟁·연예 가십·선정적 소재는 제외."""
    c = client.chat.completions.create(model=model, messages=[{"role": "user", "content": prompt}], max_completion_tokens=3500, temperature=0.4)
    t = c.choices[0].message.content or ""
    data["analysis"] = json.loads(t[t.find("{"):t.rfind("}") + 1])
    mark_dups(data["analysis"].get("topic_ideas", []), db)
    mark_copies(data["analysis"].get("topic_ideas", []), vids)
    data["analysis"]["texts"] = build_texts(data["analysis"])
    data["analysis"]["at"] = dt.date.today().isoformat()
    print(f"  분석 완료: 패턴 {len(data['analysis'].get('patterns', []))}, 소재 추천 {len(data['analysis'].get('topic_ideas', []))}")


def mark_dups(ideas, db):
    """추천 소재가 이미 만든 소재(폐기 포함)와 겹치면 dup 에 이유를 적는다 (나라 구분 없이 전체 비교)"""
    try:
        import find_dup_topics as FD
    except Exception:
        return
    for t in ideas:
        t.pop("dup", None)
        f = {"topic": t.get("title", ""), "hook": t.get("title", ""), "label": t.get("title", "")}
        best, why, idx = 0.0, "", -1
        for i, o in enumerate(db):
            s, w = FD.score_pair(f, o)
            if s > best:
                best, why, idx = s, w, i
        if best >= 0.4:
            t["dup"] = f"[{idx}] {why}"


def _norm(s):
    return re.sub(r"[^0-9a-z가-힣]", "", str(s or "").lower())


def mark_copies(ideas, vids, thr=0.5):
    """추천 소재 제목이 조사한 영상 제목과 너무 비슷하면 copy 에 적고, 영감이 된 영상 링크를 inspired 에 기록한다"""
    import difflib
    for t in ideas:
        t.pop("copy", None)
        a = _norm(t.get("title"))
        best, bt = 0.0, None
        for v in vids:
            b = _norm(v.get("title"))
            if not a or not b:
                continue
            r = difflib.SequenceMatcher(None, a, b).ratio()
            if r > best:
                best, bt = r, v
        if bt is not None and best >= thr:
            t["copy"] = f"조사한 영상 제목과 {best:.2f} 유사: {bt['title'][:50]}"
        urls = []
        for i in t.get("src_idx") or []:
            try:
                urls.append(vids[int(i)]["url"])
            except Exception:
                pass
        t["inspired"] = urls[:3]


def build_texts(a):
    """소재/대본 프롬프트에 붙일 트렌드 문단. 제목·문장은 전달하지 않고 패턴·후크·니즈만 전달한다"""
    pat = "; ".join(f"{p.get('name')}({p.get('desc')})" for p in (a.get("patterns") or [])[:4])
    hk = ", ".join(map(str, (a.get("hooks") or [])[:5]))
    nd = ", ".join(str(n.get("need")) for n in (a.get("needs") or [])[:4])
    if EN:
        head = "[Recent trend signals - reference only; the notes below are in Korean, write your output in English]"
        top = [f"Title patterns that work lately: {pat}", f"Hook types: {hk}", f"Viewer needs: {nd}",
               "Use these only as direction. Never copy another video's title or wording; facts must come from the given material."]
        sc = [f"Open with a hook of a fitting type: {hk}", f"Serve the viewer's need: {nd}",
              "Do not add facts that are not in the material, and do not copy phrasing from other videos."]
    else:
        head = "[최근 트렌드 신호 - 참고용]"
        top = [f"최근 잘 터진 제목 패턴: {pat}", f"효과적인 후크 유형: {hk}", f"시청자 니즈: {nd}",
               "방향 참고용일 뿐입니다. 다른 영상의 제목·문장을 그대로 따라 쓰지 말고, 사실은 주어진 자료에서만 가져오세요."]
        sc = [f"첫 문장은 소재에 맞는 후크 유형으로 시작: {hk}", f"시청자 니즈를 충족하는 방향으로 구성: {nd}",
              "자료에 없는 사실을 추가하지 말고, 다른 영상의 표현을 그대로 쓰지 마세요."]
    f = lambda L: head + "\n" + "\n".join("- " + x for x in L if x.split(": ", 1)[-1].strip()) if (pat or hk or nd) else ""
    return {"topic": f(top), "script": f(sc)}


def trend_hints(max_chars=900):
    """대본/소재 프롬프트에 붙일 짧은 트렌드 요약 (없으면 빈 문자열)"""
    try:
        a = json.load(open(FILE, encoding="utf-8")).get("analysis") or {}
    except Exception:
        return ""
    if not a:
        return ""
    parts = []
    if a.get("patterns"):
        parts.append("최근 잘 터진 제목 패턴: " + "; ".join(f"{p.get('name')}({p.get('desc')})" for p in a["patterns"][:4]))
    if a.get("hooks"):
        parts.append("효과적인 첫 문장 후크: " + ", ".join(map(str, a["hooks"][:5])))
    if a.get("needs"):
        parts.append("시청자 니즈: " + ", ".join(str(n.get("need")) for n in a["needs"][:4]))
    return "\n".join(parts)[:max_chars]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--yt", default="", help="쉼표로 구분한 검색어")
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--limit", type=int, default=25)
    ap.add_argument("--max-sec", type=int, default=90)
    ap.add_argument("--channels", default="", help="쉼표로 구분한 채널 (@핸들, 채널ID, 주소)")
    ap.add_argument("--per", type=int, default=30, help="채널당 최근 영상 수")
    ap.add_argument("--mult", type=float, default=2.0, help="채널 중앙값의 몇 배 이상이면 '터진 영상'")
    ap.add_argument("--wiki", action="store_true")
    ap.add_argument("--wiki-limit", type=int, default=40)
    ap.add_argument("--reddit", default="")
    ap.add_argument("--period", default="week")
    ap.add_argument("--analyze", action="store_true")
    ap.add_argument("--top", type=int, default=25)
    ap.add_argument("--max-units", type=int, default=3000)
    ap.add_argument("--fresh", action="store_true")
    ap.add_argument("--test-key", action="store_true")
    a = ap.parse_args()
    data = load()
    split = lambda s: [x.strip() for x in s.split(",") if x.strip()]
    if a.test_key:
        yt = YT(data, a.max_units)
        r = yt.call("videos", part="id", id="dQw4w9WgXcQ")
        print("키 정상 작동" if r.get("items") is not None else "응답 이상")
        save(data); return
    yt = None
    if a.yt or a.channels:
        yt = YT(data, a.max_units)
    try:
        if a.yt:
            print("▶ 유튜브 키워드 조사"); do_search(yt, data, split(a.yt), a.days, a.limit, a.max_sec, a.fresh)
        if a.channels:
            print("▶ 채널 조사"); do_channels(yt, data, split(a.channels), a.max_sec, a.per, a.mult)
        if a.wiki:
            print("▶ 위키 급상승"); do_wiki(data, a.wiki_limit)
        if a.reddit:
            print("▶ 레딧"); do_reddit(data, split(a.reddit), a.period, a.limit)
        if a.analyze:
            print("▶ 분석"); do_analyze(data, a.top)
    finally:
        save(data)
        if yt:
            print(f"오늘 YouTube 사용량: {yt.q['used']}유닛 / 제한 {a.max_units}")


if __name__ == "__main__":
    main()
