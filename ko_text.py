# -*- coding: utf-8 -*-
"""한국어 채널용 글 다듬기: ① 나라 이름을 한국어 표기로 통일(음성이 영어/한국어 발음으로 섞이는 것 방지)
② 음성이 영어로 읽는 '(English)' 괄호 설명 제거 ③ 어투 점검('~한다.' 체가 섞인 딱딱한 대본 찾기).
영어 채널에서는 아무것도 바꾸지 않는다."""
import re
import unicodedata

try:
    import country_codes as _cc
except Exception:
    _cc = None

_OVERRIDE = {"KR": "한국", "RU": "러시아", "GB": "영국", "TW": "대만", "VN": "베트남", "LA": "라오스", "CD": "콩고민주공화국", "TR": "튀르키예",
             "CZ": "체코", "MM": "미얀마", "AE": "아랍에미리트", "US": "미국"}
_LATIN_PAREN = re.compile(r"\s*[\(（\[][^()（）\[\]가-힣]*[A-Za-z][^()（）\[\]가-힣]*[\)）\]]")


def strip_latin_parens(text):
    """'볼리비아(Bolivia)', '디아블라다( Diablada )' 처럼 한글이 없는 괄호 설명을 지운다 (음성이 영어로 읽어서 어색함)"""
    return _LATIN_PAREN.sub("", str(text or "")).strip() if text else text


def disp_country(name):
    """'Peru' -> '페루', '볼리비아 (Bolivia)' -> '볼리비아', 'Canada (Quebec)' -> '캐나다'. 모르면 원래 이름"""
    s = strip_latin_parens(unicodedata.normalize("NFKC", str(name or "")).strip())
    if re.search(r"[가-힣]", s):
        return s
    base = re.sub(r"\s*[\(（].*$", "", s).strip()
    if _cc and base:
        code = _cc.country_code(base)
        if code:
            return _OVERRIDE.get(code) or _cc.NAMES.get(code, (s,))[0]
    return s


_PLAIN = re.compile(r"(다|이다|된다|한다|있다|없다|했다|였다|한다고)[.!]?$")
_POLITE = re.compile(r"(습니다|입니다|니다|세요|어요|아요|해요|예요|이에요|죠|까요|네요|군요|에요|할게요|볼까요|드려요|거든요|잖아요)[.!?]?$")


def plain_ratio(text):
    """문장 중 '~한다.' 체(딱딱한 어투) 비율 0~1"""
    ss = [x.strip() for x in re.split(r"(?<=[.!?])\s+|\n+", str(text or "").strip()) if x.strip()]
    if not ss:
        return 0.0
    return sum(1 for s in ss if _PLAIN.search(s) and not _POLITE.search(s)) / len(ss)


def is_stiff(text, thr=0.3):
    return plain_ratio(text) >= thr
