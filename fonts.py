# -*- coding: utf-8 -*-
"""영상·자막·썸네일에 쓸 수 있는 글씨체 목록 (fonts/ 폴더의 무료 글꼴, OFL 라이선스).

고르는 값은 글꼴 id(문자열) 하나. ''(기본)이면 예전처럼 Malgun/Noto Sans CJK 를 씁니다.
용도별 기본 글꼴은 환경변수: FONT_SUB(자막), FONT_TITLE(영상 상단 제목), FONT_OVL(화면 문구 기본)."""
import os
from pathlib import Path

DIR = Path(__file__).resolve().parent / "fonts"

# id: (표시 이름, 파일)
REGISTRY = {
    "blackhan": ("블랙한산스 — 굵고 임팩트", "BlackHanSans-Regular.ttf"),
    "dohyeon": ("도현 — 깔끔한 굵은 고딕", "DoHyeon-Regular.ttf"),
    "hanna": ("배민 한나 — 둥근 굵은체", "BM-HANNA.ttf"),
    "jua": ("주아 — 귀여운 둥근체", "Jua-Regular.ttf"),
    "sunflower": ("해바라기 — 단단한 고딕", "Sunflower-Bold.ttf"),
    "gugi": ("구기 — 각진 디자인체", "Gugi-Regular.ttf"),
    "myeongjo": ("나눔명조 ExtraBold — 신문·다큐 느낌", "NanumMyeongjo-ExtraBold.ttf"),
    "songmyung": ("송명 — 부드러운 명조", "SongMyung-Regular.ttf"),
    "yeonsung": ("연성 — 손글씨", "YeonSung-Regular.ttf"),
    "gaegu": ("개구 — 가벼운 손글씨", "Gaegu-Bold.ttf"),
    "dokdo": ("동해독도 — 붓글씨", "EastSeaDokdo-Regular.ttf"),
    "anton": ("Anton — 영어 임팩트", "Anton-Regular.ttf"),
    "bebas": ("Bebas Neue — 영어 슬림 대문자", "BebasNeue-Regular.ttf"),
}


def available():
    """실제 파일이 있는 글꼴만 {id: 표시이름}."""
    return {k: v[0] for k, v in REGISTRY.items() if (DIR / v[1]).exists()}


def label(fid):
    return REGISTRY.get(fid, ("기본 글꼴",))[0] if fid else "기본 글꼴"


def path(fid):
    """글꼴 id → 파일 경로. 없거나 ''이면 None (호출한 쪽의 기본 글꼴 사용)."""
    v = REGISTRY.get(fid or "")
    if v and (DIR / v[1]).exists():
        return str(DIR / v[1])
    return None


def role_path(role):
    """role: 'sub'|'title'|'ovl'|'thumb' → 환경변수 FONT_<ROLE> 로 정한 글꼴 경로 (없으면 None)."""
    return path(os.environ.get("FONT_" + role.upper(), "").strip())
