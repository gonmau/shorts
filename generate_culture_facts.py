"""
세계 문화 상식 쇼츠 - 소재 자동 생성 스크립트

기능:
1. Claude API로 국가별 흥미로운 문화 상식 소재를 배치 생성
2. facts_db.json에 누적 저장, 이미 쓴 소재(국가+주제)는 중복 방지 (같은 나라도 주제가 다르면 허용)
3. 각 소재는 훅 문장 + 본문 설명 + 반전/추가정보 구조로 생성되어
   바로 다음 단계(스크립트→TTS) 파이프라인에 넣을 수 있는 형태

사용법:
    Groq 무료 API 키 발급: https://console.groq.com/keys (신용카드 등록 불필요)

    Windows PowerShell: $env:GROQ_API_KEY="발급받은키"
    Windows cmd:        set GROQ_API_KEY=발급받은키
    영구 등록(cmd):      setx GROQ_API_KEY "발급받은키"  (새 창부터 적용)
    Mac/Linux:           export GROQ_API_KEY="발급받은키"

    pip install groq --break-system-packages
    python generate_culture_facts.py --count 20

실행할 때마다 DB에 새 소재가 append 되며, 이미 사용한 국가+주제 조합은
프롬프트에 포함시켜 LLM이 겹치지 않게 생성하도록 유도합니다.
"""

import json
import os
import argparse
from datetime import datetime, timezone
from pathlib import Path

from groq import Groq

DB_PATH = Path("facts_db.json")

# Groq 모델 카탈로그가 자주 바뀌므로 하드코딩 대신 선호 순서대로 사용 가능한 모델을 탐지한다
PREFERRED_MODELS = [
    "llama-3.1-8b-instant",   # 일반 instruct 모델, reasoning 토큰 소모 없어 우선 사용
    "llama-3.3-70b-versatile",
    "llama-3.1-70b-versatile",
    "gemma2-9b-it",
    "openai/gpt-oss-120b",    # reasoning 모델, 위 모델들 없을 때만 사용
]


def pick_model(client: Groq) -> str:
    available = {m.id for m in client.models.list().data}
    for name in PREFERRED_MODELS:
        if name in available:
            return name
    # 선호 목록에 없으면 사용 가능한 첫 번째 모델 사용
    if available:
        fallback = sorted(available)[0]
        print(f"선호 모델이 없어 사용 가능한 모델로 대체: {fallback}")
        return fallback
    raise SystemExit("사용 가능한 Groq 모델을 찾지 못했습니다. console.groq.com/docs/models 확인 필요")


def load_db() -> list[dict]:
    if DB_PATH.exists():
        with open(DB_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def save_db(db: list[dict]) -> None:
    with open(DB_PATH, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)


def used_summary(db: list[dict], limit: int = 80) -> str:
    """최근 사용한 국가+주제 조합을 프롬프트용 텍스트로 요약"""
    recent = db[-limit:]
    if not recent:
        return "(아직 없음)"
    return "\n".join(f"- {item['country']}: {item['topic']}" for item in recent)


def build_prompt(count: int, used: str) -> str:
    return f"""세계 각국의 흥미로운 문화/관습/법 상식을 유튜브 쇼츠 소재로 {count}개 생성해줘.

조건:
- 같은 나라가 다시 나와도 되지만, 이미 쓴 주제와 겹치면 안 됨 (같은 나라라면 완전히 다른 관습/법/음식/언어 소재로)
- 한 번에 생성하는 소재끼리는 되도록 서로 다른 나라로 다양하게
- 시청자가 "어?" 하고 멈출 만큼 의외성이 있을 것
- 사람과 상황이 눈에 그려지는 이야기형 소재를 우선할 것 (예: 이웃이 집을 통째로 옮겨주는 풍습, 죽은 사람과 결혼하는 제도, 아이들이 말을 타는 일상, 신생아에게 박스를 주는 정책처럼 장면이 떠오르는 것)
- 단순한 규정/제도/금지 조항 설명(예: 차량 요일 제한, 흡연·화폐·동물 거리 규정, 요일 이름 유래)은 피하고, 꼭 쓴다면 사람이 곤란해지거나 놀라는 구체적 장면으로 풀 것
- 이미 너무 유명한 소재(토마토 축제, 산페르민 소몰이 등)는 피할 것
- 종교/전쟁/정치적으로 민감한 내용은 제외 (관습, 법, 음식, 언어, 생활문화 위주)
- 사실 기반이어야 하며, 확인 가능한 정보일 것 (불확실하면 넣지 말 것)

아래는 최근에 이미 사용한 국가+주제 목록이야. 이것과 겹치지 않게 생성해줘:
{used}

각 소재는 다음 JSON 형식의 배열로만 응답해. 다른 설명이나 마크다운 없이 순수 JSON 배열만:
[
  {{
    "country": "나라 이름",
    "topic": "주제 한 줄 요약 (예: 결혼 풍습, 팁 문화 등)",
    "hook": "영상 시작 3초용 후킹 문장 (예: '이 나라에서는 시계를 선물하면 절교당합니다')",
    "body": "본문 설명 (2~3문장, 왜 그런지 배경 포함)",
    "twist": "반전이나 추가로 놀랄 만한 정보 1문장",
    "verify_note": "사실 확인 시 참고할 키워드 (사람이 검수할 때 검색할 용도)"
  }}
]"""


BATCH_SIZE = 4  # Groq TPM 8,000 제한을 고려해 요청 크기를 줄임
MAX_COMPLETION_TOKENS = 6000


def extract_json_array(text: str) -> list[dict]:
    """모델이 설명/추론 텍스트를 앞뒤로 붙여도 JSON 배열 부분만 뽑아낸다"""
    text = text.strip()
    start = text.find("[")
    end = text.rfind("]")
    if start == -1 or end == -1 or start > end:
        raise ValueError("JSON 배열을 찾지 못함 (응답이 중간에 끊겼을 수 있음)")
    return json.loads(text[start : end + 1])


def generate_batch(client: Groq, model: str, count: int, used: str) -> list[dict]:
    """작은 배치로 소재를 생성한다."""
    completion = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": build_prompt(count, used)}],
        max_completion_tokens=MAX_COMPLETION_TOKENS,
        temperature=0.8,
    )

    text = completion.choices[0].message.content or ""
    finish_reason = completion.choices[0].finish_reason

    if not text.strip():
        raise ValueError(f"응답이 비어있음 (finish_reason={finish_reason})")

    return extract_json_array(text)


def generate_facts(
    client: Groq,
    model: str,
    count: int,
    used: str,
    db: list[dict],
) -> list[dict]:
    """배치 단위로 생성하고 성공한 배치는 즉시 DB에 저장한다."""
    all_facts: list[dict] = []
    remaining = count
    used_running = used

    while remaining > 0:
        batch_count = min(BATCH_SIZE, remaining)

        try:
            batch = generate_batch(client, model, batch_count, used_running)

        except (ValueError, json.JSONDecodeError) as e:
            print(f"  배치 실패, 1회 재시도: {e}")

            try:
                batch = generate_batch(client, model, batch_count, used_running)

            except (ValueError, json.JSONDecodeError) as e2:
                print(f"  재시도도 실패, 이번 배치 건너뜀: {e2}")
                remaining -= batch_count
                continue

        if not batch:
            print("  빈 배치 응답, 건너뜀")
            remaining -= batch_count
            continue

        # 실제 반환 개수만큼 진행
        batch = batch[:batch_count]
        seen = {(str(f.get("country", "")).strip().lower(), str(f.get("topic", "")).strip().lower()) for f in db}
        uniq = []
        for f in batch:
            k = (str(f.get("country", "")).strip().lower(), str(f.get("topic", "")).strip().lower())
            if k in seen:
                print(f"  중복 제외: {f.get('country')} / {f.get('topic')}")
                continue
            seen.add(k)
            uniq.append(f)
        batch = uniq
        if not batch:
            remaining -= batch_count
            continue
        all_facts.extend(batch)

        now = datetime.now(timezone.utc).isoformat()
        for fact in batch:
            fact["created_at"] = now
            fact["status"] = "unverified"

        # ★ 배치 성공 즉시 DB에 저장
        db.extend(batch)
        save_db(db)

        used_running += "\n" + "\n".join(
            f"- {f['country']}: {f['topic']}" for f in batch
        )

        remaining -= len(batch)
        print(f"  진행: {len(all_facts)}/{count} (DB 즉시 저장 완료)")

        # 모델이 요청보다 적게 반환한 경우 무한 루프 방지
        if len(batch) < batch_count:
            print(
                f"  주의: {batch_count}개 요청했지만 "
                f"{len(batch)}개만 반환되었습니다."
            )

    return all_facts


def main():
    parser = argparse.ArgumentParser(description="세계 문화 상식 소재 자동 생성")
    parser.add_argument("--count", type=int, default=20, help="생성할 소재 개수 (기본 20)")
    args = parser.parse_args()

    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise SystemExit("환경변수 GROQ_API_KEY를 설정해주세요. (무료 키: https://console.groq.com/keys)")

    client = Groq(api_key=api_key)
    model = pick_model(client)
    print(f"사용 모델: {model}")
    db = load_db()

    print(f"기존 DB: {len(db)}개 소재 보유")
    print(f"신규 생성 요청: {args.count}개")

    new_facts = generate_facts(
        client,
        model,
        args.count,
        used_summary(db),
        db,
    )

    print(f"완료: {len(new_facts)}개 추가, 총 {len(db)}개 소재 보유")
    print(f"저장 위치: {DB_PATH.resolve()}")
    print("\n다음 단계: status가 'unverified'인 항목을 사람이 훑어보고 "
          "verify_note로 팩트체크 후 'verified'로 변경하세요.")


if __name__ == "__main__":
    main()
