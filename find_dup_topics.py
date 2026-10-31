# -*- coding: utf-8 -*-
"""facts_db.json 안에서 중복으로 보이는 소재 쌍을 찾는다 (폐기된 소재는 제외, 보기만 하고 DB를 바꾸지 않음).

 python find_dup_topics.py            # 목록 출력 + dup_topics.md 저장
 python find_dup_topics.py --thr 0.4  # 유사도 기준 (낮출수록 더 많이 잡음, 기본 0.45)
- 한국어 채널: 같은 나라(표기가 'Sweden'/'스웨덴'처럼 달라도 같은 나라로 묶음) 안에서 주제·훅·제목·대본 앞부분을 비교합니다.
- 영어 채널: 소재 라벨/주제/훅을 전체에서 비교합니다.
- 비교 방식은 글자 유사도 + 핵심 단어 겹침이라 표현이 다른 같은 내용은 놓칠 수 있고, 다른 소재가 우연히 잡힐 수도 있으니 목록은 후보로만 보세요.
- '어느 쪽을 남길지' 제안: 유튜브에 올라간 것 > 영상 완료 > 조회수(리포트가 있으면) > 번호가 앞선 것. 둘 다 영상이 있으면 제안하지 않습니다."""
import argparse
import difflib
import json
import re
from pathlib import Path

DB = Path("facts_db.json")
IS_EN = Path("generate_topics.py").exists()
_STOP = set("the a an of to in on for and or is are was were with by at from as that this it its you your what why how do does can have has when where who".split())
_JOSA = ("들의", "들은", "들이", "들을", "에서", "으로", "에게", "까지", "부터", "의", "은", "는", "이", "가", "을", "를", "에", "로", "와", "과", "도", "만")


def _canon(s):
    return re.sub(r"[^0-9a-z가-힣]", "", str(s or "").lower())


def _tokens(*texts):
    out = set()
    for t in texts:
        for w in re.findall(r"[A-Za-z]{3,}|[가-힣]{2,}", str(t or "")):
            w = w.lower()
            if re.fullmatch(r"[a-z]+", w):
                if w in _STOP:
                    continue
            else:
                for j in _JOSA:
                    if w.endswith(j) and len(w) - len(j) >= 2:
                        w = w[: -len(j)]
                        break
            out.add(w)
    return out


def _sim(a, b):
    a, b = _canon(a), _canon(b)
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def _country_key(f):
    if IS_EN:
        return ""
    try:
        from country_codes import country_code
        c = country_code(f.get("country", ""))
        if c:
            return c
    except Exception:
        pass
    return _canon(f.get("country", ""))


def score_pair(a, b):
    """(점수, 이유). 점수는 0~1."""
    best, why = 0.0, ""
    for key, label in (("topic", "주제"), ("hook", "훅"), ("label", "라벨")):
        s = _sim(a.get(key), b.get(key))
        if s > best:
            best, why = s, f"{label} 유사 {s:.2f}"
    ta = _tokens(a.get("topic"), a.get("hook"), a.get("title_line1"), a.get("title_line2"), a.get("label"))
    tb = _tokens(b.get("topic"), b.get("hook"), b.get("title_line1"), b.get("title_line2"), b.get("label"))
    if ta and tb:
        j = len(ta & tb) / len(ta | tb)
        if j > best:
            best, why = j, f"핵심 단어 겹침 {j:.2f} ({', '.join(sorted(ta & tb)[:5])})"
    na, nb = str(a.get("narration", ""))[:80], str(b.get("narration", ""))[:80]
    s = _sim(na, nb)
    if s > best and na and nb:
        best, why = s, f"대본 앞부분 유사 {s:.2f}"
    return best, why


def _views():
    try:
        d = json.loads(Path("yt_stats.json").read_text(encoding="utf-8"))
        return {v.get("id"): v.get("views", 0) for v in d[-1]["videos"]}
    except Exception:
        return {}


def rank(f, views):
    """남길 가치: 클수록 남김. (업로드, 영상완료, 조회수)"""
    return (1 if f.get("youtube_id") else 0, 1 if (f.get("status_v6") == "video_done" or f.get("status") == "video_done") else 0, views.get(f.get("youtube_id"), 0))


def find_pairs(db, thr=0.45):
    """-> [{a, b, score, why, keep, drop, drop_safe}] 점수 높은 순. drop_safe=True 면 영상/업로드가 없는 쪽이라 폐기해도 잃는 게 없음."""
    views = _views()
    groups = {}
    for i, f in enumerate(db):
        if f.get("status") == "rejected" or not (f.get("topic") or f.get("hook") or f.get("label")):
            continue
        groups.setdefault(_country_key(f), []).append(i)
    out = []
    for _k, ids in groups.items():
        for x in range(len(ids)):
            for y in range(x + 1, len(ids)):
                i, j = ids[x], ids[y]
                s, why = score_pair(db[i], db[j])
                if s < thr:
                    continue
                ri, rj = rank(db[i], views), rank(db[j], views)
                if ri > rj:
                    keep, drop = i, j
                elif rj > ri:
                    keep, drop = j, i
                elif ri == rj and ri[:2] == (0, 0):
                    keep, drop = min(i, j), max(i, j)          # 둘 다 영상이 없으면 앞 번호를 남김
                else:
                    keep, drop = None, None                    # 둘 다 영상/업로드가 있으면 직접 판단
                safe = drop is not None and rank(db[drop], views)[:2] == (0, 0)
                out.append({"a": i, "b": j, "score": round(s, 2), "why": why, "keep": keep, "drop": drop, "drop_safe": safe})
    out.sort(key=lambda p: -p["score"])
    return out


def describe(f):
    st = "업로드" if f.get("youtube_id") else ("영상완료" if (f.get("status_v6") == "video_done" or f.get("status") == "video_done") else f.get("status", ""))
    return f"{f.get('country', '')} · {str(f.get('topic') or f.get('label') or '')[:40]} ({st})"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--thr", type=float, default=0.45)
    a = ap.parse_args()
    db = json.loads(DB.read_text(encoding="utf-8"))
    pairs = find_pairs(db, a.thr)
    lines = [f"# 중복 소재 후보 {len(pairs)}쌍 (기준 {a.thr})", ""]
    for p in pairs:
        i, j = p["a"], p["b"]
        sug = f"→ [{p['drop']}] 폐기 제안" + (" (영상·업로드 없음)" if p["drop_safe"] else " (이미 영상/업로드가 있어 신중히)") if p["drop"] is not None else "→ 둘 다 영상/업로드가 있어 직접 판단"
        lines += [f"- {p['score']:.2f} · [{i}] {describe(db[i])}  ↔  [{j}] {describe(db[j])}", f"    근거: {p['why']} {sug}"]
    rep = "\n".join(lines)
    Path("dup_topics.md").write_text(rep + "\n", encoding="utf-8")
    print(rep)


if __name__ == "__main__":
    main()
