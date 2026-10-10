# -*- coding: utf-8 -*-
"""영상으로 만들 소재의 제목/핵심 문구를 사람이 고치기 쉬운 review.txt로 내보냅니다."""
import argparse
from pathlib import Path

from common import load_db, pending_render, split_sentences

HEADER = """# 영상 제작 전 검수 파일
# - 제목1/제목2: 영상 상단에 크게 들어가는 제목입니다. 자유롭게 고치세요.
# - 핵심[번호]: 화면 하단에 크게 띄울 문구입니다. 번호는 '(대본 N)'의 문장 번호입니다.
#   *별표*로 감싼 단어는 노란색으로 강조됩니다. 줄을 지우면 그 문구는 영상에서 빠집니다.
# - '(대본'으로 시작하는 줄은 참고용이라 무시됩니다. '===[번호]===' 줄은 바꾸지 마세요.
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=3)
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--out", default="review.txt")
    args = ap.parse_args()

    db = load_db()
    blocks = []
    for idx, item in pending_render(db, args.start):
        if not item.get("narration"):
            continue
        lines = [f"=== [{idx}] {item.get('country', '')} ==="]
        lines.append(f"제목1: {item.get('title_line1', '')}")
        lines.append(f"제목2: {item.get('title_line2', '')}")
        for h in item.get("highlights") or []:
            lines.append(f"핵심[{h['s']}]: {h['text']}")
        for n, sent in enumerate(split_sentences(item["narration"]), start=1):
            lines.append(f"(대본 {n}) {sent}")
        blocks.append("\n".join(lines))
        if len(blocks) >= args.limit:
            break

    Path(args.out).write_text(HEADER + "\n" + "\n\n".join(blocks) + "\n", encoding="utf-8")
    print(f"{args.out}: {len(blocks)}개 소재 내보냄")


if __name__ == "__main__":
    main()
