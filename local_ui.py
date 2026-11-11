"""PC용 간이 UI (Streamlit). 실행: streamlit run local_ui.py
코드 폴더(facts_db.json이 있는 곳)에 넣고 실행. 환경변수 GROQ_API_KEY(필수), PIXABAY_API_KEY 등은 미리 설정."""
import os, re, subprocess, sys, json, time
from pathlib import Path
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

# 다시 켜도 입력했던 소재 번호·제목·선택 방식을 기억 (ui_state.json)
_UI_STATE = "ui_state.json"
_UI_KEYS = ("lf_mode", "lf_theme", "lf_idx", "lf_title", "cut_idx")
def _ui_keep(k_):
    return k_ in _UI_KEYS or (k_.endswith("_ids") and isinstance(st.session_state.get(k_), str))
try:
    _ui_old = json.load(open(_UI_STATE, encoding="utf-8"))
except Exception:
    _ui_old = {}
if "_ui_restored" not in st.session_state:
    st.session_state["_ui_restored"] = True
    for _uk, _uv in _ui_old.items():
        st.session_state.setdefault(_uk, _uv)
else:
    try:
        _ui_new = {k_: v_ for k_, v_ in st.session_state.items() if _ui_keep(k_) and isinstance(v_, (str, int, float))}
        if _ui_new != {k_: v_ for k_, v_ in _ui_old.items() if k_ in _ui_new} or set(_ui_new) - set(_ui_old):
            json.dump({**_ui_old, **_ui_new}, open(_UI_STATE, "w", encoding="utf-8"), ensure_ascii=False)
    except Exception:
        pass
_NOTRANS_JS = ("<script>try{var d=window.parent.document.documentElement;d.setAttribute('lang','ko');d.setAttribute('translate','no');"
               "var m=window.parent.document.createElement('meta');m.name='google';m.content='notranslate';window.parent.document.head.appendChild(m);}catch(e){}</script>")
try:  # 브라우저 자동 번역(크롬 번역 등)이 화면을 건드려 생기는 'removeChild' 오류 방지
    _js = ("<script>try{var d=window.parent.document.documentElement;d.setAttribute('lang','ko');d.setAttribute('translate','no');"
           "var m=window.parent.document.createElement('meta');m.name='google';m.content='notranslate';window.parent.document.head.appendChild(m);}catch(e){}</script>")
    if hasattr(st, "iframe"):          # 최신 Streamlit (components.v1.html 은 곧 제거됨)
        st.iframe(_js, height=1)
    else:
        import streamlit.components.v1 as _cmp
        _cmp.html(_js, height=0)
except Exception:
    pass
st.title("Shorts 로컬 실행 - " + CH)
st.caption(f"폴더: {HERE}  |  채널: {'영어 (KoreaAtoZ)' if EN else '한국어 (gonmauY)'}")

with st.sidebar:
    st.header("사용법")
    st.markdown("""
**📖 기능 찾기·작업 순서는 위쪽 '🏠 시작·가이드' 탭**
1 소재 → 2 대본 → 3 이미지 → 4 음성 → 5 영상 → 6 업로드
(각 단계 탭 안에 *실행*과 *보기·수정*이 같이 있습니다)

- **count / start_index**: 맨 위 공통 입력. 이 개수·번호 이상만 처리
- **redo** (맨 위): 영상만 `98,99` / 대본부터 `101`+체크 / 폐기 되살리기 `101!`+체크. 작업이 끝나면 비우세요
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
TTS_CFG.setdefault("tv_fx", False)         # 영상 처음/끝에 옛날 TV 켜짐·꺼짐 효과
TTS_CFG.setdefault("font_sub", ""); TTS_CFG.setdefault("font_title", ""); TTS_CFG.setdefault("font_ovl", "")   # 글씨체 id (fonts.py), 빈 값=기본
TTS_CFG.setdefault("yt_thumb", False)   # 업로드할 때 썸네일도 같이 올림 (토큰에 youtube.force-ssl 권한 필요)
TTS_CFG.setdefault("scenes", 10)
if not TTS_CFG.get("_verify_off_v1"):      # 한 번만: 교차검증/이미지 자동검증을 기본 꺼짐으로 (직접 검증한 대본을 붙여 쓰는 방식 기본)
    TTS_CFG["cross"] = False
    TTS_CFG["imgchk"] = False
    TTS_CFG["_verify_off_v1"] = True
TTS_CFG.setdefault("cross", False)
TTS_CFG.setdefault("imgchk", False)          # 이미지 받을 때 자동 검증(+불일치 교체)
TTS_CFG.setdefault("imgchk_ollama", True)    # CLIP이 애매할 때 Ollama 비전 모델로 2차 확인
TTS_CFG.setdefault("imgchk_ollama_all", False)
TTS_CFG.setdefault("imgchk_model", "qwen2.5vl:3b")
TTS_CFG.setdefault("imgchk_thr", 0.22)
TTS_CFG.setdefault("imgchk_retry", 2)
TTS_CFG.setdefault("gh_repo", "gonmau/shortsEN" if EN else "gonmau/shorts")
TTS_CFG.setdefault("gh_auto", True)        # 시작 시 GitHub에서 먼저 가져오고(병합), 작업 후 자동으로 올림 (GITHUB_TOKEN이 있을 때만)
TTS_CFG.setdefault("discord_notify", False)  # 오래 걸리는 작업이 끝나면 디스코드로 알림
TTS_CFG.setdefault("discord_min_secs", 60)   # 이 시간(초) 이상 걸린 작업만 알림 (실패는 항상 알림)
SECRET_FILE = ".local_secrets.json"          # 웹훅 URL은 GitHub에 올라갈 수 있는 tts_settings.json 대신 여기(.gitignore 대상)에 저장
try:
    _SEC = json.load(open(SECRET_FILE, encoding="utf-8"))
except Exception:
    _SEC = {}
TTS_CFG.pop("discord_webhook", None)
if _SEC.get("discord_webhook") and not os.environ.get("DISCORD_WEBHOOK_URL"):
    os.environ["DISCORD_WEBHOOK_URL"] = _SEC["discord_webhook"]
for _sk, _ek in (("youtube_api_key", "YOUTUBE_API_KEY"), ("yt_refresh_token", "YT_REFRESH_TOKEN"), ("yt_client_id", "YT_CLIENT_ID"), ("yt_client_secret", "YT_CLIENT_SECRET")):
    if _SEC.get(_sk) and not os.environ.get(_ek):    # get_token.bat 이 저장한 값 (환경변수가 없을 때만)
        os.environ[_ek] = _SEC[_sk]
TTS_CFG.setdefault("drive_auto", False)    # 작업 후 구글 드라이브에 자동 업로드 (바뀐 파일만)
TTS_CFG.setdefault("drive_cats", ["thumbs", "subs", "audio", "images", "videos", "longform", "db"])
ENGINE_LABELS = {"auto": "Supertonic 우선, 실패하면 Edge 등 (기본)", "edge": "Edge 우선, 실패하면 Supertonic 등", "supertonic": "Supertonic만 (실패하면 중단)", "edge_only": "Edge만 (실패하면 중단)"}
ENGINE_ORDER = {"auto": "supertonic,edge,google,gtts", "edge": "edge,supertonic,google,gtts", "supertonic": "supertonic", "edge_only": "edge"}
CAP_LABELS = {"script": "대본 자막 (기본)", "highlight": "핵심 문구 표시 (예전 방식)", "srt": "SRT 파일만 (영상엔 자막 없음)", "both": "대본 자막 + SRT", "script_hl": "대본 자막 + 핵심 문구 둘 다 (핵심 문구는 이미지 위쪽)"}

def _gh_token():
    return os.environ.get("GITHUB_TOKEN", "").strip()

def _shared_settings_sync():
    """음성·자막 설정이 바뀌었으면 pipeline_settings.json(GitHub 자동 실행과 공유하는 설정)을 갱신하고 올릴 표시를 한다"""
    try:
        import pipeline_settings as _ps
        new = _ps.shared(TTS_CFG)
        try:
            old = json.load(open(_ps.FILE, encoding="utf-8"))
        except Exception:
            old = None
        if new != old:
            json.dump(new, open(_ps.FILE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
            st.session_state["gh_dirty"] = True
            st.session_state["ps_push"] = True
    except Exception:
        pass

def _gh_sync(push):
    """sync_db.py 로 GitHub DB와 병합 (push=True면 병합본을 GitHub에도 커밋). -> (성공, 출력)"""
    cmd = [sys.executable, "sync_db.py", "--repo", TTS_CFG["gh_repo"], "--apply", "--auto"] + (["--push"] if push else [])
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300,
                           env=dict(os.environ, PYTHONIOENCODING="utf-8"))
        return r.returncode == 0, (r.stdout + r.stderr).strip()
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"

if TTS_CFG.get("gh_auto") and _gh_token() and "gh_boot" not in st.session_state:   # UI를 열 때마다(새 세션) 먼저 GitHub DB를 가져와 병합
    with st.spinner("GitHub에서 DB를 가져와 병합하는 중..."):
        _ok_b, _out_b = _gh_sync(False)
    st.session_state["gh_boot"] = (_ok_b, _out_b)
    if not _ok_b:
        st.warning("GitHub DB 자동 가져오기 실패/보류: " + "\n".join(_out_b.splitlines()[-4:]))

def _code_check():
    """GitHub에 새 코드가 있는지 점검 (세션당 1번, 실패해도 조용히 넘어감). -> 안내 문구 또는 ''"""
    try:
        r = subprocess.run([sys.executable, "update_code.py", "--repo", TTS_CFG["gh_repo"], "--check", "--quiet"], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=20, env=dict(os.environ, PYTHONIOENCODING="utf-8"))
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""

if "code_chk" not in st.session_state and os.path.exists("update_code.py"):
    st.session_state["code_chk"] = _code_check()

def _lf_extra_files():
    """롱폼 DB와 함께 올릴 파일들 (고친 대본, 채널 표시 설정/이미지, 내 스타일 지침)"""
    out = []
    for f_ in ("longform_scripts.json", "longform_brand.json", "channel_avatar.png", "style_profile.json", "deep_db.json"):
        if os.path.exists(f_):
            out += ["--file", f_]
    return out

def _hist_sync():
    """run_history.jsonl 을 GitHub와 양방향 병합 (+요약 md/csv 갱신). -> (성공, 한 줄)"""
    try:
        r = subprocess.run([sys.executable, "history.py", "sync", "--repo", TTS_CFG["gh_repo"]], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=180, env=dict(os.environ, PYTHONIOENCODING="utf-8"))
        return r.returncode == 0, ((r.stdout + r.stderr).strip().splitlines() or [""])[-1]
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"

if TTS_CFG.get("gh_auto") and _gh_token() and "hist_boot" not in st.session_state and os.path.exists("history.py"):
    st.session_state["hist_boot"] = _hist_sync()

def tts_env():
    return {f"SUPERTONIC_VOICE_{LANG.upper()}": TTS_CFG["voice"], "TTS_RATE": f"{int(TTS_CFG['rate']):+d}%",
            "TTS_EDGE_VOICE": TTS_CFG["edge"], "CAPTION_MODE": TTS_CFG["caption"],
            "TTS_ORDER": ENGINE_ORDER.get(TTS_CFG["engine"], ENGINE_ORDER["auto"]),
            "SCENE_COUNT": str(int(TTS_CFG.get("scenes") or 10)),
            "CROSS_CHECK": "1" if TTS_CFG.get("cross") else "0",
            "IMAGE_CHECK": "1" if TTS_CFG.get("imgchk") else "0",
            "IMG_OLLAMA": "1" if TTS_CFG.get("imgchk_ollama") else "0",
            "IMG_OLLAMA_ALL": "1" if TTS_CFG.get("imgchk_ollama_all") else "0",
            "IMG_OLLAMA_MODEL": str(TTS_CFG.get("imgchk_model") or "qwen2.5vl:3b"),
            "IMG_CLIP_THR": str(TTS_CFG.get("imgchk_thr") or 0.22),
            "IMG_RETRY": str(int(TTS_CFG.get("imgchk_retry") if TTS_CFG.get("imgchk_retry") is not None else 2)),
            **({"SCRIPT_TARGET_SEC": str(int(TTS_CFG["target_sec"]))} if int(TTS_CFG.get("target_sec") or 0) > 0 else {}),
            **({"YT_THUMBNAIL": "on"} if TTS_CFG.get("yt_thumb") else {}),
            **({"TV_FX": "on"} if TTS_CFG.get("tv_fx") else {}),
            **{ev_: str(TTS_CFG[k_]) for k_, ev_ in (("font_sub", "FONT_SUB"), ("font_title", "FONT_TITLE"), ("font_ovl", "FONT_OVL")) if TTS_CFG.get(k_)}}

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
    if ok and args and args[0] not in ("sync_db.py", "gh_push.py", "drive_sync.py", "list_channel_videos.py", "tts_preview.py", "status_report.py", "notify_discord.py", "notify_longform.py", "update_code.py", "history.py", "cuts.py"):
        st.session_state["gh_dirty"] = True   # 이 실행이 끝나면 아래에서 자동 동기화
    sec = time.time() - t0
    _skip = ("sync_db.py", "gh_push.py", "drive_sync.py", "list_channel_videos.py", "tts_preview.py", "status_report.py", "notify_discord.py", "notify_longform.py", "history.py", "update_code.py")
    if args and args[0] not in _skip:
        try:
            import history as _H
            _kind = {"build_longform.py": "롱폼"}.get(args[0], args[0].replace(".py", ""))
            _title = " ".join(args)[:150]
            _H.add(_kind, _title, "success" if ok else "failed", sec, "" if ok else "\n".join(buf[-3:]))
            st.session_state["gh_dirty"] = True
            if TTS_CFG.get("discord_notify") and os.environ.get("DISCORD_WEBHOOK_URL") and (not ok or sec >= float(TTS_CFG.get("discord_min_secs") or 60)):
                _H.notify(f"{'✅ 완료' if ok else '❌ 실패'} [{_H.CHANNEL} PC] {_title[:100]} — {int(sec // 60)}분 {int(sec % 60)}초" + ("" if ok else "\n" + "\n".join(buf[-3:])[:600]))
        except Exception:
            pass
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
start = c2.number_input("start_index", 0, 9999, 0 if EN else 0, help="이 번호 이상인 소재부터 처리. 그보다 작은 번호(옛 소재)는 건너뜀")
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
    if st.session_state.get("code_chk"):
        st.warning("🔄 " + st.session_state["code_chk"] + " → '☁️ 동기화' 탭에서 코드 업데이트")
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

# ================= 화면 구성: 단계 탭 (각 단계 안에 '실행'과 '보기·수정'을 함께 둠) =================
def _sync_line():
    ps = []
    ps.append("GitHub 자동동기화 " + ("켜짐" if (TTS_CFG.get("gh_auto") and _gh_token()) else ("꺼짐 (토큰 없음)" if TTS_CFG.get("gh_auto") else "꺼짐")))
    last = st.session_state.get("gh_last")
    if last:
        ps.append(("✅ " if last[0] else "⚠️ ") + f"마지막 {last[1]} {last[2][:60]}")
    ps.append("드라이브 자동 " + ("켜짐" if (TTS_CFG.get("drive_auto") and os.path.exists("token_drive.json")) else "꺼짐"))
    ps.append("디스코드 알림 " + ("켜짐" if (TTS_CFG.get("discord_notify") and os.environ.get("DISCORD_WEBHOOK_URL")) else "꺼짐"))
    if st.session_state.get("code_chk"):
        ps.append("🔄 " + st.session_state["code_chk"])
    return "☁️ " + " · ".join(ps) + "  — 자세한 설정은 '⚙ 관리·동기화' 탭"

def _style_panel():
    """내 성향·스타일 지침 (style_profile.json) - 대본·롱폼·소재 생성 프롬프트에 붙는다"""
    import style_profile as _SP
    _P = _SP.load()
    with st.expander("🎯 내 스타일 · 성향 반영 (대본·롱폼·소재 만들 때 AI에게 전달)", expanded=False):
        st.caption("'어떻게 말할지'에 대한 내 기준입니다. 켠 항목이 대본(쇼츠·롱폼)과 새 소재 만들기 프롬프트에 붙습니다. 사실 정확성이 항상 우선이며, 이미 만든 대본은 바뀌지 않으니 '대본부터 다시'로 다시 만드세요. 저장하면 GitHub 자동 동기화로 GitHub Actions에도 같이 적용됩니다.")
        _sel = []
        _cols = st.columns(2)
        for _i, (_k, _v) in enumerate(_SP.RULES.items()):
            if _cols[_i % 2].checkbox(_v[0], _k in _P["rules"], key=f"sp_r_{_k}", help=_v[1]):
                _sel.append(_k)
        _P["rules"] = _sel
        _P["custom"] = st.text_area("추가 지침 (내 말로)", _P.get("custom", ""), height=80, key="sp_custom",
                                    placeholder="예: 숫자는 단위와 기준 연도를 같이 말하기 / 문장은 15자~40자 사이로")
        _P["avoid"] = st.text_input("쓰지 말 표현·주제 (쉼표로 구분)", _P.get("avoid", ""), key="sp_avoid", placeholder="예: 충격, 소름, 역대급")
        st.markdown("**새 소재 만들 때 우선할 분야** (켠 분야를 우선하되 다양성은 유지)")
        _ta = []
        _c2 = st.columns(4)
        for _i, (_k, _v) in enumerate(_SP.TOPIC_AREAS.items()):
            if _c2[_i % 4].checkbox(_v[0], _k in _P.get("topic_areas", []), key=f"sp_t_{_k}"):
                _ta.append(_k)
        _P["topic_areas"] = _ta
        _P["topic_custom"] = st.text_input("소재 선호 추가 설명", _P.get("topic_custom", ""), key="sp_tcustom", placeholder="예: 제도나 시스템 때문에 생긴 생활 습관 위주")
        if st.button("💾 스타일 저장", key="sp_save", type="primary"):
            _SP.save(_P)
            st.session_state["gh_dirty"] = True
            st.success("저장했습니다. 다음에 만드는 대본/소재부터 적용됩니다.")
        st.text_area("AI에게 실제로 전달되는 문장 (대본)", _SP.block("script", _P) or "(없음)", height=170, disabled=True, key="sp_prev")

st.caption(_sync_line())
TD, TH, T1, T2, T3, T4, T5, T6, TL, TS = st.tabs(["📊 현황", "🏠 시작·가이드", "1 소재", "2 대본", "3 이미지", "4 음성", "5 영상", "6 업로드", "🎞 롱폼", "⚙ 관리·동기화"])
with T1:
    st.caption("새 소재를 만들고 승인/제외합니다. 직접 소재를 넣거나, 상태·폐기·업로드 기록도 여기서 봅니다.")
    T1a, T1b, T1c, T1d = st.tabs(["⚙ 만들기·승인", "➕ 직접 추가", "🗂 상태·폐기·업로드 기록", "📈 트렌드·벤치마크"])
with T2:
    st.caption("대본을 만들고 읽어 보며 고칩니다. 제목·핵심 문구·이미지 검색어는 review.txt에서도 고칠 수 있습니다.")
    T2a, T2b, T2c = st.tabs(["⚙ 대본 만들기", "📝 대본 보기·수정", "📄 review.txt"])
with T3:
    st.caption("장면 이미지를 받고(자동 검증 옵션), 장면별로 확인하거나 검색어·내 사진으로 교체합니다.")
    T3a, T3b = st.tabs(["⚙ 이미지 받기", "🖼 검수·교체"])
with T4:
    st.caption("목소리·속도·자막 방식을 정하고 음성을 만들어 들어봅니다. 음성 설정은 음성을 만들기 전에 정하세요.")
    T4a, T4b = st.tabs(["🎙 음성·자막 설정", "⚙ 음성 만들기·듣기"])
with T5:
    st.caption("영상과 썸네일을 만들고, 만든 영상 확인·문구 넣기·편집 포인트를 다룹니다.")
    T5a, T5b, T5c, T5d = st.tabs(["⚙ 렌더링", "🎬 만든 영상", "✍ 문구 넣기", "🎞 편집 포인트"])
with T6:
    st.caption("비공개로 업로드하고, 제목/설명을 복사하거나 디스코드로 보냅니다.")
    T6a, T6b = st.tabs(["⚙ 업로드", "📋 제목·설명 (디스코드·유튜브)"])
with TD:
    try:
        import dashboard as _dash
        from common import load_db as _ldb
        _dash.render(st, _ldb(), int(start), int(os.environ.get("DAILY_MAX", "20") or 20), TTS_CFG.get("gh_repo", ""))
    except Exception as _e:
        st.error(f"현황 화면을 그리지 못했습니다: {_e}")

with TH:
    H_main = st.container()
    H_auto = st.expander("⚡ 자동 진행 (확인 없이 이어서 실행)", expanded=False)

with T4a:
    t1, t2, t3 = st.columns(3)
    TTS_CFG["voice"] = t1.selectbox("Supertonic 목소리 (F=여성, M=남성)", ST_VOICES, ST_VOICES.index(TTS_CFG["voice"]) if TTS_CFG["voice"] in ST_VOICES else 0,
                                    help="기본 음성 엔진. 아래 '미리듣기'로 들어보고 고르세요")
    TTS_CFG["rate"] = t2.slider("속도 (%)", -20, 30, int(TTS_CFG["rate"]), 1,
                                help="0=기본. 느리게는 -, 빠르게는 +. 빠를수록 영상이 짧아집니다")
    if int(TTS_CFG["rate"]) > 10:
        st.caption("⚠️ 속도를 +10% 넘게 올리면 Supertonic 음성의 문장 끝이 잘리거나 덜 발음될 수 있습니다 (내부적으로 1.2배 상한을 둡니다). 0~+5% 권장.")
    TTS_CFG["edge"] = t3.selectbox("Edge 음성", EDGE_VOICES, EDGE_VOICES.index(TTS_CFG["edge"]) if TTS_CFG["edge"] in EDGE_VOICES else 0)
    _ek = list(ENGINE_LABELS)
    TTS_CFG["engine"] = st.radio("음성 엔진", _ek, _ek.index(TTS_CFG["engine"]) if TTS_CFG["engine"] in _ek else 0, horizontal=True,
                                 format_func=lambda k: ENGINE_LABELS[k],
                                 help="Edge는 마이크로소프트 서버를 쓰므로 인터넷이 필요하고, 막히면(403 등) 실패합니다. 안 되면 pip install -U edge-tts 후 다시 시도하세요")
    _ck = list(CAP_LABELS)
    TTS_CFG["caption"] = st.radio("자막 방식", _ck, _ck.index(TTS_CFG["caption"]) if TTS_CFG["caption"] in _ck else 0, horizontal=True,
                                  format_func=lambda k: CAP_LABELS[k],
                                  help="대본 자막: 음성 속도에 맞춰 대본을 보여줌 / 핵심 문구: 대본 중 강조 문구만 (review.txt의 핵심 줄 사용) / SRT만: 영상엔 자막 없이 .srt 파일만 (유튜브 스튜디오에서 올리면 시청자가 켜고 끌 수 있음). .srt 파일은 어떤 방식이든 같이 만들어집니다. 롱폼은 핵심 문구 방식이 없어 대본 자막으로 나옵니다. 둘 다: 아래엔 대본 자막, 이미지 위쪽엔 핵심 문구(쇼츠만)")
    TTS_CFG["tv_fx"] = st.checkbox("📺 영상 처음·끝에 옛날 TV 켜짐/꺼짐 효과", bool(TTS_CFG.get("tv_fx")), key="tv_fx_cb",
                                   help="시작: 가운데 빛줄이 위아래로 열리며 켜짐(0.5초) / 끝: 줄로 닫혔다 점으로 꺼짐(0.55초). 음성은 그대로. 이미 만든 영상엔 redo 후 5단계 렌더링으로 적용")
    import fonts as _FN0
    _fa0 = _FN0.available()
    _fo = ["", *_fa0]
    _fc1, _fc2, _fc3 = st.columns(3)
    for _col, _k, _lb, _hp in ((_fc1, "font_sub", "자막 글씨체", "영상 아래 자막(대본·핵심 문구 모두)"),
                               (_fc2, "font_title", "영상 상단 제목 글씨체", "영상 맨 위 제목·채널명 영역"),
                               (_fc3, "font_ovl", "화면 문구 기본 글씨체", "편집 탭 '문구'의 기본값 (문구마다 따로 바꿀 수도 있음)")):
        TTS_CFG[_k] = _col.selectbox(_lb, _fo, _fo.index(TTS_CFG.get(_k) or "") if (TTS_CFG.get(_k) or "") in _fo else 0, key=_k + "_sel",
                                     format_func=lambda x: "기본 (맑은 고딕/Noto)" if not x else _fa0[x], help=_hp + ". 바꾼 뒤엔 이미 만든 영상은 redo 후 5단계 렌더링으로 적용")
    with st.expander("🔤 글씨체 미리보기"):
        from PIL import Image as _PI, ImageDraw as _PD, ImageFont as _PF
        _smp = "세계 문화 상식 1g에 금보다 비쌌다" if not EN else "World Facts 1g costs more than gold"
        if not _fa0:
            st.warning("글씨체 파일(fonts 폴더)이 아직 없습니다. 코드 업데이트(update_code)를 한 번 더 실행하면 받아집니다.")
            _fa0 = {}
        _im = _PI.new("RGB", (900, max(1, 64 * len(_fa0))), "white"); _d = _PD.Draw(_im)
        for _i, (_k, _lb) in enumerate(_fa0.items()):
            try:
                _d.text((10, _i * 64 + 6), _smp, font=_PF.truetype(_FN0.path(_k), 40), fill="black")
                _d.text((690, _i * 64 + 20), _lb.split(" — ")[0], font=_PF.truetype(_FN0.path("dohyeon") or _FN0.path(_k), 24), fill=(140, 140, 140))
            except Exception:
                pass
        if _fa0:
            st.image(_im)
    json.dump(TTS_CFG, open(TTS_FILE, "w", encoding="utf-8"), ensure_ascii=False)
    st.caption("☁️ 목소리·속도·음성 엔진·자막 방식은 바뀔 때마다 GitHub에도 자동으로 올라가 자동 실행(Actions)에도 똑같이 적용됩니다 (GitHub 자동동기화가 켜져 있을 때). 워크플로를 수동 실행하며 입력한 값이 있으면 그 값이 우선입니다.")
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


def _title_editor(_kp):
    """영상 맨 위 두 줄 제목(글자)과 색을 고친다. 영상 만들기 전에도, 만든 뒤에도 쓸 수 있다 (만든 뒤엔 redo + 5단계 렌더링 필요)."""
    _vd0 = _ld()
    _vn = sorted([i for i, it in enumerate(_vd0) if (it.get("video_path_v6") or it.get("narration")) and it.get("status") != "rejected"], reverse=True)
    if not _vn:
        st.info("대본이 있는 소재가 없습니다.")
        return
    _vs = st.selectbox("소재 번호", _vn, key=f"{_kp}vt_sel", format_func=lambda i: f"{i} {_vd0[i].get('country', '')} - {str(_vd0[i].get('title_line1', '') or _vd0[i].get('topic', ''))[:30]}")
    it = _vd0[_vs]
    _vo = dict(it.get("title_opts") or {})
    _tt1 = st.text_input("1줄 제목", str(it.get("title_line1") or it.get("topic") or ""), key=f"{_kp}vt_t1_{_vs}")
    _tt2 = st.text_input("2줄 제목", str(it.get("title_line2") or ""), key=f"{_kp}vt_t2_{_vs}")
    _vc1, _vc2 = st.columns(2)
    _d1 = _vc1.color_picker("1줄 기본색", _vo.get("color1") or "#000000", key=f"{_kp}vt_c1_{_vs}")
    _d2 = _vc2.color_picker("2줄 기본색", _vo.get("color2") or "#C800FF", key=f"{_kp}vt_c2_{_vs}")
    _vres = {}
    for _ln, (_txt, _dc) in enumerate(((_tt1, _d1), (_tt2, _d2)), 1):
        _wd = str(_txt).split()
        if not _wd:
            continue
        st.caption(f"{_ln}줄 단어별 색 (기본색과 다르게 고른 단어만 적용)")
        _pv = _vo.get(f"colors{_ln}") or {}
        _cc = st.columns(min(len(_wd), 6))
        _pk = {}
        for _k, _w in enumerate(_wd):
            _c = _cc[_k % len(_cc)].color_picker(_w, _pv.get(str(_k), _dc), key=f"{_kp}vt_w{_ln}_{_vs}_{_k}")
            if _c.lower() != _dc.lower():
                _pk[str(_k)] = _c
        _vres[f"colors{_ln}"] = _pk
    _vb1, _vb2 = st.columns(2)
    if _vb1.button("저장", key=f"{_kp}vt_save_{_vs}", type="primary"):
        _dm = _ld()
        _dm[_vs]["title_line1"], _dm[_vs]["title_line2"] = _tt1.strip(), _tt2.strip()
        if _d1.lower() == "#000000" and _d2.lower() == "#c800ff" and not any(_vres.values()):
            _dm[_vs].pop("title_opts", None)
        else:
            _dm[_vs]["title_opts"] = {"color1": _d1, "color2": _d2, **_vres}
        _sd(_dm)
        st.success("저장했습니다. " + ("이미 만든 영상이라 redo에 번호를 넣고 5단계 렌더링을 해야 영상에 반영됩니다." if it.get("video_path_v6") else "아직 영상 전이라 다음 렌더링에 그대로 반영됩니다."))
    if _vb2.button("제목 색만 기본으로 되돌리기", key=f"{_kp}vt_reset_{_vs}"):
        _dm = _ld(); _dm[_vs].pop("title_opts", None); _sd(_dm); st.rerun()


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
    if redo.strip() and not redo_script:            # redo 칸에 넣은 번호(이미 영상이 있는 소재)도 음성·렌더링 목록에 포함
        _dbr = _ld()
        for _t in re.findall(r"\d+", redo.replace("!", "")):
            if int(_t) < len(_dbr) and int(_t) not in out and _dbr[int(_t)].get("narration"):
                out.append(int(_t))
        out.sort()
    return out

def _targets():
    return _ready_all()[:int(count)]

def _img_state(i, f):
    n = len(list(_vd(HERE, i, f).glob("scene_*.png"))) if _vd(HERE, i, f).exists() else 0
    return n, bool(f.get("image_queries_done"))


def _ext_panel(pfx, default_idx):
    """외부 AI(ChatGPT/Gemini/Perplexity 등)에서 작성·검증한 대본을 붙여넣어 쓰는 패널 (+ 외부 AI에 줄 요청문 만들기)"""
    import ext_script as _E
    with st.expander("📥 외부 AI로 대본 작성·검증 → 붙여넣기 (Groq 토큰 절약)", expanded=False):
        st.caption("① 소재 번호를 넣고 '요청문'을 복사해 외부 AI에 붙여 넣기 → ② 답변(### 번호 + 대본)을 아래에 붙여넣기 → ③ 저장. "
                   "붙여넣은 대본은 '직접 검증함'으로 표시되어 교차검증을 건너뛰고, 쇼츠는 제목·핵심 문구·이미지 검색어만 자동으로 만듭니다.")
        _k = st.radio("대상", ["쇼츠 대본", "롱폼 챕터 대본"], index=default_idx, horizontal=True, key=pfx + "kind")
        _long = _k.startswith("롱폼")
        _ids_txt = st.text_input("소재 번호 (예: 117,118 / 110-115)", key=pfx + "ids")
        try:
            from build_longform import parse_indexes as _pi
            _ids = _pi(_ids_txt) if _ids_txt.strip() else []
        except Exception:
            _ids = []
        _dbx = _ld()
        _ids = [i_ for i_ in _ids if 0 <= i_ < len(_dbx)]
        if _long:
            import longform_script as _LS
            _lo, _hi = _LS.LEN_RANGE
            _unit_en = EN
        else:
            _t = int(TTS_CFG.get("target_sec") or 0); _m = 1 + int(TTS_CFG.get("rate") or 0) / 100
            if EN:
                _lo, _hi = (round(_t * 2.2 * _m * 0.88), round(_t * 2.2 * _m * 1.12)) if _t > 0 else (90, 115)
            else:
                _lo, _hi = (int(_t * 7.04 * _m / 10) * 10, int(_t * 8.96 * _m / 10 + 1) * 10) if _t > 0 else (350, 500)
            _unit_en = EN
        _mode = st.radio("요청문 종류", ["새로 작성 + 검증", "내 기존 대본 검증·수정"], horizontal=True, key=pfx + "mode")
        if _ids:
            import ko_text as _KT2
            _items = []
            for i_ in _ids:
                f_ = _dbx[i_]
                cur_ = ((_LS.get_rec(i_).get("narration") if _long else "") or f_.get("narration", "")) if _mode.startswith("내") else ""
                try:
                    import topic_ko as _TK
                    tp_ = _TK.shown(i_, f_) if not EN else f_.get("topic", "")
                except Exception:
                    tp_ = f_.get("topic", "")
                _items.append((i_, (f_.get("country", "") if EN else _KT2.disp_country(f_.get("country", ""))), tp_, cur_))
            _req = _E.build_request(_items, "long" if _long else "short", "verify" if _mode.startswith("내") else "new", _lo, _hi, en=EN)
            st.code(_req, language="text")
            st.download_button("요청문 파일로 받기", _req.encode("utf-8"), f"request_{'long' if _long else 'short'}.txt", key=pfx + "dl")
        else:
            st.caption("소재 번호를 넣으면 요청문이 만들어집니다.")
        _paste = st.text_area("외부 AI 답변 붙여넣기 (소재마다 '### 번호' 다음 줄에 대본)", height=260, key=pfx + "paste")
        _redo_ok = False
        if not _long:
            _redo_ok = st.checkbox("이미 영상이 있는 소재도 저장 (영상·음성 기록을 지우고 새 대본으로 다시 만들 수 있게 함, 유튜브에 올린 기록은 유지)", True, key=pfx + "redo")
        _blocks = _E.parse_blocks(_paste) if _paste.strip() else {}
        _ok = {}
        if _blocks:
            rows_ = []
            for i_, t_ in sorted(_blocks.items()):
                if not (0 <= i_ < len(_dbx)):
                    rows_.append({"번호": i_, "나라": "-", "길이": str(len(t_)), "상태": "DB에 없는 번호 - 건너뜀"})
                    continue
                n_, pr_ = _E.check(t_, _lo, _hi, en=_unit_en)
                st_ = _dbx[i_].get("status", "")
                blocked_ = (not _long) and st_ in ("video_done",) and not _redo_ok
                rows_.append({"번호": i_, "나라": _dbx[i_].get("country", ""), "길이": f"{n_}{'단어' if _unit_en else '자'} (기준 {_lo}~{_hi})",
                              "상태": ("이미 영상 있음 - 건너뜀(위 체크를 켜면 저장)" if blocked_ else ("저장 가능 (영상 다시 만들기 필요)" if ((not _long) and st_ == "video_done") else "저장 가능")) + ((" / 주의: " + ", ".join(pr_)) if pr_ else "")})
                if not blocked_:
                    _ok[i_] = t_
            st.dataframe(rows_, hide_index=True, use_container_width=True)
        _rs = False
        if _long:
            _rs = st.checkbox("저장 후 키워드·비교·요약·영상 검색어를 이 대본에 맞게 AI로 다시 만들기 (챕터당 약 3~4천 토큰)", True, key=pfx + "rs")
        _rm = False
        if not _long:
            _rm = st.checkbox("저장 후 주제·훅/본문/반전·제목·핵심 문구·이미지 검색어를 새 대본에 맞게 AI로 다시 만들기 (소재당 AI 호출 3~4회, 약 1~2천 토큰)", True, key=pfx + "rm",
                              help="대본만 바꾸면 제목·핵심 문구·훅(유튜브 설명)·주제가 옛 내용으로 남아 영상과 어긋날 수 있습니다. 켜 두면 새 대본 기준으로 다시 만듭니다. GROQ_API_KEY가 필요합니다")
        if st.button(f"💾 붙여넣은 대본 저장 ({len(_ok)}개)", key=pfx + "save", type="primary", disabled=not _ok):
            if _long:
                import longform_script as _LS2
                for i_, t_ in _ok.items():
                    _LS2.update_rec(i_, {"narration": t_, "verified_by": "manual"})
                st.success(f"롱폼 대본 {len(_ok)}개 저장·잠금: {', '.join(map(str, _ok))}")
                if _rs:
                    _s = ",".join(str(i_) for i_ in _ok)
                    run("build_longform.py", "--mode", "manual", "--indexes", _s, "--min", "1", "--start", "0", "--plan-only", "--only", _s, "--resync")
            else:
                _vd = [i_ for i_ in _ok if _dbx[i_].get("status") == "video_done" or _dbx[i_].get("video_path_v6")]
                if _vd:
                    subprocess.run([sys.executable, "redo_videos.py", "--indexes", ",".join(map(str, _vd))], capture_output=True, text=True,
                                   encoding="utf-8", errors="replace", env=dict(os.environ, PYTHONIOENCODING="utf-8"))
                lines_ = []
                for i_, t_ in _ok.items():
                    lines_.append(f"=== [{i_}] ===\n" + "\n".join(f"대본[{n_}]: {x_}" for n_, x_ in enumerate(_E.sentences(t_), 1)))
                with open("review_tmp_edit.txt", "w", encoding="utf-8") as f_:
                    f_.write("\n\n".join(lines_) + "\n")
                r_ = subprocess.run([sys.executable, "apply_review.py", "--file", "review_tmp_edit.txt"], capture_output=True, text=True,
                                    encoding="utf-8", errors="replace", env=dict(os.environ, PYTHONIOENCODING="utf-8"))
                try:
                    os.remove("review_tmp_edit.txt")
                except OSError:
                    pass
                subprocess.run([sys.executable, "promote_ready.py", "--start", "0"], capture_output=True, text=True, encoding="utf-8", errors="replace",
                               env=dict(os.environ, PYTHONIOENCODING="utf-8"))
                _d2 = _ld()
                for i_ in _ok:
                    if 0 <= i_ < len(_d2):
                        _d2[i_].update({"cross_checked": True, "cross_verdict": "manual", "cross_notes": ["직접 검증한 대본 (외부 AI)"], "cross_flags": []})
                _sd(_d2)
                st.session_state["gh_dirty"] = True
                st.success(f"쇼츠 대본 {len(_ok)}개 저장: {', '.join(map(str, _ok))} → 2단계 '대본 만들기' 또는 5단계에서 제목·핵심 문구·이미지 검색어가 대본 기준으로 채워집니다.")
                st.code((r_.stdout + r_.stderr).strip()[-600:] or "(apply_review 출력 없음)")
                if _rm:
                    run("resync_meta.py", "--indexes", ",".join(map(str, _ok)))


with T1a:
    st.caption("🎯 새 소재의 선호 분야는 '2 대본 › 대본 만들기'의 '내 스타일'에서 정합니다.")
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

with T2a:
    _ext_panel('xs_', 0)
    _style_panel()
    TTS_CFG["target_sec"] = st.slider("목표 대본 길이 (초, 0 = 기본)", 0, 170, int(TTS_CFG.get("target_sec") or 0), 1, key="target_sec",
                                      help="새로 만드는 대본의 분량을 음성 길이 기준으로 맞춥니다. 0이면 기본 분량(한국어 350~500자 / 영어 90~115단어). 음성 속도 설정도 반영됩니다. 이미 만든 대본은 안 바뀌니 '대본부터 다시'로 다시 만드세요")
    if int(TTS_CFG["target_sec"]) > 0:
        _t = int(TTS_CFG["target_sec"]); _m = 1 + int(TTS_CFG["rate"]) / 100
        st.caption(f"목표 {_t}초 → " + (f"약 {int(_t * 7.04 * _m / 10) * 10}~{int(_t * 8.96 * _m / 10 + 1) * 10}자 (한국어)" if not EN
                                       else f"약 {round(_t * 2.2 * _m * 0.88)}~{round(_t * 2.2 * _m * 1.12)}단어 (영어)") + " · 실제 음성 길이는 4단계 후 확인")
        if _t > 60:
            st.caption("ℹ️ 유튜브 쇼츠는 최대 3분(세로 영상)까지 쇼츠로 인정됩니다. 60초를 넘기면 시청 유지율이 떨어질 수 있으니 내용이 촘촘할 때만 쓰고, 장면(이미지) 수도 늘리세요 (5초마다 1장 기준).")
    TTS_CFG["scenes"] = st.select_slider("장면(이미지) 수", options=list(range(6, 31, 2)), value=int(TTS_CFG.get("scenes") or 10), key="scene_n",
                                         help="새로 만드는 소재의 이미지 장수입니다. 길이 50초면 10장 ≈ 5초마다 전환. 많을수록 이미지 받기·검색어 생성이 늘어납니다. 이미 만든 소재는 원래 장수(6장 등)를 유지하고, 대본부터 다시 만들면 새 장수가 적용됩니다")
    TTS_CFG["cross"] = st.checkbox("🔍 대본 교차검증 (쇼츠 대본 + 롱폼 확장 대본, 위키백과 근거 + 다른 모델이 문장별 검증)", bool(TTS_CFG.get("cross")), key="cross_chk",
                                   help="대본/제목/이미지 검색어를 만들 때 자동으로 검증합니다. 모순/근거 없는 문장은 먼저 고쳐 쓰고(바로잡기·한정어 추가·삭제) 다시 검증하며, 원문은 narration_original에 보관합니다. 2번 고쳐도 모순이 남거나 문장 절반 이상이 근거 없음이면 소재를 폐기(rejected)합니다. Groq 호출이 소재당 1~6회 늘어납니다. 오류를 줄일 뿐 100% 보장은 아니니 review.txt의 (교차검증 메모)는 직접 확인하세요. GitHub Actions에는 적용되지 않습니다(로컬 실행 전용)")
    json.dump(TTS_CFG, open(TTS_FILE, "w", encoding="utf-8"), ensure_ascii=False)
    st.caption("🖼️ 이미지 자동 검증: " + ("**켜짐** (이미지를 받을 때 검색어와 맞는지 확인하고 불일치는 교체)" if TTS_CFG.get("imgchk") else "꺼짐") + " — 설정은 '이미지' 탭에서")
    auto_ok = st.checkbox("승인 안 된 소재는 count개까지 자동 승인하고 진행", True, key="auto_ok2",
                          help="끄면 1단계에서 승인한 소재(verified)만 대본을 만듭니다")
    if st.button("대본 만들기 (제목/이미지 검색어 포함, review.txt 생성)", key="st2_go"):
        chain(script_steps(auto_ok))
    st.caption("끝나면 아래 review.txt 또는 '📝 대본 전체 보기/수정' 탭에서 대본·제목을 확인하고 저장하세요. 대본이 마음에 안 들면 redo 칸에 번호! 를 넣어 다시 만들 수 있습니다.")

with T3a:
    tg = _targets()
    st.caption("대본이 끝난 소재 중 앞에서 count개: " + (", ".join(map(str, tg)) or "없음") + "   (이미지 검색어도 이때 대본 기준으로 만들어집니다)")
    if st.button("이미지 받기 (검색어 생성 + 장면 이미지)", key="st3_go", help="음성보다 먼저 이미지를 받아 확인할 수 있습니다. 이미 받은 장면은 건드리지 않습니다"):
        chain(IMAGE_STEP)
    st.caption("끝나면 '🖼 이미지 검수/교체' 탭에서 장면별로 확인하고, 마음에 안 들면 검색어를 바꿔 다시 받거나 내 사진으로 교체하세요.")
    with st.expander("🎨 AI 이미지(콘티) 프롬프트 만들기 — 테스트 기능"):
        st.caption("핵심 컷의 이미지 생성용 프롬프트만 만듭니다. 이미지는 Krea·Playground 같은 곳에서 직접 만들어 컷 이름(예: 117_01.png)으로 my_images 폴더에 넣으면 자동 검색 사진보다 먼저 쓰입니다. 사실 확인이 필요한 실제 장소·물건 컷은 사진이 낫고, 상징적인 컷에 쓰기를 권합니다.")
        if st.checkbox("이 기능 사용", False, key="aip_on"):
            _a1, _a2 = st.columns(2)
            _aip_idx = _a1.text_input("소재 번호 (비우면 렌더링 대기 소재 전부)", "", key="aip_idx", help="예: 117,118 또는 117-120")
            _aip_cuts = _a2.text_input("프롬프트를 만들 컷 번호", "1", key="aip_cuts", help="기본 1 (첫 장면). 예: 1,4")
            _aip_style = st.text_area("화풍 (프롬프트 뒤에 붙음)", "clean editorial illustration, soft warm colors, simple composition, vertical 9:16, no text, no letters, no logos, no watermark, no recognizable real people", key="aip_style", height=80)
            _aip_dc = st.checkbox("디스코드로도 보내기 (길게 눌러 복사)", False, key="aip_dc")
            if st.button("프롬프트 만들기", key="aip_go"):
                _aa = ["--cuts", _aip_cuts.strip() or "1", "--style", _aip_style.strip()]
                _aa += ["--indexes", _aip_idx.strip()] if _aip_idx.strip() else ["--pending"]
                if _aip_dc:
                    _aa.append("--discord")
                run("ai_prompts.py", *_aa)
            if os.path.exists("ai_prompts.md"):
                with st.expander("만들어 둔 프롬프트 (ai_prompts.md)"):
                    st.markdown(open("ai_prompts.md", encoding="utf-8").read())

def _audio_ok(f):
    ap_ = f.get("audio_path_v2")
    return bool(f.get("status_tts_v2") == "done" and ap_ and os.path.exists(ap_))

with T4b:
    dv = _ld()
    allv = _ready_all()
    st.caption("대본이 끝난 소재의 음성만 따로 만듭니다 (영상은 안 만듦). 목소리/속도/엔진은 위 '🎙 음성 · 자막 설정' 패널에서 정합니다. 대본을 고치면 음성은 지워지니 대본 확정 후에 만드세요.")
    pickv = st.multiselect("음성 만들 소재", allv, default=([int(x) for x in re.findall(r"\d+", redo.replace("!", "")) if int(x) in allv] if (redo.strip() and not redo_script) else allv[:int(count)]), key=f"vo_pick_{redo}_{int(start)}_{int(count)}_{len(allv)}",
                           format_func=lambda i: f"{i} {dv[i].get('country', '')} - {dv[i].get('topic', '')}" + ("  [음성 있음]" if _audio_ok(dv[i]) else ""))
    skip_done = st.checkbox("이미 만든 음성은 건너뛰기", True, key="vo_skip", help="끄면 선택한 소재의 음성을 현재 목소리/속도로 다시 만듭니다")
    if st.button("음성 만들기", key="vo_go", disabled=not pickv):
        steps = list(pre)
        for i in pickv:
            if skip_done and _audio_ok(dv[i]) and not (redo.strip() and not redo_script and str(i) in re.findall(r"\d+", redo)):
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

with T5a:
    d4 = _ld()
    allr = _ready_all()
    _rn = []
    if redo.strip() and not redo_script:               # redo 칸 번호는 start_index와 상관없이 목록에 넣고 기본 선택한다
        for _t in re.findall(r"\d+", redo.replace("!", "")):
            if int(_t) < len(d4) and int(_t) not in _rn:
                _rn.append(int(_t))
        allr = sorted(set(allr) | set(_rn))
    st.caption(f"렌더링 대기 {len(allr)}개 (start_index {int(start)} 이상, 번호순). 아래에서 만들 소재를 직접 고르세요. 기본은 앞에서 count개입니다." + (f" redo 번호 {_rn}는 자동 포함됩니다." if _rn else ""))
    pick4 = st.multiselect("렌더링할 소재", allr, default=(_rn or allr[:int(count)]), key=f"rd_pick_{int(start)}_{int(count)}_{len(allr)}_{'-'.join(map(str, _rn))}",
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

with T6a:
    _yth = st.checkbox("썸네일도 같이 올리기 (업로드 전에 없는 썸네일은 만듦)", bool(TTS_CFG.get("yt_thumb")), key="up_thumb",
                       help="토큰에 youtube.force-ssl 권한이 있어야 합니다 (get_refresh_token.py 로 새로 받은 토큰은 포함). 권한이 없으면 영상은 올라가고 썸네일만 실패합니다. 켜면 GitHub 자동 업로드에도 같이 적용됩니다. 채널의 사용자 지정 썸네일 권한(전화번호 인증)이 필요할 수 있습니다")
    if _yth != bool(TTS_CFG.get("yt_thumb")):
        TTS_CFG["yt_thumb"] = _yth
        json.dump(TTS_CFG, open(TTS_FILE, "w", encoding="utf-8"), ensure_ascii=False)
    _dmax = st.number_input("하루 업로드 상한 (오늘 올린 개수 포함, 한국시간 기준)", 1, 50, int(os.environ.get("DAILY_MAX", "20") or 20), key="up_dmax",
                            help="오늘 이미 올린 개수가 이 값에 닿으면 더 안 올립니다. 늘리면 그만큼 더 올라갑니다 (유튜브 API 일일 할당량도 고려하세요)")
    _ud = _ld()
    _upl = []
    for _i, _f in enumerate(_ud):
        _vp = _f.get("video_path_v6")
        if _f.get("status") != "rejected" and _f.get("status_v6") == "video_done" and not _f.get("youtube_id") and _vp and os.path.exists(_vp):
            _upl.append(_i)
    st.markdown(f"**업로드 대기 영상 {len(_upl)}개** (영상 파일이 이 PC에 있고 아직 유튜브에 올리지 않은 것, 폐기한 소재 제외)")
    if _upl:
        _rows = []
        for _i in _upl:
            _f = _ud[_i]
            try:
                _mb = os.path.getsize(_f["video_path_v6"]) / 1048576
            except Exception:
                _mb = 0
            try:
                _tt = " ".join(filter(None, [_f.get("title_line1"), _f.get("title_line2")])) or _f.get("topic", "")
            except Exception:
                _tt = ""
            _rows.append({"번호": _i, "나라": _f.get("country", ""), "제목": str(_tt)[:40], "크기(MB)": round(_mb, 1), "영상 파일": os.path.basename(_f["video_path_v6"])})
        st.dataframe(_rows, use_container_width=True, hide_index=True)
        _all = st.checkbox("목록 전체 선택", False, key="up_all")
        _pick_u = st.multiselect("올릴 영상", _upl, default=(_upl if _all else []), key=f"up_pick_{'all' if _all else 'sel'}_{len(_upl)}",
                                 format_func=lambda i: f"{i} {_ud[i].get('country', '')} - {str(_ud[i].get('title_line1', '') or _ud[i].get('topic', ''))[:30]}")
        if st.button(f"선택한 {len(_pick_u)}개 업로드", key="up_pick_go", type="primary", disabled=not _pick_u,
                     help="고른 영상만 비공개로 올립니다. 하루 상한을 넘으면 그만큼만 올라갑니다"):
            if os.environ.get("YT_REFRESH_TOKEN"):
                if TTS_CFG.get("yt_thumb"):
                    run("make_thumbnail.py", "--channel", CH, "--handle", HD, "--only", ",".join(map(str, _pick_u)))
                run("upload_to_youtube.py", "--indexes", ",".join(map(str, _pick_u)), "--daily-max", str(int(_dmax)))
                st.rerun()
            else:
                st.error("YT_REFRESH_TOKEN 이 없습니다. get_refresh_token.py 로 받아 두세요.")
    else:
        st.info("올릴 영상이 없습니다. (이미 업로드했거나, 영상 파일이 이 PC에 없는 경우입니다)")
    if st.button("앞에서부터 count개 업로드", key="up_go", help="목록 순서대로 count 개수만큼 올립니다 (고르지 않고 빠르게)"):
        if os.environ.get("YT_REFRESH_TOKEN"):
            if TTS_CFG.get("yt_thumb"):
                run("make_thumbnail.py", "--channel", CH, "--handle", HD)
            run("upload_to_youtube.py", "--limit", str(count), "--daily-max", str(int(_dmax)))
        else:
            st.error("YT_REFRESH_TOKEN 환경변수가 없습니다.")
    with st.expander("🖼 썸네일 만들기 (한 편씩 미리보기·장면 고르기)"):
        import subprocess as _sp_t, sys as _sys_t
        from pathlib import Path as _P_t
        _tb = _P_t(__file__).resolve().parent
        _td = _ld()
        _tn = [i for i, it in enumerate(_td) if it.get("video_path_v6") and _P_t(it["video_path_v6"]).exists()]
        st.caption("영상이 만들어진 소재의 썸네일을 새로 만들어 바로 확인합니다. 제목은 위 '제목 수정'에서 고친 값이 쓰입니다. 배경 장면은 자동(선명한 것)이거나 직접 고릅니다.")
        _ts = st.selectbox("소재 번호", sorted(_tn, reverse=True), key="thm_sel",
                           format_func=lambda i: f"{i} {_td[i].get('country', '')} - {str(_td[i].get('title_line1', '') or _td[i].get('topic', ''))[:30]}")
        if _ts is not None:
            _tc1, _tc2 = st.columns(2)
            _tst = _tc1.selectbox("스타일", ["hook", "pop", "classic"], 0, key="thm_style",
                                  format_func=lambda x: {"hook": "hook (제목·후크 중심)", "pop": "pop (국기+나라 띠)", "classic": "classic"}[x])
            _tsc = _tc2.number_input("배경 장면 번호 (0=자동)", 0, 30, int(_td[_ts].get("thumb_scene") or 0), key=f"thm_sc_{_ts}")
            _to = dict(_td[_ts].get("thumb_opts") or {})
            _o1, _o2, _o3 = st.columns(3)
            _sc1 = _o1.slider("제목 1줄 크기 배율", 0.5, 1.8, float(_to.get("scale1", 1.0)), 0.05, key=f"thm_s1_{_ts}")
            _sc2 = _o2.slider("제목 2줄 크기 배율", 0.5, 1.8, float(_to.get("scale2", 1.0)), 0.05, key=f"thm_s2_{_ts}")
            _ang = _o3.slider("기울기(도)", -20.0, 20.0, float(_to.get("angle", 0.0)), 0.5, key=f"thm_an_{_ts}")
            import fonts as _FN1
            _fa1 = _FN1.available()
            _fl = ["", *_fa1]
            _tfo = st.selectbox("썸네일 글씨체", _fl, _fl.index(_to.get("font") or "") if (_to.get("font") or "") in _fl else 0,
                                key=f"thm_ft_{_ts}", format_func=lambda x: "기본 (맑은 고딕/Noto)" if not x else _fa1[x])
            _o4, _o5 = st.columns(2)
            _dy = _o4.slider("글자 위치 (위↑ / 아래↓ px)", -500, 500, int(_to.get("dy", 0)), 10, key=f"thm_dy_{_ts}")
            _tg = _o5.checkbox("제목 위 태그(알약) 넣기", bool(_to.get("tag", True)), key=f"thm_tg_{_ts}")
            _g1, _g2, _g3 = st.columns([2, 1, 1])
            _tgt = _g1.text_input("태그 글자 (비우면 후크 첫 문장 자동, 나라 이름은 쓰지 않음)", _to.get("tag_text") or "", key=f"thm_tt_{_ts}")
            _tgc = _g2.color_picker("태그 배경색", _to.get("tag_color") or "#EB1414", key=f"thm_tgc_{_ts}")
            _tgf = _g3.color_picker("태그 글자색", _to.get("tag_fg") or "#FFFFFF", key=f"thm_tgf_{_ts}")
            if st.button("🟡 노란 태그 + 노란 2줄 글자 (띠 없음) 모양으로", key=f"thm_pre_{_ts}", help="1줄 흰색 / 2줄 노란 글자 / 노란 태그에 검정 글자 모양으로 한 번에 맞춰 다시 만듭니다"):
                import subprocess as _sp_p, sys as _sys_p
                _dm = _ld()
                _dm[_ts]["thumb_opts"] = {"band": "none", "color2": "#FFE200", "tag_color": "#FFE200", "tag_fg": "#000000", "tag": True}
                _sd(_dm)
                for _k_ in list(st.session_state.keys()):
                    if str(_k_).startswith("thm_") and (str(_k_).endswith(f"_{_ts}") or f"_{_ts}_" in str(_k_)) and not str(_k_).startswith("thm_sel"):
                        del st.session_state[_k_]
                _sp_p.run([_sys_p.executable, str(_tb / "make_thumbnail.py"), "--channel", CH, "--handle", HD, "--style", "hook", "--only", str(_ts)],
                          cwd=str(_tb), capture_output=True, text=True)
                st.rerun()
            st.markdown("**2줄 뒤 띠** (기본: 노란 붓터치)")
            _b1, _b2, _b3 = st.columns(3)
            _bk = _b1.selectbox("모양", ["brush", "rect", "round", "skew", "none"], ["brush", "rect", "round", "skew", "none"].index(_to.get("band", "brush")), key=f"thm_bk_{_ts}",
                                format_func=lambda x: {"brush": "붓터치", "rect": "사각", "round": "둥근 알약", "skew": "비스듬한 사각", "none": "띠 없음"}[x])
            _bc = _b2.color_picker("띠 색", _to.get("band_color") or "#FFE200", key=f"thm_bc_{_ts}")
            _bo = _b3.slider("투명도(%)", 20, 100, int(_to.get("band_opacity", 100)), 5, key=f"thm_bo_{_ts}")
            _b4, _b5, _b6, _b7 = st.columns(4)
            _bw = _b4.slider("폭 (글자보다 +px)", -100, 500, int(_to.get("band_w", 90)), 10, key=f"thm_bw_{_ts}")
            _bh = _b5.slider("높이 배율", 0.5, 2.0, float(_to.get("band_h", 1.0)), 0.05, key=f"thm_bh_{_ts}")
            _ba = _b6.slider("띠 기울기(도)", -15.0, 15.0, float(_to.get("band_angle", -2.0)), 0.5, key=f"thm_ba_{_ts}")
            _bd = _b7.slider("띠 위/아래(px)", -100, 100, int(_to.get("band_dy", 0)), 5, key=f"thm_bd_{_ts}")
            _k1, _k2 = st.columns(2)
            _tc1 = _k1.color_picker("1줄 기본 글자색", _to.get("color1") or "#ffffff", key=f"thm_k1_{_ts}")
            _tc2 = _k2.color_picker("2줄 기본 글자색", _to.get("color2") or "#000000", key=f"thm_k2_{_ts}")
            _cols = {}
            st.markdown("**썸네일 문구** (영상 제목과 따로 적을 수 있음 — 비우면 영상 제목 그대로)")
            _x1, _x2 = st.columns(2)
            _tx1 = _x1.text_input("1줄", _to.get("text1") or "", placeholder=str(_td[_ts].get("title_line1") or _td[_ts].get("topic") or ""), key=f"thm_x1_{_ts}")
            _tx2 = _x2.text_input("2줄", _to.get("text2") or "", placeholder=str(_td[_ts].get("title_line2") or ""), key=f"thm_x2_{_ts}")
            _cols["text1"], _cols["text2"] = _tx1.strip(), _tx2.strip()
            for _ln, (_key, _dflt, _txt) in enumerate((("title_line1", _tc1, _tx1), ("title_line2", _tc2, _tx2)), 1):
                _wd = str(_txt.strip() or _td[_ts].get(_key) or (_td[_ts].get("topic") if _ln == 1 else "") or "").split()
                if not _wd:
                    continue
                st.caption(f"{_ln}줄 단어별 색·크기 (기본색·1.0배와 다르게 고른 단어만 적용)")
                _prev = _to.get(f"colors{_ln}") or {}
                _prevz = _to.get(f"sizes{_ln}") or {}
                _cc = st.columns(min(len(_wd), 6))
                _pick, _pz = {}, {}
                for _k, _w in enumerate(_wd):
                    with _cc[_k % len(_cc)]:
                        _c = st.color_picker(_w, _prev.get(str(_k), _dflt), key=f"thm_c{_ln}_{_ts}_{_k}")
                        _z = st.number_input("크기 배율", 0.4, 2.5, float(_prevz.get(str(_k), 1.0)), 0.1, key=f"thm_z{_ln}_{_ts}_{_k}", label_visibility="collapsed",
                                             help=f"'{_w}' 크기 배율 (1.0=기본)")
                    if _c.lower() != _dflt:
                        _pick[str(_k)] = _c
                    if abs(_z - 1.0) > 1e-6:
                        _pz[str(_k)] = round(_z, 2)
                _cols[f"colors{_ln}"] = _pick
                _cols[f"sizes{_ln}"] = _pz
            if st.button("↩ 썸네일 설정 기본값으로 되돌리기", key=f"thm_reset_{_ts}", help="크기·기울기·색·띠·글씨체 설정을 지우고 기본 디자인으로 다시 만듭니다 (배경 장면 번호는 위 입력값 그대로)"):
                import subprocess as _sp_r, sys as _sys_r
                _dm = _ld()
                _dm[_ts].pop("thumb_opts", None)
                _sd(_dm)
                for _k_ in list(st.session_state.keys()):      # 이 소재의 슬라이더·색 선택 상태도 초기화
                    if str(_k_).startswith("thm_") and str(_k_).endswith(f"_{_ts}") or str(_k_).startswith(("thm_c1_" + str(_ts) + "_", "thm_c2_" + str(_ts) + "_")):
                        del st.session_state[_k_]
                _sp_r.run([_sys_r.executable, str(_tb / "make_thumbnail.py"), "--channel", CH, "--handle", HD, "--style", "hook", "--only", str(_ts)],
                          cwd=str(_tb), capture_output=True, text=True)
                st.rerun()
            if st.button("썸네일 만들기", key=f"thm_go_{_ts}"):
                _dm = _ld()
                _dm[_ts]["thumb_opts"] = {"scale1": _sc1, "scale2": _sc2, "angle": _ang, "dy": _dy, "tag": _tg, "tag_text": _tgt, "tag_color": _tgc, "tag_fg": _tgf, "font": _tfo, "band": _bk, "band_color": _bc, "band_opacity": _bo,
                                                 "band_w": _bw, "band_h": _bh, "band_angle": _ba, "band_dy": _bd, "color1": _tc1, "color2": _tc2, **_cols}
                if int(_tsc):
                    _dm[_ts]["thumb_scene"] = int(_tsc)
                else:
                    _dm[_ts].pop("thumb_scene", None)
                _sd(_dm)
                st.session_state["gh_dirty"] = True
                _r = _sp_t.run([_sys_t.executable, str(_tb / "make_thumbnail.py"), "--channel", CH, "--handle", HD,
                                "--style", _tst, "--only", str(_ts)], cwd=str(_tb), capture_output=True, text=True)
                if _r.returncode:
                    st.error((_r.stderr or _r.stdout)[-600:])
                st.session_state["thm_done"] = _ts
            _vp = _td[_ts].get("video_path_v6")
            _tf = _tb / "thumbnails" / f"{_P_t(_vp).stem}.png"
            if _tf.exists():
                st.image(str(_tf), width=300, caption=f"[{_ts}] {_tf.name} (현재 썸네일)")
    with st.expander("🎨 영상 상단 제목·색 (영상 맨 위 두 줄)"):
        _title_editor("u_")
    with st.expander("✏️ 제목 수정 (이미 만든 영상의 유튜브 제목·설명)"):
        st.caption("review.txt에는 아직 영상을 안 만든 소재만 나옵니다. 이미 만든 영상의 제목은 여기서 고치세요. 유튜브 제목과 썸네일 제목이 바뀝니다. "
                   "영상 화면 위에 이미 들어간 제목은 그대로입니다(바꾸려면 5단계 redo로 다시 만들어야 함).")
        _te = st.selectbox("소재 번호", sorted(_upl, reverse=True) if _upl else [], key="tedit_sel",
                           format_func=lambda i: f"{i} {_ud[i].get('country', '')} - {str(_ud[i].get('title_line1', '') or _ud[i].get('topic', ''))[:30]}")
        if _te is not None and 0 <= _te < len(_ud):
            _ft = _ud[_te]
            _t1 = st.text_input("제목 1줄", _ft.get("title_line1", ""), key=f"tedit1_{_te}")
            _t2 = st.text_input("제목 2줄", _ft.get("title_line2", ""), key=f"tedit2_{_te}")
            _hk = st.text_area("설명(후크/본문/반전, 한 줄씩)", "\n".join(str(_ft.get(k, "")) for k in ("hook", "body", "twist")), height=110, key=f"tedit3_{_te}")
            st.caption("대본: " + " ".join(str(_ft.get("narration", "")).split())[:300])
            if st.button("제목 저장", key=f"tedit_go_{_te}"):
                _dm = _ld()
                _dm[_te]["title_line1"] = _t1.strip()
                _dm[_te]["title_line2"] = _t2.strip()
                _hl = (_hk.split("\n") + ["", "", ""])[:3]
                for _k, _v in zip(("hook", "body", "twist"), _hl):
                    if _v.strip():
                        _dm[_te][_k] = _v.strip()
                _sd(_dm)
                st.session_state["gh_dirty"] = True
                st.success(f"[{_te}] 제목 저장 완료")
                st.rerun()
    with st.expander("🔗 이미 올린 영상을 소재에 직접 연결 (번호 + 영상 주소)"):
        st.caption("스튜디오에서 직접 올렸거나 제목을 고친 영상을 소재에 이어 줍니다. 연결하면 업로드 대기 목록에서 빠지고 중복 업로드가 막힙니다. 소재에는 업로드 기록(youtube_id)만 추가되고 대본·영상은 그대로입니다.")
        _mc1, _mc2 = st.columns([1, 3])
        _mn = _mc1.number_input("소재 번호", 0, 99999, 0, key="mlink_n")
        _mu = _mc2.text_input("영상 주소 또는 id (예: https://youtu.be/xxxx)", key="mlink_u")
        if st.button("연결", key="mlink_go", disabled=not _mu.strip()):
            import re as _re_m
            _m = _re_m.search(r"(?:youtu\.be/|v=|shorts/|^)([A-Za-z0-9_-]{11})(?:[?&/]|$)", _mu.strip())
            _dm = _ld()
            if not _m:
                st.error("영상 id를 찾지 못했습니다. 주소 전체를 붙여 넣으세요.")
            elif not (0 <= int(_mn) < len(_dm)):
                st.error("없는 소재 번호입니다.")
            else:
                _o = _dm[int(_mn)]
                _o["youtube_id"] = _m.group(1)
                _o["uploaded_manually"] = True
                _o.setdefault("uploaded_at", time.strftime("%Y-%m-%d"))
                _o.pop("upload_cleared_ts", None)
                _sd(_dm)
                st.session_state["gh_dirty"] = True
                st.success(f"[{int(_mn)}] {_o.get('country', '')} 에 영상 {_m.group(1)} 을 연결했습니다.")
                st.rerun()
    with st.expander("🧹 디스크 정리 (업로드 끝난 소재의 영상·음성·사진 지우기)"):
        st.caption("유튜브에 올라간(youtube_id 있음) 소재의 영상·음성·썸네일·장면 사진 파일을 지워 용량을 확보합니다. 대본·소재 DB, 내가 고른 사진(my_images)은 지우지 않습니다. 지운 소재를 다시 만들려면 이미지부터 다시 받아야 합니다.")
        _cl_clips = st.checkbox("롱폼 클립(clips/)도 포함 — 아직 롱폼에 안 쓴 소재가 있으면 끄세요", False, key="cl_clips")
        _cl_rej = st.checkbox("폐기한 소재의 파일도 포함", False, key="cl_rej")
        _cl_idx = st.text_input("번호 지정 (비우면 전체, 예: 3,5-9)", "", key="cl_idx")
        _ca = []
        if _cl_clips: _ca.append("--clips")
        if _cl_rej: _ca.append("--rejected")
        if _cl_idx.strip(): _ca += ["--indexes", _cl_idx.strip()]
        _c1, _c2 = st.columns(2)
        if _c1.button("용량 확인 (지우지 않음)", key="cl_scan"):
            run("cleanup_media.py", *_ca)
        _cl_ok = _c2.checkbox("위 대상을 정말 지웁니다", False, key="cl_ok")
        if _c2.button("지우기", key="cl_go", disabled=not _cl_ok):
            run("cleanup_media.py", "--delete", *_ca)
    with st.expander("🔎 업로드 현황 점검 (삭제된 영상 · 중복 영상)"):
        st.caption("채널(비공개 포함)의 실제 영상 목록과 DB의 업로드 기록을 비교합니다. ① 채널에 없는 영상(삭제됨) ② 채널 안의 중복 영상 ③ 한 영상이 여러 소재에 연결된 경우. 점검만 하고 DB는 바꾸지 않습니다. 영상 삭제는 유튜브 스튜디오에서 직접 하세요.")
        _ck1, _ck2 = st.columns(2)
        if _ck1.button("점검하기 (읽기만)", key="chk_up"):
            if os.environ.get("YT_REFRESH_TOKEN"):
                run("check_uploads.py")
            else:
                st.error("YT_REFRESH_TOKEN 이 없습니다.")
        _clr = _ck2.checkbox("채널에 없는 영상의 업로드 기록을 지워 '미업로드'로 되돌리기", False, key="chk_clr")
        if _ck2.button("삭제된 영상 기록 지우기", key="chk_up_clr", disabled=not _clr, help="DB의 youtube_id 등을 비웁니다. 영상 파일이 있으면 다시 올릴 수 있게 됩니다"):
            run("check_uploads.py", "--clear-missing")
        st.markdown("---")
        st.markdown("**🔗 채널 영상을 DB 소재에 연결 (sync_uploads)** — 수동으로 올린 영상 등 연결 안 된 영상을 소재와 이어 줍니다")
        st.caption("이 PC의 DB에 바로 적용됩니다 (GitHub 쪽 DB를 거치지 않음). 확실한 것(설명에 훅이 그대로 있거나 제목이 거의 같음)만 연결하고, 이미 연결된 소재는 공개 상태만 새로고칩니다. '미리 보기'는 저장하지 않습니다.")
        _sy1, _sy2 = st.columns(2)
        if _sy1.button("미리 보기 (저장 안 함)", key="syu_dry"):
            if os.environ.get("YT_REFRESH_TOKEN"):
                run("sync_uploads.py", "--dry")
            else:
                st.error("YT_REFRESH_TOKEN 이 없습니다.")
        if _sy2.button("연결하고 저장", key="syu_go", type="primary"):
            if os.environ.get("YT_REFRESH_TOKEN"):
                run("sync_uploads.py")
                st.session_state["gh_dirty"] = True
            else:
                st.error("YT_REFRESH_TOKEN 이 없습니다.")
        st.markdown("---")
        st.markdown("**🔗 공유 연결 정리** (한 유튜브 영상이 여러 소재에 연결된 경우)")
        st.caption("영상은 하나인데 소재가 여러 개 연결돼 있으면 중복 소재이거나 잘못 연결된 것입니다. 남길 소재를 고르면 나머지의 업로드 기록을 지웁니다. 영상 파일과 유튜브 영상은 건드리지 않습니다. 토큰이 있으면 채널 영상과 비교해 남길 소재를 제안합니다.")
        if st.button("공유 연결 찾기", key="fsl_find"):
            import fix_shared_links as _FS
            _vv = _FS.fetch_videos()
            st.session_state["fsl_groups"] = _FS.find_groups(_ld(), _vv)
            st.session_state["fsl_online"] = bool(_vv)
        _gs = st.session_state.get("fsl_groups")
        if _gs is not None:
            import fix_shared_links as _FS
            _dd = _ld()
            _gs = [g for g in _gs if sum(1 for x in g["items"] if _dd[x["i"]].get("youtube_id") == g["id"]) >= 2]
            st.write(f"**{len(_gs)}개** 영상이 여러 소재에 연결됨" + ("" if st.session_state.get("fsl_online") else " (채널 비교 못 함 - 번호가 앞선 소재를 제안)"))
            _keeps = {}
            for g in _gs:
                _ids = [x["i"] for x in g["items"]]
                _t = g["video"]["title"][:40] if g.get("video") else ""
                _sc = {x["i"]: x["score"] for x in g["items"]}
                _keeps[g["id"]] = st.selectbox(f"https://youtu.be/{g['id']} {_t} — 남길 소재", _ids, index=_ids.index(g["keep"]), key=f"fsl_keep_{g['id']}",
                                               format_func=lambda i, _sc=_sc: f"[{i}] {_dd[i].get('country', '')} {str(_dd[i].get('topic', ''))[:30]} ({_dd[i].get('status', '')}" + (f", 일치 {_sc[i]}" if _sc.get(i) is not None else "") + ")")
            if _gs:
                _how = st.radio("나머지 소재 처리", ["폐기 + 업로드 기록 지움 (중복 소재일 때)", "업로드 기록만 지움 (다른 소재가 잘못 연결됐을 때, 미업로드로 돌아가 다시 올릴 수 있음)"], key="fsl_how")
                if st.button("정리 적용", key="fsl_apply", type="primary"):
                    _d4 = _ld()
                    _done = _FS.apply_plan(_d4, _gs, _keeps, reject=_how.startswith("폐기"))
                    _sd(_d4)
                    st.session_state["gh_dirty"] = True
                    st.session_state.pop("fsl_groups", None)
                    st.success(f"{len(_done)}개 소재 정리: {', '.join(map(str, _done))}. 위 '쇼츠 DB 올리기'로 GitHub에 반영하세요.")
                    st.rerun()
        if os.path.exists("upload_check.md"):
            with st.expander("최근 점검 결과 (upload_check.md)", expanded=True):
                st.markdown(open("upload_check.md", encoding="utf-8").read())

with H_auto:
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

# ---------------- 🏠 시작·가이드 ----------------
FEATURES = [
    # (분류, 기능, 어디서, 설명, 새기능)
    ("롱폼", "GitHub 단계별 미리 보기", "Actions > longform > preview 선택", "list(목록)/script(대본·시나리오)/images(장면 사진)/voice(음성 mp3)를 영상 없이 따로 실행해 디스코드로 확인. 대본은 저장되어 이후 영상에 그대로 사용. 영어 주제는 자동으로 한국어로 표시", "신규"),
    ("롱폼", "이미지 컷 시트 · 후보 고르기 · 내 사진", "Actions > longform > preview=cuts, pick / my_images 폴더", "cuts: 컷 이름·대본·검색어 시트 + 컷별 후보 사진(Pixabay/Commons/Openverse) 번호 시트를 디스코드로. pick 칸에 `117_3=2` 처럼 적어 고르거나, `my_images/117_03.jpg` 로 직접 올리면 자동 검색보다 우선 사용. PC는 🎞 롱폼 탭의 '✂️ 이미지 컷' 패널에서 같은 작업 + GitHub my_images 주고받기", "신규"),
    ("2 대본", "외부 AI 대본 작성·검증 → 붙여넣기", "2 대본 › 대본 만들기 / 🎞 롱폼 맨 위 📥", "소재 번호로 외부 AI(ChatGPT/Gemini/Perplexity)에 줄 요청문(새로 작성+검증 / 기존 대본 검증·수정)을 만들고, 답변(### 번호 + 대본)을 붙여넣어 쇼츠 대본 또는 롱폼 챕터 대본으로 일괄 저장. 교차검증은 건너뛰고 Groq 토큰을 거의 안 씀 (교차검증은 기본 꺼짐)", "신규"),
    ("공통", "처리 개수 · 시작 번호", "맨 위 count / start_index", "한 번에 처리할 개수와, 이 번호 이상만 처리. 모든 단계에 적용", ""),
    ("공통", "다시 만들기 (redo)", "맨 위 redo 칸", "영상만 `98,99` / 대본부터 `101` + 체크 / 폐기 되살리기 `101!` + 체크. 끝나면 칸을 비우세요", ""),
    ("공통", "현황 (단계별 개수)", "왼쪽 사이드바 / 이 탭의 '현황 보기'", "승인대기·대본·음성·영상·업로드·폐기 개수", ""),
    ("1 소재", "새 소재 만들기 · 승인 · 제외", "1 소재 › 만들기·승인", "위키 기반 소재 생성 → 선택 승인 / 제외 (제외 = 폐기, 사유 'UI에서 제외')", ""),
    ("1 소재", "직접 소재 추가", "1 소재 › 직접 추가", "내가 정한 주제나 대본으로 소재 추가", ""),
    ("1 소재", "상태 확인 · 폐기 되살리기 · 업로드 기록", "1 소재 › 상태·폐기·업로드 기록", "소재별 상태, 폐기 사유/되살리기, 유튜브 영상 주소 기록, 교차검증 일괄 해제", ""),
    ("2 대본", "대본 만들기 (+목표 길이·장면 수)", "2 대본 › 대본 만들기", "목표 길이(초)·장면(이미지) 수 설정 후 대본/제목/이미지 검색어 생성", ""),
    ("2 대본", "대본 교차검증", "2 대본 › 대본 만들기의 🔍 체크", "위키 근거로 문장 검증. 모순은 폐기 전에 먼저 고쳐 씀, 근거 없음만으로는 폐기 안 함", "🆕"),
    ("2 대본", "내 스타일 · 성향 반영", "2 대본 › 대본 만들기의 🎯 내 스타일", "밀도·구체성·결말·과장 같은 내 기준과 선호 소재 분야를 저장하면 쇼츠/롱폼 대본과 새 소재 생성에 반영 (GitHub Actions에도 동기화)", "🆕"),
    ("2 대본", "어투 점검 (딱딱한 대본 존댓말로)", "2 대본 › 대본 보기·수정의 🗣 어투 점검", "'~한다.' 체로 나온 대본을 찾아 사실은 그대로 두고 존댓말 구어체로 고침 (한국어 채널)", "🆕"),
    ("2 대본", "대본 보기 · 수정 · 일괄 수정", "2 대본 › 대본 보기·수정", "소재별 대본 읽고 고치기, 여러 개 한 번에 수정", ""),
    ("2 대본", "제목 · 핵심 문구 · 이미지 검색어 · 제외", "2 대본 › review.txt", "review.txt를 보고 고침 (제외: 뒤에 사유를 쓰면 건너뜀)", ""),
    ("3 이미지", "이미지 받기", "3 이미지 › 이미지 받기", "검색어 생성 + 장면 이미지 다운로드", ""),
    ("3 이미지", "이미지 자동 검증 (CLIP+Ollama)", "3 이미지 › 검수·교체 안의 옵션", "받을 때 내용과 다른 사진을 걸러 다른 사진으로 교체, 수동 검증도 가능", "🆕"),
    ("3 이미지", "이미지 검수 · 교체", "3 이미지 › 검수·교체", "장면별 확인, 검색어 바꿔 다시 받기, 내 사진으로 교체", ""),
    ("4 음성", "목소리 · 속도 · 자막 방식", "4 음성 › 음성·자막 설정", "Supertonic/Edge 음성, 속도, 자막 방식. 미리듣기 가능", ""),
    ("4 음성", "음성 만들기 · 듣기", "4 음성 › 음성 만들기·듣기", "선택한 소재 음성 생성 후 바로 들어보기", ""),
    ("5 영상", "렌더링 (영상+썸네일)", "5 영상 › 렌더링", "영상·썸네일 합성. 음성이 없으면 같이 생성", ""),
    ("5 영상", "만든 영상 보기", "5 영상 › 만든 영상", "완성된 영상 재생/확인", ""),
    ("5 영상", "문구 넣기 · 편집 포인트", "5 영상 › 문구 넣기 / 편집 포인트", "영상 위 글자, 장면 전환 등 세부 조정", ""),
    ("6 업로드", "유튜브 비공개 업로드", "6 업로드 › 업로드", "YT_REFRESH_TOKEN 필요. 비공개로 올림", ""),
    ("6 업로드", "제목 · 설명 복사 / 디스코드", "6 업로드 › 제목·설명", "유튜브에 붙여넣을 제목/설명, 디스코드 전송", ""),
    ("롱폼", "롱폼 만들기 (rich 스타일)", "🎞 롱폼", "소재 3~30개를 묶어 가로 영상으로. 챕터 카드·키워드 팝업·비교 카드·인트로/요약", "🆕"),
    ("롱폼", "롱폼 대본·시나리오 확인/수정", "🎞 롱폼 › ① 대본·시나리오 → ② 수정 → ③ 만들기", "나레이션·키워드·비교 카드·화면 지정을 고쳐 반영. 챕터별 AI 재작성 지시 가능", "🆕"),
    ("롱폼", "채널 표시 (이름·주소·이미지·켜기/끄기·문구)", "🎞 롱폼 › 🎨 채널 표시", "오른쪽 위 채널 이름/주소/이미지를 각각 끄고 켜기, 문구 직접 입력, 채널 이미지 올리기, 인트로·엔딩 문구", "🆕"),
    ("롱폼", "오프닝 · 엔딩 멘트 수정", "🎞 롱폼 › ② › 🎤 오프닝·엔딩 멘트", "영상 앞 소개와 요약 화면에서 읽는 멘트를 고쳐 그 문구로 음성 생성", "🆕"),
    ("롱폼", "사진·영상 확인 (빠진 사진 점검)", "🎞 롱폼 › ② 챕터 안 '사진 · 영상 확인'", "챕터별 사진 미리보기, 빠진 사진 받기, 스톡 영상 미리보고 끄기. 빠진 사진이 있으면 합성 전에 멈춤", "🆕"),
    ("롱폼", "고친 대본에 맞춰 키워드·비교 다시 만들기", "🎞 롱폼 › ② 챕터 안 🔁 버튼", "나레이션을 고친 뒤 AI가 키워드 팝업·비교 카드·요약·영상 검색어를 새 글에 맞춰 다시 만듦 (대본은 그대로)", "🆕"),
    ("롱폼", "심층편 (소재 1개 → 긴 영상 1편)", "🎞 롱폼 › 🔭 심층편 / Actions > longform > deep", "소재 번호 1개를 소주제 3~8개(기본 5)로 나눠 5~12분(기본 8분) 영상 1편으로. 섹션 대본은 확인·수정·잠금 가능(deep_db.json). GitHub는 manual + 번호 1개 + deep 체크", "신규"),
    ("롱폼", "마지막 요약 화면 켜고 끄기", "🎞 롱폼 › 🎨 채널 표시 '마지막 요약 화면' / 심층편 체크박스 / Actions recap", "끄면 요약 화면과 엔딩 멘트 없이 마지막 챕터에서 바로 끝. 설명란 '요약' 챕터도 빠짐. 심층편에도 동일 적용", "신규"),
    ("롱폼", "비교 카드 켜고 끄기", "🎞 롱폼 › 🎨 채널 표시 '챕터별 비교 카드' / 심층편 체크박스 / Actions compare", "끄면 챕터에 저장된 비교 카드가 있어도 영상과 오프닝 멘트에 넣지 않음. AI가 대본을 다시 만들어도 다시 켜지지 않음", "신규"),
    ("롱폼", "챕터 순서 자동 배치 / 직접 바꾸기", "🎞 롱폼 › 순서 자동 배치 체크 / ② '↕ 챕터 순서 바꾸기'", "auto는 맨 앞에 가장 재밌는 소재·중간에 흐름 유지·분야/나라 안 겹치게 자동 배치, manual은 입력 순서 그대로. 순서를 바꾸면 각 챕터 마지막 연결 문장만 새 순서에 맞게 다시 씀", "신규"),
    ("롱폼", "스톡 영상 (Pexels/Pixabay)", "🎞 롱폼 체크박스", "분위기용 짧은 영상을 일부 장면에 사용 (Pixabay 키 필요)", "🆕"),
    ("롱폼", "렌더링 진행률", "🎞 롱폼 실행 로그", "10%마다 진행률과 남은 시간 표시", "🆕"),
    ("자동", "자동 진행", "이 탭 아래 '⚡ 자동 진행'", "확인 없이 대본/이미지/렌더링까지 한 번에", ""),
    ("동기화", "GitHub DB 동기화", "⚙ 관리·동기화 › GitHub", "UI 열 때 가져오고 작업 후 자동 올림. PC와 GitHub 번호 병합", "🆕"),
    ("동기화", "코드 업데이트 (GitHub → PC)", "⚙ 관리·동기화 › 코드 업데이트", "zip 없이 이 채널 저장소 코드만 받아 덮어씀. 채널이 다르면 멈춤", "🆕"),
    ("동기화", "구글 드라이브 저장", "⚙ 관리·동기화 › 구글 드라이브", "썸네일·이미지·음성·영상·자막을 드라이브에 업로드/받기 (외부에서도 작업)", "🆕"),
    ("이력", "작업 이력 · 요약 파일", "⚙ 관리·동기화 › 작업 이력", "언제 무슨 작업이 성공/실패했는지, 소재별 현황(csv). PC와 GitHub Actions 합산", "🆕"),
    ("이력", "디스코드 알림", "⚙ 관리·동기화 › 작업 이력 · 디스코드", "오래 걸리는 작업이 끝나면(실패는 항상) 한 줄 알림", "🆕"),
]
TASKS = [
    ("대본이 마음에 안 들어요", "2 대본 › 대본 보기·수정 (고친 뒤 3·4단계 다시)"),
    ("제목/핵심 문구만 고치고 싶어요", "2 대본 › review.txt"),
    ("이미지가 내용과 달라요", "3 이미지 › 검수·교체 (자동 검증 옵션도 있음)"),
    ("이미 만든 영상을 다시 만들고 싶어요", "맨 위 redo 칸에 번호 입력 → 5 영상 › 렌더링 (대본부터면 체크)"),
    ("폐기한 소재를 되살리고 싶어요", "맨 위 redo 칸에 `번호!` + 체크 (또는 1 소재 › 상태·폐기)"),
    ("롱폼 대본을 미리 보고 고치고 싶어요", "🎞 롱폼 › ① 대본·시나리오 만들기 → ② 수정"),
    ("PC와 GitHub 데이터가 다른 것 같아요", "⚙ 관리·동기화 › GitHub 동기화 › 차이 보기"),
    ("새 코드를 받고 싶어요", "⚙ 관리·동기화 › 코드 업데이트 › 최신 코드로 업데이트 (끝나면 안내대로: .py만 바뀌면 화면 새로고침(Rerun), 새 패키지/bat이 바뀌면 bat 재실행)"),
    ("지금까지 뭘 했는지 보고 싶어요", "⚙ 관리·동기화 › 작업 이력"),
]
with H_main:
    st.markdown("#### 작업 순서")
    _fc = st.columns(6)
    for _c_, (_t_, _d_) in zip(_fc, (("1 소재", "만들기·승인"), ("2 대본", "만들기→고치기"), ("3 이미지", "받기→검수"), ("4 음성", "설정→듣기"), ("5 영상", "렌더링"), ("6 업로드", "비공개 업로드"))):
        _c_.markdown(f"**{_t_}**  \n{_d_}")
    st.caption("각 단계 탭에는 '⚙ 실행'과 '보기·수정'이 같이 있습니다. 위쪽 count / start_index / redo는 모든 단계에 공통입니다. 확인 없이 한 번에 하려면 아래 '⚡ 자동 진행'.")
    if st.button("현황 보기", help="소재 상태별 개수와 render 가능 개수", key="home_status"):
        run("status_report.py")
    st.markdown("#### 자주 하는 일")
    st.table([{"하고 싶은 일": a_, "여기서": b_} for a_, b_ in TASKS])
    st.markdown("#### 기능 찾기")
    _q = st.text_input("검색 (예: 이미지, 동기화, 롱폼, 알림, 이력)", key="feat_q")
    _only_new = st.checkbox("🆕 최근에 추가된 기능만", False, key="feat_new")
    _rows = [r_ for r_ in FEATURES if (not _q.strip() or _q.strip().lower() in " ".join(r_).lower()) and (not _only_new or r_[4])]
    st.dataframe([{"": r_[4], "분류": r_[0], "기능": r_[1], "어디서": r_[2], "설명": r_[3]} for r_ in _rows], use_container_width=True, hide_index=True,
                 column_config={"": st.column_config.TextColumn(width="small"), "분류": st.column_config.TextColumn(width="small"), "기능": st.column_config.TextColumn(width="medium"),
                                "어디서": st.column_config.TextColumn(width="medium"), "설명": st.column_config.TextColumn(width="large")})
    if not _rows:
        st.caption("검색 결과가 없습니다.")


with T1b:
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

with T1c:
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
    with st.expander("🧩 중복 소재 찾기 (같은 나라에서 주제·훅이 비슷한 소재 쌍)", expanded=False):
        st.caption("폐기된 소재는 제외하고, 같은 나라(표기가 달라도 같은 나라로 묶음) 안에서 주제·훅·제목·대본 앞부분이 비슷한 쌍을 찾습니다. 후보일 뿐이라 다른 소재가 잡히거나 표현이 다른 같은 내용은 놓칠 수 있습니다. 남길 쪽은 업로드 > 영상 완료 > 조회수 > 앞 번호 순으로 제안합니다.")
        _dthr = st.slider("유사도 기준 (낮을수록 더 많이 잡음)", 0.3, 0.9, 0.45, 0.05, key="dup_thr")
        if st.button("중복 후보 찾기", key="dup_find"):
            import find_dup_topics as _FD
            st.session_state["dup_pairs"] = _FD.find_pairs(_ld(), float(_dthr))
        _pairs = st.session_state.get("dup_pairs")
        if _pairs is not None:
            _dd = _ld()
            import find_dup_topics as _FD
            st.write(f"**{len(_pairs)}쌍** (현재 DB 기준으로 이미 폐기된 소재가 낀 쌍은 숨깁니다)")
            _rows, _drop_opts, _safe = [], [], []
            for p in _pairs:
                if _dd[p["a"]].get("status") == "rejected" or _dd[p["b"]].get("status") == "rejected":
                    continue
                _rows.append({"유사도": p["score"], "A": f"[{p['a']}] {_FD.describe(_dd[p['a']])}", "B": f"[{p['b']}] {_FD.describe(_dd[p['b']])}",
                              "근거": p["why"], "제안": ("[%d] 폐기" % p["drop"] + (" (안전)" if p["drop_safe"] else " (영상/업로드 있음)")) if p["drop"] is not None else "직접 판단"})
                for _k in (p["a"], p["b"]):
                    if _k not in _drop_opts:
                        _drop_opts.append(_k)
                if p["drop"] is not None and p["drop_safe"] and p["drop"] not in _safe:
                    _safe.append(p["drop"])
            if _rows:
                st.dataframe(_rows, use_container_width=True, hide_index=True)
                _useall = st.checkbox("안전한 제안(영상·업로드 없는 쪽)을 모두 선택", False, key="dup_safe_all")
                _pk = st.multiselect("폐기할 소재", sorted(_drop_opts), default=(sorted(_safe) if _useall else []), key=f"dup_pick_{_useall}_{len(_rows)}",
                                     format_func=lambda i: f"{i} {_FD.describe(_dd[i])}")
                _dr = st.text_input("폐기 사유", "중복 소재", key="dup_reason")
                if st.button(f"선택한 {len(_pk)}개 폐기", key="dup_rej", type="primary", disabled=not _pk,
                             help="상태만 폐기(rejected)로 바꿉니다. 영상 파일과 유튜브 영상은 그대로입니다"):
                    _d3 = _ld()
                    for _i in _pk:
                        _d3[_i]["status"] = "rejected"
                        _d3[_i]["reject_reason"] = _dr or "중복 소재"
                    _sd(_d3)
                    st.session_state["gh_dirty"] = True
                    st.session_state.pop("dup_pairs", None)
                    st.success(f"{len(_pk)}개 폐기: {', '.join(map(str, _pk))}. 위 '쇼츠 DB 올리기'로 GitHub에 반영하세요.")
                    st.rerun()
            else:
                st.info("중복 후보가 없습니다.")
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

    with st.expander("🔁 교차검증 다시 돌리기 (일괄 해제)"):
        from common import load_db as _ldx, save_db as _sdx
        _dx = _ldx()
        _rej_x = [i for i, f in enumerate(_dx) if f.get("status") == "rejected" and str(f.get("reject_reason", "")).startswith("교차검증")]
        _done_x = [i for i, f in enumerate(_dx) if f.get("cross_checked")]
        st.caption(f"교차검증으로 폐기된 소재 {len(_rej_x)}개 · 검증 결과가 있는 소재 {len(_done_x)}개. 해제하면 다음 '대본(2단계)' 실행 때 (음성·자막 설정에서 교차검증을 켠 상태여야 함) 새 기준으로 다시 검증하고, 모순 문장은 고쳐 씁니다.")
        _sc_x = st.radio("대상", ["교차검증으로 폐기된 소재 (복구 + 다시 검증)", "검증 결과가 있는 소재 전부", "번호 직접 입력"], key="xr_scope")
        _nums_x = st.text_input("번호 (예: 265,290-294)", key="xr_nums", disabled=not _sc_x.startswith("번호"))
        if _sc_x.startswith("교차검증으로"):
            _tg_x = list(_rej_x)
        elif _sc_x.startswith("검증 결과"):
            _tg_x = list(_done_x)
        else:
            _tg_x = []
            for _p in re.split(r"[,\s]+", _nums_x.strip()):
                _m = re.fullmatch(r"(\d+)-(\d+)", _p)
                _tg_x += list(range(int(_m.group(1)), int(_m.group(2)) + 1)) if _m else ([int(_p)] if _p.isdigit() else [])
            _tg_x = [i for i in dict.fromkeys(_tg_x) if 0 <= i < len(_dx)]
        st.write(f"대상 {len(_tg_x)}개: " + (", ".join(f"{i} {_dx[i].get('country', '')}" for i in _tg_x[:30]) + (" ..." if len(_tg_x) > 30 else "")))
        if st.button("교차검증 결과 해제", key="xr_go", disabled=not _tg_x):
            for i in _tg_x:
                f = _dx[i]
                if f.get("status") == "rejected" and str(f.get("reject_reason", "")).startswith("교차검증"):
                    f["status"] = "scripted" if f.get("narration") else "verified"
                    f.pop("reject_reason", None)
                for k in ("cross_checked", "cross_verdict", "cross_notes", "cross_model", "cross_sources"):
                    f.pop(k, None)
            _sdx(_dx)
            st.success(f"{len(_tg_x)}개 해제했습니다. 교차검증을 켠 채로 '2 대본' 단계를 실행하세요 (start_index가 소재 번호 이하여야 합니다).")
            st.rerun()

with T2c:
    st.caption("대본·제목·검색어를 한 파일에서 고칩니다 (위 대본 탭과 같은 내용)")
    st.caption("대본[N]·핵심[N]·이미지[N]·제목 수정 가능 / 소재를 건너뛰려면 `제외:` 뒤에 사유 / ( 로 시작하는 줄은 참고용 / === [번호] === 줄은 수정 금지")
    txt = read_review()
    new = st.text_area("review.txt", txt, height=400, label_visibility="collapsed", help="수정 후 아래 저장 버튼을 꼭 누르세요")
    if st.button("review.txt 저장"):
        write_review(new); st.success("저장됨 (다음 단계 실행 때 자동 반영)")



with T2b:
    with st.expander("🎬 영상 맨 위 제목·색 수정 (영상 만들기 전에 미리 고치기)"):
        _title_editor("s_")
    with st.expander("🔄 대본에 맞게 주제·훅·제목·핵심 문구 다시 만들기 (대본을 직접 고친 소재)", expanded=False):
        st.caption("대본을 직접 바꿨는데 제목·핵심 문구·유튜브 설명(훅/본문/반전)·주제가 옛 내용이면 영상과 어긋납니다. 번호를 넣으면 새 대본 기준으로 다시 만듭니다 (대본·나라·영상·업로드 기록은 그대로). 영상에 반영하려면 그 뒤 redo + 렌더링을 하세요. GROQ_API_KEY 필요, 소재당 AI 호출 3~4회.")
        _rsn = st.text_input("소재 번호 (예: 286,304)", key="rsm_idx")
        _rk = st.checkbox("제목은 그대로 두기", False, key="rsm_keep")
        if st.button("다시 만들기", key="rsm_go", disabled=not _rsn.strip()):
            run("resync_meta.py", "--indexes", _rsn.replace(" ", ""), *(["--keep-title"] if _rk else []))
    if not EN:
        with st.expander("🗣 어투 점검 (딱딱한 '~한다.' 체 대본 찾기·고치기)", expanded=False):
            import ko_text as _KT
            _dbt = _ld()
            _st = [(i_, _KT.plain_ratio(f_.get("narration", ""))) for i_, f_ in enumerate(_dbt)
                   if i_ >= int(start) and f_.get("status") != "rejected" and str(f_.get("narration", "")).strip() and _KT.plain_ratio(f_.get("narration", "")) >= 0.3]
            st.caption("대본은 '~합니다/~해요' 존댓말 구어체여야 하는데, '~한다.' 체로 나온 소재를 찾습니다 (start_index 이상). 고치면 사실·문장 수·순서는 그대로 두고 말투만 바꾸며, 그 소재의 음성은 지워지니 음성부터 다시 만드세요. 새로 만드는 대본은 딱딱하면 자동으로 다시 쓰게 해 두었습니다.")
            if not _st:
                st.success("딱딱한 어투의 대본이 없습니다.")
            else:
                st.dataframe([{"번호": i_, "나라": _dbt[i_].get("country", ""), "주제": _dbt[i_].get("topic", ""), "딱딱한 문장 비율": f"{r_:.0%}",
                               "대본 앞부분": str(_dbt[i_].get("narration", ""))[:50]} for i_, r_ in _st], use_container_width=True, hide_index=True)
                _pick_t = st.multiselect("고칠 소재", [i_ for i_, _ in _st], default=[i_ for i_, _ in _st][:10], key="tone_pick",
                                         format_func=lambda i_: f"{i_} {_dbt[i_].get('country', '')} - {str(_dbt[i_].get('topic', ''))[:20]}")
                _t1, _t2 = st.columns(2)
                if _t1.button("미리보기 (저장 안 함)", key="tone_dry", disabled=not _pick_t):
                    run("fix_tone.py", "--indexes", ",".join(map(str, _pick_t)), "--dry-run")
                if _t2.button("존댓말로 고치기 (Groq)", key="tone_go", type="primary", disabled=not _pick_t):
                    run("fix_tone.py", "--indexes", ",".join(map(str, _pick_t)))
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
            st.markdown("**핵심 문구** (자막 방식이 '핵심 문구' 또는 '대본 자막 + 핵심 문구 둘 다'일 때만 화면에 나옵니다)")
            h_txt = st.text_area("핵심", "\n".join(hls), height=100, key=f"h_{sel}", label_visibility="collapsed")
            st.caption("핵심[번호]의 번호는 대본 문장 번호입니다. 대본에서 문장을 빼거나 넣고 저장하면 핵심 문구 번호가 자동으로 새 대본에 맞춰집니다 (빠진 문장의 핵심 문구는 같이 빠짐) — 번호를 직접 바꾸지 마세요.")
            with st.expander("🎛 핵심 문구 모양·효과 (기본값 그대로 써도 됩니다)"):
                import fonts as _FH
                import overlays as OV
                _fh = _FH.available()
                _hs0 = dict((_ld()[sel].get("highlight_style") or {})) if sel < len(_ld()) else {}
                _he1, _he2, _he3 = st.columns(3)
                _hef = _he1.selectbox("효과", OV.EFFECTS, OV.EFFECTS.index(_hs0.get("effect") or "페이드") if (_hs0.get("effect") or "페이드") in OV.EFFECTS else 0, key=f"hs_ef_{sel}",
                                      help="타자기는 핵심 문구에선 '나타남'으로 처리됩니다")
                _hsc = _he2.slider("크기 배율", 0.5, 1.5, float(_hs0.get("scale") or 1.0), 0.05, key=f"hs_sc_{sel}")
                _hfo = ["", *_fh]
                _hft = _he3.selectbox("글씨체", _hfo, _hfo.index(_hs0.get("font") or "") if (_hs0.get("font") or "") in _hfo else 0, key=f"hs_ft_{sel}",
                                      format_func=lambda x: "기본 (설정 탭 자막 글씨체)" if not x else _fh[x])
                _hp1, _hp2 = st.columns(2)
                _hx = _hp1.slider("가로 위치 x(%)", 0, 100, int(_hs0.get("x") or 50), key=f"hs_x_{sel}")
                _hy_auto = _hp2.checkbox("세로 위치 자동 (아래쪽, '둘 다'일 땐 이미지 위쪽)", _hs0.get("y") in (None, ""), key=f"hs_ya_{sel}")
                _hy = None
                if not _hy_auto:
                    _hy = st.slider("세로 위치 y(%) (이미지 영역은 약 23~76%)", 0, 100, int(_hs0.get("y") or 70), key=f"hs_y_{sel}")
                _hc1, _hc2, _hc3 = st.columns(3)
                _hch = _hc1.color_picker("강조(*별표*) 글자색", _hs0.get("color_hl") or "#FFE200", key=f"hs_ch_{sel}")
                _hcb = _hc2.color_picker("나머지 글자색", _hs0.get("color_base") or "#FFFFFF", key=f"hs_cb_{sel}")
                _hcs = _hc3.color_picker("외곽선색", _hs0.get("stroke") or "#000000", key=f"hs_cs_{sel}")
                _hb1, _hb2 = st.columns(2)
                if _hb1.button("모양 저장", key=f"hs_save_{sel}", type="primary"):
                    _dm = _ld()
                    _dm[sel]["highlight_style"] = {"effect": _hef, "scale": _hsc, "font": _hft, "x": _hx, "y": _hy,
                                                   "color_hl": _hch, "color_base": _hcb, "stroke": _hcs}
                    _sd(_dm)
                    st.success("저장했습니다. 이미 만든 영상이면 redo에 번호를 넣고 5단계 렌더링을 해야 반영됩니다.")
                if _hb2.button("기본 모양으로 되돌리기", key=f"hs_reset_{sel}"):
                    _dm = _ld(); _dm[sel].pop("highlight_style", None); _sd(_dm); st.rerun()
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

with T3b:
    from common import load_db, save_db, visual_dir
    db_ = load_db()
    cand = [i for i, f in enumerate(db_) if f.get("status") in ("scripted", "tts_done", "video_done") and i >= start]
    _direct = st.text_input("번호로 바로 열기 (목록에 없는 소재, 예: 595)", "", key="img_direct",
                            help="목록은 '대본 완료 이상' 상태이고 시작 번호(start_index) 이상인 소재만 보입니다. 상태가 다르거나 시작 번호보다 앞이어도 번호를 넣으면 열립니다.")
    _dn = int(_direct) if _direct.strip().isdigit() and int(_direct) < len(db_) else None
    if _dn is not None and _dn not in cand:
        _f_ = db_[_dn]
        st.caption(f"[{_dn}] {_f_.get('country', '')} 상태: {_f_.get('status')} — 목록 조건(상태 scripted/tts_done/video_done, 번호 ≥ start_index {start})에 맞지 않아 직접 열었습니다.")
        cand = sorted(cand + [_dn])
        if _f_.get("status") == "rejected" and _f_.get("narration"):
            st.warning(f"폐기(rejected) 상태입니다. 사유: {_f_.get('reject_reason', '')} — review.txt의 `제외:` 줄에 글자가 남아 있으면 저장할 때마다 다시 폐기됩니다. "
                       "대본·이미지를 계속 쓰려면 아래 버튼으로 되살리고, review.txt의 `제외:` 뒤 글자를 지우세요.")
            if st.button("폐기 해제 (대본 완료 상태로 되돌리기)", key=f"unrej_{_dn}"):
                _dm = load_db()
                _dm[_dn]["status"] = "scripted"
                _dm[_dn].pop("reject_reason", None)
                save_db(_dm)
                st.session_state["gh_dirty"] = True
                st.rerun()
    if not cand:
        st.info("대상 소재가 없습니다.")
    else:
        _def = cand.index(_dn) if _dn in cand else 0
        idx = st.selectbox("소재 번호", cand, _def, key=f"img_sel_{_dn}", format_func=lambda i: f"{i} {db_[i].get('country', '')} ({db_[i].get('status')})")
        item = db_[idx]
        folder = visual_dir(HERE, idx, item)
        st.checkbox("이미 업로드된 영상은 이미지를 다시 받을 때 유튜브 설명(사진 출처)도 같이 수정", True, key="desc_sync",
                    help="영상 파일 자체는 유튜브에서 못 바꾸고 설명란만 바뀝니다. 영상에 새 사진을 넣으려면 새로 렌더링해 다시 올려야 합니다. 토큰에 영상 수정 권한이 없으면 실패하고 붙여넣을 설명을 보여줍니다.")
        qs = list(item.get("image_queries") or [])
        credits = {c.get("scene"): c for c in (item.get("image_credits") or [])}
        from scenes import item_scene_count as _isc
        try:
            from scenes import used_scene_count as _usc
        except ImportError:      # scenes.py 가 아직 예전 버전(코드 업데이트를 한 번 더 하면 해결)
            _usc = _isc
            st.warning("scenes.py 가 예전 버전입니다. 관리·동기화 탭에서 코드 업데이트를 한 번 더 하세요.")
        _n_sc = _isc(item)
        _grp = _usc(item)          # 영상에 실제 쓰이는 장면 수 (대본 문장이 적으면 뒤쪽 이미지는 안 씀)
        _have = [n_ for n_ in range(1, _grp + 1) if (folder / f"scene_{n_:02d}.png").exists()]
        _miss = [n_ for n_ in range(1, _grp + 1) if n_ not in _have]
        if _miss:
            st.error(f"⚠️ 이미지 누락 {len(_miss)}장: 장면 {', '.join(map(str, _miss))} (영상에 쓰이는 {_grp}장 중 {len(_have)}장). "
                     "이대로 5단계를 하면 영상 제작이 이 소재를 건너뜁니다. 아래 '빠진 이미지 받기' 또는 사진 올리기로 채우세요.")
        else:
            st.success(f"영상에 쓰이는 이미지 {_grp}/{_grp}장 모두 있음")
        if _grp < _n_sc:
            st.info(f"대본 문장이 적어 장면이 {_grp}개로 묶입니다. 장면 {_grp + 1}번 이미지는 영상에 안 쓰이니 없어도 됩니다 (대본 문장을 늘리면 쓰입니다)." if _grp + 1 == _n_sc else f"대본 문장이 적어 장면이 {_grp}개로 묶입니다. 장면 {_grp + 1}~{_n_sc}번 이미지는 영상에 안 쓰이니 없어도 됩니다 (대본 문장을 늘리면 쓰입니다).")
        elif qs and len(qs) != _n_sc:
            st.warning(f"이미지 검색어 {len(qs)}개 ≠ 장면 {_n_sc}개. '검색어도 새로 만들기'를 체크하고 이미지를 다시 받으세요.")
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
        _lack = []
        for _i, _f in enumerate(db_):
            if _f.get("status") in ("scripted", "tts_done") and _i >= start:
                _fd = visual_dir(HERE, _i, _f)
                _ms = [n_ for n_ in range(1, _usc(_f) + 1) if not (_fd / f"scene_{n_:02d}.png").exists()]
                if _ms:
                    _lack.append(f"{_i} {_f.get('country', '')}: {len(_ms)}장 누락 ({', '.join(map(str, _ms))})")
        if _lack:
            with st.expander(f"⚠️ 이미지가 빠진 소재 {len(_lack)}개 (영상 제작 전 채워야 함)"):
                st.code("\n".join(_lack))
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
        with st.expander("🖼️ 이미지 검증 (CLIP + Ollama) 설정 · 검증 실행", expanded=bool(TTS_CFG.get("imgchk"))):
            st.caption("사진이 장면 검색어와 맞는지 PC에서 확인합니다. CLIP(빠름)이 먼저 보고, 애매하면 Ollama 비전 모델이 2차 판정합니다. "
                       "점수는 참고값이며 라이선스·사실 확인은 대신하지 않습니다. GitHub Actions에서는 동작하지 않습니다(로컬 전용).")
            TTS_CFG["imgchk"] = st.checkbox("이미지를 받을 때 자동으로 검증하고 불일치 사진은 다른 사진으로 교체", bool(TTS_CFG.get("imgchk")), key="imgchk_auto",
                                            help="5단계(이미지 받기) 및 '빠진 이미지 받기/전부 새로 받기'에 적용됩니다. 소재당 시간이 늘어납니다")
            g1, g2, g3 = st.columns(3)
            TTS_CFG["imgchk_ollama"] = g1.checkbox("Ollama 2차 확인", bool(TTS_CFG.get("imgchk_ollama")), key="imgchk_ol",
                                                   help="CLIP 점수가 기준 근처이거나 미달인 장면만 비전 모델로 다시 봅니다")
            TTS_CFG["imgchk_ollama_all"] = g2.checkbox("모든 장면을 Ollama로", bool(TTS_CFG.get("imgchk_ollama_all")), key="imgchk_olall",
                                                       disabled=not TTS_CFG["imgchk_ollama"], help="가장 정확하지만 CPU에서는 이미지당 수십 초")
            TTS_CFG["imgchk_retry"] = g3.number_input("불일치 시 교체 시도", 0, 5, int(TTS_CFG.get("imgchk_retry") or 0), key="imgchk_rt",
                                                      help="0이면 판정만 하고 교체는 안 합니다")
            h1, h2 = st.columns(2)
            TTS_CFG["imgchk_model"] = h1.text_input("Ollama 모델", str(TTS_CFG.get("imgchk_model") or "qwen2.5vl:3b"), key="imgchk_mdl")
            TTS_CFG["imgchk_thr"] = h2.slider("CLIP 기준값", 0.10, 0.40, float(TTS_CFG.get("imgchk_thr") or 0.22), 0.01, key="imgchk_thr_s",
                                              help="이 값 미만이면 불일치 의심. 실제 결과를 보며 조정하세요 (일치인데 자꾸 불일치로 나오면 낮추기)")
            json.dump(TTS_CFG, open(TTS_FILE, "w", encoding="utf-8"), ensure_ascii=False)
            v1, v2 = st.columns(2)
            if v1.button("🔍 이 소재 이미지 검증", key=f"ic_{idx}", disabled=not qs):
                run("image_check.py", "--index", str(idx))
                st.rerun()
            if v2.button("🔍 검증 + 불일치 자동 교체", key=f"icf_{idx}", disabled=not qs,
                         help="불일치 장면만 Commons/Pixabay의 다른 사진으로 바꿉니다. 맞는 사진이 없으면 가장 나은 사진을 남깁니다"):
                if run("image_check.py", "--index", str(idx), "--fix", "--force"):
                    sync_desc([idx])
                st.rerun()
            bulk_ic = st.text_input("여러 소재 일괄 검증 (예: 109-115,120)", key="ic_bulk")
            bfix = st.checkbox("불일치는 자동 교체까지", True, key="ic_bulk_fix")
            if st.button("일괄 검증 시작", key="ic_bulk_go", disabled=not bulk_ic.strip()):
                nums = []
                for part in re.split(r"[,\s]+", bulk_ic.strip()):
                    m_ = re.fullmatch(r"(\d+)-(\d+)", part)
                    if m_:
                        nums += list(range(int(m_.group(1)), int(m_.group(2)) + 1))
                    elif part.isdigit():
                        nums.append(int(part))
                nums = [n_ for n_ in dict.fromkeys(nums) if 0 <= n_ < len(db_)]
                TIMES.clear()
                prog = st.progress(0.0)
                for k_, n_ in enumerate(nums, start=1):
                    st.write(f"**[{k_}/{len(nums)}] {n_} {db_[n_].get('country', '')}**")
                    run("image_check.py", "--index", str(n_), *(["--fix"] if bfix else []))
                    prog.progress(k_ / len(nums))
                if bfix:
                    sync_desc(nums)
                st.success(f"{len(nums)}개 소재 검증 완료. 교체한 소재는 redo에 번호를 넣고 5단계로 영상에 반영하세요.")
        checks = {e.get("scene"): e for e in (item.get("image_check") or []) if isinstance(e, dict)}
        _ic_badge = {"ok": "✅ 일치", "doubt": "⚠️ 애매", "bad": "❌ 불일치", "unknown": "➖ 미검증"}
        if checks:
            _cn = {}
            for e_ in checks.values():
                _cn[e_.get("verdict")] = _cn.get(e_.get("verdict"), 0) + 1
            st.caption("검증 결과: " + " · ".join(f"{_ic_badge.get(k, k)} {v}" for k, v in _cn.items()))
        if not qs:
            st.warning("이미지 검색어가 아직 없습니다. 위 버튼을 누르세요.")
        else:
            cols = st.columns(3)
            for n in range(1, max(len(qs), 1) + 1):
                with cols[(n - 1) % 3]:
                    f_ = folder / f"scene_{n:02d}.png"
                    if f_.exists():
                        st.image(str(f_), caption=f"장면 {n}", use_container_width=True)
                        _e = checks.get(n)
                        try:
                            import image_check as _IC
                            if _e and _e.get("sig") != _IC._sig(f_, qs[n - 1] if n - 1 < len(qs) else ""):
                                st.caption("➖ 미검증 (사진 또는 검색어가 바뀜)"); _e = None
                        except Exception:
                            pass
                        if _e:
                            _t = _ic_badge.get(_e.get("verdict"), "")
                            if _e.get("clip") is not None:
                                _t += f" · CLIP {_e['clip']:.3f}"
                            if _e.get("ollama"):
                                _t += f" · Ollama {'맞음' if _e['ollama'].get('match') else '다름'}({_e['ollama'].get('conf')})"
                            (st.error if _e.get("verdict") == "bad" else st.warning if _e.get("verdict") == "doubt" else st.caption)(_t + (f"\n\n사진 내용: {_e['seen']}" if _e.get("seen") else ""))
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
                    if f_.exists() and st.button("🔍 이 장면 검증", key=f"icsc_{idx}_{n}"):
                        run("image_check.py", "--index", str(idx), "--scene", str(n), "--force")
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

with T5d:
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

with T6b:
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

with T5b:
    if os.path.isdir("videos"):
        for f in sorted(os.listdir("videos"))[-3:]:
            if f.endswith(".mp4"):
                st.caption(f); st.video(os.path.join("videos", f))
                sp = os.path.join("videos", f[:-4] + ".srt")
                if os.path.exists(sp):
                    st.download_button("SRT 자막 받기", open(sp, "rb").read(), file_name=f[:-4] + ".srt", key="srt_" + f)
    else:
        st.info("아직 만든 영상이 없습니다.")

with T5c:
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
        cols = ["text", "start", "dur", "x", "y", "size", "color", "stroke", "bold", "font", "effect", "bg"]
        # 색은 코드(#RRGGBB) 대신 이름으로 고른다. 목록에 없는 색은 아래 '색 직접 고르기'로 추가 (이미 쓴 코드는 자동으로 목록에 들어감)
        _PRESET = [("흰색", "#FFFFFF"), ("노랑", "#FFE200"), ("주황", "#FF8A00"), ("빨강", "#FF3B30"), ("분홍", "#FF5FA2"), ("보라", "#8A5CFF"),
                   ("파랑", "#2F80FF"), ("하늘", "#5CD6FF"), ("초록", "#2ECC71"), ("연두", "#B6F23A"), ("검정", "#000000"), ("회색", "#808080")]
        _n2h = {n_: h_ for n_, h_ in _PRESET}
        _h2n = {h_.lower(): n_ for n_, h_ in _PRESET}
        _custom = st.session_state.setdefault("ov_custom_colors", [])
        _ov0 = OV.clean_list(it_o.get("overlays") or [])
        for _r in _ov0:
            for _c in ("color", "stroke", "bg"):
                _v = str(_r.get(_c) or "").strip()
                if _v.startswith("#") and _v.lower() not in _h2n and _v.upper() not in _custom:
                    _custom.append(_v.upper())

        def _to_name(v):
            v = str(v or "").strip()
            return "" if not v else _h2n.get(v.lower(), v.upper() if v.startswith("#") else v)

        def _to_hex(v):
            v = str(v or "").strip()
            return "" if v in ("", "없음") else _n2h.get(v, v)
        _opts_c = [n_ for n_, _ in _PRESET] + _custom
        _opts_o = ["없음"] + _opts_c
        import fonts as _FN
        _fa = _FN.available()
        _f2l = {k_: v_ for k_, v_ in _fa.items()}
        _l2f = {v_: k_ for k_, v_ in _fa.items()}
        _FDEF = "기본(전체 설정)"
        df0 = pd.DataFrame(_ov0, columns=cols)
        df0["font"] = df0["font"].map(lambda v: _f2l.get(str(v or ""), _FDEF)) if len(df0) else df0["font"].astype(object)
        for _c, _dflt in (("color", "흰색"), ("stroke", "없음"), ("bg", "없음")):
            df0[_c] = df0[_c].map(lambda v, _d=_dflt: _to_name(v) or _d) if len(df0) else df0[_c]
        for c_ in ("text", "color", "stroke", "effect", "bg"):
            df0[c_] = df0[c_].astype(str) if len(df0) else df0[c_].astype(object)
        if df0.empty:
            df0 = pd.DataFrame([{"text": "", "start": 0.0, "dur": 2.0, "x": 50, "y": 50, "size": 80, "color": "흰색",
                                 "stroke": "검정", "bold": True, "font": _FDEF, "effect": "팝", "bg": "없음"}], columns=cols)
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
                "color": st.column_config.SelectboxColumn("글자색", options=_opts_c, help="목록에서 고르세요. 없는 색은 아래 '색 직접 고르기'로 추가"),
                "stroke": st.column_config.SelectboxColumn("외곽선색", options=_opts_o, help="'없음'이면 외곽선 없음"),
                "bold": st.column_config.CheckboxColumn("굵게"),
                "font": st.column_config.SelectboxColumn("글씨체", options=[_FDEF] + list(_fa.values()), help="이 문구만 다른 글씨체로. '기본(전체 설정)'은 설정 탭에서 고른 문구 글씨체. 굵게 칸은 기본 글꼴에서만 적용됩니다"),
                "effect": st.column_config.SelectboxColumn("효과", options=OV.EFFECTS),
                "bg": st.column_config.SelectboxColumn("배경박스색", options=_opts_o, help="'없음'이면 배경 박스 없음"),
            })
        rows_o = [{k: (None if (isinstance(v, float) and v != v) else v) for k, v in r.items()} for r in ed.to_dict("records")]
        for _r in rows_o:
            for _c in ("color", "stroke", "bg"):
                _r[_c] = _to_hex(_r.get(_c))
            _r["font"] = _l2f.get(str(_r.get("font") or ""), "")
        _pk1, _pk2 = st.columns([1, 3])
        _pick = _pk1.color_picker("색 직접 고르기", "#FFFFFF", key="ov_pick")
        if _pk2.button("이 색을 위 목록에 추가", key="ov_pick_add", help="추가한 색은 글자색/외곽선색/배경박스색 칸에서 고를 수 있습니다 (코드가 #RRGGBB로 자동 입력됨)"):
            if _pick.upper() not in _custom and _pick.lower() not in _h2n:
                _custom.append(_pick.upper())
            st.rerun()
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
                bgi = BV.make_template(t1, t2, BV.safe_country(it_o), None, channel_name=CH, handle=HD, avatar_path="avatar.png", title_opts=it_o.get("title_opts")).convert("RGB")
                sp = _vd(HERE, sel_o, it_o) / f"scene_{int(sc_prev):02d}.png"
                if sp.exists():
                    from layout import IMG_BOX
                    sc_img = _I.open(sp).convert("RGB")
                    bw, bh = IMG_BOX[2] - IMG_BOX[0], IMG_BOX[3] - IMG_BOX[1]
                    r = max(bw / sc_img.width, bh / sc_img.height)
                    sc_img = sc_img.resize((int(sc_img.width * r), int(sc_img.height * r)))
                    l, tp_ = (sc_img.width - bw) // 2, (sc_img.height - bh) // 2
                    bgi.paste(sc_img.crop((l, tp_, l + bw, tp_ + bh)), (IMG_BOX[0], IMG_BOX[1]))
                shown = OV.preview(OV.clean_list(rows_o), float(t_prev), bgi, show_grid=show_gr, images=it_o.get("image_overlays"), shapes=it_o.get("shape_overlays"))
                st.image(shown, caption=f"{t_prev}초 시점 (효과는 최종 모습으로 표시, 자막은 안 보임)", width=480)
            except Exception as e:
                st.error(f"미리보기 실패: {type(e).__name__}: {e}")

        # ---------------- 이미지 얹기 ----------------
        with st.expander("🖼 이미지 얹기 (근거 사진·캡처를 배경 장면 위에 추가, 배경은 그대로)", expanded=bool(it_o.get("image_overlays"))):
            st.caption("배경 이미지를 바꾸지 않고 그 위에 사진/캡처를 추가로 올립니다. 시작·지속(초), 위치(x,y %), 크기(화면 가로 대비 %), 효과를 정합니다. "
                       "이미지는 이 PC의 overlay_images 폴더에 저장되며, 이 기능으로 만든 영상은 PC에서 제작해야 합니다(GitHub 서버에는 이미지가 없음). 위 '미리보기'에도 같이 나옵니다.")
            os.makedirs("overlay_images", exist_ok=True)
            up_f = st.file_uploader("이미지 올리기 (png/jpg/webp, 여러 장 가능)", type=["png", "jpg", "jpeg", "webp"], accept_multiple_files=True, key=f"ovi_up_{sel_o}")
            if up_f and st.button("업로드한 이미지를 목록에 추가", key=f"ovi_add_{sel_o}"):
                from PIL import Image as _Ii
                db_o = _ld()
                cur = list(db_o[sel_o].get("image_overlays") or [])
                for k_, f_ in enumerate(up_f):
                    n_ = len([x for x in os.listdir("overlay_images") if x.startswith(f"{sel_o}_")]) + 1
                    pth = f"overlay_images/{sel_o}_{n_}.png"
                    _Ii.open(f_).convert("RGBA").save(pth)
                    cur.append({"image": pth, "start": round(1.0 + 3.0 * len(cur), 1), "dur": 3.0, "x": 50, "y": 45, "width": 60, "opacity": 1.0,
                                "rotate": 0, "border": "#FFFFFF", "bw": 6, "radius": 24, "shadow": True, "effect": "팝"})
                db_o[sel_o]["image_overlays"] = OV.clean_images(cur)
                _sd(db_o)
                st.rerun()
            _io = OV.clean_images(it_o.get("image_overlays") or [])
            icols = ["image", "start", "dur", "x", "y", "width", "crop_l", "crop_t", "crop_r", "crop_b", "opacity", "rotate", "border", "bw", "radius", "shadow", "effect"]
            idf = pd.DataFrame(_io, columns=icols)
            if idf.empty:
                st.info("올린 이미지가 없습니다. 위에서 이미지를 올리고 '목록에 추가'를 누르세요.")
            else:
                idf["border"] = idf["border"].map(lambda v: _to_name(v) or "없음")
                ied = st.data_editor(
                    idf, num_rows="dynamic", key=f"ovi_ed_{sel_o}_{abs(hash(str(_io))) % 10**8}", use_container_width=True, hide_index=True,
                    column_config={
                        "image": st.column_config.TextColumn("이미지 파일", disabled=True),
                        "start": st.column_config.NumberColumn("시작(초)", min_value=0.0, step=0.1),
                        "dur": st.column_config.NumberColumn("지속(초)", min_value=0.2, step=0.1),
                        "x": st.column_config.NumberColumn("x(%)", min_value=0, max_value=100, step=1, help="이미지 중심의 가로 위치"),
                        "y": st.column_config.NumberColumn("y(%)", min_value=0, max_value=100, step=1, help="이미지 중심의 세로 위치 (이미지 영역은 약 23~76%)"),
                        "width": st.column_config.NumberColumn("크기(가로 %)", min_value=5, max_value=100, step=5, help="화면 가로 대비 이미지 너비. 60이면 화면의 60%"),
                        "crop_l": st.column_config.NumberColumn("자르기 왼(%)", min_value=0, max_value=80, step=5, help="이미지 왼쪽을 이 % 만큼 잘라냄 (일부만 확대해 보여줄 때)"),
                        "crop_t": st.column_config.NumberColumn("자르기 위(%)", min_value=0, max_value=80, step=5),
                        "crop_r": st.column_config.NumberColumn("자르기 오른(%)", min_value=0, max_value=80, step=5),
                        "crop_b": st.column_config.NumberColumn("자르기 아래(%)", min_value=0, max_value=80, step=5),
                        "opacity": st.column_config.NumberColumn("투명도", min_value=0.1, max_value=1.0, step=0.1, help="1.0=불투명"),
                        "rotate": st.column_config.NumberColumn("기울기(도)", min_value=-45, max_value=45, step=1),
                        "border": st.column_config.SelectboxColumn("테두리색", options=_opts_o),
                        "bw": st.column_config.NumberColumn("테두리 굵기", min_value=0, max_value=30, step=1),
                        "radius": st.column_config.NumberColumn("모서리 둥글기", min_value=0, max_value=200, step=4),
                        "shadow": st.column_config.CheckboxColumn("그림자"),
                        "effect": st.column_config.SelectboxColumn("효과", options=OV.IMG_EFFECTS, help="팝/줌인(천천히 커짐)/흔들림/슬라이드/페이드/깜빡임"),
                    })
                irows = [{k: (None if (isinstance(v, float) and v != v) else v) for k, v in r.items()} for r in ied.to_dict("records")]
                for _r in irows:
                    _r["border"] = _to_hex(_r.get("border"))
                if st.button("이미지 설정 저장", key=f"ovi_save_{sel_o}", type="primary"):
                    db_o = _ld()
                    clean_i = OV.clean_images(irows)
                    if clean_i:
                        db_o[sel_o]["image_overlays"] = clean_i
                    else:
                        db_o[sel_o].pop("image_overlays", None)
                    _sd(db_o)
                    st.success(f"이미지 {len(clean_i)}개 저장. " + ("이미 만든 영상이면 redo에 번호를 넣고 5단계를 하세요." if it_o.get("video_path_v6") else "다음 렌더링에 반영됩니다."))
                    st.rerun()

        # ---------------- 도형 강조 (원·사각형·화살표) ----------------
        with st.expander("⭕ 도형 강조 (원 · 사각형 · 화살표)", expanded=bool(it_o.get("shape_overlays"))):
            st.caption("장면이나 얹은 이미지 위에 원/사각형/화살표로 강조합니다. 크기는 w(가로 %)·h(세로 %), 화살표는 w가 길이이고 angle로 방향을 정합니다 (0=오른쪽→, 90=아래↓, 180=왼쪽←, 270=위↑). "
                       "효과: 그리기(그려지듯 등장)/페이드/팝/맥박(커졌다 작아졌다)/깜빡임. 행을 추가하려면 표 맨 아래 빈 줄을 누르세요.")
            scols = ["type", "start", "dur", "x", "y", "w", "h", "angle", "color", "thick", "effect"]
            _so = OV.clean_shapes(it_o.get("shape_overlays") or [])
            sdf = pd.DataFrame(_so, columns=scols)
            if sdf.empty:
                sdf = pd.DataFrame([{"type": "원", "start": 2.0, "dur": 3.0, "x": 50, "y": 45, "w": 40, "h": 12, "angle": 0,
                                     "color": "빨강", "thick": 10, "effect": "그리기"}], columns=scols)
            else:
                sdf["color"] = sdf["color"].map(lambda v: _to_name(v) or "빨강")
            sed = st.data_editor(
                sdf, num_rows="dynamic", key=f"ovs_ed_{sel_o}_{abs(hash(str(_so))) % 10**8}", use_container_width=True, hide_index=True,
                column_config={
                    "type": st.column_config.SelectboxColumn("도형", options=OV.SHAPES),
                    "start": st.column_config.NumberColumn("시작(초)", min_value=0.0, step=0.1),
                    "dur": st.column_config.NumberColumn("지속(초)", min_value=0.2, step=0.1),
                    "x": st.column_config.NumberColumn("x(%)", min_value=0, max_value=100, step=1),
                    "y": st.column_config.NumberColumn("y(%)", min_value=0, max_value=100, step=1),
                    "w": st.column_config.NumberColumn("w 가로(%)", min_value=3, max_value=100, step=1, help="화면 가로 대비 크기 (화살표는 길이)"),
                    "h": st.column_config.NumberColumn("h 세로(%)", min_value=2, max_value=100, step=1, help="화면 세로 대비 크기 (화살표는 안 씀)"),
                    "angle": st.column_config.NumberColumn("방향(도)", min_value=-360, max_value=360, step=15, help="화살표만: 0=→ 90=↓ 180=← 270=↑"),
                    "color": st.column_config.SelectboxColumn("색", options=_opts_c),
                    "thick": st.column_config.NumberColumn("굵기", min_value=2, max_value=40, step=1),
                    "effect": st.column_config.SelectboxColumn("효과", options=OV.SHAPE_EFFECTS),
                })
            srows = [{k: (None if (isinstance(v, float) and v != v) else v) for k, v in r.items()} for r in sed.to_dict("records")]
            for _r in srows:
                _r["color"] = _to_hex(_r.get("color"))
            if st.button("도형 설정 저장", key=f"ovs_save_{sel_o}", type="primary"):
                db_o = _ld()
                clean_s = OV.clean_shapes(srows)
                if clean_s:
                    db_o[sel_o]["shape_overlays"] = clean_s
                else:
                    db_o[sel_o].pop("shape_overlays", None)
                _sd(db_o)
                st.success(f"도형 {len(clean_s)}개 저장. " + ("이미 만든 영상이면 redo에 번호를 넣고 5단계를 하세요." if it_o.get("video_path_v6") else "다음 렌더링에 반영됩니다."))
                st.rerun()

        # ---------------- 구간 영상 미리보기 (움직이는 효과 확인) ----------------
        with st.expander("▶ 구간 영상 미리보기 (문구·이미지·도형의 움직임 확인)"):
            st.caption("지정한 구간만 짧은 영상으로 만들어 효과를 확인합니다 (저장된 문구·이미지·도형 기준, 문구는 위 표의 현재 값). 배경은 정지 화면이고 자막·음성은 없으며 해상도는 절반입니다. 보통 5~20초 걸립니다.")
            vp1, vp2, vp3 = st.columns(3)
            v_t0 = vp1.number_input("시작(초)", 0.0, 600.0, 0.0, 0.5, key="ovv_t0")
            v_t1 = vp2.number_input("끝(초)", 0.5, 600.0, 6.0, 0.5, key="ovv_t1")
            v_sc = vp3.number_input("배경 장면 번호", 1, 6, 1, key="ovv_sc")
            if st.button("구간 영상 만들기", key="ovv_go"):
                try:
                    import build_video as BV
                    from PIL import Image as _I
                    from layout import IMG_BOX
                    t1_, t2_ = BV.split_title(it_o)
                    bgv = BV.make_template(t1_, t2_, BV.safe_country(it_o), None, channel_name=CH, handle=HD, avatar_path="avatar.png", title_opts=it_o.get("title_opts")).convert("RGB")
                    spv = _vd(HERE, sel_o, it_o) / f"scene_{int(v_sc):02d}.png"
                    if spv.exists():
                        sci = _I.open(spv).convert("RGB")
                        bw_, bh_ = IMG_BOX[2] - IMG_BOX[0], IMG_BOX[3] - IMG_BOX[1]
                        rr = max(bw_ / sci.width, bh_ / sci.height)
                        sci = sci.resize((int(sci.width * rr), int(sci.height * rr)))
                        l_, t_ = (sci.width - bw_) // 2, (sci.height - bh_) // 2
                        bgv.paste(sci.crop((l_, t_, l_ + bw_, t_ + bh_)), (IMG_BOX[0], IMG_BOX[1]))
                    outp = os.path.join("overlay_images", f"_preview_{sel_o}.mp4")
                    os.makedirs("overlay_images", exist_ok=True)
                    with st.spinner("구간 영상 만드는 중..."):
                        OV.render_preview_video(OV.clean_list(rows_o), it_o.get("image_overlays"), it_o.get("shape_overlays"), bgv, float(v_t0), float(v_t1), outp)
                    st.session_state["ovv_file"] = outp
                except Exception as e:
                    st.error(f"구간 영상 실패: {type(e).__name__}: {e}")
            if st.session_state.get("ovv_file") and os.path.exists(st.session_state["ovv_file"]):
                st.video(open(st.session_state["ovv_file"], "rb").read())

        # ---------------- 위치 잡기 (화면을 직접 클릭/드래그) ----------------
        with st.expander("🎯 위치 잡기 (화면을 클릭·드래그해서 도형·이미지 위치와 크기 정하기)"):
            try:
                from streamlit_image_coordinates import streamlit_image_coordinates as _sic
            except Exception:
                _sic = None
            if _sic is None:
                st.info("이 기능은 'streamlit-image-coordinates' 패키지가 필요합니다.")
                if st.button("지금 설치", key="sic_install"):
                    r_ = subprocess.run([sys.executable, "-m", "pip", "install", "streamlit-image-coordinates"], capture_output=True, text=True)
                    st.code((r_.stdout + r_.stderr)[-600:])
                    st.success("설치 끝. 화면을 새로고침(F5)하세요.") if r_.returncode == 0 else st.error("설치 실패")
            else:
                st.caption("저장된 도형·이미지를 고르고 화면에서 **클릭**하면 그 지점이 중심이 되고, **드래그**하면 상자 크기까지 정해집니다. "
                           "화살표는 꼬리에서 머리 방향으로 드래그하세요. 파란 상자가 지금 선택한 항목입니다. 적용하면 저장된 값이 바뀝니다 (표는 새로고침됨).")
                _sh = OV.clean_shapes(it_o.get("shape_overlays") or [])
                _im = OV.clean_images(it_o.get("image_overlays") or [])
                _tg = [("도형", i_) for i_ in range(len(_sh))] + [("이미지", i_) for i_ in range(len(_im))]
                if not _tg:
                    st.info("저장된 도형이나 이미지가 없습니다. 위에서 먼저 추가하고 저장하세요.")
                else:
                    _lab = lambda t_: (f"도형 {t_[1] + 1}: {_sh[t_[1]]['type']} ({_sh[t_[1]]['start']}초~)" if t_[0] == "도형"
                                       else f"이미지 {t_[1] + 1}: {os.path.basename(_im[t_[1]]['image'])} ({_im[t_[1]]['start']}초~)")
                    g1, g2, g3 = st.columns([2, 1, 1])
                    tgt = g1.selectbox("조정할 항목", _tg, format_func=_lab, key=f"pk_t_{sel_o}")
                    cur = (_sh if tgt[0] == "도형" else _im)[tgt[1]]
                    pk_t = g2.number_input("확인할 시점(초)", 0.0, 600.0, float(cur["start"]) + 0.5, 0.5, key=f"pk_time_{sel_o}_{tgt[0]}{tgt[1]}",
                                           help="이 시점에 보이는 화면 위에서 위치를 잡습니다. 다른 이미지 위에 도형을 얹을 땐 둘 다 보이는 시점으로")
                    pk_sc = g3.number_input("배경 장면", 1, 6, 1, key=f"pk_sc_{sel_o}")
                    pk_w = st.slider("화면 크기(px)", 300, 900, 560, 20, key="pk_width", help="크게 하면 더 정확하게 잡을 수 있습니다")
                    try:
                        import build_video as BV
                        from PIL import Image as _I, ImageDraw as _ID
                        from layout import IMG_BOX
                        t1_, t2_ = BV.split_title(it_o)
                        bgp = BV.make_template(t1_, t2_, BV.safe_country(it_o), None, channel_name=CH, handle=HD, avatar_path="avatar.png", title_opts=it_o.get("title_opts")).convert("RGB")
                        spp = _vd(HERE, sel_o, it_o) / f"scene_{int(pk_sc):02d}.png"
                        if spp.exists():
                            sci = _I.open(spp).convert("RGB")
                            bw_, bh_ = IMG_BOX[2] - IMG_BOX[0], IMG_BOX[3] - IMG_BOX[1]
                            rr = max(bw_ / sci.width, bh_ / sci.height)
                            sci = sci.resize((int(sci.width * rr), int(sci.height * rr)))
                            l_, t_ = (sci.width - bw_) // 2, (sci.height - bh_) // 2
                            bgp.paste(sci.crop((l_, t_, l_ + bw_, t_ + bh_)), (IMG_BOX[0], IMG_BOX[1]))
                        # 선택 항목이 그 시점에 항상 보이도록 시작 시간을 맞춰 그린다
                        def _show(item_list, idx, kind):
                            out = []
                            for j_, o_ in enumerate(item_list):
                                o2 = dict(o_)
                                if j_ == idx and kind:
                                    o2["start"], o2["dur"] = 0.0, 999.0
                                out.append(o2)
                            return out
                        shp_l = _show(_sh, tgt[1], tgt[0] == "도형")
                        img_l = _show(_im, tgt[1], tgt[0] == "이미지")
                        base_img = OV.preview(OV.clean_list(it_o.get("overlays") or []), float(pk_t), bgp, show_grid=True, images=img_l, shapes=shp_l)
                        # 선택 항목 테두리(파랑)
                        if tgt[0] == "도형":
                            cd_, cx_, cy_ = OV.render_shape(OV.normalize_shape(shp_l[tgt[1]]))
                        else:
                            rr_ = OV.render_image(OV.normalize_image(img_l[tgt[1]]))
                            cd_, cx_, cy_ = rr_ if rr_ else (None, 0, 0)
                        if cd_ is not None:
                            _ID.Draw(base_img).rectangle((cx_ - cd_.width / 2, cy_ - cd_.height / 2, cx_ + cd_.width / 2, cy_ + cd_.height / 2), outline=(0, 160, 255), width=6)
                        val = _sic(base_img, width=int(pk_w), click_and_drag=True, key=f"pk_img_{sel_o}_{tgt[0]}{tgt[1]}_{int(pk_sc)}")
                    except Exception as e:
                        val = None
                        st.error(f"화면 만들기 실패: {type(e).__name__}: {e}")
                    if val and val.get("width"):
                        k_ = 1080.0 / float(val["width"])
                        x1, y1 = float(val.get("x1", val.get("x", 0))) * k_, float(val.get("y1", val.get("y", 0))) * k_
                        x2, y2 = float(val.get("x2", val.get("x", 0))) * k_, float(val.get("y2", val.get("y", 0))) * k_
                        drag = abs(x2 - x1) > 20 or abs(y2 - y1) > 20
                        new = {"x": round((x1 + x2) / 2 / 1080 * 100, 1), "y": round((y1 + y2) / 2 / 1920 * 100, 1)}
                        if drag:
                            if tgt[0] == "도형" and cur["type"] == "화살표":
                                import math
                                new["w"] = round(math.hypot(x2 - x1, y2 - y1) / 1080 * 100, 1)
                                new["angle"] = round(math.degrees(math.atan2(y2 - y1, x2 - x1)), 0)
                            elif tgt[0] == "도형":
                                new["w"] = round(abs(x2 - x1) / 1080 * 100, 1)
                                new["h"] = round(abs(y2 - y1) / 1920 * 100, 1)
                            else:
                                new["width"] = round(abs(x2 - x1) / 1080 * 100, 1)
                        st.write("선택한 값: " + ", ".join(f"{k}={v}" for k, v in new.items()) + ("  (드래그: 크기 포함)" if drag else "  (클릭: 위치만)"))
                        try:   # 적용 후 모습 미리보기 (저장 전)
                            _pv_s, _pv_i = [dict(x) for x in shp_l], [dict(x) for x in img_l]
                            (_pv_s if tgt[0] == "도형" else _pv_i)[tgt[1]].update(new)
                            _after = OV.preview(OV.clean_list(it_o.get("overlays") or []), float(pk_t), bgp, show_grid=False, images=_pv_i, shapes=_pv_s)
                            st.image(_after, caption="적용 후 모습 (아직 저장 전)", width=int(pk_w))
                        except Exception as e:
                            st.caption(f"미리보기 실패: {e}")
                        if st.button("이 값으로 적용·저장", key=f"pk_apply_{sel_o}", type="primary"):
                            db_o = _ld()
                            key_ = "shape_overlays" if tgt[0] == "도형" else "image_overlays"
                            lst = list(db_o[sel_o].get(key_) or [])
                            # clean_* 이 항목 수를 바꾸지 않았다고 가정하고 같은 순서의 항목을 고침
                            norm_ = (OV.clean_shapes if tgt[0] == "도형" else OV.clean_images)(lst)
                            if tgt[1] < len(norm_):
                                norm_[tgt[1]].update(new)
                                db_o[sel_o][key_] = norm_
                                _sd(db_o)
                                st.success("저장했습니다. 위 표가 새 값으로 바뀝니다.")
                                st.rerun()

with T1c:
    with st.expander("🌍 나라 수정 · 나라와 주제가 안 맞는 소재 점검"):
        st.caption("나라 칸과 제목·주제·훅이 가리키는 나라가 다른 소재를 찾아 고칩니다. 목록 보기는 아무것도 안 바꿉니다. "
                   "자동 고치기: 영상이 아직 없는 소재는 나라가 하나로 분명하면 나라를 고치고 애매하면 폐기, 이미 영상이 있는 소재는 나라 칸만 고치고(애매하면 표시만) 폐기하지 않습니다.")
        if os.path.exists("check_country.py"):
            cc1, cc2 = st.columns(2)
            if cc1.button("🔍 불일치 목록 보기", key="cc_list"):
                run("check_country.py")
            if cc2.button("🛠 자동 고치기 적용", key="cc_apply"):
                run("check_country.py", "--apply")
        else:
            st.caption("이 채널에는 자동 점검 도구가 없어 아래에서 직접 고칩니다.")
        st.markdown("**한 소재만 직접 고치기**")
        m1, m2 = st.columns([1, 2])
        cc_i = m1.number_input("소재 번호", 0, 9999, 0, key="cc_i")
        _dbc = _ld()
        _cur = str(_dbc[int(cc_i)].get("country", "")) if 0 <= int(cc_i) < len(_dbc) else ""
        cc_new = m2.text_input("새 나라 이름", _cur, key=f"cc_new_{int(cc_i)}", help="나라 칸에 들어가는 이름 (한국어 채널은 한국어 이름)")
        if 0 <= int(cc_i) < len(_dbc):
            st.caption(f"현재: {_cur} / 주제: {str(_dbc[int(cc_i)].get('topic', ''))[:60]} / 영상 {'있음' if _dbc[int(cc_i)].get('video_path_v6') else '없음'}")
        if st.button("나라 바꾸기", key="cc_set") and 0 <= int(cc_i) < len(_dbc) and cc_new.strip() and cc_new.strip() != _cur:
            from common import visual_dir as _vdir
            _old_it = dict(_dbc[int(cc_i)])
            _dbc[int(cc_i)]["country"] = cc_new.strip()
            _od, _nd = _vdir(HERE, int(cc_i), _old_it), _vdir(HERE, int(cc_i), _dbc[int(cc_i)])
            if _od.exists() and not _nd.exists() and _od != _nd:     # 장면 이미지 폴더 이름도 새 나라로 맞춤
                _od.rename(_nd)
                st.write(f"이미지 폴더 이름 변경: {_od.name} → {_nd.name}")
            # 음성·타이밍 파일 이름에도 나라가 들어가므로 같이 바꾸고 DB의 경로 기록도 맞춘다
            from common import safe_country as _sc
            _ao, _an = f"{int(cc_i):04d}_{_sc(_old_it)}", f"{int(cc_i):04d}_{_sc(_dbc[int(cc_i)])}"
            _adir = Path(HERE) / "audio"
            if _adir.exists() and _ao != _an:
                for _fp in _adir.glob(_ao + "*"):
                    _np = _fp.with_name(_an + _fp.name[len(_ao):])
                    if not _np.exists():
                        _fp.rename(_np)
                        st.write(f"음성 파일 이름 변경: {_fp.name} → {_np.name}")
                for _k in ("audio_path_v2", "timing_path_v2"):
                    _v = _dbc[int(cc_i)].get(_k)
                    if _v and _ao in str(_v):
                        _dbc[int(cc_i)][_k] = str(_v).replace(_ao, _an)
            _sd(_dbc)
            st.session_state["gh_dirty"] = True
            st.success(f"[{int(cc_i)}] 나라: {_cur} → {cc_new.strip()}" + (" (이미 만든 영상·썸네일은 redo 후 다시 렌더링해야 새 나라로 바뀝니다)" if _old_it.get("video_path_v6") else ""))

with T2a:
    if os.path.exists("clean_hedges.py"):
        with st.expander("🧹 대본의 물러서는·회피하는 문장 지우기 (\"~는 다를 수 있습니다\" 등)"):
            st.caption("만든 대본에서 면책·단서 문장을 찾습니다. 목록 보기는 아무것도 안 바꿉니다. 지우기는 영상이 아직 없는 소재만 적용하고, 지운 소재는 음성을 다시 만들어야 합니다. "
                       "영상이 있는 소재는 목록에만 표시됩니다 (redo 후 지우고 음성부터 다시).")
            h1, h2 = st.columns(2)
            if h1.button("🔍 목록 보기", key="hd_list"):
                run("clean_hedges.py")
            if h2.button("🧹 영상 없는 대본에서 지우기", key="hd_apply"):
                run("clean_hedges.py", "--apply")

with T1d:
    st.caption("잘 터진 쇼츠·채널, 위키 급상승, 레딧 화제를 모아 소재 아이디어를 얻습니다. 결과는 trend_data.json에 캐시되고(오늘 조회한 검색어는 다시 호출 안 함), 추천은 판단 보조입니다.")
    _yk = os.environ.get("YOUTUBE_API_KEY", "").strip()
    k1, k2 = st.columns([3, 1])
    k1.markdown("**YOUTUBE_API_KEY**: " + (f"✅ 설정됨 (…{_yk[-4:]})" if _yk else "❌ 없음 — 아래에 입력하세요"))
    if k2.button("🔑 키 테스트", key="tr_keytest", disabled=not _yk, help="유튜브에 1유닛짜리 요청을 보내 키가 작동하는지 확인합니다"):
        run("trend_research.py", "--test-key")
    with st.expander("API 키 입력·저장 (이 PC의 .local_secrets.json에만 저장, GitHub에 안 올라감)"):
        _nk = st.text_input("YouTube Data API v3 키", type="password", key="tr_newkey")
        if st.button("저장", key="tr_savekey", disabled=not _nk.strip()):
            _SEC["youtube_api_key"] = _nk.strip(); os.environ["YOUTUBE_API_KEY"] = _nk.strip()
            json.dump(_SEC, open(SECRET_FILE, "w", encoding="utf-8"), ensure_ascii=False)
            st.success("저장했습니다"); st.rerun()
        st.caption("발급: console.cloud.google.com → 프로젝트 선택 → API 및 서비스 → 라이브러리에서 'YouTube Data API v3' 사용 설정 → 사용자 인증 정보 → API 키 만들기. 무료 한도는 하루 10,000유닛(키워드 1개 조회 ≈ 100유닛).")
    t_kw = st.text_input("조사 키워드 (쉼표) — 유튜브 검색 100유닛/개", "e.g. korean culture, korea travel tips" if EN else "세계 문화 상식, 나라별 금기, 해외 풍습", key="tr_kw")
    t1, t2, t3 = st.columns(3)
    t_days = t1.selectbox("기간(일)", [7, 14, 30, 90], 2, key="tr_days")
    t_units = t2.number_input("하루 사용 제한(유닛)", 500, 10000, 3000, 500, key="tr_units")
    t_mult = t3.number_input("터진 영상 기준(채널 중앙값의 N배)", 1.5, 10.0, 2.0, 0.5, key="tr_mult")
    t_ch = st.text_input("경쟁·참고 채널 (쉼표, @핸들·채널ID·주소)", "", key="tr_ch")
    t_rd = st.text_input("레딧 서브레딧 (쉼표)", "korea,Living_in_Korea,seoul" if EN else "todayilearned,travel,Damnthatsinteresting", key="tr_rd")
    w1, w2 = st.columns(2)
    t_wiki = w1.checkbox("위키 급상승 문서 (무료)", True, key="tr_wiki")
    t_an = w2.checkbox("끝나면 AI 분석·소재 추천 (Groq)", True, key="tr_an")
    if st.button("📈 조사 시작", key="tr_go", type="primary"):
        _a = []
        if t_kw.strip() and _yk and not t_kw.startswith("e.g."):
            _a += ["--yt", t_kw, "--days", str(t_days)]
        if t_ch.strip() and _yk:
            _a += ["--channels", t_ch, "--mult", str(t_mult)]
        if t_rd.strip():
            _a += ["--reddit", t_rd]
        if t_wiki:
            _a += ["--wiki"]
        if t_an:
            _a += ["--analyze"]
        if not _yk:
            st.warning("API 키가 없어 유튜브 조사는 건너뜁니다 (위키·레딧만 실행)")
        run("trend_research.py", *_a, "--max-units", str(int(t_units)))
    try:
        _TD = json.load(open("trend_data.json", encoding="utf-8"))
    except Exception:
        _TD = {}
    if _TD:
        _q = _TD.get("quota") or {}
        st.caption(f"마지막 조사: {_TD.get('updated', '-')} · 오늘 YouTube 사용량 {_q.get('used', 0) if _q.get('date') == __import__('datetime').date.today().isoformat() else 0}유닛")
        _an = _TD.get("analysis") or {}
        R1, R2, R3, R4 = st.tabs(["💡 추천 소재", "🎬 터진 영상", "📺 채널", "🌐 위키·레딧"])
        with R1:
            if not _an:
                st.info("아직 분석 결과가 없습니다. 조사 후 'AI 분석'을 켜서 실행하세요.")
            for _i, _t in enumerate(_an.get("topic_ideas", [])):
                with st.container(border=True):
                    st.markdown(f"**{_t.get('title', '')}**  \n🎯 {_t.get('need', '')} · 💗 {_t.get('emotion', '')}  \n_근거: {_t.get('why', '')} ({_t.get('source', '')})_")
                    if _t.get("dup"):
                        st.warning("⚠ 이미 만든 소재와 겹칠 수 있음: " + str(_t["dup"]))
                    if st.button("이걸로 소재 만들기 (승인 대기)", key=f"tr_mk_{_i}", disabled=bool(_t.get("dup")), help="중복 의심 소재는 막아 둡니다 (만든 뒤에도 같은 기준으로 한 번 더 검사)"):
                        _ids = run_cap("add_topic.py", "keyword", "--keyword", _t.get("title", ""), "--wiki")
                        after_create(_ids, False)
            if _an.get("patterns"):
                with st.expander("잘 터지는 제목 패턴 · 후크 · 니즈"):
                    for _p in _an["patterns"]:
                        st.markdown(f"- **{_p.get('name')}**: {_p.get('desc')} — 예) {_p.get('example')}")
                    st.markdown("**후크 유형**: " + ", ".join(map(str, _an.get("hooks", []))))
                    for _n in _an.get("needs", []):
                        st.markdown(f"- 니즈 **{_n.get('need')}**: {_n.get('evidence')}")
        with R2:
            _vs = _TD.get("videos") or []
            _sort = st.radio("정렬", ["조회수", "구독자 대비 조회수(작은 채널 대박)"], horizontal=True, key="tr_sort")
            _vs = sorted(_vs, key=(lambda v: -(v.get("views") or 0)) if _sort == "조회수" else (lambda v: -(v.get("ratio") or 0)))
            if _vs:
                st.dataframe([{"제목": v["title"], "조회수": v["views"], "구독자": v.get("subs"), "배율": v.get("ratio"), "길이(초)": v.get("secs"),
                               "게시일": v.get("published"), "채널": v.get("channel"), "검색어": v.get("kw"), "링크": v["url"]} for v in _vs[:150]],
                             use_container_width=True, hide_index=True, column_config={"링크": st.column_config.LinkColumn("링크", display_text="열기")})
            else:
                st.caption("영상 데이터가 없습니다 (API 키 필요)")
        with R3:
            _cs = _TD.get("channels") or []
            _vm = {v["id"]: v for v in _TD.get("videos", [])}
            for _c in _cs:
                st.markdown(f"**{_c.get('title')}** {_c.get('handle', '')} · 구독자 {_c.get('subs') if _c.get('subs') is not None else '비공개'} · 영상 중앙값 {_c.get('median_views', 0):,}회")
                for _h in _c.get("hits", []):
                    _v = _vm.get(_h)
                    if _v:
                        st.markdown(f"  - [{_v['title']}]({_v['url']}) · {_v['views']:,}회 (평균의 {_v.get('x_median')}배)")
            if not _cs:
                st.caption("채널 데이터가 없습니다. 위 '경쟁·참고 채널'에 입력하세요.")
        with R4:
            _w = _TD.get("wiki") or []
            if _w:
                st.markdown("**위키 급상승** (1주 전보다 순위가 오른 문서)")
                st.dataframe([{"문서": w["title"], "조회수": w["views"], "순위": w["rank"], "1주 전": w.get("prev_rank") or "-", "링크": w["url"]} for w in _w],
                             use_container_width=True, hide_index=True, column_config={"링크": st.column_config.LinkColumn("링크", display_text="열기")})
            _r = _TD.get("reddit") or []
            if _r:
                st.markdown("**레딧 화제글**")
                st.dataframe([{"출처": r["source"], "제목": r["title"][:110], "점수": r.get("score"), "링크": r["url"]} for r in _r],
                             use_container_width=True, hide_index=True, column_config={"링크": st.column_config.LinkColumn("링크", display_text="열기")})

with TL:
    _ext_panel('xl_', 1)
    st.caption("영상이 끝난 쇼츠를 묶어 가로 롱폼 1개로 만듭니다. 소재마다 음성/이미지를 다시 만들어서 시간이 걸립니다. 개수는 3~30개, 예상 40분 이하. facts_db.json과 별도로 longform_db.json에 기록됩니다.")
    lm = st.radio("선택 방식", ["auto (자동)", "manual (번호 직접)"], horizontal=True, key="lf_mode",
                  help="auto: 영상이 끝나고 롱폼에 안 쓴 소재를 번호순으로 / manual: 아래 번호들을 묶음")
    l1, l2, l3 = st.columns(3)
    lcount = l1.number_input("auto 개수", 3, 30, 6, key="lf_count")
    lstart = l2.number_input("auto 시작 번호", 0, 9999, 0 if EN else 0, key="lf_start", help="이 번호 이상인 소재만 후보")
    ltheme_free = l3.text_input("직접 입력 키워드 (쉼표로 여러 개)", key="lf_theme",
                                help="나라·분야·주제에 이 글자가 하나라도 들어 있으면 후보. 예: 음식, 일본. 비우면 조건 없이 번호순")
    ltheme = ltheme_free
    if lm.startswith("auto"):
        # 지금 롱폼 후보(영상 완료 + 아직 롱폼에 안 쓴 소재)에서 고를 수 있는 키워드를 보여줌
        _fdb = _ld()
        try:
            _used = {m_ for r_ in json.load(open("longform_db.json", encoding="utf-8")) for m_ in r_.get("members", [])}
        except Exception:
            _used = set()
        _pool = [i_ for i_, f_ in enumerate(_fdb) if i_ >= int(lstart) and f_.get("status") == "video_done" and str(f_.get("narration", "")).strip() and i_ not in _used]
        from collections import Counter
        _cc = Counter(str(_fdb[i_].get("country", "")).strip() for i_ in _pool)
        _tc = Counter(str(_fdb[i_].get("theme", "")).strip() for i_ in _pool)
        _wc = Counter()
        for i_ in _pool:
            for w_ in set(re.findall(r"[가-힣A-Za-z]{2,}", str(_fdb[i_].get("topic", "")))):
                _wc[w_] += 1
        _cc.pop("", None); _tc.pop("", None)
        st.caption(f"지금 후보 소재: **{len(_pool)}개** (영상 완료 · 아직 롱폼에 안 쓴 · 시작 번호 {int(lstart)} 이상). 아래에서 고르면 그 키워드가 들어간 소재만 후보가 됩니다. 아무것도 안 고르면 번호순.")
        k1, k2, k3 = st.columns(3)
        _pc = k1.multiselect("나라/대상", [c_ for c_, _ in _cc.most_common()], key="lf_kw_c", format_func=lambda c_: f"{c_} ({_cc[c_]})")
        _pt = k2.multiselect("분야", [t_ for t_, _ in _tc.most_common()], key="lf_kw_t", format_func=lambda t_: f"{t_} ({_tc[t_]})")
        _pw = k3.multiselect("자주 나온 주제 단어", [w_ for w_, n_ in _wc.most_common(40) if n_ >= 2], key="lf_kw_w", format_func=lambda w_: f"{w_} ({_wc[w_]})")
        _kws = [x.strip() for x in _pc + _pt + _pw + ltheme_free.split(",") if x.strip()]
        ltheme = ",".join(dict.fromkeys(_kws))
        if _kws:
            _lw = [x.lower() for x in _kws]
            _hit = [i_ for i_ in _pool if any(t_ in " ".join(str(_fdb[i_].get(k_, "")) for k_ in ("theme", "topic", "country", "title_line1", "title_line2")).lower() for t_ in _lw)]
            st.caption(f"선택한 키워드({', '.join(_kws)})에 맞는 후보: **{len(_hit)}개** " + ("→ " + ", ".join(f"{i_} {str(_fdb[i_].get('country', ''))[:10]}" for i_ in _hit[:12]) + (" …" if len(_hit) > 12 else "") if _hit else "(없음: 키워드를 바꾸세요)"))
    lidx = st.text_input("manual 번호 (예: 109,110,115-118)", key="lf_idx")
    ltitle = st.text_input("제목 (비우면 자동)", key="lf_title")
    lx1, lx2 = st.columns(2)
    lf_exc = lx1.text_input("🚫 제외할 번호 (auto/manual 공통, 예: 112,115)", key="lf_exc", help="자동으로 뽑힌 소재 중 원치 않는 번호를 빼고 그 자리는 다음 후보로 채웁니다")
    lf_add = lx2.text_input("➕ 꼭 넣을 번호 (예: 20,21)", key="lf_add", help="자동 개수에 포함되어 목록 끝에 붙습니다. 대본이 있고 폐기되지 않은 소재만 가능 (이미 롱폼에 쓴 소재도 넣을 수 있음)")
    lf_arr = st.checkbox("🔀 순서 자동 배치 (맨 앞에 가장 재밌는 소재, 중간에 흐름 유지용, 분야·나라가 이어지지 않게)", lm.startswith("auto"), key=f"lf_arr_{'a' if lm.startswith('auto') else 'm'}",
                         help="auto 기본 켜짐 / manual 기본 꺼짐(입력한 번호 순서 그대로). 켜면 manual도 번호 순서를 재배치하고, 끄면 auto도 번호순 그대로 씁니다. 순서는 ② 단계에서 직접 바꿀 수도 있습니다")
    sel_args = ["--mode", "auto" if lm.startswith("auto") else "manual", "--indexes", lidx, "--theme", ltheme,
                "--count", str(int(lcount)), "--start", str(int(lstart))] \
               + (["--exclude", lf_exc] if lf_exc.strip() else []) + (["--add", lf_add] if lf_add.strip() else []) \
               + (["--arrange"] if (lf_arr and not lm.startswith("auto")) else []) + (["--no-arrange"] if (not lf_arr and lm.startswith("auto")) else [])
    o1, o2, o3 = st.columns(3)
    lf_style = o1.selectbox("화면 스타일", ["rich (풀스크린·챕터카드·키워드·비교카드·인트로/요약)", "classic (예전: 오른쪽 흰 패널)"], key="lf_style")
    lf_expand = o2.checkbox("롱폼 전용 확장 대본 만들기 (Groq + 음성 새로 생성)", True, key="lf_expand", disabled=lf_style.startswith("classic"),
                            help="끄면 쇼츠 대본/음성을 그대로 이어 붙입니다. 켜면 소재마다 약 100~130초로 자세히 풀어 쓰고, 한국어는 나라끼리 / 영어는 한국 vs 다른 나라 비교 카드를 만듭니다")
    lf_regen = o3.checkbox("확장 대본 전부 다시 만들기", False, key="lf_regen", disabled=lf_style.startswith("classic") or not lf_expand,
                           help="저장된 확장 대본(longform_scripts.json)이 있어도 새로 씁니다. 직접 고친 대본도 덮어쓰니 주의")
    lf_clips = st.checkbox("🎞 스톡 영상(Pexels / Pixabay)을 일부 장면에 사용 (분위기용 B-roll, 소재당 최대 3개)", False, key="lf_clips",
                           disabled=lf_style.startswith("classic"),
                           help="PEXELS_API_KEY(무료) 또는 PIXABAY_API_KEY 필요. 검색어와 안 맞거나 못 받으면 사진을 씁니다. 용량과 합성 시간이 늘어납니다")
    if lf_clips:
        _pk = [n_ for n_ in ("PEXELS_API_KEY", "PIXABAY_API_KEY") if os.environ.get(n_, "").strip()]
        st.caption("스톡 영상 키: " + (", ".join(_pk) if _pk else "없음 → 사진만 사용됩니다 (PEXELS_API_KEY 환경변수 설정)"))
    with st.expander("✂️ 이미지 컷 · 후보 사진 고르기 · 내 사진 (영상 만들기 전에 사진 확정)", expanded=False):
        import cuts as _CU
        st.caption("컷 이름 = 소재번호_컷번호 (예: 117_03). ① 컷 시트·후보 만들기 → ② 후보 번호 고르기 → 적용. 직접 구한 사진은 아래에 올리거나 my_images 폴더에 `117_03.jpg`로 넣으면 "
                   "자동 검색보다 먼저 쓰입니다. GitHub 실행(Actions)과는 아래 버튼으로 my_images를 주고받습니다.")
        _DRAFT = Path("cut_picks_draft.json")
        try:
            _dr = json.loads(_DRAFT.read_text(encoding="utf-8"))
        except Exception:
            _dr = {}
        if "cut_idx" not in st.session_state and _dr.get("idx"):
            st.session_state["cut_idx"] = _dr["idx"]
        for _dk, _dv in (_dr.get("picks") or {}).items():          # 다시 켜도 고른 후보 번호를 복원
            st.session_state.setdefault(f"cut_pick_{_dk}", int(_dv))
        _ci = st.text_input("대상 소재 번호 (예: 117,118 / 비우면 위 manual 번호)", key="cut_idx")
        _cidx = (_ci or lidx or "").strip()
        c1_, c2_ = st.columns(2)
        if c1_.button("① 컷 시트 · 후보 사진 만들기", key="cut_make", disabled=not _cidx):
            run("build_longform.py", "--preview", "cuts", "--mode", "manual", "--indexes", _cidx, "--min", "1", "--start", "0")
        _cs = Path("longform_out/preview_cutsheet.txt")
        if _cs.exists():
            with st.expander("컷 시트 (이름 · 대략의 대본 · 검색어)", expanded=False):
                st.text(_cs.read_text(encoding="utf-8"))
                if Path("longform_out/preview_cutsheet.csv").exists():
                    st.download_button("컷 시트 CSV 받기", Path("longform_out/preview_cutsheet.csv").read_bytes(), "cutsheet.csv", key="cut_csv")
        try:
            from build_longform import parse_indexes as _pi
            _cl = _pi(_cidx) if _cidx else []
        except Exception:
            _cl = []
        _man = _CU._j(_CU.MANIFEST, {})
        _picks = {}
        for _i in _cl:
            _imgf = Path(f"longform_out/preview_cands_{_i}.jpg")
            _ks = sorted([k_ for k_ in _man if k_.startswith(f"{_i}_")], key=lambda k_: int(k_.split("_")[1]))
            if not _ks:
                continue
            st.markdown(f"**소재 {_i}**")
            if _imgf.exists():
                st.image(str(_imgf), use_container_width=True)
            _cols = st.columns(min(6, len(_ks)))
            for _n, _k in enumerate(_ks):
                _mine = _CU._my_file(_i, int(_k.split("_")[1]))
                _nc = len(_man[_k].get("cands", []))
                if st.session_state.get(f"cut_pick_{_k}", 0) > _nc:
                    st.session_state[f"cut_pick_{_k}"] = 0
                _v = _cols[_n % len(_cols)].selectbox(_k + (" ✅내 사진" if _mine else ""), [0] + list(range(1, _nc + 1)), key=f"cut_pick_{_k}",
                                                      format_func=lambda x: "선택 안 함" if x == 0 else f"후보 {x}")
                if _v:
                    _picks[_k] = _v
        try:   # 고른 후보 번호를 저장 (적용 전에 창을 닫아도 유지)
            _vis = {k_[len("cut_pick_"):]: v_ for k_, v_ in st.session_state.items() if k_.startswith("cut_pick_") and isinstance(v_, int)}
            _new = {"idx": _ci, "picks": {**(_dr.get("picks") or {}), **{k_: v_ for k_, v_ in _vis.items() if v_}}}
            for k_, v_ in _vis.items():
                if not v_:
                    _new["picks"].pop(k_, None)
            if _new != _dr:
                _DRAFT.write_text(json.dumps(_new, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass
        if _picks and c2_.button(f"② 고른 사진 적용 ({len(_picks)}컷)", key="cut_apply"):
            run("cuts.py", "--pick", ", ".join(f"{k_.split('_')[0]}_{int(k_.split('_')[1])}={v_}" for k_, v_ in _picks.items()))
            try:
                _DRAFT.unlink()
            except Exception:
                pass
        _up = st.file_uploader("내 사진 올리기 (파일 이름이 컷 이름이어야 함: 117_03.jpg)", type=["jpg", "jpeg", "png", "webp"], accept_multiple_files=True, key="cut_up")
        if _up and st.button("올린 사진을 my_images에 저장", key="cut_up_save"):
            _my = Path("my_images"); _my.mkdir(exist_ok=True)
            for _f in _up:
                if re.fullmatch(r"\d+_\d+\.(jpe?g|png|webp)", _f.name, re.I):
                    (_my / _f.name).write_bytes(_f.getvalue())
                    st.write(f"저장: {_f.name}")
                else:
                    st.warning(f"{_f.name}: 이름 형식이 맞지 않아 건너뜀 (예: 117_03.jpg)")
        with st.expander("📋 출처 한 번에 붙여넣기 (컷 / 저작권 / 원본링크 표)", expanded=False):
            st.caption("스프레드시트에서 3칸(컷 · 저작권 · 원본링크)을 복사해 붙여넣으세요. 컷 이름은 `40_01` 형식, 저작권 칸은 `작가, 라이선스, via Wikimedia Commons` 형식이면 "
                       "작가·라이선스·파일 제목을 자동으로 나눠 저장합니다. 이미 있는 출처는 같은 컷만 덮어씁니다. 비어 있는 줄은 건너뜁니다.")
            _pt_ = st.text_area("붙여넣기", height=160, key="cut_paste")
            if st.button("붙여넣은 출처 저장", key="cut_paste_save", disabled=not _pt_.strip()):
                _n_, _notes_ = _CU.save_pasted(_pt_)
                st.success(f"{_n_}개 컷의 출처를 저장했습니다.")
                if _notes_:
                    st.warning("확인 필요: " + " · ".join(_notes_[:40]))
        _mfs = sorted(f_ for f_ in Path("my_images").glob("*") if f_.suffix.lower() in _CU.EXT) if Path("my_images").exists() else []
        if _mfs:
            st.markdown("**내 사진 출처 입력** (직접 올린/고른 사진의 출처. 출처 구분에 따라 설명란 표기가 자동으로 들어갑니다)")
            st.caption("필요한 항목: " + " / ".join(f"**{k_}** → {v_}" for k_, v_ in _CU.GUIDE.items()))
            _crs = _CU._j(_CU.CREDITS, {})
            _rows = []
            for _f in _mfs:
                _c = _crs.get(_f.stem) or {}
                _k0 = _CU.kind_of(_c)
                _rows.append({"파일": _f.stem, "출처 구분": _k0, "라이선스": _c.get("license", "") if _k0.startswith("기타") else "", "작가": _c.get("user", ""),
                              "제목": _c.get("title", ""), "원본 링크": _c.get("page", ""),
                              "확인": _CU.credit_problems(_k0, _c.get("license", ""), _c.get("user", ""), _c.get("page", "")) if not _k0.startswith("자동") else ""})
            _ed = st.data_editor(_rows, hide_index=True, use_container_width=True, key="cut_cr_ed", num_rows="fixed",
                                 disabled=["파일", "확인"],
                                 column_config={"출처 구분": st.column_config.SelectboxColumn("출처 구분", options=_CU.KINDS, required=True, width="medium")})
            _edl = _ed if isinstance(_ed, list) else _ed.to_dict("records")
            _bad = [f"{r_['파일']}: {_CU.credit_problems(r_['출처 구분'], r_.get('라이선스', ''), r_.get('작가', ''), r_.get('원본 링크', ''))}" for r_ in _edl
                    if not r_["출처 구분"].startswith("자동") and _CU.credit_problems(r_["출처 구분"], r_.get("라이선스", ""), r_.get("작가", ""), r_.get("원본 링크", ""))
                    and r_["출처 구분"] != "미입력"]
            if _bad:
                st.warning("확인 필요: " + " · ".join(_bad))
            if st.button("💾 출처 저장", key="cut_cr_save"):
                _CU.save_credits(_edl)
                st.success("출처를 저장했습니다. 다음에 영상을 만들 때 설명란에 반영됩니다.")
        _mine_files = sorted(f_.name for f_ in Path("my_images").glob("*") if f_.suffix.lower() in _CU.EXT) if Path("my_images").exists() else []
        st.caption(f"my_images 에 있는 사진 {len(_mine_files)}장" + (": " + ", ".join(_mine_files[:30]) + (" ..." if len(_mine_files) > 30 else "") if _mine_files else ""))
        if st.button("📥 현재 사진을 my_images에 담기 (위 대상 소재 번호)", key="cut_freeze", disabled=not _cidx,
                     help="지금 PC에서 쓰는 장면 사진(visuals)을 컷 이름(40_09.png)으로 my_images에 복사하고 출처도 옮깁니다. 이미 my_images에 있는 컷은 그대로. "
                          "이걸 한 뒤 아래 ⬆ 버튼으로 GitHub에 올리면 GitHub에서도 같은 사진으로 다시 만들 수 있습니다"):
            run("cuts.py", "--freeze", _cidx)
        g1_, g2_ = st.columns(2)
        if g1_.button("⬇ GitHub에서 my_images 가져오기", key="cut_down"):
            run("cuts.py", "--sync", "down", "--repo", TTS_CFG["gh_repo"])
        if g2_.button("⬆ my_images를 GitHub로 올리기", key="cut_upgh", disabled=not _gh_token(), help="GITHUB_TOKEN 필요"):
            run("cuts.py", "--sync", "up", "--repo", TTS_CFG["gh_repo"])
    with st.expander("🎨 채널 표시 (이름 · 주소 · 이미지 · 켜기/끄기 · 문구)", expanded=False):
        import longform_render as _R
        _bf = _R.BRAND_FILE
        _B = _R.load_brand()
        st.caption("롱폼 화면 오른쪽 위(채널 이름·주소·이미지), 인트로, 엔딩의 채널 표시를 정합니다. 비워 두면 기본값(위쪽 채널 이름)을 씁니다. 저장하면 다음 롱폼부터 적용됩니다.")
        b1, b2 = st.columns(2)
        _B["channel"] = b1.text_input("표시할 채널 이름", _B.get("channel") or "", placeholder=CH, key="br_ch", help="화면에 나오는 이름. 영상 설명·제목에는 영향 없음")
        _B["handle"] = b2.text_input("채널 주소 (@…)", _B.get("handle") or "", placeholder=HD, key="br_hd")
        _up = st.file_uploader("채널 이미지 올리기 (png/jpg, 정사각형 권장)", type=["png", "jpg", "jpeg", "webp"], key="br_up")
        if _up is not None:
            from PIL import Image as _PI
            _im = _PI.open(_up).convert("RGB")
            _im.save("channel_avatar.png")
            _B["avatar"] = "channel_avatar.png"
            st.success("channel_avatar.png 로 저장했습니다. 아래 '저장'을 눌러 확정하세요.")
        _cur = _R.avatar_file(_B.get("avatar") or None)
        a1, a2 = st.columns([1, 4])
        if _cur:
            a1.image(_cur, width=96)
            a2.caption(f"현재 이미지: {_cur}")
        else:
            a1.image(_R.avatar(None, 96, _B.get("channel") or CH), width=96)
            a2.warning("채널 이미지 파일이 없어 이름 첫 글자 원으로 대신 나옵니다. 위에서 이미지를 올려 주세요. (이전에 파란 원만 나온 이유)")
        t1_, t2_, t3_ = st.columns(3)
        _B["recap"] = st.checkbox("마지막 요약 화면 + 엔딩 멘트 넣기", bool(_B.get("recap", True)), key="br_recap",
                                  help="끄면 마지막 챕터가 끝나고 바로 영상이 끝납니다 (요약 음성도 안 만들어 시간 절약). 깃허브에도 이 설정이 함께 올라갑니다")
        _B["recap_cards"] = st.checkbox("└ 챕터별 요약 카드 표시", bool(_B.get("recap_cards", True)), key="br_rcards", disabled=not _B["recap"],
                                        help="끄면 요약 카드(번호·나라·한 줄 요약 목록)는 화면에 안 나오고, 흐린 배경에 채널 이름만 보이면서 엔딩 멘트 음성만 나옵니다. 요약 화면 자체를 빼려면 위 체크를 끄세요")
        _B["compare"] = st.checkbox("챕터별 비교 카드 넣기", bool(_B.get("compare", True)), key="br_compare",
                                    help="끄면 저장된 비교 카드가 있어도 영상에 넣지 않고 오프닝 멘트의 비교 언급도 뺍니다 (AI가 다시 만들어도 다시 켜지지 않음). 깃허브에도 이 설정이 함께 올라갑니다")
        _B["hud"] = t1_.checkbox("오른쪽 위 채널 표시 켜기", bool(_B.get("hud", True)), key="br_hud")
        _B["hud_avatar"] = t1_.checkbox("└ 이미지", bool(_B.get("hud_avatar", True)), key="br_hav", disabled=not _B["hud"])
        _B["hud_name"] = t2_.checkbox("└ 채널 이름", bool(_B.get("hud_name", True)), key="br_hnm", disabled=not _B["hud"])
        _B["hud_handle"] = t2_.checkbox("└ 채널 주소", bool(_B.get("hud_handle", True)), key="br_hhd", disabled=not _B["hud"])
        _B["hud_pill"] = t3_.checkbox("뒤에 반투명 띠 깔기", bool(_B.get("hud_pill", True)), key="br_pill", disabled=not _B["hud"])
        _B["hud_text"] = st.text_input("오른쪽 위 문구 직접 입력 (비우면 이름 + 주소)", _B.get("hud_text") or "", key="br_htx", disabled=not _B["hud"])
        i1_, i2_ = st.columns(2)
        _B["intro_logo"] = i1_.checkbox("인트로에 채널 이미지 표시", bool(_B.get("intro_logo", True)), key="br_il")
        _B["intro_name"] = i2_.checkbox("인트로에 채널 이름 표시", bool(_B.get("intro_name", True)), key="br_in")
        _B["cta"] = st.text_input("엔딩 하단 띠 문구 (비우면 띠 안 나옴)", _B.get("cta") or "", key="br_cta")
        try:   # 미리보기: 오른쪽 위 표시
            _R.BRAND.update(_B)
            from PIL import Image as _PI2
            _hud = _R.make_hud(1, 6, "Japan" if EN else "일본", _B.get("channel") or CH, _B.get("handle") or HD, _B.get("avatar") or None, "")
            _bg = _PI2.new("RGBA", _hud.size, (92, 120, 150, 255))
            _bg.alpha_composite(_hud)
            st.image(_bg.crop((0, 0, _hud.size[0], 190)).convert("RGB"), caption="미리보기 (화면 윗부분)")
        except Exception as _e:
            st.caption(f"미리보기 실패: {type(_e).__name__}: {_e}")
        if st.button("💾 채널 표시 저장", key="br_save", type="primary"):
            json.dump(_B, open(_bf, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
            st.success("저장했습니다. 다음 롱폼부터 적용됩니다. (GitHub Actions에서도 쓰려면 동기화 탭에서 올리세요)")
    lf_fill = st.checkbox("🖼 빠진 사진은 합성 전에 자동으로 받아 채우기 (Pixabay/Commons)", True, key="lf_fill",
                          help="사진이 비어 있으면 색 카드로 대신 들어가므로, 먼저 받아서 채웁니다. PIXABAY_API_KEY 필요. 끄면 빠진 채로(또는 아래 설정에 따라 멈춤)")
    try:
        R_BRAND_RECAP = bool(json.load(open("longform_brand.json", encoding="utf-8")).get("recap", True))
        R_BRAND_COMPARE = bool(json.load(open("longform_brand.json", encoding="utf-8")).get("compare", True))
    except Exception:
        R_BRAND_RECAP = True
        R_BRAND_COMPARE = True
    lf_nomiss_deep = False
    common_args = ["--channel", CH, "--handle", HD, "--style", "classic" if lf_style.startswith("classic") else "rich"] \
        + ([] if lf_expand else ["--no-expand"]) + (["--clips"] if lf_clips else []) + (["--fill-images"] if lf_fill else [])
    base_args = ["build_longform.py"] + sel_args + common_args + (["--regen"] if lf_regen else [])

    with st.expander("🔭 심층편 (소재 1개 → 소주제 여러 개로 나눠 긴 영상 1편)", expanded=False):
        st.caption("소재 번호 1개를 넣으면 소주제(배경·생활·비교·디테일·여행자 팁…)로 나눠 한 편으로 만듭니다. 소주제 개수와 목표 길이로 섹션당 글자 수가 정해져서 "
                   "AI가 그 분량에 맞춰 씁니다. ① 대본 만들기 → 아래에서 확인/수정(잠금) → ② 심층편 만들기.")
        d1, d2, d3 = st.columns(3)
        _dsrc = d1.number_input("소재 번호", min_value=0, value=0, step=1, key="deep_src")
        _dsec = d2.slider("소주제 개수", 3, 8, 5, key="deep_sec")
        _dmin = d3.slider("목표 길이 (분)", 5, 12, 8, key="deep_min")
        _drecap = st.checkbox("마지막 요약 화면 + 엔딩 멘트 넣기", bool(R_BRAND_RECAP), key="deep_recap", help="끄면 마지막 소주제에서 바로 끝납니다 (채널 표시 설정과 별개로 이번 실행에만 적용)")
        _dcards = st.checkbox("└ 챕터별 요약 카드 표시 (끄면 엔딩 멘트 음성만)", True, key="deep_cards", disabled=not _drecap)
        _dcmp = st.checkbox("소주제별 비교 카드 넣기", bool(R_BRAND_COMPARE), key="deep_compare", help="끄면 이번 실행에만 비교 카드를 쓰지 않습니다 (채널 표시 설정과 별개)")
        _dins = st.text_input("AI 추가 지시 (선택, 예: 한국과 비교를 더 자세히)", key="deep_ins")
        _dargs = ["build_longform.py", "--deep", "--indexes", str(int(_dsrc)), "--sections", str(_dsec), "--minutes", str(_dmin)] + common_args
        e1, e2 = st.columns(2)
        if e1.button("① 심층편 대본 만들기", key="deep_plan_go", help="음성/영상 없이 섹션 대본만 AI로 씁니다. 이미 있는 대본(잠금 포함)은 재사용"):
            run(*_dargs, "--plan-only", *(["--instruction", _dins] if _dins else []))
            st.rerun()
        if e2.button("② 심층편 만들기 (음성 + 영상 합성)", key="deep_run", type="primary"):
            TIMES.clear()
            run(*_dargs, "--require-images" if not lf_nomiss_deep else "--fill-images", *([] if _drecap else ["--no-recap"]), *([] if _dcmp else ["--no-compare"]), *([] if (_dcards or not _drecap) else ["--no-recap-cards"]), "--title", ltitle)
        try:
            import deep as _DP
            _dd = _DP.load().get(str(int(_dsrc)))
        except Exception:
            _dd = None
        if _dd:
            import pandas as pd
            st.caption(f"저장된 심층편 대본: 소주제 {len(_dd['sections'])}개 · 만든 때 {_dd.get('created', '')}  (개수/길이를 바꾸면 ①이 새로 씁니다. 잠금된 섹션은 유지)")
            _df = pd.DataFrame([{"잠금": bool(x.get("locked")), "소제목": x.get("title", ""), "요약": x.get("recap", ""), "나레이션": x.get("narration", ""),
                                 "글자수": len(x.get("narration", ""))} for x in _dd["sections"]])
            _ed = st.data_editor(_df, key=f"deep_ed_{int(_dsrc)}", use_container_width=True, hide_index=True, disabled=["글자수"],
                                 column_config={"나레이션": st.column_config.TextColumn(width="large")})
            if st.button("수정한 대본 저장 · 잠금", key="deep_save"):
                for k_, r_ in _ed.iterrows():
                    x_ = _dd["sections"][k_]
                    if r_["나레이션"] != x_.get("narration"):
                        x_["narration"] = str(r_["나레이션"]).strip(); x_["keywords"] = [kw for kw in x_.get("keywords", []) if True]; x_["locked"] = True
                    else:
                        x_["locked"] = bool(r_["잠금"])
                    x_["title"] = str(r_["소제목"]).strip() or x_.get("title", "")
                    x_["recap"] = str(r_["요약"]).strip()
                _all = _DP.load(); _all[str(int(_dsrc))] = _dd; _DP.save(_all)
                st.success("저장했습니다 (수정한 섹션은 잠금)."); st.rerun()

    def _lf_plan():
        try:
            return json.load(open("longform_plan.json", encoding="utf-8"))
        except Exception:
            return None
    plan = _lf_plan()
    st.markdown("##### ① 대본·시나리오 만들기 → ② 확인/수정 → ③ 롱폼 만들기")
    c1, c2, c3 = st.columns(3)
    if c1.button("목록만 보기", key="lf_dry", help="어떤 소재가 묶일지만 보여줌 (영상 안 만듦)"):
        run(*base_args, "--dry-run")
    if c2.button("① 대본·시나리오 만들기", key="lf_plan_go", disabled=lf_style.startswith("classic") or not lf_expand,
                 help="음성/영상 없이 대본만 AI로 쓰고(이미 있으면 재사용) 아래에 시나리오로 보여줍니다. 몇 초 ~ 1분 정도"):
        run(*base_args, "--plan-only")
        st.rerun()
    use_plan = c3.checkbox("③에서 아래 확인한 소재 구성을 사용", bool(plan), key="lf_use_plan", disabled=not plan,
                           help="① 때 정해진 소재 목록(번호 순서)으로 만듭니다. 끄면 위의 선택 방식(auto/manual)을 다시 적용합니다")
    render_args = list(base_args)
    if plan and use_plan:
        render_args = ["build_longform.py", "--mode", "manual", "--indexes", ",".join(str(i) for i in plan["members"])] + common_args \
                      + (["--relink"] if plan.get("order_changed") else [])
    lf_nomiss = st.checkbox("이미지가 빠진 소재가 있어도 그냥 진행 (빠진 자리는 색 카드)", False, key="lf_nomiss",
                            help="끄면 사진이 빠진 소재가 있을 때 합성 전에 멈추고 어느 소재인지 알려줍니다. ②의 챕터별 '사진 확인'에서 미리 볼 수 있어요")
    if not lf_nomiss:
        render_args += ["--require-images"]
    if st.button("③ 롱폼 만들기 (음성 + 영상 합성)", key="lf_run", type="primary",
                 help="수정한 대본으로 음성을 새로 만들고 영상으로 합성합니다 (오래 걸림, 진행률이 10%마다 표시됨)"):
        TIMES.clear(); run(*render_args, "--title", ltitle)

    # ---------------- ② 대본·시나리오 확인/수정
    if plan and not lf_style.startswith("classic"):
        import pandas as pd
        import longform_script as LS
        from common import load_db as _ldl
        _dbl = _ldl()
        st.markdown("### ② 대본 · 시나리오 확인/수정")
        st.caption(f"소재 {len(plan['members'])}개 (만든 시각 {plan.get('created', '')}). 고친 내용은 '저장'을 눌러야 반영되고, 저장한 대본은 ③에서 AI가 덮어쓰지 않습니다(잠금). 나레이션을 고치면 ③에서 음성이 새로 만들어집니다.")
        if os.path.exists("longform_plan.txt"):
            st.download_button("시나리오 전체 txt 받기", open("longform_plan.txt", "rb").read(), file_name="longform_plan.txt", key="lf_plan_dl")

        _recs_all = {i_: LS.get_rec(i_) for i_ in plan["members"]}
        _cn = [str(_dbl[i_].get("country", "")).strip() for i_ in plan["members"] if 0 <= i_ < len(_dbl)]
        _auto_in = LS.intro_text(_cn, len(plan["members"]), [str((_recs_all[i_].get("compare") or {}).get("right") or "") for i_ in plan["members"]])
        _auto_out = LS.outro_text([(_recs_all[i_].get("recap") or str(_dbl[i_].get("topic", ""))) for i_ in plan["members"] if 0 <= i_ < len(_dbl)])
        with st.expander("🎤 오프닝 · 엔딩 멘트 (수정 가능)", expanded=False):
            st.caption("오프닝은 영상 맨 앞 소개, 엔딩은 '오늘의 요약' 화면에서 읽는 멘트입니다. 고치면 ③에서 이 문구로 음성을 새로 만듭니다. 비우거나 '자동 문구로 되돌리기'를 누르면 자동 문구를 씁니다.")
            _in_t = st.text_area("오프닝 멘트", plan.get("intro_text") or _auto_in, height=110, key=f"lf_intro_txt_{abs(hash(str(plan.get('intro_text'))))}")
            _out_t = st.text_area("엔딩 멘트 (요약 + 인사)", plan.get("outro_text") or _auto_out, height=170, key=f"lf_outro_txt_{abs(hash(str(plan.get('outro_text'))))}")
            _cps = 13.0 if EN else 6.0
            st.caption(f"예상 길이: 오프닝 약 {int(len(re.sub(chr(32), '', _in_t)) / _cps)}초 · 엔딩 약 {int(len(re.sub(chr(32), '', _out_t)) / _cps)}초. 마지막에 인사까지 끝나도록 문장을 마침표로 끝내세요.")
            m1, m2 = st.columns(2)
            if m1.button("💾 멘트 저장", key="lf_txt_save", type="primary"):
                _pl = _lf_plan() or {}
                for _k, _v, _a in (("intro_text", _in_t.strip(), _auto_in), ("outro_text", _out_t.strip(), _auto_out)):
                    if _v and _v != _a.strip():
                        _pl[_k] = _v
                    else:
                        _pl.pop(_k, None)
                json.dump(_pl, open("longform_plan.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
                st.success("저장했습니다."); st.rerun()
            if m2.button("↩ 자동 문구로 되돌리기", key="lf_txt_reset"):
                _pl = _lf_plan() or {}
                _pl.pop("intro_text", None); _pl.pop("outro_text", None)
                json.dump(_pl, open("longform_plan.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
                st.rerun()
        try:
            import build_video as _BV0
            _lack = []
            for i_ in plan["members"]:
                if 0 <= i_ < len(_dbl):
                    _ps = _BV0.get_visual_paths(i_, _dbl[i_])
                    _ms = [n_ + 1 for n_, p_ in enumerate(_ps) if not os.path.exists(p_)]
                    if _ms or not _ps:
                        _lack.append(f"{i_} {_dbl[i_].get('country', '')} ({', '.join(map(str, _ms)) or '전부'}번 없음)")
            if _lack:
                st.warning("🖼 사진이 빠진 소재: " + " / ".join(_lack) + "  — 챕터를 펼쳐 '빠진 사진 받기'를 누르거나 '3 이미지' 탭에서 받으세요. 이대로 ③을 누르면 멈춥니다(위 '그냥 진행'을 켜지 않았다면).")
            else:
                st.success("🖼 모든 소재의 사진이 있습니다.")
        except Exception:
            pass

        def _save_order(_m, changed=True):
            _pl = _lf_plan() or {}
            _pl["members"] = list(_m)
            _pl["order_changed"] = bool(changed)
            for _k in ("intro_text", "outro_text"):      # 순서가 바뀌면 고쳐 둔 오프닝/엔딩 멘트의 나라 순서도 어긋나므로 자동 문구로 돌린다
                _pl.pop(_k, None)
            json.dump(_pl, open("longform_plan.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)

        with st.expander("↕ 챕터 순서 바꾸기 · 자동 배치", expanded=bool(plan.get("order_changed"))):
            st.caption("⬆⬇로 순서를 바꾸면 각 챕터 마지막의 '다음 소재로 넘어가는' 문장만 새 순서에 맞게 다시 씁니다 (나머지 대본·키워드·사진 지정은 그대로). 바꾼 뒤 '🔗 연결 멘트 다시 쓰기'를 누르거나, ③에서 만들 때 자동으로 맞춥니다. 오프닝/엔딩 멘트는 자동 문구로 돌아갑니다.")
            _mem = list(plan["members"])
            for _p, _i in enumerate(_mem):
                if not (0 <= _i < len(_dbl)):
                    continue
                _rc = st.columns([10, 1, 1, 1])
                if _rc[3].button("✖", key=f"lf_rm_{_i}", disabled=len(_mem) <= 1, help="이 소재를 롱폼에서 뺍니다"):
                    _save_order([m_ for m_ in _mem if m_ != _i]); st.rerun()
                _rc[0].markdown(f"**{_p + 1}.** [{_i}] {_dbl[_i].get('country', '')} — {str(_dbl[_i].get('topic', ''))[:44]}")
                if _rc[1].button("⬆", key=f"lf_up_{_i}", disabled=_p == 0):
                    _mem[_p - 1], _mem[_p] = _mem[_p], _mem[_p - 1]
                    _save_order(_mem); st.rerun()
                if _rc[2].button("⬇", key=f"lf_dn_{_i}", disabled=_p == len(_mem) - 1):
                    _mem[_p + 1], _mem[_p] = _mem[_p], _mem[_p + 1]
                    _save_order(_mem); st.rerun()
            _n1, _n2 = st.columns([3, 1])
            _newn = _n1.text_input("➕ 소재 번호 추가 (예: 20 또는 20,21)", key="lf_addn")
            if _n2.button("추가", key="lf_addn_btn"):
                try:
                    import build_longform as _BL
                    _ad = [x for x in _BL.parse_indexes(_newn) if x not in _mem]
                    _BL._check_add(_dbl, _ad)
                    if _ad:
                        _save_order(_mem + _ad); st.rerun()
                    else:
                        st.info("이미 목록에 있는 번호입니다.")
                except SystemExit as _e:
                    st.error(str(_e))
                except Exception as _e:
                    st.error(f"추가 실패: {type(_e).__name__}: {_e}")
            _a1, _a2 = st.columns(2)
            if _a1.button("🔀 재미 순서로 자동 배치", key="lf_arr_btn", help="맨 앞에 가장 재밌는 소재, 중간(약 60%)에 다음으로 강한 소재, 마지막에 그다음 소재. 유튜브 성과 데이터가 있으면 그걸, 없으면 훅 문장으로 판단합니다"):
                try:
                    import build_longform as _BL
                    _new = _BL.order_members(_dbl, _mem)
                    if _new != _mem:
                        _save_order(_new); st.rerun()
                    else:
                        st.info("이미 이 순서가 자동 배치 결과와 같습니다.")
                except Exception as _e:
                    st.error(f"자동 배치 실패: {type(_e).__name__}: {_e}")
            if plan.get("order_changed"):
                st.warning("순서가 바뀌었습니다. 연결 멘트(각 챕터 마지막 문장)를 새 순서에 맞게 다시 써야 합니다.")
            if _a2.button("🔗 연결 멘트 다시 쓰기", key="lf_relink", type="primary", disabled=not plan.get("order_changed"),
                          help="순서에 맞게 각 챕터 마지막 문장만 AI로 다시 씁니다 (챕터당 약 400토큰). 음성은 ③에서 다시 만들어집니다"):
                run("build_longform.py", "--mode", "manual", "--indexes", ",".join(str(i) for i in _mem), *common_args, "--plan-only", "--relink")
                st.rerun()

        def _nan(v):
            try:
                return None if v is None or (isinstance(v, float) and v != v) else v
            except Exception:
                return v

        def _int(v, lo=1, hi=999):
            v = _nan(v)
            try:
                n_ = int(float(v))
            except (TypeError, ValueError):
                return None
            return n_ if lo <= n_ <= hi else None

        for no_, idx_ in enumerate(plan["members"], 1):
            if not (0 <= idx_ < len(_dbl)):
                continue
            it_ = _dbl[idx_]
            rec_ = LS.get_rec(idx_)
            if not rec_.get("narration"):
                st.warning(f"{idx_} {it_.get('country', '')}: 저장된 대본이 없습니다. ①을 다시 눌러 주세요.")
                continue
            ver_ = abs(hash(str(rec_.get("created", "")) + str(rec_.get("edited", "")))) % 100000
            k_ = f"{idx_}_{ver_}"
            n_scn = max(1, int(it_.get("scene_count") or 6))
            qs_ = list(it_.get("image_queries") or [])
            with st.expander(f"{no_}. [{idx_}] {it_.get('country', '')} — {it_.get('topic', '')}   ·   {len(rec_['narration'])}자" + ("   ✏️ 수정됨(잠금)" if rec_.get("locked") else ""), expanded=(no_ == 1)):
                narr_ = st.text_area("나레이션 (문장은 마침표/물음표로 끝내세요. 마지막 문장은 다음 챕터로 넘어가는 연결 멘트)", rec_["narration"], height=260, key=f"lfn_{k_}")
                sents_ = LS.split_sentences(narr_)
                chars_ = len(re.sub(r"\s+", "", narr_))
                est_ = chars_ / (13.0 if EN else 6.0)
                if narr_.strip() != rec_["narration"].strip():
                    _was = len(LS.split_sentences(rec_["narration"]))
                    st.info("✏️ 대본을 고치는 중입니다. 저장하면 이 대본으로 음성을 새로 만듭니다. 키워드 팝업·화면 지정은 '문장 번호' 기준이라 자동으로 바뀌지 않습니다"
                            + (f" (문장 수 {_was}→{len(sents_)}개로 바뀌어 번호가 어긋날 수 있어요)" if _was != len(sents_) else "")
                            + ". 저장한 뒤 아래 '🔁 이 대본에 맞춰 다시 만들기'를 누르면 AI가 키워드·비교 카드·요약·영상 검색어를 새 글에 맞춰 다시 만듭니다.")
                st.caption(f"문장 {len(sents_)}개 · {chars_}자 · 예상 {int(est_ // 60)}분 {int(est_ % 60)}초 (음성을 만들면 정확한 길이가 나옵니다)")
                t1c, t2c = st.columns(2)
                import build_video as _BV
                _d1, _d2 = _BV.split_title(it_)
                title1_ = t1c.text_input("챕터 제목 1줄 (화면 왼쪽 아래 박스)", rec_.get("title1") or _d1, key=f"lft1_{k_}")
                title2_ = t2c.text_input("챕터 제목 2줄 (강조색)", rec_.get("title2") or _d2, key=f"lft2_{k_}")
                st.markdown("**키워드 팝업** — 몇 번째 문장이 읽힐 때 어떤 큰 글자를 띄울지 (표에서 추가/삭제 가능)")
                kdf = pd.DataFrame([{"문장번호": k["sentence"], "문구": k["text"]} for k in (rec_.get("keywords") or [])] or [{"문장번호": 1, "문구": ""}])
                kdf = st.data_editor(kdf, num_rows="dynamic", key=f"lfk_{k_}", use_container_width=True, hide_index=True)
                st.markdown("**비교 카드**")
                cmp0 = rec_.get("compare") or {}
                use_cmp = st.checkbox("비교 카드 사용", bool(cmp0.get("rows")), key=f"lfcu_{k_}")
                cc1, cc2, cc3, cc4 = st.columns([2, 1, 1, 1])
                cmp_title = cc1.text_input("카드 제목", cmp0.get("title", ""), key=f"lfct_{k_}", disabled=not use_cmp)
                cmp_left = cc2.text_input("왼쪽", cmp0.get("left", "Korea" if EN else it_.get("country", "")), key=f"lfcl_{k_}", disabled=not use_cmp)
                cmp_right = cc3.text_input("오른쪽", cmp0.get("right", ""), key=f"lfcr_{k_}", disabled=not use_cmp)
                cmp_at = cc4.number_input("나올 문장 번호 (0=자동)", 0, max(1, len(sents_)), int(rec_.get("compare_at") or 0), key=f"lfca_{k_}", disabled=not use_cmp)
                rdf = pd.DataFrame([{"항목": r["label"], "왼쪽": r["left"], "오른쪽": r["right"]} for r in (cmp0.get("rows") or [])] or [{"항목": "", "왼쪽": "", "오른쪽": ""}])
                rdf = st.data_editor(rdf, num_rows="dynamic", key=f"lfcrw_{k_}", use_container_width=True, hide_index=True, disabled=not use_cmp)
                st.markdown(f"**화면(사진/영상) 지정** — 비워 두면 자동 배치. 문장번호부터 해당 사진(1~{n_scn}) 또는 영상(1~3)을 보여줍니다")
                cu0 = [{"문장번호": c.get("sentence"), "사진번호": c.get("scene"), "영상번호": c.get("clip")} for c in (rec_.get("images") or []) if isinstance(c, dict)]
                cdf = st.data_editor(pd.DataFrame(cu0 or [{"문장번호": None, "사진번호": None, "영상번호": None}]), num_rows="dynamic",
                                     key=f"lfcue_{k_}", use_container_width=True, hide_index=True)
                st.markdown("**사진 · 영상 확인**")
                try:
                    import build_video as _BV1
                    _pp = _BV1.get_visual_paths(idx_, it_)
                except Exception:
                    _pp = []
                _have = [(n_ + 1, p_) for n_, p_ in enumerate(_pp) if os.path.exists(p_)]
                _no = [n_ + 1 for n_, p_ in enumerate(_pp) if not os.path.exists(p_)]
                if _have:
                    _gc = st.columns(min(6, len(_have)))
                    for _j, (_n, _p) in enumerate(_have):
                        _gc[_j % len(_gc)].image(_p, caption=f"사진 {_n}", use_container_width=True)
                if _no or not _pp:
                    st.error(f"사진 {', '.join(map(str, _no)) or '전부'}번이 없습니다 (이대로 합성하면 색 카드로 대신 들어갑니다).")
                    if st.button("🖼 빠진 사진 받기", key=f"lfimg_{k_}"):
                        run("fetch_images.py", "--index", str(idx_)); st.rerun()
                elif _pp:
                    st.caption(f"사진 {len(_pp)}장 모두 있음. 마음에 안 들면 '3 이미지 › 검수·교체'에서 바꾸세요.")
                _clips_cur = [dict(c_) for c_ in (rec_.get("clips") or []) if isinstance(c_, dict)]
                _clip_use = []
                if _clips_cur:
                    _cc = st.columns(min(3, len(_clips_cur)))
                    for _j, _c in enumerate(_clips_cur):
                        with _cc[_j % len(_cc)]:
                            if _c.get("path") and os.path.exists(_c["path"]):
                                st.video(_c["path"])
                            _clip_use.append(st.checkbox(f"영상 {_j + 1} 사용" + (f" ({_c.get('query', '')[:20]})" if _c.get("query") else ""), bool(_c.get("use", True)), key=f"lfcu{_j}_{k_}"))
                elif lf_clips:
                    st.caption("스톡 영상: 아직 없음 (③을 실행하면 받아 옵니다. 한 번 받은 뒤 여기서 미리 보고 끌 수 있어요)")
                if qs_:
                    st.caption("사진 검색어: " + " / ".join(f"{i + 1}. {q}" for i, q in enumerate(qs_)) + "  (사진 교체는 '이미지 검수/교체' 탭)")
                cq0 = list(rec_.get("clip_queries") or rec_.get("broll") or [])
                cq_cols = st.columns(3)
                clipq_ = [cq_cols[i].text_input(f"영상 {i + 1} 검색어 (영어)", cq0[i] if i < len(cq0) else "", key=f"lfcq{i}_{k_}") for i in range(3)]
                recap_ = st.text_input("마지막 요약 화면 한 줄", rec_.get("recap", ""), key=f"lfrc_{k_}")

                # 현재 입력값으로 만든 임시 rec (저장 전에도 시나리오 표에 바로 반영)
                kws_ = []
                for r in kdf.to_dict("records"):
                    n_ = _int(r.get("문장번호"), 1, max(1, len(sents_)))
                    t_ = str(_nan(r.get("문구")) or "").strip()
                    if n_ and t_:
                        kws_.append({"sentence": n_, "text": t_[:28]})
                rows_ = []
                for r in rdf.to_dict("records"):
                    a_, b_, c_ = (str(_nan(r.get(x)) or "").strip() for x in ("항목", "왼쪽", "오른쪽"))
                    if a_ and b_ and c_:
                        rows_.append({"label": a_[:24], "left": b_[:30], "right": c_[:30]})
                compare_ = ({"title": cmp_title.strip()[:40], "left": ("Korea" if EN else cmp_left.strip()[:24]), "right": cmp_right.strip()[:24], "rows": rows_[:4]}
                            if use_cmp and len(rows_) >= 2 and cmp_right.strip() else None)
                cues_ = []
                for r in cdf.to_dict("records"):
                    n_ = _int(r.get("문장번호"), 1, max(1, len(sents_)))
                    sc_, cl_ = _int(r.get("사진번호"), 1, n_scn), _int(r.get("영상번호"), 1, 3)
                    if n_ and cl_:
                        cues_.append({"sentence": n_, "clip": cl_})
                    elif n_ and sc_:
                        cues_.append({"sentence": n_, "scene": sc_})
                tmp_ = {**rec_, "narration": narr_, "keywords": kws_, "compare": compare_, "compare_at": int(cmp_at) if compare_ else 0,
                        "recap": recap_.strip(), "images": cues_, "title1": title1_.strip(), "title2": title2_.strip()}
                sv1, sv2, sv3 = st.columns(3)
                if sv1.button("💾 저장 (이 대본으로 잠금)", key=f"lfsave_{k_}", type="primary"):
                    LS.update_rec(idx_, {"narration": narr_.strip(), "keywords": kws_, "compare": compare_, "compare_at": tmp_["compare_at"],
                                         "recap": tmp_["recap"], "images": cues_, "title1": tmp_["title1"], "title2": tmp_["title2"],
                                         "clip_queries": [q.strip() for q in clipq_ if q.strip()],
                                         **({"clips": [{**c_, "use": bool(u_)} for c_, u_ in zip(_clips_cur, _clip_use)]} if _clips_cur and len(_clip_use) == len(_clips_cur) else {})})
                    st.success("저장했습니다. ③에서 이 대본으로 음성을 만들고 합성합니다.")
                    st.rerun()
                if sv2.button("🔓 잠금 해제 (자동 상태로)", key=f"lfunlock_{k_}", disabled=not rec_.get("locked"),
                              help="소재 구성이 바뀌면 AI가 대본을 다시 쓸 수 있게 합니다 (내용은 그대로 남음)"):
                    LS.update_rec(idx_, {"locked": False}, lock=False)
                    st.rerun()
                if st.button("🔁 이 대본에 맞춰 키워드·비교·요약·영상 검색어 다시 만들기 (AI, 대본은 그대로)", key=f"lfsync_{k_}",
                             help="현재 입력한 나레이션을 저장한 뒤, 그 글에 맞는 키워드 팝업/비교 카드/요약/영상 검색어를 AI가 새로 만듭니다. 화면 지정(사진·영상 큐)은 자동 배치로 초기화됩니다"):
                    LS.update_rec(idx_, {"narration": narr_.strip()})
                    run("build_longform.py", "--mode", "manual", "--indexes", ",".join(str(i) for i in plan["members"]), *common_args,
                        "--plan-only", "--only", str(idx_), "--resync")
                    st.rerun()
                ins_ = st.text_input("AI에게 다시 쓰게 하기 — 추가 지시 (예: 한국과 비교를 더 자세히 / 더 쉬운 말로 / 숫자는 줄이기)", key=f"lfins_{k_}")
                if st.button("🤖 이 챕터만 지시대로 AI가 다시 쓰기", key=f"lfai_{k_}", disabled=not ins_.strip(),
                             help="이 챕터 대본·키워드·비교 카드를 새로 만듭니다 (화면 지정은 초기화). 다른 챕터는 그대로"):
                    run("build_longform.py", "--mode", "manual", "--indexes", ",".join(str(i) for i in plan["members"]), *common_args,
                        "--plan-only", "--only", str(idx_), "--instruction", ins_.strip())
                    st.rerun()
                st.markdown("**시나리오 (저장 전 입력값 기준 미리보기)**")
                sc_rows = LS.scenario_rows(it_, tmp_)
                st.dataframe(pd.DataFrame([{"문장": r["n"], "시간(초)": r["t"], "화면": (f"영상 {r['scene']}" if r["kind"] == "clip" else f"사진 {r['scene']}"),
                                            "효과": " · ".join(r["events"]), "대사": r["text"]} for r in sc_rows]),
                             use_container_width=True, hide_index=True)
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

with TS:
    st.caption("평소에는 자동으로 동기화되므로 여기를 열어 볼 일은 거의 없습니다. 설정을 바꾸거나 수동으로 실행할 때만 펼치세요. (맨 위 줄에 현재 상태가 요약돼 있습니다)")
    with st.expander("☁️ GitHub 동기화 (DB)", expanded=False):
        TTS_CFG["gh_repo"] = st.text_input("저장소 (소유자/이름)", TTS_CFG.get("gh_repo", ""), key="gh_repo_in")
        _tk = st.text_input("GITHUB_TOKEN (이 실행 동안만 사용, 저장 안 됨)", type="password", key="gh_tok_in",
                            help="환경변수로 미리 설정했다면 비워 두세요. 해당 저장소 Contents 읽기/쓰기 권한이 있는 토큰")
        if _tk.strip():
            os.environ["GITHUB_TOKEN"] = _tk.strip()
        st.caption("GITHUB_TOKEN: " + ("**설정됨**" if _gh_token() else "**없음** (자동 동기화는 꺼진 상태. 가져오기는 공개 저장소만 가능)"))
        TTS_CFG["gh_auto"] = st.checkbox("UI를 열 때 GitHub DB를 먼저 가져오고, 작업이 끝나면 자동으로 올리기", bool(TTS_CFG.get("gh_auto")), key="gh_auto_cb",
                                         help="병합 방식입니다: 소재 번호는 PC 기준을 유지하고, GitHub(자동 제작)에만 있는 소재는 뒤에 붙이고, 영상/업로드 기록은 앞선 쪽을 따릅니다. 새 GitHub 소재가 10개를 넘으면 자동으로는 멈추고 수동 확인을 요청합니다")
        if st.session_state.get("gh_boot"):
            _okb, _outb = st.session_state["gh_boot"]
            st.caption(("✅ 시작 시 가져오기 완료: " if _okb else "⚠️ 시작 시 가져오기 보류: ") + (_outb.splitlines()[-1] if _outb else ""))
        json.dump(TTS_CFG, open(TTS_FILE, "w", encoding="utf-8"), ensure_ascii=False)
        g1, g2, g3 = st.columns(3)
        if g1.button("📥 가져오기 (병합만)", key="gh_pull", help="GitHub DB를 PC DB에 병합합니다. GitHub에는 쓰지 않음"):
            run("sync_db.py", "--repo", TTS_CFG["gh_repo"], "--apply"); st.rerun()
        if g2.button("📤 쇼츠 DB 올리기 (병합 후)", key="gh_push", disabled=not _gh_token(), help="GitHub와 병합한 DB를 PC와 GitHub에 모두 반영 (facts_db.json)"):
            run("sync_db.py", "--repo", TTS_CFG["gh_repo"], "--apply", "--push"); st.rerun()
        if g3.button("📤 롱폼 DB 올리기", key="gh_push_lf", disabled=not (_gh_token() and os.path.exists("longform_db.json")), help="longform_db.json을 그대로 GitHub에 커밋 (롱폼은 PC에서만 만들어 병합 없이 덮어씀)"):
            run("gh_push.py", "--repo", TTS_CFG["gh_repo"], "--file", "longform_db.json", *_lf_extra_files())
        with st.expander("차이 미리보기 (아무것도 바꾸지 않음)"):
            if st.button("PC ↔ GitHub 차이 보기", key="gh_diff"):
                run("sync_db.py", "--repo", TTS_CFG["gh_repo"], "--detail")

    with st.expander("🔄 코드 업데이트 (GitHub → 이 PC)", expanded=False):
        st.caption("zip을 풀어 넣을 필요 없이, 이 채널 저장소의 최신 코드(*.py, requirements.txt)만 받아 덮어씁니다. 소재 DB·설정·토큰·영상은 건드리지 않고, 바뀐 파일은 _backup 폴더에 보관합니다. 채널이 다른 저장소면 멈춥니다. 끝나면 결과 안내를 따르세요: .py만 바뀌면 화면 새로고침(Rerun)이면 되고, 새 패키지(requirements.txt)나 bat이 바뀌었을 때만 bat을 다시 실행합니다.")
        _u1, _u2, _u3 = st.columns(3)
        if _u3.button("⬆️ 이 PC 코드를 GitHub에 올리기", key="uc_push", disabled=not _gh_token(), help="zip으로 받은 코드를 PC에 넣은 뒤 이 버튼 한 번이면 GitHub 저장소에도 반영됩니다 (채널이 다른 저장소면 멈춤)"):
            run("update_code.py", "--repo", TTS_CFG["gh_repo"], "--push")
        if _u1.button("🔍 바뀔 파일 확인", key="uc_check"):
            run("update_code.py", "--repo", TTS_CFG["gh_repo"], "--check")
        if _u2.button("⬇️ 최신 코드로 업데이트", key="uc_apply", type="primary"):
            if run("update_code.py", "--repo", TTS_CFG["gh_repo"]):
                st.session_state["code_chk"] = ""
                st.info("코드를 받았습니다. 위 결과의 안내를 따르세요 (보통은 화면 새로고침/Rerun이면 됩니다. 새 패키지나 bat이 바뀐 경우에만 bat 재실행).")

    with st.expander("🧾 작업 이력 · 디스코드 알림", expanded=False):
        TTS_CFG["discord_notify"] = st.checkbox("오래 걸리는 작업이 끝나면 디스코드로 알림 (실패는 시간과 상관없이 알림)", bool(TTS_CFG.get("discord_notify")), key="dc_notify")
        _dc1, _dc2 = st.columns([3, 1])
        _wh = _dc1.text_input("디스코드 웹훅 URL (비우면 환경변수 DISCORD_WEBHOOK_URL 사용)", _SEC.get("discord_webhook", ""), type="password", key="dc_hook")
        if _wh.strip() != _SEC.get("discord_webhook", ""):
            _SEC["discord_webhook"] = _wh.strip()
            json.dump(_SEC, open(SECRET_FILE, "w", encoding="utf-8"))
        if _wh.strip():
            os.environ["DISCORD_WEBHOOK_URL"] = _wh.strip()
        TTS_CFG["discord_min_secs"] = _dc2.number_input("알림 최소 시간(초)", 0, 7200, int(TTS_CFG.get("discord_min_secs") or 60), key="dc_min")
        st.caption("웹훅: " + ("**설정됨**" if os.environ.get("DISCORD_WEBHOOK_URL") else "**없음**") + "  (디스코드 채널 설정 → 연동 → 웹훅에서 URL 복사. 입력한 URL은 이 PC의 .local_secrets.json에만 저장되고 GitHub에는 올라가지 않습니다)")
        json.dump(TTS_CFG, open(TTS_FILE, "w", encoding="utf-8"), ensure_ascii=False)
        _h1, _h2, _h3 = st.columns(3)
        if _h1.button("🔔 테스트 알림 보내기", key="dc_test", disabled=not os.environ.get("DISCORD_WEBHOOK_URL")):
            import history as _H
            st.success("전송했습니다") if _H.notify(f"🔔 테스트 알림 [{_H.CHANNEL} PC] 정상 연결") else st.error("전송 실패 (URL 확인)")
        if _h2.button("🔄 이력 GitHub와 동기화", key="hist_sync", disabled=not _gh_token(), help="PC와 GitHub Actions의 이력을 합치고 요약(run_history.md)·소재표(history_items.csv)도 올립니다"):
            _okh, _mh = _hist_sync()
            (st.success if _okh else st.error)(_mh)
        if _h3.button("📝 요약 파일 다시 만들기", key="hist_report"):
            run("history.py", "report")
        if st.button("📚 과거 이력 가져오기 (GitHub Actions 실행 + DB 커밋, 처음 한 번)", key="hist_backfill", help="저장소의 Actions 실행 기록(성공/실패·소요시간)과 DB 커밋 기록을 이력에 채웁니다. 여러 번 눌러도 중복되지 않고 기존 기록은 그대로입니다"):
            run("history.py", "backfill", "--repo", TTS_CFG["gh_repo"])
        try:
            import history as _H
            _recs = _H.read()
        except Exception:
            _recs = []
        st.caption(f"기록 {len(_recs)}건 (PC에서 실행한 작업 + 동기화로 가져온 GitHub Actions 작업)")
        if _recs:
            st.dataframe([{"시각": r["time"], "곳": r.get("source", ""), "종류": r["kind"], "작업": r["title"], "결과": r["status"],
                           "소요": _H._fmt_secs(r.get("secs")), "비고": r.get("detail", "")[:80]} for r in reversed(_recs[-200:])],
                         use_container_width=True, hide_index=True)
            _dl1, _dl2 = st.columns(2)
            if os.path.exists("run_history.md"):
                _dl1.download_button("run_history.md 받기", open("run_history.md", "rb").read(), file_name="run_history.md", key="dl_hist_md")
            if os.path.exists("history_items.csv"):
                _dl2.download_button("history_items.csv 받기 (소재별 현황)", open("history_items.csv", "rb").read(), file_name="history_items.csv", key="dl_hist_csv")

    with st.expander("📁 구글 드라이브 (썸네일·이미지·음성·영상·자막 등)", expanded=False):
        _DL = {"thumbs": "썸네일", "subs": "자막(SRT)", "audio": "음성", "images": "이미지", "videos": "영상(mp4)", "longform": "롱폼", "db": "DB·설정 백업"}
        _tok_ok = os.path.exists("token_drive.json")
        st.caption("인증: " + ("**완료** (token_drive.json)" if _tok_ok else "**필요** — 아래 '처음 한 번' 안내를 따라 하세요"))
        TTS_CFG["drive_cats"] = st.multiselect("대상 종류", list(_DL), [c for c in TTS_CFG.get("drive_cats", list(_DL)) if c in _DL],
                                               format_func=lambda k: _DL[k], key="dr_cats", help="영상(mp4)은 용량이 큽니다. 처음엔 빼고 시작해도 됩니다")
        _dr_idx = st.text_input("소재 번호 범위 (비우면 전체, 예: 100-120,130)", key="dr_idx")
        _dr_only = ",".join(TTS_CFG["drive_cats"]) or "thumbs"
        _dr_idx_args = ["--index", _dr_idx.strip()] if _dr_idx.strip() else []
        TTS_CFG["drive_auto"] = st.checkbox("작업이 끝나면 자동으로 드라이브에 올리기 (바뀐 파일만)", bool(TTS_CFG.get("drive_auto")), key="dr_auto", disabled=not _tok_ok)
        json.dump(TTS_CFG, open(TTS_FILE, "w", encoding="utf-8"), ensure_ascii=False)
        d1, d2, d3, d4 = st.columns(4)
        if d1.button("현황", key="dr_status"):
            run("drive_sync.py", "status", "--only", _dr_only)
        if d2.button("올릴 것 미리보기", key="dr_dry", disabled=not _tok_ok):
            run("drive_sync.py", "push", "--only", _dr_only, *_dr_idx_args, "--dry-run")
        if d3.button("⬆ 드라이브로 올리기", key="dr_push", disabled=not _tok_ok):
            run("drive_sync.py", "push", "--only", _dr_only, *_dr_idx_args)
        if d4.button("⬇ 드라이브에서 받기", key="dr_pull", disabled=not _tok_ok, help="이 PC에 없는(또는 크기가 다른) 파일만 받습니다. DB는 받지 않음 (DB는 GitHub로)"):
            run("drive_sync.py", "pull", "--only", _dr_only, *_dr_idx_args)
        with st.expander("처음 한 번 (인증)"):
            st.markdown("""
    1. [Google Cloud 콘솔](https://console.cloud.google.com/) → 유튜브 업로드용으로 만든 같은 프로젝트에서 **API 및 서비스 → 라이브러리 → Google Drive API → 사용**
    2. OAuth 동의 화면의 **테스트 사용자**에 드라이브를 쓸 구글 계정이 있어야 합니다 (유튜브 때와 같은 방식)
    3. 이 폴더에서: `python drive_sync.py auth client_secret.json` → 브라우저에서 허용 → `token_drive.json` 생성
    4. 다른 PC에서 이어서 작업하려면 코드 폴더 + `client_secret.json` + `token_drive.json`을 그 PC로 복사하고 '⬇ 드라이브에서 받기'
    - **GitHub Actions 결과도 같은 드라이브 폴더에 저장**: 저장소 Settings → Secrets에 `DRIVE_CLIENT_ID`, `DRIVE_CLIENT_SECRET`, `DRIVE_REFRESH_TOKEN`을 추가 (값은 `token_drive.json` 안의 client_id / client_secret / refresh_token). 워크플로의 '구글 드라이브 저장' 단계가 영상·음성·이미지·썸네일·자막(롱폼은 롱폼)을 올립니다. Secret이 없으면 건너뜁니다.
    - 권한은 `drive.file`(이 프로그램이 만든 파일만 접근)이라 드라이브의 다른 파일은 볼 수 없습니다.
    - 영어/한국어 채널은 드라이브 루트 폴더가 따로 만들어집니다 (`culture-shorts-ko` / `korea-shorts-en`).
    """)

# ---- 작업 후 자동 동기화 (화면을 다 그린 뒤 한 번)
_shared_settings_sync()
if st.session_state.get("gh_dirty"):
    st.session_state["gh_dirty"] = False
    if TTS_CFG.get("gh_auto") and _gh_token():
        _hist_sync()
        with st.status("☁️ GitHub로 자동 동기화 중...", expanded=False) as _stt:
            _ok1, _o1 = _gh_sync(True)
            _lines = _o1.splitlines()
            _msg = _lines[-1] if _lines else ""
            if os.path.exists("longform_db.json") or os.path.exists("style_profile.json"):
                _r2 = subprocess.run([sys.executable, "gh_push.py", "--repo", TTS_CFG["gh_repo"], "--file", "longform_db.json"]
                                     + _lf_extra_files(),
                                     capture_output=True, text=True, encoding="utf-8", errors="replace", env=dict(os.environ, PYTHONIOENCODING="utf-8"))
                _ok1 = _ok1 and _r2.returncode == 0
                _msg += " | " + ((_r2.stdout + _r2.stderr).strip().splitlines() or [""])[-1]
            if st.session_state.pop("ps_push", False) and os.path.exists("pipeline_settings.json"):
                _r3 = subprocess.run([sys.executable, "gh_push.py", "--repo", TTS_CFG["gh_repo"], "--file", "pipeline_settings.json"],
                                     capture_output=True, text=True, encoding="utf-8", errors="replace", env=dict(os.environ, PYTHONIOENCODING="utf-8"))
                _ok1 = _ok1 and _r3.returncode == 0
                _msg += " | 설정: " + ((_r3.stdout + _r3.stderr).strip().splitlines() or [""])[-1]
            _stt.update(label=("✅ GitHub 동기화 완료: " if _ok1 else "⚠️ GitHub 동기화 보류/실패: ") + _msg, state="complete" if _ok1 else "error", expanded=not _ok1)
            st.session_state["gh_last"] = (_ok1, time.strftime("%H:%M"), _msg)
            if not _ok1:
                st.code(_o1[-1500:])
    if TTS_CFG.get("drive_auto") and os.path.exists("token_drive.json"):
        run("drive_sync.py", "push", "--only", ",".join(TTS_CFG.get("drive_cats") or ["thumbs"]))
