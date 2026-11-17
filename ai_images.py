"""대본 문장에 맞춘 AI 이미지 생성 (무료 경로).
- 장면별 영어 프롬프트: Groq LLM 이 그 장면이 덮는 대본 문장을 보고 작성 (실패 시 image_queries 로 대체). item["ai_prompts"] 에 저장 -> 수정 가능
- 그림: Cloudflare Workers AI FLUX.1-schnell (CF_ACCOUNT_ID + CF_API_TOKEN, 하루 약 170장 무료)
        또는 Gemini API (GEMINI_API_KEY, 무료 한도는 계정에 따라 다름). AI_IMAGE_PROVIDER=cloudflare|gemini 로 고정 가능
- 결과: <visual_dir>/scene_NN.png (정사각 1024), image_credits 에 source "ai"
- 수동 경로: export_prompts() 로 프롬프트 목록을 내보내 Gemini/ChatGPT 앱에서 만든 뒤 my_images 로 올리면 된다
"""
import base64
import io
import json
import os
import re
import time
from pathlib import Path

import requests
from PIL import Image

STYLE = ("clean modern editorial illustration, cinematic lighting, rich detail, consistent muted color palette, "
         "no text, no letters, no logos, no watermark, no captions")
CF_MODEL = "@cf/black-forest-labs/flux-1-schnell"
GEMINI_MODEL = os.environ.get("GEMINI_IMAGE_MODEL", "gemini-2.5-flash-image")


def enabled(item=None):
    if item is not None and item.get("ai_images") is False:
        return False
    return os.environ.get("AI_IMAGES", "0") == "1" or bool(item and item.get("ai_images"))


def cf_missing():
    return [k for k in ("CF_ACCOUNT_ID", "CF_API_TOKEN") if not os.environ.get(k, "").strip()]


def provider():
    """기본은 Cloudflare만. Gemini 는 무료 키로 이미지 생성이 막히는 경우가 많아 AI_IMAGE_PROVIDER=gemini 로 명시했을 때만 쓴다"""
    p = os.environ.get("AI_IMAGE_PROVIDER", "").strip().lower()
    if p == "gemini" and os.environ.get("GEMINI_API_KEY", "").strip():
        return "gemini"
    if not cf_missing():
        return "cloudflare"
    return ""


def scene_texts(item):
    """각 장면이 덮는 대본 문장 묶음 (이미지 장면 수 기준)"""
    from common import split_sentences
    from scenes import auto_scene_map, item_scene_count
    sents = split_sentences(item.get("narration") or "")
    k = item_scene_count(item)
    if not sents:
        return [""] * k
    starts = auto_scene_map(sents, k)
    out = []
    for i, s in enumerate(starts):
        e = (starts[i + 1] - 1) if i + 1 < len(starts) else len(sents)
        e = max(e, s)
        out.append(" ".join(sents[s - 1:e]))
    return out


def make_prompts(item, force=False):
    """장면별 영어 프롬프트. 이미 있고 대본 장면 수와 같으면 재사용(수정한 것 보존)"""
    texts = scene_texts(item)
    cur = list(item.get("ai_prompts") or [])
    if cur and len(cur) == len(texts) and not force:
        return cur
    qs = list(item.get("image_queries") or [])
    fallback = [(qs[i] if i < len(qs) else (item.get("country") or "world")) + ", documentary scene" for i in range(len(texts))]
    prompts = None
    key = os.environ.get("GROQ_API_KEY", "").strip()
    if key:
        try:
            from groq import Groq
            c = Groq(api_key=key, timeout=90.0)
            topic = f"{item.get('country', '')} / {item.get('verify_note') or item.get('topic') or ''}"
            lines = "\n".join(f"{i + 1}. {t}" for i, t in enumerate(texts))
            msg = (f"Video topic: {topic}\nWrite one English image-generation prompt per numbered voice-over segment below. "
                   "Each prompt must visually depict what that segment says (concrete subject, setting, action, era), "
                   "be a single sentence under 45 words, contain no text/lettering, no real living people's faces, "
                   "and vary the camera angle between scenes. Output JSON only: {\"prompts\": [\"...\", ...]} with exactly "
                   f"{len(texts)} items.\n\n{lines}")
            for m in ("openai/gpt-oss-120b", "llama-3.3-70b-versatile"):
                try:
                    kw = {"max_completion_tokens": 4000}
                    if "gpt-oss" in m:
                        kw["extra_body"] = {"reasoning_effort": "low"}
                    r = c.chat.completions.create(model=m, temperature=0.6, messages=[
                        {"role": "system", "content": "You write precise text-to-image prompts. Output JSON only."},
                        {"role": "user", "content": msg}], **kw)
                    mm = re.search(r"\{.*\}", r.choices[0].message.content or "", re.S)
                    arr = json.loads(mm.group(0)).get("prompts") if mm else None
                    if isinstance(arr, list) and len(arr) == len(texts) and all(str(a).strip() for a in arr):
                        prompts = [str(a).strip() for a in arr]
                        break
                except Exception as e:
                    print(f"    [AI이미지] 프롬프트 {m} 실패: {type(e).__name__}: {str(e)[:80]}", flush=True)
        except Exception as e:
            print(f"    [AI이미지] 프롬프트 생성 건너뜀 ({type(e).__name__})", flush=True)
    item["ai_prompts"] = prompts or fallback
    return item["ai_prompts"]


def _gen_cloudflare(prompt, session):
    acc, tok = os.environ["CF_ACCOUNT_ID"].strip(), os.environ["CF_API_TOKEN"].strip()
    r = session.post(f"https://api.cloudflare.com/client/v4/accounts/{acc}/ai/run/{CF_MODEL}",
                     headers={"Authorization": f"Bearer {tok}"}, json={"prompt": prompt, "steps": 4}, timeout=120)
    if r.status_code == 429:
        raise RuntimeError("Cloudflare 한도 초과(429): " + r.text[:150])
    r.raise_for_status()
    b64 = (r.json().get("result") or {}).get("image")
    if not b64:
        raise RuntimeError("응답에 이미지 없음")
    return base64.b64decode(b64)


def _gen_gemini(prompt, session):
    key = os.environ["GEMINI_API_KEY"].strip()
    r = session.post(f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent",
                     headers={"x-goog-api-key": key},
                     json={"contents": [{"parts": [{"text": prompt}]}],
                           "generationConfig": {"responseModalities": ["IMAGE"]}}, timeout=120)
    if r.status_code == 429:
        raise RuntimeError("Gemini 429 (이미지 생성은 무료 키로는 한도 0일 수 있음): " + r.text[:200])
    r.raise_for_status()
    for cand in r.json().get("candidates", []):
        for p in (cand.get("content") or {}).get("parts", []):
            d = p.get("inlineData") or p.get("inline_data")
            if d and d.get("data"):
                return base64.b64decode(d["data"])
    raise RuntimeError("응답에 이미지 없음 (무료 한도 밖이거나 안전 필터)")


def generate_one(prompt, dest, prov=None, session=None):
    prov = prov or provider()
    if not prov:
        raise RuntimeError("Cloudflare 키가 없습니다: " + ", ".join(cf_missing()))
    session = session or requests.Session()
    full = f"{prompt}. {STYLE}"
    last = None
    for attempt in range(3):
        try:
            raw = _gen_cloudflare(full, session) if prov == "cloudflare" else _gen_gemini(full, session)
            im = Image.open(io.BytesIO(raw)).convert("RGB")
            w, h = im.size
            s = min(w, h)
            im = im.crop(((w - s) // 2, (h - s) // 2, (w - s) // 2 + s, (h - s) // 2 + s)).resize((1024, 1024))
            Path(dest).parent.mkdir(parents=True, exist_ok=True)
            im.save(dest, "PNG")
            return True
        except Exception as e:
            last = e
            if "429" in str(e):      # 한도 문제는 재시도해도 안 풀리고 한도만 더 쓴다
                break
            time.sleep(6 * (attempt + 1))
    raise RuntimeError(f"{type(last).__name__}: {last}")


def fill(item, folder, force=False, scenes=None):
    """장면 이미지를 AI로 만든다. 이미 있는 장면은 force 가 아니면 건드리지 않는다. 성공한 장면 번호 집합을 돌려줌"""
    prov = provider()
    if not prov:
        print(f"    [AI이미지] Cloudflare 키가 없어 건너뜁니다. 빠진 환경변수: {', '.join(cf_missing())}")
        return set()
    print(f"    [AI이미지] 공급자: {prov}")
    prompts = make_prompts(item)
    session = requests.Session()
    done_p = list(item.get("ai_prompts_done") or [])
    credits = {c.get("scene"): c for c in (item.get("image_credits") or [])}
    ok = set()
    for n, p in enumerate(prompts, start=1):
        if scenes and n not in scenes:
            continue
        dest = Path(folder) / f"scene_{n:02d}.png"
        changed = n > len(done_p) or done_p[n - 1] != p
        user_img = (credits.get(n) or {}).get("source") == "user"
        if dest.exists() and not (force or (changed and (credits.get(n) or {}).get("source") == "ai")) :
            continue
        if user_img and not force:
            continue
        try:
            generate_one(p, dest, prov, session)
            credits[n] = {"scene": n, "source": "ai", "license": "AI-generated", "title": p[:80]}
            while len(done_p) < n:
                done_p.append("")
            done_p[n - 1] = p
            ok.add(n)
            print(f"    scene_{n:02d}: AI 생성 ({prov})")
        except Exception as e:
            print(f"    scene_{n:02d}: AI 생성 실패 ({e}) -> 검색 사진으로 대체")
        time.sleep(1.0)
    item["ai_prompts_done"] = done_p
    item["image_credits"] = [credits[k] for k in sorted(k for k in credits if k)]
    return ok


def export_prompts(item):
    """Gemini/ChatGPT 앱에 붙여넣을 프롬프트 목록(텍스트)"""
    texts, prompts = scene_texts(item), make_prompts(item)
    out = [f"# {item.get('country', '')} - 장면별 이미지 프롬프트 (정사각 1:1로 만들고, 파일명은 장면 번호)", ""]
    for i, (t, p) in enumerate(zip(texts, prompts), start=1):
        out += [f"## 장면 {i}", f"대본: {t}", f"프롬프트: {p}. {STYLE}", ""]
    return "\n".join(out)


def main():
    import argparse
    from common import load_db, save_db, visual_dir
    ap = argparse.ArgumentParser()
    ap.add_argument("--index", type=int, required=True)
    ap.add_argument("--scene", type=int, default=None, help="이 장면만 (다시) 만들기")
    ap.add_argument("--force", action="store_true", help="이미 있는 장면도 다시 만들기")
    ap.add_argument("--prompts", action="store_true", help="프롬프트만 새로 쓰기")
    a = ap.parse_args()
    db = load_db()
    item = db[a.index]
    base = Path(__file__).resolve().parent
    if a.prompts:
        make_prompts(item, force=True)
        save_db(db)
        return
    if not provider():
        raise SystemExit(f"Cloudflare 키가 없습니다. UI를 실행한 환경에 빠진 환경변수: {', '.join(cf_missing())} (설정 후 UI를 완전히 껐다 켜세요)")
    ok = fill(item, visual_dir(base, a.index, item), force=a.force or a.scene is not None,
              scenes={a.scene} if a.scene else None)
    save_db(db)
    if not provider():
        raise SystemExit(f"Cloudflare 키가 없습니다. UI를 실행한 환경에 빠진 환경변수: {', '.join(cf_missing())} (설정 후 UI를 완전히 껐다 켜세요)")
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
