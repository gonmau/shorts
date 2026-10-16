"""
KoreaAtoZ (English) - 소재 자동 생성 스크립트

외국인 시청자 시선에서 흥미로운 한국 문화/일상/음식/예절/언어/현대 생활 소재를
Groq(무료 API)로 배치 생성해 facts_db.json에 누적 저장합니다.
각 소재: 훅 + 본문 + 반전 + 검증 메모(verify_note, 사람이 사실 확인할 때 검색할 키워드).

    export GROQ_API_KEY="발급받은키"
    python generate_topics.py --count 12

이미 쓴 소재(label+topic)는 프롬프트에 넣어 겹치지 않게 하고, 정확히 같은 소재는 코드에서 제외합니다.
"""

import json
import time
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
    return "\n".join(f"- {item.get('label', '')}: {item['topic']}" for item in recent)


def build_prompt(count: int, used: str) -> str:
    return f"""Generate {count} fascinating topics about Korea (South Korea) for English YouTube Shorts aimed at international viewers who have never been to Korea.

Requirements:
- Cover everyday life, food and table manners, social etiquette, language quirks, holidays and traditions, modern life and technology, school and work culture, travel tips, and surprising numbers about Korea. Vary the categories within one request.
- Prefer stories with people and concrete scenes over bare rules or definitions. A viewer should be able to picture it (for example a person doing something unexpected), not just read a regulation.
- Each topic must make an outsider think "wait, really?". Surprise matters more than trivia.
- Only well-documented, widely verifiable facts. If you are not sure it is true, leave it out. Do not repeat myths or stereotypes (for example "fan death", or claims about dog meat being common). Prefer present-day Korea over old history.
- Exclude politics, North Korea, territorial or historical disputes, religion debates, and private lives of celebrities. K-pop and K-drama are fine only as culture and industry facts, never gossip, and never quote lyrics.
- ACCURACY FIRST. Surprising must never mean exaggerated. Use calm, qualified wording and state the scope (who, where, when).
  * Do not use absolutes: "everyone", "all Koreans", "always", "never", "illegal", "banned", "the only country", "the first/biggest/most" unless it is firmly documented.
  * Say "many", "often", "in some places", "at many cafes" when a practice is common but not universal. Never turn a trend, a single company or a single city's practice into a nationwide rule.
  * No statistics, prices or dates unless you are highly confident of the exact figure; otherwise describe it qualitatively ("relatively cheap", "a few minutes").
  * No generalizations about Koreans as a people, no shock-bait, no insulting comparisons with other countries.
- Avoid the most overused topics (kimchi basics, "Korean age" alone, soju shots). Look for fresh angles.

Here are topics already used. Do not overlap with them:
{used}

Respond with a pure JSON array only, no markdown and no other text:
[
  {{
    "label": "Short title of the subject, 2-5 words in English (example: Korean Delivery Culture)",
    "topic": "One-line summary in English (example: Food delivered to a park bench in minutes)",
    "hook": "Opening line for the first 3 seconds, a question or surprising claim in English (example: In Korea, you can order fried chicken to a bench by the river.)",
    "body": "Explanation in English, 3 to 4 sentences including why it is like this",
    "twist": "One English sentence with a surprising extra detail",
    "caveat": "One English sentence on the limits of this fact (where/when/for whom it applies, what is not universal)",
    "confidence": "high only if you are sure this is accurate and well documented, otherwise medium or low",
    "verify_note": "Keywords a human can search to fact-check this"
  }}
]"""


BATCH_SIZE = 4  # Groq TPM 8,000 제한을 고려해 요청 크기를 줄임
MAX_COMPLETION_TOKENS = 5000


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
    # 요청 토큰(프롬프트 + 최대 출력)이 Groq 분당 한도(8,000)를 넘으면 413이 나므로
    # 이미 쓴 소재 목록을 최근 것만 쓰고, 그래도 크면 더 줄여서 한 번 더 시도한다.
    completion = None
    last_err = None
    for lines, max_tok in ((40, MAX_COMPLETION_TOKENS), (20, 3500)):
        ctx = "\n".join(used.splitlines()[-lines:])
        try:
            completion = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": build_prompt(count, ctx)}],
                max_completion_tokens=max_tok,
                temperature=0.8,
            )
            break
        except Exception as e:  # 한도 초과/일시 오류는 배치 실패로 처리해 전체 실행이 죽지 않게 한다
            last_err = e
            msg = str(e)
            if "413" in msg or "rate_limit" in msg or "429" in msg:
                print(f"  [Groq 한도] 요청을 줄여 다시 시도합니다: {msg[:120]}")
                time.sleep(20)
                continue
            raise ValueError(f"Groq 호출 실패: {msg[:200]}")
    if completion is None:
        raise ValueError(f"Groq 호출 실패: {str(last_err)[:200]}")

    text = completion.choices[0].message.content or ""
    finish_reason = completion.choices[0].finish_reason

    if not text.strip():
        raise ValueError(f"응답이 비어있음 (finish_reason={finish_reason})")

    items = extract_json_array(text)
    kept = [f for f in items if str(f.get("confidence", "")).strip().lower() == "high"]
    if len(kept) < len(items):
        print(f"  확신도 낮은 소재 {len(items) - len(kept)}개 제외 (과장/오류 방지)")
    return kept


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
        seen = {(str(f.get("label", "")).strip().lower(), str(f.get("topic", "")).strip().lower()) for f in db}
        uniq = []
        for f in batch:
            k = (str(f.get("label", "")).strip().lower(), str(f.get("topic", "")).strip().lower())
            if k in seen:
                print(f"  중복 제외: {f.get('label')} / {f.get('topic')}")
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
            fact["country"] = str(fact.get("label", "")).strip()  # 폴더/파일명/썸네일 등 기존 코드와의 호환용
            fact["created_at"] = now
            fact["status"] = "unverified"

        # ★ 배치 성공 즉시 DB에 저장
        db.extend(batch)
        save_db(db)

        used_running += "\n" + "\n".join(
            f"- {f.get('label', '')}: {f['topic']}" for f in batch
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
    parser = argparse.ArgumentParser(description="Korea Culture Shorts 소재 자동 생성")
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
