# -*- coding: utf-8 -*-
"""시청자 니즈·감정 기반 설계: 소재마다 '어떤 니즈를 충족하고 어떤 감정을 일으킬지'를 붙이고,
그에 맞는 대본 구성 틀·이미지 분위기를 프롬프트에 넣고, 내 채널의 니즈별 조회수 성과를 계산한다.

  python audience.py --tag-new --limit 60      # 니즈/감정이 없는 소재에 태그 (업로드된 소재 먼저, Groq 사용)
  python audience.py --stats                   # 니즈별 성과 표

- 소재 필드: need(니즈 id), emotion(감정 id). 대본 생성 때 없으면 자동으로 붙인다.
- 성과: yt_stats.json 의 마지막 스냅샷 조회수를 소재의 youtube_id 와 이어서 니즈별 평균을 낸다. 표본이 적으면 전체 평균 쪽으로 당겨(shrink) 과신하지 않는다.
- 구성 틀은 '어떻게 구성할지'만 정하며, 사실은 항상 주어진 자료에서만 가져온다."""
import argparse
import json
import os
import statistics
from pathlib import Path

BASE = Path(__file__).resolve().parent
EN = (BASE / "generate_topics.py").exists() and not (BASE / "generate_culture_facts.py").exists()

# id: (한국어 라벨, English label, 한국어 설명, 한국어 구성 틀, English structure, 이미지 분위기(영문))
NEEDS = {
    "curiosity": ("호기심 해소", "Curiosity", "왜 그런지 궁금한 것을 풀어 준다",
                  "①첫 문장에서 의문(의외의 상황)을 제시 ②흔한 추측을 짧게 깨기 ③진짜 이유·원리를 차례로 풀기 ④처음의 의문에 답하며 마무리. 시청자가 '아, 그래서!' 하고 느끼게.",
                  "1) open with the puzzling situation 2) briefly break the common guess 3) explain the real reason or mechanism step by step 4) close by answering the opening question, so the viewer thinks 'so that's why!'.",
                  "intriguing, detail-focused shots of the object or place in question"),
    "surprise": ("놀람·반전", "Surprise", "예상을 뒤집는 사실로 놀라게 한다",
                 "①결과나 장면부터 던지기 ②'그런데'로 반전을 이른 지점(약 1/3)에 배치 ③배경 설명은 짧게 ④가장 의외인 디테일로 마무리.",
                 "1) start with the result or scene 2) put the twist early (about one third in) 3) keep background short 4) end on the most unexpected detail.",
                 "striking, unexpected, high-contrast scenes"),
    "practical": ("실용·정보", "Practical info", "알아두면 쓸모 있는 규칙·방법을 준다",
                  "①어떤 상황인지 ②핵심 규칙 1~3개를 또렷하게 ③해야 할 것과 하지 말 것 대비 ④기억에 남는 한 줄로 정리. 정보는 3개 이내.",
                  "1) set the situation 2) give 1-3 clear key rules 3) contrast do vs don't 4) wrap up in one memorable line. No more than 3 pieces of information.",
                  "clear, well-lit shots of the actual object, place or action being used"),
    "relatable": ("공감·비교", "Relatability", "내 일상과 견주어 보게 한다",
                  "①시청자 일상과 맞닿은 장면 ②우리와 다른 점 대비 ③그렇게 된 사정 ④'나라면?'을 떠올리게 하는 여운(질문으로 끝내지 않기).",
                  "1) a scene close to the viewer's daily life 2) contrast with what they know 3) why it is that way 4) a lingering line that makes them picture themselves there (do not end with a question).",
                  "everyday street-level scenes in warm natural light"),
    "awe": ("감탄·경외", "Awe", "규모·아름다움·역사에 감탄하게 한다",
            "①장면의 규모나 아름다움 ②역사·유래 ③사람들에게 의미하는 것 ④담담한 여운 한 문장. 과장 없이 차분하게.",
            "1) the scale or beauty of the scene 2) history or origin 3) what it means to people 4) one calm lingering line. No hype.",
            "wide, scenic, golden-light shots with a sense of scale"),
    "humor": ("웃음·기묘함", "Amusement", "엉뚱하고 재미있는 사실로 웃게 한다",
              "①엉뚱한 상황 ②진지하게 이어지는 사실 ③웃음 포인트 ④가볍게 마무리. 특정 집단 비하·조롱은 금지.",
              "1) an odd situation 2) delivered with a straight face 3) the funny point 4) a light ending. No mockery of any group.",
              "playful, quirky everyday scenes"),
}
# id: (한국어, English)
EMOTIONS = {"surprise": ("놀람", "surprise"), "curiosity": ("호기심", "curiosity"), "wonder": ("감탄", "wonder"), "empathy": ("공감", "empathy"),
            "amusement": ("웃음", "amusement"), "pride": ("뿌듯함", "pride"), "caution": ("경각심", "caution")}


def label(kind, i):
    d = NEEDS if kind == "need" else EMOTIONS
    return d[i][1 if EN else 0] if i in d else (i or "")


def norm(kind, v):
    """id 또는 한/영 라벨을 id 로 바꾼다 (못 찾으면 '')"""
    d = NEEDS if kind == "need" else EMOTIONS
    v = str(v or "").strip().lower()
    if v in d:
        return v
    for k, t in d.items():
        if v in (str(t[0]).lower(), str(t[1]).lower()):
            return k
    return ""


def script_block(fact):
    """대본 프롬프트 뒤에 붙일 니즈 설계 문단 (태그가 없으면 '')"""
    n = norm("need", fact.get("need"))
    if not n:
        return ""
    e = norm("emotion", fact.get("emotion"))
    t = NEEDS[n]
    if EN:
        return (f"\n\n[Viewer-need design]\n- Need this video serves: {t[1]}" + (f"; emotion to evoke: {EMOTIONS[e][1]}" if e else "") +
                f"\n- Structure: {t[4]}\n- This only shapes HOW you structure it; facts must come only from the material above.")
    return (f"\n\n[시청자 니즈 설계]\n- 이 영상이 충족할 니즈: {t[0]} ({t[2]})" + (f", 일으킬 감정: {EMOTIONS[e][0]}" if e else "") +
            f"\n- 구성 틀: {t[3]}\n- 이 틀은 '어떻게 구성할지'에만 적용하고, 사실은 위 자료에서만 가져옵니다.")


def image_block(fact):
    """이미지 검색어 프롬프트에 붙일 분위기 문단"""
    n = norm("need", fact.get("need"))
    if not n:
        return ""
    return f"\n\nVisual mood to prefer when several queries would fit equally well: {NEEDS[n][5]}. Never let the mood override rule 3 (match what the scene says)."


# ---------------- 태그 붙이기 ----------------
def _legend():
    return "; ".join(f"{k}={v[1]}" for k, v in NEEDS.items()), "; ".join(f"{k}={v[1]}" for k, v in EMOTIONS.items())


def _parse(t):
    try:
        return json.loads(t[t.find("{"):t.rfind("}") + 1])
    except Exception:
        return None


def ensure_tags(client, models, fact):
    """need/emotion 이 없으면 모델로 한 번 분류해 fact 에 넣는다 (실패하면 조용히 넘어감). 바뀌었으면 True"""
    if norm("need", fact.get("need")) and norm("emotion", fact.get("emotion")):
        return False
    nl, el = _legend()
    txt = " | ".join(str(fact.get(k, "")) for k in ("topic", "hook", "body", "twist"))[:900]
    prompt = (f"Classify this short-video topic.\nTopic: {txt}\nneed (pick the ONE main viewer need): {nl}\nemotion (pick the ONE main emotion): {el}\n"
              'Answer with JSON only: {"need":"id","emotion":"id"}')
    for m in models:
        try:
            kw = {"max_completion_tokens": 1200, "extra_body": {"reasoning_effort": "low"}} if "gpt-oss" in str(m) else {"max_completion_tokens": 80}
            r = client.chat.completions.create(model=m, messages=[{"role": "user", "content": prompt}], temperature=0.1, **kw)
            d = _parse(r.choices[0].message.content or "") or {}
            n, e = norm("need", d.get("need")), norm("emotion", d.get("emotion"))
            if n:
                fact["need"] = n  # 추론 모델은 토큰이 부족하면 빈 응답이 오므로 위에서 한도를 늘림
                if e:
                    fact["emotion"] = e
                return True
        except Exception:
            continue
    return False


# ---------------- 성과 ----------------
def views_by_id():
    try:
        d = json.loads((BASE / "yt_stats.json").read_text(encoding="utf-8"))
        return {v.get("id"): int(v.get("views", 0)) for v in d[-1]["videos"]}
    except Exception:
        return {}


def performance(db, k=3):
    """니즈별 {n, avg, median, rel}. rel = 표본이 적으면 1.0 쪽으로 당긴 상대 성과(전체 평균 대비). 데이터가 없으면 {}"""
    vw = views_by_id()
    rows = [(norm("need", f.get("need")), vw[f["youtube_id"]]) for f in db if f.get("youtube_id") in vw and norm("need", f.get("need"))]
    if not rows:
        return {}
    allavg = sum(v for _, v in rows) / len(rows)
    out = {}
    for n in NEEDS:
        vs = [v for k_, v in rows if k_ == n]
        if not vs:
            continue
        shr = (sum(vs) + k * allavg) / (len(vs) + k)
        out[n] = {"n": len(vs), "avg": int(sum(vs) / len(vs)), "median": int(statistics.median(vs)), "rel": round(shr / allavg, 2) if allavg else 1.0}
    return out


def perf_text(db):
    p = performance(db)
    if not p:
        return ""
    return "\n".join(f"- {label('need', n)}: 영상 {s['n']}개, 평균 조회수 {s['avg']:,}, 상대 성과 x{s['rel']}" for n, s in sorted(p.items(), key=lambda x: -x[1]["rel"]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag-new", action="store_true")
    ap.add_argument("--limit", type=int, default=60)
    ap.add_argument("--stats", action="store_true")
    a = ap.parse_args()
    from common import load_db, save_db
    db = load_db()
    if a.stats or not a.tag_new:
        t = perf_text(db)
        print(t or "성과 데이터가 없습니다 (yt_stats.json 과 태그된 업로드 영상이 필요)")
        tagged = sum(1 for f in db if norm("need", f.get("need")))
        print(f"태그된 소재 {tagged}/{len(db)}")
        if not a.tag_new:
            return
    from groq import Groq
    key = os.environ.get("GROQ_API_KEY", "").strip()
    if not key:
        raise SystemExit("GROQ_API_KEY 가 없습니다")
    client = Groq(api_key=key)
    mod = __import__("generate_topics" if EN else "generate_culture_facts")
    models = [mod.pick_model(client)]
    todo = [i for i, f in enumerate(db) if f.get("status") != "rejected" and not (norm("need", f.get("need")) and norm("emotion", f.get("emotion")))]
    todo.sort(key=lambda i: (0 if db[i].get("youtube_id") else 1, i))
    todo = todo[:a.limit]
    print(f"태그 대상 {len(todo)}개")
    n_ok = 0
    for j, i in enumerate(todo, 1):
        if ensure_tags(client, models, db[i]):
            n_ok += 1
            print(f"  [{i}] {label('need', db[i].get('need'))} / {label('emotion', db[i].get('emotion'))}")
        if j % 10 == 0:
            save_db(db)
    save_db(db)
    print(f"완료: {n_ok}/{len(todo)}개 태그")


if __name__ == "__main__":
    main()
