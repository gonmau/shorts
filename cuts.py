# -*- coding: utf-8 -*-
"""이미지 컷 관리: 컷 시트(이름·문장·검색어) / 후보 사진 받기 / 번호로 고르기 / 직접 올린 사진 적용.

컷 이름 = <소재번호>_<컷번호> (예: 117_03).  my_images/117_03.jpg (jpg/png/webp) 를 올리면 자동 검색보다 먼저 쓰입니다.
  python cuts.py --cands 117,118     소재별 후보 사진(Pixabay/Commons/Openverse)을 받아 cuts_out/ 에 컷 시트 + 후보 시트 생성
  python cuts.py --pick "117_3=2, 118_1=5"   후보 번호로 확정 -> my_images/ 에 저장 (후보를 만든 실행의 cuts_manifest 필요)
"""
import argparse
import io
import json
import os
import re
import shutil
import sys
import time
from pathlib import Path

import requests
from PIL import Image, ImageDraw

BASE = Path(__file__).resolve().parent
MY = BASE / "my_images"
MANIFEST = MY / "cuts_manifest.json"
CREDITS = MY / "credits.json"
OUT = BASE / "cuts_out"
HEAD = {"User-Agent": "culture-shorts-bot/1.0"}
EXT = (".jpg", ".jpeg", ".png", ".webp")


def _j(p, d):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:
        return d


def cut_name(idx, n):
    return f"{idx}_{n:02d}"


def _my_file(idx, n):
    for e in EXT:
        for nm in (f"{idx}_{n:02d}", f"{idx}_{n}"):
            p = MY / (nm + e)
            if p.exists():
                return p
    return None


def apply_my_images(db, idx):
    """my_images/<idx>_<n>.* 를 이 소재의 scene_NN.png 로 복사 (자동 검색보다 우선). db[idx] 의 사진 출처 표시도 갱신."""
    from common import visual_dir
    from scenes import item_scene_count
    item = db[idx]
    folder = visual_dir(BASE, idx, item)
    cr = _j(CREDITS, {})
    used = 0
    for n in range(1, item_scene_count(item) + 1):
        src = _my_file(idx, n)
        if not src:
            continue
        dest = folder / f"scene_{n:02d}.png"
        try:
            im = Image.open(src).convert("RGB")
            im.thumbnail((1920, 1920))
            dest.parent.mkdir(parents=True, exist_ok=True)
            im.save(dest, "PNG")
        except Exception as e:
            print(f"    내 사진 {src.name} 읽기 실패: {e}")
            continue
        c = dict(cr.get(src.stem) or cr.get(cut_name(idx, n)) or {"source": "user", "user": ""})
        c["scene"] = n
        creds = [x for x in (item.get("image_credits") or []) if x.get("scene") != n] + [c]
        item["image_credits"] = sorted(creds, key=lambda x: x.get("scene", 0))
        used += 1
    if used:
        print(f"    내 사진 {used}장 사용 (my_images)", flush=True)
    return used


def _chunks(text, k):
    s = [x.strip() for x in re.split(r"(?<=[.!?。])\s+", " ".join(str(text or "").split())) if x.strip()]
    if not s:
        return [""] * k
    out, per = [], len(s) / k
    for i in range(k):
        a, b = int(round(i * per)), max(int(round((i + 1) * per)), int(round(i * per)) + 1)
        out.append(" ".join(s[a:b]))
    return out


def cutsheet(db, members, recs=None):
    """컷 시트 텍스트/CSV: 컷 이름 · 대략 이 컷의 대본 · 검색어"""
    from scenes import item_scene_count
    recs = recs or {}
    L, rows = ["이미지 컷 시트 - 파일 이름을 '컷이름.jpg'로 해서 my_images 폴더에 올리면 그 컷에 우선 사용됩니다 (문장은 대략의 위치).", ""], [["컷", "나라", "대략 이 컷의 대본", "검색어"]]
    for i in members:
        it = db[i]
        k = item_scene_count(it)
        qs = it.get("image_queries") or []
        ch = _chunks((recs.get(i) or {}).get("narration") or it.get("narration"), k)
        L.append(f"■ [{i}] {it.get('country', '')}")
        for n in range(1, k + 1):
            q = qs[n - 1] if n - 1 < len(qs) else ""
            line = ch[n - 1]
            L.append(f"  {cut_name(i, n)}  |  {line[:70]}{'…' if len(line) > 70 else ''}  |  {q}")
            rows.append([cut_name(i, n), it.get("country", ""), line, q])
        L.append("")
    return "\n".join(L), rows


def _gather(session, idx, item, n, per_src=3):
    """한 컷의 후보: Pixabay + Commons + Openverse"""
    import commons
    import fetch_images as F
    import openverse
    qs = item.get("image_queries") or []
    q = qs[n - 1] if n - 1 < len(qs) else f"{item.get('country', '')} travel"
    cands, used = [], set()
    key = os.environ.get("PIXABAY_API_KEY", "").strip()
    if key:
        try:
            for h in F.search(session, key, q, 800):
                if h["id"] in used or not h.get("largeImageURL"):
                    continue
                used.add(h["id"])
                cands.append({"source": "pixabay", "id": h["id"], "thumb": h.get("webformatURL") or h["largeImageURL"], "url": h["largeImageURL"],
                              "user": h.get("user", ""), "page": h.get("pageURL", "")})
                if sum(1 for c in cands if c["source"] == "pixabay") >= per_src:
                    break
        except Exception as e:
            print(f"    {cut_name(idx, n)} Pixabay 실패: {type(e).__name__}", flush=True)
    cu = set()
    for _ in range(2):
        try:
            c = commons.search(session, q, cu)
        except Exception:
            c = None
        if not c:
            break
        cu.add(c["id"])
        cands.append({"source": "commons", "id": c["id"], "thumb": c["url"], "url": c["url"], "user": c["artist"], "license": c["license"],
                      "title": c["title"], "page": c["page"]})
        time.sleep(0.8)
    try:
        for o in openverse.search(session, q, set(), per_src):
            cands.append({"source": "openverse", "id": o["id"], "thumb": o["thumb"], "url": o["url"], "user": o["artist"],
                          "license": o["license"], "title": o["title"], "page": o["page"]})
    except Exception as e:
        print(f"    {cut_name(idx, n)} Openverse 실패: {type(e).__name__}", flush=True)
    return q, cands[:8]


def _thumb(session, c, w, h):
    r = session.get(c["thumb"], headers=HEAD, timeout=40)
    r.raise_for_status()
    im = Image.open(io.BytesIO(r.content)).convert("RGB")
    im.thumbnail((w, h))
    return im


def make_candidates(db, members):
    """소재별 후보 시트 -> cuts_out/cands_<idx>.jpg, 후보 정보 -> my_images/cuts_manifest.json (번호로 고를 때 사용)"""
    from scenes import item_scene_count
    OUT.mkdir(exist_ok=True)
    MY.mkdir(exist_ok=True)
    s = requests.Session()
    man = _j(MANIFEST, {})
    TW, TH, LAB = 240, 135, 26
    for i in members:
        it = db[i]
        k = item_scene_count(it)
        rows = []
        for n in range(1, k + 1):
            q, cands = _gather(s, i, it, n)
            man[cut_name(i, n)] = {"query": q, "cands": cands}
            tiles = []
            for c in cands:
                try:
                    tiles.append(_thumb(s, c, TW, TH))
                except Exception:
                    tiles.append(None)
            rows.append((n, q, tiles, cands))
            print(f"  {cut_name(i, n)}: 후보 {len(cands)}개 ({q})", flush=True)
        sh = Image.new("RGB", (8 * TW + 90, len(rows) * (TH + LAB) + 8), (22, 22, 28))
        d = ImageDraw.Draw(sh)
        for r_, (n, q, tiles, cands) in enumerate(rows):
            y = 4 + r_ * (TH + LAB)
            d.text((6, y + 4), cut_name(i, n), fill=(255, 226, 0))
            d.text((96, y + 4), q[:90], fill=(210, 210, 220))
            for c_, (t, c) in enumerate(zip(tiles, cands)):
                x = 90 + c_ * TW
                if t:
                    sh.paste(t, (x, y + LAB))
                d.rectangle((x, y + LAB, x + 22, y + LAB + 20), fill=(0, 0, 0))
                d.text((x + 6, y + LAB + 3), str(c_ + 1), fill=(255, 255, 255))
        sh.save(OUT / f"cands_{i}.jpg", quality=80)
    MANIFEST.write_text(json.dumps(man, ensure_ascii=False, indent=1), encoding="utf-8")


def pick(spec):
    """'117_3=2, 118_1=5' -> my_images/117_03.jpg 로 저장 (후보 번호는 후보 시트의 번호)"""
    man = _j(MANIFEST, {})
    cr = _j(CREDITS, {})
    s = requests.Session()
    ok = 0
    for part in re.split(r"[,\s]+", spec.strip()):
        m = re.fullmatch(r"(\d+)_(\d+)=(\d+)", part)
        if not m:
            if part:
                print(f"형식 오류: {part} (예: 117_3=2)")
            continue
        idx, n, k = int(m[1]), int(m[2]), int(m[3])
        e = man.get(cut_name(idx, n))
        if not e or not (1 <= k <= len(e["cands"])):
            print(f"{part}: 후보가 없습니다 (후보 보기를 먼저 실행하세요)")
            continue
        c = e["cands"][k - 1]
        try:
            r = s.get(c["url"], headers=HEAD, timeout=60)
            r.raise_for_status()
            im = Image.open(io.BytesIO(r.content)).convert("RGB")
            im.thumbnail((1920, 1920))
            MY.mkdir(exist_ok=True)
            for old in MY.glob(f"{idx}_{n:02d}.*"):
                old.unlink()
            im.save(MY / f"{cut_name(idx, n)}.jpg", quality=90)
            cr[cut_name(idx, n)] = {k_: v for k_, v in c.items() if k_ in ("source", "user", "license", "title", "page", "id")}
            ok += 1
            print(f"{part}: {c['source']} 후보 {k} 저장")
        except Exception as ex:
            print(f"{part}: 받기 실패 ({type(ex).__name__}: {ex})")
    CREDITS.write_text(json.dumps(cr, ensure_ascii=False, indent=1), encoding="utf-8")
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pick", default="")
    ap.add_argument("--cands", default="", help="후보 시트를 만들 소재 번호 (쉼표)")
    a = ap.parse_args()
    if a.pick:
        pick(a.pick)
    if a.cands:
        db = _j(BASE / "facts_db.json", [])
        make_candidates(db, [int(x) for x in a.cands.split(",") if x.strip()])


if __name__ == "__main__":
    main()
