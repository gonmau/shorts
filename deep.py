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


def plan(n, en=False):
    A = ANGLES_EN if en else ANGLES_KO
    n = max(3, min(8, int(n)))
    return A[:n - 1] + [A[-1]]


def chars_per_section(minutes, n, en=False):
    sec = float(minutes) * 60.0 / max(1, n)
    return int(sec * (14.5 if en else 6.7))


def scenes_per_section(minutes, n):
    s = round(float(minutes) * 60.0 / max(1, n) / 9)
    return max(6, min(16, s + (s % 2)))


def _prompt(item, ev, angle, k, n, prev, minutes, instruction, en):
    country = str(item.get("country", "")).strip()
    topic = str(item.get("topic") or item.get("title_line1") or "").strip()
    short = str(item.get("narration", "")).strip()
    cps = chars_per_section(minutes, n, en)
    lo, hi = int(cps * 0.85), int(cps * 1.15)
    nq = scenes_per_section(minutes, n)
    evidence = "\n".join(ev)[:2400] if ev else "(none)"
    prev_txt = "\n".join(f"- {p}" for p in prev) or "(none yet)"
    ins = (f"\n- Editor's extra instruction (follow it): {instruction}" if en else f"\n- 편집자 추가 지시 (반드시 반영): {instruction}") if instruction else ""
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
- recap: ONE short line (<=60 chars) summarising this section.{ins}
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
- recap: 이 섹션 한 줄 요약 (30자 이내).{ins}
순수 JSON만 출력:
{{"title":"...","narration":"...","keywords":[{{"sentence":1,"text":"..."}}],"image_queries":["..."],"recap":"..."}}"""


def generate(client, models, idx, item, n=5, minutes=8, instruction="", only=None):
    """섹션 대본 생성 -> deep_db.json 저장 (이미 잠긴 섹션은 only 가 아니면 유지). -> dict"""
    import crosscheck as C
    import longform_script as LS
    en = LS.IS_EN
    d = load()
    cur = d.get(str(idx)) or {}
    secs_old = cur.get("sections") or []
    pl = plan(n, en)
    topic = f"{item.get('country', '')} {item.get('topic', '')}".strip()
    ev = C._wiki(topic, "en" if en else "ko") or ([] if en else C._wiki(topic, "en"))
    secs, prev = [], []
    for k, ang in enumerate(pl, 1):
        old = secs_old[k - 1] if k - 1 < len(secs_old) else None
        if old and old.get("locked") and not (only and k in only):
            secs.append(old)
            prev.append(f"{old.get('title', '')}: " + " ".join(LS.split_sentences(old.get("narration", ""))[:2]))
            continue
        if old and not only and cur.get("n") == n and old.get("narration") and not instruction:
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
                                 _prompt(item, ev, ang, k, n, prev, minutes, instruction, en), tokens=3500)
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
    d[str(idx)] = {"n": n, "minutes": minutes, "created": time.strftime("%Y-%m-%d %H:%M"), "instruction": instruction, "sections": secs}
    save(d)
    return d[str(idx)]


def script_text(idx, item, data):
    L = [f"[심층편] {item.get('country', '')} - {item.get('topic', '')}  (섹션 {len(data['sections'])}개)", ""]
    for k, s in enumerate(data["sections"], 1):
        L += [f"[{k}. {s.get('title', '')}] ({len(s.get('narration', ''))}자)", s.get("narration", ""), ""]
    return "\n".join(L)


def title(item, minutes, en=False):
    c = str(item.get("country", "")).strip()
    t = str(item.get("topic", "")).strip()
    if en:
        return f"{t}: The Complete Story ({c})"[:95]
    return f"{c} {t} 완전 정리 | 깊이 있게 보기"[:95]


def intro_text(item, n, en=False):
    c = str(item.get("country", "")).strip()
    t = str(item.get("topic", "")).strip()
    if en:
        return f"Welcome to Korea A to Z. Today we take one subject and go deep: {t}. We will walk through it in {n} parts. Let's get started."
    return f"오늘은 {c}의 {t}, 이 이야기 하나만 깊이 있게 살펴보겠습니다. 총 {n}가지 이야기로 풀어 볼게요. 끝까지 보시면 이 문화가 조금 다르게 보일 거예요. 지금 시작합니다."


def outro_text(recaps, en=False):
    if en:
        return "Quick recap. " + " ".join(f"Part {i}: {r.rstrip('.')}." for i, r in enumerate(recaps, 1) if r) + " Thanks for watching, and see you in the next video."
    return "오늘 이야기를 한 번에 정리해 볼게요. " + " ".join(f"{i}부, {r.rstrip('.')}." for i, r in enumerate(recaps, 1) if r) + " 끝까지 봐 주셔서 감사합니다. 다음 영상에서 만나요."


# ---------------------------------------------------------------- 가상 소재
def _load_db():
    return json.loads(DB_FILE.read_text(encoding="utf-8"))


def _save_db(db):
    DB_FILE.write_text(json.dumps(db, ensure_ascii=False, indent=2), encoding="utf-8")


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
        from common import visual_dir
        for i in vidx:
            shutil.rmtree(visual_dir(BASE, i, db[i]), ignore_errors=True)
    except Exception:
        pass
    try:
        import longform_script as LS
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
        LS.update_rec(i, {"narration": s["narration"], "keywords": kw_, "compare": None, "recap": s.get("recap", ""),
                          "broll": [], "clip_queries": [], "clips": [], "images": [], "compare_at": 0, "title1": s.get("title", ""),
                          "title2": str(item.get("country", ""))})
    return new
