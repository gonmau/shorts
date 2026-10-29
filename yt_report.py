# -*- coding: utf-8 -*-
"""유튜브 분석(Analytics API) -> 영상 제작 개선용 주간 리포트.

- 영상별 조회수/평균 시청 비율/구독 증가/유지율 곡선을 받아 facts_db.json 의 소재 정보(나라·분야·길이)와 묶어
  '어떤 유형이 잘 나오는지', '어디서 이탈하는지'를 정리한다. 결과: yt_report.md, yt_stats.json (+ 디스코드).
- 필요한 환경변수: YT_CLIENT_ID, YT_CLIENT_SECRET, YT_REFRESH_TOKEN (yt-analytics.readonly 권한 포함 토큰)
- 영상 수가 적으면 우연이 크다: 한 유형이 표본 3개 미만이면 '참고용'으로만 표시한다.
사용: python yt_report.py [--days 28] [--top 5] [--no-discord]"""
import argparse
import json
import os
import re
import statistics as st
import time
from datetime import date, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parent
SCOPES = ["https://www.googleapis.com/auth/yt-analytics.readonly", "https://www.googleapis.com/auth/youtube.readonly"]
MIN_N = 3


def services():
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    c = Credentials(None, refresh_token=os.environ["YT_REFRESH_TOKEN"], token_uri="https://oauth2.googleapis.com/token",
                    client_id=os.environ["YT_CLIENT_ID"], client_secret=os.environ["YT_CLIENT_SECRET"], scopes=SCOPES)
    return build("youtubeAnalytics", "v2", credentials=c, cache_discovery=False), build("youtube", "v3", credentials=c, cache_discovery=False)


def _rows(resp):
    cols = [h["name"] for h in resp.get("columnHeaders", [])]
    return [dict(zip(cols, r)) for r in resp.get("rows") or []]


def iso_seconds(d):
    m = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", d or "")
    if not m:
        return 0
    h, mi, s = (int(x or 0) for x in m.groups())
    return h * 3600 + mi * 60 + s


def fetch(an, yt, days, top):
    end = date.today() - timedelta(days=1)
    start = end - timedelta(days=days - 1)
    q = dict(ids="channel==MINE", startDate=start.isoformat(), endDate=end.isoformat())
    vids = _rows(an.reports().query(**q, dimensions="video", sort="-views", maxResults=200,
                                   metrics="views,estimatedMinutesWatched,averageViewDuration,averageViewPercentage,likes,comments,subscribersGained,shares").execute())
    meta = {}
    ids = [v["video"] for v in vids]
    try:
        for i in range(0, len(ids), 50):
            for it in yt.videos().list(part="snippet,contentDetails", id=",".join(ids[i:i + 50])).execute().get("items", []):
                meta[it["id"]] = {"title": it["snippet"]["title"], "published": it["snippet"]["publishedAt"][:10],
                                  "sec": iso_seconds(it["contentDetails"].get("duration"))}
    except Exception as e:   # youtube.readonly 권한이 없어도 동작: 길이는 (평균 시청 시간 / 평균 시청 비율)로 추정, 제목은 DB에서
        print(f"  영상 정보 조회 불가({type(e).__name__}) -> 분석 데이터로 길이를 추정하고 제목은 DB에서 찾습니다", flush=True)
        titles = {f.get("youtube_id"): (f.get("title_line1", "") + " " + f.get("title_line2", "")).strip() or f.get("topic", "")
                  for f in load_db() if f.get("youtube_id")}
        for v in vids:
            pct = float(v.get("averageViewPercentage") or 0)
            dur = float(v.get("averageViewDuration") or 0)
            meta[v["video"]] = {"title": titles.get(v["video"]) or v["video"], "published": "",
                                "sec": int(round(dur / (pct / 100))) if pct > 1 else 0}
    traffic = _rows(an.reports().query(**q, dimensions="insightTrafficSourceType", metrics="views,estimatedMinutesWatched", sort="-views").execute())
    out = []
    for v in vids:
        m = meta.get(v["video"], {})
        out.append({**v, "id": v["video"], **m})
    for v in out[:top] + out[-top:]:       # 유지율 곡선은 상위/하위 영상만 (호출 수 절약)
        if "ret" in v:
            continue
        try:
            r = _rows(an.reports().query(**q, dimensions="elapsedVideoTimeRatio", metrics="audienceWatchRatio",
                                         filters=f"video=={v['id']}").execute())
            v["ret"] = [round(float(x["audienceWatchRatio"]), 3) for x in sorted(r, key=lambda x: float(x["elapsedVideoTimeRatio"]))]
        except Exception as e:
            v["ret"] = []
            print(f"  유지율 조회 실패 {v['id']}: {type(e).__name__}", flush=True)
    return {"start": start.isoformat(), "end": end.isoformat(), "videos": out, "traffic": traffic}


def load_db():
    try:
        return json.loads((BASE / "facts_db.json").read_text(encoding="utf-8"))
    except Exception:
        return []


def load_lf():
    try:
        return json.loads((BASE / "longform_db.json").read_text(encoding="utf-8"))
    except Exception:
        return []


IS_EN = (BASE / "generate_topics.py").exists()      # 영어 채널: country 칸이 소재 제목이라 나라별 집계가 의미 없음
NOT_THEME = {"manual", "keyword", "직접 입력", "키워드", ""}


def ko_country(name):
    """'Wales'/'미국'처럼 섞인 나라 표기를 한국어 하나로 통일 (영어 채널은 그대로)"""
    if IS_EN or not name:
        return name
    UK = {"wales": "웨일스", "웨일스": "웨일스", "scotland": "스코틀랜드", "스코틀랜드": "스코틀랜드",
          "england": "잉글랜드", "잉글랜드": "잉글랜드", "northern ireland": "북아일랜드", "북아일랜드": "북아일랜드"}
    if str(name).strip().lower() in UK:
        return UK[str(name).strip().lower()]
    try:
        from country_codes import country_code, NAMES
        c = country_code(name)
        if c and c in NAMES:
            return NAMES[c][0]
    except Exception:
        pass
    return name


def attach(videos, db, lf):
    by_id = {f.get("youtube_id"): f for f in db if f.get("youtube_id")}
    lf_titles = {re.sub(r"\s+", "", str(r.get("title", "")).split("|")[0]): r for r in lf}
    for v in videos:
        f = by_id.get(v["id"])
        v["kind"] = "short" if (v.get("sec") or 0) <= 180 else "long"
        if f:
            v.update({"own": True, "country": ko_country(f.get("country", "")), "theme": f.get("theme", ""), "topic": f.get("topic", ""),
                      "idx": db.index(f), "chars": len(str(f.get("narration", "")))})
        elif v["kind"] == "long":
            r = lf_titles.get(re.sub(r"\s+", "", str(v.get("title", "")).split("|")[0]))
            if r:
                v["own"] = True
                v["members"] = r.get("members", [])
    return videos


def mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else 0.0


def group(videos, key, kind="short"):
    g = {}
    for v in videos:
        if v.get("kind") != kind or not v.get(key):
            continue
        g.setdefault(v[key], []).append(v)
    rows = []
    for k, vs in g.items():
        rows.append({"key": k, "n": len(vs), "views": mean([float(x.get("views", 0)) for x in vs]),
                     "pct": mean([float(x.get("averageViewPercentage", 0)) for x in vs]),
                     "subs": sum(float(x.get("subscribersGained", 0)) for x in vs)})
    return sorted(rows, key=lambda r: -r["views"])


def retention_summary(videos):
    """유지율 곡선 -> (3% 지점 시청 비율 중앙값, 절반 이탈 지점 중앙값)"""
    early, half = [], []
    for v in videos:
        r = v.get("ret") or []
        if len(r) < 20:
            continue
        early.append(min(1.0, r[min(len(r) - 1, 3)]))      # 재시청으로 100% 넘는 값은 100%로
        h = next((i / len(r) for i, x in enumerate(r) if x < 0.5), None)
        half.append(h if h is not None else 1.0)
    return (st.median(early) if early else None, st.median(half) if half else None, len(early))


def fmt_sec(s):
    s = int(s or 0)
    return f"{s // 60}:{s % 60:02d}"


def build_report(data, db, lf, days, top):
    vids = attach(data["videos"], db, lf)
    all_n = len(vids)
    if any(v.get("own") for v in vids):      # 채널의 다른 영상(음악, 현장 영상 등)은 비교에서 제외
        vids_all = vids
        vids = [v for v in vids if v.get("own")]
    else:
        vids_all = vids
    sh = [v for v in vids if v["kind"] == "short"]
    lg = [v for v in vids if v["kind"] == "long"]
    L = [f"# 유튜브 성과 리포트 ({data['start']} ~ {data['end']}, {days}일)", ""]
    tv = sum(float(v.get("views", 0)) for v in vids)
    L.append(f"영상 {len(vids)}개 (쇼츠 {len(sh)} · 롱폼 {len(lg)}) · 조회수 합계 {int(tv):,} · 구독 증가 {int(sum(float(v.get('subscribersGained', 0)) for v in vids)):,}")
    if all_n > len(vids):
        L.append(f"(자동 제작 영상만 집계: 채널의 다른 영상 {all_n - len(vids)}개는 제외)")
    if data.get("traffic"):
        tt = sum(float(t["views"]) for t in data["traffic"]) or 1
        L.append("유입: " + " · ".join(f"{t['insightTrafficSourceType']} {float(t['views']) / tt * 100:.0f}%" for t in data["traffic"][:5]))
    L.append("")

    def line(v):
        tag = f"[{v.get('idx')}] " if v.get("idx") is not None else ""
        return (f"- {tag}{str(v.get('title', ''))[:42]} · 조회 {int(float(v.get('views', 0))):,} · 평균 {float(v.get('averageViewPercentage', 0)):.0f}% "
                f"({fmt_sec(v.get('averageViewDuration'))}/{fmt_sec(v.get('sec'))}) · 구독 +{int(float(v.get('subscribersGained', 0)))}")
    for name, vs in (("쇼츠", sh), ("롱폼", lg)):
        if not vs:
            continue
        L += [f"## {name} 상위 {min(top, len(vs))} / 하위 {min(top, max(0, len(vs) - top))}"]
        L += [line(v) for v in vs[:top]]
        if len(vs) > top * 2:
            L.append("  … (중간 생략)")
        L += [line(v) for v in vs[max(top, len(vs) - top):]]
        L.append("")
    notes = []
    for key, label in (("theme", "분야"), ("country", "나라")):
        if key == "country" and IS_EN:
            continue
        rows = group(vids, key)
        if key == "theme":
            rows = [r for r in rows if r["key"] not in NOT_THEME]
        if key == "country":                 # 나라는 1편짜리가 대부분이라 2편 이상인 나라만 비교
            rows = [r for r in rows if r["n"] >= 2]
        if rows:
            L.append(f"## 쇼츠 {label}별 평균 (표본 {MIN_N}개 미만은 참고용 *)")
            for r in rows[:8]:
                L.append(f"- {r['key']}{'*' if r['n'] < MIN_N else ''}: {r['n']}편 · 평균 조회 {r['views']:.0f} · 평균 시청 {r['pct']:.0f}% · 구독 +{r['subs']:.0f}")
            L.append("")
            good = [r for r in rows if r["n"] >= MIN_N]
            if len(good) >= 2 and good[0]["views"] > good[-1]["views"] * 1.3:   # 차이가 30% 미만이면 우연으로 보고 제안하지 않음
                notes.append(f"{label}: '{good[0]['key']}'이(가) 평균 조회 {good[0]['views']:.0f}로 가장 높고 '{good[-1]['key']}'이(가) {good[-1]['views']:.0f}로 가장 낮습니다 -> 소재 선택 시 비중 조정 검토")
    # 길이 구간
    if len([v for v in sh if v.get("sec")]) >= 6 and len({v["sec"] for v in sh if v.get("sec")}) > 1:
        short_vs = [v for v in sh if v.get("sec")]
        med = st.median([v["sec"] for v in short_vs])
        a = [v for v in short_vs if v["sec"] <= med]
        b = [v for v in short_vs if v["sec"] > med]
        if not a or not b:
            a, b = [v for v in short_vs if v["sec"] < med] or a, [v for v in short_vs if v["sec"] >= med] or b
        L.append(f"## 쇼츠 길이별 (중앙값 {med:.0f}초)")
        L.append(f"- 짧은 쪽 {len(a)}편: 평균 시청 {mean([float(x.get('averageViewPercentage', 0)) for x in a]):.0f}% · 조회 {mean([float(x.get('views', 0)) for x in a]):.0f}")
        L.append(f"- 긴 쪽 {len(b)}편: 평균 시청 {mean([float(x.get('averageViewPercentage', 0)) for x in b]):.0f}% · 조회 {mean([float(x.get('views', 0)) for x in b]):.0f}")
        L.append("")
    for name, vs in (("쇼츠", sh), ("롱폼", lg)):
        e, h, n = retention_summary(vs)
        if n:
            L.append(f"## {name} 유지율 (곡선을 받은 {n}편)")
            L.append(f"- 시작 3% 지점까지 남은 시청자: 중앙값 {e * 100:.0f}% · 시청자 절반이 떠나는 지점: 영상의 {h * 100:.0f}%")
            if e < 0.6:
                notes.append(f"{name}: 초반 이탈이 큽니다(시작 직후 {e * 100:.0f}%만 남음) -> 후크 첫 문장 강화, 첫 장면 전환을 빠르게")
            if h < (0.3 if name == "쇼츠" else 0.15):
                notes.append(f"{name}: 영상의 {h * 100:.0f}% 지점에서 시청자 절반이 이탈합니다 -> 중반 장면 전환/키워드 팝업 간격 단축, 대본 길이 축소 검토")
            L.append("")
    if notes:
        L += ["## 제안 (참고용: 표본이 적으면 우연일 수 있음)"] + [f"- {x}" for x in notes] + [""]
    if len(vids) < 20:
        L.append("※ 영상 수가 적어(20편 미만) 유형별 비교는 불확실합니다. 데이터가 쌓일수록 정확해집니다.")
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=28)
    ap.add_argument("--top", type=int, default=5)
    ap.add_argument("--no-discord", action="store_true")
    a = ap.parse_args()
    for k in ("YT_CLIENT_ID", "YT_CLIENT_SECRET", "YT_REFRESH_TOKEN"):
        if not os.environ.get(k):
            raise SystemExit(f"{k} 가 없습니다 (GitHub Secrets 확인). 분석 권한(yt-analytics.readonly)이 포함된 토큰이어야 합니다.")
    an, yt = services()
    try:
        data = fetch(an, yt, a.days, a.top)
    except Exception as e:
        msg = str(e)
        if "403" in msg or "insufficient" in msg.lower() or "forbidden" in msg.lower():
            raise SystemExit("분석 데이터 접근 거부: 토큰에 yt-analytics.readonly 권한이 없거나 YouTube Analytics API가 꺼져 있습니다. get_refresh_token.py 로 다시 발급하세요.")
        raise
    rep = build_report(data, load_db(), load_lf(), a.days, a.top)
    (BASE / "yt_report.md").write_text(rep + "\n", encoding="utf-8")
    hist_p = BASE / "yt_stats.json"
    try:
        hist = json.loads(hist_p.read_text(encoding="utf-8"))
    except Exception:
        hist = []
    hist.append({"date": date.today().isoformat(), "days": a.days, "start": data["start"], "end": data["end"],
                 "videos": [{k: v for k, v in x.items() if k != "ret"} | ({"ret": x["ret"][::5]} if x.get("ret") else {}) for x in data["videos"]]})
    hist_p.write_text(json.dumps(hist[-26:], ensure_ascii=False), encoding="utf-8")
    print(rep)
    url = os.environ.get("DISCORD_WEBHOOK_URL")
    if url and not a.no_discord:
        try:
            ch = "KoreaAtoZ" if (BASE / "generate_topics.py").exists() else "세계문화"
            from notify_discord import post_file
            lines = rep.splitlines()
            cut = next((i for i, x in enumerate(lines) if x.startswith("## ")), len(lines))
            head = [x for x in lines[:cut] if x.strip()]
            if "## 제안 (참고용: 표본이 적으면 우연일 수 있음)" in lines:        # 제안은 메시지에도 보여줌
                k = lines.index("## 제안 (참고용: 표본이 적으면 우연일 수 있음)")
                head += [""] + [x for x in lines[k:] if x.strip()][:6]
            post_file(url, BASE / "yt_report.md", f"📈 [{ch}] 유튜브 성과 리포트\n" + "\n".join(head)[:1500] + "\n📎 전체 리포트는 첨부 파일")
        except Exception as e:
            print("디스코드 전송 실패:", e)


if __name__ == "__main__":
    main()
