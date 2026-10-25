# -*- coding: utf-8 -*-
"""내 성향·스타일 지침: 대본/롱폼/소재 생성 프롬프트 끝에 붙인다 (UI '2 대본 › 내 스타일'에서 고침, style_profile.json).
파일이 없으면 DEFAULT_ON 규칙이 적용된다. 사실 정확성이 항상 우선이며, 이 지침은 '어떻게 말할지'만 정한다."""
import json
from pathlib import Path

BASE = Path(__file__).resolve().parent
FILE = BASE / "style_profile.json"


def _is_en():
    has_en, has_ko = (BASE / "generate_topics.py").exists(), (BASE / "generate_culture_facts.py").exists()
    if has_en and has_ko:
        try:
            return (BASE / "channel.txt").read_text(encoding="utf-8").strip().lower() == "en"
        except Exception:
            return False
    return has_en and not has_ko


IS_EN = _is_en()

# key: (한국어 라벨, 한국어 규칙, 영어 규칙, 기본 켜짐)
RULES = {
    "dense": ("짧고 밀도 높게", "군더더기 서론·반복·같은 말 되풀이 없이 첫 문장부터 핵심을 말하고, 한 문장에는 정보 하나만 담습니다.",
              "No filler intros or repetition; start with the key point in the first sentence; one piece of information per sentence.", True),
    "concrete": ("구체적으로 (수치·고유명사)", "확인된 연도·수치·지명·제도 이름 등 구체 정보를 우선하고, '독특한·놀라운·신기한' 같은 막연한 형용사는 줄입니다. 단 자료에 없는 숫자나 이름은 절대 만들지 않습니다.",
                 "Prefer concrete, verified details (years, numbers, place and institution names) over vague adjectives like 'unique' or 'amazing'. Never invent numbers or names that are not in the source.", True),
    "fact_vs_guess": ("사실과 추정 구분", "확인된 사실과 '~로 알려져 있습니다', '일부 지역에서는', '유래에는 여러 설이 있습니다'처럼 설·추정을 구분해서 말합니다.",
                      "Separate verified facts from theories or estimates ('is said to', 'in some regions', 'several theories exist').", True),
    "why": ("왜 그런지 설명", "관습이나 현상은 '무엇'에서 끝내지 말고 '왜 그런지'(역사·제도·실용적 이유·원리)를 최소 한 문장 설명합니다.",
            "Don't stop at what it is: explain why it exists (history, rules, practical reasons, mechanism) in at least one sentence.", True),
    "no_cliche_end": ("상투적 결말 금지", "'~해 보세요', '~어떠세요?', '여러분은 어떻게 생각하세요?' 같은 상투적이거나 조심스러운 마무리는 쓰지 않고, 핵심을 되짚는 여운 한 문장이나 반전으로 끝냅니다.",
                      "No cliché or timid endings ('what do you think?', 'try it yourself'); end with one line that lands the key point or a twist.", True),
    "no_hype": ("과장·낚시 줄이기", "'충격', '경악', '소름', '믿기 힘든' 같은 과장·낚시 표현을 쓰지 않고 차분하게 사실로 흥미를 만듭니다.",
                "Avoid hype and clickbait words (shocking, unbelievable); build interest from the facts themselves.", True),
    "visual": ("화면에 그릴 수 있는 문장", "각 문장에 화면으로 보여줄 수 있는 구체적 대상(장소·물건·행동)을 넣어, 장면 이미지와 대사가 서로 맞게 합니다.",
               "Put something visible (a place, object or action) in each sentence so the scene images can match the narration.", True),
    "compare": ("익숙한 것과 비교", "시청자가 이미 아는 것과 짧게 비교해서 이해시킵니다 (예: 우리나라의 비슷한 제도·물건).",
                "Briefly compare with something the viewer already knows so it is easy to grasp.", False),
}
DEFAULT_ON = [k for k, v in RULES.items() if v[3]]

# 소재 만들기 때 가중치를 줄 관심 분야 (켠 것이 우선 소재가 된다)
TOPIC_AREAS = {
    "language": ("언어·말의 구조", "언어·말·표기의 구조와 유래", "language, words and writing systems"),
    "tech": ("기술·산업", "기술·산업·인프라가 일상에 들어온 방식", "technology, industry and infrastructure in daily life"),
    "system": ("제도·법·행정", "제도·법·행정이 만든 생활 규칙", "laws, rules and administration shaping daily life"),
    "efficiency": ("생활 효율·시스템", "편리함·효율을 위한 생활 시스템", "everyday systems built for convenience and efficiency"),
    "food_science": ("음식과 원리", "음식·생활 습관 뒤의 과학적·실용적 원리", "the science or practical logic behind food and habits"),
    "economy": ("돈·경제 문화", "돈·거래·소비와 관련된 문화", "money, trade and consumption customs"),
    "media": ("게임·미디어·대중문화", "게임·미디어·대중문화", "games, media and pop culture"),
}


def load():
    d = {"rules": list(DEFAULT_ON), "custom": "", "avoid": "", "topic_areas": [], "topic_custom": ""}
    try:
        d.update({k: v for k, v in json.loads(FILE.read_text(encoding="utf-8")).items() if k in d})
    except Exception:
        pass
    return d


def save(d):
    FILE.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")


def block(kind="script", d=None):
    """프롬프트 뒤에 붙일 지침 문단 (없으면 ''). kind: script | longform | topic"""
    d = d or load()
    if kind == "topic":
        areas = [TOPIC_AREAS[k][2 if IS_EN else 1] for k in d.get("topic_areas", []) if k in TOPIC_AREAS]
        lines = []
        if areas:
            lines.append(("Prefer topics from these areas when possible (keep variety): " if IS_EN else "가능하면 다음 분야의 소재를 우선하되 다양성은 유지: ") + "; ".join(areas))
        if d.get("topic_custom", "").strip():
            lines.append(d["topic_custom"].strip())
        if d.get("avoid", "").strip():
            lines.append(("Do NOT pick: " if IS_EN else "다음은 소재로 쓰지 않기: ") + d["avoid"].strip())
        head = "[Editor's topic preferences]" if IS_EN else "[편집자 소재 선호]"
        return head + "\n" + "\n".join("- " + x for x in lines) if lines else ""
    lines = [RULES[k][2 if IS_EN else 1] for k in d.get("rules", []) if k in RULES]
    if kind == "longform" and "no_cliche_end" in d.get("rules", []):   # 롱폼 챕터 끝은 '다음 소재로 이어주는 말'이라 따로 표현
        lines = [(("The closing line of a chapter must not be a cliché sign-off ('stay tuned', 'see you next'); make it one natural sentence that leads into the next subject." if IS_EN
                   else "챕터 끝 연결 멘트는 '다음 이야기도 기대해 주세요' 같은 상투적 인사 없이, 다음 소재로 자연스럽게 이어지는 한 문장으로 씁니다.") if x == RULES["no_cliche_end"][2 if IS_EN else 1] else x) for x in lines]
    if d.get("custom", "").strip():
        lines.append(d["custom"].strip())
    if d.get("avoid", "").strip():
        lines.append(("Never use these words/phrases: " if IS_EN else "다음 표현은 쓰지 않기: ") + d["avoid"].strip())
    if not lines:
        return ""
    head = ("[Editor's style guide - applies to HOW you write; factual accuracy and the rules above always come first]" if IS_EN
            else "[편집자 스타일 지침 - '어떻게 말할지'에만 적용. 사실 정확성과 위의 규칙이 항상 우선]")
    return head + "\n" + "\n".join("- " + x for x in lines)


def apply(prompt, kind="script"):
    b = block(kind)
    return f"{prompt}\n\n{b}" if b else prompt
