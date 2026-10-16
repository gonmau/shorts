# -*- coding: utf-8 -*-
"""교차확인용 한글 번역: 유튜브 제목/설명/대본을 한국어로 옮겨 facts_db.json(ko_*)에 저장한다.

영상 제작에는 쓰이지 않고, review.txt와 디스코드 알림에서 영어 내용을 한글로 확인하는 용도.
"""
import argparse
import hashlib
import json
import os
import sys
import time

from groq import Groq

from common import load_db, pending_render, save_db, youtube_meta
from generate_script import ask_models, extract_json, pick_models


def source_text(item):
    title, desc = youtube_meta(item)
    return title, desc, str(item.get("narration", "")).strip()


def source_hash(item):
    title, desc, narr = source_text(item)
    issues = "|".join(item.get("fact_issues") or [])
    return hashlib.md5("\n".join([title, desc, narr, issues]).encode("utf-8")).hexdigest()[:12]


def build_prompt(item):
    title, desc, narr = source_text(item)
    issues = item.get("fact_issues") or []
    return f"""Translate the following YouTube Shorts texts about Korea from English into natural Korean.
This is only for a Korean editor to cross-check the English content, so translate faithfully and literally.
Do not soften, add or omit claims. Keep hashtags, emoji and the channel line as they are.

[title]
{title}

[description]
{desc}

[narration]
{narr}

[fact-check notes]
{json.dumps(issues, ensure_ascii=False)}

Respond with a pure JSON object only:
{{"title": "...", "description": "...", "narration": "...", "issues": ["Korean translation of each fact-check note"]}}"""


def parse(text):
    d = extract_json(text)
    if isinstance(d, dict) and d.get("title") and d.get("narration"):
        return d
    return None


def ensure_ko(client, models, item, retries=3):
    """번역이 없거나 원문(제목/설명/대본)이 바뀌었으면 다시 번역. 바뀐 게 있으면 True."""
    if not item.get("narration"):
        return False
    h = source_hash(item)
    if item.get("ko_src") == h and item.get("ko_narration"):
        return False
    d = ask_models(client, models, "You are a precise English-to-Korean translator. Output JSON only.",
                   build_prompt(item), 3500, retries, parse)
    if not d:
        print("  [한글 번역 실패]")
        return False
    item["ko_title"] = str(d["title"]).strip()
    item["ko_description"] = str(d.get("description", "")).strip()
    item["ko_narration"] = str(d["narration"]).strip()
    item["ko_issues"] = [str(x).strip() for x in (d.get("issues") or []) if str(x).strip()]
    item["ko_src"] = h
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=3)
    ap.add_argument("--start", type=int, default=0)
    args = ap.parse_args()
    if not os.getenv("GROQ_API_KEY"):
        print("GROQ_API_KEY 없음 - 번역 건너뜀")
        return
    client = Groq(api_key=os.environ["GROQ_API_KEY"])
    models = pick_models(client, None)
    db = load_db()
    n = 0
    for idx, item in pending_render(db, args.start):
        if n >= args.limit:
            break
        n += 1
        print(f"[번역] {idx} {item.get('country', '')}")
        if ensure_ko(client, models, item):
            save_db(db)
            print(f"  -> {item['ko_title']}")
        time.sleep(1.0)
    print(f"한글 번역 점검: {n}개")


if __name__ == "__main__":
    main()
