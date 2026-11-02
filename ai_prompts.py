# -*- coding: utf-8 -*-
"""AI 이미지(콘티) 프롬프트 시트: 소재의 핵심 컷만 골라 이미지 생성용 프롬프트를 만든다 (이미지는 직접 만들어 my_images 에 넣음).

  python ai_prompts.py --indexes 117,118 --cuts 1            # 소재 117,118 의 1번 컷 프롬프트 -> ai_prompts.md
  python ai_prompts.py --pending --cuts 1,4 --discord        # 렌더링 대기 소재 전부, 1·4번 컷, 디스코드로도 전송

만든 이미지는 컷 이름(예: 117_01.png)으로 my_images/ 에 저장하면 자동 검색 사진보다 먼저 쓰입니다 (cuts.py 와 같은 규칙).
컷을 고르는 방법은 사람이 정합니다: 1번 컷(첫 장면)이 시선을 잡는 컷이라 기본값입니다."""
import argparse
import os
import sys
from pathlib import Path

from common import load_db, pending_render
from cuts import _chunks, _my_file, cut_name
from scenes import item_scene_count

DEFAULT_STYLE = ("clean editorial illustration, soft warm colors, simple composition, vertical 9:16, "
                 "no text, no letters, no logos, no watermark, no recognizable real people")


def parse_nums(s):
    out = []
    for p in str(s or "").replace(" ", "").split(","):
        if not p:
            continue
        if "-" in p:
            a, b = p.split("-", 1)
            out += list(range(int(a), int(b) + 1))
        else:
            out.append(int(p))
    return out


def build(db, idxs, cuts, style):
    """-> [{idx, country, cut, name, line, prompt, exists}]"""
    rows = []
    for i in idxs:
        if i < 0 or i >= len(db):
            continue
        it = db[i]
        if it.get("status") == "rejected":
            continue
        k = item_scene_count(it)
        qs = it.get("image_queries") or []
        lines = _chunks(it.get("narration"), k)
        for n in cuts:
            if not 1 <= n <= k:
                continue
            q = (qs[n - 1] if n - 1 < len(qs) else "") or str(it.get("country", ""))
            rows.append({"idx": i, "country": it.get("label") or it.get("country", ""), "cut": n, "name": cut_name(i, n),
                         "line": lines[n - 1], "prompt": f"{q}, {style}".strip(", "), "exists": bool(_my_file(i, n))})
    return rows


def to_md(rows):
    L = ["# AI 이미지 프롬프트 (콘티)", "",
         "각 프롬프트로 이미지를 만든 뒤 표시된 파일 이름으로 `my_images/` 에 저장하세요. (이미 있는 컷은 건너뛰어도 됩니다)", ""]
    for r in rows:
        L += [f"### [{r['idx']}] {r['country']} · {r['name']}" + ("  ✅ my_images 에 이미 있음" if r["exists"] else ""),
              f"- 저장 이름: `{r['name']}.png`", f"- 이 컷의 대본: {r['line']}", "", "```", r["prompt"], "```", ""]
    return "\n".join(L)


def send_discord(rows):
    url = os.environ.get("DISCORD_WEBHOOK_URL", "")
    if not url:
        print("DISCORD_WEBHOOK_URL 없음 → 디스코드 전송 생략")
        return
    from notify_discord import post
    post(url, f"🎨 **AI 이미지 프롬프트 {len(rows)}개** — 길게 눌러 복사 → 이미지 생성 → `컷이름.png` 로 my_images 에 저장")
    for r in rows:
        post(url, f"**{r['name']}** {r['country']}" + (" (이미 있음)" if r["exists"] else "") + f"\n대본: {r['line'][:120]}\n```{r['prompt']}```")
    print("디스코드로 전송했습니다.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--indexes", default="")
    ap.add_argument("--pending", action="store_true", help="렌더링 대기 소재 전부")
    ap.add_argument("--cuts", default="1", help="프롬프트를 만들 컷 번호 (예: 1 또는 1,4). 기본 1")
    ap.add_argument("--style", default=DEFAULT_STYLE)
    ap.add_argument("--out", default="ai_prompts.md")
    ap.add_argument("--discord", action="store_true")
    a = ap.parse_args()
    db = load_db()
    idxs = parse_nums(a.indexes) + ([i for i, _ in pending_render(db)] if a.pending else [])
    idxs = list(dict.fromkeys(idxs))
    if not idxs:
        sys.exit("대상 소재가 없습니다. --indexes 나 --pending 을 지정하세요.")
    rows = build(db, idxs, parse_nums(a.cuts), a.style)
    if not rows:
        sys.exit("만들 프롬프트가 없습니다 (폐기됐거나 컷 번호가 범위를 벗어남).")
    Path(a.out).write_text(to_md(rows), encoding="utf-8")
    print(to_md(rows))
    print(f"\n✅ {len(rows)}개 프롬프트 → {a.out}")
    if a.discord:
        send_discord(rows)


if __name__ == "__main__":
    main()
