# -*- coding: utf-8 -*-
"""UI '📊 현황' 탭: 소재 진행 · 업로드 · 조회수 · 실행 이력을 표와 그래프로 한눈에. (읽기 전용 — DB를 바꾸지 않습니다)"""
import json
import os
import time
from datetime import datetime, timedelta, timezone

import pandas as pd

KST = timezone(timedelta(hours=9))
STAGES = [("unverified", "1 승인 대기"), ("verified", "2 승인됨"), ("scripted", "3 대본 완료"),
          ("tts_done", "4 음성 완료"), ("video_done", "5 영상 완료"), ("rejected", "폐기")]


def _jl(path):
    out = []
    if os.path.exists(path):
        for ln in open(path, encoding="utf-8"):
            try:
                out.append(json.loads(ln))
            except Exception:
                pass
    return out


def _day(v):
    s = str(v or "")[:10]
    return s if len(s) == 10 and s[4] == "-" else ""


def _has_video(f):
    return bool(f.get("video_path_v6") or f.get("status_v6") == "video_done")


def _fetch_stats(repo, force=False, max_age_h=6):
    """yt_stats.json 은 Actions(yt_report)가 GitHub에 올리는 파일이라 PC에는 없다. 없거나 오래되면 GitHub에서 받아 PC에 저장한다.
    -> (데이터 또는 [], 메모)"""
    path = "yt_stats.json"
    try:
        fresh = os.path.exists(path) and (time.time() - os.path.getmtime(path)) < max_age_h * 3600
    except OSError:
        fresh = False
    note = ""
    if repo and (force or not fresh):
        try:
            import requests
            url = f"https://raw.githubusercontent.com/{repo}/main/{path}"
            r = requests.get(url, headers={"User-Agent": "shorts-ui"}, timeout=20)      # 공개 저장소는 토큰 없이
            tok = os.environ.get("GITHUB_TOKEN", "").strip()
            if r.status_code in (403, 404) and tok:                                      # 비공개면 토큰으로 재시도
                r = requests.get(url, headers={"User-Agent": "shorts-ui", "Authorization": f"Bearer {tok}"}, timeout=20)
            if r.status_code == 200 and isinstance(r.json(), list):
                open(path, "w", encoding="utf-8").write(r.text)
                note = f"GitHub({repo})에서 새로 받음"
            else:
                note = f"GitHub에서 못 받음 (HTTP {r.status_code})" + (" - 비공개 저장소면 GITHUB_TOKEN 필요" if r.status_code == 404 else "")
        except Exception as e:
            note = f"GitHub에서 못 받음 ({type(e).__name__})"
    try:
        return json.load(open(path, encoding="utf-8")), note
    except Exception:
        return [], note


def render(st, db, start=0, daily_max=None, repo=""):
    today = datetime.now(KST).strftime("%Y-%m-%d")
    if start > 0:
        use_si = st.checkbox(f"start_index {start} 이상만 보기 (끄면 전체 DB {len(db)}개 기준)", False, key="dash_si")
        start = start if use_si else 0
    items = [(i, f) for i, f in enumerate(db) if i >= start]
    uploaded = [(i, f) for i, f in items if f.get("youtube_id")]
    rejected = [(i, f) for i, f in items if f.get("status") == "rejected"]
    waiting_up = [(i, f) for i, f in items if not f.get("youtube_id") and _has_video(f) and f.get("status") != "rejected"]
    waiting_render = [(i, f) for i, f in items if not _has_video(f) and f.get("status") in ("scripted", "tts_done")]
    today_up = sum(1 for _, f in uploaded if _day(f.get("uploaded_at")) == today)

    st.caption((f"소재 번호 {start} 이상 {len(items)}개 기준" if start > 0 else f"전체 DB {len(db)}개 기준") + " · 이 탭은 읽기 전용입니다.")
    c = st.columns(6)
    c[0].metric("업로드됨", len(uploaded), f"오늘 +{today_up}")
    c[1].metric("업로드 대기", len(waiting_up), help="영상은 있고 아직 안 올린 소재 (폐기 제외)")
    c[2].metric("렌더링 대기", len(waiting_render), help="대본·음성은 있고 영상이 없는 소재")
    c[3].metric("승인 대기", sum(1 for _, f in items if f.get("status") == "unverified"))
    c[4].metric("폐기", len(rejected))
    c[5].metric("오늘 업로드 한도", f"{today_up}/{daily_max}" if daily_max else str(today_up))

    left, right = st.columns(2)
    with left:
        st.markdown("**① 단계별 소재 수**")
        cnt = {}
        for _, f in items:
            cnt[f.get("status")] = cnt.get(f.get("status"), 0) + 1
        df = pd.DataFrame({"소재 수": [cnt.get(k, 0) for k, _ in STAGES]}, index=[lb for _, lb in STAGES])
        st.bar_chart(df)
    with right:
        st.markdown("**② 최근 30일 일별 업로드 수**")
        days = [(datetime.now(KST) - timedelta(days=n)).strftime("%m-%d") for n in range(29, -1, -1)]
        full = [(datetime.now(KST) - timedelta(days=n)).strftime("%Y-%m-%d") for n in range(29, -1, -1)]
        per = {}
        for _, f in uploaded:
            d = _day(f.get("uploaded_at"))
            if d:
                per[d] = per.get(d, 0) + 1
        st.bar_chart(pd.DataFrame({"업로드": [per.get(d, 0) for d in full]}, index=days))
        no_date = sum(1 for _, f in uploaded if not _day(f.get("uploaded_at")))
        if no_date:
            st.caption(f"업로드 날짜가 기록되지 않은 소재 {no_date}개는 그래프에 없습니다.")

    # ---- 조회수 (yt_stats.json = 마지막 리포트 시점) ----
    st.markdown("**③ 조회수 (마지막 유튜브 리포트 기준)**")
    _rf = st.button("🔄 조회수 새로고침 (GitHub에서 받기)", key="dash_stats_rf") if repo else False
    snaps, _note = _fetch_stats(repo, force=_rf)
    if _note:
        st.caption(_note)
    if not snaps:
        st.info("조회수 데이터(yt_stats.json)가 없습니다. 유튜브 리포트(yt_report) 워크플로가 한 번 돌아 GitHub에 올라와야 합니다." + ("" if repo else " (GitHub 저장소 설정이 없어 받지 못했습니다)"))
    else:
        s = snaps[-1]
        vids = [v for v in s.get("videos", []) if v.get("kind", "short") == "short"] or s.get("videos", [])
        st.caption(f"리포트 {s.get('date', '?')} · 최근 {s.get('days', '?')}일({s.get('start', '')}~{s.get('end', '')}) · 영상 {len(vids)}개")
        if vids:
            v = pd.DataFrame(vids)
            v["published"] = v.get("published")
            g1, g2 = st.columns(2)
            with g1:
                st.markdown("업로드일별 평균 조회수")
                by = v.groupby("published")["views"].mean().round(0)
                st.line_chart(by.rename("평균 조회수"))
            with g2:
                st.markdown("조회수 vs 평균 시청 비율(%)")
                if "averageViewPercentage" in v:
                    st.scatter_chart(v, x="views", y="averageViewPercentage") if hasattr(st, "scatter_chart") else st.line_chart(v.set_index("published")["averageViewPercentage"])
            top = v.sort_values("views", ascending=False)
            cols = [c_ for c_ in ("title", "views", "averageViewDuration", "averageViewPercentage", "likes", "subscribersGained", "published") if c_ in top]
            ren = {"title": "제목", "views": "조회수", "averageViewDuration": "평균 시청(초)", "averageViewPercentage": "평균 시청%",
                   "likes": "좋아요", "subscribersGained": "구독 증가", "published": "업로드일"}
            t1, t2 = st.tabs(["상위 10", "하위 10"])
            t1.dataframe(top[cols].head(10).rename(columns=ren), hide_index=True)
            t2.dataframe(top[cols].tail(10).iloc[::-1].rename(columns=ren), hide_index=True)
            st.caption(f"평균 조회수 {v['views'].mean():,.0f} · 중앙값 {v['views'].median():,.0f}" +
                       (f" · 평균 시청% {v['averageViewPercentage'].mean():.1f}" if "averageViewPercentage" in v else ""))

    # ---- 조회수 원인 분석 ----
    if snaps:
        with st.expander("📈 조회수 원인 분석 (출처·길이·목소리·주차별)"):
            min_age = st.number_input("올린 지 최소 며칠 지난 영상만 (조회수가 쌓일 시간)", 1, 30, 3, key="dash_minage")
            since = st.text_input("이 날짜 이후 업로드만 (YYYY-MM-DD)", "2026-10-13", key="dash_since")
            byid = {f.get("youtube_id"): (i, f) for i, f in enumerate(db) if f.get("youtube_id")}
            today_d = datetime.now(KST).date()
            rows = []
            for v in [x for x in snaps[-1].get("videos", []) if x.get("kind", "short") == "short"]:
                m = byid.get(v.get("id"))
                if not m or not v.get("published") or str(v["published"]) < since:
                    continue
                try:
                    pub = datetime.strptime(str(v["published"])[:10], "%Y-%m-%d").date()
                except ValueError:
                    continue
                if (today_d - pub).days < min_age:
                    continue
                f = m[1]
                p_ = str(f.get("video_path_v6") or "")
                src = "GitHub 자동" if p_.startswith("/home/runner") else ("PC" if p_ else "알 수 없음")
                sec = int(v.get("sec") or 0)
                rows.append({"views": v.get("views", 0), "출처": src, "길이": (f"{sec // 10 * 10}~{sec // 10 * 10 + 9}초" if sec else "?"),
                             "목소리": str(f.get("tts_voice_v2") or "?").replace("ko-KR-", "").replace("en-US-", "").replace("Neural", ""),
                             "주차": f"{pub.isocalendar()[1]}주차"})
            if not rows:
                st.info("조건에 맞는 영상이 없습니다.")
            else:
                df2 = pd.DataFrame(rows)
                st.caption(f"영상 {len(df2)}개 · 양호 = 조회 300 이상, 저조 = 50 미만. 편수가 적은 그룹은 참고만 하세요. 출처는 영상 파일 경로로 추정합니다 (/home/runner = GitHub 자동).")
                for col in ("출처", "목소리", "길이", "주차"):
                    g = df2.groupby(col)["views"].agg(편수="count", 중앙값="median", 평균="mean",
                                                      **{"양호%": lambda s: round(100 * (s >= 300).mean()), "저조%": lambda s: round(100 * (s < 50).mean())})
                    g["평균"] = g["평균"].round(0)
                    st.markdown(f"**{col}별**")
                    st.dataframe(g.sort_index())

    # ---- 실행 이력 ----
    st.markdown("**④ 실행 이력**")
    hist = _jl("run_history.jsonl")
    if not hist:
        st.info("run_history.jsonl 이 없습니다.")
    else:
        h = pd.DataFrame(hist)
        h["day"] = h["time"].astype(str).str[:10]
        w = h[h["day"] >= (datetime.now(KST) - timedelta(days=7)).strftime("%Y-%m-%d")]
        a, b = st.columns(2)
        with a:
            st.markdown("최근 7일 실행 결과 (출처별)")
            if len(w):
                pv = w.pivot_table(index="source", columns="status", values="id", aggfunc="count", fill_value=0)
                st.dataframe(pv)
            else:
                st.caption("최근 7일 기록 없음")
        with b:
            st.markdown("작업별 평균 소요시간 (초, 측정된 것만)")
            t = h[h["secs"].notna()]
            if len(t):
                tt = t.groupby("kind")["secs"].agg(["count", "mean"]).round(0).sort_values("mean", ascending=False)
                tt.columns = ["횟수", "평균(초)"]
                st.dataframe(tt.head(10))
            else:
                st.caption("소요시간 기록 없음")
        fails = h[h["status"].astype(str).str.lower().isin(["failure", "fail", "failed", "error"])].tail(10)
        st.markdown("최근 실패 10건" if len(fails) else "최근 실패 없음 ✅")
        if len(fails):
            st.dataframe(fails[["time", "channel", "source", "kind", "title"]].iloc[::-1], hide_index=True)
        with st.expander("최근 실행 20건"):
            st.dataframe(h.tail(20).iloc[::-1][["time", "channel", "source", "kind", "title", "status", "secs"]], hide_index=True)

    # ---- 확인 필요 ----
    st.markdown("**⑤ 확인이 필요한 소재**")
    probs = []
    for i, f in waiting_up:
        p = str(f.get("video_path_v6") or "")
        if p and not os.path.exists(p):
            probs.append((i, f.get("label") or f.get("country") or "", "업로드 대기인데 영상 파일이 없음"))
    for i, f in uploaded:
        if f.get("status") == "rejected":
            probs.append((i, f.get("label") or f.get("country") or "", "폐기했지만 유튜브에 올라가 있음 (스튜디오에서 삭제 확인)"))
    for i, f in waiting_render:
        if not f.get("narration"):
            probs.append((i, f.get("label") or f.get("country") or "", "렌더링 대기인데 대본이 비어 있음"))
    if probs:
        st.dataframe(pd.DataFrame(probs, columns=["번호", "소재", "문제"]), hide_index=True)
    else:
        st.success("확인이 필요한 소재가 없습니다.")
