# -*- coding: utf-8 -*-
"""소재 단계 '근거 부실' 걸러내기: 대본으로 넘어가기 전에, 일반론이거나 근거 없이 지어낸 듯한 소재를 폐기(rejected)한다.

  python grounding.py                 # 점검만 (DB를 바꾸지 않음)
  python grounding.py --llm           # AI 판정까지 해서 점수를 보여줌 (바꾸지 않음)
  python grounding.py --apply --llm   # 기준 미달 소재를 rejected 로 돌리고 사유(reject_reason)를 남김
  python grounding.py --recheck       # 이미 점검한 소재도 다시

대상: 아직 영상이 없는 소재(unverified/verified/scripted). 영상이 있거나 직접 쓴/고친 소재는 건드리지 않는다.
판정 기준 (각 0~10): distinct(그 나라·지역만의 구체적 내용인가, 세계 어디에나 있는 일반론이 아닌가) / concrete(고유명사·수치·작동 방식 등 구체 정보가 있는가) /
supported(위키 발췌문과 맞거나 널리 알려진 사실인가, 지어낸 디테일이 없는가).  평균이 기준(기본 5) 미만이거나 distinct·supported 가 3 이하면 폐기.
AI 판정을 못 하면(키 없음·호출 실패) 규칙으로 확실한 것(일반 문서 + 일반론 단서)만 폐기한다.
폐기한 소재는 UI의 '상태·폐기' 에서 사유를 보고 되살릴 수 있다."""
import argparse
import datetime as dt
import json
import os
import re
from pathlib import Path

DB = Path("facts_db.json")
EN = Path("generate_topics.py").exists() and not Path("generate_culture_facts.py").exists()
TARGET = ("unverified", "verified", "scripted")
VER = 1

GENERIC_CAVEAT = re.compile(r"(전 세계|세계 (여러|각)|다른 (지역|나라)|여러 (지역|나라)|어디서나|비슷(한|하게)).{0,12}(비슷|열리|있|존재|나타)|similar (festivals|practices|customs).{0,20}(elsewhere|around the world|in many)", re.I)
VAGUE = re.compile(r"전통과 현대|독특한|이색적인|인상적(이|인)|특별한 (경험|의미)|문화 체험|다양한 (의미|문화)|풍성하|활기찬|함께 (어우러|흘러)|여운|한층|많은 사람들이|살아 숨 쉬|"
                   r"unique (tradition|culture|experience)|vibrant|rich (culture|tradition)|blend of (tradition|modern)", re.I)


def _names(f):
    try:
        from country_codes import NAMES, country_code
        c = country_code(str(f.get("country", "")))
        if c and c in NAMES:
            return [x.lower() for x in NAMES[c] if x]
    except Exception:
        pass
    return [str(f.get("country", "")).lower()] if f.get("country") else []


def flags(f):
    """규칙 기반 점검: (flag 목록, 확실히 부실한지)"""
    out = []
    text = " ".join(str(f.get(k, "")) for k in ("hook", "body", "twist"))
    src = " ".join(str(f.get(k, "")) for k in ("wiki_title", "source_url", "source_excerpt")).lower()
    names = [] if EN else _names(f)
    generic_doc = False
    if f.get("wiki_title") and names:
        if not any(n and n in src for n in names):
            generic_doc = True
            out.append("근거 문서에 나라 언급 없음" if f.get("source_excerpt") else "근거 문서 제목에 나라 없음(일반 문서일 수 있음)")
    cav = bool(GENERIC_CAVEAT.search(str(f.get("caveat", ""))))
    if cav:
        out.append("한계 문장이 '다른 곳에도 비슷하게 있다'는 일반론")
    v = len(VAGUE.findall(text))
    if v >= 2:
        out.append(f"막연한 표현 {v}개")
    if not re.search(r"\d", text) and len(re.findall(r"[A-Za-z]{4,}", text)) < 2 and len(re.findall(r"\(", str(f.get("topic", "")) + text)) == 0:
        out.append("수치·원어 표기 같은 구체 정보 없음")
    sure = (generic_doc and cav) or (generic_doc and v >= 2) or (cav and v >= 2)
    return out, sure


def _models(client):
    mod = __import__("generate_topics" if EN else "generate_culture_facts")
    return [mod.pick_model(client)]


def _prompt(batch):
    blocks = []
    for n, (i, f) in enumerate(batch, 1):
        blocks.append(f"[{n}] 나라/주제: {f.get('country', '')} / {f.get('topic', '')}\n근거 문서: {f.get('wiki_title', '(없음)')}\n"
                      f"발췌문: {str(f.get('source_excerpt', '(저장 안 됨)'))[:600]}\n훅: {f.get('hook', '')}\n본문: {str(f.get('body', ''))[:420]}\n반전: {f.get('twist', '')}\n한계: {f.get('caveat', '')}")
    return f"""너는 유튜브 쇼츠 소재 검수자다. 아래 소재 {len(batch)}개가 영상으로 만들 만큼 근거가 탄탄하고 구체적인지 0~10점으로 평가해라.
- distinct: 그 나라·지역·집단만의 구체적인 내용인가. 세계 어디에나 있는 일반론(예: '와인 축제', '전통과 현대의 만남')이면 낮게.
- concrete: 고유명사, 수치, 제도·절차·작동 방식 등 시청자가 새로 배울 구체 정보가 있는가. 분위기·감상 위주면 낮게.
- supported: 발췌문과 맞거나 널리 문서화된 사실인가. 발췌문에 없는 디테일을 지어낸 듯하거나 근거 문서가 그 나라와 무관하면 낮게. 발췌문이 없으면 네가 아는 범위에서 판단하고 확신이 없으면 낮게.
엄격하게 평가하되 근거가 분명하면 높게 줘라. JSON 배열로만 응답: [{{"n":1,"distinct":0,"concrete":0,"supported":0,"reason":"한 줄 사유(한국어)"}}]

{chr(10).join(blocks)}"""


def judge(client, models, batch):
    kw = {"max_completion_tokens": 3000, "extra_body": {"reasoning_effort": "low"}} if "gpt-oss" in models[0] else {"max_completion_tokens": 1500}
    for m in models:
        try:
            r = client.chat.completions.create(model=m, messages=[{"role": "user", "content": _prompt(batch)}], temperature=0.2, **kw)
            t = r.choices[0].message.content or ""
            arr = json.loads(t[t.find("["):t.rfind("]") + 1])
            res = {}
            for x in arr:
                n = int(x["n"]) - 1
                if 0 <= n < len(batch):
                    res[n] = {k: max(0, min(10, int(x.get(k, 0)))) for k in ("distinct", "concrete", "supported")}
                    res[n]["reason"] = str(x.get("reason", ""))[:120]
            if res:
                return res
        except Exception as e:
            print(f"  AI 판정 실패: {type(e).__name__} {str(e)[:80]}")
    return {}


def verdict(g, thr):
    avg = (g["distinct"] + g["concrete"] + g["supported"]) / 3
    return avg < thr or g["distinct"] <= 3 or g["supported"] <= 3, round(avg, 1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--llm", action="store_true")
    ap.add_argument("--recheck", action="store_true")
    ap.add_argument("--thr", type=float, default=5.0)
    ap.add_argument("--limit", type=int, default=60, help="한 번에 AI 판정할 최대 소재 수")
    a = ap.parse_args()
    db = json.loads(DB.read_text(encoding="utf-8"))
    cand = []
    for i, f in enumerate(db):
        if f.get("status") not in TARGET or f.get("youtube_id") or f.get("confidence") == "user" or f.get("narration_user_edited"):
            continue
        if (f.get("grounding") or {}).get("v") == VER and not a.recheck:
            continue
        cand.append((i, f))
    print(f"점검 대상 {len(cand)}개")
    client = models = None
    if a.llm:
        try:
            from groq import Groq
            key = os.environ.get("GROQ_API_KEY", "").strip()
            if not key:
                raise RuntimeError("GROQ_API_KEY 없음")
            client = Groq(api_key=key)
            models = _models(client)
        except Exception as e:
            print(f"AI 판정을 쓸 수 없어 규칙만 적용합니다 ({e})")
    today = dt.date.today().isoformat()
    rej = 0
    judged = {}
    if client:
        todo = cand[:a.limit]
        for s in range(0, len(todo), 6):
            batch = todo[s:s + 6]
            for n, g in judge(client, models, batch).items():
                judged[batch[n][0]] = g
    for i, f in cand:
        fl, sure = flags(f)
        g = judged.get(i)
        bad, why = False, ""
        if g:
            bad, avg = verdict(g, a.thr)
            why = f"distinct {g['distinct']}/concrete {g['concrete']}/supported {g['supported']} (평균 {avg}) {g['reason']}"
            if fl:
                why += " · 규칙: " + ", ".join(fl)
            f["grounding"] = {"v": VER, "at": today, **g, "avg": avg, "flags": fl}
        elif sure:
            bad, why = True, "규칙 판정: " + ", ".join(fl)
            f["grounding"] = {"v": VER, "at": today, "flags": fl, "rule_only": True}
        elif client is None:
            continue   # AI 없이는 확실하지 않은 소재를 건드리지 않고, 다음에 AI로 판정하도록 표시 안 함
        else:
            continue   # 이번 한도 밖
        tag = "폐기" if bad else "통과"
        print(f"  [{i}] {tag} {f.get('country')} | {str(f.get('topic'))[:36]} — {why[:150]}")
        if bad:
            rej += 1
            if a.apply:
                f["status"] = "rejected"
                f["reject_reason"] = "근거 부실(자동): " + why[:200]
    if a.apply:
        DB.write_text(json.dumps(db, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"폐기 {'했음' if a.apply else '대상'} {rej}개" + ("" if a.apply else " (점검만, 바뀐 것 없음)"))


if __name__ == "__main__":
    main()
