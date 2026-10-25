# -*- coding: utf-8 -*-
"""가벼운 웹 UI (아이패드/폰 브라우저용). 렌더링은 하지 않는다.
GitHub 저장소의 facts_db.json 을 읽고 고쳐 커밋하고, Actions(prepare/render)를 실행한다.
Streamlit Cloud 에 올리고 Secrets 에 GITHUB_TOKEN, REPOS 를 넣는다 (README_web_ui.md 참고)."""
import base64
import json

import requests
import streamlit as st

st.set_page_config(page_title="쇼츠 관리", page_icon="🎬", layout="centered")
API = "https://api.github.com"
STATUSES = ["unverified", "verified", "scripted", "video_done", "rejected"]
STATUS_KO = {"unverified": "미확인", "verified": "승인", "scripted": "대본완료", "video_done": "영상완료", "rejected": "폐기"}


def secret(name, default=""):
    try:
        return st.secrets[name]
    except Exception:
        return default


TOKEN = secret("GITHUB_TOKEN")
REPOS = dict(secret("REPOS", {}) or {})
BRANCH = secret("BRANCH", "main")

if not TOKEN or not REPOS:
    st.title("🎬 쇼츠 관리")
    st.error("Streamlit Secrets에 GITHUB_TOKEN 과 REPOS 를 넣어야 합니다. (README_web_ui.md 참고)")
    st.stop()


PW = secret("APP_PASSWORD")
if PW and st.session_state.get("authed") != True:
    st.title("🎬 쇼츠 관리")
    pw = st.text_input("비밀번호", type="password")
    if pw and pw == PW:
        st.session_state["authed"] = True
        st.rerun()
    elif pw:
        st.error("비밀번호가 틀립니다.")
    st.stop()
if not PW:
    st.warning("APP_PASSWORD 가 없습니다. 앱 URL을 아는 누구나 사용할 수 있으니 Secrets에 꼭 넣으세요.")


def hdr():
    return {"Authorization": f"Bearer {TOKEN}", "Accept": "application/vnd.github+json"}


def load_db(repo):
    r = requests.get(f"{API}/repos/{repo}/contents/facts_db.json", params={"ref": BRANCH}, headers=hdr(), timeout=30)
    r.raise_for_status()
    meta = r.json()
    if meta.get("content"):
        raw = base64.b64decode(meta["content"])
    else:  # 1MB 초과
        b = requests.get(f"{API}/repos/{repo}/git/blobs/{meta['sha']}", headers=hdr(), timeout=60)
        b.raise_for_status()
        raw = base64.b64decode(b.json()["content"])
    return json.loads(raw.decode("utf-8")), meta["sha"]


def save_db(repo, db, sha, msg):
    body = {"message": msg, "branch": BRANCH, "sha": sha,
            "content": base64.b64encode(json.dumps(db, ensure_ascii=False, indent=2).encode("utf-8")).decode()}
    r = requests.put(f"{API}/repos/{repo}/contents/facts_db.json", json=body, headers=hdr(), timeout=60)
    r.raise_for_status()
    return r.json()["content"]["sha"]


def apply_changes(repo, changes, msg):
    """저장 직전에 최신 DB를 다시 받아 변경만 적용한다 (Actions가 그 사이 커밋했어도 덮어쓰지 않음).
    changes: [(index, country, fn(item))]"""
    db, sha = load_db(repo)
    for i, country, fn in changes:
        if i >= len(db) or db[i].get("country") != country:
            st.error(f"{i}번 소재가 서버와 달라졌습니다. 새로고침 후 다시 시도하세요.")
            return False
        fn(db[i])
    save_db(repo, db, sha, msg + " [skip ci]")
    st.session_state.pop("db_cache", None)
    return True


def get_db(repo, force=False):
    c = st.session_state.get("db_cache")
    if force or not c or c[0] != repo:
        db, sha = load_db(repo)
        st.session_state["db_cache"] = (repo, db, sha)
    return st.session_state["db_cache"][1]


def up_state(f):
    if f.get("youtube_id"):
        pv = {"public": "공개", "private": "비공개", "unlisted": "일부공개"}.get(f.get("youtube_privacy"), "")
        return f"업로드({pv})" if pv else "업로드"
    if f.get("video_path_v6") or f.get("status_v6") == "video_done":
        return "영상완료(미업로드)"
    return ""


def lab(db, i):
    f = db[i]
    t = " ".join(x for x in (f.get("title_line1"), f.get("title_line2")) if x) or str(f.get("topic") or "")
    u = up_state(f)
    return f"{i} · {f.get('label') or f.get('country', '')} · {' '.join(t.split())[:30]}" + (f" · {u}" if u else "")


def set_status(item, s, reason=""):
    item["status"] = s
    if s == "rejected":
        item["reject_reason"] = reason or "웹 UI에서 폐기"
    else:
        item.pop("reject_reason", None)
    if s == "video_done":
        item["status_v6"] = "video_done"


st.title("🎬 쇼츠 관리")
chan = st.radio("채널", list(REPOS), horizontal=True)
repo = REPOS[chan]
c1, c2 = st.columns([3, 1])
c1.caption(f"{repo} · {BRANCH}")
if c2.button("🔄 새로고침"):
    get_db(repo, force=True)
try:
    db = get_db(repo)
except Exception as e:
    st.error(f"facts_db.json 을 못 읽었습니다: {e}")
    st.stop()

counts = {s: sum(1 for f in db if f.get("status") == s) for s in STATUSES}
st.write(" · ".join(f"{STATUS_KO[s]} {n}" for s, n in counts.items()) + f" · 전체 {len(db)}")
_up = sum(1 for f in db if f.get("youtube_id"))
_vd = sum(1 for f in db if not f.get("youtube_id") and (f.get("video_path_v6") or f.get("status_v6") == "video_done"))
st.write(f"업로드됨 {_up} · 영상완료/미업로드 {_vd}")

tab_edit, tab_state, tab_run = st.tabs(["📝 대본 보기/수정", "🗂 상태 변경", "▶ 실행(Actions)"])

with tab_edit:
    flt = st.selectbox("상태 필터", ["전체"] + STATUSES, format_func=lambda s: s if s == "전체" else STATUS_KO[s], index=3, key="flt_e")
    idxs = [i for i, f in enumerate(db) if flt == "전체" or f.get("status") == flt]
    if not idxs:
        st.info("해당 소재가 없습니다.")
    else:
        i = st.selectbox("소재", idxs, format_func=lambda i: lab(db, i), key="sel_e")
        f = db[i]
        st.caption(f"상태: {STATUS_KO.get(f.get('status'), f.get('status'))}" + (f" · 사유: {f['reject_reason']}" if f.get("reject_reason") else ""))
        notes = list(f.get("fact_issues") or []) + list(f.get("cross_notes") or [])
        if f.get("fact_risk") or f.get("cross_verdict") or notes:
            with st.expander("검수/교차검증 메모", expanded=bool(notes)):
                st.write(f"위험도 {f.get('fact_risk', '-')} · 교차검증 {f.get('cross_verdict', '-')}")
                for n in notes:
                    st.write("- " + str(n))
        if f.get("verify_note"):
            st.caption("확인 검색어: " + str(f["verify_note"]))
        k = f"{repo}_{i}"
        t1 = st.text_input("제목 1줄", f.get("title_line1", ""), key=f"t1_{k}")
        t2 = st.text_input("제목 2줄", f.get("title_line2", ""), key=f"t2_{k}")
        nar = st.text_area("대본", f.get("narration", ""), height=300, key=f"nr_{k}")
        st.caption(f"{len(nar)}자 · 이미 음성/영상을 만든 소재는 대본을 고친 뒤 '실행' 탭에서 redo 번호에 넣어야 반영됩니다.")
        if st.button("💾 저장 (GitHub에 커밋)", key=f"sv_{k}"):
            def fn(it, t1=t1, t2=t2, nar=nar):
                it["title_line1"], it["title_line2"], it["narration"] = t1, t2, nar
            if apply_changes(repo, [(i, f.get("country"), fn)], f"web: {i}번 대본/제목 수정"):
                st.success("저장했습니다.")
                get_db(repo, force=True)

with tab_state:
    flt2 = st.selectbox("현재 상태", ["전체"] + STATUSES, format_func=lambda s: s if s == "전체" else STATUS_KO[s], key="flt_s")
    q = st.text_input("검색 (국가/제목/주제)")
    rows = [i for i, f in enumerate(db) if (flt2 == "전체" or f.get("status") == flt2)
            and (not q or q.lower() in json.dumps({k: f.get(k) for k in ("country", "label", "topic", "title_line1", "title_line2")}, ensure_ascii=False).lower())]
    picked = st.multiselect(f"소재 ({len(rows)}개 중 선택)", rows, format_func=lambda i: f"[{STATUS_KO.get(db[i].get('status'), db[i].get('status'))}] {lab(db, i)}")
    target = st.selectbox("바꿀 상태", STATUSES, index=4, format_func=lambda s: STATUS_KO[s])
    reason = st.text_input("폐기 사유 (폐기일 때)") if target == "rejected" else ""
    if st.button("상태 변경 (GitHub에 커밋)", disabled=not picked):
        ch = [(i, db[i].get("country"), (lambda it, t=target, r=reason: set_status(it, t, r))) for i in picked]
        if apply_changes(repo, ch, f"web: {len(picked)}개 소재 → {target}"):
            st.success(f"{len(picked)}개를 '{STATUS_KO[target]}'로 바꿨습니다.")
            get_db(repo, force=True)

    st.divider()
    st.subheader("📌 업로드 기록 (영상 주소)")
    import re as _re
    import datetime as _dt
    pend = sorted([i for i, f in enumerate(db) if not f.get("youtube_id") and (f.get("video_path_v6") or f.get("status_v6") == "video_done")], reverse=True)
    if not pend:
        st.caption("영상완료·미업로드 소재가 없습니다.")
    else:
        pk = st.selectbox("소재 (영상완료·미업로드)", pend, format_func=lambda i: lab(db, i), key="urec_pick")
        url = st.text_input("유튜브 영상 주소", key="urec_url")
        pvk = st.radio("공개 상태", ["비공개", "공개", "일부공개"], horizontal=True, key="urec_priv")
        if st.button("업로드 기록 저장 (GitHub에 커밋)", disabled=not url.strip(), key="urec_go"):
            m = _re.search(r"(?:youtu\.be/|youtube\.com/(?:shorts/|embed/|live/)|[?&]v=)([\w-]{11})", url) or _re.fullmatch(r"([\w-]{11})", url.strip())
            if not m:
                st.error("영상 주소에서 ID를 찾지 못했습니다")
            elif any(f.get("youtube_id") == m.group(1) for f in db):
                st.error("이 영상은 이미 다른 소재에 연결돼 있습니다")
            else:
                vid = m.group(1)
                pv = {"비공개": "private", "공개": "public", "일부공개": "unlisted"}[pvk]
                today = _dt.datetime.now(_dt.timezone(_dt.timedelta(hours=9))).strftime("%Y-%m-%d")

                def fn_u(it, vid=vid, pv=pv, today=today):
                    it["youtube_id"], it["youtube_privacy"], it["uploaded_at"] = vid, pv, today
                if apply_changes(repo, [(pk, db[pk].get("country"), fn_u)], f"web: {pk}번 업로드 기록"):
                    st.success(f"{pk}번 소재에 {vid} 기록"); get_db(repo, force=True)

with tab_run:
    wf = secret("WORKFLOWS", {}) or {}
    wf_file = st.text_input("워크플로 파일명", wf.get(chan, "") or ("culture-shorts-pipeline.yml" if "한" in chan or "ko" in chan.lower() else "korea-shorts-pipeline.yml"))
    stage = st.selectbox("stage", ["prepare", "render", "all"])
    r1, r2 = st.columns(2)
    count = r1.number_input("count", 1, 20, 3)
    start = r2.number_input("start_index", 0, 100000, 0)
    redo = st.text_input("redo (영상 다시 만들 번호, 예: 12,15)")
    redo_script = st.text_input("redo_script (대본부터 다시, 예: 12,15)")
    if st.button("▶ 실행"):
        inputs = {"stage": stage, "count": str(int(count)), "start_index": str(int(start))}
        if redo.strip():
            inputs["redo"] = redo.strip()
        if redo_script.strip():
            inputs["redo_script"] = redo_script.strip()
        r = requests.post(f"{API}/repos/{repo}/actions/workflows/{wf_file}/dispatches",
                          json={"ref": BRANCH, "inputs": inputs}, headers=hdr(), timeout=30)
        if r.status_code == 204:
            st.success("실행을 요청했습니다. 완료되면 디스코드로 알림이 옵니다.")
        else:
            st.error(f"실패 {r.status_code}: {r.text[:300]}")
    try:
        rr = requests.get(f"{API}/repos/{repo}/actions/runs", params={"per_page": 5}, headers=hdr(), timeout=30).json()
        for run in rr.get("workflow_runs", []):
            icon = {"success": "✅", "failure": "❌", None: "⏳"}.get(run.get("conclusion"), "⚪")
            st.markdown(f"{icon} [{run['name']} #{run['run_number']}]({run['html_url']}) · {run['status']} · {run['created_at'][:16].replace('T', ' ')}")
    except Exception:
        pass
