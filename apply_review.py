# -*- coding: utf-8 -*-
"""review.txt에서 고친 제목/핵심 문구를 facts_db.json에 반영합니다."""
import argparse
import re
from pathlib import Path

from common import load_db, save_db, split_sentences

HEAD = re.compile(r"^===\s*\[(\d+)\]")
TITLE = re.compile(r"^제목\s*([12])\s*[:：]\s*(.*)$")
NARR = re.compile(r"^대본\s*\[\s*(\d+)\s*\]\s*[:：]\s*(.*)$")
FIELD = re.compile(r"^(후크|본문|반전)\s*[:：]\s*(.*)$")
FIELD_KEY = {"후크": "hook", "본문": "body", "반전": "twist"}
HL = re.compile(r"^핵심\s*\[\s*(\d+)\s*\]\s*[:：]\s*(.*)$")


def parse(text):
    blocks, cur = {}, None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("(대본"):
            continue
        m = HEAD.match(line)
        if m:
            cur = blocks.setdefault(int(m.group(1)), {"t1": None, "t2": None, "hl": [], "narr": {}, "fields": {}})
            continue
        if cur is None:
            continue
        m = TITLE.match(line)
        if m:
            cur["t" + m.group(1)] = m.group(2).strip()
            continue
        m = NARR.match(line)
        if m:
            cur["narr"][int(m.group(1))] = m.group(2).strip()
            continue
        m = FIELD.match(line)
        if m:
            cur["fields"][FIELD_KEY[m.group(1)]] = m.group(2).strip()
            continue
        m = HL.match(line)
        if m and m.group(2).strip():
            cur["hl"].append({"s": int(m.group(1)), "text": m.group(2).strip()})
    return blocks


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default="review.txt")
    args = ap.parse_args()

    path = Path(args.file)
    if not path.exists():
        print("review.txt 없음 - 건너뜀")
        return

    blocks = parse(path.read_text(encoding="utf-8"))
    db = load_db()
    changed = 0
    for idx, b in blocks.items():
        if not (0 <= idx < len(db)):
            continue
        item = db[idx]
        before = (item.get("title_line1"), item.get("title_line2"), item.get("highlights"))
        if b["t1"]:
            item["title_line1"] = b["t1"]
        if b["t2"]:
            item["title_line2"] = b["t2"]
        hl = sorted(b["hl"], key=lambda h: h["s"])  # 문장 번호 순
        if hl or item.get("highlights") is not None:
            item["highlights"] = hl  # 빈 리스트 = 핵심 문구 표시 안 함
        edited = False
        if b["narr"]:
            old = split_sentences(item.get("narration", ""))
            new = [t for _, t in sorted(b["narr"].items()) if t]
            if new and new != old:
                item.setdefault("narration_original", item.get("narration", ""))
                item["narration"] = " ".join(new)
                for k in ("audio_path_v2", "timing_path_v2", "tts_voice_v2", "status_tts_v2"):
                    item.pop(k, None)  # 대본이 바뀌었으니 음성을 다시 만든다
                edited = True
        for k, v in b["fields"].items():
            if v and v != " ".join(str(item.get(k, "")).split()):
                item[k] = v
                edited = True
        if edited:
            # 사람이 직접 고친 소재: AI 검수가 덮어쓰지 않게 하고 새 대본 기준으로 번역을 다시 한다
            item["fact_verifiability"] = "user"
            item["fact_risk"] = "user-reviewed"
            item["fact_applied"] = True
            changed += 1
            print(f"  [{idx}] {item.get('country', '')}: 대본/설명 직접 수정 반영 (음성 다시 생성)")
        if before != (item.get("title_line1"), item.get("title_line2"), item.get("highlights")):
            changed += 1
            print(f"  [{idx}] {item.get('country', '')}: 수정 반영")
    if changed:
        save_db(db)
    print(f"review.txt 반영: {changed}개 소재 수정")


if __name__ == "__main__":
    main()
