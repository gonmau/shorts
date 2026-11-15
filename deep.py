# -*- coding: utf-8 -*-
"""심층편: 소재 1개를 여러 소주제(섹션)로 나눠 8~12분짜리 롱폼 1편으로 만든다.

- 섹션 대본은 deep_db.json 에 저장(수정·잠금 가능) -> 영상 만들 때 소주제마다 '가상 소재'를 facts_db.json 끝에 잠깐 붙여
  기존 롱폼 파이프라인(챕터 카드·키워드·사진·음성·합성)을 그대로 쓰고, 끝나면 지웁니다 (cleanup).
- 가상 소재: status="deep_part", deep_of=<원본 번호>. 쇼츠 파이프라인은 이 상태를 건드리지 않습니다.
"""
import json
import os
import re
import shutil
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent
DEEP_FILE = BASE / "deep_db.json"
DB_FILE = BASE / "facts_db.json"


def _is_en():
    try:
        import longform_script as LS
        return bool(LS.IS_EN)
    except Exception:
        return False


def load():
    try:
        return json.loads(DEEP_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save(d):
    DEEP_FILE.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")


# (소제목 힌트, 지시) - 개수 n 에 맞춰 앞에서부터 고르고 마지막은 항상 '정리'
ANGLES_KO = [("배경과 유래", "어떻게 시작됐고 왜 생겼는지(배경·유래)를 풀어 설명"),
             ("생활 속 모습", "지금 사람들의 일상에서 어떻게 나타나는지 구체적인 장면과 사례로 설명"),
             ("다른 나라와 비교", "다른 나라의 비슷한 문화와 비교해 같은 점과 다른 점을 설명"),
             ("몰랐던 디테일", "잘 알려지지 않은 디테일과 흔한 오해를 바로잡기"),
             ("여행자가 알아둘 점", "직접 접했을 때 알아두면 좋은 점과 예절"),
             ("변화와 앞으로", "최근의 변화와 앞으로의 모습"),
             ("의미와 가치", "이 문화가 사람들에게 주는 의미와 가치"),
             ("정리", "지금까지 이야기를 한 번에 정리하고 따뜻하게 마무리 (구독/좋아요 요청 금지)")]
ANGLES_EN = [("Background and origin", "how it started and why it exists"),
             ("In everyday life", "how it shows up in daily life, with concrete scenes and examples"),
             ("Compared with elsewhere", "how it compares with similar customs in other countries"),
             ("Details you may not know", "lesser-known details and common misunderstandings"),
             ("What visitors should know", "what is good to know when you meet it in person, including etiquette"),
             ("Change and the future", "recent changes and where it is heading"),
             ("Meaning and value", "what it means to the people who practice it"),
             ("Wrap-up", "a warm wrap-up of the whole story (no subscribe/like requests)")]


# 서사형: 한 줄기 이야기(궁금증 -> 배경 -> 갈등 -> 반전 -> 지금 -> 여운). 섹션이 개수에 맞춰 앞에서부터 쓰이고 마지막은 항상 '여운'
ARC_KO = [("장면과 궁금증", "가장 인상적인 한 장면이나 의문으로 시작해, 끝까지 봐야 풀리는 궁금증을 던진다 (설명 나열 금지)"),
          ("그 시작", "이 일이 어떻게 시작됐는지, 당시 사람들이 처한 상황과 이유를 이야기로 풀기"),
          ("엇갈림과 긴장", "갈등·어려움·논란처럼 이야기가 팽팽해지는 부분을 구체적인 장면으로"),
          ("뜻밖의 전환", "사람들이 흔히 모르는 반전이나 오해가 풀리는 지점"),
          ("지금의 모습", "그 결과가 오늘날 사람들의 삶에 어떻게 남아 있는지 구체적인 장면으로"),
          ("다른 시선", "다른 나라 사람들의 눈에는 어떻게 보이는지, 비슷한 사례와의 대비"),
          ("남는 질문", "이 이야기가 우리에게 던지는 질문"),
          ("여운", "처음의 궁금증에 답하며 여운 있게 마무리 (구독/좋아요 요청 금지)")]
ARC_EN = [("Scene and question", "open on one striking scene or question that only pays off at the end (no list of facts)"),
          ("How it began", "tell how it started, who was involved, and why, as a story"),
          ("Tension", "the conflict, difficulty or controversy, in concrete scenes"),
          ("The turn", "the surprising twist or misunderstanding that gets cleared up"),
          ("Today", "how that story still lives in people's daily lives, in concrete scenes"),
          ("Another view", "how it looks to outsiders, contrasted with similar cases"),
          ("The open question", "the question this story leaves us with"),
          ("Afterglow", "answer the opening question and close with feeling (no subscribe/like requests)")]


def plan(n, en=False, style="topic"):
    if style == "story":
        A = ARC_EN if en else ARC_KO
    else:
        A = ANGLES_EN if en else ANGLES_KO
    n = max(3, min(12, int(n)))
    mid = list(A[:-1])
    while len(mid) < n - 1:   # 직접 구성으로 섹션이 8개를 넘을 때 (잠긴 섹션은 관점을 쓰지 않음)
        mid.append(("이어지는 이야기", "앞 이야기를 이어 새로운 장면을 하나 더 풀기" if not en else "continue with one more scene"))
    return mid[:n - 1] + [A[-1]]


def chars_per_section(minutes, n, en=False):
    sec = float(minutes) * 60.0 / max(1, n)
    return int(sec * (14.5 if en else 6.7))


def scenes_per_section(minutes, n):
    s = round(float(minutes) * 60.0 / max(1, n) / 9)
    return max(6, min(16, s + (s % 2)))


def _prompt(item, ev, angle, k, n, prev, minutes, instruction, en, style="topic"):
    country = str(item.get("country", "")).strip()
    topic = str(item.get("topic") or item.get("title_line1") or "").strip()
    short = str(item.get("narration", "")).strip()
    cps = chars_per_section(minutes, n, en)
    lo, hi = int(cps * 0.85), int(cps * 1.15)
    nq = scenes_per_section(minutes, n)
    evidence = "\n".join(ev)[:2400] if ev else "(none)"
    prev_txt = "\n".join(f"- {p}" for p in prev) or "(none yet)"
    ins = (f"\n- Editor's extra instruction (follow it): {instruction}" if en else f"\n- 편집자 추가 지시 (반드시 반영): {instruction}") if instruction else ""
    story_en = ("\n- STORY MODE: this is ONE continuous story, not a fact list. Keep a single thread, name a concrete scene, person-less but vivid detail, and leave one open question that the next section answers. Avoid 'first/second/third' listing." if style == "story" else "")
    story_ko = ("\n- 서사 모드: 사실 나열이 아니라 하나의 이야기 줄기로 씁니다. 구체적인 장면과 감각적 디테일을 넣고, 첫 섹션에서 던진 궁금증을 마지막에 풀며, 각 섹션 끝은 다음이 궁금해지는 한 줄로 끝내세요. '첫째, 둘째' 식 나열 금지." if style == "story" else "")
    if en:
        return f"""You write section {k} of {n} of ONE long YouTube video (a deep dive on a single subject) for the channel "Korea A to Z".
Subject: {topic} (country/place: {country})
This section's angle: {angle[0]} - {angle[1]}
Short-video script it comes from (keep core facts): {short}
Reference text (encyclopedia intro, may be incomplete):
{evidence}
Sections already written (do NOT repeat their content):
{prev_txt}

Rules:
- {lo}-{hi} characters of voice-over for THIS section only. Friendly spoken English, short plain sentences (under 22 words), no emojis/markdown/footnotes, no "subscribe/like" requests.
- {'First sentence: a natural start of the video (hook).' if k == 1 else 'First sentence: a smooth link from the previous section.'} {'Last sentence: a warm wrap-up.' if k == n else 'Last sentence: a one-line lead-in to the next section.'}
- Never invent specific numbers, dates, names or prices; hedge (about / many / in some places) when unsure. Prefer facts from the reference text or the short script.
- title: a short on-screen section title (<=24 characters).
- keywords: only the core, usually 2-3 (at most 4) short on-screen phrases (<=24 chars), each tied to the sentence number (1-based) where it is spoken.
- image_queries: exactly {nq} different English stock-photo search queries (2-5 words each) that match the scenes in order, concrete and varied. No brands, no specific people.
- recap: ONE short line (<=60 chars) summarising this section.{story_en}{ins}
Return pure JSON only:
{{"title":"...","narration":"...","keywords":[{{"sentence":1,"text":"..."}}],"image_queries":["..."],"recap":"..."}}"""
    return f"""당신은 '세계 문화 상식' 유튜브의 심층편(소재 하나를 깊이 다루는 긴 영상) {n}개 섹션 중 {k}번째 섹션 나레이션 작가입니다.
소재: {country} - {topic}
이 섹션의 관점: {angle[0]} - {angle[1]}
바탕이 된 쇼츠 대본 (핵심 사실은 유지): {short}
참고 자료 (백과사전 요약, 불완전할 수 있음):
{evidence}
이미 쓴 섹션 (내용을 반복하지 마세요):
{prev_txt}

규칙:
- 이 섹션만 공백 포함 {lo}~{hi}자. 존댓말 구어체, 짧은 문장(한 문장 45자 이내), 이모지/마크다운/각주/구독 요청 금지.
- {'첫 문장은 영상을 여는 자연스러운 후크.' if k == 1 else '첫 문장은 앞 섹션에서 자연스럽게 이어지는 연결.'} {'마지막 문장은 영상 전체를 정리하는 따뜻한 마무리.' if k == n else '마지막 문장은 다음 섹션으로 넘어가는 한 줄 연결.'}
- 확실하지 않은 숫자·연도·이름·금액은 쓰지 말고 '약', '대체로', '일부 지역에서' 같은 표현을 쓰거나 빼세요. 참고 자료와 쇼츠 대본의 사실을 우선하세요.
- title: 화면에 띄울 섹션 소제목 (12자 이내).
- keywords: 핵심만 2~3개(최대 4개), 화면에 띄울 짧은 문구(14자 이내)와, 그 말이 나오는 문장 번호(1부터).
- image_queries: 장면 순서에 맞는 서로 다른 영어 스톡사진 검색어 정확히 {nq}개 (2~5단어, 구체적이고 다양하게). 브랜드/특정 인물 금지.
- recap: 이 섹션 한 줄 요약 (30자 이내).{story_ko}{ins}
순수 JSON만 출력:
{{"title":"...","narration":"...","keywords":[{{"sentence":1,"text":"..."}}],"image_queries":["..."],"recap":"..."}}"""


def generate(client, models, idx, item, n=5, minutes=8, instruction="", only=None, style="topic"):
    """섹션 대본 생성 -> deep_db.json 저장 (이미 잠긴 섹션은 only 가 아니면 유지). -> dict"""
    import crosscheck as C
    import longform_script as LS
    en = LS.IS_EN
    d = load()
    cur = d.get(str(idx)) or {}
    secs_old = cur.get("sections") or []
    pl = plan(n, en, style)
    if cur.get("style", "topic") != style and not cur.get("manual"):
        secs_old = []   # 방식이 바뀌면 처음부터
    topic = f"{item.get('country', '')} {item.get('topic', '')}".strip()
    ev = C._wiki(topic, "en" if en else "ko") or ([] if en else C._wiki(topic, "en"))
    secs, prev = [], []
    for k, ang in enumerate(pl, 1):
        old = secs_old[k - 1] if k - 1 < len(secs_old) else None
        if old and old.get("locked") and not (only and k in only):
            secs.append(old)
            prev.append(f"{old.get('title', '')}: " + " ".join(LS.split_sentences(old.get("narration", ""))[:2]))
            continue
        if old and not only and cur.get("n") == n and cur.get("style", "topic") == style and old.get("narration") and not instruction:
            secs.append(old)
            prev.append(f"{old.get('title', '')}: " + " ".join(LS.split_sentences(old.get("narration", ""))[:2]))
            continue
        if only and k not in only and old:
            secs.append(old)
            prev.append(f"{old.get('title', '')}: " + " ".join(LS.split_sentences(old.get("narration", ""))[:2]))
            continue
        res = best = None
        for attempt in range(2):
            raw, used = LS._chat(client, models, "You write accurate, engaging voice-over scripts. Output JSON only.",
                                 _prompt(item, ev, ang, k, n, prev, minutes, instruction, en, style), tokens=3500)
            res = LS._normalize({**(raw or {}), "compare": None}, n_sent_min=3) if raw else None
            if res:
                L = len(res["narration"]); cps = chars_per_section(minutes, n, en)
                if (L < cps * 0.6 or L > cps * 1.5) and attempt == 0:
                    print(f"    [심층편] 섹션 {k} 길이 {L}자 (목표 약 {cps}자) - 한 번 더 시도", flush=True)
                    best = res
                    res = None
                    continue
                break
            if best and attempt == 1:
                res = best
            print(f"    [심층편] 섹션 {k} 형식 오류 - 다시 시도 ({attempt + 1}/2)", flush=True)
        if not res:
            if old:
                secs.append(old)
                continue
            raise SystemExit(f"섹션 {k} 대본을 만들지 못했습니다 (GROQ_API_KEY/한도 확인).")
        if not en:
            import ko_text as KT
            if KT.is_stiff(res["narration"]):
                res["narration"] = LS.soften(client, models, res["narration"])
        qs = [LS.clean(x)[:80] for x in (raw.get("image_queries") or []) if isinstance(x, str) and LS.clean(x)]
        sec = {"title": LS.clean(raw.get("title"))[: (28 if en else 14)] or ang[0], "narration": res["narration"], "keywords": res["keywords"],
               "recap": res["recap"] or ang[0], "image_queries": qs, "angle": ang[0], "locked": False}
        secs.append(sec)
        prev.append(f"{sec['title']}: " + " ".join(LS.split_sentences(sec["narration"])[:2]))
        print(f"    [심층편] 섹션 {k}/{n} '{sec['title']}': {len(sec['narration'])}자, 키워드 {len(sec['keywords'])}, 검색어 {len(qs)}개", flush=True)
    d[str(idx)] = {**{k_: v_ for k_, v_ in cur.items() if k_ in ("intro_text", "outro_text", "recap", "recap_cards", "thumb", "manual")}, "style": style, "n": n, "minutes": minutes, "created": time.strftime("%Y-%m-%d %H:%M"), "instruction": instruction, "sections": secs}
    save(d)
    return d[str(idx)]


def script_text(idx, item, data):
    L = [f"[심층편] {item.get('country', '')} - {item.get('topic', '')}  (섹션 {len(data['sections'])}개)", ""]
    for k, s in enumerate(data["sections"], 1):
        L += [f"[{k}. {s.get('title', '')}] ({len(s.get('narration', ''))}자)", s.get("narration", ""), ""]
    return "\n".join(L)


def title(item, minutes, en=False, style="topic"):
    if style == "story":
        t_ = str(item.get("topic", "")).strip()
        return (f"{t_}: The Story Behind It" if en else f"{t_} | 그 뒤에 숨은 이야기")[:95]
    c = str(item.get("country", "")).strip()
    t = str(item.get("topic", "")).strip()
    if en:
        return f"{t}: The Complete Story ({c})"[:95]
    return f"{c} {t} 완전 정리 | 깊이 있게 보기"[:95]


def intro_text(item, n, en=False, style="topic"):
    if style == "story":
        t_ = str(item.get("topic", "")).strip()   # 서사형: 첫 섹션이 후크라서 인트로는 한 줄만
        return f"{t_}. Let's begin." if en else f"{t_}. 이 이야기를 시작합니다."
    c = str(item.get("country", "")).strip()
    t = str(item.get("topic", "")).strip()
    if en:
        return f"Welcome to Korea A to Z. Today we take one subject and go deep: {t}. We will walk through it in {n} parts. Let's get started."
    return f"오늘은 {c}의 {t}, 이 이야기 하나만 깊이 있게 살펴보겠습니다. 총 {n}가지 이야기로 풀어 볼게요. 끝까지 보시면 이 문화가 조금 다르게 보일 거예요. 지금 시작합니다."


def outro_text(recaps, en=False, style="topic", cards=False):
    if style == "story" and cards and not en and any(recaps):   # 요약 목록 카드를 띄우면 카드 내용을 같이 읽어 준다
        return "이야기를 한 번 더 정리해 볼게요. " + " ".join(f"{i}. {r.rstrip('.')}." for i, r in enumerate(recaps, 1) if r) + " 끝까지 봐 주셔서 감사합니다. 다음 이야기에서 또 만나요."
    if style == "story":
        return "끝까지 봐 주셔서 감사합니다. 다음 이야기에서 또 만나요." if not en else "Thanks for watching. See you in the next story."
    if en:
        return "Quick recap. " + " ".join(f"Part {i}: {r.rstrip('.')}." for i, r in enumerate(recaps, 1) if r) + " Thanks for watching, and see you in the next video."
    return "오늘 이야기를 한 번에 정리해 볼게요. " + " ".join(f"{i}부, {r.rstrip('.')}." for i, r in enumerate(recaps, 1) if r) + " 끝까지 봐 주셔서 감사합니다. 다음 영상에서 만나요."


# ---------------------------------------------------------------- 가상 소재
def _load_db():
    return json.loads(DB_FILE.read_text(encoding="utf-8"))


def _save_db(db):
    DB_FILE.write_text(json.dumps(db, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------------------------------------------------------------- 사진·음성 캐시 (다시 만들 때 재사용)
CACHE = BASE / "deep_cache"


def cache_dir(src, part):
    return CACHE / str(src) / str(part)


def _stash(i, f, rec, LS):
    """가상 소재 i 의 사진 폴더와 음성을 deep_cache/<원본>/<섹션>/ 로 복사해 둔다"""
    from common import visual_dir
    src, part = f.get("deep_of"), f.get("deep_part")
    if src is None or part is None:
        return
    dst = cache_dir(src, part)
    shutil.rmtree(dst, ignore_errors=True)
    dst.mkdir(parents=True, exist_ok=True)
    vd = visual_dir(BASE, i, f)
    if vd.exists():
        shutil.copytree(vd, dst / "visuals")
    meta = {"queries": list(f.get("image_queries") or []), "tts_hash": rec.get("tts_hash", ""), "audio": "", "timing": ""}
    if LS is not None:
        for name, fld in (("audio", "audio"), ("timing", "timing")):
            pth = rec.get(fld)
            if pth and Path(pth).exists():
                (dst / "audio").mkdir(exist_ok=True)
                shutil.copy2(pth, dst / "audio" / Path(pth).name.replace(f"lf_{i:04d}_", "lf_PFX_", 1))
                meta[name] = Path(pth).name.replace(f"lf_{i:04d}_", "lf_PFX_", 1)
    (dst / "meta.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")


def _restore(src, part, i, f, LS):
    """캐시된 사진·음성을 새 가상 소재 i 로 되돌린다. 검색어가 바뀐 장면 사진은 지워 그 장면만 다시 받게 한다. -> rec 에 넣을 필드"""
    from common import visual_dir
    dst = cache_dir(src, part)
    try:
        meta = json.loads((dst / "meta.json").read_text(encoding="utf-8"))
    except Exception:
        return {}
    vd = visual_dir(BASE, i, f)
    if (dst / "visuals").exists():
        shutil.rmtree(vd, ignore_errors=True)
        shutil.copytree(dst / "visuals", vd)
        oldq, newq = list(meta.get("queries") or []), list(f.get("image_queries") or [])
        for n in range(1, max(len(oldq), len(newq)) + 1):
            if n > len(newq) or n > len(oldq) or oldq[n - 1] != newq[n - 1]:
                for ext in ("png", "jpg"):
                    (vd / f"scene_{n:02d}.{ext}").unlink(missing_ok=True)
    out = {}
    if meta.get("audio") and (dst / "audio" / meta["audio"]).exists():
        Path(LS.AUDIO_DIR).mkdir(exist_ok=True)
        pref = f"lf_{i:04d}_"
        for fn in (dst / "audio").iterdir():
            shutil.copy2(fn, Path(LS.AUDIO_DIR) / fn.name.replace("lf_PFX_", pref, 1))
        out = {"audio": str(Path(LS.AUDIO_DIR) / meta["audio"].replace("lf_PFX_", pref, 1)), "tts_hash": meta.get("tts_hash", "")}
        if meta.get("timing"):
            out["timing"] = str(Path(LS.AUDIO_DIR) / meta["timing"].replace("lf_PFX_", pref, 1))
    return out


def clear_cache(src=None):
    shutil.rmtree(CACHE / str(src) if src is not None else CACHE, ignore_errors=True)


def cleanup():
    """facts_db.json 에서 가상 소재(deep_of)와 그 대본 캐시·사진·음성 폴더를 지운다. -> 지운 개수"""
    try:
        db = _load_db()
    except Exception:
        return 0
    vidx = [i for i, f in enumerate(db) if isinstance(f, dict) and f.get("deep_of") is not None]
    if not vidx:
        return 0
    try:
        import longform_script as LS
        st0 = LS.load_scripts()
    except Exception:
        LS, st0 = None, {}
    for i in vidx:   # 지우기 전에 사진·음성을 deep_cache 로 옮겨 둔다 (다시 만들 때 재사용)
        try:
            _stash(i, db[i], (st0.get(str(i)) or {}), LS)
        except Exception as e:
            print(f"    [심층편] 캐시 보관 실패 {i}: {type(e).__name__}: {e}", flush=True)
    try:
        from common import visual_dir
        for i in vidx:
            shutil.rmtree(visual_dir(BASE, i, db[i]), ignore_errors=True)
    except Exception:
        pass
    try:
        st = LS.load_scripts()
        for i in vidx:
            st.pop(str(i), None)
        LS.save_scripts(st)
        for i in vidx:
            for f in Path(LS.AUDIO_DIR).glob(f"lf_{i:04d}_*"):
                try:
                    f.unlink()
                except OSError:
                    pass
    except Exception:
        pass
    keep = [f for f in db if not (isinstance(f, dict) and f.get("deep_of") is not None)]
    _save_db(keep)
    return len(vidx)


def materialize(src, data):
    """섹션마다 가상 소재를 facts_db.json 끝에 붙인다 -> (새 번호 목록). 롱폼 대본(잠금)도 같이 저장."""
    import longform_script as LS
    cleanup()
    db = _load_db()
    item = db[src]
    new = []
    for k, s in enumerate(data["sections"], 1):
        qs = [q for q in (s.get("image_queries") or []) if q] or [f"{item.get('country', '')} travel"] * 6
        qs = qs[:30]
        f = {"country": item.get("country", ""), "topic": f"{item.get('topic', '')} - {s.get('title', '')}",
             "title_line1": s.get("title", ""), "title_line2": str(item.get("country", "")), "narration": s["narration"],
             "status": "deep_part", "deep_of": src, "deep_part": k, "image_queries": qs, "scene_count": len(qs),
             "theme": item.get("theme", ""), "hook": "", "body": "", "twist": ""}
        db.append(f)
        new.append(len(db) - 1)
    _save_db(db)
    for k, (i, s) in enumerate(zip(new, data["sections"]), 1):
        ns_ = len(LS.split_sentences(s["narration"]))
        kw_ = [k_ for k_ in (s.get("keywords") or []) if isinstance(k_, dict) and 1 <= int(k_.get("sentence", 0)) <= ns_]
        _rs = {}
        try:
            _rs = _restore(src, k, i, db[i], LS)
        except Exception as e:
            print(f"    [심층편] 캐시 복원 실패 {k}: {type(e).__name__}: {e}", flush=True)
        if not s.get("kw_manual"):
            kw_ = align_keywords(s["narration"], kw_)
        _allc = [c for c in (s.get("clips") or []) if isinstance(c, dict) and c.get("path") and Path(c["path"]).exists()]
        _clips = [c for c in _allc if c.get("use", True)]
        _noclip = bool(s.get("clips")) and not _clips   # 받은 영상을 전부 '사용 안 함'으로 했으면 다시 검색하지 않는다
        LS.update_rec(i, {**_rs, "narration": s["narration"], "keywords": kw_, "compare": None, "recap": s.get("recap", ""),
                          "broll": [], "clip_queries": ([] if _noclip else list(s.get("clip_queries") or [q for q in (db[i].get("image_queries") or []) if q][:3])), "clips": _clips, "images": [], "compare_at": 0, "title1": s.get("title", ""),
                          "title2": str(item.get("country", ""))})
    return new


# ---------------------------------------------------------------- 직접 구성
def save_manual(idx, sections, style="story", minutes=8, extra=None):
    """UI 에서 직접 입력·수정·삭제·순서 변경한 섹션 목록을 저장 (모두 잠금). extra: intro_text/outro_text/recap/recap_cards/thumb"""
    d = load()
    cur = d.get(str(idx)) or {}
    secs, order = [], []
    for s in sections:
        narr = str(s.get("narration", "")).strip()
        if not narr:
            continue
        order.append(s.get("_from"))
        secs.append({"title": str(s.get("title", "")).strip()[:28] or narr[:12], "narration": narr, "keywords": s.get("keywords") or [],
                     "recap": str(s.get("recap", "")).strip() or str(s.get("title", "")).strip(), "image_queries": [q for q in (s.get("image_queries") or []) if q],
                     "angle": s.get("angle", "직접 입력"), "locked": True,
                     **({"kw_manual": True} if s.get("kw_manual") else {}), **({"clip_queries": s["clip_queries"]} if s.get("clip_queries") else {}),
                     **({"clips": s["clips"]} if s.get("clips") else {})})
    new = {**cur, "style": style, "n": len(secs), "minutes": minutes, "manual": True, "created": cur.get("created") or time.strftime("%Y-%m-%d %H:%M"),
           "sections": secs}
    for k, v in (extra or {}).items():
        if v in (None, "", {}):
            new.pop(k, None)
        else:
            new[k] = v
    d[str(idx)] = new
    save(d)
    try:   # 섹션을 지우거나 순서를 바꿨으면 사진·음성 캐시도 같은 자리로 옮긴다
        if any(o is not None for o in order) and order != list(range(1, len(order) + 1)):
            root = CACHE / str(idx)
            if root.exists():
                tmp = CACHE / f"_tmp_{idx}"
                shutil.rmtree(tmp, ignore_errors=True)
                tmp.mkdir(parents=True)
                for k, o in enumerate(order, 1):
                    if o is not None and (root / str(o)).exists():
                        shutil.copytree(root / str(o), tmp / str(k))
                shutil.rmtree(root, ignore_errors=True)
                shutil.move(str(tmp), str(root))
    except Exception as e:
        print(f"    [심층편] 캐시 정리 실패: {e}", flush=True)
    return new


# ---------------------------------------------------------------- 핵심 문구 맞추기 · 시나리오 미리보기 · 스톡 영상
def _bg(s):
    s = re.sub(r"[^0-9A-Za-z가-힣]", "", str(s or "").lower())
    return {s[i:i + 2] for i in range(len(s) - 1)} if len(s) >= 2 else ({s} if s else set())


def align_keywords(narration, kws):
    """핵심 문구가 실제로 그 말이 나오는 문장에 붙게 한다: 지정한 문장에 문구와 겹치는 글자가 없고 다른 문장에 있으면 그쪽으로 옮긴다.
    (추상적인 문구처럼 어느 문장에도 겹침이 없으면 그대로 둔다)"""
    import longform_script as LS
    sents = LS.split_sentences(narration)
    out = []
    for k in kws or []:
        if not isinstance(k, dict):
            continue
        try:
            n = int(k.get("sentence", 1))
        except (TypeError, ValueError):
            continue
        txt = str(k.get("text", "")).strip()
        if not txt or not sents:
            continue
        n = max(1, min(n, len(sents)))
        kb = _bg(txt)
        sc = [len(kb & _bg(s)) for s in sents]
        if kb and sc[n - 1] == 0 and max(sc) > 0:
            n = sc.index(max(sc)) + 1
        out.append({"sentence": n, "text": txt})
    return out


def scenario_rows(sec, cps=6.0):
    """섹션 대본 -> 문장별 [번호, 시작(초), 문장, 핵심문구]. 시간은 글자 수 비율 추정(음성을 만들면 실제와 조금 다를 수 있음)"""
    import longform_script as LS
    sents = LS.split_sentences(sec.get("narration", ""))
    kws = sec.get("keywords") or []
    if not sec.get("kw_manual"):
        kws = align_keywords(sec.get("narration", ""), kws)
    by = {}
    for k in kws:
        by.setdefault(k["sentence"], []).append(k["text"])
    rows, acc = [], 0.0
    for i, s in enumerate(sents, 1):
        rows.append({"n": i, "t": round(acc, 1), "text": s, "kw": " / ".join(by.get(i, []))})
        acc += len(re.sub(r"\s+", "", s)) / cps
    return rows, acc


def fetch_clips(src, k, queries, old=None, max_clips=3):
    """섹션 k 의 스톡 영상을 검색어마다 받아 deep_clips/ 에 둔다 -> [{query,path,source,...,use}]"""
    import longform_clips as LC
    if not LC.available():
        raise RuntimeError("PEXELS_API_KEY 또는 PIXABAY_API_KEY 가 없습니다")
    folder = BASE / "deep_clips" / str(src) / str(k)
    folder.mkdir(parents=True, exist_ok=True)
    old_by = {c.get("query"): c for c in (old or []) if c.get("path") and Path(c["path"]).exists()}
    res, used = [], set()
    for n, q in enumerate([x.strip() for x in queries if x and x.strip()][:max_clips], 1):
        if q in old_by:
            res.append(old_by[q]); used.add(old_by[q].get("id")); continue
        got = LC.fetch_query(q, folder / f"clip_{n}_{abs(hash(q)) % 10000}.mp4", used)
        if got:
            res.append({**got, "use": True})
    return res
