# -*- coding: utf-8 -*-
"""소재를 직접 추가한다 (facts_db.json 맨 뒤에 append). 끝에 'CREATED: 번호,번호' 한 줄을 출력한다.

  python add_topic.py manual  --narration "대본 전체" [--country 라오스] [--topic 주제] [--narration-file 파일]
      직접 쓴 대본으로 소재 생성 -> 상태 scripted. 제목/핵심문구/이미지 검색어는 이후
      python generate_script.py --extras-only --index N  으로 채운다. (LLM 호출 없음)
  python add_topic.py keyword --keyword "라오스 머리 만지기" [--wiki] [--approve]
      키워드로 소재(훅/본문/반전)를 만든다. --wiki 는 위키백과 발췌를 근거로 쓴다(없으면 모델 기억).
  python add_topic.py text    --text "SNS 글 내용" [--url 원문링크] [--approve]
      SNS/기사 글을 씨앗으로 소재를 만든다. 원문에 없는 사실은 넣지 않게 요청한다.
키워드/글 기반 소재는 기본 unverified(승인 대기). --approve 면 verified(바로 대본 생성 가능).
"""
import argparse
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from common import load_db, save_db, split_sentences

EN = not Path("generate_culture_facts.py").exists() and Path("generate_topics.py").exists()


def now():
    return datetime.now(timezone.utc).isoformat()


def guess_country(text):
    """대본에 나온 나라 이름을 찾는다 (한국어 채널용). 못 찾으면 ''."""
    try:
        import country_codes as C
    except Exception:
        return ""
    best, pos = "", 10 ** 9
    for code, (ko, en) in C.NAMES.items():
        for nm in (ko,):
            i = text.find(nm)
            if i != -1 and i < pos and len(nm) >= 2:
                best, pos = nm, i
    return best


def add_manual(a):
    text = a.narration or ""
    if a.narration_file:
        text = Path(a.narration_file).read_text(encoding="utf-8")
    text = " ".join(text.split())
    if len(text) < 60:
        raise SystemExit("대본이 너무 짧습니다 (60자 이상).")
    sents = split_sentences(text)
    country = (a.country or ("" if EN else guess_country(text))).strip()
    if not country:
        raise SystemExit("나라(또는 영어 채널은 짧은 제목)를 입력하세요. 대본에서 자동으로 찾지 못했습니다.")
    topic = (a.topic or sents[0])[:60].strip()
    item = {
        "country": country, "topic": topic, "theme": "직접 입력" if not EN else "manual",
        "hook": sents[0], "body": " ".join(sents[1:-1]) if len(sents) > 2 else "", "twist": sents[-1] if len(sents) > 1 else "",
        "caveat": "", "narration": text, "status": "scripted", "confidence": "user", "verify_note": "직접 입력한 대본",
        "fact_verifiability": "user", "fact_risk": "user-pending", "narration_user_edited": True, "created_at": now(),
    }
    return [item]


def _client():
    from groq import Groq
    key = os.environ.get("GROQ_API_KEY", "").strip()
    if not key:
        raise SystemExit("GROQ_API_KEY 환경변수가 없습니다.")
    return Groq(api_key=key)


def _model(client):
    mod = __import__("generate_topics" if EN else "generate_culture_facts")
    return mod.pick_model(client)


def wiki_extract(keyword):
    """키워드로 위키백과를 검색해 (제목, 링크, 발췌)를 돌려준다. 실패하면 None."""
    import requests
    for lang in (("en",) if EN else ("ko", "en")):
        try:
            r = requests.get(f"https://{lang}.wikipedia.org/w/api.php", params={
                "action": "query", "format": "json", "generator": "search", "gsrsearch": keyword, "gsrlimit": 3,
                "gsrnamespace": 0, "prop": "extracts|info", "exintro": 1, "explaintext": 1, "exchars": 1200,
                "exlimit": "max", "inprop": "url", "redirects": 1},
                headers={"User-Agent": "shorts-add-topic/1.0"}, timeout=25)
            r.raise_for_status()
            pages = (r.json().get("query") or {}).get("pages") or {}
            for p in sorted(pages.values(), key=lambda x: x.get("index", 99)):
                ext = " ".join(str(p.get("extract", "")).split())
                if len(ext) >= 200:
                    return p.get("title", ""), p.get("fullurl", ""), ext
        except Exception as e:
            print(f"  위키 검색 실패({lang}): {type(e).__name__}")
    return None


def build_prompt(seed, source_note, grounded):
    rule_src = ("아래 [자료]에 적힌 사실만 사용하고, 자료에 없는 숫자/연도/고유명사를 추가하지 마세요." if grounded
                else "확실히 알려진 사실만 쓰고, 불확실하면 빼세요. 숫자/연도는 확신할 때만 쓰세요.")
    if EN:
        return f"""Make ONE YouTube Shorts topic about Korea for international viewers from the seed below.
{'Use only facts in the [Material]; do not add numbers, dates or names that are not there.' if grounded else 'Use only well-documented facts; if unsure, leave it out. No numbers or dates unless highly confident.'}
No absolutes (everyone, always, never, illegal, the only/first/biggest), no stereotypes, no politics/religion debates. Say "many/often/in some places" and name the scope.
All fields in English.

[Material]
{seed[:1800]}
{source_note}

Respond with one pure JSON object only:
{{"label": "2-5 word title", "topic": "one-line summary", "hook": "opening line for the first 3 seconds", "body": "3 to 4 sentences", "twist": "one surprising extra detail", "caveat": "limits of this fact (where/when/for whom)", "confidence": "high/medium/low", "verify_note": "search keywords to fact-check"}}"""
    return f"""아래 씨앗으로 유튜브 쇼츠 소재를 딱 1개 만들어줘.
{rule_src}
"모든", "항상", "절대", "세계 최초" 같은 단정은 쓰지 말고, 일부 지역/일부 사람의 관습이면 범위를 한정하세요. 고정관념, 정치/종교 논쟁, 민감한 내용은 피하세요.
모든 필드는 한국어(고유명사는 한국어 표기 뒤에 괄호로 원어)로 쓰세요.

[자료]
{seed[:1800]}
{source_note}

JSON 객체 하나로만 응답 (설명/마크다운 금지):
{{"country": "나라 이름(한국어 한 단어)", "topic": "주제 한 줄 요약", "hook": "영상 시작 3초용 후킹 문장", "body": "본문 2~3문장 (배경 포함)", "twist": "반전이나 추가 정보 1문장", "caveat": "이 사실의 한계 한 문장 (어디서/누구에게/언제)", "confidence": "high/medium/low", "verify_note": "사실 확인용 검색 키워드"}}"""


def llm_item(seed, source_note="", grounded=False):
    client = _client()
    model = _model(client)
    last = None
    for max_tok in (1500, 1000):
        try:
            c = client.chat.completions.create(model=model, messages=[{"role": "user", "content": build_prompt(seed, source_note, grounded)}],
                                               max_completion_tokens=max_tok, temperature=0.5)
            text = c.choices[0].message.content or ""
            s, e = text.find("{"), text.rfind("}")
            if s == -1 or e <= s:
                raise ValueError("JSON 객체를 찾지 못함")
            return json.loads(text[s:e + 1])
        except Exception as ex:
            last = ex
            print(f"  Groq 오류, 다시 시도: {str(ex)[:120]}")
            time.sleep(8)
    raise SystemExit(f"소재 생성 실패: {str(last)[:200]}")


def add_seeded(a, seed, source_note="", grounded=False, extra=None):
    f = llm_item(seed, source_note, grounded)
    if EN:
        f["country"] = str(f.get("label") or f.get("topic") or "Korea").strip()
    for k in ("country", "topic", "hook", "body"):
        if not str(f.get(k, "")).strip():
            raise SystemExit(f"생성 결과에 {k}가 없습니다. 다시 시도하세요.")
    f.update({"status": "verified" if a.approve else "unverified", "created_at": now(), "theme": "키워드" if not EN else "keyword"})
    f.update(extra or {})
    return [f]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["manual", "keyword", "text"])
    ap.add_argument("--narration", default="")
    ap.add_argument("--narration-file", default="")
    ap.add_argument("--country", default="")
    ap.add_argument("--topic", default="")
    ap.add_argument("--keyword", default="")
    ap.add_argument("--text", default="")
    ap.add_argument("--url", default="")
    ap.add_argument("--wiki", action="store_true")
    ap.add_argument("--approve", action="store_true")
    a = ap.parse_args()

    if a.mode == "manual":
        items = add_manual(a)
    elif a.mode == "keyword":
        kw = a.keyword.strip()
        if not kw:
            raise SystemExit("키워드를 입력하세요.")
        w = wiki_extract(kw) if a.wiki else None
        if w:
            title, url, ext = w
            print(f"위키백과 근거: {title}")
            items = add_seeded(a, f"키워드: {kw}\n위키 문서: {title}\n발췌: {ext}", grounded=True,
                               extra={"source_url": url, "wiki_title": title, "verify_note": title, "confidence": "source"})
        else:
            if a.wiki:
                print("위키 근거를 못 찾아 모델 지식으로 만듭니다. 사실 확인이 꼭 필요합니다.")
            items = add_seeded(a, f"키워드: {kw}", extra={"seed_keyword": kw})
    else:
        t = " ".join(a.text.split())
        if len(t) < 30:
            raise SystemExit("글 내용이 너무 짧습니다 (30자 이상).")
        note = f"출처 링크: {a.url}" if a.url else ""
        items = add_seeded(a, t, note, grounded=True, extra={"source_url": a.url, "seed_text": t[:600],
                                                             "verify_note": a.url or "SNS 글 기반 - 사실 확인 필요", "confidence": "low"})

    db = load_db()
    start = len(db)
    db.extend(items)
    save_db(db)
    ids = list(range(start, len(db)))
    for i in ids:
        print(f"[{i}] {db[i].get('country')} - {db[i].get('topic')} ({db[i].get('status')})")
    print("CREATED: " + ",".join(map(str, ids)))


if __name__ == "__main__":
    main()
