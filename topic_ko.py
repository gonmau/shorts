# -*- coding: utf-8 -*-
"""한국어 채널: 영어로 저장된 소재 주제(topic)를 한국어로 옮겨 topic_ko.json 에 저장한다 (facts_db.json·대본은 건드리지 않음).
목록/디스코드 미리보기에서 shown(idx,item) 으로 한국어 주제를 쓴다. 한글이 이미 있으면 그대로.
사용: python topic_ko.py [--start N] [--indexes 116,117] [--all]"""
import argparse
import json
import os
import re
from pathlib import Path

BASE = Path(__file__).resolve().parent
F = BASE / "topic_ko.json"


def _load():
    try:
        return json.loads(F.read_text(encoding="utf-8"))
    except Exception:
        return {}


def has_hangul(s):
    return bool(re.search(r"[가-힣]", str(s or "")))


def shown(idx, item, cache=None):
    """목록에 보여줄 주제: 한글이면 그대로, 영어면 번역본(있으면), 없으면 원문"""
    t = str(item.get("topic", "") or "")
    if has_hangul(t):
        return t
    c = cache if cache is not None else _load()
    return c.get(str(idx)) or t


def translate(db, idxs):
    from groq import Groq
    from generate_script import ask_models, extract_json, pick_models
    cache = _load()
    todo = [i for i in idxs if 0 <= i < len(db) and not has_hangul(db[i].get("topic")) and str(i) not in cache and db[i].get("topic")]
    if not todo:
        print("번역할 영어 주제가 없습니다.")
        return 0
    client = Groq(api_key=os.environ["GROQ_API_KEY"])
    models = pick_models(client)
    n = 0
    for s in range(0, len(todo), 25):
        part = todo[s:s + 25]
        lines = "\n".join(f"{i}: {db[i].get('topic')} ({db[i].get('country', '')})" for i in part)
        prompt = ("아래 번호: 영어 문화 주제를 자연스러운 한국어 제목으로 옮겨 주세요. 나라/지명/축제 이름은 한국어 표기(예: 오악사카, 코르도바)를 쓰고 "
                  "의미를 바꾸거나 덧붙이지 마세요. JSON 객체로만 답하세요: {\"번호\": \"한국어 주제\"}\n\n" + lines)

        def parse(text):
            d = extract_json(text)
            return d if isinstance(d, dict) else None
        res = ask_models(client, models, "당신은 정확한 한영 번역가입니다. JSON만 출력합니다.", prompt, 2000, 2, parse) or {}
        for k, v in res.items():
            v = str(v).strip()
            if has_hangul(v) and str(k).isdigit():
                cache[str(k)] = v
                n += 1
    F.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"주제 한국어 번역 {n}개 저장 (topic_ko.json)")
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--indexes", default="")
    ap.add_argument("--all", action="store_true")
    a = ap.parse_args()
    db = json.loads((BASE / "facts_db.json").read_text(encoding="utf-8"))
    if a.indexes:
        from build_longform import parse_indexes
        idxs = parse_indexes(a.indexes)
    else:
        idxs = [i for i in range(len(db)) if a.all or i >= a.start]
    translate(db, idxs)


if __name__ == "__main__":
    main()
