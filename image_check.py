# -*- coding: utf-8 -*-
"""장면 이미지가 이미지 검색어(= 장면 내용)와 맞는지 검증한다. (PC 로컬 전용, 선택 기능)

- 1차 CLIP(open_clip ViT-B-32): 이미지-검색어 의미 유사도 점수. 빠름(이미지당 ~0.3초, CPU).
- 2차 Ollama 비전 모델(기본 qwen2.5vl:3b): "이 사진이 이 장면 설명에 맞나?"를 JSON으로 판정. 느림(CPU에선 이미지당 수십 초).
  기본은 CLIP이 애매하거나 미달인 장면에만 쓰고, IMG_OLLAMA_ALL=1이면 모든 장면에 씁니다.
- 판정: ok(일치) / doubt(애매: 두 도구 의견이 갈림) / bad(불일치) / unknown(검증 도구 없음 또는 실패).
- 결과는 item["image_check"] = [{scene, verdict, clip, ollama, seen, ...}] 에 저장됩니다.
- --fix 또는 자동 모드(IMAGE_CHECK=1)에서는 bad 장면을 다른 후보(Commons/Pixabay 번갈아)로 최대 IMG_RETRY번 교체하고,
  끝까지 맞는 사진이 없으면 시도한 것 중 점수가 가장 좋은 사진을 남깁니다.
- 어떤 도구가 없거나 실패해도 영상 제작은 멈추지 않습니다(그 장면은 unknown).

환경변수: IMAGE_CHECK=1(자동 모드) IMG_CLIP_THR(0.22) IMG_OLLAMA=1 IMG_OLLAMA_ALL=1 IMG_OLLAMA_MODEL(qwen2.5vl:3b)
          OLLAMA_URL(http://localhost:11434) IMG_RETRY(2) IMG_CLIP=0(CLIP 끄기)

CLI:  python image_check.py --index 12 [--scene 3] [--fix] [--force]
"""
import argparse
import base64
import copy
import hashlib
import io
import json
import os
import sys
import time
from pathlib import Path

import requests

BASE_DIR = Path(__file__).resolve().parent
MARGIN = 0.03          # CLIP이 기준값+MARGIN 이상이면 Ollama 없이 일치로 본다(기본 모드)
MIN_CONF = 65          # Ollama 확신도 이 이상이어야 match로 인정
_ST = {}               # 모델/연결 상태 캐시 (프로세스 동안)
_WARNED = set()
LABEL = {"ok": "일치", "doubt": "애매", "bad": "불일치", "unknown": "미검증"}
RANK = {"ok": 3, "doubt": 2, "unknown": 1, "bad": 0}


def _warn(key, msg):
    if key not in _WARNED:
        _WARNED.add(key)
        print(f"    [이미지검증] {msg}")


def enabled():
    return os.environ.get("IMAGE_CHECK", "0") == "1"


def cfg():
    def f(k, d):
        try:
            return float(os.environ.get(k, "") or d)
        except ValueError:
            return d
    return {
        "thr": f("IMG_CLIP_THR", 0.22),
        "clip": os.environ.get("IMG_CLIP", "1") != "0",
        "ollama": os.environ.get("IMG_OLLAMA", "0") == "1",
        "ollama_all": os.environ.get("IMG_OLLAMA_ALL", "0") == "1",
        "model": os.environ.get("IMG_OLLAMA_MODEL", "").strip() or "qwen2.5vl:3b",
        "url": (os.environ.get("OLLAMA_URL", "").strip() or "http://localhost:11434").rstrip("/"),
        "retry": int(f("IMG_RETRY", 2)),
    }


def tools_label(c):
    t = []
    if c["clip"]:
        t.append("clip")
    if c["ollama"]:
        t.append("ollama-all" if c["ollama_all"] else "ollama")
    return "+".join(t) or "none"


# ---------------------------------------------------------------- CLIP
def _clip():
    if "clip" in _ST:
        return _ST["clip"]
    _ST["clip"] = None
    try:
        import torch
        import open_clip
        dev = "cuda" if torch.cuda.is_available() else "cpu"
        model, _, pre = open_clip.create_model_and_transforms("ViT-B-32", pretrained="laion2b_s34b_b79k")
        model = model.to(dev).eval()
        tok = open_clip.get_tokenizer("ViT-B-32")
        _ST["clip"] = (torch, model, pre, tok, dev, {})
    except Exception as e:
        _warn("clip", f"CLIP을 쓸 수 없어 건너뜁니다 ({type(e).__name__}: {e}). 이 python({sys.executable})에 "
                      "`pip install open_clip_torch torch`가 필요합니다.")
    return _ST["clip"]


def clip_score(path, query):
    st = _clip()
    if not st:
        return None
    torch, model, pre, tok, dev, tcache = st
    from PIL import Image
    try:
        with torch.no_grad():
            if query not in tcache:
                t = model.encode_text(tok([f"a photo of {query}"]).to(dev))
                tcache[query] = t / t.norm(dim=-1, keepdim=True)
            with Image.open(path) as im:
                x = pre(im.convert("RGB")).unsqueeze(0).to(dev)
            f = model.encode_image(x)
            f = f / f.norm(dim=-1, keepdim=True)
            return round(float((f @ tcache[query].T).item()), 4)
    except Exception as e:
        _warn("clip_run", f"CLIP 계산 실패 ({type(e).__name__}: {e})")
        return None


# ---------------------------------------------------------------- Ollama
def _ollama_ready(c):
    if "ollama" in _ST:
        return _ST["ollama"]
    ok = False
    try:
        r = requests.get(c["url"] + "/api/tags", timeout=4)
        r.raise_for_status()
        names = [m.get("name", "") for m in r.json().get("models", [])]
        want = c["model"]
        if any(n == want or n.split(":")[0] == want.split(":")[0] and ":" not in want for n in names):
            ok = True
        else:
            _warn("ollama_model", f"Ollama에 '{want}' 모델이 없습니다 (설치됨: {', '.join(names) or '없음'}). `ollama pull {want}`")
    except Exception as e:
        _warn("ollama_conn", f"Ollama({c['url']})에 연결할 수 없어 건너뜁니다 ({type(e).__name__}). Ollama 앱을 실행하세요.")
    _ST["ollama"] = ok
    return ok


def ollama_judge(path, query, c):
    """-> {"match": bool, "conf": int, "seen": str} 또는 None(실패)"""
    if not _ollama_ready(c):
        return None
    try:
        from PIL import Image
        with Image.open(path) as im:
            im = im.convert("RGB")
            im.thumbnail((640, 640))
            buf = io.BytesIO()
            im.save(buf, "JPEG", quality=85)
        prompt = (
            "You check a photo for a short video. Intended scene description: "
            f"\"{query}\".\n"
            "Does the photo's main visible subject clearly match this description? "
            "Judge only what you can see. If unsure or it shows something else, answer match=false.\n"
            "Return only JSON: {\"match\": true or false, \"confidence\": 0-100, "
            "\"seen\": \"what the photo shows, max 12 words\"}")
        r = requests.post(c["url"] + "/api/generate", json={
            "model": c["model"], "prompt": prompt, "images": [base64.b64encode(buf.getvalue()).decode("ascii")],
            "stream": False, "format": "json", "options": {"temperature": 0}}, timeout=300)
        r.raise_for_status()
        j = json.loads(r.json().get("response", "") or "{}")
        return {"match": j.get("match") is True, "conf": int(float(j.get("confidence", 0) or 0)),
                "seen": str(j.get("seen", ""))[:120]}
    except Exception as e:
        _warn("ollama_run", f"Ollama 판정 실패 ({type(e).__name__}: {e})")
        return None


# ---------------------------------------------------------------- 판정
def judge(path, query, c=None):
    """사진 1장 판정 -> dict(verdict, clip, ollama, seen, tools)"""
    c = c or cfg()
    s = clip_score(path, query) if c["clip"] else None
    clip_ok = None if s is None else s >= c["thr"]
    o = None
    run_o = c["ollama"] and (c["ollama_all"] or s is None or s < c["thr"] + MARGIN)
    if run_o:
        o = ollama_judge(path, query, c)
    o_ok = None if o is None else (o["match"] and o["conf"] >= MIN_CONF)
    if clip_ok is None and o_ok is None:
        v = "unknown"
    elif o_ok is None:
        v = "ok" if clip_ok else "bad"
    elif clip_ok is None:
        v = "ok" if o_ok else "bad"
    elif clip_ok and (o_ok or o is None):
        v = "ok"       # CLIP 통과 + (Ollama 통과 또는 생략)
    elif clip_ok != o_ok:
        v = "doubt"
    else:
        v = "bad"
    return {"verdict": v, "clip": s, "ollama": (None if o is None else {"match": o["match"], "conf": o["conf"]}),
            "seen": (o or {}).get("seen", ""), "tools": tools_label(c)}


def _sig(path, query):
    p = Path(path)
    st = p.stat()
    return hashlib.sha1(f"{query}|{st.st_size}|{int(st.st_mtime)}".encode("utf-8")).hexdigest()[:12]


def _entries(item):
    return {e.get("scene"): e for e in (item.get("image_check") or []) if isinstance(e, dict)}


def _put(item, n, entry):
    d = _entries(item)
    old = d.get(n, {})
    entry = {**entry, "scene": n, "rejected_ids": old.get("rejected_ids", [])}
    d[n] = entry
    item["image_check"] = [d[k] for k in sorted(d)]


def _line(n, e):
    sc = "" if e.get("clip") is None else f" CLIP {e['clip']:.3f}"
    ol = ""
    if e.get("ollama"):
        ol = f" Ollama {'맞음' if e['ollama']['match'] else '다름'}({e['ollama']['conf']})"
    seen = f" - {e['seen']}" if e.get("seen") else ""
    return f"    scene_{n:02d}: [{LABEL[e['verdict']]}]{sc}{ol}{seen}"


def check_item(idx, item, folder, scenes=None, force=False):
    """소재의 장면 이미지를 검증해 item["image_check"]에 저장. 바뀐 게 없는 장면은 이전 결과를 재사용한다."""
    c = cfg()
    qs = list(item.get("image_queries") or [])
    old = _entries(item)
    todo = scenes or list(range(1, len(qs) + 1))
    for n in todo:
        f = folder / f"scene_{n:02d}.png"
        if not (1 <= n <= len(qs)) or not f.exists():
            continue
        sg = _sig(f, qs[n - 1])
        e0 = old.get(n)
        if not force and e0 and e0.get("sig") == sg and e0.get("tools") == tools_label(c) and e0.get("verdict") != "unknown":
            continue
        e = judge(f, qs[n - 1], c)
        e["sig"] = sg
        e["at"] = time.strftime("%Y-%m-%d %H:%M")
        _put(item, n, e)
        print(_line(n, e))
    return item.get("image_check") or []


# ---------------------------------------------------------------- 교체
def _credit(item, n):
    return next((x for x in (item.get("image_credits") or []) if x.get("scene") == n), None)


def _set_credit(item, folder, n, credit):
    merged = {x.get("scene"): x for x in (item.get("image_credits") or [])
              if (folder / f"scene_{int(x.get('scene', 0)):02d}.png").exists()}
    if credit:
        merged[n] = credit
    else:
        merged.pop(n, None)
    item["image_credits"] = [merged[k] for k in sorted(merged)]
    if merged:
        item["image_source"] = "pixabay" if any(x.get("source", "pixabay") == "pixabay" for x in merged.values()) else "commons"


def fix_item(session, key, idx, item, folder, scenes=None):
    """bad 판정 장면을 다른 사진으로 교체. 바뀐 장면 번호 목록을 돌려준다."""
    import fetch_images as F
    c = cfg()
    changed = []
    qs = list(item.get("image_queries") or [])
    for n, e in sorted(_entries(item).items()):
        if (scenes and n not in scenes) or e.get("verdict") != "bad" or not (1 <= n <= len(qs)):
            continue
        dest = folder / f"scene_{n:02d}.png"
        if not dest.exists():
            continue
        cur_c = _credit(item, n) or {}
        rej = {i for i in (e.get("rejected_ids") or [])}
        if cur_c.get("id") is not None:
            rej.add(cur_c["id"])
        best = {"rank": RANK["bad"], "clip": e.get("clip") if e.get("clip") is not None else -9,
                "bytes": dest.read_bytes(), "credit": copy.deepcopy(cur_c) or None, "entry": e, "cur": True}
        order = ["commons", "pixabay"] if cur_c.get("source", "pixabay") == "pixabay" else ["pixabay", "commons"]
        print(f"    scene_{n:02d}: 불일치 -> 다른 사진 찾는 중 (최대 {c['retry']}회)")
        for k in range(max(0, c["retry"])):
            src = order[k % 2]
            if src == "pixabay" and not key:
                src = "commons"
            try:
                ok = F.refetch_scene(session, key, idx, item, n, src) if not rej else _refetch_ex(F, session, key, idx, item, n, src, rej)
            except Exception as ex:
                print(f"    scene_{n:02d}: 교체 실패 ({type(ex).__name__}: {ex})")
                ok = False
            if not ok:
                continue
            ne = judge(dest, qs[n - 1], c)
            ne["sig"] = _sig(dest, qs[n - 1])
            ne["at"] = time.strftime("%Y-%m-%d %H:%M")
            nc = _credit(item, n) or {}
            if nc.get("id") is not None:
                rej.add(nc["id"])
            print(_line(n, ne) + "  (교체 후보)")
            sc = ne["clip"] if ne.get("clip") is not None else -1
            if (RANK[ne["verdict"]], sc) > (best["rank"], best["clip"]):
                best = {"rank": RANK[ne["verdict"]], "clip": sc, "bytes": dest.read_bytes(),
                        "credit": copy.deepcopy(nc) or None, "entry": ne, "cur": False}
            if ne["verdict"] == "ok":
                break
        # 마지막으로 받은 사진이 최선이 아니면 최선의 사진으로 되돌린다
        if dest.read_bytes() != best["bytes"]:
            dest.write_bytes(best["bytes"])
            _set_credit(item, folder, n, best["credit"])
        ent = {**best["entry"]}
        ent["sig"] = _sig(dest, qs[n - 1])
        _put(item, n, ent)
        item["image_check"] = [{**x, "rejected_ids": sorted(rej, key=str)} if x.get("scene") == n else x
                               for x in item["image_check"]]
        if not best["cur"]:
            changed.append(n)
            print(f"    scene_{n:02d}: 교체됨 -> [{LABEL[ent['verdict']]}]")
        else:
            print(f"    scene_{n:02d}: 더 나은 사진을 못 찾아 기존 사진 유지 -> 직접 교체 권장")
    return changed


def _refetch_ex(F, session, key, idx, item, n, src, rej):
    """refetch_scene은 현재 사진만 제외하므로, 이미 불일치였던 사진도 제외하도록 현재 크레딧 id 목록을 임시로 넓혀 호출"""
    orig = F.pick
    orig_c = F.commons.search

    def pick2(s, k, q, used):
        return orig(s, k, q, set(used) | rej)

    def com2(s, q, used=()):
        return orig_c(s, q, set(used) | rej)

    F.pick, F.commons.search = pick2, com2
    try:
        return F.refetch_scene(session, key, idx, item, n, src)
    finally:
        F.pick, F.commons.search = orig, orig_c


def check_and_fix(session, key, idx, item, scenes=None, fix=True, force=False):
    """fetch_images에서 새로 받은 직후 호출. 실패해도 예외를 밖으로 내지 않는다."""
    try:
        from common import visual_dir
        folder = visual_dir(BASE_DIR, idx, item)
        check_item(idx, item, folder, scenes, force)
        if fix and cfg()["retry"] > 0:
            return fix_item(session, key, idx, item, folder, scenes)
    except Exception as e:
        print(f"    [이미지검증] 건너뜀 ({type(e).__name__}: {e})")
    return []


def main():
    ap = argparse.ArgumentParser(description="장면 이미지가 검색어와 맞는지 검증(CLIP/Ollama)")
    ap.add_argument("--index", type=int, required=True)
    ap.add_argument("--scene", type=int, default=None, help="이 장면만")
    ap.add_argument("--fix", action="store_true", help="불일치 장면을 다른 사진으로 교체")
    ap.add_argument("--force", action="store_true", help="이전 결과가 있어도 다시 검증")
    a = ap.parse_args()
    from common import load_db, save_db, visual_dir
    db = load_db()
    if not (0 <= a.index < len(db)):
        raise SystemExit(f"--index {a.index} 범위 오류")
    item = db[a.index]
    folder = visual_dir(BASE_DIR, a.index, item)
    c = cfg()
    print(f"이미지 검증: {a.index:04d} {item.get('country', '')} (도구: {tools_label(c)}, CLIP 기준 {c['thr']})")
    if not item.get("image_queries"):
        raise SystemExit("이미지 검색어가 없습니다. 먼저 이미지를 받으세요.")
    scenes = [a.scene] if a.scene else None
    check_item(a.index, item, folder, scenes, a.force)
    save_db(db)
    changed = []
    if a.fix:
        key = os.environ.get("PIXABAY_API_KEY", "").strip()
        changed = fix_item(requests.Session(), key, a.index, item, folder, scenes)
        save_db(db)
    cnt = {}
    for e in item.get("image_check") or []:
        cnt[e["verdict"]] = cnt.get(e["verdict"], 0) + 1
    print("결과: " + " · ".join(f"{LABEL[k]} {v}" for k, v in cnt.items()) + (f" | 교체 {changed}" if changed else ""))
    if changed:
        print("영상에 반영하려면 redo에 번호를 넣고 5단계를 다시 하세요.")


if __name__ == "__main__":
    main()
