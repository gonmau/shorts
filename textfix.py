# -*- coding: utf-8 -*-
"""글꼴에 없는 문자(특히 LLM이 즐겨 쓰는 비분리 하이픈 U+2011 등)가 네모칸(□)으로 나오는 문제를 막는다.
import 하면 PIL 글꼴의 글자 그리기/길이 계산 직전에 문자를 안전한 것으로 바꿔 준다 (제목·자막·문구·썸네일·롱폼 모두 적용)."""
from PIL import ImageFont

# 글꼴(맑은 고딕 등)에 없어 네모칸으로 나오기 쉬운 문자 -> 대체 (코드 포인트로 적어 둠)
_HYPHENS = (0x2010, 0x2011, 0x2012, 0x2212, 0xFE58, 0xFE63, 0xFF0D, 0x2043)      # 하이픈 종류 -> '-'
_SPACES = (0x00A0, 0x202F, 0x2007, 0x2009, 0x200A, 0x2002, 0x2003)                 # 특수 공백 -> ' '
_ZERO = (0x200B, 0x200C, 0x200D, 0x2060, 0xFEFF, 0x00AD, 0x200E, 0x200F)           # 보이지 않는 문자 -> 제거
_TABLE = {**{c: "-" for c in _HYPHENS}, **{c: " " for c in _SPACES}, **{c: None for c in _ZERO}}


def fix(text):
    return text.translate(_TABLE) if isinstance(text, str) else text


def install():
    cls = ImageFont.FreeTypeFont
    if getattr(cls, "_textfix", False):
        return
    for name in ("getmask", "getmask2", "getlength", "getbbox", "getsize", "getsize_multiline"):
        orig = getattr(cls, name, None)
        if orig is None:
            continue

        def make(o):
            def wrapped(self, text, *a, **k):
                return o(self, fix(text), *a, **k)
            wrapped.__name__ = o.__name__
            return wrapped
        setattr(cls, name, make(orig))
    cls._textfix = True


install()
