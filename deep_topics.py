# -*- coding: utf-8 -*-
"""롱폼 서사형 주제 후보: (1) 조회수 높은 기존 쇼츠 (2) AI 제안.
- from_stats(): yt_stats.json 에서 소재별 최고 성과 쇼츠를 점수(조회수 x 평균시청률 + 구독 가중)로 정렬
- propose(): AI 가 서사로 풀기 좋은 주제를 제안 -> deep_topics.json 에 저장. 고르면 seed() 가 facts_db 에 'deep_seed' 소재로 추가
"""
import json
import re
from pathlib import Path

BASE = Path(__file__).resolve().parent
STATS = BASE / "yt_stats.json"
PROP = BASE / "deep_topics.json"
DB = BASE / "facts_db.json"


def _load(p, d):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:
        return d


def from_stats(limit=15):
    snaps = _load(STATS, [])
    best = {}
    for s in snaps if isinstance(snaps, list) else []:
        for v in s.get("videos", []):
            if v.get("kind") != "short" or not v.get("own", True) or v.get("idx") is None:
                continue
            i = int(v["idx"])
            sc = v.get("views", 0) * (v.get("averageViewPercentage", 0) / 100.0) + 30 * v.get("subscribersGained", 0)
            if i not in best or sc > best[i]["score"]:
                best[i] = {"idx": i, "score": round(sc), "views": v.get("views", 0), "pct": round(v.get("averageViewPercentage", 0)),
                           "subs": v.get("subscribersGained", 0), "country": v.get("country", ""), "topic": v.get("topic") or v.get("title", "")}
    try:
        import deep as D
        done = set(D.load().keys())
    except Exception:
        done = set()
    rows = [r for r in best.values() if str(r["idx"]) not in done]
    return sorted(rows, key=lambda r: -r["score"])[:limit]


def load_proposals():
    return _load(PROP, [])


def propose(client, models, n=8, hint=""):
    """AI 가 서사형 롱폼 주제 n개를 제안 -> 저장 후 반환"""
    top = from_stats(8)
    seen = [f"{r['topic']}" for r in top]
    db = _load(DB, [])
    used = [str(f.get("topic", "")) for f in db[-120:] if isinstance(f, dict)]
    old = [p["topic"] for p in load_proposals()]
    prompt = f"""한국어 유튜브 채널 '세계 문화 상식'의 8~12분 서사형 롱폼 주제를 {n}개 제안하세요.
서사형 = 사실 나열이 아니라 '궁금증 -> 배경 -> 갈등 -> 반전 -> 지금 -> 여운' 한 줄기 이야기로 풀 수 있는 주제.
조건:
- 세계 각지의 문화·관습·생활 지식. 특정 개인 비방, 정치·종교 갈등, 확인 어려운 통계가 핵심인 주제 제외.
- 소제목처럼 짧은 주제명(25자 이내) + 한 줄 훅(궁금증을 던지는 문장) + 이야기로 풀 만한 이유 한 줄.
- 최근 반응 좋았던 소재와 같은 결: {', '.join(seen) or '(없음)'}
- 이미 다룬 것과 겹치지 않게: {', '.join(used[-60:]) or '(없음)'} / 이미 제안한 것: {', '.join(old[-30:]) or '(없음)'}
{('- 추가 요청: ' + hint) if hint else ''}
순수 JSON 배열만: [{{"label":"나라/지역/짧은 라벨","topic":"...","hook":"...","why":"..."}}]"""
    out = None
    for m in models:
        try:
            kw = ({"max_completion_tokens": 6000, "extra_body": {"reasoning_effort": "low"}} if "gpt-oss" in m else {"max_completion_tokens": 2500})
            r = client.chat.completions.create(model=m, temperature=0.8, messages=[{"role": "user", "content": prompt}], **kw)
            txt = r.choices[0].message.content if r.choices else ""
            mm = re.search(r"\[.*\]", txt or "", re.S)
            if mm:
                arr = json.loads(mm.group(0))
                out = [a for a in arr if isinstance(a, dict) and str(a.get("topic", "")).strip()]
                if out:
                    break
        except Exception as e:
            print(f"    [주제 제안] {m} 실패: {type(e).__name__}: {str(e)[:100]}", flush=True)
    if not out:
        raise SystemExit("주제를 만들지 못했습니다 (GROQ_API_KEY/한도 확인)")
    allp = load_proposals() + [{"label": str(a.get("label", "")).strip()[:14], "topic": str(a["topic"]).strip()[:40],
                                "hook": str(a.get("hook", "")).strip(), "why": str(a.get("why", "")).strip()} for a in out[:n]]
    PROP.write_text(json.dumps(allp[-60:], ensure_ascii=False, indent=1), encoding="utf-8")
    return allp[-n:]


def seed(label, topic, hook=""):
    """AI 제안 주제를 facts_db 에 'deep_seed' 소재로 추가 -> 번호. (쇼츠 파이프라인 대상 아님)"""
    db = _load(DB, [])
    for i, f in enumerate(db):
        if isinstance(f, dict) and f.get("status") == "deep_seed" and f.get("topic") == topic:
            return i
    db.append({"country": label or topic[:14], "topic": topic, "title_line1": topic[:14], "title_line2": label or "",
               "narration": hook or topic, "status": "deep_seed", "theme": "", "hook": hook, "body": "", "twist": ""})
    DB.write_text(json.dumps(db, ensure_ascii=False, indent=2), encoding="utf-8")
    return len(db) - 1


if __name__ == "__main__":
    import argparse
    import longform_script as LS
    ap = argparse.ArgumentParser()
    ap.add_argument("--propose", type=int, default=0)
    ap.add_argument("--hint", default="")
    ap.add_argument("--seed", default="", help="라벨|주제|훅")
    a = ap.parse_args()
    if a.propose:
        c, ms = LS.client_models()
        for r in propose(c, ms, a.propose, a.hint):
            print(f"- [{r['label']}] {r['topic']} :: {r['hook']}")
    if a.seed:
        l, t_, h = (a.seed.split("|") + ["", ""])[:3]
        print("SEED", seed(l, t_, h))
