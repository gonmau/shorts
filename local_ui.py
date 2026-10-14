"""PC용 간이 UI (Streamlit). 실행: streamlit run local_ui.py
코드 폴더(facts_db.json이 있는 곳)에 넣고 실행. 환경변수 GROQ_API_KEY(필수), PIXABAY_API_KEY 등은 미리 설정."""
import os, re, subprocess, sys, json, time
import streamlit as st

HERE = os.path.dirname(os.path.abspath(__file__))
os.chdir(HERE)
EN = os.path.exists("generate_topics.py")
CH, HD = ("KoreaAtoZ", "@KoreaA2Z") if EN else ("gonmauY", "@gonmauY")
st.set_page_config(page_title="Shorts 로컬", layout="wide")
st.title("Shorts 로컬 실행 - " + CH)

with st.sidebar:
    st.header("상황별 사용법")
    st.markdown("""
**새 영상 (검수 포함)**
1. count, start_index 입력
2. ① prepare 클릭
3. ② review.txt 수정 후 *저장*
4. ③ render 클릭

**소재 건너뛰기**
review.txt의 해당 소재 `제외:` 뒤에 사유 입력 → 저장 → render

**대본 되살리기 (폐기된 소재)**
redo 칸에 `101!` + *redo_script 체크* → prepare → review.txt 수정·저장 → **redo 칸 비우고** render

**대본부터 다시**
redo 칸 `101` + *redo_script 체크* → prepare

**영상만 다시 (음성/이미지 문제)**
redo 칸 `98,99` + *체크 해제* → render

**직접 넣은 대본(JSON)으로 제작**
facts_db.json에 narration 입력 → render만

**주의**
- redo 칸은 작업이 끝나면 비우세요 (매번 적용됨)
- 검은 cmd 창을 닫으면 UI가 꺼집니다
- 긴 작업 중엔 로그가 아래에 흐릅니다
""")

TIMES = []

def run(*args):
    t0 = time.time()
    st.write("▶ `python " + " ".join(args) + "`")
    box = st.empty(); buf = []
    env = dict(os.environ, PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8")
    p = subprocess.Popen([sys.executable, *args], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         text=True, encoding="utf-8", errors="replace", env=env)
    for line in p.stdout:
        buf.append(line.rstrip()); box.code("\n".join(buf[-25:]))
    ok = p.wait() == 0
    sec = time.time() - t0
    TIMES.append((" ".join(args)[:60], round(sec, 1), "완료" if ok else "실패"))
    (st.success if ok else st.error)(f"{'완료' if ok else '실패 (코드 ' + str(p.returncode) + ')'} - {sec:.0f}초")
    return ok

def chain(steps):
    TIMES.clear(); t_all = time.time()
    for s in steps:
        if not run(*s):
            break
    st.subheader("단계별 소요 시간")
    st.table([{"단계": a_, "초": b_, "결과": c_} for a_, b_, c_ in TIMES] +
             [{"단계": "합계", "초": round(time.time() - t_all, 1), "결과": f"{int((time.time() - t_all) // 60)}분 {int((time.time() - t_all) % 60)}초"}])

c1, c2, c3 = st.columns(3)
count = c1.number_input("count", 1, 20, 1, help="이번에 처리할 소재 개수. 처음엔 1~2 권장 (Groq 일일 한도)")
start = c2.number_input("start_index", 0, 9999, 0 if EN else 106, help="이 번호 이상인 소재부터 처리. 그보다 작은 번호(옛 소재)는 건너뜀")
redo = c3.text_input("redo / redo_script (예: 98,99 / 101!)", help="평소엔 비워 두세요. 영상만 다시: 98,99 / 대본부터 다시: 101 (아래 체크) / 폐기 소재 되살리기: 101! (아래 체크). 작업 후엔 꼭 비우기")
redo_script = st.checkbox("위 입력을 redo_script(대본부터)로 사용", False, help="체크: 대본부터 다시 / 번호 뒤 ! 는 폐기 해제. 해제: 영상만 다시")
a, b = f"--limit {count} --start {start}".split(), None
S = lambda *x: list(x)

pre = [S("promote_ready.py", "--start", str(start)), S("apply_review.py")]
if redo:
    pre.append(S("redo_videos.py", *(["--script"] if redo_script else []), "--indexes", redo))
prepare = pre + [S("generate_script.py", *a), S("export_review.py", *a)]
render = pre + [S("generate_script.py", "--extras-only", *a), S("generate_tts.py", *a),
                S("fetch_images.py", *a), S("build_video.py", *a, "--channel", CH, "--handle", HD),
                S("make_thumbnail.py", "--channel", CH, "--handle", HD)]

b1, b2, b3, b4 = st.columns(4)
if b1.button("① prepare (대본+review.txt)", help="대본/제목/핵심문구/이미지 검색어까지 만들고 review.txt 생성. 영상은 안 만듦"): chain(prepare)
if b2.button("③ render (영상 제작)", help="review.txt 수정을 반영해 음성→이미지→영상→썸네일 제작. 먼저 review.txt를 저장하세요"): chain(render)
if b3.button("현황", help="소재 상태별 개수와 render 가능 개수 보기"): run("status_report.py")
if b4.button("유튜브 업로드", help="만든 영상을 비공개로 업로드. YT_REFRESH_TOKEN 환경변수 필요") and os.environ.get("YT_REFRESH_TOKEN"): run("upload_to_youtube.py", "--limit", str(count))


def read_review():
    return open("review.txt", encoding="utf-8").read() if os.path.exists("review.txt") else ""

def write_review(t):
    open("review.txt", "w", encoding="utf-8").write(t)

HEAD = re.compile(r"^===\s*\[(\d+)\]")
def block_range(lines, idx):
    st_ = next((i for i, l in enumerate(lines) if (m := HEAD.match(l.strip())) and int(m.group(1)) == idx), None)
    if st_ is None:
        return None
    en = next((i for i in range(st_ + 1, len(lines)) if HEAD.match(lines[i].strip())), len(lines))
    return st_, en

def review_indexes():
    return [int(m.group(1)) for l in read_review().splitlines() if (m := HEAD.match(l.strip()))]

def replace_lines(idx, pattern, new_lines):
    """review.txt의 idx 소재 블록에서 pattern에 맞는 줄을 모두 지우고 new_lines를 첫 줄 위치에 넣는다."""
    lines = read_review().splitlines()
    r = block_range(lines, idx)
    if not r:
        return False
    a_, b_ = r
    pos = next((i for i in range(a_ + 1, b_) if re.match(pattern, lines[i].strip())), b_)
    keep_before = [l for l in lines[a_ + 1:pos]]
    after = [l for l in lines[pos:b_] if not re.match(pattern, l.strip())]
    write_review("\n".join(lines[:a_ + 1] + keep_before + new_lines + after + lines[b_:]) + "\n")
    return True

def apply_quiet():
    subprocess.run([sys.executable, "apply_review.py"], capture_output=True, text=True, encoding="utf-8", errors="replace",
                   env=dict(os.environ, PYTHONIOENCODING="utf-8"))

st.subheader("② review.txt 검수 (여기서 수정 후 저장)")
st.caption("대본[N]·핵심[N]·이미지[N]·제목 수정 가능 / 소재를 건너뛰려면 `제외:` 뒤에 사유 / ( 로 시작하는 줄은 참고용 / === [번호] === 줄은 수정 금지")
txt = read_review()
new = st.text_area("review.txt", txt, height=400, label_visibility="collapsed", help="수정 후 아래 저장 버튼을 꼭 누르세요")
if st.button("review.txt 저장"):
    write_review(new); st.success("저장됨 (render 때 자동 반영)")

tab_s, tab_i, tab_m, tab_v = st.tabs(["📝 대본 전체 보기/수정", "🖼 이미지 검수/교체", "📋 제목/설명 (디스코드·유튜브)", "🎬 만든 영상"])

with tab_s:
    ids = review_indexes()
    if not ids:
        st.info("review.txt에 소재가 없습니다. 먼저 ① prepare를 실행하세요.")
    else:
        sel = st.selectbox("소재 번호", ids, key="script_sel", help="review.txt에 있는 소재만 수정할 수 있습니다")
        lines = read_review().splitlines()
        a_, b_ = block_range(lines, sel)
        blk = lines[a_:b_]
        narr = [re.sub(r"^대본\s*\[\s*\d+\s*\]\s*[:：]\s*", "", l.strip()) for l in blk if re.match(r"^대본\s*\[", l.strip())]
        hls = [l.strip() for l in blk if re.match(r"^핵심\s*\[", l.strip())]
        title = [l.strip() for l in blk if re.match(r"^제목\s*[12]", l.strip())]
        st.caption(" / ".join(title))
        st.markdown("**대본 (한 줄 = 한 문장, 줄을 지우면 문장이 빠지고 번호는 다시 매겨집니다)**")
        n_txt = st.text_area("대본", "\n".join(narr), height=260, key=f"n_{sel}", label_visibility="collapsed")
        st.markdown("**핵심 문구 (`핵심[N]: *강조* 문구`, N=문장 번호. 대본 줄 수를 바꿨다면 번호도 맞춰 주세요)**")
        h_txt = st.text_area("핵심", "\n".join(hls), height=140, key=f"h_{sel}", label_visibility="collapsed")
        st.caption("대본을 고치면 음성이 다시 만들어지고, 이미지 검색어는 새 대본 기준으로 다시 만들어집니다(이미지 탭에서 확인).")
        if st.button("대본/핵심 저장", key=f"save_s_{sel}"):
            ns = [x.strip() for x in n_txt.splitlines() if x.strip()]
            hs = [x.strip() for x in h_txt.splitlines() if x.strip()]
            replace_lines(sel, r"^대본\s*\[", [f"대본[{i}]: {t}" for i, t in enumerate(ns, 1)])
            replace_lines(sel, r"^핵심\s*\[", hs)
            apply_quiet()
            st.success(f"저장 및 DB 반영 완료 (대본 {len(ns)}문장, 핵심 {len(hs)}개)")
            st.rerun()

with tab_i:
    from common import load_db, save_db, visual_dir
    db_ = load_db()
    cand = [i for i, f in enumerate(db_) if f.get("status") in ("scripted", "tts_done", "video_done") and i >= start]
    if not cand:
        st.info("대상 소재가 없습니다.")
    else:
        idx = st.selectbox("소재 번호", cand, key="img_sel", format_func=lambda i: f"{i} {db_[i].get('country', '')} ({db_[i].get('status')})")
        item = db_[idx]
        folder = visual_dir(HERE, idx, item)
        qs = list(item.get("image_queries") or [])
        credits = {c.get("scene"): c for c in (item.get("image_credits") or [])}
        pix = os.environ.get("PIXABAY_API_KEY", "").strip()
        st.caption("검색어를 고치고 [이 장면 다시 받기]를 누르면 그 장면만 새로 받습니다. 직접 가진 사진은 [사진 올리기]로 바꿀 수 있습니다. "
                   "이미지 검색어가 비어 있으면 render 때(또는 아래 버튼으로) 대본 기준으로 만들어집니다.")
        fetch_code = ("import os,requests;import fetch_images as F;from common import load_db,save_db;"
                      f"db=load_db();F.fetch_item(requests.Session(),os.environ['PIXABAY_API_KEY'],{idx},db[{idx}],False);save_db(db)")
        cA, cB = st.columns(2)
        if cA.button("빠진 이미지 받기 / 검색어 생성", key=f"fill_{idx}", help="검색어가 없으면 대본 기준으로 만들고, 없는 장면의 이미지를 받습니다"):
            if not qs:
                run("generate_script.py", "--extras-only", "--limit", "1", "--start", str(idx))
            if pix:
                run("-c", fetch_code)
            else:
                st.warning("PIXABAY_API_KEY가 없어 이미지를 받을 수 없습니다.")
            st.rerun()
        if not qs:
            st.warning("이미지 검색어가 아직 없습니다. 위 버튼을 누르세요.")
        else:
            cols = st.columns(3)
            for n in range(1, 7):
                with cols[(n - 1) % 3]:
                    f_ = folder / f"scene_{n:02d}.png"
                    if f_.exists():
                        st.image(str(f_), caption=f"장면 {n}", use_container_width=True)
                    else:
                        st.warning(f"장면 {n}: 이미지 없음 (색 카드로 대체)")
                    c_ = credits.get(n)
                    if c_:
                        st.caption(f"출처: {c_.get('source')} · {c_.get('user', '')} {c_.get('license', '')}")
                    q_new = st.text_input("검색어", qs[n - 1] if n - 1 < len(qs) else "", key=f"q_{idx}_{n}")
                    if st.button("이 장면 다시 받기", key=f"re_{idx}_{n}"):
                        qq = (qs + [""] * 6)[:6]; qq[n - 1] = q_new.strip()
                        d2 = load_db(); d2[idx]["image_queries"] = qq; save_db(d2)
                        replace_lines(idx, r"^이미지\s*\[", [f"이미지[{i}]: {t}" for i, t in enumerate(qq, 1)])  # review.txt에도 반영
                        if pix:
                            run("-c", fetch_code)
                        else:
                            st.warning("PIXABAY_API_KEY가 없어 받을 수 없습니다.")
                        st.rerun()
                    up = st.file_uploader("사진 올리기", type=["png", "jpg", "jpeg", "webp"], key=f"up_{idx}_{n}")
                    if up is not None and st.button("이 사진으로 교체", key=f"rep_{idx}_{n}"):
                        from PIL import Image
                        folder.mkdir(parents=True, exist_ok=True)
                        Image.open(up).convert("RGB").save(f_, "PNG")
                        d2 = load_db(); it2 = d2[idx]
                        it2["image_credits"] = [c for c in (it2.get("image_credits") or []) if c.get("scene") != n]  # 직접 올린 사진은 크레딧 없음
                        save_db(d2)
                        st.success(f"장면 {n} 교체 완료 (저작권은 직접 확인하세요)")
                        st.rerun()

with tab_m:
    from common import load_db as _ld, youtube_meta
    dbm = _ld()
    candm = [i for i, f in enumerate(dbm) if f.get("status") in ("scripted", "tts_done", "video_done") and i >= start]
    if not candm:
        st.info("대상 소재가 없습니다.")
    else:
        mi = st.selectbox("소재 번호", candm, key="meta_sel", format_func=lambda i: f"{i} {dbm[i].get('country', '')} ({dbm[i].get('status')})")
        if st.button("review.txt 수정 반영해서 새로고침", help="review.txt에서 고친 제목/후크/본문/반전을 DB에 반영한 뒤 아래를 갱신"):
            apply_quiet(); st.rerun()
        mt, md = youtube_meta(dbm[mi])
        st.markdown("**제목** (디스코드 첫 메시지 / 유튜브 제목)")
        st.code(mt, language=None)
        st.markdown("**설명** (디스코드 두 번째 메시지 / 유튜브 설명)")
        st.code(md, language=None)
        st.caption("제목은 review.txt의 `제목1/제목2`, 설명은 `후크/본문/반전`을 고치면 바뀝니다. 사진 출처 줄은 이미지를 받은 뒤에 생깁니다. 코드 상자 오른쪽 위 아이콘으로 복사할 수 있습니다.")

with tab_v:
    if os.path.isdir("videos"):
        for f in sorted(os.listdir("videos"))[-3:]:
            if f.endswith(".mp4"):
                st.caption(f); st.video(os.path.join("videos", f))
    else:
        st.info("아직 만든 영상이 없습니다.")
