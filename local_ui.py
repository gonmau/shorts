"""PC용 간이 UI (Streamlit). 실행: streamlit run local_ui.py
코드 폴더(facts_db.json이 있는 곳)에 넣고 실행. 환경변수 GROQ_API_KEY(필수), PIXABAY_API_KEY 등은 미리 설정."""
import os, re, subprocess, sys, json, time
import streamlit as st

HERE = os.path.dirname(os.path.abspath(__file__))
os.chdir(HERE)
_has_en, _has_ko = os.path.exists("generate_topics.py"), os.path.exists("generate_culture_facts.py")
EN = _has_en and not _has_ko
if _has_en and _has_ko:  # 두 채널 파일이 섞인 폴더: 파일 안의 언어로 판별 (channel.txt로 강제 지정 가능)
    try:
        EN = open("channel.txt", encoding="utf-8").read().strip().lower() == "en"
    except Exception:
        EN = "ko-KR-SunHiNeural" not in open("generate_tts.py", encoding="utf-8").read()
CH, HD = ("KoreaAtoZ", "@KoreaA2Z") if EN else ("gonmauY", "@gonmauY")
st.set_page_config(page_title="Shorts 로컬", layout="wide")
try:  # 브라우저 자동 번역(크롬 번역 등)이 화면을 건드려 생기는 'removeChild' 오류 방지
    import streamlit.components.v1 as _cmp
    _cmp.html("<script>try{var d=window.parent.document.documentElement;d.setAttribute('lang','ko');d.setAttribute('translate','no');"
              "var m=window.parent.document.createElement('meta');m.name='google';m.content='notranslate';window.parent.document.head.appendChild(m);}catch(e){}</script>", height=0)
except Exception:
    pass
st.title("Shorts 로컬 실행 - " + CH)
st.caption(f"폴더: {HERE}  |  채널: {'영어 (KoreaAtoZ)' if EN else '한국어 (gonmauY)'}")

with st.sidebar:
    st.header("사용법")
    st.markdown("""
**기본 흐름 (아래 '작업 순서')**
1 소재 → 2 대본 → 3 이미지 → 4 음성 → 5 렌더링 → 6 업로드
각 단계 결과를 확인하고 다음으로. 확인 없이 한 번에 하려면 *⚡ 자동 진행*.

**공통 입력**
- count: 한 번에 처리할 개수 / start_index: 이 번호 이상만 처리

**고치기**
- 대본: 탭 *대본 전체 보기/수정* 또는 *review.txt* (고치면 음성·이미지 검색어는 지워짐 → 3·4단계 다시)
- 이미지: 탭 *이미지 검수/교체*
- 소재 건너뛰기: review.txt의 `제외:` 뒤에 사유
- 문구 넣기 / 롱폼: 각 탭

**이미 만든 영상 다시 만들기 (redo)**
- 영상만: redo `98,99` (체크 해제) → 5단계
- 대본부터: redo `101` + *redo_script 체크* → 2단계
- 폐기 소재 되살리기: `101!` + 체크

**주의**
- redo 칸은 작업이 끝나면 비우세요 (매번 적용됨)
- 검은 cmd 창을 닫으면 UI가 꺼집니다
""")

TIMES = []

# ---- 목소리/속도 설정 (tts_settings.json에 저장, 모든 단계에 환경변수로 전달) ----
LANG = "en" if EN else "ko"
ST_VOICES = ["F1", "F2", "F3", "F4", "F5", "M1", "M2", "M3", "M4", "M5"]
EDGE_VOICES = (["en-US-AndrewNeural", "en-US-AriaNeural", "en-US-GuyNeural", "en-US-JennyNeural", "en-GB-RyanNeural"] if EN
               else ["ko-KR-SunHiNeural", "ko-KR-InJoonNeural", "ko-KR-HyunsuMultilingualNeural", "ko-KR-JiMinNeural", "ko-KR-SeoHyeonNeural"])
TTS_FILE = "tts_settings.json"
try:
    TTS_CFG = json.load(open(TTS_FILE, encoding="utf-8"))
except Exception:
    TTS_CFG = {}
TTS_CFG.setdefault("voice", "M1" if EN else "F1")
TTS_CFG.setdefault("rate", 8 if EN else -3)
TTS_CFG.setdefault("edge", EDGE_VOICES[0])
TTS_CFG.setdefault("caption", "script")
TTS_CFG.setdefault("engine", "auto")
TTS_CFG.setdefault("target_sec", 0)
TTS_CFG.setdefault("scenes", 10)
TTS_CFG.setdefault("cross", False)
ENGINE_LABELS = {"auto": "Supertonic 우선, 실패하면 Edge 등 (기본)", "edge": "Edge 우선, 실패하면 Supertonic 등", "supertonic": "Supertonic만 (실패하면 중단)", "edge_only": "Edge만 (실패하면 중단)"}
ENGINE_ORDER = {"auto": "supertonic,edge,google,gtts", "edge": "edge,supertonic,google,gtts", "supertonic": "supertonic", "edge_only": "edge"}
CAP_LABELS = {"script": "대본 자막 (기본)", "highlight": "핵심 문구 표시 (예전 방식)", "srt": "SRT 파일만 (영상엔 자막 없음)", "both": "대본 자막 + SRT"}

def tts_env():
    return {f"SUPERTONIC_VOICE_{LANG.upper()}": TTS_CFG["voice"], "TTS_RATE": f"{int(TTS_CFG['rate']):+d}%",
            "TTS_EDGE_VOICE": TTS_CFG["edge"], "CAPTION_MODE": TTS_CFG["caption"],
            "TTS_ORDER": ENGINE_ORDER.get(TTS_CFG["engine"], ENGINE_ORDER["auto"]),
            "SCENE_COUNT": str(int(TTS_CFG.get("scenes") or 10)),
            "CROSS_CHECK": "1" if TTS_CFG.get("cross") else "0",
            **({"SCRIPT_TARGET_SEC": str(int(TTS_CFG["target_sec"]))} if int(TTS_CFG.get("target_sec") or 0) > 0 else {})}

def run(*args):
    t0 = time.time()
    st.write("▶ `python " + " ".join(args) + "`")
    box = st.empty(); buf = []
    env = dict(os.environ, PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8", **tts_env())
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

def sync_desc(idxs):
    """이미지를 다시 받은 소재 중 이미 업로드된 것(youtube_id 있음)은 유튜브 설명(사진 출처)도 새로 고친다. 성공/불필요면 True"""
    if not st.session_state.get("desc_sync", True):
        return True
    from common import load_db as _l
    d_ = _l()
    up = [i for i in idxs if 0 <= i < len(d_) and d_[i].get("youtube_id")]
    if not up:
        return True
    if not (os.environ.get("YT_REFRESH_TOKEN") and os.environ.get("YT_CLIENT_ID")):
        st.warning(f"{up}번은 이미 업로드된 영상입니다. YT_* 환경변수가 없어 설명을 자동 수정하지 못했습니다. 📋 제목/설명 탭의 설명을 Studio에 붙여넣으세요.")
        return False
    return run("update_description.py", "--indexes", ",".join(map(str, up)))

c1, c2, c3 = st.columns(3)
count = c1.number_input("count", 1, 20, 1, help="이번에 처리할 소재 개수. 처음엔 1~2 권장 (Groq 일일 한도)")
start = c2.number_input("start_index", 0, 9999, 0 if EN else 106, help="이 번호 이상인 소재부터 처리. 그보다 작은 번호(옛 소재)는 건너뜀")
redo = c3.text_input("redo / redo_script (예: 98,99 / 101!)", help="평소엔 비워 두세요. 영상만 다시: 98,99 / 대본부터 다시: 101 (아래 체크) / 폐기 소재 되살리기: 101! (아래 체크). 작업 후엔 꼭 비우기")
redo_script = st.checkbox("위 입력을 redo_script(대본부터)로 사용", False, help="체크: 대본부터 다시 / 번호 뒤 ! 는 폐기 해제. 해제: 영상만 다시")
a = f"--limit {count} --start {start}".split()
S = lambda *x: list(x)

def _status_counts():
    from common import load_db as _l
    d_ = _l(); c_ = {}
    for i, f in enumerate(d_):
        if i >= int(start):
            c_[f.get("status")] = c_.get(f.get("status"), 0) + 1
    return d_, c_

with st.sidebar:
    st.divider()
    st.subheader("현황 (항상 표시)")
    _d, _c = _status_counts()
    st.caption(f"start_index {int(start)} 이상 {sum(_c.values())}개 (전체 {len(_d)}개)")
    for _k, _lab in (("unverified", "1 승인 대기"), ("verified", "2 승인됨 (대본 만들 차례)"), ("scripted", "3 대본 완료"),
                     ("tts_done", "4 음성 완료"), ("video_done", "5 영상 완료"), ("rejected", "폐기")):
        st.write(f"{_lab}: **{_c.get(_k, 0)}**")
    _up = [f_ for i_, f_ in enumerate(_d) if i_ >= int(start) and f_.get("youtube_id")]
    _vdone = [f_ for i_, f_ in enumerate(_d) if i_ >= int(start) and not f_.get("youtube_id") and (f_.get("video_path_v6") or f_.get("status_v6") == "video_done")]
    st.write(f"업로드됨: **{len(_up)}** · 영상완료/미업로드: **{len(_vdone)}**")
    st.caption("렌더링 대기(대본 있고 영상 없음)는 5단계 목록 기준")


pre = [S("promote_ready.py", "--start", str(start)), S("apply_review.py")]
if redo:
    pre.append(S("redo_videos.py", *(["--script"] if redo_script else []), "--indexes", redo))

with st.expander("🎙 음성 · 자막 설정 (음성 만들기 전에 정하세요)"):
    t1, t2, t3 = st.columns(3)
    TTS_CFG["voice"] = t1.selectbox("Supertonic 목소리 (F=여성, M=남성)", ST_VOICES, ST_VOICES.index(TTS_CFG["voice"]) if TTS_CFG["voice"] in ST_VOICES else 0,
                                    help="기본 음성 엔진. 아래 '미리듣기'로 들어보고 고르세요")
    TTS_CFG["rate"] = t2.slider("속도 (%)", -20, 30, int(TTS_CFG["rate"]), 1,
                                help="0=기본. 느리게는 -, 빠르게는 +. 빠를수록 영상이 짧아집니다")
    TTS_CFG["edge"] = t3.selectbox("Edge 음성", EDGE_VOICES, EDGE_VOICES.index(TTS_CFG["edge"]) if TTS_CFG["edge"] in EDGE_VOICES else 0)
    _ek = list(ENGINE_LABELS)
    TTS_CFG["engine"] = st.radio("음성 엔진", _ek, _ek.index(TTS_CFG["engine"]) if TTS_CFG["engine"] in _ek else 0, horizontal=True,
                                 format_func=lambda k: ENGINE_LABELS[k],
                                 help="Edge는 마이크로소프트 서버를 쓰므로 인터넷이 필요하고, 막히면(403 등) 실패합니다. 안 되면 pip install -U edge-tts 후 다시 시도하세요")
    _ck = list(CAP_LABELS)
    TTS_CFG["caption"] = st.radio("자막 방식", _ck, _ck.index(TTS_CFG["caption"]) if TTS_CFG["caption"] in _ck else 0, horizontal=True,
                                  format_func=lambda k: CAP_LABELS[k],
                                  help="대본 자막: 음성 속도에 맞춰 대본을 보여줌 / 핵심 문구: 대본 중 강조 문구만 (review.txt의 핵심 줄 사용) / SRT만: 영상엔 자막 없이 .srt 파일만 (유튜브 스튜디오에서 올리면 시청자가 켜고 끌 수 있음). .srt 파일은 어떤 방식이든 같이 만들어집니다. 롱폼은 핵심 문구 방식이 없어 대본 자막으로 나옵니다")
    json.dump(TTS_CFG, open(TTS_FILE, "w", encoding="utf-8"), ensure_ascii=False)
    sample = st.text_input("미리듣기 문장", "프랑스에서는 빵을 거꾸로 놓으면 불길하다고 여겼습니다." if not EN else "In Korea, you never stick chopsticks upright in a bowl of rice.")
    pe1, pe2 = st.columns([1, 3])
    pv_engine = pe1.radio("미리듣기 엔진", ["Supertonic", "Edge"], horizontal=True, key="pv_engine",
                          help="선택한 엔진과 위에서 고른 목소리/속도로 들어봅니다. Supertonic은 '목소리', Edge는 'Edge 음성'을 씁니다")
    if pe2.button("▶ 미리듣기", help="위 문장을 한 번 만들어 들어봅니다 (Supertonic은 처음엔 모델 다운로드로 오래 걸림)"):
        outp = "_preview.wav" if pv_engine == "Supertonic" else "_preview.mp3"
        cmd = [sys.executable, "tts_preview.py", "--engine", pv_engine.lower(), "--text", sample, "--out", outp,
               "--lang", LANG, f"--rate={int(TTS_CFG['rate']):+d}%", "--voice", TTS_CFG["edge"]]
        with st.spinner(f"{pv_engine}로 만드는 중..."):
            r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                               env=dict(os.environ, PYTHONIOENCODING="utf-8", **tts_env()))
        if r.returncode == 0 and os.path.exists(outp):
            st.audio(outp)
            st.caption(f"{pv_engine} / " + (TTS_CFG["voice"] if pv_engine == "Supertonic" else TTS_CFG["edge"]) + f" / 속도 {int(TTS_CFG['rate']):+d}%")
        else:
            st.error(f"{pv_engine} 미리듣기 실패: " + ((r.stderr or r.stdout)[-500:] or "원인 불명"))
    st.caption("영상/자막/장면 전환은 만들어진 음성의 실제 길이·문장 타이밍을 따라 자동으로 맞춰집니다. "
               "대본은 글자 수 기준이라 속도를 늦추면 영상이 길어지고(58초 초과 시 경고), 빠르게 하면 짧아집니다. "
               "이미 만든 영상에 적용하려면 redo 칸에 번호를 넣고(체크 해제) 5단계(음성 다시 만들기 체크)를 실행하세요.")

# ================= 작업 순서: 1 소재 -> 2 대본 -> 3 이미지 -> 4 렌더링 -> 5 업로드 =================
from common import load_db as _ld, save_db as _sd, pending_render as _pr, visual_dir as _vd, upload_state
GEN = "generate_culture_facts.py" if not EN else "generate_topics.py"
def script_steps(auto):
    return pre + ([S("approve.py", "--limit", str(count), "--start", str(start))] if auto else []) + [S("generate_script.py", *a), S("export_review.py", *a)]

IMAGE_STEP = pre + [S("generate_script.py", "--extras-only", *a), S("fetch_images.py", *a, "--any")]

def _ready_all():
    """렌더링 대기 소재 번호들 (현황의 'render 바로 가능'과 같은 기준: 대본이 있는 승인/미승인 소재도 포함)"""
    out = []
    for i, f in enumerate(_ld()):
        if i < int(start) or f.get("video_path_v6") or f.get("status_v6") == "video_done":
            continue
        if f.get("status") in ("scripted", "tts_done") or (
                f.get("status") in ("unverified", "verified") and len(str(f.get("narration") or "").strip()) >= 60):
            out.append(i)
    return out

def _targets():
    return _ready_all()[:int(count)]

def _img_state(i, f):
    n = len(list(_vd(HERE, i, f).glob("scene_*.png"))) if _vd(HERE, i, f).exists() else 0
    return n, bool(f.get("image_queries_done"))

st.markdown("### 작업 순서  (1 소재 → 2 대본 → 3 이미지 → 4 음성 → 5 렌더링 → 6 업로드)")
st.caption("단계마다 결과를 확인하고 다음으로 넘어가세요. 위의 count/start_index는 모든 단계에 공통으로 적용됩니다.")
if st.button("현황 보기", help="소재 상태별 개수와 render 가능 개수"):
    run("status_report.py")

with st.expander("1단계 · 소재 만들기 / 확인 / 승인", expanded=False):
    n_topics = st.number_input("새 소재 개수", 1, 30, 12, help="위키백과 기반으로 새 소재(unverified)를 만듭니다. 한 번에 12개 이하 권장 (Groq 한도)")
    if st.button("소재 만들기", key="st1_make"):
        run(GEN, "--count", str(int(n_topics)))
    _db1 = _ld()
    cand1 = [i for i, f in enumerate(_db1) if i >= int(start) and f.get("status") == "unverified"
             and len(str(f.get("narration") or "").strip()) < 60]
    st.caption(f"승인 대기(unverified) 소재 {len(cand1)}개 (start_index {int(start)} 이상). 내용을 보고 승인하거나 제외하세요.")
    if cand1:
        st.dataframe([{"번호": i, "나라": _db1[i].get("country", ""), "주제": _db1[i].get("topic", ""), "분야": _db1[i].get("theme", ""),
                       "훅": str(_db1[i].get("hook", ""))[:60], "출처": _db1[i].get("verify_note", "")} for i in cand1[:60]],
                     use_container_width=True, hide_index=True)
        picked = st.multiselect("선택", cand1[:60], key="st1_pick", format_func=lambda i: f"{i} {_db1[i].get('country', '')} - {_db1[i].get('topic', '')}")
        x1, x2, x3 = st.columns(3)
        if x1.button("선택 승인", key="st1_ok", help="선택한 소재를 대본 생성 대상(verified)으로 바꿉니다"):
            for i in picked:
                _db1[i]["status"] = "verified"
            _sd(_db1); st.success(f"{len(picked)}개 승인"); st.rerun()
        if x2.button("선택 제외", key="st1_no", help="선택한 소재를 폐기(rejected)합니다. 번호! 로 되살릴 수 있습니다"):
            for i in picked:
                _db1[i]["status"] = "rejected"; _db1[i]["reject_reason"] = "UI에서 제외"
            _sd(_db1); st.success(f"{len(picked)}개 제외"); st.rerun()
        if x3.button("앞에서 count개 자동 승인", key="st1_auto"):
            run("approve.py", "--limit", str(int(count)), "--start", str(int(start)))

with st.expander("2단계 · 대본 만들기 → 확인/수정", expanded=False):
    TTS_CFG["target_sec"] = st.slider("목표 대본 길이 (초, 0 = 기본)", 0, 58, int(TTS_CFG.get("target_sec") or 0), 1, key="target_sec",
                                      help="새로 만드는 대본의 분량을 음성 길이 기준으로 맞춥니다. 0이면 기본 분량(한국어 350~500자 / 영어 90~115단어). 음성 속도 설정도 반영됩니다. 이미 만든 대본은 안 바뀌니 '대본부터 다시'로 다시 만드세요")
    if int(TTS_CFG["target_sec"]) > 0:
        _t = int(TTS_CFG["target_sec"]); _m = 1 + int(TTS_CFG["rate"]) / 100
        st.caption(f"목표 {_t}초 → " + (f"약 {int(_t * 7.04 * _m / 10) * 10}~{int(_t * 8.96 * _m / 10 + 1) * 10}자 (한국어)" if not EN
                                       else f"약 {round(_t * 2.2 * _m * 0.88)}~{round(_t * 2.2 * _m * 1.12)}단어 (영어)") + " · 실제 음성 길이는 4단계 후 확인")
    TTS_CFG["scenes"] = st.select_slider("장면(이미지) 수", options=list(range(6, 21, 2)), value=int(TTS_CFG.get("scenes") or 10), key="scene_n",
                                         help="새로 만드는 소재의 이미지 장수입니다. 길이 50초면 10장 ≈ 5초마다 전환. 많을수록 이미지 받기·검색어 생성이 늘어납니다. 이미 만든 소재는 원래 장수(6장 등)를 유지하고, 대본부터 다시 만들면 새 장수가 적용됩니다")
    TTS_CFG["cross"] = st.checkbox("🔍 대본 교차검증 (위키백과 근거 + 다른 모델이 문장별 검증)", bool(TTS_CFG.get("cross")), key="cross_chk",
                                   help="대본/제목/이미지 검색어를 만들 때 자동으로 검증합니다. 모순이 있거나 근거 없는 문장이 절반 이상이면 소재를 폐기(rejected)합니다. Groq 호출이 소재당 1~2회 늘어납니다. 오류를 줄일 뿐 100% 보장은 아니니 review.txt의 (교차검증 메모)는 직접 확인하세요. GitHub Actions에는 적용되지 않습니다(로컬 실행 전용)")
    json.dump(TTS_CFG, open(TTS_FILE, "w", encoding="utf-8"), ensure_ascii=False)
    auto_ok = st.checkbox("승인 안 된 소재는 count개까지 자동 승인하고 진행", True, key="auto_ok2",
                          help="끄면 1단계에서 승인한 소재(verified)만 대본을 만듭니다")
    if st.button("대본 만들기 (제목/이미지 검색어 포함, review.txt 생성)", key="st2_go"):
        chain(script_steps(auto_ok))
    st.caption("끝나면 아래 review.txt 또는 '📝 대본 전체 보기/수정' 탭에서 대본·제목을 확인하고 저장하세요. 대본이 마음에 안 들면 redo 칸에 번호! 를 넣어 다시 만들 수 있습니다.")

with st.expander("3단계 · 이미지 받기 → 확인/교체", expanded=False):
    tg = _targets()
    st.caption("대본이 끝난 소재 중 앞에서 count개: " + (", ".join(map(str, tg)) or "없음") + "   (이미지 검색어도 이때 대본 기준으로 만들어집니다)")
    if st.button("이미지 받기 (검색어 생성 + 장면 이미지)", key="st3_go", help="음성보다 먼저 이미지를 받아 확인할 수 있습니다. 이미 받은 장면은 건드리지 않습니다"):
        chain(IMAGE_STEP)
    st.caption("끝나면 '🖼 이미지 검수/교체' 탭에서 장면별로 확인하고, 마음에 안 들면 검색어를 바꿔 다시 받거나 내 사진으로 교체하세요.")

def _audio_ok(f):
    ap_ = f.get("audio_path_v2")
    return bool(f.get("status_tts_v2") == "done" and ap_ and os.path.exists(ap_))

with st.expander("4단계 · 음성 만들기 → 들어보기", expanded=False):
    dv = _ld()
    allv = _ready_all()
    st.caption("대본이 끝난 소재의 음성만 따로 만듭니다 (영상은 안 만듦). 목소리/속도/엔진은 위 '🎙 음성 · 자막 설정' 패널에서 정합니다. 대본을 고치면 음성은 지워지니 대본 확정 후에 만드세요.")
    pickv = st.multiselect("음성 만들 소재", allv, default=allv[:int(count)], key=f"vo_pick_{int(start)}_{int(count)}_{len(allv)}",
                           format_func=lambda i: f"{i} {dv[i].get('country', '')} - {dv[i].get('topic', '')}" + ("  [음성 있음]" if _audio_ok(dv[i]) else ""))
    skip_done = st.checkbox("이미 만든 음성은 건너뛰기", True, key="vo_skip", help="끄면 선택한 소재의 음성을 현재 목소리/속도로 다시 만듭니다")
    if st.button("음성 만들기", key="vo_go", disabled=not pickv):
        steps = list(pre)
        for i in pickv:
            if skip_done and _audio_ok(dv[i]):
                continue
            steps.append(S("generate_tts.py", "--index", str(i)))
        chain(steps)
    dv2 = _ld()
    have = [i for i in pickv if _audio_ok(dv2[i])]
    if have:
        st.markdown("**만들어진 음성**")
        for i in have:
            f = dv2[i]
            try:
                tm = json.load(open(f.get("timing_path_v2"), encoding="utf-8")) if f.get("timing_path_v2") else {}
                dur = float(tm["sentences"][-1]["end"]) if tm.get("sentences") else 0.0
                vname = tm.get("voice", "")
            except Exception:
                dur, vname = 0.0, ""
            st.write(f"{i} {f.get('country', '')} - {dur:.1f}초 · {vname}" + ("  ⚠ 58초 초과 (쇼츠 1분 제한)" if dur > 58 else ""))
            st.audio(f["audio_path_v2"])

with st.expander("5단계 · 렌더링 (영상 + 썸네일, 음성이 없으면 같이 생성)", expanded=False):
    d4 = _ld()
    allr = _ready_all()
    st.caption(f"렌더링 대기 {len(allr)}개 (start_index {int(start)} 이상, 번호순). 아래에서 만들 소재를 직접 고르세요. 기본은 앞에서 count개입니다.")
    pick4 = st.multiselect("렌더링할 소재", allr, default=allr[:int(count)], key=f"rd_pick_{int(start)}_{int(count)}_{len(allr)}",
                           format_func=lambda i: f"{i} {d4[i].get('country', '')} - {d4[i].get('topic', '')}")
    rows = []
    for i in pick4:
        n_img, tried = _img_state(i, d4[i])
        rows.append({"번호": i, "나라": d4[i].get("country", ""), "이미지": f"{n_img}/6", "이미지 단계 거침": "O" if tried else "X",
                     "음성": "O" if _audio_ok(d4[i]) else "X"})
    if rows:
        st.dataframe(rows, use_container_width=True, hide_index=True)
    else:
        st.info("선택된 소재가 없습니다. (이미 만든 영상을 다시 만들려면 위 redo 칸에 번호를 넣고 5단계를 실행하세요)")
    unchecked = [r["번호"] for r in rows if r["이미지 단계 거침"] == "X"]
    ok4 = True
    if unchecked:
        st.warning(f"{unchecked}번은 3단계(이미지 받기/확인)를 거치지 않았습니다.")
        ok4 = st.checkbox("이미지를 확인하지 않고 그대로 렌더링 (없는 이미지는 자동으로 받음)", False, key="rd_skip")
    redo_voice = st.checkbox("음성도 지금 설정으로 다시 만들기 (끄면 4단계에서 만든 음성을 그대로 사용)", False, key="rd_revoice")
    st.caption("자막 방식은 위 '🎙 음성 · 자막 설정' 패널에서 정합니다. 음성이 없는 소재만 음성을 새로 만듭니다. 선택한 소재만 만들어집니다.")
    if st.button("렌더링 시작", key="rd_go", disabled=not ((rows or redo.strip()) and ok4), help="review.txt 수정을 반영한 뒤 선택한 소재만 음성 → 영상 → 썸네일 순서로 만듭니다"):
        steps = list(pre)
        for i in pick4:
            steps.append(S("generate_script.py", "--extras-only", "--index", str(i)))
            if redo_voice or not _audio_ok(d4[i]):
                steps.append(S("generate_tts.py", "--index", str(i)))
            if unchecked:
                steps.append(S("fetch_images.py", "--index", str(i)))
            steps.append(S("build_video.py", "--index", str(i), "--channel", CH, "--handle", HD))
        if pick4:
            steps.append(S("make_thumbnail.py", "--channel", CH, "--handle", HD, "--only", ",".join(map(str, pick4))))
        chain(steps)

with st.expander("6단계 · 유튜브 업로드 (비공개)", expanded=False):
    if st.button("업로드", key="up_go", help="만든 영상을 비공개로 올립니다. YT_REFRESH_TOKEN 환경변수가 필요합니다") :
        if os.environ.get("YT_REFRESH_TOKEN"):
            run("upload_to_youtube.py", "--limit", str(count))
        else:
            st.error("YT_REFRESH_TOKEN 환경변수가 없습니다.")

with st.expander("⚡ 자동 진행 (확인 없이 이어서 실행)", expanded=False):
    upto = st.radio("어디까지 자동으로 이어서 할까요", ["2 대본까지", "3 이미지까지", "4 렌더링까지"], index=0, horizontal=True, key="auto_upto",
                    help="중간 확인 없이 선택한 단계까지 한 번에 실행합니다. 검수를 하려면 위 단계별 버튼을 쓰세요")
    if st.button("자동 진행 시작", key="auto_go"):
        steps = script_steps(True)
        if not upto.startswith("2"):
            steps += [S("generate_script.py", "--extras-only", *a), S("fetch_images.py", *a, "--any")]
        if upto.startswith("4"):
            steps += [S("generate_tts.py", *a), S("build_video.py", *a, "--channel", CH, "--handle", HD),
                      S("make_thumbnail.py", "--channel", CH, "--handle", HD, "--start", str(start))]
        chain(steps)

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

tab_s, tab_add, tab_st, tab_r, tab_i, tab_v, tab_o, tab_ep, tab_m, tab_l = st.tabs(["📝 대본 보기/수정", "➕ 소재 추가", "🗂 소재 상태/폐기", "📄 review.txt", "🖼 이미지 검수/교체", "🎬 만든 영상", "✍ 문구 넣기", "🎞 편집 포인트", "📋 제목/설명 (디스코드·유튜브)", "🎞 롱폼 묶기"])

with tab_add:
    def run_cap(*args):
        """add_topic.py 같은 짧은 작업: 실행하고 출력 마지막의 'CREATED: 번호,...' 를 돌려준다"""
        st.write("▶ `python " + " ".join(a_[:60] for a_ in args) + "`")
        env_ = dict(os.environ, PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8", **tts_env())
        with st.spinner("실행 중..."):
            r_ = subprocess.run([sys.executable, *args], capture_output=True, text=True, encoding="utf-8", errors="replace", env=env_)
        out_ = (r_.stdout or "") + (r_.stderr or "")
        (st.success if r_.returncode == 0 else st.error)("완료" if r_.returncode == 0 else f"실패 (코드 {r_.returncode})")
        st.code(out_[-1500:] or "(출력 없음)")
        m_ = re.search(r"CREATED:\s*([\d,]+)", out_)
        return [int(x) for x in m_.group(1).split(",")] if m_ and r_.returncode == 0 else []

    def after_create(ids, go_script):
        """만든 소재를 대본 단계까지 이어서 진행"""
        if not ids:
            return
        d_ = _ld()
        if add_edit.strip():
            for i in ids:
                d_[i]["edit_points_text"] = add_edit.strip()
            _sd(d_)
        for i in ids:
            f_ = d_[i]
            if f_.get("status") == "scripted":  # 직접 쓴 대본: 제목/핵심 문구/이미지 검색어만 채움
                if go_script:
                    run("generate_script.py", "--extras-only", "--index", str(i))
                    run("export_review.py", "--limit", "1", "--start", str(i))
            elif f_.get("status") == "verified" and go_script:
                run("generate_script.py", "--start", str(i), "--limit", "1")
                run("export_review.py", "--limit", "1", "--start", str(i))
        st.success(f"소재 {ids} 추가됨. 사이드바 현황에서 확인하고, '📝 대본 보기/수정' 탭에서 대본을 확인한 뒤 3단계(이미지)로 가세요.")

    add_mode = st.radio("추가 방식", ["✍ 대본 직접 입력", "🔑 키워드로 만들기", "📡 SNS 발굴 / 글 붙여넣기"], horizontal=True, key="add_mode")
    go_script = st.checkbox("만든 뒤 대본/제목/이미지 검색어까지 이어서 만들기 (Groq 사용)", True, key="add_go")
    add_edit = st.text_area("편집 지시 (선택, 쇼츠 렌더링 때 자동 반영)", key="add_edit", height=70,
                            placeholder='예: 첫 화면에 갈색 치즈를 크게 보여주고, "초콜릿이 아니라 치즈" 대목에서 일반 치즈와 교차 편집하세요.')

    if add_mode.startswith("✍"):
        st.caption("직접 쓴 대본으로 소재를 만듭니다 (대본 완료 상태로 바로 들어감). 제목·핵심 문구·이미지 검색어는 AI가 채웁니다.")
        m_narr = st.text_area("대본 (60자 이상, 전체 내용)", height=220, key="add_narr")
        m1, m2 = st.columns(2)
        m_country = m1.text_input("나라" if not EN else "짧은 제목 (영어, 2~5단어)", key="add_country",
                                  help="비워 두면 대본에서 나라 이름을 찾습니다" if not EN else "예: Korean Delivery Culture")
        m_topic = m2.text_input("주제 한 줄 (선택)", key="add_topic")
        if st.button("소재 만들기", key="add_manual_go", disabled=len(m_narr.strip()) < 60):
            ids_ = run_cap("add_topic.py", "manual", "--narration", m_narr, *(["--country", m_country] if m_country.strip() else []),
                           *(["--topic", m_topic] if m_topic.strip() else []))
            after_create(ids_, go_script)
    elif add_mode.startswith("🔑"):
        st.caption("키워드로 소재(훅/본문/반전)를 만들고 대본까지 이어갑니다. 위키백과 근거를 쓰면 사실 확인이 쉬워집니다. 모델 지식만 쓴 경우 사실 확인이 꼭 필요합니다.")
        kw = st.text_input("키워드", key="add_kw", placeholder="예: 라오스 머리 만지기 금기" if not EN else "e.g. Korean convenience store culture")
        k1, k2 = st.columns(2)
        use_wiki = k1.checkbox("위키백과 근거 사용", True, key="add_wiki")
        k_ok = k2.checkbox("바로 승인(verified)", True, key="add_kw_ok", help="끄면 승인 대기로 들어가 1단계에서 확인 후 승인합니다")
        if st.button("키워드로 소재 만들기", key="add_kw_go", disabled=not kw.strip()):
            ids_ = run_cap("add_topic.py", "keyword", "--keyword", kw.strip(), *(["--wiki"] if use_wiki else []), *(["--approve"] if k_ok else []))
            after_create(ids_, go_script)
    else:
        st.caption("레딧에서 요즘 화제인 글을 모으거나, 다른 SNS(인스타·X·스레드·네이버 등) 글을 복사해 붙여넣어 소재를 만듭니다. "
                   "글에 적힌 내용만 쓰도록 요청하지만 SNS 글은 틀린 정보가 많으니 사실 확인이 꼭 필요합니다(승인 대기로 들어갑니다). 저작권상 글 표현을 그대로 쓰지 않고 사실만 새로 씁니다.")
        st.caption("소스: 레딧 + 마스토돈(키 불필요), 유튜브(환경변수 YOUTUBE_API_KEY 필요). 인스타·X·스레드·네이버 등은 공식 API가 없거나 유료/약관 제한이 있어 아래 '글 직접 붙여넣기'를 쓰세요.")
        d1, d2, d3 = st.columns([3, 1, 1])
        subs = d1.text_input("레딧 서브레딧 (쉼표, 비우면 제외)", "korea,Living_in_Korea,seoul" if EN else "todayilearned,travel,Damnthatsinteresting", key="sns_subs")
        per = d2.selectbox("기간", ["week", "day", "month", "year"], key="sns_per")
        lim = d3.number_input("소스당 개수", 5, 50, 15, key="sns_lim")
        e1, e2 = st.columns(2)
        mtags = e1.text_input("마스토돈 해시태그 (쉼표, 선택)", "korea,koreanculture" if EN else "culture,travel", key="sns_mtags")
        ykw = e2.text_input("유튜브 검색어 (쉼표, 선택, API 키 필요)", "", key="sns_ykw")
        cur = st.checkbox("한국어로 번역하고 우리 채널 주제 적합도(0~10) 매기기 (Groq 사용, 후보 8개당 1회)", True, key="sns_cur")
        if st.button("후보 모으기", key="sns_go"):
            run("discover_sns.py", "--subs", subs, "--time", per, "--limit", str(int(lim)),
                *(["--mastodon-tags", mtags] if mtags.strip() else []), *(["--youtube", ykw] if ykw.strip() else []), *(["--curate"] if cur else []))
        cands = []
        try:
            cands = json.load(open("sns_candidates.json", encoding="utf-8"))
        except Exception:
            pass
        if cands:
            has_fit = any("fit" in c_ for c_ in cands)
            min_fit = st.slider("최소 적합도", 0, 10, 5 if has_fit else 0, key="sns_minfit") if has_fit else 0
            view = [i for i, c_ in enumerate(cands) if int(c_.get("fit", 10)) >= min_fit]
            st.caption(f"후보 {len(cands)}개 중 {len(view)}개 표시 (적합도 높은 순)")
            if view:
                ci = st.selectbox("후보", view, key="sns_pick",
                                  format_func=lambda i: (f"[{cands[i].get('fit', '-')}] " if has_fit else "") + f"{cands[i]['source']} · "
                                                        + (cands[i].get("ko_title") or cands[i]["title"])[:70])
                c_ = cands[ci]
                st.markdown(f"[원문 열기]({c_['url']})")
                if c_.get("ko_title"):
                    st.markdown(f"**{c_['ko_title']}**  \n{c_.get('ko_summary', '')}  \n_적합도 {c_.get('fit', '-')}: {c_.get('reason', '')}_")
                with st.expander("원문"):
                    st.text(c_["title"] + ("\n\n" + c_["text"][:800] if c_.get("text") else ""))
                if st.button("이 글로 소재 만들기", key="sns_make"):
                    ids_ = run_cap("add_topic.py", "text", "--text", c_["title"] + "\n" + c_.get("text", ""), "--url", c_["url"])
                    after_create(ids_, False)
        st.divider()
        st.markdown("**글 직접 붙여넣기** (아무 SNS/기사 글)")
        p_txt = st.text_area("글 내용", height=160, key="sns_paste")
        p_url = st.text_input("원문 링크 (선택)", key="sns_url")
        p_ok = st.checkbox("바로 승인(verified)", False, key="sns_ok", help="사실 확인을 마쳤다면 켜세요")
        if st.button("붙여넣은 글로 소재 만들기", key="sns_paste_go", disabled=len(p_txt.strip()) < 30):
            ids_ = run_cap("add_topic.py", "text", "--text", p_txt, *(["--url", p_url] if p_url.strip() else []), *(["--approve"] if p_ok else []))
            after_create(ids_, go_script and p_ok)

with tab_st:
    import redo_videos as RV
    ST_LABEL = {"unverified": "승인 대기", "verified": "승인됨(대본 만들 차례)", "scripted": "대본 완료", "tts_done": "음성 완료",
                "video_done": "영상 완료", "rejected": "폐기"}
    ACTIONS = {
        "폐기 (rejected)": "reject",
        "승인 대기로 (unverified)": "unverified",
        "승인됨으로 (verified)": "verified",
        "대본 완료로 되돌리기 - 대본 유지, 음성/영상 기록 지움 (영상 다시 만들기)": "scripted",
        "영상 완료로 (video_done) - 이미 영상을 만들었거나 다른 곳에서 올린 소재를 렌더링 대상에서 뺌": "video_done",
        "대본부터 다시 - 대본/제목/검색어/음성/영상 지움": "redo_script",
    }
    db_t = _ld()
    st.caption("소재(대본)의 상태를 바꿉니다. 폐기하면 이후 단계에서 건너뜁니다. 영상 파일과 유튜브 업로드 기록(youtube_id)은 지우지 않습니다.")
    f1, f2 = st.columns([2, 1])
    stat_pick = f1.multiselect("상태 필터", list(ST_LABEL), default=["unverified", "verified", "scripted", "tts_done", "video_done"],
                               format_func=lambda k: ST_LABEL[k], key="stt_filter")
    only_start = f2.checkbox("start_index 이상만", True, key="stt_start")
    rows_t = [i for i, f in enumerate(db_t) if f.get("status") in stat_pick and (not only_start or i >= int(start))]
    rows_t = sorted(rows_t, reverse=True)[:300]
    if rows_t:
        st.dataframe([{"번호": i, "나라": db_t[i].get("country", ""), "주제": str(db_t[i].get("topic", ""))[:40],
                       "상태": ST_LABEL.get(db_t[i].get("status"), db_t[i].get("status")),
                       "대본": "O" if len(str(db_t[i].get("narration") or "").strip()) >= 60 else "X",
                       "유튜브": upload_state(db_t[i]), "사유": str(db_t[i].get("reject_reason", ""))[:30]} for i in rows_t],
                     use_container_width=True, hide_index=True, height=300)
    pick_t = st.multiselect("바꿀 소재", rows_t, key="stt_pick",
                            format_func=lambda i: f"{i} {db_t[i].get('country', '')} - {db_t[i].get('topic', '')} [{ST_LABEL.get(db_t[i].get('status'), '')}]")
    act_t = st.radio("바꿀 상태", list(ACTIONS), key="stt_act")
    reason_t = st.text_input("폐기 사유 (선택)", "UI에서 폐기", key="stt_reason") if ACTIONS[act_t] == "reject" else ""
    if st.button("상태 변경", key="stt_go", disabled=not pick_t):
        d_ = _ld(); msgs = []
        if ACTIONS[act_t] == "redo_script":
            RV.redo_script(d_, pick_t)
            msgs.append(f"{len(pick_t)}개: 대본부터 다시 (2단계에서 대본 만들기)")
        else:
            for i in pick_t:
                f = d_[i]
                a_t = ACTIONS[act_t]
                if a_t == "reject":
                    f["status"] = "rejected"; f["reject_reason"] = reason_t or "UI에서 폐기"
                elif a_t == "scripted":
                    if len(str(f.get("narration") or "").strip()) < 60:
                        msgs.append(f"{i}: 대본이 없어 건너뜀"); continue
                    for k in RV.CLEAR + ("reject_reason",):
                        f.pop(k, None)
                    f["status"] = "scripted"
                elif a_t == "video_done":
                    if len(str(f.get("narration") or "").strip()) < 60:
                        msgs.append(f"{i}: 대본이 없어 건너뜀"); continue
                    f.pop("reject_reason", None); f["status"] = "video_done"; f["status_v6"] = "video_done"
                else:
                    f.pop("reject_reason", None); f["status"] = a_t
            msgs.append(f"{len(pick_t)}개 처리")
        _sd(d_)
        st.success(" / ".join(msgs)); st.rerun()

    # ---- 업로드 기록: 유튜브에 직접 올린 영상 주소를 소재에 연결 ----
    st.divider()
    st.subheader("📌 업로드 기록 (영상 주소 붙여넣기)")
    st.caption("유튜브에 직접 올린 영상의 주소를 소재에 연결해 두면 '영상완료·미업로드'와 '업로드됨'이 구분됩니다. "
               "주소는 youtu.be/… , youtube.com/watch?v=… , youtube.com/shorts/… 모두 됩니다.")
    import re as _re_u, datetime as _dt_u
    _PRIV_U = {"비공개": "private", "공개": "public", "일부공개": "unlisted"}

    def _yt_id_u(text):
        m_ = _re_u.search(r"(?:youtu\.be/|youtube\.com/(?:shorts/|embed/|live/)|[?&]v=)([\w-]{11})", text or "")
        if m_:
            return m_.group(1)
        t_ = (text or "").strip()
        return t_ if _re_u.fullmatch(r"[\w-]{11}", t_) else ""

    def _link_u(d_, idx, vid, priv):
        """소재 idx 에 영상 연결. 문제 있으면 이유(str), 성공이면 ''"""
        if not (0 <= idx < len(d_)):
            return f"{idx}번 소재가 없습니다"
        for j_, g_ in enumerate(d_):
            if j_ != idx and g_.get("youtube_id") == vid:
                return f"이 영상은 이미 {j_}번 소재에 연결돼 있습니다"
        d_[idx]["youtube_id"], d_[idx]["youtube_privacy"] = vid, priv
        d_[idx]["uploaded_at"] = _dt_u.datetime.now(_dt_u.timezone(_dt_u.timedelta(hours=9))).strftime("%Y-%m-%d")
        return ""

    d_u = _ld()
    pend_u = sorted([i for i, f in enumerate(d_u) if not f.get("youtube_id") and (f.get("video_path_v6") or f.get("status_v6") == "video_done")], reverse=True)
    mode_u = st.radio("방식", ["한 개씩", "여러 개 한 번에"], horizontal=True, key="urec_mode")
    if mode_u == "한 개씩":
        if not pend_u:
            st.info("영상완료·미업로드 소재가 없습니다.")
        else:
            pk_u = st.selectbox("소재 (영상완료·미업로드)", pend_u, key="urec_pick",
                                format_func=lambda i: f"{i} {d_u[i].get('country', '')} - {' '.join(filter(None, [d_u[i].get('title_line1'), d_u[i].get('title_line2')])) or d_u[i].get('topic', '')}")
            url_u = st.text_input("유튜브 영상 주소", key="urec_url")
            pv_u = st.radio("공개 상태", list(_PRIV_U), horizontal=True, key="urec_priv")
            if st.button("업로드 기록 저장", key="urec_go", disabled=not url_u.strip()):
                vid_u = _yt_id_u(url_u)
                if not vid_u:
                    st.error("영상 주소에서 ID를 찾지 못했습니다")
                else:
                    why_u = _link_u(d_u, pk_u, vid_u, _PRIV_U[pv_u])
                    if why_u:
                        st.error(why_u)
                    else:
                        _sd(d_u); st.success(f"{pk_u}번 소재에 {vid_u} 기록"); st.rerun()
    else:
        st.caption("한 줄에 `소재번호 영상주소` (공개 상태를 적으려면 끝에 공개/비공개/일부공개). 예: `270 https://youtu.be/xxxxxxxxxxx 공개`")
        bulk_u = st.text_area("목록", height=140, key="urec_bulk")
        if st.button("한 번에 기록", key="urec_bulk_go", disabled=not bulk_u.strip()):
            msgs_u, ok_u = [], 0
            for ln_ in bulk_u.splitlines():
                ln_ = ln_.strip()
                if not ln_:
                    continue
                parts_ = ln_.split()
                if len(parts_) < 2 or not parts_[0].isdigit():
                    msgs_u.append(f"형식 오류: {ln_[:40]}"); continue
                vid_u = _yt_id_u(parts_[1])
                if not vid_u:
                    msgs_u.append(f"{parts_[0]}: 주소를 못 읽음"); continue
                pv_ = _PRIV_U.get(parts_[2], "private") if len(parts_) > 2 else "private"
                why_u = _link_u(d_u, int(parts_[0]), vid_u, pv_)
                if why_u:
                    msgs_u.append(f"{parts_[0]}: {why_u}")
                else:
                    ok_u += 1
            if ok_u:
                _sd(d_u)
            (st.success if ok_u else st.warning)(f"{ok_u}개 기록" + ("\n" + "\n".join(msgs_u) if msgs_u else ""))
    with st.expander("연결 해제 / 공개 상태 고치기"):
        upl_u = sorted([i for i, f in enumerate(d_u) if f.get("youtube_id")], reverse=True)
        pk2_u = st.multiselect("업로드 기록이 있는 소재", upl_u, key="urec_un_pick",
                               format_func=lambda i: f"{i} {d_u[i].get('country', '')} [{d_u[i].get('youtube_privacy', '')}] {d_u[i].get('youtube_id', '')}")
        c1_u, c2_u = st.columns(2)
        pvn_u = c1_u.selectbox("바꿀 공개 상태", list(_PRIV_U), key="urec_un_priv")
        if c1_u.button("공개 상태만 기록 변경 (유튜브는 안 바뀜)", key="urec_un_set", disabled=not pk2_u):
            for i in pk2_u:
                d_u[i]["youtube_privacy"] = _PRIV_U[pvn_u]
            _sd(d_u); st.success("변경됨"); st.rerun()
        if c2_u.button("연결 해제 (기록 삭제)", key="urec_un_clear", disabled=not pk2_u):
            for i in pk2_u:
                for k in ("youtube_id", "youtube_privacy", "uploaded_at"):
                    d_u[i].pop(k, None)
            _sd(d_u); st.success("해제됨"); st.rerun()

with tab_r:
    st.caption("대본·제목·검색어를 한 파일에서 고칩니다 (위 대본 탭과 같은 내용)")
    st.caption("대본[N]·핵심[N]·이미지[N]·제목 수정 가능 / 소재를 건너뛰려면 `제외:` 뒤에 사유 / ( 로 시작하는 줄은 참고용 / === [번호] === 줄은 수정 금지")
    txt = read_review()
    new = st.text_area("review.txt", txt, height=400, label_visibility="collapsed", help="수정 후 아래 저장 버튼을 꼭 누르세요")
    if st.button("review.txt 저장"):
        write_review(new); st.success("저장됨 (다음 단계 실행 때 자동 반영)")



with tab_s:
    from common import load_db as _ldb, split_sentences as _ss
    ids_rev = review_indexes()
    db_s = _ldb()
    cand_s = [i for i, f in enumerate(db_s) if str(f.get("narration", "")).strip() and f.get("status") != "rejected"]
    cand_s = sorted(set(cand_s) | set(ids_rev), reverse=True)  # 최신 번호가 위로
    if not cand_s:
        st.info("대본이 있는 소재가 없습니다. 먼저 ① prepare를 실행하세요.")
    else:
        sel = st.selectbox("소재 번호", cand_s, key="script_sel",
                           format_func=lambda i: f"{i} {db_s[i].get('country', '') if i < len(db_s) else ''} "
                                                 f"({db_s[i].get('status', '') if i < len(db_s) else ''})"
                                                 + (" · review.txt" if i in ids_rev else ""),
                           help="review.txt에 있는 소재는 거기에 저장되고, 없는 소재는 facts_db.json에 바로 저장됩니다")
        if sel in ids_rev:
            lines = read_review().splitlines()
            a_, b_ = block_range(lines, sel)
            blk = lines[a_:b_]
            narr = [re.sub(r"^대본\s*\[\s*\d+\s*\]\s*[:：]\s*", "", l.strip()) for l in blk if re.match(r"^대본\s*\[", l.strip())]
            hls = [l.strip() for l in blk if re.match(r"^핵심\s*\[", l.strip())]
            title = [l.strip() for l in blk if re.match(r"^제목\s*[12]", l.strip())]
            st.caption(" / ".join(title))
        else:
            narr = _ss(db_s[sel].get("narration", ""))
            hls = []
            st.caption(f"{db_s[sel].get('title_line1', '')} {db_s[sel].get('title_line2', '')}".strip()
                       + "  (review.txt에 없는 소재: facts_db.json에 바로 저장)")
        st.markdown("**대본 (한 줄 = 한 문장, 줄을 지우면 문장이 빠지고 번호는 다시 매겨집니다)**")
        n_txt = st.text_area("대본", "\n".join(narr), height=260, key=f"n_{sel}", label_visibility="collapsed")
        h_txt = ""
        if sel in ids_rev:
            st.markdown("**핵심 문구** (`CAPTION_MODE=highlight`일 때만 쓰임. 기본 자막 방식에서는 화면에 안 나옵니다)")
            h_txt = st.text_area("핵심", "\n".join(hls), height=100, key=f"h_{sel}", label_visibility="collapsed")
        st.caption("대본을 고치면 음성이 다시 만들어지고, 이미지 검색어는 새 대본 기준으로 다시 만들어집니다(이미지 탭에서 확인). "
                   "이미 영상이 만들어진 소재는 수정 후 redo에 번호를 넣고 5단계를 해야 영상에 반영됩니다.")
        if st.button("대본 저장", key=f"save_s_{sel}"):
            ns = [x.strip() for x in n_txt.splitlines() if x.strip()]
            if sel in ids_rev:
                hs = [x.strip() for x in h_txt.splitlines() if x.strip()]
                replace_lines(sel, r"^대본\s*\[", [f"대본[{i}]: {t}" for i, t in enumerate(ns, 1)])
                replace_lines(sel, r"^핵심\s*\[", hs)
                apply_quiet()
            else:
                tmp = "review_tmp_edit.txt"
                with open(tmp, "w", encoding="utf-8") as f_:
                    f_.write(f"=== [{sel}] ===\n" + "\n".join(f"대본[{i}]: {t}" for i, t in enumerate(ns, 1)) + "\n")
                subprocess.run([sys.executable, "apply_review.py", "--file", tmp], capture_output=True, text=True,
                               encoding="utf-8", errors="replace", env=dict(os.environ, PYTHONIOENCODING="utf-8"))
                try:
                    os.remove(tmp)
                except OSError:
                    pass
            st.success(f"저장 및 DB 반영 완료 (대본 {len(ns)}문장)")
            st.rerun()

    with st.expander("✏️ 여러 대본 한 번에 수정 (일괄)"):
        st.caption("번호를 지정해 불러오면 한 칸에 여러 소재의 대본이 나옵니다. `=== [번호] ===` 줄은 지우지 말고, 그 아래 한 줄 = 한 문장으로 고치세요. "
                   "바뀐 소재만 저장됩니다. (제목/핵심 문구는 여기서 안 바뀜)")
        bc1, bc2 = st.columns([3, 1])
        bsel = bc1.text_input("불러올 번호 (예: 109,110,115-118)", key="bulk_sel", help="쉼표와 범위(115-118)를 섞어 쓸 수 있습니다")

        def _narr_of(i):
            if i in ids_rev:
                ln = read_review().splitlines()
                rg = block_range(ln, i)
                if rg:
                    return [re.sub(r"^대본\s*\[\s*\d+\s*\]\s*[:：]\s*", "", l.strip()) for l in ln[rg[0]:rg[1]] if re.match(r"^대본\s*\[", l.strip())]
            return _ss(db_s[i].get("narration", "")) if i < len(db_s) else []

        def _parse_nums(t):
            out = []
            for part in re.split(r"[,\s]+", t.strip()):
                if not part:
                    continue
                m = re.match(r"^(\d+)\s*-\s*(\d+)$", part)
                if m:
                    a_, b_ = int(m.group(1)), int(m.group(2))
                    out += list(range(min(a_, b_), max(a_, b_) + 1))
                elif part.isdigit():
                    out.append(int(part))
            return [i for i in dict.fromkeys(out) if i in cand_s]

        if bc2.button("불러오기", key="bulk_load"):
            nums = sorted(_parse_nums(bsel))
            if not nums:
                st.warning("대본이 있는 소재 번호가 없습니다.")
            elif len(nums) > 30:
                st.warning("한 번에 30개까지만 불러올 수 있습니다.")
            else:
                st.session_state["bulk_txt"] = "\n\n".join(f"=== [{i}] ===\n" + "\n".join(_narr_of(i)) for i in nums)
                st.session_state["bulk_orig"] = {i: _narr_of(i) for i in nums}
        if st.session_state.get("bulk_txt"):
            btxt = st.text_area("일괄 편집", st.session_state["bulk_txt"], height=500, key="bulk_area")
            if st.button("바뀐 대본 모두 저장", key="bulk_save", type="primary", help="바뀐 소재만 DB에 반영합니다. 음성은 지워지고 이미지 검색어는 새 대본 기준으로 다시 만들어집니다"):
                blocks, cur = {}, None
                for l in btxt.splitlines():
                    m = re.match(r"^===\s*\[(\d+)\]", l.strip())
                    if m:
                        cur = int(m.group(1)); blocks[cur] = []
                    elif cur is not None and l.strip():
                        blocks[cur].append(l.strip())
                orig = st.session_state.get("bulk_orig", {})
                changed = [i for i, v in blocks.items() if i in orig and v != orig[i] and v]
                tmp_lines, in_rev = [], False
                for i in changed:
                    if i in ids_rev:
                        replace_lines(i, r"^대본\s*\[", [f"대본[{n}]: {t}" for n, t in enumerate(blocks[i], 1)])
                        in_rev = True
                    else:
                        tmp_lines.append(f"=== [{i}] ===\n" + "\n".join(f"대본[{n}]: {t}" for n, t in enumerate(blocks[i], 1)))
                if tmp_lines:
                    with open("review_tmp_edit.txt", "w", encoding="utf-8") as f_:
                        f_.write("\n\n".join(tmp_lines) + "\n")
                    subprocess.run([sys.executable, "apply_review.py", "--file", "review_tmp_edit.txt"], capture_output=True, text=True,
                                   encoding="utf-8", errors="replace", env=dict(os.environ, PYTHONIOENCODING="utf-8"))
                    try:
                        os.remove("review_tmp_edit.txt")
                    except OSError:
                        pass
                if in_rev:
                    apply_quiet()
                for i in changed:
                    orig[i] = blocks[i]
                st.session_state["bulk_orig"] = orig
                st.success(f"{len(changed)}개 소재 저장 완료: {', '.join(map(str, changed)) or '변경 없음'}"
                           + ("  → 이미지 탭의 '일괄 새로 받기'(검색어도 새로 만들기 체크)로 이미지를 받으세요" if changed else ""))

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
        st.checkbox("이미 업로드된 영상은 이미지를 다시 받을 때 유튜브 설명(사진 출처)도 같이 수정", True, key="desc_sync",
                    help="영상 파일 자체는 유튜브에서 못 바꾸고 설명란만 바뀝니다. 영상에 새 사진을 넣으려면 새로 렌더링해 다시 올려야 합니다. 토큰에 영상 수정 권한이 없으면 실패하고 붙여넣을 설명을 보여줍니다.")
        qs = list(item.get("image_queries") or [])
        credits = {c.get("scene"): c for c in (item.get("image_credits") or [])}
        pix = os.environ.get("PIXABAY_API_KEY", "").strip()
        st.caption("검색어를 고치고 [이 장면 다시 받기]를 누르면 그 장면만 새로 받습니다. 직접 가진 사진은 [사진 올리기]로 바꿀 수 있습니다. "
                   "이미지 검색어가 비어 있으면 5단계 때(또는 아래 버튼으로) 대본 기준으로 만들어집니다.")
        fetch_code = ("import os,requests;import fetch_images as F;from common import load_db,save_db;"
                      f"db=load_db();F.fetch_item(requests.Session(),os.environ['PIXABAY_API_KEY'],{idx},db[{idx}],False);save_db(db)")
        cA, cB = st.columns(2)
        if cA.button("빠진 이미지 받기 / 검색어 생성", key=f"fill_{idx}", help="검색어가 없으면 대본 기준으로 만들고, 없는 장면의 이미지를 받습니다"):
            if not qs:
                run("generate_script.py", "--extras-only", "--index", str(idx))
            if pix:
                run("-c", fetch_code)
                if not sync_desc([idx]):
                    st.stop()
            else:
                st.warning("PIXABAY_API_KEY가 없어 이미지를 받을 수 없습니다.")
            st.rerun()
        regen = st.checkbox("검색어도 대본 기준으로 새로 만들기 (Groq 호출 1회)", key=f"regen_{idx}",
                            help="체크하면 현재 검색어를 지우고 대본 내용으로 다시 만든 뒤 이미지를 받습니다. 체크 해제는 지금 검색어 그대로 사진만 새로 받음")
        if cB.button("이 소재 이미지 전부 새로 받기", key=f"all_{idx}", help="영상이 이미 만들어진 소재도 됩니다. 영상에 반영하려면 redo에 번호를 넣고 5단계를 다시 하세요"):
            if not pix:
                st.warning("PIXABAY_API_KEY가 없어 받을 수 없습니다.")
            else:
                if regen:
                    run("generate_script.py", "--extras-only", "--index", str(idx), "--regen-queries")
                run("fetch_images.py", "--index", str(idx), "--force")
                if sync_desc([idx]):
                    st.rerun()
        done_idx = [i for i, f in enumerate(db_) if f.get("status") == "video_done"]
        with st.expander("🔁 여러 소재 이미지 일괄 새로 받기 (영상 있는 소재 포함)"):
            st.caption("선택한 소재의 사진을 전부 다시 받아 덮어씁니다(소재당 보통 10~20초). 영상은 안 바뀌므로 반영하려면 redo에 번호를 넣고 5단계를 하세요. "
                       "검색어를 새로 만들면 소재당 Groq 1회가 듭니다.")
            bulk = st.text_input("소재 번호 (예: 109-115,120)", key="bulk_idx")
            use_done = st.checkbox(f"영상이 있는 모든 소재({len(done_idx)}개) 대상으로", key="bulk_alldone")
            bulk_regen = st.checkbox("검색어도 대본 기준으로 새로 만들기 (없는 소재는 자동으로 만듦)", key="bulk_regen")
            ok_b = st.checkbox("사진을 전부 덮어써도 됩니다", key="bulk_ok")
            if st.button("일괄 새로 받기", key="bulk_go", disabled=not ok_b):
                nums = list(done_idx) if use_done else []
                for part in re.split(r"[,\s]+", bulk.strip()):
                    m_ = re.fullmatch(r"(\d+)-(\d+)", part)
                    if m_:
                        nums += list(range(int(m_.group(1)), int(m_.group(2)) + 1))
                    elif part.isdigit():
                        nums.append(int(part))
                nums = [n_ for n_ in dict.fromkeys(nums) if 0 <= n_ < len(db_)]
                if not nums:
                    st.warning("번호를 입력하거나 '영상이 있는 모든 소재'를 체크하세요.")
                elif not pix:
                    st.warning("PIXABAY_API_KEY가 없어 받을 수 없습니다.")
                else:
                    TIMES.clear()
                    prog = st.progress(0.0)
                    for k_, n_ in enumerate(nums, start=1):
                        st.write(f"**[{k_}/{len(nums)}] {n_} {db_[n_].get('country', '')}**")
                        if bulk_regen or not db_[n_].get("image_queries"):
                            run("generate_script.py", "--extras-only", "--index", str(n_), *(["--regen-queries"] if bulk_regen else []))
                        run("fetch_images.py", "--index", str(n_), "--force")
                        prog.progress(k_ / len(nums))
                    sync_desc(nums)
                    st.success(f"{len(nums)}개 소재 완료. 영상에 반영하려면 redo에 번호를 넣고 5단계를 하세요.")
        if not qs:
            st.warning("이미지 검색어가 아직 없습니다. 위 버튼을 누르세요.")
        else:
            cols = st.columns(3)
            for n in range(1, max(len(qs), 1) + 1):
                with cols[(n - 1) % 3]:
                    f_ = folder / f"scene_{n:02d}.png"
                    if f_.exists():
                        st.image(str(f_), caption=f"장면 {n}", use_container_width=True)
                    else:
                        st.warning(f"장면 {n}: 이미지 없음 (색 카드로 대체)")
                    c_ = credits.get(n)
                    if c_:
                        st.caption(f"출처: {'Wikimedia Commons' if c_.get('source') == 'commons' else 'Pixabay' + (' ' + {'illustration': '일러스트', 'vector': '벡터'}.get(c_.get('type'), '') if c_.get('type') in ('illustration', 'vector') else '')} · {c_.get('user', '')} {c_.get('license', '')}")
                    q_new = st.text_input("검색어", qs[n - 1] if n - 1 < len(qs) else "", key=f"q_{idx}_{n}")
                    if st.button("이 장면 다시 받기", key=f"re_{idx}_{n}"):
                        qq = list(qs); qq[n - 1] = q_new.strip()
                        d2 = load_db(); d2[idx]["image_queries"] = qq; save_db(d2)
                        replace_lines(idx, r"^이미지\s*\[", [f"이미지[{i}]: {t}" for i, t in enumerate(qq, 1)])  # review.txt에도 반영
                        if pix:
                            run("-c", fetch_code)
                            if not sync_desc([idx]):
                                st.stop()
                        else:
                            st.warning("PIXABAY_API_KEY가 없어 받을 수 없습니다.")
                        st.rerun()
                    kind_ = st.selectbox("Pixabay 종류", ["photo", "illustration", "vector"], key=f"kind_{idx}_{n}",
                                         format_func=lambda k: {"photo": "사진", "illustration": "일러스트", "vector": "벡터(그림)"}[k],
                                         help="Pixabay로 받을 때만 적용됩니다. Pixabay 라이선스는 일러스트도 같습니다")
                    sb1, sb2 = st.columns(2)
                    for col_, src_, lab_ in ((sb1, "pixabay", "Pixabay로"), (sb2, "commons", "Commons로")):
                        if col_.button(lab_, key=f"src_{src_}_{idx}_{n}",
                                       help=("현재 검색어로 Pixabay에서 다른 사진을 받습니다" if src_ == "pixabay"
                                             else "현재 검색어로 Wikimedia Commons(CC0/퍼블릭도메인/CC BY)에서 다른 사진을 받습니다. 출처/라이선스가 설명란에 들어갑니다")):
                            qq = list(qs); qq[n - 1] = q_new.strip()
                            d2 = load_db(); d2[idx]["image_queries"] = qq; save_db(d2)
                            replace_lines(idx, r"^이미지\s*\[", [f"이미지[{i}]: {t}" for i, t in enumerate(qq, 1)])
                            if src_ == "pixabay" and not pix:
                                st.warning("PIXABAY_API_KEY가 없어 받을 수 없습니다.")
                                st.stop()
                            ok_ = run("fetch_images.py", "--index", str(idx), "--scene", str(n), "--source", src_, "--type", kind_)
                            if ok_ and not sync_desc([idx]):
                                st.stop()
                            if ok_:
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

with tab_ep:
    import edit_points as EPm
    st.caption("영상 편집 지시를 글로 적으면 그대로 반영합니다 (쇼츠 전용). 예: 첫 화면에 갈색 치즈를 크게 보여주고, \"초콜릿이 아니라 치즈\" 대목에서 일반 치즈와 교차 편집하세요. "
               "지시는 소재마다 따로 저장되고 언제든 바꿔 다시 해석할 수 있습니다. 순서: ① 해석하기 → ② 이미지 받기 → ③ 영상 다시 만들기 (음성은 그대로 씀).")
    db_e = _ld()
    cand_e = [i for i, f in enumerate(db_e) if f.get("status") in ("scripted", "tts_done", "video_done") and i >= int(start)]
    if not cand_e:
        st.info("대상 소재가 없습니다. (start_index 이상, 대본이 끝난 소재)")
    else:
        ei = st.selectbox("소재", sorted(cand_e, reverse=True), key="ep_sel",
                          format_func=lambda i: f"{i} {db_e[i].get('country', '')} ({db_e[i].get('status')})"
                                                + (f" · 편집 포인트 {len(db_e[i].get('edit_points') or [])}개" if db_e[i].get("edit_points") else ""))
        it_e = db_e[ei]
        from common import split_sentences as _sse
        with st.expander("대본 (문장 번호)", expanded=False):
            st.text("\n".join(f"{n}. {t}" for n, t in enumerate(_sse(it_e.get("narration", "")), 1)))
        ep_text = st.text_area("편집 지시", it_e.get("edit_points_text", ""), height=110, key=f"ep_text_{ei}",
                               placeholder='예: 첫 화면에 갈색 치즈를 크게 보여주고, "초콜릿이 아니라 치즈"라는 대목에서 일반 치즈와 교차 편집하세요.')
        z1, z2 = st.columns(2)
        if z1.button("⚡ 한 번에: 해석 → 이미지 → 영상", key=f"ep_all_{ei}", disabled=not (ep_text.strip() and _audio_ok(it_e)),
                     help="지시를 해석하고, 이미지를 받고, 현재 음성으로 영상을 다시 만듭니다"):
            chain([S("edit_points.py", "parse", "--index", str(ei), "--text", ep_text), S("edit_points.py", "fetch", "--index", str(ei)),
                   S("build_video.py", "--index", str(ei), "--channel", CH, "--handle", HD)])
        if z2.button("지시만 저장 (렌더링 때 자동 반영)", key=f"ep_save_{ei}", disabled=not ep_text.strip(),
                     help="저장만 해 두면 5단계 렌더링/자동 진행 때 해석과 이미지 받기까지 자동으로 하고 영상에 넣습니다"):
            d_ = _ld(); d_[ei]["edit_points_text"] = ep_text; d_[ei]["edit_points"] = []; _sd(d_); st.success("저장됨"); st.rerun()
        b1, b2 = st.columns(2)
        if b1.button("① 해석하기 (Groq)", key=f"ep_parse_{ei}", disabled=not ep_text.strip()):
            run("edit_points.py", "parse", "--index", str(ei), "--text", ep_text)
            st.rerun()
        if b2.button("편집 포인트 모두 지우기", key=f"ep_clear_{ei}", disabled=not it_e.get("edit_points")):
            d_ = _ld(); d_[ei]["edit_points"] = []; d_[ei]["edit_points_text"] = ""; _sd(d_); st.rerun()
        pts = it_e.get("edit_points") or []
        if pts:
            st.markdown("**해석 결과** (틀렸으면 아래 JSON을 고치거나 지시를 바꿔 다시 해석하세요)")
            st.dataframe([{"#": k, "위치": {"start": "첫 화면", "sentence": f"{p.get('sentence')}번 문장", "phrase": f"\"{p.get('phrase')}\""}.get(p.get("at"), p.get("at")),
                           "동작": {"cross": "교차 편집(반복)", "sequence": "순서대로 전환"}.get(p.get("action"), "크게 보여주기"), "이미지(검색어)": (" → " if p.get("action") == "sequence" else " ↔ ").join(p.get("queries") or []),
                           "길이": p.get("dur") or "문장 길이", "교차 간격": p.get("interval") if p.get("action") == "cross" else ""}
                          for k, p in enumerate(pts, 1)], use_container_width=True, hide_index=True)
            with st.expander("고급: JSON 직접 수정"):
                js_ = st.text_area("edit_points", json.dumps(pts, ensure_ascii=False, indent=1), height=220, key=f"ep_json_{ei}")
                if st.button("JSON 저장", key=f"ep_jsave_{ei}"):
                    try:
                        new_pts = EPm.clean(json.loads(js_), len(_sse(it_e.get("narration", ""))))
                        d_ = _ld(); d_[ei]["edit_points"] = new_pts; _sd(d_); st.success("저장됨"); st.rerun()
                    except Exception as e_:
                        st.error(f"JSON 오류: {e_}")
            f1, f2 = st.columns(2)
            force_e = f2.checkbox("이미지를 전부 다시 받기", False, key=f"ep_force_{ei}", help="끄면 이미 받은 이미지는 그대로 둡니다. 검색어를 바꿨다면 켜세요")
            if f1.button("② 이미지 받기", key=f"ep_fetch_{ei}"):
                if run("edit_points.py", "fetch", "--index", str(ei), *(["--force"] if force_e else [])):
                    sync_desc([ei])
                    st.rerun()
            fol_ = _vd(HERE, ei, it_e)
            shown = [(k, j) for k, p in enumerate(pts, 1) for j in range(len(p.get("queries") or []))]
            have_ = [(k, j) for k, j in shown if EPm.image_path(fol_, k, j).exists()]
            if have_:
                cols_ = st.columns(min(4, len(have_)))
                for n_, (k, j) in enumerate(have_):
                    cols_[n_ % len(cols_)].image(str(EPm.image_path(fol_, k, j)), caption=f"#{k}-{j + 1} {pts[k - 1]['queries'][j]}", use_container_width=True)
            miss_ = len(shown) - len(have_)
            if miss_:
                st.warning(f"이미지가 없는 항목 {miss_}개 - ② 이미지 받기를 누르세요. 이미지가 없는 포인트는 영상에서 건너뜁니다.")
            ok_a = _audio_ok(it_e)
            if st.button("③ 이 소재 영상 다시 만들기 (음성 그대로)", key=f"ep_build_{ei}", disabled=not ok_a,
                         help="현재 음성과 이미지로 영상만 다시 렌더링합니다. 썸네일은 그대로입니다"):
                chain([S("build_video.py", "--index", str(ei), "--channel", CH, "--handle", HD)])
            if not ok_a:
                st.caption("음성이 아직 없어 영상을 만들 수 없습니다. 4단계에서 음성을 먼저 만드세요.")

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
                sp = os.path.join("videos", f[:-4] + ".srt")
                if os.path.exists(sp):
                    st.download_button("SRT 자막 받기", open(sp, "rb").read(), file_name=f[:-4] + ".srt", key="srt_" + f)
    else:
        st.info("아직 만든 영상이 없습니다.")

with tab_o:
    import pandas as pd
    import overlays as OV
    st.caption("영상 특정 시점에 문구를 넣습니다 (쇼츠). 시작/지속은 초 단위. 위치는 x,y(화면 가로·세로 %, 문구 중심)로 원하는 곳 어디든 지정합니다. 미리보기의 격자(10% 간격)를 보고 정하세요. "
               "저장 후 영상에 반영하려면 redo에 번호를 넣고 5단계를 하세요. 롱폼에는 적용되지 않습니다.")
    db_o = _ld()
    cand_o = [i for i, f in enumerate(db_o) if i >= int(start) and f.get("status") in ("scripted", "tts_done", "video_done")]
    if not cand_o:
        st.info("대상 소재가 없습니다. (start_index 이상, 대본이 끝난 소재)")
    else:
        sel_o = st.selectbox("소재 번호", sorted(cand_o, reverse=True), key="ov_sel",
                             format_func=lambda i: f"{i} {db_o[i].get('country', '')} ({db_o[i].get('status')})")
        it_o = db_o[sel_o]
        # 문장별 시간 (있으면)
        sents, total = [], 0.0
        for tp in ([it_o.get("timing_path_v2")] if it_o.get("timing_path_v2") else []):
            try:
                sents = json.load(open(tp, encoding="utf-8")).get("sentences") or []
                total = float(sents[-1]["end"]) if sents else 0.0
            except Exception:
                sents = []
        if sents:
            with st.expander(f"문장별 시간 (음성 길이 약 {total:.1f}초) - 문구 시작 시간 잡을 때 참고"):
                st.dataframe([{"시작": round(x["start"], 1), "끝": round(x["end"], 1), "문장": x["text"]} for x in sents],
                             use_container_width=True, hide_index=True)
        else:
            st.caption("아직 음성이 없어 문장별 시간을 보여줄 수 없습니다. (음성을 만든 뒤 보입니다. 쇼츠는 보통 30~50초)")
        cols = ["text", "start", "dur", "x", "y", "size", "color", "stroke", "bold", "effect", "bg"]
        df0 = pd.DataFrame(OV.clean_list(it_o.get("overlays") or []), columns=cols)
        for c_ in ("text", "color", "stroke", "effect", "bg"):
            df0[c_] = df0[c_].astype(str) if len(df0) else df0[c_].astype(object)
        if df0.empty:
            df0 = pd.DataFrame([{"text": "", "start": 0.0, "dur": 2.0, "x": 50, "y": 50, "size": 80, "color": "#FFFFFF",
                                 "stroke": "#000000", "bold": True, "effect": "팝", "bg": ""}], columns=cols)
        df0["bold"] = df0["bold"].astype(bool)
        ed = st.data_editor(
            df0, num_rows="dynamic", key=f"ov_ed_{sel_o}", use_container_width=True, hide_index=True,
            column_config={
                "text": st.column_config.TextColumn("문구 (길면 자동 줄바꿈)", width="large"),
                "start": st.column_config.NumberColumn("시작(초)", min_value=0.0, step=0.1),
                "dur": st.column_config.NumberColumn("지속(초)", min_value=0.2, step=0.1),
                "x": st.column_config.NumberColumn("x(%)", min_value=0, max_value=100, step=1, help="문구 중심의 가로 위치 (0=왼쪽 끝, 50=가운데, 100=오른쪽 끝)"),
                "y": st.column_config.NumberColumn("y(%)", min_value=0, max_value=100, step=1, help="문구 중심의 세로 위치 (0=맨 위, 50=가운데, 100=맨 아래). 이미지 영역은 약 23~76%"),
                "size": st.column_config.NumberColumn("크기(px)", min_value=20, max_value=220, step=2),
                "color": st.column_config.TextColumn("글자색", help="#RRGGBB 예: #FFE200"),
                "stroke": st.column_config.TextColumn("외곽선색", help="#RRGGBB, 비우면 외곽선 없음"),
                "bold": st.column_config.CheckboxColumn("굵게"),
                "effect": st.column_config.SelectboxColumn("효과", options=OV.EFFECTS),
                "bg": st.column_config.TextColumn("배경박스색", help="#RRGGBB, 비우면 없음"),
            })
        rows_o = [{k: (None if (isinstance(v, float) and v != v) else v) for k, v in r.items()} for r in ed.to_dict("records")]
        o1, o2 = st.columns(2)
        if o1.button("저장", key=f"ov_save_{sel_o}", type="primary"):
            clean = OV.clean_list(rows_o)
            db_o = _ld()
            if clean:
                db_o[sel_o]["overlays"] = clean
            else:
                db_o[sel_o].pop("overlays", None)
            _sd(db_o)
            st.success(f"문구 {len(clean)}개 저장. " + ("이미 만든 영상이면 redo에 번호를 넣고 5단계를 하세요." if it_o.get("video_path_v6") else "다음 렌더링에 반영됩니다."))
        # 미리보기 (저장 전 값 기준, 정지 화면)
        pv1, pv2 = st.columns(2)
        t_prev = pv1.number_input("미리보기 시점(초)", 0.0, 600.0, 1.0, 0.5, key="ov_t")
        sc_prev = pv2.number_input("배경 장면 번호", 1, 6, 1, key="ov_sc")
        show_gr = st.checkbox("격자 표시 (10% 간격 좌표)", True, key="ov_grid")
        if st.button("미리보기", key="ov_prev"):
            try:
                import build_video as BV
                from PIL import Image as _I
                t1, t2 = BV.split_title(it_o)
                bgi = BV.make_template(t1, t2, BV.safe_country(it_o), None, channel_name=CH, handle=HD, avatar_path="avatar.png").convert("RGB")
                sp = _vd(HERE, sel_o, it_o) / f"scene_{int(sc_prev):02d}.png"
                if sp.exists():
                    from layout import IMG_BOX
                    sc_img = _I.open(sp).convert("RGB")
                    bw, bh = IMG_BOX[2] - IMG_BOX[0], IMG_BOX[3] - IMG_BOX[1]
                    r = max(bw / sc_img.width, bh / sc_img.height)
                    sc_img = sc_img.resize((int(sc_img.width * r), int(sc_img.height * r)))
                    l, tp_ = (sc_img.width - bw) // 2, (sc_img.height - bh) // 2
                    bgi.paste(sc_img.crop((l, tp_, l + bw, tp_ + bh)), (IMG_BOX[0], IMG_BOX[1]))
                shown = OV.preview(OV.clean_list(rows_o), float(t_prev), bgi, show_grid=show_gr)
                st.image(shown, caption=f"{t_prev}초 시점 (효과는 최종 모습으로 표시, 자막은 안 보임)", width=480)
            except Exception as e:
                st.error(f"미리보기 실패: {type(e).__name__}: {e}")

with tab_l:
    st.caption("영상이 끝난 쇼츠를 묶어 가로 롱폼 1개로 만듭니다. 소재마다 음성/이미지를 다시 만들어서 시간이 걸립니다. 개수는 3~30개, 예상 40분 이하. facts_db.json과 별도로 longform_db.json에 기록됩니다.")
    lm = st.radio("선택 방식", ["auto (자동)", "manual (번호 직접)"], horizontal=True, key="lf_mode",
                  help="auto: 영상이 끝나고 롱폼에 안 쓴 소재를 번호순으로 / manual: 아래 번호들을 묶음")
    l1, l2, l3 = st.columns(3)
    lcount = l1.number_input("auto 개수", 3, 30, 6, key="lf_count")
    lstart = l2.number_input("auto 시작 번호", 0, 9999, 0 if EN else 106, key="lf_start", help="이 번호 이상인 소재만 후보")
    ltheme = l3.text_input("auto 분야/나라/주제 키워드", key="lf_theme", help="비우면 번호순. 소재의 theme/topic/country에 이 글자가 들어 있으면 후보")
    lidx = st.text_input("manual 번호 (예: 109,110,115-118)", key="lf_idx")
    ltitle = st.text_input("제목 (비우면 자동)", key="lf_title")
    base_args = ["build_longform.py", "--mode", "auto" if lm.startswith("auto") else "manual", "--indexes", lidx, "--theme", ltheme,
                 "--count", str(int(lcount)), "--start", str(int(lstart)), "--channel", CH, "--handle", HD]
    c1, c2 = st.columns(2)
    if c1.button("목록만 보기", key="lf_dry", help="어떤 소재가 묶일지만 보여줌 (영상 안 만듦)"):
        run(*base_args, "--dry-run")
    if c2.button("롱폼 만들기", key="lf_run", help="음성/이미지를 다시 만들고 가로 영상으로 합성 (오래 걸림)"):
        TIMES.clear(); run(*base_args, "--title", ltitle)
    if os.path.isdir("longform_out"):
        vids = sorted(f for f in os.listdir("longform_out") if f.endswith(".mp4"))
        if vids:
            last = vids[-1]
            st.markdown(f"**최근 롱폼: {last}**")
            tp = os.path.join("longform_out", last.replace(".mp4", ".txt"))
            if os.path.exists(tp):
                st.code(open(tp, encoding="utf-8").read(), language=None)
            st.video(os.path.join("longform_out", last))
            sp = os.path.join("longform_out", last[:-4] + ".srt")
            if os.path.exists(sp):
                st.download_button("롱폼 SRT 자막 받기", open(sp, "rb").read(), file_name=last[:-4] + ".srt", key="lf_srt")
