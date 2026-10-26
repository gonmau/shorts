# -*- coding: utf-8 -*-
"""영상으로 만들 소재의 제목/핵심 문구를 사람이 고치기 쉬운 review.txt로 내보냅니다."""
import argparse
from pathlib import Path

from common import load_db, pending_render, split_sentences

HEADER = """# 영상 제작 전 검수 파일 (고친 뒤 저장/Commit 하고 render 실행)
# - 제목1/제목2: 영상 상단에 크게 들어가는 제목입니다.
# - 대본[번호]: 영상에서 읽는 대본 문장입니다. 직접 고치면 그대로 반영되어 음성이 다시 만들어집니다.
#   (팩트체크한 수정 대본을 문장별로 붙여넣으세요. 문장을 지우면 대본에서 빠지고 번호는 위에서부터 다시 매겨집니다)
# - 후크/본문/반전: 유튜브 설명에 들어가는 문구입니다. 고치면 설명과 디스코드에 반영됩니다.
# - 핵심[번호]: 화면 하단에 크게 띄울 문구입니다. 번호는 '대본[N]'의 문장 번호입니다.
#   *별표*로 감싼 단어는 노란색으로 강조됩니다. 줄을 지우면 그 문구는 영상에서 빠집니다.
# - 이미지[번호]: 장면 이미지 6장의 영어 검색어(Pixabay)입니다. 고치면 그 검색어로 이미지를 다시 받습니다.
#   대본을 고치고 이미지 줄은 그대로 두면, 새 대본에 맞춰 검색어를 자동으로 다시 만듭니다.
# - 제외: 이 소재를 영상으로 만들지 않으려면 뒤에 사유(또는 '예')를 적으세요. 비워 두면 그대로 제작합니다.
#   제외한 소재는 폐기(rejected)로 바뀌어 render에서 건너뛰고, 나중에 'redo_script=번호!'로 되살릴 수 있습니다.
# - '('로 시작하는 줄은 참고용이라 무시됩니다. '=== [번호] ===' 줄은 바꾸지 마세요.
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
        if item.get("fact_risk"):
            lines.append(f"(사실 검수 위험도) {item['fact_risk']}")
        for n, t in enumerate(item.get("fact_issues") or [], start=1):
            lines.append(f"(검수 메모 {n}) {t}")
        if item.get("cross_verdict"):
            lines.append(f"(교차검증) {item['cross_verdict']}")
        for n, t in enumerate(item.get("cross_notes") or [], start=1):
            lines.append(f"(교차검증 메모 {n}) {t}")
        for f_ in item.get("cross_flags") or []:
            lines.append(f"(직접 확인할 문장 {f_.get('n')}번) {f_.get('text')}")
        if item.get("verify_note"):
            lines.append(f"(사실 확인용 검색어) {item['verify_note']}")
        for key, label in (("hook", "후크"), ("body", "본문"), ("twist", "반전")):
            lines.append(f"{label}: {' '.join(str(item.get(key, '')).split())}")
        lines.append("제외:")
        lines.append(f"제목1: {item.get('title_line1', '')}")
        lines.append(f"제목2: {item.get('title_line2', '')}")
        for h in item.get("highlights") or []:
            lines.append(f"핵심[{h['s']}]: {h['text']}")
        for n, q in enumerate(item.get("image_queries") or [], start=1):
            lines.append(f"이미지[{n}]: {q}")
        for n, sent in enumerate(split_sentences(item["narration"]), start=1):
            lines.append(f"대본[{n}]: {sent}")
        blocks.append("\n".join(lines))
        if len(blocks) >= args.limit:
            break

    Path(args.out).write_text(HEADER + "\n" + "\n\n".join(blocks) + "\n", encoding="utf-8")
    print(f"{args.out}: {len(blocks)}개 소재 내보냄")


if __name__ == "__main__":
    main()
