# -*- coding: utf-8 -*-
"""편집 포인트: '첫 화면에 갈색 치즈를 크게 보여주고, "초콜릿이 아니라 치즈" 대목에서 일반 치즈와 교차 편집' 같은 지시를
소재별 item["edit_points"] 로 해석/저장하고, 영상 제작 때 그대로 반영한다. (쇼츠 전용)

  python edit_points.py parse --index N --text "편집 지시 자연어"   # Groq로 구조화 -> item["edit_points"]
  python edit_points.py fetch --index N [--force]                  # 지시에 나온 이미지(영어 검색어)를 받아 visuals/<폴더>/edit_K_J.png 로 저장

edit_points 한 개:
  {"at": "start"|"sentence"|"phrase", "sentence": 3, "phrase": "초콜릿이 아니라 치즈",
   "action": "show"(그 이미지를 큰 화면으로) | "cross"(여러 이미지를 번갈아 반복 교차 편집) | "sequence"(여러 이미지를 순서대로 한 번씩 전환),
   "to_sentence": 3(선택: 이 문장까지 구간을 늘림),
   "queries": ["brown cheese brunost", "cheddar cheese"], "dur": null(초, 없으면 그 문장 길이), "interval": 0.9, "note": "원문 지시"}
구간은 해당 문장이 읽히는 동안(at=start 는 첫 문장)입니다. 지시는 언제든 바꿔 다시 해석하면 됩니다.
"""
import argparse
import json
import os
import re
import time
from pathlib import Path

from common import load_db, save_db, split_sentences, visual_dir

BASE_DIR = Path(__file__).resolve().parent


def _norm(t):
    return re.sub(r"[^0-9a-z가-힣]", "", str(t or "").lower())


def build_prompt(sentences, text):
    num = "\n".join(f"{i}. {s}" for i, s in enumerate(sentences, 1))
    return f"""영상 편집 지시를 구조화된 JSON으로 바꿔줘. 이 영상은 아래 대본(문장 번호 포함)을 읽는 쇼츠야.

[대본]
{num}

[편집 지시]
{text}

규칙:
- 지시마다 편집 포인트 1개. at: 첫 화면/시작이면 "start", 특정 문장 번호면 "sentence"(sentence에 번호), 특정 대목/문구면 "phrase"(phrase에 대본에 나온 문구 그대로, sentence에는 그 문구가 있는 문장 번호도 함께).
- action: 한 이미지를 크게 보여주면 "show", 둘 이상을 번갈아 반복해 보여주는 교차 편집이면 "cross", "A 다음 B 다음 C 순으로 전환"처럼 순서대로 한 번씩 넘기면 "sequence".
- queries: 보여줄 이미지를 사진 검색용 영어 2~5단어로 (지시에 나온 순서대로). show는 1개, cross/sequence는 2개 이상 (예: "brown cheese brunost", "cheddar cheese").
- to_sentence: 구간이 여러 문장에 걸쳐야 할 때(예: "시작해서 3번 문장까지", sequence로 여러 장면을 순서대로 넘길 때) 끝 문장 번호, 아니면 null. 지시에 범위가 없으면 sequence는 시작 문장부터 대본의 앞 절반 정도까지(문장 수의 절반 번호)로 정해줘.
- 완성된 결과물보다 "만드는 과정" 장면을 먼저 보여달라는 지시는 그 과정 장면을 찍은 사진을 찾을 검색어로 바꿔 show로 처리 (예: "hand sprinkling colored powder pattern").
- dur: 지시에 초 단위가 있을 때만 숫자, 없으면 null. interval: 교차 간격(초), 지시 없으면 0.9.
- note: 원래 지시 한 줄.
JSON 배열로만 응답 (설명/마크다운 금지):
[{{"at": "start", "sentence": 1, "to_sentence": null, "phrase": "", "action": "show", "queries": ["..."], "dur": null, "interval": 0.9, "note": "..."}}]"""


def parse_text(sentences, text):
    from groq import Groq
    key = os.environ.get("GROQ_API_KEY", "").strip()
    if not key:
        raise SystemExit("GROQ_API_KEY 환경변수가 없습니다.")
    client = Groq(api_key=key)
    mod = __import__("generate_topics" if (not Path("generate_culture_facts.py").exists() and Path("generate_topics.py").exists()) else "generate_culture_facts")
    model = mod.pick_model(client)
    last = None
    for _ in range(2):
        try:
            c = client.chat.completions.create(model=model, messages=[{"role": "user", "content": build_prompt(sentences, text)}],
                                               max_completion_tokens=1500, temperature=0.1)
            t = c.choices[0].message.content or ""
            return clean(json.loads(t[t.find("["):t.rfind("]") + 1]), len(sentences))
        except Exception as e:
            last = e
            time.sleep(6)
    raise SystemExit(f"해석 실패: {str(last)[:200]}")


def clean(points, n_sent):
    out = []
    for p in points:
        qs = [str(q).strip() for q in (p.get("queries") or []) if str(q).strip()]
        if not qs:
            continue
        act = p.get("action") if (p.get("action") in ("cross", "sequence") and len(qs) >= 2) else "show"
        at = p.get("at") if p.get("at") in ("start", "sentence", "phrase") else "sentence"
        try:
            sn = min(max(int(p.get("sentence") or 1), 1), max(n_sent, 1))
        except (TypeError, ValueError):
            sn = 1
        try:
            dur = float(p["dur"]) if p.get("dur") not in (None, "", 0) else None
        except (TypeError, ValueError):
            dur = None
        try:
            iv = max(0.3, float(p.get("interval") or 0.9))
        except (TypeError, ValueError):
            iv = 0.9
        try:
            ts = int(p["to_sentence"]) if p.get("to_sentence") not in (None, "", 0) else None
            ts = min(max(ts, sn), max(n_sent, 1)) if ts else None
        except (TypeError, ValueError):
            ts = None
        out.append({"at": at, "sentence": sn, "to_sentence": ts, "phrase": str(p.get("phrase") or "").strip(), "action": act,
                    "queries": qs[:6] if act in ("cross", "sequence") else qs[:1], "dur": dur, "interval": iv, "note": str(p.get("note") or "")[:200]})
    return out


def resolve(points, timings, audio_duration):
    """편집 포인트 -> [(시작, 끝, action, 이미지 번호들(queries 순), interval)]. timings: [{start,end,text}]"""
    res = []
    if not timings:
        return res
    for k, p in enumerate(points or [], 1):
        idx = None
        if p.get("at") == "start":
            idx = 0
        elif p.get("at") == "phrase" and p.get("phrase"):
            ph = _norm(p["phrase"])
            for i, t in enumerate(timings):
                if ph and ph in _norm(t["text"]):
                    idx = i
                    break
            if idx is None:  # 문구가 문장 경계에 걸리거나 약간 다르면 글자 겹침이 가장 큰 문장
                grams = lambda s: {s[i:i + 2] for i in range(len(s) - 1)}
                g = grams(ph)
                best = max(range(len(timings)), key=lambda i: len(g & grams(_norm(timings[i]["text"]))) if g else 0)
                if g and len(g & grams(_norm(timings[best]["text"]))) >= max(2, len(g) // 3):
                    idx = best
        if idx is None:
            idx = min(max(int(p.get("sentence") or 1) - 1, 0), len(timings) - 1)
        t0 = float(timings[idx]["start"])
        t1 = float(timings[idx]["end"])
        if p.get("to_sentence"):
            t1 = float(timings[min(max(int(p["to_sentence"]) - 1, idx), len(timings) - 1)]["end"])
        if p.get("dur"):
            t1 = t0 + float(p["dur"])
        t1 = min(max(t1, t0 + 0.6), audio_duration)
        if t1 - t0 < 0.3:
            continue
        res.append((t0, t1, p.get("action", "show"), list(range(len(p.get("queries") or []))), float(p.get("interval") or 0.9), k))
    return res


def image_path(folder, k, j):
    return Path(folder) / f"edit_{k}_{j}.png"


def fetch_points(idx, item, force=False):
    import requests
    import commons
    import fetch_images as F
    key = os.environ.get("PIXABAY_API_KEY", "").strip()
    folder = visual_dir(BASE_DIR, idx, item)
    sess = requests.Session()
    credits, ok = [], 0
    for k, p in enumerate(item.get("edit_points") or [], 1):
        for j, q in enumerate(p.get("queries") or []):
            dest = image_path(folder, k, j)
            if dest.exists() and not force:
                ok += 1
                continue
            got = None
            try:
                hit, rel = (F.pick(sess, key, q, set()) if key else (None, False))
                if hit and rel:
                    F.download(sess, hit["largeImageURL"], dest)
                    got = {"source": "pixabay", "user": hit.get("user", ""), "page": hit.get("pageURL", "")}
                else:
                    c = commons.search(sess, q, set())
                    if c:
                        F.download(sess, c["url"], dest, {"User-Agent": commons.UA})
                        got = {"source": "commons", "user": c["artist"], "license": c["license"], "title": c["title"], "page": c["page"]}
                    elif hit:
                        F.download(sess, hit["largeImageURL"], dest)
                        got = {"source": "pixabay", "user": hit.get("user", ""), "page": hit.get("pageURL", "")}
            except Exception as e:
                print(f"  포인트{k}-{j} '{q}' 실패: {type(e).__name__} {str(e)[:80]}")
            if got:
                got["scene"] = 100 + k * 10 + j
                credits.append(got)
                ok += 1
                print(f"  포인트{k}-{j} '{q}' -> {got['source']}")
            else:
                print(f"  포인트{k}-{j} '{q}': 이미지를 못 받았습니다 (이 포인트는 건너뜀)")
            time.sleep(0.7)
    old = [c for c in (item.get("edit_credits") or []) if c.get("scene") not in {c2["scene"] for c2 in credits}]
    item["edit_credits"] = sorted(old + credits, key=lambda c: c["scene"])
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["parse", "fetch"])
    ap.add_argument("--index", type=int, required=True)
    ap.add_argument("--text", default="")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    db = load_db()
    item = db[a.index]
    if a.mode == "parse":
        sents = split_sentences(item.get("narration", ""))
        if not sents:
            raise SystemExit("대본이 없습니다.")
        pts = parse_text(sents, a.text) if a.text.strip() else []
        item["edit_points_text"] = a.text
        item["edit_points"] = pts
        save_db(db)
        print(json.dumps(pts, ensure_ascii=False, indent=1))
        print(f"편집 포인트 {len(pts)}개 저장")
    else:
        n = fetch_points(a.index, item, a.force)
        save_db(db)
        print(f"이미지 {n}장 준비")


if __name__ == "__main__":
    main()
