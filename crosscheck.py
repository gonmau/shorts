"""대본 교차검증: (1) 위키백과 근거 + (2) 생성과 다른 모델이 문장별로 검증.
CROSS_CHECK=1 일 때 generate_script.ensure_extras 가 호출한다.
모순(contradicted)이 있거나 근거 없는 문장이 절반 이상이면 소재를 rejected 로 돌린다.
검증 모델 호출이 전부 실패하면(한도 등) 폐기하지 않고 '미검증'으로 둔다."""
import json
import os
import re

import requests

from common import split_sentences

LANG = "ko"
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


def _ask(client, models, system, prompt):
    for model in models:
        try:
            kw = {"max_completion_tokens": 4000, "extra_body": {"reasoning_effort": "low"}} \
                if "gpt-oss" in model else {"max_completion_tokens": 1500}
            r = client.chat.completions.create(
                model=model, temperature=0.1,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": prompt}], **kw)
            d = _parse(r.choices[0].message.content if r.choices else "")
            if d:
                return d, model
        except Exception:
            continue
    return None, None


def cross_check(client, models, fact):
    """True 를 돌려주면 fact 가 변경된 것 (저장 필요)."""
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
    numbered = "\n".join(f"{i}. {s}" for i, s in enumerate(sents, 1))
    evidence = "\n\n".join(ev) if ev else "(no encyclopedia text found - use only what you reliably know)"
    prompt = f"""You verify claims in a short-video script. Subject: {topic}

Evidence (encyclopedia intro text, may be incomplete):
{evidence}

Script sentences:
{numbered}

For EACH sentence give a verdict:
- supported: evidence or your reliable knowledge confirms it
- unsupported: cannot confirm (no evidence either way, or too vague/absolute)
- contradicted: evidence or reliable knowledge says it is wrong
Be honest; do not guess "supported" for things you have never heard of.
Pure JSON only: {{"claims":[{{"n":1,"verdict":"supported|unsupported|contradicted","reason":"short"}}]}}"""
    data, used = _ask(client, verifiers, "You are a strict fact verifier. Output JSON only.", prompt)
    fact["cross_checked"] = True
    fact["cross_sources"] = len(ev)
    if not data:
        fact["cross_verdict"] = "unchecked"
        fact["cross_notes"] = ["교차검증 모델 호출 실패(한도/오류) - 사람이 확인하세요"]
        print("  [교차검증] 모델 호출 실패 - 미검증으로 둡니다")
        return True
    verdict = {}
    notes = []
    for c in data["claims"]:
        try:
            n = int(c.get("n"))
        except Exception:
            continue
        v = str(c.get("verdict", "unsupported")).strip().lower()
        verdict[n] = v
        if v != "supported":
            notes.append(f"[{v}] {n}번 문장: {str(c.get('reason', '')).strip()}")
    bad = sum(1 for v in verdict.values() if v == "contradicted")
    unsup = sum(1 for i in range(1, len(sents) + 1) if verdict.get(i, "unsupported") == "unsupported")
    fact["cross_notes"] = notes
    fact["cross_model"] = used
    if bad:
        fact["cross_verdict"] = "contradicted"
        fact["status"] = "rejected"
        fact["reject_reason"] = f"교차검증: 모순 {bad}건"
    elif unsup * 2 >= len(sents):
        fact["cross_verdict"] = "unsupported"
        fact["status"] = "rejected"
        fact["reject_reason"] = f"교차검증: 근거 없는 문장 {unsup}/{len(sents)}"
    else:
        fact["cross_verdict"] = "ok" if not unsup else "partial"
    print(f"  [교차검증] {fact['cross_verdict']} (모델 {used}, 위키 근거 {len(ev)}개, 근거없음 {unsup}/{len(sents)}, 모순 {bad})")
    for n_ in notes:
        print("    - " + n_)
    if fact.get("status") == "rejected":
        print(f"  [폐기] {fact['reject_reason']}")
    return True
