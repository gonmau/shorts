# -*- coding: utf-8 -*-
"""롱폼 전용 '확장 대본'을 만든다. (쇼츠 대본을 이어 붙이지 않고, 소재마다 더 자세히 풀어 쓴다)

소재마다 AI(Groq)로 아래를 한 번에 만든다:
  - narration : 약 90~120초 분량의 확장 대본 (배경/원인/구체적 사례/다른 나라와의 차이). 마지막 문장은 다음 소재로 넘어가는 연결 멘트
  - keywords  : 화면에 크게 띄울 핵심 키워드 3~5개 (몇 번째 문장에서)
  - compare   : 비교 카드 (한국어 채널=이 소재 나라 vs 다른 나라(한국 포함 가능), 영어 채널=한국 vs 다른 나라)
  - recap     : 마지막 요약 화면에 들어갈 한 줄
그 뒤 위키백과 근거 + 다른 모델로 문장별 검증(crosscheck)해 '모순' 문장은 빼고, 비교 칸의 모순 줄도 뺀다.
음성(TTS)도 이 대본으로 새로 만든다. 결과는 longform_scripts.json 에 캐시 (같은 소재/이웃이면 AI를 다시 부르지 않음).
AI/음성이 실패하면 호출한 쪽(build_longform)이 기존 쇼츠 대본·음성으로 대신한다.
"""
import hashlib
import json
import os
import re
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent
def _detect_en(base):
    """영어 채널 여부. 두 채널 파일이 섞인 폴더도 local_ui.py와 같은 규칙으로 판별 (channel.txt > 파일 구성 > generate_tts.py 내용)"""
    has_en, has_ko = (base / "generate_topics.py").exists(), (base / "generate_culture_facts.py").exists()
    if has_en and has_ko:
        try:
            return (base / "channel.txt").read_text(encoding="utf-8").strip().lower() == "en"
        except Exception:
            try:
                return "ko-KR-SunHiNeural" not in (base / "generate_tts.py").read_text(encoding="utf-8")
            except Exception:
                return False
    return has_en and not has_ko

IS_EN = _detect_en(BASE)
import ko_text as KT  # noqa: E402
SCRIPTS = BASE / "longform_scripts.json"
AUDIO_DIR = BASE / "audio"
LEN_RANGE = (1400, 1900) if IS_EN else (650, 900)     # 확장 대본 글자 수(공백 포함). 한국어 약 100~130초 / 영어 약 100~130초
MODELS = ["llama-3.3-70b-versatile", "openai/gpt-oss-120b", "llama-3.1-8b-instant", "openai/gpt-oss-20b"]
EN_PARTNERS = ["United States", "Japan", "China", "United Kingdom", "France", "Germany", "India", "Australia", "Brazil", "Canada"]
VERSION = 3


def enabled():
    return os.environ.get("LF_EXPAND", "1") != "0" and bool(os.environ.get("GROQ_API_KEY", "").strip())


def client_models():
    from groq import Groq
    c = Groq(api_key=os.environ["GROQ_API_KEY"].strip(), timeout=90.0)
    try:
        avail = {m.id for m in c.models.list().data}
        ms = [m for m in MODELS if m in avail] or MODELS
    except Exception:
        ms = MODELS
    return c, ms


def _json(text):
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
        return d if isinstance(d, dict) else None
    except Exception:
        return None


def _chat(client, models, system, prompt, tokens=3500):
    for m in models:
        try:
            kw = ({"max_completion_tokens": max(tokens, 5000), "extra_body": {"reasoning_effort": "low"}}
                  if "gpt-oss" in m else {"max_completion_tokens": tokens})
            r = client.chat.completions.create(model=m, temperature=0.5, messages=[
                {"role": "system", "content": system}, {"role": "user", "content": prompt}], **kw)
            d = _json(r.choices[0].message.content if r.choices else "")
            if d and str(d.get("narration", "")).strip():
                return d, m
        except Exception as e:
            print(f"    [확장대본] {m} 실패: {type(e).__name__}: {str(e)[:100]}", flush=True)
    return None, None


def split_sentences(text):
    parts = re.split(r"(?<=[.!?。！？])\s+|\n+", str(text or "").strip())
    return [p.strip() for p in parts if p.strip()]


def clean(text):
    t = re.sub(r"[*#_`>\[\]{}]", "", str(text or ""))
    t = re.sub(r"[\U0001F000-\U0001FFFF☀-➿]", "", t)       # 이모지 제거
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _hash(*parts):
    return hashlib.sha1("|".join(str(p) for p in parts).encode("utf-8")).hexdigest()[:12]


def load_scripts():
    try:
        d = json.loads(SCRIPTS.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def save_scripts(d):
    tmp = SCRIPTS.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(SCRIPTS)


# ---------------------------------------------------------------- 프롬프트
def _prompt(item, ev, next_info, candidates, instruction=""):
    import style_profile as _sp
    return _sp.apply(__prompt_base(item, ev, next_info, candidates, instruction), "longform")


def __prompt_base(item, ev, next_info, candidates, instruction=""):
    lo, hi = LEN_RANGE
    ins = str(instruction or "").strip()
    extra = (f"- EDITOR'S EXTRA INSTRUCTION (follow it): {ins}\n" if IS_EN else f"- 편집자의 추가 지시 (반드시 반영): {ins}\n") if ins else ""
    country = (str(item.get("country", "")).strip() if IS_EN else KT.disp_country(item.get("country", "")))
    topic = str(item.get("topic") or item.get("title_line1") or "").strip()
    short = str(item.get("narration", "")).strip()
    evidence = "\n".join(ev)[:2400] if ev else "(none)"
    if IS_EN:
        nxt = (f"Last sentence: a natural one-line transition to the next story, which is about \"{next_info}\"."
               if next_info else "Last sentence: a warm one-line wrap-up of the whole video (no 'subscribe' request).")
        return f"""You write the voice-over for ONE chapter of a long YouTube video (about {lo}-{hi} characters, roughly 100-130 seconds) for the channel "Korea A to Z", which introduces Korea to foreigners.
Chapter subject: {topic} (country/place context: {country})
Short-video script it comes from (keep its core facts):
{short}

Reference text (encyclopedia intro, may be incomplete):
{evidence}

Rules:
- Explain it in much more depth than the short: background, why it exists, concrete everyday examples, interesting details, and what surprises foreigners.
- Never invent specific numbers, dates, names or prices. If unsure, use soft wording ("about", "many", "in some places") or leave it out. Prefer facts that appear in the reference text or the short script.
- Friendly spoken English, short plain sentences (under 22 words), no emojis, no markdown, no "subscribe/like" requests. First sentence is a hook (question or surprising fact).
- {nxt}
- compare: Korea is ALWAYS the left side. Pick the ONE country (from: {', '.join(candidates)}) whose situation is most different or most relatable for this subject and compare Korea with it in 3 rows. Each row: a short label (<=22 chars) and short values (<=28 chars each). If you are not sure about a number, use qualitative words (common / rare / strict / relaxed).
- keywords: 3-5 short on-screen phrases (<=24 chars), each tied to the sentence number (1-based) where it is spoken. Choose names, numbers, or key words.
- recap: ONE short line (<=60 chars) summarising this chapter for the final recap screen.
- broll: 3 short English stock-footage search queries (2-5 words each) for generic atmospheric video that fits this chapter (e.g. "seoul night street", "family dinner table"). No brand names, no specific people.
{extra}Return pure JSON only:
{{"narration":"...","keywords":[{{"sentence":1,"text":"..."}}],"compare":{{"title":"Korea vs <country>","left":"Korea","right":"<country>","rows":[{{"label":"...","left":"...","right":"..."}}]}},"recap":"...","broll":["...","...","..."]}}"""
    nxt = (f"마지막 문장은 다음 소재 '{next_info}'로 자연스럽게 넘어가는 한 줄 연결 멘트로 쓰세요."
           if next_info else "마지막 문장은 영상 전체를 정리하는 따뜻한 한 줄 마무리로 쓰세요 (구독/좋아요 요청은 금지).")
    return f"""당신은 '세계 문화 상식' 유튜브 롱폼(여러 나라를 묶은 긴 영상)의 한 챕터 나레이션 작가입니다.
챕터 소재: {country} - {topic}
이 챕터의 바탕이 된 쇼츠 대본 (핵심 사실은 유지):
{short}

참고 자료 (백과사전 요약, 불완전할 수 있음):
{evidence}

규칙:
- 쇼츠보다 훨씬 자세히 풀어 쓰세요: 배경과 유래, 왜 그런지, 생활 속 구체적 사례, 흥미로운 디테일, 다른 나라와의 차이. 분량은 공백 포함 {lo}~{hi}자.
- 확실하지 않은 숫자, 연도, 이름, 금액은 쓰지 마세요. 모르면 '약', '대체로', '일부 지역에서' 같은 표현을 쓰거나 빼세요. 참고 자료와 쇼츠 대본에 있는 사실을 우선하세요.
- 존댓말 구어체, 짧은 문장(한 문장 45자 이내), 이모지/마크다운/구독 요청 금지. 첫 문장은 시청자를 붙잡는 질문이나 놀라운 사실.
- {nxt}
- compare(비교 카드): 왼쪽은 이 챕터의 나라('{country}'). 오른쪽은 다음 후보 중 이 소재와 가장 대비되는(또는 비교하기 좋은) 나라 하나를 고르세요: {', '.join(candidates)}. (특정 나라로 고정하지 말고 소재에 맞게 고르세요.) 3줄 비교. 줄마다 항목 이름(12자 이내)과 값(각 16자 이내). 숫자가 불확실하면 '많음/적음/엄격/느슨' 같은 정성 표현을 쓰세요.
- keywords: 화면에 크게 띄울 짧은 문구(14자 이내) 3~5개와, 그 말이 나오는 문장 번호(1부터). 이름/숫자/핵심어 위주.
- recap: 마지막 요약 화면용 한 줄(30자 이내).
- broll: 이 챕터 분위기에 맞는 일반적인 스톡 영상 검색어 3개 (영어, 2~5단어. 예: "forest lake sunrise", "street market crowd"). 브랜드/특정 인물 금지.
{extra}순수 JSON만 출력:
{{"narration":"...","keywords":[{{"sentence":1,"text":"..."}}],"compare":{{"title":"{country} vs 나라","left":"{country}","right":"나라","rows":[{{"label":"...","left":"...","right":"..."}}]}},"recap":"...","broll":["...","...","..."]}}"""


def soften(client, models, narr):
    """'~한다.' 체가 섞인 딱딱한 대본을, 사실·문장 수·순서는 그대로 두고 존댓말 구어체로 고친다 (실패하면 원본)"""
    n = len(split_sentences(narr))
    prompt = (f"다음 한국어 유튜브 내레이션을 자연스러운 존댓말 구어체('~합니다', '~해요', '~죠')로 고쳐 쓰세요. "
              f"문장 수({n}개)와 문장 순서, 사실·숫자·고유명사는 그대로 두고 말투만 바꿉니다. 한 문장은 45자 이내. 순수 JSON만 출력: {{\"narration\":\"...\"}}\n\n{narr}")
    try:
        d, _ = _chat(client, models, "You rewrite Korean voice-over scripts into a polite conversational tone. Output JSON only.", prompt)
        new = clean((d or {}).get("narration"))
        if new and len(split_sentences(new)) == n and KT.plain_ratio(new) < KT.plain_ratio(narr):
            return new
    except Exception:
        pass
    return narr


def _normalize(d, n_sent_min=6):
    """AI 응답 -> 안전한 형태로 정리 (실패하면 None)"""
    narr = clean(d.get("narration"))
    if not IS_EN:
        narr = clean(KT.strip_latin_parens(narr))   # '(Diablada)' 같은 영어 괄호는 음성이 영어로 읽어 어색함
    sents = split_sentences(narr)
    if len(sents) < n_sent_min:
        return None
    kws = []
    for k in d.get("keywords") or []:
        try:
            s = int(k.get("sentence"))
            t = clean(k.get("text"))[: (28 if IS_EN else 16)]
        except Exception:
            continue
        if t and 1 <= s <= len(sents) and all(x["sentence"] != s for x in kws):
            kws.append({"sentence": s, "text": t})
    cmp_ = d.get("compare") if isinstance(d.get("compare"), dict) else {}
    rows = []
    for r in cmp_.get("rows") or []:
        if isinstance(r, dict) and all(clean(r.get(k)) for k in ("label", "left", "right")):
            rows.append({"label": clean(r["label"])[:24], "left": clean(r["left"])[:30], "right": clean(r["right"])[:30]})
    compare = None
    if len(rows) >= 2 and clean(cmp_.get("left")) and clean(cmp_.get("right")):
        compare = {"title": clean(cmp_.get("title"))[:40], "left": clean(cmp_["left"])[:24], "right": clean(cmp_["right"])[:24], "rows": rows[:3]}
        if IS_EN:
            compare["left"] = "Korea"
    broll = [clean(x)[:60] for x in (d.get("broll") or []) if isinstance(x, str) and clean(x)][:3]
    return {"narration": narr, "keywords": kws[:5], "compare": compare, "recap": clean(d.get("recap"))[:70], "broll": broll}


def _resync_prompt(item, narr, candidates, next_info):
    """고쳐 쓴 나레이션은 그대로 두고, 그에 맞는 키워드/비교 카드/요약/영상 검색어만 새로 만든다"""
    country = str(item.get("country", "")).strip()
    sents = split_sentences(narr)
    numbered = "\n".join(f"{i}. {x}" for i, x in enumerate(sents, 1))
    if IS_EN:
        return f"""Below is the FINAL voice-over of one chapter (sentences are numbered). Do NOT change it. Create the on-screen helpers that match THIS text.
{numbered}

- keywords: 3-5 short on-screen phrases (<=24 chars) taken from the text, each tied to the sentence number (1-{len(sents)}) where it is spoken.
- compare: Korea is ALWAYS the left side; choose ONE country from: {', '.join(candidates)}; 3 rows (label <=22 chars, values <=28 chars). Use only facts that appear in the text, or soft qualitative words.
- recap: ONE short line (<=60 chars) summarising the chapter.
- broll: 3 short English stock-footage search queries (2-5 words) that fit the text. No brand names or specific people.
Return pure JSON only:
{{"keywords":[{{"sentence":1,"text":"..."}}],"compare":{{"title":"Korea vs <country>","left":"Korea","right":"<country>","rows":[{{"label":"...","left":"...","right":"..."}}]}},"recap":"...","broll":["...","...","..."]}}"""
    return f"""아래는 한 챕터의 최종 나레이션입니다 (문장에 번호가 있음). 내용을 바꾸지 말고, 이 글에 맞는 화면 보조 요소만 새로 만드세요.
{numbered}

- keywords: 글에 나온 말 중 화면에 크게 띄울 짧은 문구(14자 이내) 3~5개와, 그 말이 나오는 문장 번호(1~{len(sents)}).
- compare(비교 카드): 왼쪽은 '{country}'. 오른쪽은 다음 중 하나: {', '.join(candidates)}. 3줄 (항목 12자 이내, 값 각 16자 이내). 글에 나온 사실이나 '많음/적음' 같은 정성 표현만 쓰세요.
- recap: 마지막 요약 화면용 한 줄(30자 이내).
- broll: 이 글에 어울리는 일반적인 스톡 영상 검색어 3개 (영어, 2~5단어). 브랜드/특정 인물 금지.
순수 JSON만 출력:
{{"keywords":[{{"sentence":1,"text":"..."}}],"compare":{{"title":"{country} vs 나라","left":"{country}","right":"나라","rows":[{{"label":"...","left":"...","right":"..."}}]}},"recap":"...","broll":["...","...","..."]}}"""


# ---------------------------------------------------------------- 검증
def verify(client, models, item, ev, res):
    """모순 문장/비교 줄을 뺀다. 검증 호출이 실패하면 그대로 두고 '미검증' 기록."""
    import crosscheck as C
    topic = f"{item.get('country', '')} {item.get('topic', '')}".strip()
    sents = split_sentences(res["narration"])
    rows = (res.get("compare") or {}).get("rows") or []
    cmp_ = res.get("compare") or {}
    claims = sents + [f"{cmp_.get('left')} - {r['label']}: {r['left']} / {cmp_.get('right')}: {r['right']}" for r in rows]
    verifiers = [m for m in C.VERIFIERS if m in models] or list(models)
    try:
        verdict, notes, used = C._verify(client, verifiers, topic, ev, claims)
    except Exception:
        verdict = None
    if verdict is None:
        res["verify"] = {"status": "unchecked", "notes": ["검증 모델 호출 실패 - 사람이 확인하세요"]}
        return res
    bad_s = {i for i in range(1, len(sents) + 1) if verdict.get(i) == "contradicted"}
    bad_r = {i for i in range(len(rows)) if verdict.get(len(sents) + 1 + i) == "contradicted"}
    unsup = sum(1 for i in range(1, len(claims) + 1) if verdict.get(i, "unsupported") == "unsupported")
    if bad_s and len(bad_s) <= max(1, len(sents) // 3):
        keep = [s for i, s in enumerate(sents, 1) if i not in bad_s]
        # 키워드 문장 번호를 새 번호로 옮기고, 빠진 문장의 키워드는 버린다
        newno, k = {}, 0
        for i in range(1, len(sents) + 1):
            if i not in bad_s:
                k += 1
                newno[i] = k
        res["keywords"] = [{"sentence": newno[x["sentence"]], "text": x["text"]} for x in res["keywords"] if x["sentence"] in newno]
        res["narration"] = " ".join(keep)
    if cmp_:
        kept = [r for i, r in enumerate(rows) if i not in bad_r]
        if len(kept) >= 2:
            cmp_["rows"] = kept
        else:
            res["compare"] = None
    res["verify"] = {"status": "ok" if not (bad_s or bad_r) else "fixed", "removed_sentences": len(bad_s), "removed_rows": len(bad_r),
                     "unsupported": unsup, "notes": notes[:8], "model": used}
    return res


# ---------------------------------------------------------------- 음성
def synth(text, key):
    """text -> (audio_path, timing_path). 이미 같은 이름이 있으면 호출한 쪽이 해시로 판단해서 다시 부르지 않는다."""
    import generate_tts as G
    voice = os.environ.get("TTS_EDGE_VOICE") or ("en-US-AndrewNeural" if IS_EN else "ko-KR-SunHiNeural")
    rate = os.environ.get("TTS_RATE") or ("+8%" if IS_EN else "-3%")
    AUDIO_DIR.mkdir(exist_ok=True)
    ap, tp = AUDIO_DIR / f"{key}.mp3", AUDIO_DIR / f"{key}_timing.json"
    G.generate_tts(text, ap, tp, voice, rate, "+0%", "+0Hz", timeout=240, retries=3)
    return ap, tp


def ensure_audio(rec, key, text):
    """rec(dict)에 audio/timing 경로를 채운다. 글이 같고 파일이 있으면 재사용. 성공 True"""
    h = _hash(text, os.environ.get("TTS_EDGE_VOICE", ""), os.environ.get("TTS_RATE", ""), os.environ.get("SUPERTONIC_VOICE_EN" if IS_EN else "SUPERTONIC_VOICE_KO", ""), "stcap" + os.environ.get("SUPERTONIC_MAX_SPEED", "1.2"))
    if rec.get("tts_hash") == h and rec.get("audio") and Path(rec["audio"]).exists():
        return True
    try:
        ap, tp = synth(text, key)
        rec.update({"audio": str(ap), "timing": str(tp), "tts_hash": h})
        return True
    except Exception as e:
        print(f"    [롱폼 음성] 실패: {type(e).__name__}: {str(e)[:150]}", flush=True)
        return False


# ---------------------------------------------------------------- 소재 1개
KEEP_FIELDS = ("title1", "title2", "clip_queries", "clips", "locked_note")


def get_rec(idx):
    return load_scripts().get(str(idx)) or {}


def update_rec(idx, fields, lock=True):
    """사람이 고친 값을 저장한다. lock=True 면 이후 자동 실행이 이 대본을 덮어쓰지 않는다(다시 만들기 요청 제외)."""
    store = load_scripts()
    rec = store.get(str(idx)) or {}
    rec.update(fields)
    if lock:
        rec["locked"] = True
        rec["edited"] = time.strftime("%Y-%m-%d %H:%M")
    store[str(idx)] = rec
    save_scripts(store)
    return rec


def prepare_item(client, models, idx, item, next_info, candidates, force=False, instruction="", plan_only=False, resync=False):
    """확장 대본 (+ 음성). 성공하면 dict(narration, keywords, compare, recap, audio, timing, ...) 아니면 None.
    - 사람이 고쳐서 잠근(locked) 대본은 force 가 아니면 그대로 쓴다. 지시문(instruction)이 있으면 그 지시를 반영해 다시 쓴다.
    - plan_only=True 면 음성은 만들지 않는다 (대본/시나리오 미리보기용).
    - resync=True 면 저장된(고친) 나레이션은 그대로 두고 키워드/비교 카드/요약/영상 검색어만 그 글에 맞게 다시 만든다."""
    import crosscheck as C
    store = load_scripts()
    key = str(idx)
    sig = _hash(VERSION, item.get("narration", ""), item.get("country", ""), next_info, ",".join(candidates), LEN_RANGE)
    rec = store.get(key) or {}
    regen = force or bool(str(instruction or "").strip())
    _nr = re.sub(r"\s+", "", rec.get("narration", ""))
    if _nr and rec.get("locked") and not regen:   # 다른 언어로 만들어진 잠금 대본(채널 판별 오류 때 생김)은 쓰지 않는다
        _ko = len(re.findall(r"[가-힣]", _nr)) / len(_nr)
        if (_ko < 0.2) != IS_EN:
            print(f"    [확장대본] {idx}: 저장된 대본의 언어가 채널과 달라 다시 만듭니다", flush=True)
            rec = {k: v for k, v in rec.items() if k in KEEP_FIELDS}
    if resync and rec.get("narration") and not regen:
        if client is None:
            print(f"    [확장대본] {idx}: AI에 연결할 수 없어 화면 요소를 다시 만들지 못했습니다", flush=True)
        else:
            d, used = _chat(client, models, "You create on-screen helpers for a fixed voice-over. Output JSON only.",
                            _resync_prompt(item, rec["narration"], candidates, next_info))
            res = _normalize({**(d or {}), "narration": rec["narration"]}, n_sent_min=1) if d else None
            if res:
                now_ = time.strftime("%Y-%m-%d %H:%M")
                rec = {**rec, "keywords": res["keywords"], "compare": res["compare"], "recap": res["recap"] or rec.get("recap", ""), "broll": res["broll"],
                       "clip_queries": res["broll"] or rec.get("clip_queries", []), "clips": [], "images": [], "compare_at": 0,
                       "locked": True, "edited": now_, "resynced": now_}
                store[key] = rec
                save_scripts(store)
                print(f"    [확장대본] {idx}: 고친 대본에 맞춰 키워드 {len(res['keywords'])}개, 비교 {'O' if res['compare'] else 'X'}, 영상 검색어 {len(res['broll'])}개를 다시 만들었습니다", flush=True)
            else:
                print(f"    [확장대본] {idx}: 화면 요소 재생성 실패 - 기존 값을 유지합니다", flush=True)
    elif rec.get("narration") and rec.get("locked") and not regen:
        print(f"    [확장대본] {idx}: 편집/잠금된 대본 사용 ({rec.get('edited', '')})", flush=True)
    elif regen or rec.get("sig") != sig or not rec.get("narration") or (not IS_EN and KT.is_stiff(rec.get("narration", ""))):
        if not regen and rec.get("sig") == sig and rec.get("narration"):
            print(f"    [확장대본] {idx}: 저장된 대본이 '~한다.' 체로 딱딱해 존댓말로 다시 씁니다", flush=True)
        if client is None:
            return None
        topic = f"{item.get('country', '')} {item.get('topic', '')}".strip()
        wl = "en" if IS_EN else "ko"
        ev = C._wiki(topic, wl) or ([] if IS_EN else C._wiki(topic, "en"))
        d, used = None, None
        for attempt in range(2):
            d, used = _chat(client, models, "You write accurate, engaging voice-over scripts. Output JSON only.", _prompt(item, ev, next_info, candidates, instruction))
            res = _normalize(d) if d else None
            if res and len(res["narration"]) >= LEN_RANGE[0] * 0.6:
                break
            res = None
            print(f"    [확장대본] {idx} 분량/형식이 맞지 않아 다시 시도 ({attempt + 1}/2)", flush=True)
        if not res:
            return rec if rec.get("narration") and not force else None
        if not IS_EN and KT.is_stiff(res["narration"]):
            res["narration"] = soften(client, models, res["narration"])
            print(f"    [확장대본] {idx}: 어투가 딱딱해 존댓말 구어체로 고침", flush=True)
        if os.environ.get("CROSS_CHECK", "0") == "1":
            res = verify(client, models, item, ev, res)
        else:
            res["verify"] = {"status": "skipped", "notes": ["교차검증 꺼짐(CROSS_CHECK=0) - 직접 검증하거나 확인하세요"]}
        keep = {k: rec[k] for k in KEEP_FIELDS if k in rec}
        rec = {**keep, **res, "sig": sig, "model": used, "created": time.strftime("%Y-%m-%d %H:%M")}
        if str(instruction or "").strip():
            rec["instruction"] = str(instruction).strip()
        store[key] = rec
        save_scripts(store)
        print(f"    [확장대본] {idx} {item.get('country', '')}: {len(rec['narration'])}자, 키워드 {len(rec['keywords'])}, 비교 {'O' if rec.get('compare') else 'X'}, 검증 {rec['verify']['status']}", flush=True)
    else:
        print(f"    [확장대본] {idx}: 저장된 대본 재사용", flush=True)
    if plan_only:
        return rec
    name = re.sub(r"[^\w가-힣-]+", "_", str(item.get("country", "x")))[:30]
    if not ensure_audio(rec, f"lf_{idx:04d}_{name}", rec["narration"]):
        return None
    store = load_scripts()
    store[key] = rec
    save_scripts(store)
    return rec


# ---------------------------------------------------------------- 시나리오 (사람이 읽는 설명)
def scenario_rows(item, rec):
    """문장별로 '몇 초쯤, 어느 사진/영상, 어떤 화면 효과'가 나오는지 목록으로 돌려준다 (미리보기/수정 화면용).
    -> [dict(n, text, t, scene, kind('img'|'clip'), events[str])]"""
    from common import safe_country  # noqa: F401
    from scenes import scene_groups, item_scene_count
    sents = split_sentences(rec.get("narration"))
    if not sents:
        return []
    n_scenes = max(1, item_scene_count(item))
    sz = [len(re.sub(r"\s+", "", x)) for x in sents]
    total = sum(sz) or 1
    # 시간: 음성이 있으면 실제 타이밍, 없으면 글자 수로 추정 (한국어 약 6자/초, 영어 약 13자/초)
    timings = None
    try:
        if rec.get("timing") and Path(rec["timing"]).exists():
            timings = json.loads(Path(rec["timing"]).read_text(encoding="utf-8")).get("sentences")
    except Exception:
        timings = None
    cps = 13.0 if IS_EN else 6.0
    cum = [0]
    for z in sz:
        cum.append(cum[-1] + z)

    def at(n):   # n번째 문장이 시작하는 시각
        if n <= 1:
            return 0.0
        if timings:
            import build_video as B
            return float(B.time_at_fraction(cum[n - 1] / total, timings))
        return cum[n - 1] / cps

    groups = scene_groups(sents, n_scenes)
    auto_scene = {}
    for gi, (a, b) in enumerate(groups, 1):
        for k in range(a, b + 1):
            auto_scene[k] = gi
    clips = [c for c in (rec.get("clips") or []) if c.get("path") and Path(c["path"]).exists()]
    cue_map = {}
    cues = [c for c in (rec.get("images") or []) if isinstance(c, dict)]
    for c in sorted(cues, key=lambda c: int(c.get("sentence", 1) or 1)):
        try:
            cue_map[int(c.get("sentence", 1))] = c
        except (TypeError, ValueError):
            pass
    clip_scene = {}
    if not cue_map and clips:
        for j in range(min(len(clips), 3)):
            pos = min(n_scenes - 1, max(1, round((j + 1) * n_scenes / (min(len(clips), 3) + 1))))
            clip_scene[pos + 1] = j + 1
    rows, cur = [], None
    kw_at = {}
    for k in rec.get("keywords") or []:
        kw_at.setdefault(int(k["sentence"]), []).append(k["text"])
    cmp_ = rec.get("compare") if (rec.get("compare") or {}).get("rows") else None
    cmp_n = 0
    if cmp_:
        cmp_n = int(rec.get("compare_at") or 0)
        if cmp_n < 1:
            cmp_n = next((i for i in range(1, len(sents) + 1) if cum[i] / total >= 0.55), len(sents))
    for n, text in enumerate(sents, 1):
        ev = []
        if cue_map:
            c = cue_map.get(n)
            if c:
                cur = ("clip", int(c["clip"])) if c.get("clip") else ("img", int(c.get("scene") or 1))
            elif cur is None:
                cur = ("img", 1)
        else:
            sc = auto_scene.get(n, 1)
            cur = ("clip", clip_scene[sc]) if sc in clip_scene else ("img", sc)
        for t in kw_at.get(n, []):
            ev.append(f"키워드 팝업: '{t}'" if not IS_EN else f"Keyword pop-up: '{t}'")
        if cmp_ and n == cmp_n:
            ev.append((f"비교 카드: {cmp_.get('title', '')} ({len(cmp_['rows'])}줄)") if not IS_EN else f"Compare card: {cmp_.get('title', '')} ({len(cmp_['rows'])} rows)")
        rows.append({"n": n, "text": text, "t": round(at(n), 1), "kind": cur[0], "scene": cur[1], "events": ev})
    return rows


def scenario_text(item, rec, no=None):
    """사람이 읽는 시나리오 설명 (txt로 저장해도 됨)"""
    lines = []
    head = f"[{no}] " if no else ""
    lines.append(f"{head}{item.get('country', '')} - {item.get('topic', '')}")
    qs = item.get("image_queries") or []
    prev = None
    for r in scenario_rows(item, rec):
        mark = ""
        if (r["kind"], r["scene"]) != prev:
            if r["kind"] == "clip":
                q = ((rec.get("clips") or [{}] * 9)[r["scene"] - 1] or {}).get("query", "")
                mark = f"  >> 화면: 스톡 영상 {r['scene']} ({q})"
            else:
                q = qs[r["scene"] - 1] if 0 < r["scene"] <= len(qs) else ""
                mark = f"  >> 화면: 사진 {r['scene']} ({q})"
            prev = (r["kind"], r["scene"])
        lines.append(f"  {r['n']:>2}. [{int(r['t']) // 60}:{int(r['t']) % 60:02d}] {r['text']}{mark}")
        for e in r["events"]:
            lines.append(f"        * {e}")
    if rec.get("recap"):
        lines.append(f"  요약 한 줄: {rec['recap']}")
    return "\n".join(lines)


# ---------------------------------------------------------------- 인트로 / 요약
def intro_text(countries, n, partners=None):
    if IS_EN:
        ps = [p for p in dict.fromkeys(partners or []) if p][:3]
        if len(ps) >= 2:
            cmp_ = ", ".join(ps[:-1]) + " and " + ps[-1]
        else:
            cmp_ = ps[0] if ps else "your own country"
        return (f"Welcome to Korea A to Z. In this video, we walk through {n} everyday things about Korea that often surprise people "
                f"from other countries, and compare them with places like {cmp_}. Let's get started.")
    names = ", ".join(c for c in countries[:3] if c)
    return (f"세계에는 우리가 몰랐던 문화가 정말 많습니다. 이번 영상에서는 {names} 등 {n}가지 이야기를 하나씩 깊이 있게 살펴보고, "
            f"나라마다 무엇이 어떻게 다른지 비교해 보겠습니다. 끝까지 보시면 세상이 조금 다르게 보일 거예요. 지금 시작합니다.")


_KO_ORD = ["첫", "두", "세", "네", "다섯", "여섯", "일곱", "여덟", "아홉", "열", "열한", "열두", "열세", "열네", "열다섯", "열여섯", "열일곱", "열여덟", "열아홉", "스물",
           "스물한", "스물두", "스물세", "스물네", "스물다섯", "스물여섯", "스물일곱", "스물여덟", "스물아홉", "서른"]


def ko_ord(n):
    """1 -> '첫', 2 -> '두' ... ('{n}번째'로 쓰면 음성이 '일번째, 이번째'로 읽는다)"""
    return _KO_ORD[n - 1] if 1 <= n <= len(_KO_ORD) else f"{n}"


def outro_text(recaps):
    if IS_EN:
        body = " ".join(f"Number {i}: {r.rstrip('.')}." for i, r in enumerate(recaps, 1) if r)
        return f"That is our list. Quick recap. {body} If you enjoyed this, please subscribe and see you in the next video."
    body = " ".join(f"{ko_ord(i)} 번째, {r.rstrip('.')}." for i, r in enumerate(recaps, 1) if r)
    return f"오늘 이야기를 한 번에 정리해 볼게요. {body} 재미있게 보셨다면 구독과 좋아요 부탁드립니다. 다음 영상에서 만나요."


def prepare_extra(key_prefix, text):
    """인트로/요약 음성. -> dict(audio, timing, text) 또는 None"""
    rec = {}
    key = f"{key_prefix}_{_hash(text)}"
    if (AUDIO_DIR / f"{key}.mp3").exists() and (AUDIO_DIR / f"{key}_timing.json").exists():
        return {"audio": str(AUDIO_DIR / f"{key}.mp3"), "timing": str(AUDIO_DIR / f"{key}_timing.json"), "text": text}
    if ensure_audio(rec, key, text):
        rec["text"] = text
        return rec
    return None
