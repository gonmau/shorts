"""
세계 문화 상식 쇼츠 - 소재 자동 생성 스크립트

기능:
1. 위키백과 발췌문(나라 x 분야)을 근거로 LLM(Groq)이 문화 상식 소재를 만든다. 접속 실패 시 모델 기억 방식으로 대체
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
import time
import os
import argparse
from datetime import datetime, timezone
from pathlib import Path

import re
import requests
from groq import Groq

import wiki_source

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


def build_prompt(count: int, used: str):
    import style_profile as _sp
    return _sp.apply(_build_prompt_base(count, used), "topic")


def _build_prompt_base(count: int, used: str) -> str:
    return f"""세계 각국의 흥미로운 문화/관습/법 상식을 유튜브 쇼츠 소재로 {count}개 생성해줘.

조건:
- 모든 필드는 한국어로 쓰고, 고유명사는 한국어 표기 뒤에 괄호로 원어를 적을 것 (영어 문장 금지)
- 같은 나라가 다시 나와도 되지만, 이미 쓴 주제와 겹치면 안 됨 (같은 나라라면 완전히 다른 관습/법/음식/언어 소재로)
- 한 번에 생성하는 소재끼리는 되도록 서로 다른 나라로 다양하게
- 시청자가 "어?" 하고 멈출 만큼 의외성이 있을 것
- 훅(hook)은 첫 3초에 승부가 납니다: 금액·숫자·벌금·금지·반전 중 하나가 들어간 구체적 장면으로 쓰고, "~에서는 ~합니다!" 식의 밋밋한 설명문형은 피할 것 (좋은 예: "하루 차값보다 더 번다?", "도시 전체가 장미 따기 위해 쉬는 날이 있다면?", "조용히 안 타면 30분 정차")
- 사람과 상황이 눈에 그려지는 이야기형 소재를 우선할 것 (예: 이웃이 집을 통째로 옮겨주는 풍습, 죽은 사람과 결혼하는 제도, 아이들이 말을 타는 일상, 신생아에게 박스를 주는 정책처럼 장면이 떠오르는 것)
- 단순한 규정/제도/금지 조항 설명(예: 차량 요일 제한, 흡연·화폐·동물 거리 규정, 요일 이름 유래)은 피하고, 꼭 쓴다면 사람이 곤란해지거나 놀라는 구체적 장면으로 풀 것
- 이미 너무 유명한 소재(토마토 축제, 산페르민 소몰이 등)는 피할 것
- 종교/전쟁/정치적으로 민감한 내용은 제외 (관습, 법, 음식, 언어, 생활문화 위주)
- 사실 기반이어야 하며, 확인 가능한 정보일 것 (불확실하면 넣지 말 것)
- 정확성이 최우선: 놀라움이 과장이 되면 안 됨. 적용 범위(어디서/누가/언제)를 분명히 쓸 것
  * "모든", "누구나", "항상", "절대", "불법", "금지", "유일한 나라", "세계 최초/최대" 같은 단정 표현은 확실한 근거가 있을 때만
  * 일부 지역·일부 업체·일부 사람의 관습을 그 나라 전체의 규칙처럼 쓰지 말 것 ("일부 지역에서는", "많은 경우" 등으로 한정)
  * 통계·금액·연도는 정확히 확신할 때만, 아니면 정성적으로 표현
  * 특정 민족·국민에 대한 일반화나 비하, 자극적 낚시 표현 금지

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
    "caveat": "이 사실의 한계 한 문장 (어디서/누구에게/언제 적용되는지, 모든 경우는 아닌 점)",
    "confidence": "정확하고 문서로 잘 확인되는 확신이 있을 때만 high, 아니면 medium 또는 low",
    "verify_note": "사실 확인 시 참고할 키워드 (사람이 검수할 때 검색할 용도)"
  }}
]"""


# ---------- 품질 필터: 한국어 확인 / 같은 나라 안에서 주제 중복 방지 ----------
def _hangul_ratio(text: str) -> float:
    letters = re.findall(r"[A-Za-z가-힣]", str(text or ""))
    if not letters:
        return 0.0
    return sum(1 for c in letters if "가" <= c <= "힣") / len(letters)


def is_korean(f: dict) -> bool:
    """한국어 채널이므로 주제/훅/본문이 한국어여야 한다 (영어로 나온 소재는 버린다)."""
    if not re.search(r"[가-힣]", str(f.get("topic", ""))):
        return False
    return _hangul_ratio(f"{f.get('topic', '')} {f.get('hook', '')} {f.get('body', '')}") >= 0.5


def _grams(text: str) -> set:
    t = re.sub(r"[^0-9a-z가-힣]", "", str(text or "").lower())
    return {t[i:i + 2] for i in range(len(t) - 1)} if len(t) > 1 else {t}


def _sim(a: str, b: str) -> float:
    ga, gb = _grams(a), _grams(b)
    return len(ga & gb) / len(ga | gb) if ga and gb else 0.0


def is_duplicate(f: dict, pool: list) -> bool:
    """같은 위키 문서이거나, 같은 나라에서 주제/훅이 비슷하면 중복. (같은 나라라도 주제가 다르면 허용)"""
    wt = wiki_source._norm(f.get("wiki_title", ""))
    c = str(f.get("country", "")).strip().lower()
    for o in pool:
        if wt and wt == wiki_source._norm(o.get("wiki_title", "")):
            return True
        if str(o.get("country", "")).strip().lower() != c:
            continue
        if max(_sim(f.get("topic"), o.get("topic")), _sim(f.get("hook"), o.get("hook"))) >= 0.5:
            return True
    return False


def filter_new(batch: list, db: list) -> list:
    kept, pool = [], list(db)
    for f in batch:
        if not is_korean(f):
            print(f"  한국어가 아니어서 제외: {str(f.get('country'))} / {str(f.get('topic'))[:40]}")
            continue
        if is_duplicate(f, pool):
            print(f"  중복(같은 나라+비슷한 주제) 제외: {f.get('country')} / {f.get('topic')}")
            continue
        pool.append(f)
        kept.append(f)
    return kept


# ---------- 위키백과 근거 기반 생성 ----------
def build_wiki_prompt(cands: list) -> str:
    blocks = "\n\n".join(
        f"[{i}] 나라: {c['country']} / 분야: {c['theme']} / 위키 문서: {c['title']}\n발췌: {c['extract'][:700]}"
        for i, c in enumerate(cands, start=1)
    )
    return f"""아래는 위키백과 발췌문 {len(cands)}개야. 각 발췌문에서 유튜브 쇼츠 소재를 최대 1개씩 만들어줘.

규칙:
- 반드시 발췌문에 적힌 사실만 사용. 발췌문에 없는 내용, 숫자, 연도를 추가하지 말 것
- 모든 필드는 한국어로 쓰고, 고유명사는 한국어 표기 뒤에 괄호로 원어를 적을 것 (영어 문장 금지)
- 시청자가 "어?" 하고 멈출 의외의 장면/상황/규칙 하나를 골라 사람이 곤란하거나 놀라는 장면으로 풀 것
- 개요 설명, 단순 정의, 지루하거나 너무 일반적인 내용, 종교/전쟁/정치적으로 민감한 내용이면 그 번호는 건너뛸 것
- "모든", "항상", "세계 최초" 같은 단정은 발췌문이 분명히 말할 때만. 일부 지역/일부 사람의 관습이면 범위를 한정할 것
- 한 소재는 한 가지 사실에 집중할 것
- 훅(hook)은 첫 3초에 승부가 납니다: 금액·숫자·벌금·금지·반전 중 하나가 들어간 구체적 장면으로 쓰고, "~에서는 ~합니다!" 식의 밋밋한 설명문형은 피할 것 (좋은 예: "하루 차값보다 더 번다?", "도시 전체가 장미 따기 위해 쉬는 날이 있다면?", "조용히 안 타면 30분 정차")

{blocks}

JSON 배열로만 응답 (설명/마크다운 금지). src는 위 번호:
[
  {{"src": 1, "topic": "주제 한 줄 요약", "hook": "영상 시작 3초용 후킹 문장", "body": "본문 2~3문장 (배경 포함)",
    "twist": "반전이나 추가 정보 1문장", "caveat": "이 사실의 한계 한 문장 (어디서/누구에게/언제)"}}
]"""


def generate_wiki_batch(client: Groq, model: str, cands: list) -> list:
    last_err = None
    completion = None
    for max_tok in (3000, 2000):
        try:
            completion = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": build_wiki_prompt(cands)}],
                max_completion_tokens=max_tok,
                temperature=0.6,
            )
            break
        except Exception as e:
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
    if not text.strip():
        raise ValueError("응답이 비어있음")
    out = []
    for f in extract_json_array(text):
        try:
            c = cands[int(f.get("src")) - 1]
        except (TypeError, ValueError, IndexError):
            continue
        f.pop("src", None)
        f.update({
            "country": c["country"], "theme": c["theme"], "wiki_title": c["title"], "source_url": c["url"],
            "verify_note": c["title"],            # 영어 위키 제목: 사람이 검수/이미지 검색할 때 쓰는 키워드
            "confidence": "source",               # 위키백과 발췌문 기반 (LLM 기억 기반 아님)
        })
        out.append(f)
    return out


def generate_wiki_facts(client: Groq, model: str, count: int, db: list) -> list:
    session = requests.Session()
    cands = wiki_source.gather(session, db, count)
    print(f"위키백과 후보 {len(cands)}개 수집")
    all_new: list = []
    BATCH = 3
    for i in range(0, len(cands), BATCH):
        if len(all_new) >= count:
            break
        chunk = cands[i:i + BATCH]
        try:
            batch = generate_wiki_batch(client, model, chunk)
        except (ValueError, json.JSONDecodeError) as e:
            print(f"  배치 실패, 건너뜀: {e}")
            continue
        batch = filter_new(batch, db)[: count - len(all_new)]
        if not batch:
            continue
        now = datetime.now(timezone.utc).isoformat()
        for fact in batch:
            fact["created_at"] = now
            fact["status"] = "unverified"
        db.extend(batch)
        save_db(db)
        all_new.extend(batch)
        print(f"  진행: {len(all_new)}/{count} (DB 즉시 저장 완료)")
    return all_new


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
        batch = filter_new(batch, db)
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
    parser.add_argument("--source", choices=["wiki", "llm"], default="wiki",
                        help="wiki=위키백과 발췌문 기반(기본), llm=모델 기억 기반(위키 접속 실패 시 자동 대체)")
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

    new_facts = []
    if args.source == "wiki":
        try:
            new_facts = generate_wiki_facts(client, model, args.count, db)
        except Exception as e:
            print(f"위키백과 방식 실패 ({type(e).__name__}: {str(e)[:120]}) -> 모델 기억 방식으로 대체")
        if len(new_facts) < args.count:
            print(f"위키 방식으로 {len(new_facts)}개 생성, 부족분은 모델 기억 방식으로 보충합니다")
    left = args.count - len(new_facts)
    if left > 0:
        new_facts += generate_facts(client, model, left, used_summary(db), db)

    print(f"완료: {len(new_facts)}개 추가, 총 {len(db)}개 소재 보유")
    print(f"저장 위치: {DB_PATH.resolve()}")
    print("\n다음 단계: status가 'unverified'인 항목을 사람이 훑어보고 "
          "verify_note로 팩트체크 후 'verified'로 변경하세요.")


if __name__ == "__main__":
    main()
