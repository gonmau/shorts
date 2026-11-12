# -*- coding: utf-8 -*-
"""대본에 맞는 인포그래픽(비교 막대 · 큰 숫자 · 타임라인 · 순위 · 단계)을 AI가 대본에서 뽑고, 템플릿으로 그려 영상에 넣는다.

  python infographic.py --index 583 [--force] [--preview out.png]   # 한 소재의 인포그래픽 만들기/보기
  python infographic.py --missing --limit 20                         # 대본은 있는데 인포그래픽이 아직 없는 소재 채우기 (AI 판정, 없으면 'none')

저장: 소재의 "infographic" 필드
  {"on": true, "kind": "bars", "title": "...", "s": 3, "dur": 5.0, "unit": "", "rows": [{"label": "", "value": 12.0, "text": "12%"}], "none": false}
규칙(환각 방지):
  - 숫자·항목은 대본에 실제로 나온 것만 쓴다. 대본에 없는 숫자가 들어간 행은 버리고, 행이 2개 미만이 되면 인포그래픽을 만들지 않는다.
  - 막대 길이는 실제 수치 비율(0부터)로 그린다.
  - 만들 만한 구조가 없으면(분위기·이야기 위주) 만들지 않는다(none)."""
import argparse
import json
import os
import re
from pathlib import Path

from PIL import Image, ImageDraw

BASE = Path(__file__).resolve().parent
EN = (BASE / "generate_topics.py").exists() and not (BASE / "generate_culture_facts.py").exists()
KINDS = {"bars": "비교 막대", "bignum": "큰 숫자", "timeline": "타임라인", "ranking": "순위", "steps": "단계"}
BG = (14, 16, 28)
SKY = (56, 189, 248)
YEL = (255, 226, 0)
WHITE = (255, 255, 255)
SOFT = (200, 205, 225)


# ---------------- 검증 ----------------
def _nums(s):
    return [x.replace(",", "") for x in re.findall(r"\d[\d,]*\.?\d*", str(s or ""))]


def _nospace(s):
    return re.sub(r"\s+", "", str(s or ""))


def _bigrams(s):
    t = re.sub(r"[^0-9A-Za-z가-힣]", "", str(s or "").lower())
    return {t[i:i + 2] for i in range(len(t) - 1)}


def verify(spec, narration):
    """대본과 맞지 않는 행을 버리고 정리된 spec 을 돌려준다. 못 쓰면 None"""
    if not spec or spec.get("kind") not in KINDS:
        return None
    nar_digits = set(_nums(narration))
    nar_bg = _bigrams(narration)
    rows = []
    for r in spec.get("rows") or []:
        label, text = str(r.get("label", "")).strip(), str(r.get("text", "")).strip()
        if not (label or text):
            continue
        ns = _nums(label) + _nums(text)
        if any(n not in nar_digits and not any(n in d for d in nar_digits) for n in ns):
            continue                                  # 대본에 없는 숫자가 있는 행은 버린다
        bg = _bigrams(label + text)
        if bg and len(bg & nar_bg) / len(bg) < 0.5 and not ns:
            continue                                  # 숫자도 없고 대본과 글자가 거의 안 겹치는 행도 버린다
        try:
            v = float(r["value"]) if r.get("value") is not None else None
        except (TypeError, ValueError):
            v = None
        rows.append({"label": label[:24], "value": v, "text": text[:30]})
    need = 1 if spec["kind"] == "bignum" else 2
    if len(rows) < need:
        return None
    if spec["kind"] == "bars" and sum(1 for r in rows if r["value"] is not None) < 2:
        return None
    out = dict(spec)
    out["rows"] = rows[:5]
    out["title"] = str(spec.get("title", "")).strip()[:40]
    return out


# ---------------- AI 분석 ----------------
def _sentences(narration):
    try:
        from subtitles import split_sentences
        return split_sentences(narration)
    except Exception:
        return [x for x in re.split(r"(?<=[.!?])\s+|\n+", str(narration or "")) if x.strip()]


def prompt(narration):
    sents = _sentences(narration)
    num = "\n".join(f"[{i}] {s}" for i, s in enumerate(sents, 1))
    lang = "English" if EN else "한국어"
    return f"""You make ONE infographic spec for a short video from its narration. Write labels in {lang}.
Narration (sentence numbers in brackets):
{num}

Choose the kind that the narration really supports:
- bars: 2-5 items with comparable numbers (value = number only, text = number with unit as written)
- bignum: one striking number (label = what it is, text = the number as written)
- timeline: 2-5 dated steps (label = year/time as written, text = what happened)
- ranking: 2-5 ordered items (label = item, text = short note or number)
- steps: 2-5 procedure steps (label = short step name, text = short detail)
Rules: use ONLY numbers, names and facts that appear in the narration, written the same way. Never invent or round numbers. Labels max 8 chars (Korean) / 14 chars (English); text max 14 chars (Korean) / 22 chars (English). title max 16 chars (Korean) / 30 chars (English).
"s" = the sentence number where this information is introduced. If the narration has no real structure for an infographic (mood, story only), answer {{"kind":"none"}}.
JSON only: {{"kind":"bars|bignum|timeline|ranking|steps|none","title":"","s":1,"unit":"","rows":[{{"label":"","value":null,"text":""}}]}}"""


def generate(client, models, narration):
    """대본 -> 검증된 spec(dict) 또는 {"none": True}. 호출 실패면 None(나중에 다시 시도)"""
    kw = {"max_completion_tokens": 1500, "extra_body": {"reasoning_effort": "low"}} if "gpt-oss" in str(models[0]) else {"max_completion_tokens": 700}
    for m in models:
        try:
            r = client.chat.completions.create(model=m, messages=[{"role": "user", "content": prompt(narration)}], temperature=0.2, **kw)
            t = r.choices[0].message.content or ""
            d = json.loads(t[t.find("{"):t.rfind("}") + 1])
        except Exception as e:
            print(f"  인포그래픽 분석 실패: {type(e).__name__} {str(e)[:60]}")
            continue
        if d.get("kind") in (None, "none"):
            return {"none": True, "on": False}
        v = verify(d, narration)
        if not v:
            return {"none": True, "on": False, "why": "대본과 대조해 쓸 수 있는 행이 부족"}
        n_s = len(_sentences(narration))
        try:
            s = int(d.get("s") or 1)
        except (TypeError, ValueError):
            s = 1
        v.update({"on": True, "s": min(max(1, s), max(1, n_s)), "dur": 5.0, "none": False})
        return v
    return None


# ---------------- 그리기 ----------------
def _font(size, bold=True):
    import overlays
    return overlays._font(int(size), bold)


def _w(d, t, f):
    return d.textlength(str(t), font=f)


def _fit(d, text, max_w, size, min_size=22, bold=True):
    text = str(text)
    f = _font(size, bold)
    while size > min_size and _w(d, text, f) > max_w:
        size = int(size * 0.92)
        f = _font(size, bold)
    if _w(d, text, f) > max_w:           # 그래도 넘치면 말줄임
        while len(text) > 2 and _w(d, text + "…", f) > max_w:
            text = text[:-1]
        text += "…"
    return f, text


def _num_text(r):
    return r.get("text") or (("%g" % r["value"]) if r.get("value") is not None else "")


def render(spec, w=960, h=560):
    """인포그래픽 카드 이미지(RGBA, w x h)"""
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    R = max(18, h // 14)
    d.rounded_rectangle((0, 0, w - 1, h - 1), radius=R, fill=BG + (255,), outline=SKY + (255,), width=5)
    pad = int(w * 0.045)
    kind, rows = spec.get("kind"), spec.get("rows") or []
    y = pad * 0.6
    title = spec.get("title") or ""
    if title:
        f, t = _fit(d, title, w - 2 * pad, int(h * 0.105), 26)
        d.text((w / 2, y + f.size * 0.55), t, font=f, fill=WHITE, anchor="mm", stroke_width=2, stroke_fill=(0, 0, 0))
        y += f.size * 1.4
        d.rounded_rectangle((w / 2 - 70, y, w / 2 + 70, y + 6), radius=3, fill=YEL)
        y += 22
    top, bottom = y, h - pad * 0.7
    avail = bottom - top
    n = len(rows)
    if kind == "bignum":
        r = rows[0]
        f, t = _fit(d, _num_text(r), w - 2 * pad, int(avail * 0.62), 40)
        d.text((w / 2, top + avail * 0.38), t, font=f, fill=YEL, anchor="mm", stroke_width=3, stroke_fill=(0, 0, 0))
        f2, t2 = _fit(d, r.get("label", ""), w - 2 * pad, int(avail * 0.17), 24, False)
        d.text((w / 2, top + avail * 0.80), t2, font=f2, fill=WHITE, anchor="mm")
        for k, r2 in enumerate(rows[1:3]):          # 보조 숫자는 작게
            pass
        return im
    rh = min(avail / n, h * 0.2)
    top += (avail - rh * n) / 2
    lab_w = w * 0.27
    if kind == "bars":
        vals = [r["value"] for r in rows if r.get("value") is not None]
        vmax = max(vals) if vals else 1.0
        vmax = vmax if vmax > 0 else 1.0
        bar_x0, bar_x1 = pad + lab_w + 14, w - pad - w * 0.2
        for i, r in enumerate(rows):
            cy = top + rh * (i + 0.5)
            f, t = _fit(d, r["label"], lab_w, int(rh * 0.42), 20)
            d.text((pad + lab_w, cy), t, font=f, fill=WHITE, anchor="rm")
            v = r.get("value")
            ln = (bar_x1 - bar_x0) * (max(0.0, v) / vmax) if v is not None else 0
            col = YEL if (v is not None and v == max(vals)) else SKY
            bh = rh * 0.52
            d.rounded_rectangle((bar_x0, cy - bh / 2, bar_x0 + max(8, ln), cy + bh / 2), radius=int(bh / 3), fill=col + (255,))
            f2, t2 = _fit(d, _num_text(r), w * 0.2, int(rh * 0.42), 20)
            d.text((bar_x0 + max(8, ln) + 14, cy), t2, font=f2, fill=col, anchor="lm", stroke_width=1, stroke_fill=(0, 0, 0))
        return im
    if kind == "timeline":
        lx = pad + w * 0.2
        d.line((lx, top + rh * 0.3, lx, top + rh * (n - 0.3)), fill=SKY + (255,), width=5)
        for i, r in enumerate(rows):
            cy = top + rh * (i + 0.5)
            d.ellipse((lx - 14, cy - 14, lx + 14, cy + 14), fill=YEL + (255,), outline=BG, width=3)
            f, t = _fit(d, r["label"], w * 0.2 - 10, int(rh * 0.44), 20)
            d.text((lx - 28, cy), t, font=f, fill=YEL, anchor="rm", stroke_width=1, stroke_fill=(0, 0, 0))
            f2, t2 = _fit(d, r.get("text") or "", w - lx - 40 - pad, int(rh * 0.40), 20, False)
            d.text((lx + 30, cy), t2, font=f2, fill=WHITE, anchor="lm")
        return im
    # ranking / steps: 번호 + 제목 + 설명
    for i, r in enumerate(rows):
        cy = top + rh * (i + 0.5)
        rr = min(rh * 0.36, 34)
        cx = pad + rr + 4
        d.ellipse((cx - rr, cy - rr, cx + rr, cy + rr), fill=(YEL if i == 0 and kind == "ranking" else SKY) + (255,))
        f0 = _font(int(rr * 1.25))
        d.text((cx, cy), str(i + 1), font=f0, fill=(14, 16, 28), anchor="mm")
        x0 = cx + rr + 22
        has_t = bool(r.get("text"))
        f, t = _fit(d, r["label"], (w - x0 - pad) * (0.5 if has_t and kind == "ranking" else 1.0), int(rh * 0.46), 20)
        if kind == "steps" and has_t:
            d.text((x0, cy - rh * 0.17), t, font=f, fill=WHITE, anchor="lm")
            f2, t2 = _fit(d, r["text"], w - x0 - pad, int(rh * 0.32), 18, False)
            d.text((x0, cy + rh * 0.20), t2, font=f2, fill=SOFT, anchor="lm")
        else:
            d.text((x0, cy), t, font=f, fill=WHITE, anchor="lm")
            if has_t:
                f2, t2 = _fit(d, r["text"], w * 0.3, int(rh * 0.40), 18)
                d.text((w - pad, cy), t2, font=f2, fill=YEL, anchor="rm")
    return im


def screen_layer(spec, W=1920, H=1080):
    """롱폼용: 화면 전체 크기 레이어(어둡게 깔고 가운데에 카드)"""
    layer = Image.new("RGBA", (W, H), (6, 6, 12, 190))
    card = render(spec, int(W * 0.62), int(H * 0.6))
    layer.alpha_composite(card, ((W - card.width) // 2, (H - card.height) // 2))
    return layer


# ---------------- 영상에 넣을 때 쓰는 도우미 ----------------
def active(item):
    g = (item or {}).get("infographic") or {}
    return g if (g.get("on") and not g.get("none") and g.get("rows") and os.environ.get("INFOGRAPHIC", "1") != "0") else None


def info_json(spec):
    return {k: spec.get(k) for k in ("on", "kind", "title", "s", "dur", "unit", "rows", "none", "why") if k in spec}


# ---------------- CLI ----------------
def _client():
    from groq import Groq
    key = os.environ.get("GROQ_API_KEY", "").strip()
    if not key:
        raise SystemExit("GROQ_API_KEY 가 없습니다")
    c = Groq(api_key=key)
    mod = __import__("generate_topics" if EN else "generate_culture_facts")
    return c, [mod.pick_model(c)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--index", type=int)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--missing", action="store_true")
    ap.add_argument("--limit", type=int, default=20)
    ap.add_argument("--preview", default="")
    a = ap.parse_args()
    from common import load_db, save_db
    db = load_db()
    if a.index is not None and not a.force and (db[a.index].get("infographic") or {}).get("rows") and a.preview:
        render(db[a.index]["infographic"]).save(a.preview)
        print("미리보기 저장:", a.preview)
        return
    todo = [a.index] if a.index is not None else [i for i, f in enumerate(db) if a.missing and str(f.get("narration", "")).strip() and f.get("status") != "rejected"
                                                    and "infographic" not in f][:a.limit]
    if not todo:
        print("대상이 없습니다")
        return
    client, models = _client()
    n_ok = 0
    for i in todo:
        f = db[i]
        if not str(f.get("narration", "")).strip():
            print(f"[{i}] 대본이 없어 건너뜀")
            continue
        g = generate(client, models, f["narration"])
        if g is None:
            continue
        f["infographic"] = info_json(g)
        if g.get("none"):
            print(f"[{i}] 만들 만한 구조 없음 {g.get('why', '')}")
        else:
            n_ok += 1
            print(f"[{i}] {KINDS[g['kind']]} '{g['title']}' {len(g['rows'])}행 (문장 {g['s']})")
            if a.preview:
                render(g).save(a.preview)
    save_db(db)
    print(f"완료: 인포그래픽 {n_ok}개")


if __name__ == "__main__":
    main()
