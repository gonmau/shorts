import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

from groq import Groq, RateLimitError

from common import split_sentences, strip_marks, pending_render
from scenes import scene_groups, default_scene_count
import crosscheck


DB_FILE = Path("facts_db.json")

# 우선순위가 높은 모델부터 사용합니다.
PREFERRED_MODELS = [
    "llama-3.1-8b-instant",
    "llama-3.3-70b-versatile",
    "llama-3.1-70b-versatile",
    "gemma2-9b-it",
    "openai/gpt-oss-120b",
    "openai/gpt-oss-20b",  # 120b의 하루 한도가 차면 대신 사용 (모델별로 한도가 따로 있음)
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
MAX_RUN_SECONDS = 15 * 60  # 대본 생성 단계 최대 시간(초). 넘으면 남은 소재는 다음 실행으로
DEFAULT_DELAY = 1.5
DEFAULT_RETRIES = 5

# 30~50초 영어 TTS(약 90~120단어)용으로 너무 짧은 결과는 성공으로 인정하지 않습니다.
MIN_CHARS = 380
TARGET_MIN_CHARS = 520
TARGET_MAX_CHARS = 900   # 이보다 길면 재생성
HARD_MAX_CHARS = 1050    # 재시도가 모두 실패하면 이 길이까지는 마지막 후보를 그대로 사용

# 목표 길이(초): 환경변수 SCRIPT_TARGET_SEC 이 있으면 단어 수 기준을 거기에 맞춘다 (UI 2단계에서 지정). 없으면 아래 기본값(90~115단어).
def _rate_mult():
    m = re.match(r"\s*([+-]?\d+)", os.environ.get("TTS_RATE", ""))
    return 1.0 + (int(m.group(1)) / 100.0 if m else 0.0)


W_LO, W_HI, W_HARD_MAX, W_HARD_MIN = 90, 115, 120, 80
_SEC = os.environ.get("SCRIPT_TARGET_SEC", "").strip()
if _SEC.replace(".", "", 1).isdigit() and float(_SEC) > 0:
    _w = float(_SEC) * 2.2 * _rate_mult()  # 영어 약 2.2단어/초 (속도 설정 반영)
    W_LO, W_HI = max(20, round(_w * 0.88)), max(25, round(_w * 1.12))
    W_HARD_MAX, W_HARD_MIN = round(_w * 1.2), max(15, round(_w * 0.8))
    MIN_CHARS = int(W_HARD_MIN * 4.75)
    TARGET_MIN_CHARS = int(W_LO * 5.8)
    TARGET_MAX_CHARS = int(W_HARD_MAX * 7.5)
    HARD_MAX_CHARS = int(TARGET_MAX_CHARS * 1.17)


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
    "i'm sorry",
    "i am sorry",
    "i cannot",
    "i can't",
    "not enough information",
    "insufficient information",
    "please provide",
    "could you provide",
    "as an ai",
    "unable to write",
]


def normalize_text(text):
    return re.sub(r"\s+", " ", text or "").strip()


def is_bad_narration(text):
    if not text:
        return True

    normalized = normalize_text(text)

    low = normalized.lower()
    for pattern in BAD_PATTERNS:
        if pattern in low:
            return True

    # 기존에 생성된 너무 짧은 대본도 재생성 대상
    if len(normalized) < MIN_CHARS:
        return True

    return False


# ============================================================
# 프롬프트
# ============================================================

def build_prompt(fact):
    label = fact.get("label") or fact.get("country", "")
    topic = fact.get("topic", "")
    hook = fact.get("hook", "")
    body = fact.get("body", "")
    twist = fact.get("twist", "")
    verify_note = fact.get("verify_note", "")
    caveat = fact.get("caveat", "")

    return f"""
You are a scriptwriter for English YouTube Shorts about Korean culture and daily life,
written for an international audience who has never been to Korea.

Write a 35-50 second voice-over using ONLY the verified material below.

[Subject]
{label}

[Topic]
{topic}

[Hook]
{hook}

[Key facts]
{body}

[Twist / surprising point]
{twist}

[Limits of this fact]
{caveat}

[Verification note]
{verify_note}

Rules:
1. Write in natural, conversational American English, as if talking to a friend.
2. Open with a strong first sentence built from the [Hook]. No greetings, no "Hey guys".
3. Explain the key facts, then work in the twist.
4. Do not invent facts, numbers, dates, or prices that are not in the material.
   ACCURACY OVER DRAMA: stay calm and factual, never exaggerate. No absolutes ("everyone", "always", "never", "all Koreans", "illegal", "the only country", "the most/biggest").
   Use qualifiers such as "many", "often", "in some places", "at many cafes" and name the scope (for example "in Seoul"). Never turn a common practice into a universal rule.
   Respect the [Limits of this fact] and mention the limit briefly when it matters.
5. Use short sentences that are easy to read aloud with TTS. Avoid parentheses, emoji, hashtags, and abbreviations.
6. Write Korean words in plain English letters (for example "banchan", "jeonse"), and briefly explain them. No Hangul.
7. Total length: {W_LO} to {W_HI} words. Hard limit: never more than {W_HARD_MAX} words, never fewer than {W_HARD_MIN}. Count the words before you answer and cut if you are over.
8. If the material is short, explain its meaning and context without adding new facts.
9. Never ask people to subscribe, like, follow, turn on notifications, or comment.
   End on a lingering line or a twist, ideally connected to the opening question so people want to watch again.
10. Do not include a title, numbering, or labels like "Narration:" or "Script:".
11. Output only the narration.

Important: the material is already provided. Never answer with "not enough information"
or ask for more details.
""".strip()


# ============================================================
# 응답 정리 및 품질 검사
# ============================================================

def clean_narration(text):
    if not text:
        return ""

    text = text.strip()

    text = re.sub(
        r"^```(?:text|english|en)?\s*",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"\s*```$", "", text)

    text = re.sub(
        r"^(narration|script|voice-?over)\s*[:：]\s*",
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
            return False, f"too short ({len(normalized)} chars)"

        return False, "정보 부족/거절 응답"

    length = len(normalize_text(text))

    # 너무 긴 경우도 영상 길이가 늘어날 수 있으므로 재생성
    if length > TARGET_MAX_CHARS:
        return False, f"너무 김 ({length}자)"

    return True, f"{length}자"


# ============================================================
# 화면 상단 제목 2줄 (title_line1 / title_line2)
# ============================================================

TITLE_MAX_CHARS = 24  # 프롬프트는 20자 이내를 요청하되, 24자까지 허용


def build_title_prompt(fact, narration):
    return f"""
You write on-screen titles for English YouTube Shorts about Korean culture.
Write a 2-line title that will be shown big at the top of the video.

[Subject]
{fact.get("label") or fact.get("country", "")}

[Topic]
{fact.get("topic", "")}

[Hook]
{fact.get("hook", "")}

[Narration]
{narration}

Rules:
1. Output exactly 2 lines.
2. Line 1 sets up the situation or subject. Line 2 creates curiosity with the result or the twist.
3. Each line is at most 20 characters including spaces. Short and punchy.
4. Do not invent facts or numbers that are not in the material.
5. No clickbait exaggeration. It must match the content. No absolutes such as "Everyone", "Always", "Never", "Illegal", "Only" unless the narration states it exactly that way.
6. English only. No Hangul. Korean words in plain English letters.
7. No emoji, quotation marks, periods, numbering, or labels. Just the two lines.

Output format:
(line 1)
(line 2)
""".strip()


def is_english_title(line):
    """영문 알파벳이 있고 한글이 없는 제목/문구 줄인지."""
    return bool(re.search(r"[A-Za-z]", line)) and not re.search(r"[가-힣]", line)


def parse_title(text):
    """모델 응답에서 2줄 제목을 뽑는다. 형식이 맞지 않으면 None."""
    if not text:
        return None

    lines = []
    for raw in text.strip().splitlines():
        line = re.sub(r"^\s*(\d+[.)]|[-*•]|\(?(?:line\s*)?[12]\)?\s*[:：]?)\s*", "", raw)
        line = line.strip().strip("\"'“”‘’`").rstrip(".。").strip()
        if line:
            lines.append(line)

    if len(lines) != 2:
        return None
    if any(len(x) > TITLE_MAX_CHARS for x in lines):
        return None
    if not all(is_english_title(x) for x in lines):
        return None  # 한글이 섞이면 재시도
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
                        {"role": "system", "content": "You are a fact-faithful English Shorts title writer."},
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

HL_MAX_CHARS = 28  # 프롬프트는 22자 이내를 요청하되 28자까지 허용


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
You are a caption designer for English YouTube Shorts.
Read the narration and pick the key phrases to show BIG on screen.

[Subject] {fact.get("label") or fact.get("country", "")}
[Topic] {fact.get("topic", "")}

[Narration - sentence numbers]
{numbered}

Rules:
1. Pick 3 to 6 key phrases, in story order. Sentence numbers (s) must be ascending and never repeated.
2. Each phrase is at most 22 characters including spaces. English only, no Hangul. Numbers are fine.
3. Do not copy the sentence. Compress it into a punchy word or short phrase that sticks.
4. Wrap the single most important word of each phrase in *asterisks*. Example: Buses are *free*?
5. Do not invent facts or numbers that are not in the narration.
6. Output only this JSON, nothing else:

{{"highlights": [{{"s": 1, "text": "phrase"}}, {{"s": 3, "text": "phrase"}}]}}
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
        if not plain or len(plain) > HL_MAX_CHARS or not is_english_title(plain):
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
        "You are an editor who writes short, punchy English captions.",
        build_highlight_prompt(fact, narration), 600, retries,
        lambda t: parse_highlights(t, n),
    )


def build_query_prompt(fact, narration):
    sents = split_sentences(narration)
    groups = scene_groups(sents, default_scene_count())
    hl = {h.get("s"): strip_marks(h.get("text", "")) for h in (fact.get("highlights") or []) if isinstance(h, dict)}
    blocks = []
    for k, (a, b) in enumerate(groups, start=1):
        text = " ".join(sents[a - 1:b])
        marks = [hl[n] for n in range(a, b + 1) if n in hl]
        line = f"Scene {k} (sentences {a}-{b}): {text}"
        if marks:
            line += f"\n   On-screen key phrase while this is read: {' / '.join(marks)}"
        blocks.append(line)
    subject = str(fact.get("verify_note") or fact.get("topic") or "").strip()
    return f"""
You pick stock photos for a short vertical video. The narration is split into scenes;
each scene's photo is shown WHILE that scene's sentences are being read, so the photo
must show what those sentences are about. Write one English search query per scene
for a free stock photo site (Pixabay).

[Country] {fact.get("country", "")}
[Topic] {fact.get("topic", "")}
[Main subject keywords] {subject}

{chr(10).join(blocks)}

Rules:
1. Exactly {len(groups)} queries, one per scene, in order. 2 to 5 words each, plain English.
2. Each query must describe something concrete that exists in a real photo
   (place, object, animal, food, activity). No abstract words like "freedom" or "culture".
3. The query must match what THAT scene's sentences say. If a scene has an on-screen key
   phrase, its query must name that key phrase's main subject literally.
4. Use the main subject (or the country/landmark) in at least 4 of the queries so the topic
   is recognizable in most scenes; vary the rest with related concrete things.
5. No people's names, brands, or things that need readable text (signs, posters).
6. Output only JSON: {{"queries": [{", ".join('"..."' for _ in groups)}]}}
""".strip()


def parse_queries(text, n=6):
    obj = extract_json(text)
    items = obj.get("queries") if isinstance(obj, dict) else obj
    if not isinstance(items, list):
        return None
    out = []
    for q in items:
        q = " ".join(str(q).split())
        if 3 <= len(q) <= 60 and re.fullmatch(r"[A-Za-z0-9 ,'\-]+", q):
            out.append(q)
    return out[:n] if len(out) >= n else None


def generate_queries(client, models, fact, narration, retries=3):
    return ask_models(
        client, models,
        "You are a careful photo editor. Output JSON only.",
        build_query_prompt(fact, narration), 600, retries,
        lambda t: parse_queries(t, len(scene_groups(split_sentences(narration), default_scene_count())) or 6),
    )


# ============================================================
# 사실 검수(과장/일반화 교정) 패스
# ============================================================

def build_factcheck_prompt(fact, narration):
    return f"""You are a strict fact-checker and editor for English YouTube Shorts about Korea.
Review the texts below and fix anything exaggerated, over-generalized, absolute, sensationalized, or likely inaccurate.

[Subject] {fact.get("label") or fact.get("country", "")}
[Topic] {fact.get("topic", "")}
[Limits of this fact] {fact.get("caveat", "")}

[hook]
{fact.get("hook", "")}
[body]
{fact.get("body", "")}
[twist]
{fact.get("twist", "")}
[narration]
{narration}

What to look for:
- absolutes: everyone, all Koreans, always, never, illegal, banned, the only/first/biggest/most
- a trend, a company's or one city's practice presented as a nationwide rule
- statistics, prices, dates or numbers that are unverified or likely wrong
- claims stronger than the evidence, stereotypes, shock-bait wording
- anything you believe is factually wrong

Fix them with qualified, calm wording (many / often / in some places / typically) and a clear scope, or delete the claim if it cannot be fixed.
Keep the same style, make the narration still {W_LO} to {W_HI} words, short sentences, no emoji, no subscribe/like requests.
If everything is already accurate and calm, return the texts unchanged with an empty issues list.

Respond with a pure JSON object only:
{{"issues": ["short English description of each problem you fixed or that remains uncertain"],
  "risk": "low, medium or high (how likely the ORIGINAL contained a factual error)",
  "verifiability": "documented = you know this practice/fact genuinely exists and is documented; unverified = you cannot confirm it exists; fabricated = it seems invented or you believe it does not exist. Be honest: if you have never heard of it, answer unverified",
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
        "You are a careful fact-checking editor. Output JSON only.",
        build_factcheck_prompt(fact, narration), 3000, retries, parse_factcheck,
    )
    fact["fact_checked"] = True
    if not data:
        print("  [사실 검수 실패] 검수 없이는 영상으로 만들지 않습니다 (소재 폐기).")
        fact["fact_risk"] = "unchecked"
        fact["fact_verifiability"] = "unchecked"
        fact["status"] = "rejected"
        fact["reject_reason"] = "사실 검수 실패"
        return True
    issues = [str(x).strip() for x in (data.get("issues") or []) if str(x).strip()]
    fact["fact_issues"] = issues
    fact["fact_risk"] = str(data.get("risk", "low")).strip().lower()
    fact["fact_verifiability"] = str(data.get("verifiability", "unverified")).strip().lower()
    new_narr = clean_narration(str(data.get("narration", "")))
    ok, why = validate_narration(new_narr)
    fact["fact_applied"] = False
    if issues and ok:
        fact["narration_original"] = narration
        fact["narration"] = new_narr
        fact["fact_applied"] = True
        for k in ("hook", "body", "twist"):
            v = str(data.get(k, "")).strip()
            if v:
                fact[k] = v
    # 근거가 불확실한 소재는 고쳐 쓰지 않고 폐기한다 (말투만 부드럽게 해도 지어낸 내용이면 소용없음)
    reason = None
    if fact["fact_verifiability"] != "documented":
        reason = f"확인 불가/조작 의심 ({fact['fact_verifiability']})"
    elif fact["fact_risk"] in ("medium", "high"):
        reason = f"사실 오류 위험 {fact['fact_risk']}"
    elif issues and not ok:
        reason = f"교정본이 기준에 안 맞아 적용 못 함 ({why})"
    print(f"  [사실 검수] 위험도 {fact['fact_risk']} / 확인도 {fact['fact_verifiability']} / 교정 {len(issues)}건 / 적용 {fact['fact_applied']}")
    for i in issues:
        print(f"    - {i}")
    if reason:
        fact["status"] = "rejected"
        fact["reject_reason"] = reason
        print(f"  [폐기] 이 소재는 영상으로 만들지 않습니다: {reason}")
    return True


def title_ok(fact):
    l1, l2 = fact.get("title_line1"), fact.get("title_line2")
    return bool(l1 and l2 and is_english_title(l1) and is_english_title(l2))


def ensure_extras(client, models, fact, retries=3):
    """제목 2줄 / 핵심 문구 / 이미지 검색어 중 없는 것만 만든다. 바뀐 게 있으면 True."""
    changed = False
    # AI 사실검수는 하지 않는다 (사실 확인은 사람이 직접 한다)
    narration = fact.get("narration", "")
    if crosscheck.enabled() and not fact.get("cross_checked") and fact.get("status") != "rejected":
        changed = crosscheck.cross_check(client, models, fact, fix=(clean_narration, validate_narration, (TARGET_MIN_CHARS, TARGET_MAX_CHARS))) or changed
        if fact.get("status") == "rejected":
            return True
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
            fact["scene_count"] = default_scene_count()
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
        if not (title_ok(f) and f.get("highlights") is not None and f.get("image_queries"))
        or (crosscheck.enabled() and not f.get("cross_checked"))
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
        if l1 and l2 and is_english_title(l1) and is_english_title(l2):
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
    best = None  # '너무 김'으로 거절됐지만 HARD_MAX_CHARS 이내인 마지막 후보

    for attempt in range(1, retries + 1):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a fact-faithful scriptwriter "
                            "for English YouTube Shorts."
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

            if "너무 김" in reason and len(normalize_text(narration)) <= HARD_MAX_CHARS:
                best = narration

            raise RuntimeError(reason)

        except RateLimitError as e:
            if attempt >= retries:
                return None, "Rate Limit 재시도 초과"

            msg = str(e).lower()
            if "per day" in msg or "tpd" in msg or "rpd" in msg:
                # 하루 한도는 기다려도 안 풀리므로 바로 다음 모델로 넘어간다
                return None, "하루 한도 초과 (Groq 일일 토큰/요청 한도)"

            wait_seconds = get_retry_seconds(e, attempt)

            print(
                f"  [429] {model} → "
                f"{wait_seconds:.1f}초 대기 "
                f"({attempt}/{retries})"
            )
            time.sleep(wait_seconds)

        except Exception as e:
            if attempt >= retries:
                if best:
                    print(f"  [길이 초과 대본 사용] {len(normalize_text(best))}자 (재시도 모두 소진)")
                    return best, None
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
        "--index",
        type=int,
        default=None,
        help="--extras-only와 함께: 이 번호 소재 하나만 (영상이 이미 있어도) 빠진 제목/검색어를 보충",
    )

    parser.add_argument(
        "--regen-queries",
        action="store_true",
        help="--index와 함께: 기존 이미지 검색어를 지우고 대본 기준으로 새로 만듦",
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

    client = Groq(api_key=api_key, timeout=90.0)  # 응답 없는 연결에 무한 대기하지 않게

    try:
        models = pick_models(client, args.model)
    except Exception as e:
        print(f"[오류] 모델 선택 실패: {e}")
        sys.exit(1)

    db = load_db()

    if args.titles_only:
        run_titles_only(client, models, db, args.limit, args.delay, args.retries)
        return

    if args.extras_only and args.index is not None:
        if not (0 <= args.index < len(db)):
            print(f"[오류] --index {args.index} 범위 오류")
            sys.exit(1)
        fact = db[args.index]
        if args.regen_queries:
            fact.pop("image_queries", None)
        print(f"[{args.index}] {fact.get('country', '')}: 빠진 제목/검색어 보충")
        if ensure_extras(client, models, fact, args.retries):
            save_db(db)
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

    started_at = time.time()
    for number, (db_index, fact) in enumerate(targets, start=1):
        if time.time() - started_at > MAX_RUN_SECONDS:
            print(f"\n[중단] 대본 생성이 {MAX_RUN_SECONDS // 60}분을 넘어 남은 소재는 다음 실행으로 미룹니다. "
                  "(Groq 한도/지연 가능성: console.groq.com 사용량 확인)")
            break
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
            for key in ("title_line1", "title_line2", "highlights", "image_queries", "fact_checked", "fact_issues", "fact_risk", "fact_verifiability", "fact_applied", "reject_reason", "narration_original", "cross_checked", "cross_notes", "cross_verdict", "cross_model", "cross_sources"):
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
