# -*- coding: utf-8 -*-
"""외부 AI에서 만든/검증한 대본을 붙여넣어 쓰기 위한 도구.
- build_request(): 외부 AI(ChatGPT/Gemini/Perplexity 등)에 그대로 붙여 넣을 '작성+검증' 또는 '검증·수정' 요청문을 만든다.
- parse_blocks(): 붙여넣은 답변에서 '### 번호' 블록별 대본을 뽑는다 (마크다운/각주/목록 기호 정리).
채널 언어(KO/EN)별 규칙을 따른다."""
import re

HEAD = re.compile(r"^\s*(?:#{1,4}\s*|={2,}\s*|\*\*)?\[?\s*(?:소재\s*)?(\d+)\s*\]?\s*(?:={2,}|\*\*)?\s*(?:[-–:|].*)?$")
HEAD2 = re.compile(r"^\s*#{1,4}\s*\[?(\d+)\]?")
STOP_LINE = re.compile(r"^\s*(?:#{1,4}\s*)?(?:\**\s*)?(검증\s*메모|검증\s*결과|출처|참고|notes?|sources?|verification)\b", re.I)


def clean_text(t):
    t = re.sub(r"\[\s*\d+(?:\s*[,\-–]\s*\d+)*\s*\]", "", t)            # 각주 [1] [2,3]
    t = re.sub(r"【[^】]*】|\(\s*출처[^)]*\)|\[출처[^\]]*\]", "", t)
    t = re.sub(r"\[([^\]]+)\]\((?:https?://)[^)]*\)", r"\1", t)         # 마크다운 링크
    t = re.sub(r"https?://\S+", "", t)
    t = re.sub(r"[*_`]{1,3}", "", t)
    t = re.sub(r"^\s*(?:[-•·>]|\d+[.)])\s+", "", t, flags=re.M)         # 목록 기호
    t = re.sub(r"\s*\n\s*", " ", t)
    return re.sub(r"\s{2,}", " ", t).strip()


def parse_blocks(text):
    """-> {소재번호: 대본문자열}. '### 117' / '=== [117] ===' / '[117]' / '117.' 같은 머리글을 인식"""
    out, cur, buf, stop = {}, None, [], False
    for raw in str(text or "").splitlines():
        line = raw.rstrip()
        m = HEAD2.match(line) or HEAD.match(line)
        if m and (line.strip().startswith(("#", "=", "[", "*")) or re.fullmatch(r"\s*\d+\s*[.:)]?\s*", line)):
            if cur is not None:
                out[cur] = clean_text("\n".join(buf))
            cur, buf, stop = int(m.group(1)), [], False
            continue
        if cur is None or stop:
            continue
        if STOP_LINE.match(line):
            stop = True
            continue
        if line.strip() in ("---", "***", "___"):
            continue
        buf.append(line)
    if cur is not None:
        out[cur] = clean_text("\n".join(buf))
    return {k: v for k, v in out.items() if v}


def sentences(text):
    return [s.strip() for s in re.split(r"(?<=[.!?。])\s+", str(text or "").strip()) if s.strip()]


def check(text, lo, hi, en=False):
    """-> (글자/단어 수, 문제 설명 목록)"""
    n = len(text.split()) if en else len(re.sub(r"\s", "", text)) if False else len(text)
    unit = "단어" if en else "자"
    probs = []
    if n < lo:
        probs.append(f"짧음({n}{unit} < {lo})")
    if n > hi:
        probs.append(f"김({n}{unit} > {hi})")
    if re.search(r"구독|좋아요|subscribe|like and", text, re.I):
        probs.append("구독/좋아요 문구 있음")
    if not en and len(re.findall(r"(다|한다|이다|했다)[.!]", text)) > len(sentences(text)) * 0.4:
        probs.append("'~한다.' 체가 많음(존댓말 구어체 권장)")
    return n, probs


def build_request(items, kind, mode, lo, hi, en=False, channel_desc=""):
    """items: [(번호, 나라, 주제, 기존대본)], kind: 'short'|'long', mode: 'new'|'verify'"""
    long = kind == "long"
    unit = "단어" if en else "자(공백 포함)"
    if en:
        style = "Friendly spoken English, short plain sentences (under 22 words), no emojis, no markdown, no footnotes."
    else:
        style = "존댓말 구어체, 짧은 문장(한 문장 45자 이내), 이모지/마크다운/각주/출처 표기 금지."
    what = ("유튜브 롱폼의 한 챕터 나레이션" if long else "유튜브 쇼츠 1편 나레이션") if not en else ("a long YouTube video chapter voice-over" if long else "a YouTube Shorts voice-over")
    depth = ("쇼츠보다 훨씬 자세히: 배경과 유래, 왜 그런지, 생활 속 구체적 사례, 흥미로운 디테일, 다른 나라와의 차이를 풀어 쓰세요. 마지막 문장은 다음 이야기로 넘어가는 한 줄(또는 따뜻한 마무리)."
             if long else "첫 문장은 시청자를 붙잡는 질문이나 놀라운 사실(후크), 마지막 문장은 여운이나 반전 한 줄.")
    if en:
        depth = ("Go much deeper than a short: background, why it exists, concrete everyday examples, interesting details, and what surprises foreigners. Last sentence: a one-line transition (or warm wrap-up)."
                 if long else "First sentence is a hook (question or surprising fact); last sentence is a twist or lingering line.")
    head = [
        f"아래 소재별로 {what}을 {'새로 작성' if mode == 'new' else '검증·수정'}해 주세요." if not en else f"For each subject below, {'write' if mode == 'new' else 'fact-check and correct'} {what}.",
        "",
        "[규칙]" if not en else "[Rules]",
        f"- 분량: 소재마다 {lo}~{hi}{unit if not en else ' words'}." if not en else f"- Length: {lo}-{hi} words per subject.",
        f"- 문체: {style}",
        f"- {depth}",
        "- 구독/좋아요 요청 금지." if not en else "- No subscribe/like requests.",
        "- 숫자·연도·이름·금액은 신뢰할 수 있는 자료(사전, 공공기관, 박물관, 학술/언론 보도)로 확인된 것만 쓰세요. 확인되지 않으면 '약/대체로/일부 지역에서' 같은 한정어를 쓰거나 그 문장을 빼세요."
        if not en else "- Use numbers, dates, names and prices only if confirmed by reliable sources (dictionaries, public institutions, museums, academic or news reports). Otherwise hedge (about / many / in some places) or drop the sentence.",
        "- 건강 효능, 다이어트, 기원/유래/전통/최초 주장은 근거가 확실한 것만 쓰고, 불확실하면 일반적이고 안전한 설명으로 바꾸세요."
        if not en else "- Health/diet benefits and origin/tradition/'first' claims only when well sourced; otherwise replace them with safe, general statements.",
        "- 문장을 빼서 분량이 모자라지 않게, 뺀 만큼 안전한 일반 문장으로 채우세요. 대본을 임의로 짧게 줄이지 마세요."
        if not en else "- Do not let the script get shorter than the minimum: if you remove a sentence, replace it with a safe general one.",
        "",
        "[출력 형식 - 반드시 지켜 주세요]" if not en else "[Output format - strictly]",
        "- 소재마다 '### 번호' 한 줄 다음에 대본 한 단락만 쓰세요. 설명·출처·표·검증 결과는 대본 사이에 넣지 마세요."
        if not en else "- For each subject write a line '### number' followed by ONE paragraph of script only. No explanations, sources, tables or notes between scripts.",
        "- 검증 메모가 필요하면 모든 대본이 끝난 뒤 맨 끝에 '검증 메모' 제목 아래에만 쓰세요."
        if not en else "- If you have verification notes, put them at the very end under a 'Verification notes' heading.",
        "",
        "[소재]" if not en else "[Subjects]",
    ]
    body = []
    for no, country, topic, cur in items:
        body.append(f"### {no}  ({country} - {topic})")
        if mode == "verify" and cur:
            body.append(("현재 대본:\n" if not en else "Current script:\n") + str(cur).strip())
        body.append("")
    return "\n".join(head + body).strip() + "\n"
