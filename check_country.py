# -*- coding: utf-8 -*-
"""소재의 '나라' 칸과 제목/주제/훅이 가리키는 나라가 다른 것을 찾아 고치거나 폐기한다.
  python check_country.py            # 목록만 보기 (아무것도 안 바꿈)
  python check_country.py --apply    # 아직 영상이 없는 소재: 나라가 하나로 분명하면 나라 칸을 고치고, 애매하면 rejected 로 폐기
                                     # 이미 영상이 된 소재: 나라 칸만 고침(폐기하지 않음), 애매하면 목록에만 표시
제목(title_line1/2)·주제(topic)·훅(hook)에서 나라/주요 지역/도시 이름을 찾는다. 한국 언급은 비교용일 수 있어 무시한다."""
import argparse
import json
import re
from pathlib import Path

from country_codes import NAMES, country_code

DB = Path("facts_db.json")

PLACES = {   # 나라가 아닌 지역/도시 -> 나라 코드 (자주 틀리는 것 위주)
    "푸껫": "TH", "푸켓": "TH", "방콕": "TH", "치앙마이": "TH", "티베트": "CN", "베이징": "CN", "상하이": "CN",
    "웨일스": "GB", "베네치아": "IT", "퀸즐랜드": "AU", "아키타": "JP", "시드니": "AU", "멜버른": "AU", "스코틀랜드": "GB", "잉글랜드": "GB", "런던": "GB", "사르디니아": "IT", "시칠리아": "IT", "로마": "IT",
    "두바이": "AE", "아부다비": "AE", "부에노스아이레스": "AR", "퀘벡": "CA", "토론토": "CA", "하와이": "US", "알래스카": "US",
    "뉴욕": "US", "텍사스": "US", "도쿄": "JP", "교토": "JP", "오사카": "JP", "홋카이도": "JP", "오키나와": "JP",
    "베를린": "DE", "바이에른": "DE", "파리": "FR", "프로방스": "FR", "마드리드": "ES", "바르셀로나": "ES", "이스탄불": "TR",
    "모스크바": "RU", "카이로": "EG", "레이캬비크": "IS", "제주": "KR", "서울": "KR", "부산": "KR", "발리": "ID", "자카르타": "ID",
    "하노이": "VN", "호치민": "VN", "마닐라": "PH", "카트만두": "NP", "델리": "IN", "뭄바이": "IN", "카르나타카": "IN",
    "wales": "GB", "scotland": "GB", "england": "GB", "quebec": "CA", "phuket": "TH", "tibet": "CN", "dubai": "AE", "bali": "ID",
}
_NAME_CODE = {}
for c, (ko, en) in NAMES.items():
    _NAME_CODE[ko] = c
    if len(en) >= 4:
        _NAME_CODE[en.lower()] = c
_NAME_CODE.update({"터키": "TR", "튀르키예": "TR", "체코": "CZ", "미얀마": "MM", "러시아": "RU", "베트남": "VN", "라오스": "LA", "대만": "TW",
                   "영국": "GB", "미국": "US", "파푸아 뉴기니": "PG", "파푸아뉴기니": "PG", "뉴기니": "PG", "한국": "KR", "남아공": "ZA", "남아프리카": "ZA", "이란": "IR", "홍콩": "HK"})
_NAME_CODE.update(PLACES)
_KEYS = sorted((k for k in _NAME_CODE if len(k) >= 2), key=len, reverse=True)
_PAT = re.compile("|".join(re.escape(k) for k in _KEYS), re.I)
# 이름이 다른 단어의 일부일 때(예: 인도하다, 한국어 조사 앞) 오탐을 줄이기 위한 제외
_FALSE = re.compile(r"인도(하|해|된|되|적|주의|인)|미국식|영국식|이란\s?(것|점)|오만(한|하)|터키\s?커피")


def mentions(text):
    t = _FALSE.sub(" ", str(text or ""))
    out = []
    for m in _PAT.finditer(t):
        # 영어 이름은 단어 경계가 맞을 때만 (Ireland 안의 land 같은 것 방지)
        k = m.group(0)
        if re.fullmatch(r"[A-Za-z ]+", k):
            a, b = m.start(), m.end()
            if (a > 0 and t[a - 1].isalpha()) or (b < len(t) and t[b].isalpha()):
                continue
        elif len(k) <= 3 and m.start() > 0 and "가" <= t[m.start() - 1] <= "힣":
            continue                      # 다른 한글 단어의 일부(예: 뉴기니 속 '기니')는 나라 이름으로 보지 않음
        c = _NAME_CODE.get(k) or _NAME_CODE.get(k.lower())
        if c and c not in out:
            out.append(c)
    return out


def analyze(f):
    """(상태, 제안코드, 언급목록). 상태: ok / fix(하나로 분명) / unsure(여러 나라 또는 불분명)"""
    label = str(f.get("country") or f.get("label") or "")
    own = country_code(label) or _NAME_CODE.get(label.strip().lower(), "")
    text = " ".join(str(f.get(k) or "") for k in ("title_line1", "title_line2", "topic", "hook"))
    ms = [c for c in mentions(text) if c != "KR" or own == "KR"]     # 한국 언급은 비교용으로 보고 무시
    if ms and own not in ms:
        return ("fix", ms[0], ms) if len(ms) == 1 else ("unsure", "", ms)
    if own and not ms:
        # 제목/주제에 나라가 안 보여도 대본이 있으면 대본 전체에서 그 나라가 한 번도 안 나오는지 확인 (나라와 상관없는 위키 글이 붙은 경우)
        full = " ".join(str(f.get(k) or "") for k in ("narration", "title_line1", "title_line2", "hook", "topic", "body", "twist"))
        if len(str(f.get("narration") or "")) >= 50:
            allm = [c for c in mentions(full) if c != "KR"]
            if own not in allm and (own != "KR"):
                return "nomention", "", allm
    return "ok", own, ms
    if False:
        pass
    if len(ms) == 1:
        return "fix", ms[0], ms
    return "unsure", "", ms


def made(f):
    return bool(f.get("youtube_id") or f.get("video_path_v6") or f.get("status_v6") == "video_done" or f.get("status") == "video_done")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    db = json.loads(DB.read_text(encoding="utf-8"))
    n_fix = n_rej = 0
    for i, f in enumerate(db):
        if f.get("status") == "rejected":
            continue
        st, code, ms = analyze(f)
        if st == "ok":
            continue
        name = NAMES[code][0] if code in NAMES else code
        title = f"{f.get('title_line1') or ''} {f.get('title_line2') or ''}".strip() or str(f.get("topic"))[:30]
        mark = "영상있음" if made(f) else "미제작"
        who = f"[{i}] {f.get('country')} | {title[:34]} | 언급: {','.join(ms)} ({mark})"
        if st == "fix":
            print(f"고침 -> {name}: {who}")
            if a.apply:
                f["country_before_fix"] = f.get("country")
                f["country"] = name
            n_fix += 1
        else:
            if st == "nomention":
                who = f"[{i}] {f.get('country')} | {title[:34]} | 대본에 그 나라가 한 번도 안 나옴 ({mark})"
            if made(f):
                print(f"애매(영상 있어 그대로 둠): {who}")
            else:
                print(f"폐기: {who}")
                if a.apply:
                    f["status"] = "rejected"
                    f["reject_reason"] = f"나라와 주제 불일치({f.get('country')} / {','.join(ms)})"
                n_rej += 1
    print(f"\n고침 {n_fix}개 · 폐기 {n_rej}개" + ("" if a.apply else " (목록만 - --apply 로 적용)"))
    if a.apply and (n_fix or n_rej):
        DB.write_text(json.dumps(db, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
