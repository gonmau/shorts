import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

from groq import Groq, RateLimitError

from common import split_sentences, strip_marks, pending_render


DB_FILE = Path("facts_db.json")

# 우선순위가 높은 모델부터 사용합니다.
PREFERRED_MODELS = [
    "llama-3.1-8b-instant",
    "llama-3.3-70b-versatile",
    "llama-3.1-70b-versatile",
    "gemma2-9b-it",
    "openai/gpt-oss-120b",
]

MAX_COMPLETION_TOKENS = 1200
REASONING_MODEL_TOKENS = 4000  # gpt-oss 계열은 추론 토큰이 포함되므로 넉넉하게


def completion_kwargs(model, max_tokens):
    """
    openai/gpt-oss-* 는 추론(reasoning) 모델이라 max_completion_tokens 안에
    '생각' 토큰이 함께 계산된다. 1200/100 토큰으로는 생각만 하다 끝나서
    content가 빈 문자열로 오므로, 추론 강도를 낮추고 토큰 한도를 늘린다.
    """
    if "gpt-oss" in model:
        return {
            "max_completion_tokens": max(max_tokens, REASONING_MODEL_TOKENS),
            "extra_body": {"reasoning_effort": "low"},
        }
    return {"max_completion_tokens": max_tokens}
DEFAULT_LIMIT = 15
DEFAULT_DELAY = 1.5
DEFAULT_RETRIES = 5

# 30~50초 TTS용으로 너무 짧은 결과는 성공으로 인정하지 않습니다.
MIN_CHARS = 280
TARGET_MIN_CHARS = 350
TARGET_MAX_CHARS = 500


# ============================================================
# DB
# ============================================================

def load_db():
    if not DB_FILE.exists():
        raise FileNotFoundError(
            f"facts_db.json 파일을 찾을 수 없습니다:\n"
            f"{DB_FILE.resolve()}"
        )

    with DB_FILE.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_db(db):
    tmp_file = DB_FILE.with_suffix(".tmp")

    with tmp_file.open("w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)

    tmp_file.replace(DB_FILE)


# ============================================================
# 모델
# ============================================================

def get_available_models(client):
    response = client.models.list()

    return sorted({
        model.id
        for model in response.data
        if getattr(model, "id", None)
    })


def pick_models(client, requested_model=None):
    available = get_available_models(client)

    if requested_model:
        if available and requested_model not in available:
            print(f"[오류] 지정한 모델을 사용할 수 없습니다: {requested_model}")
            print("\n사용 가능한 모델:")
            for model in available:
                print(f"  - {model}")
            sys.exit(1)

        return [requested_model]

    models = [m for m in PREFERRED_MODELS if m in available]

    if not models:
        print("[오류] 사용할 수 있는 지정 모델을 찾지 못했습니다.")
        print("\n현재 계정에서 확인된 모델:")
        for model in available:
            print(f"  - {model}")
        sys.exit(1)

    return models


# ============================================================
# 불량 대본 판정
# ============================================================

BAD_PATTERNS = [
    "제공해 주신 문화 상식 정보가 비어 있습니다",
    "제공해 주신 문화 상식 정보가 부족해",
    "제공해 주신 정보가 부족합니다",
    "제공해 주신 문화 상식 정보가 비어 있어",
    "제공해주신 내용에 국가와 주제만 있고",
    "제공해주신 정보가 부족합니다",
    "죄송합니다, 제공해 주신",
    "죄송합니다, 해당 영상에 사용할",
    "정확한 대본을 작성하기 어렵습니다",
    "정확한 스크립트를 작성하기 어렵습니다",
    "스크립트를 작성할 수 없습니다",
    "필요한 정보를 알려주시면",
    "주제와 내용, 출처를 알려주시면",
    "해당 정보를 채워 주시면",
]


def normalize_text(text):
    return re.sub(r"\s+", " ", text or "").strip()


def is_bad_narration(text):
    if not text:
        return True

    normalized = normalize_text(text)

    for pattern in BAD_PATTERNS:
        if pattern in normalized:
            return True

    # 기존에 생성된 너무 짧은 대본도 재생성 대상
    if len(normalized) < MIN_CHARS:
        return True

    return False


# ============================================================
# 프롬프트
# ============================================================

def build_prompt(fact):
    country = fact.get("country", "")
    topic = fact.get("topic", "")
    hook = fact.get("hook", "")
    body = fact.get("body", "")
    twist = fact.get("twist", "")
    verify_note = fact.get("verify_note", "")
    caveat = fact.get("caveat", "")

    return f"""
당신은 한국어 유튜브 쇼츠 전문 대본 작가입니다.

아래의 '검증된 문화 상식 자료'만 사용하여
30~50초 분량의 쇼츠 내레이션을 작성하세요.

[국가]
{country}

[주제]
{topic}

[훅]
{hook}

[핵심 내용]
{body}

[반전/흥미로운 포인트]
{twist}

[이 사실의 한계]
{caveat}

[검증 메모]
{verify_note}

작성 규칙:

1. 반드시 한국어로 작성합니다.
2. 실제 유튜브 쇼츠에서 사람이 말하는 것처럼 자연스럽게 작성합니다.
3. 존댓말을 사용합니다.
4. 첫 문장은 [훅]을 살려 강하게 시작합니다.
5. [핵심 내용]에 있는 사실을 설명합니다.
6. [반전/흥미로운 포인트]를 자연스럽게 포함합니다.
7. 제공된 자료에 없는 새로운 사실이나 숫자를 만들지 않습니다.
8. 법률, 벌금, 날짜, 수치 등은 제공된 자료에 있는 범위에서만 말합니다.
9. 자료의 내용을 단순히 복사하지 말고 쇼츠 내레이션처럼 자연스럽게 연결합니다.
10. 짧은 문장을 사용해 TTS로 읽기 좋게 만듭니다.
11. 전체 분량은 반드시 350~500자 사이를 목표로 합니다.
12. 최소 280자보다 짧게 작성하지 마세요.
13. 자료가 짧더라도 제공된 사실의 의미와 맥락을 자연스럽게 풀어 설명하여 분량을 확보하세요.
14. 없는 사실을 추가해서 분량을 채우지 마세요.
15. 구독, 좋아요, 알림 설정, 댓글을 요청하는 말은 절대 넣지 않습니다. 마지막은 여운이 남는 한 문장이나 반전으로 끝내고, 가능하면 첫 문장의 궁금증과 이어지게 해서 다시 보고 싶게 만듭니다.
16. 제목, 번호, "내레이션:", "대본:" 같은 라벨은 출력하지 않습니다.
17. 대본만 출력합니다.
18. 정확성이 우선입니다. 과장하지 말고 차분하게 사실만 전달합니다. "모두", "항상", "절대", "불법", "유일", "세계 최대/최초" 같은 단정 표현을 쓰지 않고, "많은", "일부", "대체로" 등으로 범위를 한정하며 지역·대상을 밝힙니다. 일부의 관습을 나라 전체의 규칙처럼 말하지 말고, [이 사실의 한계]를 존중합니다.

중요:
자료가 이미 제공되어 있으므로 절대로
"정보가 부족합니다"
"주제와 내용을 알려주세요"
"정확한 대본을 작성하기 어렵습니다"
같은 답변을 하지 마세요.
""".strip()


# ============================================================
# 응답 정리 및 품질 검사
# ============================================================

def clean_narration(text):
    if not text:
        return ""

    text = text.strip()

    text = re.sub(
        r"^```(?:text|korean|ko)?\s*",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"\s*```$", "", text)

    text = re.sub(
        r"^(내레이션|나레이션|대본)\s*[:：]\s*",
        "",
        text,
        flags=re.IGNORECASE,
    )

    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()


def validate_narration(text):
    """
    True = 정상 대본
    False = 재생성 필요
    """
    text = clean_narration(text)

    if not text:
        return False, "빈 대본"

    if is_bad_narration(text):
        normalized = normalize_text(text)

        if len(normalized) < MIN_CHARS:
            return False, f"너무 짧음 ({len(normalized)}자)"

        return False, "정보 부족/거절 응답"

    length = len(normalize_text(text))

    # 너무 긴 경우도 영상 길이가 늘어날 수 있으므로 재생성
    if length > TARGET_MAX_CHARS:
        return False, f"너무 김 ({length}자)"

    return True, f"{length}자"


# ============================================================
# 화면 상단 제목 2줄 (title_line1 / title_line2)
# ============================================================

TITLE_MAX_CHARS = 16  # 프롬프트는 12자 이내를 요청하되, 16자까지 허용


def build_title_prompt(fact, narration):
    return f"""
당신은 한국어 유튜브 쇼츠 제목 작가입니다.
아래 자료를 바탕으로 화면 상단에 크게 들어갈 2줄 제목을 만드세요.

[국가]
{fact.get("country", "")}

[주제]
{fact.get("topic", "")}

[훅]
{fact.get("hook", "")}

[대본]
{narration}

규칙:
1. 정확히 2줄만 출력합니다.
2. 1줄은 상황이나 주제를 제시하고, 2줄은 궁금증을 만드는 결과나 반전을 씁니다.
3. 각 줄은 공백 포함 12자 이내로 짧게 씁니다.
4. 자료에 없는 사실이나 숫자를 만들지 않습니다.
5. 낚시성 과장 없이 자료 내용과 일치해야 합니다. "모두/항상/절대/불법/유일" 같은 단정은 대본이 정확히 그렇게 말할 때만 씁니다.
6. 제목은 반드시 한글로만 씁니다. 영어 알파벳은 쓰지 않습니다.
   국가명과 고유명사도 한국어 표기로 씁니다. (예: Uruguay → 우루과이)
   [주제]나 [훅]이 영어여도 자연스러운 한국어로 옮겨 씁니다.
7. 이모지, 따옴표, 마침표, 번호, 라벨 없이 두 줄의 텍스트만 출력합니다.

출력 형식:
(1줄)
(2줄)
""".strip()


def is_korean_title(line):
    """한글이 있고 영문 알파벳이 없는 제목 줄인지 (숫자는 허용)."""
    return bool(re.search(r"[가-힣]", line)) and not re.search(r"[A-Za-z]", line)


def parse_title(text):
    """모델 응답에서 2줄 제목을 뽑는다. 형식이 맞지 않으면 None."""
    if not text:
        return None

    lines = []
    for raw in text.strip().splitlines():
        line = re.sub(r"^\s*(\d+[.)]|[-*•]|\(?[12]줄\)?\s*[:：]?)\s*", "", raw)
        line = line.strip().strip("\"'“”‘’`").rstrip(".。").strip()
        if line:
            lines.append(line)

    if len(lines) != 2:
        return None
    if any(len(x) > TITLE_MAX_CHARS for x in lines):
        return None
    if not all(is_korean_title(x) for x in lines):
        return None  # 영어가 섞이면 재시도
    return lines[0], lines[1]


def generate_title(client, models, fact, narration, retries=3):
    """제목 2줄 생성. 실패하면 None (build_video가 topic을 자동 분할해서 대체)."""
    prompt = build_title_prompt(fact, narration)

    for model in models:
        for attempt in range(1, retries + 1):
            try:
                response = client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": "당신은 사실에 충실한 한국어 쇼츠 제목 작가입니다."},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.7,
                    **completion_kwargs(model, 100),
                )
                if not response.choices:
                    continue
                parsed = parse_title(response.choices[0].message.content)
                if parsed:
                    return parsed
            except RateLimitError as e:
                if attempt >= retries:
                    break
                time.sleep(get_retry_seconds(e, attempt))
            except Exception:
                if attempt >= retries:
                    break
                time.sleep(min(2.0 * attempt, 10.0))

    return None



# ============================================================
# 핵심 문구(highlights) / 이미지 검색어(image_queries)
# ============================================================

HL_MAX_CHARS = 16  # 프롬프트는 12자 이내를 요청하되 16자까지 허용


def extract_json(text):
    """응답에서 JSON(객체 또는 배열)을 뽑는다. 실패하면 None."""
    if not text:
        return None
    text = text.strip()
    for open_c, close_c in (("{", "}"), ("[", "]")):
        a, b = text.find(open_c), text.rfind(close_c)
        if a != -1 and b > a:
            try:
                return json.loads(text[a:b + 1])
            except json.JSONDecodeError:
                continue
    return None


def ask_models(client, models, system, prompt, tokens, retries, parse):
    """모델을 순서대로 시도해 parse(text)가 None이 아닌 첫 결과를 돌려준다."""
    for model in models:
        for attempt in range(1, retries + 1):
            try:
                response = client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.7,
                    **completion_kwargs(model, tokens),
                )
                if not response.choices:
                    continue
                result = parse(response.choices[0].message.content or "")
                if result:
                    return result
            except RateLimitError as e:
                if attempt >= retries:
                    break
                time.sleep(get_retry_seconds(e, attempt))
            except Exception:
                if attempt >= retries:
                    break
                time.sleep(min(2.0 * attempt, 10.0))
    return None


def build_highlight_prompt(fact, narration):
    sents = split_sentences(narration)
    numbered = "\n".join(f"{i}. {x}" for i, x in enumerate(sents, 1))
    return f"""
당신은 한국어 유튜브 쇼츠의 화면 자막 디자이너입니다.
아래 대본을 읽고, 영상 화면에 크게 띄울 '핵심 문구'를 뽑으세요.

[국가] {fact.get("country", "")}
[주제] {fact.get("topic", "")}

[대본 - 문장 번호]
{numbered}

규칙:
1. 핵심 문구는 3~6개입니다. 대본 흐름 순서대로, 문장 번호(s)는 오름차순이며 같은 번호를 두 번 쓰지 않습니다.
2. 각 문구는 공백 포함 12자 이내로 짧게, 한글로만 씁니다. (영어 알파벳 금지, 숫자는 허용)
3. 대본 문장을 그대로 베끼지 말고, 시청자 눈에 박히는 단어나 짧은 구로 압축합니다.
4. 문구마다 가장 중요한 단어 하나를 *별표*로 감쌉니다. 예: 길에서 *사자* 키우면?
5. 대본에 없는 사실이나 숫자를 만들지 않습니다.
6. 아래 JSON만 출력합니다. 다른 설명은 쓰지 않습니다.

{{"highlights": [{{"s": 1, "text": "문구"}}, {{"s": 3, "text": "문구"}}]}}
""".strip()


def parse_highlights(text, n_sent):
    obj = extract_json(text)
    items = obj.get("highlights") if isinstance(obj, dict) else obj
    if not isinstance(items, list):
        return None

    found = {}
    for it in items:
        try:
            num = int(it.get("s"))
            raw = str(it.get("text", "")).strip()
        except (AttributeError, TypeError, ValueError):
            continue
        plain = strip_marks(raw)
        if not (1 <= num <= n_sent) or num in found:
            continue
        if not plain or len(plain) > HL_MAX_CHARS or not is_korean_title(plain):
            continue
        if raw.count("*") != 2:
            raw = raw.replace("*", "")  # 강조 표시가 어긋나면 표시만 제거
        found[num] = raw

    if len(found) < 3:
        return None
    return [{"s": n, "text": found[n]} for n in sorted(found)][:7]


def generate_highlights(client, models, fact, narration, retries=3):
    n = len(split_sentences(narration))
    if n < 3:
        return None
    return ask_models(
        client, models,
        "당신은 짧고 강렬한 한국어 자막을 만드는 편집자입니다.",
        build_highlight_prompt(fact, narration), 600, retries,
        lambda t: parse_highlights(t, n),
    )


def build_query_prompt(fact, narration):
    return f"""
You pick stock photos for a short vertical video. Read the Korean narration and
write 6 English search queries for a free stock photo site (Pexels), one per scene,
following the story order.

[Country] {fact.get("country", "")}
[Topic] {fact.get("topic", "")}
[Narration]
{narration}

Rules:
1. Exactly 6 queries, 2 to 5 words each, plain English.
2. Each query must describe something concrete that exists in a real photo
   (place, object, animal, food, activity). No abstract words like "freedom" or "culture".
3. Include the country or a well-known city/landmark name in at least 3 of the queries.
4. No people's names, brands, or things that need readable text (signs, posters).
5. Output only JSON: {{"queries": ["...", "...", "...", "...", "...", "..."]}}
""".strip()


def parse_queries(text):
    obj = extract_json(text)
    items = obj.get("queries") if isinstance(obj, dict) else obj
    if not isinstance(items, list):
        return None
    out = []
    for q in items:
        q = " ".join(str(q).split())
        if 3 <= len(q) <= 60 and re.fullmatch(r"[A-Za-z0-9 ,'\-]+", q):
            out.append(q)
    return out[:6] if len(out) >= 6 else None


def generate_queries(client, models, fact, narration, retries=3):
    return ask_models(
        client, models,
        "You are a careful photo editor. Output JSON only.",
        build_query_prompt(fact, narration), 500, retries, parse_queries,
    )


# ============================================================
# 사실 검수(과장/일반화 교정) 패스
# ============================================================

def build_factcheck_prompt(fact, narration):
    return f"""당신은 한국어 유튜브 쇼츠 대본의 엄격한 팩트체크 편집자입니다.
아래 글에서 과장, 지나친 일반화, 단정 표현, 자극적 표현, 사실과 다를 가능성이 있는 내용을 찾아 고치세요.

[국가] {fact.get("country", "")}
[주제] {fact.get("topic", "")}
[이 사실의 한계] {fact.get("caveat", "")}

[hook]
{fact.get("hook", "")}
[body]
{fact.get("body", "")}
[twist]
{fact.get("twist", "")}
[narration]
{narration}

찾을 것:
- 단정: 모든/누구나/항상/절대/불법/금지/유일/세계 최초·최대
- 일부 지역·업체·사람의 관습을 나라 전체의 규칙처럼 쓴 것
- 확인되지 않았거나 틀렸을 가능성이 있는 통계·금액·날짜·수치
- 근거보다 강한 주장, 고정관념, 낚시성 표현
- 사실이 아니라고 판단되는 내용

한정어(많은/일부/대체로)와 분명한 범위로 고치거나, 고칠 수 없으면 해당 내용을 삭제하세요.
문체(존댓말, 짧은 문장, 이모지 없음)와 분량(350~500자)은 유지하고 구독/좋아요 요청은 넣지 마세요.
이미 정확하고 차분하면 원문을 그대로 두고 issues를 빈 배열로 두세요.

순수 JSON 객체만 출력:
{{"issues": ["고친 점 또는 여전히 불확실한 점을 한 줄씩"],
  "risk": "low, medium, high 중 하나 (원문에 사실 오류가 있었을 가능성)",
  "hook": "...", "body": "...", "twist": "...", "narration": "..."}}"""


def parse_factcheck(text):
    data = extract_json(text)
    if not isinstance(data, dict) or not str(data.get("narration", "")).strip():
        return None
    return data


def factcheck_fact(client, models, fact, retries=3):
    """대본/설명(hook,body,twist)의 과장·일반화를 교정한다. 교정 내용은 fact_issues에 남긴다."""
    narration = fact.get("narration", "")
    data = ask_models(
        client, models,
        "당신은 꼼꼼한 팩트체크 편집자입니다. JSON만 출력합니다.",
        build_factcheck_prompt(fact, narration), 3000, retries, parse_factcheck,
    )
    fact["fact_checked"] = True
    if not data:
        print("  [사실 검수 실패] 원본 대본을 그대로 사용합니다. review.txt에서 직접 확인하세요.")
        fact["fact_risk"] = "unchecked"
        return True
    issues = [str(x).strip() for x in (data.get("issues") or []) if str(x).strip()]
    fact["fact_issues"] = issues
    fact["fact_risk"] = str(data.get("risk", "low")).strip().lower()
    new_narr = clean_narration(str(data.get("narration", "")))
    ok, why = validate_narration(new_narr)
    if issues and ok:
        fact["narration_original"] = narration
        fact["narration"] = new_narr
        for k in ("hook", "body", "twist"):
            v = str(data.get(k, "")).strip()
            if v:
                fact[k] = v
    elif issues and not ok:
        print(f"  [사실 검수] 수정본이 기준에 안 맞아 원본 유지 ({why})")
    print(f"  [사실 검수] 위험도 {fact['fact_risk']} / 교정 {len(issues)}건")
    for i in issues:
        print(f"    - {i}")
    return True


def title_ok(fact):
    l1, l2 = fact.get("title_line1"), fact.get("title_line2")
    return bool(l1 and l2 and is_korean_title(l1) and is_korean_title(l2))


def ensure_extras(client, models, fact, retries=3):
    """제목 2줄 / 핵심 문구 / 이미지 검색어 중 없는 것만 만든다. 바뀐 게 있으면 True."""
    changed = False
    if not fact.get("fact_checked") and fact.get("narration"):
        changed = factcheck_fact(client, models, fact, retries) or changed
    narration = fact.get("narration", "")
    if not title_ok(fact):
        titles = generate_title(client, models, fact, narration, retries)
        if titles:
            fact["title_line1"], fact["title_line2"] = titles
            changed = True
            print(f"  [제목] {titles[0]} / {titles[1]}")
        else:
            print("  [제목 생성 실패] 영상 제작 시 topic을 자동 분할해서 사용합니다.")
    if fact.get("highlights") is None:  # 빈 리스트([])는 "표시 안 함"이라는 사용자의 선택
        hl = generate_highlights(client, models, fact, narration, retries)
        if hl:
            fact["highlights"] = hl
            changed = True
            print("  [핵심 문구] " + " / ".join(strip_marks(h["text"]) for h in hl))
        else:
            print("  [핵심 문구 생성 실패] 영상 제작 시 대본 문장을 짧게 줄여 대체합니다.")
    if not fact.get("image_queries"):
        qs = generate_queries(client, models, fact, narration, retries)
        if qs:
            fact["image_queries"] = qs
            changed = True
            print("  [이미지 검색어] " + " | ".join(qs))
        else:
            print("  [이미지 검색어 생성 실패] 국가명으로 대체 검색합니다.")
    return changed


def run_extras(client, models, db, limit, start, delay, retries):
    """이미 대본이 있는 소재 중 영상 대상(앞에서 limit개)의 빠진 항목을 보충한다."""
    targets = []
    for index, fact in pending_render(db, start):
        if is_bad_narration(fact.get("narration", "")):
            continue
        targets.append((index, fact))
        if len(targets) >= limit:
            break

    todo = [
        (i, f) for i, f in targets
        if not (title_ok(f) and f.get("highlights") is not None and f.get("image_queries") and f.get("fact_checked"))
    ]
    print(f"제목/핵심 문구/이미지 검색어 보충 대상: {len(todo)}개")
    for number, (index, fact) in enumerate(todo, start=1):
        print(f"[{number}/{len(todo)}] DB index={index} {fact.get('country', '')}")
        if ensure_extras(client, models, fact, retries):
            save_db(db)
        if delay > 0 and number < len(todo):
            time.sleep(delay)


def find_title_targets(db, limit):
    """대본은 있는데 제목 2줄이 아직 없는 항목."""
    targets = []
    for index, fact in enumerate(db):
        l1, l2 = fact.get("title_line1"), fact.get("title_line2")
        # 이미 한글 제목이 있으면 건너뜀 (영어가 섞인 기존 제목은 다시 생성)
        if l1 and l2 and is_korean_title(l1) and is_korean_title(l2):
            continue
        if is_bad_narration(fact.get("narration", "")):
            continue
        targets.append((index, fact))
        if len(targets) >= limit:
            break
    return targets


def run_titles_only(client, models, db, limit, delay, retries):
    targets = find_title_targets(db, limit)
    print(f"제목 생성 대상: {len(targets)}개")

    ok = 0
    for number, (db_index, fact) in enumerate(targets, start=1):
        print(f"[{number}/{len(targets)}] DB index={db_index} {fact.get('country', '')}")
        titles = generate_title(client, models, fact, fact.get("narration", ""), retries)
        if titles:
            fact["title_line1"], fact["title_line2"] = titles
            save_db(db)
            ok += 1
            print(f"  [완료] {titles[0]} / {titles[1]}")
        else:
            print("  [실패] 다음 실행에서 다시 시도합니다.")
        if delay > 0 and number < len(targets):
            time.sleep(delay)

    print(f"\n제목 생성 완료: {ok}/{len(targets)}")


# ============================================================
# Rate Limit
# ============================================================

def get_retry_seconds(error, attempt):
    message = str(error)

    patterns = [
        r"try again in\s+([\d.]+)s",
        r"retry.*?([\d.]+)s",
        r"after\s+([\d.]+)s",
    ]

    for pattern in patterns:
        match = re.search(pattern, message, flags=re.IGNORECASE)

        if match:
            try:
                return max(
                    2.0,
                    min(float(match.group(1)) + 1.0, 60.0)
                )
            except ValueError:
                pass

    return min(8.0 * (2 ** (attempt - 1)), 60.0)


# ============================================================
# 한 모델에서 대본 생성
# ============================================================

def generate_with_model(client, model, fact, retries):
    prompt = build_prompt(fact)

    for attempt in range(1, retries + 1):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "당신은 사실에 충실한 한국어 "
                            "유튜브 쇼츠 대본 작가입니다."
                        ),
                    },
                    {
                        "role": "user",
                        "content": prompt,
                    },
                ],
                temperature=0.7,
                **completion_kwargs(model, MAX_COMPLETION_TOKENS),
            )

            if not response.choices:
                raise RuntimeError("모델 응답에 choices가 없습니다.")

            choice = response.choices[0]
            content = choice.message.content
            if not (content or "").strip():
                raise RuntimeError(f"빈 대본 (finish_reason={choice.finish_reason})")
            narration = clean_narration(content)

            valid, reason = validate_narration(narration)

            if valid:
                return narration, None

            raise RuntimeError(reason)

        except RateLimitError as e:
            if attempt >= retries:
                return None, "Rate Limit 재시도 초과"

            wait_seconds = get_retry_seconds(e, attempt)

            print(
                f"  [429] {model} → "
                f"{wait_seconds:.1f}초 대기 "
                f"({attempt}/{retries})"
            )
            time.sleep(wait_seconds)

        except Exception as e:
            if attempt >= retries:
                return None, str(e)

            wait_seconds = min(3.0 * attempt, 15.0)

            print(
                f"  [재시도] {model} → {e} / "
                f"{wait_seconds:.1f}초 후 "
                f"({attempt}/{retries})"
            )
            time.sleep(wait_seconds)

    return None, "알 수 없는 오류"


# ============================================================
# 항목별 생성
# ============================================================

def generate_script(client, models, fact, retries):
    """
    모델을 순서대로 사용합니다.

    한 모델에서 계속 빈 응답/불량 응답이 나오면
    다음 모델로 전환합니다.
    """

    for model_index, model in enumerate(models):
        print(f"  모델: {model}")

        narration, error = generate_with_model(
            client,
            model,
            fact,
            retries,
        )

        if narration:
            return narration, model

        print(f"  [모델 실패] {model}: {error}")

        if model_index + 1 < len(models):
            print("  → 다음 모델로 전환합니다.")

    return None, None


# ============================================================
# 처리 대상
# ============================================================

def find_targets(db, limit):
    targets = []

    for index, fact in enumerate(db):
        if fact.get("status") != "verified":
            continue

        narration = fact.get("narration", "")

        # narration 없음 또는 잘못된/너무 짧은 기존 대본
        if is_bad_narration(narration):
            targets.append((index, fact))

        if len(targets) >= limit:
            break

    return targets


# ============================================================
# Main
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="문화 상식 Shorts 내레이션 생성기"
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_LIMIT,
        help=f"최대 처리 개수 (기본값: {DEFAULT_LIMIT})",
    )

    parser.add_argument(
        "--model",
        type=str,
        default=None,
        help="특정 Groq 모델을 직접 지정",
    )

    parser.add_argument(
        "--delay",
        type=float,
        default=DEFAULT_DELAY,
        help=f"항목 사이 대기시간(초) (기본값: {DEFAULT_DELAY})",
    )

    parser.add_argument(
        "--retries",
        type=int,
        default=DEFAULT_RETRIES,
        help=f"모델당 최대 재시도 횟수 (기본값: {DEFAULT_RETRIES})",
    )

    parser.add_argument(
        "--start",
        type=int,
        default=0,
        help="이 번호 이후의 소재만 보충 대상으로 삼음 (PC에서 만든 옛 소재 건너뛰기)",
    )

    parser.add_argument(
        "--extras-only",
        action="store_true",
        help="대본은 건드리지 않고 제목/핵심 문구/이미지 검색어만 보충",
    )

    parser.add_argument(
        "--titles-only",
        action="store_true",
        help="대본이 이미 있는 항목에 화면 상단 제목 2줄(title_line1/2)만 생성",
    )

    args = parser.parse_args()

    if args.limit < 1:
        print("[오류] --limit은 1 이상이어야 합니다.")
        sys.exit(1)

    if args.retries < 1:
        print("[오류] --retries는 1 이상이어야 합니다.")
        sys.exit(1)

    api_key = os.getenv("GROQ_API_KEY")

    if not api_key:
        print("[오류] GROQ_API_KEY 환경변수가 없습니다.")
        sys.exit(1)

    client = Groq(api_key=api_key)

    try:
        models = pick_models(client, args.model)
    except Exception as e:
        print(f"[오류] 모델 선택 실패: {e}")
        sys.exit(1)

    db = load_db()

    if args.titles_only:
        run_titles_only(client, models, db, args.limit, args.delay, args.retries)
        return

    if args.extras_only:
        run_extras(client, models, db, args.limit, args.start, args.delay, args.retries)
        return

    targets = find_targets(db, args.limit)

    print("=" * 70)
    print("문화 상식 Shorts 대본 생성기")
    print("=" * 70)
    print(f"사용 가능 모델 : {', '.join(models)}")
    print(f"전체 DB        : {len(db)}개")
    print(f"생성/재생성 대상 : {len(targets)}개")
    print(
        f"목표 분량      : {TARGET_MIN_CHARS}~{TARGET_MAX_CHARS}자 "
        f"(최소 통과 {MIN_CHARS}자)"
    )
    print(f"최대 출력 토큰 : {MAX_COMPLETION_TOKENS}")
    print("=" * 70)

    if not targets:
        print("\n생성/재생성할 대본이 없습니다.")
        run_extras(client, models, db, args.limit, args.start, args.delay, args.retries)
        return

    success_count = 0
    fail_count = 0

    for number, (db_index, fact) in enumerate(targets, start=1):
        country = fact.get("country", "")
        topic = fact.get("topic", "")

        print(
            f"\n[{number}/{len(targets)}] 재생성 "
            f"DB index={db_index}"
        )
        print(f"  국가 : {country}")
        print(f"  주제 : {topic}")

        narration, used_model = generate_script(
            client,
            models,
            fact,
            args.retries,
        )

        if narration:
            fact["narration"] = narration
            fact["status"] = "scripted"  # TTS 단계(generate_tts_v2.py)가 이 상태를 찾습니다.

            # 대본이 새로 바뀌었으므로 이전 제목/핵심 문구/검색어는 지우고 새로 만든다
            for key in ("title_line1", "title_line2", "highlights", "image_queries", "fact_checked", "fact_issues", "fact_risk", "narration_original"):
                fact.pop(key, None)
            ensure_extras(client, models, fact, args.retries)

            # 성공 즉시 저장
            save_db(db)

            success_count += 1

            print(
                f"  [완료] {len(normalize_text(narration))}자 "
                f"/ 모델: {used_model}"
            )
            print("  [저장] facts_db.json 즉시 저장 완료")

        else:
            fail_count += 1

            print("  [실패] 이번 항목은 저장하지 않았습니다.")
            print("  → 다음 실행에서 다시 생성 대상으로 잡힙니다.")

        if args.delay > 0 and number < len(targets):
            time.sleep(args.delay)

    run_extras(client, models, db, args.limit, args.start, args.delay, args.retries)

    print("\n" + "=" * 70)
    print("작업 완료")
    print("=" * 70)
    print(f"성공 : {success_count}")
    print(f"실패 : {fail_count}")
    print(f"DB   : {DB_FILE.resolve()}")
    print("=" * 70)


if __name__ == "__main__":
    main()
