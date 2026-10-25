"""대본 교차검증: (1) 위키백과 근거 + (2) 생성과 다른 모델이 문장별로 검증.
CROSS_CHECK=1 일 때 generate_script.ensure_extras 가 호출한다.
모순(contradicted)이나 근거 없는 문장이 있으면 먼저 대본을 고쳐 쓰고(해당 문장을 바로잡거나 한정어를 붙이거나 삭제) 다시 검증한다.
CROSS_FIX(기본 3)번 고쳐도 모순(contradicted)이 남거나, 문장 절반 이상이 모순이면(소재 자체가 거짓) rejected 로 돌린다.
'근거 없음(unsupported)'만 남은 경우는 거짓이 아니라 확인 자료가 없는 것이므로 폐기하지 않고 cross_verdict=unsupported/partial 로 표시해 사람이 판단하게 한다.
검증 모델 호출이 전부 실패하면(한도 등) 폐기하지 않고 '미검증'으로 둔다."""
import json
import os
import re

import requests

from common import split_sentences

LANG = "en"
VERIFIERS = ["openai/gpt-oss-120b", "llama-3.3-70b-versatile", "openai/gpt-oss-20b", "llama-3.1-70b-versatile"]


def enabled():
    return os.environ.get("CROSS_CHECK", "0") == "1"


def _wiki(query, lang, n=2, chars=1500):
    base = f"https://{lang}.wikipedia.org/w/api.php"
    hdr = {"User-Agent": "shorts-factcheck/1.0"}
    try:
        r = requests.get(base, params={"action": "query", "list": "search", "srsearch": query,
                                       "srlimit": n, "format": "json"}, headers=hdr, timeout=15)
        titles = [h["title"] for h in r.json().get("query", {}).get("search", [])]
        out = []
        for t in titles:
            r = requests.get(base, params={"action": "query", "prop": "extracts", "exintro": 1,
                                           "explaintext": 1, "titles": t, "format": "json"},
                             headers=hdr, timeout=15)
            for p in r.json().get("query", {}).get("pages", {}).values():
                txt = (p.get("extract") or "").strip()
                if txt:
                    out.append(f"[{t}] {txt[:chars]}")
        return out
    except Exception:
        return []


def _parse(text):
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
    except Exception:
        return None
    return d if isinstance(d.get("claims"), list) else None


def _ask(client, models, system, prompt, parse=None):
    parse = parse or _parse
    for model in models:
        try:
            kw = {"max_completion_tokens": 4000, "extra_body": {"reasoning_effort": "low"}} \
                if "gpt-oss" in model else {"max_completion_tokens": 1500}
            r = client.chat.completions.create(
                model=model, temperature=0.1,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": prompt}], **kw)
            d = parse(r.choices[0].message.content if r.choices else "")
            if d:
                return d, model
        except Exception:
            continue
    return None, None


def _parse_fix(text):
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
    except Exception:
        return None
    return d if isinstance(d, dict) and str(d.get("narration", "")).strip() else None


def _fix_rounds():
    try:
        return max(0, int(os.environ.get("CROSS_FIX", "3") or 3))
    except ValueError:
        return 3


def _verify(client, verifiers, topic, ev, sents):
    """-> (verdict{n:v}, notes[], model) 또는 (None, None, None)"""
    numbered = "\n".join(f"{i}. {s}" for i, s in enumerate(sents, 1))
    evidence = "\n\n".join(ev) if ev else "(no encyclopedia text found - use only what you reliably know)"
    prompt = f"""You verify claims in a short-video script. Subject: {topic}

Evidence (encyclopedia intro text, may be incomplete):
{evidence}

Script sentences:
{numbered}

For EACH sentence give a verdict:
- supported: evidence or your reliable knowledge confirms it
- unsupported: a checkable factual claim that cannot be confirmed (no evidence either way, or too vague/absolute)
- contradicted: evidence or reliable knowledge says it is wrong
Sentences that make no factual claim (questions, rhetorical hooks, opinions, calls to think, transitions) are "supported" - do not flag them.
Be honest; do not guess "supported" for things you have never heard of.
Pure JSON only: {{"claims":[{{"n":1,"verdict":"supported|unsupported|contradicted","reason":"short"}}]}}"""
    data, used = _ask(client, verifiers, "You are a strict fact verifier. Output JSON only.", prompt)
    if not data:
        return None, None, None
    verdict, notes = {}, []
    for c in data["claims"]:
        try:
            n = int(c.get("n"))
        except Exception:
            continue
        v = str(c.get("verdict", "unsupported")).strip().lower()
        verdict[n] = v
        if v != "supported":
            notes.append(f"[{v}] {n}번 문장: {str(c.get('reason', '')).strip()}")
    return verdict, notes, used


def _rewrite(client, verifiers, fact, topic, ev, sents, verdict, notes, limits):
    """문제 문장만 바로잡거나 삭제한 새 대본. dict(narration, hook, body, twist) 또는 None"""
    flagged = [f"{i}. {s}  <-- {verdict.get(i, 'unsupported')}" for i, s in enumerate(sents, 1) if verdict.get(i, "unsupported") != "supported"]
    reasons = "\n".join(notes)
    evidence = "\n\n".join(ev) if ev else "(none)"
    ko = LANG != "en"
    lo, hi = limits
    style = (f"문체(존댓말, 짧은 문장, 이모지 없음)와 분량({lo}~{hi}자)은 유지하고 구독/좋아요 요청은 넣지 마세요."
             if ko else f"Keep the style (short plain sentences, no emojis) and length ({lo}-{hi} characters). No subscribe/like requests.")
    prompt = f"""You are a fact-correcting editor for a short-video script. Subject: {topic}
Fix ONLY the flagged sentences so that every sentence is true; keep the other sentences unchanged.
- contradicted: correct it to what the evidence/reliable knowledge says, or delete the sentence if it cannot be corrected.
- unsupported: rephrase with a hedge (many / some / often / in some places) and a clear scope, or delete it if it cannot be made accurate.
- Never add new facts that are not in the evidence or that you are not certain of. Never invent numbers, dates or amounts.
- Keep the narration coherent (hook -> body -> twist) after edits.
{style}

Evidence:
{evidence}

Full script (sentence numbers):
{chr(10).join(f"{i}. {s}" for i, s in enumerate(sents, 1))}

Flagged sentences:
{chr(10).join(flagged)}
Reasons:
{reasons}

Current hook: {fact.get('hook', '')}
Current body: {fact.get('body', '')}
Current twist: {fact.get('twist', '')}

Output pure JSON only: {{"narration": "...", "hook": "...", "body": "...", "twist": "..."}}
(hook/body/twist: update them to match the corrected narration, or copy the current ones if unaffected)"""
    d, _ = _ask(client, verifiers, "You are a careful fact-correcting editor. Output JSON only.", prompt, parse=_parse_fix)
    return d


def cross_check(client, models, fact, fix=None):
    """True 를 돌려주면 fact 가 변경된 것 (저장 필요).
    fix = (clean_narration, validate_narration, (최소글자, 최대글자)) 를 주면 모순/근거없음 문장을 고쳐 쓴 뒤 다시 검증한다.
    주지 않으면 예전처럼 곧바로 폐기한다."""
    narration = fact.get("narration", "")
    sents = split_sentences(narration)
    if not sents:
        return False
    topic = f"{fact.get('country', '')} {fact.get('topic', '')}".strip()
    wlang = "en" if LANG == "en" else "ko"
    ev = _wiki(topic, wlang)
    if wlang == "ko" and not ev:
        ev = _wiki(topic, "en")
    verifiers = [m for m in VERIFIERS if m in models] or list(models)
    finished = fact.get("status") in ("tts_done", "video_done")  # 음성/영상이 이미 있으면 대본을 고치거나 폐기하지 않고 기록만
    rounds = 0 if (fix is None or finished) else _fix_rounds()
    fact["cross_checked"] = True
    fact["cross_sources"] = len(ev)
    first_notes, fixed = [], 0
    last_cur = None
    for attempt in range(rounds + 1):
        verdict, notes, used = _verify(client, verifiers, topic, ev, sents)
        if verdict is None:
            if fixed:  # 고친 뒤 재검증 호출이 실패하면 고친 대본은 유지하되 미검증으로 표시
                fact["cross_verdict"] = "fixed_unverified"
                fact["cross_notes"] = ["[수정됨] " + n for n in first_notes] + ["고친 대본의 재검증 호출 실패 - 사람이 확인하세요"]
            else:
                fact["cross_verdict"] = "unchecked"
                fact["cross_notes"] = ["교차검증 모델 호출 실패(한도/오류) - 사람이 확인하세요"]
            print("  [교차검증] 모델 호출 실패 - 미검증으로 둡니다")
            return True
        n = len(sents)
        bad = sum(1 for v in verdict.values() if v == "contradicted")
        unsup = sum(1 for i in range(1, n + 1) if verdict.get(i, "unsupported") == "unsupported")
        if attempt == 0:
            first_notes = list(notes)
        fact["cross_model"] = used
        print(f"  [교차검증{'' if attempt == 0 else f' 재검증 {attempt}'}] 모델 {used}, 위키 근거 {len(ev)}개, 근거없음 {unsup}/{n}, 모순 {bad}")
        for n_ in notes:
            print("    - " + n_)
        mostly_bad = bad * 2 >= n   # 문장 절반 이상이 모순 -> 소재 자체가 거짓이라 고쳐 쓸 수 없음 (근거 없음은 폐기 사유가 아님)
        if bad == 0 and (unsup == 0 or attempt >= rounds or finished or fix is None):
            # 모순 없음. 근거 없는 문장이 남아도 폐기하지 않고 표시만 한다 (고쳐 쓰기를 다 썼거나 고칠 수 없는 경우)
            if unsup and fixed:
                notes = ["[수정 시도 후에도 근거 없음 남음] " + x for x in notes]
            fact["cross_verdict"] = ("fixed" if (fixed and not unsup) else ("ok" if not unsup else ("unsupported" if unsup * 2 >= n else "partial")))
            fact["cross_notes"] = (["[수정됨] " + x for x in first_notes] + notes) if fixed else notes
            if unsup:
                print(f"  [교차검증] 근거 없는 문장 {unsup}/{n} - 폐기하지 않고 '확인 필요'로 표시합니다")
            if fixed and not unsup:
                print(f"  [교차검증] 대본을 {fixed}번 고쳐 통과 (원문은 narration_original에 보관)")
            return True
        if bad == 0:
            pass   # 근거 없음만 남았고 아직 고칠 기회가 있다 -> 아래에서 고쳐 쓴다
        elif mostly_bad or attempt >= rounds or finished or fix is None:
            fact["cross_notes"] = (["[수정 시도 후에도 남음] " + x for x in notes] if fixed else notes)
            if finished:
                fact["cross_verdict"] = "contradicted" if bad else "unsupported"
                print("  [교차검증] 이미 음성/영상이 있는 소재라 폐기하지 않고 기록만 합니다 - 사람이 확인하세요")
                return True
            fact["cross_verdict"] = "contradicted"
            fact["status"] = "rejected"
            if mostly_bad:
                fact["reject_reason"] = f"교차검증: 소재 자체가 모순 (모순 {bad}, 근거없음 {unsup} / {n}문장)"
            else:
                fact["reject_reason"] = f"교차검증: 고쳐 써도 모순 {bad}건 남음"
            print(f"  [폐기] {fact['reject_reason']}")
            return True
        # ---- 고쳐 쓰기
        clean, validate, limits = fix
        new = _rewrite(client, verifiers, fact, topic, ev, sents, verdict, notes, limits)
        new_narr = clean(str(new.get("narration", ""))) if new else ""
        ok, why = validate(new_narr) if new_narr else (False, "응답 없음")
        if not ok:
            print(f"  [교차검증] 고쳐 쓴 대본이 기준에 안 맞습니다 ({why}) - 다시 시도")
            fact["cross_notes"] = notes
            continue
        if not fact.get("narration_original"):
            fact["narration_original"] = fact.get("narration", "")
        fact["narration"] = new_narr
        for k in ("hook", "body", "twist"):
            v = str(new.get(k, "")).strip()
            if v:
                fact[k] = v
        fact["highlights"] = None      # 대본이 바뀌었으니 핵심 문구는 새로 만든다
        fixed += 1
        sents = split_sentences(new_narr)
        print(f"  [교차검증] 문제 문장을 고쳐 썼습니다 ({fixed}회) - 다시 검증합니다")
    # 고쳐 쓰기가 기준에 계속 안 맞아 루프를 마친 경우: 모순이 있으면 폐기, 근거 없음뿐이면 원문 유지(확인 필요)
    if bad:
        fact["cross_verdict"] = "contradicted"
        fact["status"] = "rejected"
        fact["reject_reason"] = "교차검증: 모순 문장을 고쳐 쓰지 못함 (고친 대본이 길이/형식 기준에 안 맞음)"
        print(f"  [폐기] {fact['reject_reason']}")
    else:
        fact["cross_verdict"] = "unsupported"
        fact["cross_notes"] = ["[수정 실패, 원문 유지] " + x for x in notes]
        print("  [교차검증] 고쳐 쓰기가 기준에 안 맞아 원문을 유지합니다 - 사람이 확인하세요")
    return True
