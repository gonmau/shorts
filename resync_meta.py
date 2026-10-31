# -*- coding: utf-8 -*-
"""대본(narration)을 직접 바꾼 소재의 주제/훅/본문/반전/제목/핵심 문구/이미지 검색어를 새 대본에 맞게 다시 만든다.

 python resync_meta.py --indexes 286,304            # 주제·훅/본문/반전 → 제목·핵심 문구·이미지 검색어 순으로 다시 만듦
 python resync_meta.py --indexes 286 --keep-title   # 제목은 그대로 두고 나머지만
 python resync_meta.py --indexes 286 --only-empty   # (확인용) 아무것도 지우지 않고 빈 것만 채움
- 주제/훅/본문/반전은 '기존 값이 새 대본과 맞으면 그대로 돌려주도록' 요청해 불필요하게 바뀌지 않게 한다. 대본·나라·영상·업로드 기록은 건드리지 않는다.
- 소재당 AI 호출 약 3~4회(주제·훅 묶음 1 + 제목 + 핵심 문구 + 검색어). 필요: GROQ_API_KEY"""
import argparse
import os
import sys
from pathlib import Path

import generate_script as GS
from common import load_db, save_db

IS_EN = (Path(__file__).parent / "generate_topics.py").exists()


def build_prompt(f):
    if IS_EN:
        return f"""You edit metadata for a short YouTube video. The narration below is the final script. Rewrite the metadata fields ONLY where they no longer match the narration; if a field already matches, return it unchanged.

[Current topic] {f.get("topic", "")}
[Current hook] {f.get("hook", "")}
[Current body] {f.get("body", "")}
[Current twist] {f.get("twist", "")}

[Final narration]
{f.get("narration", "")}

Rules: hook = one attention-grabbing sentence matching the narration's opening; body = 1-3 sentences of the main facts stated in the narration; twist = the surprising point stated in the narration; topic = a short label of what the narration is about. Do not add facts that are not in the narration.
Output JSON only: {{"topic": "...", "hook": "...", "body": "...", "twist": "..."}}"""
    return f"""아래는 유튜브 쇼츠의 '최종 대본'과 현재 메타데이터입니다. 대본과 맞지 않는 항목만 대본에 맞게 고쳐 쓰고, 이미 맞는 항목은 그대로 돌려주세요.

[현재 주제] {f.get("topic", "")}
[현재 훅] {f.get("hook", "")}
[현재 본문] {f.get("body", "")}
[현재 반전] {f.get("twist", "")}

[최종 대본]
{f.get("narration", "")}

규칙: 훅=대본 첫머리와 어울리는 한 문장, 본문=대본에 나온 핵심 사실 1~3문장, 반전=대본에 나온 의외의 포인트, 주제=대본이 다루는 내용을 현재 주제와 같은 형식으로 한 줄. 대본에 없는 사실은 넣지 마세요. 주제의 형식(고유명사 표기 방식 등)은 현재 주제를 따르세요.
JSON만 출력: {{"topic": "...", "hook": "...", "body": "...", "twist": "..."}}"""


def parse_meta(text):
    try:
        d = GS.extract_json(text)
    except Exception:
        return None
    if not isinstance(d, dict):
        return None
    out = {k: " ".join(str(d.get(k, "")).split()) for k in ("topic", "hook", "body", "twist")}
    return out if all(out.values()) else None


def resync(client, models, f, keep_title=False, only_empty=False, retries=3):
    """소재 하나의 메타를 새 대본에 맞춘다. 바뀐 항목 이름 목록을 돌려준다."""
    changed = []
    if not str(f.get("narration", "")).strip():
        return changed
    if not only_empty:
        m = GS.ask_models(client, models, "You are a careful metadata editor. Output JSON only." if IS_EN else "당신은 꼼꼼한 메타데이터 편집자입니다. JSON만 출력하세요.",
                          build_prompt(f), 700, retries, parse_meta)
        if m:
            for k, v in m.items():
                if v != " ".join(str(f.get(k, "")).split()):
                    f[k] = v
                    changed.append(k)
        else:
            print("  [주의] 주제/훅/본문/반전 다시 만들기 실패 - 기존 값 유지")
        if not keep_title:
            for k in ("title_line1", "title_line2"):
                f.pop(k, None)
            changed.append("제목")
        f["highlights"] = None                       # 핵심 문구는 문장 번호에 묶여 있어 대본이 바뀌면 항상 다시 만든다
        changed.append("핵심문구")
        f.pop("image_queries", None)
        changed.append("이미지검색어")
    GS.ensure_extras(client, models, f, retries)      # 비어 있는 제목/핵심 문구/이미지 검색어를 채운다
    return changed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--indexes", required=True)
    ap.add_argument("--keep-title", action="store_true")
    ap.add_argument("--only-empty", action="store_true")
    a = ap.parse_args()
    idxs = [int(x) for x in a.indexes.replace(" ", "").split(",") if x.strip().isdigit()]
    key = os.getenv("GROQ_API_KEY")
    if not key:
        print("[오류] GROQ_API_KEY 환경변수가 없습니다.")
        sys.exit(1)
    client = GS.Groq(api_key=key, timeout=90.0)
    models = GS.pick_models(client, None)
    db = load_db()
    for n, i in enumerate(idxs, 1):
        if not (0 <= i < len(db)):
            print(f"[{i}] 범위 밖 - 건너뜀")
            continue
        f = db[i]
        print(f"[{n}/{len(idxs)}] [{i}] {f.get('country', '')}")
        ch = resync(client, models, f, a.keep_title, a.only_empty)
        save_db(db)
        print(f"  다시 만든 항목: {', '.join(ch) or '없음'} | 제목: {f.get('title_line1', '')} / {f.get('title_line2', '')}")
        for k in ("topic", "hook"):
            print(f"  {k}: {str(f.get(k, ''))[:70]}")
    print("끝. 영상에 반영하려면 해당 번호로 redo(영상만 다시) 후 렌더링하세요.")


if __name__ == "__main__":
    main()
