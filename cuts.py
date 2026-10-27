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


def freeze(db, indexes):
    """지금 쓰는 장면 사진(visuals/…/scene_NN.png)을 my_images/<번호>_<NN>.png 로 복사하고 사진 출처도 credits.json 에 옮긴다.
    -> GitHub 에서 같은 사진으로 다시 만들 수 있다. 이미 my_images 에 있는 컷은 건드리지 않는다. -> (복사한 장수, 건너뜀 장수)"""
    from common import visual_dir
    from scenes import item_scene_count
    cr = _j(CREDITS, {})
    made = skipped = 0
    MY.mkdir(exist_ok=True)
    for idx in indexes:
        if not (0 <= idx < len(db)):
            continue
        item = db[idx]
        folder = visual_dir(BASE, idx, item)
        by_scene = {c.get("scene"): c for c in (item.get("image_credits") or []) if isinstance(c, dict)}
        for n in range(1, item_scene_count(item) + 1):
            src = folder / f"scene_{n:02d}.png"
            if not src.exists():
                continue
            if _my_file(idx, n):
                skipped += 1
                continue
            shutil.copy2(src, MY / (cut_name(idx, n) + ".png"))
            c = by_scene.get(n)
            if c and cut_name(idx, n) not in cr:
                cr[cut_name(idx, n)] = {k_: v_ for k_, v_ in c.items() if k_ != "scene"}
            made += 1
    CREDITS.write_text(json.dumps(cr, ensure_ascii=False, indent=1), encoding="utf-8")
    return made, skipped


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


# ---- 내 사진 출처 입력 (UI 표 <-> credits.json)
KINDS = ["미입력", "내가 직접 촬영/제작", "CC0 · 퍼블릭 도메인", "CC BY", "Pixabay", "기타(라이선스 직접 입력)", "자동 수집 출처(그대로 둠)"]
GUIDE = {
    "내가 직접 촬영/제작": "표기 필요 없음",
    "CC0 · 퍼블릭 도메인": "표기 필요 없음 (작가·링크를 적으면 참고용으로만 기록)",
    "CC BY": "작가 + 원본 링크 필수 (제목 권장). 설명란에 라이선스와 '자르기/확대' 변경 표기까지 자동으로 들어갑니다",
    "Pixabay": "설명란에 'Photos: Pixabay' 한 줄 (작가·링크는 선택)",
    "기타(라이선스 직접 입력)": "라이선스 이름 + 작가 + 원본 링크 필수. NC / ND 는 영상에 쓰기 위험하니 비권장 (SA 는 출처 표기)",
}


def kind_of(c):
    if not c:
        return "미입력"
    src, lic = c.get("source"), str(c.get("license") or "")
    if src in ("commons", "openverse"):
        return "자동 수집 출처(그대로 둠)"
    if src == "own":
        return "내가 직접 촬영/제작"
    if src == "pixabay":
        return "Pixabay"
    if lic.upper().startswith("CC0") or "public domain" in lic.lower():
        return "CC0 · 퍼블릭 도메인"
    if lic.upper().replace("-", " ").strip() == "CC BY":
        return "CC BY"
    return "기타(라이선스 직접 입력)" if lic else "미입력"


def credit_problems(kind, lic="", user="", page=""):
    if kind == "CC BY" and not (user and page):
        return "작가와 원본 링크를 적어 주세요"
    if kind.startswith("기타") and not (lic and user and page):
        return "라이선스·작가·원본 링크를 적어 주세요"
    if kind.startswith("기타") and re.search(r"\b(nc|nd)\b|non.?commercial|no.?deriv", lic, re.I):
        return "NC/ND 라이선스는 영상에 쓰기 위험합니다 (SA는 출처 표기로 사용)"
    if kind == "미입력":
        return "출처를 입력하세요 (직접 촬영이면 '내가 직접 촬영/제작')"
    return ""


def credit_from_row(kind, lic="", user="", title="", page="", old=None):
    user, title, page, lic = (str(x or "").strip() for x in (user, title, page, lic))
    if kind.startswith("자동"):
        return old
    if kind == "내가 직접 촬영/제작":
        return {"source": "own"}
    if kind.startswith("CC0"):
        return {"source": "user", "license": "CC0", "user": user, "title": title, "page": page}
    if kind == "CC BY":
        return {"source": "user", "license": "CC BY", "user": user, "title": title, "page": page}
    if kind == "Pixabay":
        return {"source": "pixabay", "user": user, "page": page}
    if kind.startswith("기타"):
        return {"source": "user", "license": lic, "user": user, "title": title, "page": page}
    return None


def save_credits(rows):
    """rows: [{파일(컷이름), 출처 구분, 라이선스, 작가, 제목, 원본 링크}] -> credits.json 갱신"""
    cr = _j(CREDITS, {})
    for r in rows:
        k = r["파일"]
        c = credit_from_row(r.get("출처 구분") or "미입력", r.get("라이선스"), r.get("작가"), r.get("제목"), r.get("원본 링크"), cr.get(k))
        if c:
            cr[k] = c
        else:
            cr.pop(k, None)
    MY.mkdir(exist_ok=True)
    CREDITS.write_text(json.dumps(cr, ensure_ascii=False, indent=1), encoding="utf-8")


_LIC_RE = re.compile(r"(CC0(?:\s*1\.0)?|Public\s*domain|No restrictions|CC[\s-]*BY(?:[\s-]*(?:SA|NC|ND))*(?:[\s-]*\d\.\d)?)", re.I)


def parse_credit_text(txt, link=""):
    """'Pete Verdon, Public domain, via Wikimedia Commons' 같은 한 줄 -> {"license","user","title","page"} (못 읽으면 None)"""
    t = re.sub(r",?\s*via\s+Wikimedia\s+Commons\s*$", "", str(txt or "").strip(), flags=re.I).strip(" ,")
    if not t:
        return None
    ms = list(_LIC_RE.finditer(t))
    if not ms:
        return None
    m = ms[-1]
    lic = re.sub(r"\s+", " ", m.group(1)).strip().upper().replace("PUBLIC DOMAIN", "Public domain").replace("NO RESTRICTIONS", "No restrictions")
    lic = re.sub(r"CC[\s-]*BY", "CC BY", lic).replace("CC BY SA", "CC BY-SA").replace("CC BY NC", "CC BY-NC").replace("CC BY ND", "CC BY-ND")
    user = t[:ms[0].start()].strip(" ,") or t[:m.start()].strip(" ,")
    user = re.sub(r",?\s*Wikimedia Commons\s*$", "", user, flags=re.I).strip(" ,")
    page = str(link or "").strip()
    title = ""
    mm = re.search(r"/wiki/File:([^?#]+)", page)
    if mm:
        from urllib.parse import unquote
        title = re.sub(r"\.[A-Za-z]{3,4}$", "", unquote(mm.group(1))).replace("_", " ")[:90]
    return {"source": "user", "license": lic, "user": user, "title": title, "page": page}


def parse_paste(text):
    """탭/여러 칸 공백으로 나눈 '컷 / 저작권 / 원본링크' 표 붙여넣기 -> (credits dict, 건너뜀/주의 목록)"""
    out, notes = {}, []
    for line in str(text or "").splitlines():
        if not line.strip() or line.lower().startswith("컷"):
            continue
        parts = [x.strip() for x in re.split(r"\t+|\s{2,}", line.strip())]
        m = re.fullmatch(r"(\d+)_(\d+)", parts[0]) if parts else None
        if not m:
            notes.append(f"{parts[0] if parts else line[:20]}: 컷 이름 형식이 아님 (예: 40_01)")
            continue
        name = f"{int(m.group(1))}_{int(m.group(2)):02d}"
        rest = parts[1:]
        link = next((x for x in rest if x.startswith("http")), "")
        cred = next((x for x in rest if not x.startswith("http")), "")
        if not cred:
            notes.append(f"{name}: 출처가 비어 있음")
            continue
        c = parse_credit_text(cred, link)
        if not c:
            notes.append(f"{name}: 라이선스를 못 읽음 ('{cred[:40]}')")
            continue
        if "/wiki/File:" not in link:
            notes.append(f"{name}: 원본 링크가 파일 페이지가 아님 (검색 페이지) - 파일 페이지 주소로 바꾸면 좋음")
        if re.search(r"NC|ND", c["license"]):
            notes.append(f"{name}: {c['license']} 는 영상에 쓰기 위험")
        out[name] = c
    return out, notes


def save_pasted(text):
    """붙여넣은 표를 credits.json 에 병합 저장 -> (저장 개수, 주의 목록)"""
    got, notes = parse_paste(text)
    cr = _j(CREDITS, {})
    cr.update(got)
    MY.mkdir(exist_ok=True)
    CREDITS.write_text(json.dumps(cr, ensure_ascii=False, indent=1), encoding="utf-8")
    return len(got), notes


def _blob_sha(path):
    import hashlib
    d = Path(path).read_bytes()
    return hashlib.sha1(b"blob %d\0" % len(d) + d).hexdigest()


def sync_down(repo, branch="main"):
    """GitHub my_images/ -> 이 PC my_images/ (없거나 다른 파일만 받음. credits.json 은 합침, PC 것이 우선)"""
    import base64
    tok = os.environ.get("GITHUB_TOKEN", "").strip()
    h = {"Accept": "application/vnd.github+json", **({"Authorization": f"Bearer {tok}"} if tok else {})}
    r = requests.get(f"https://api.github.com/repos/{repo}/contents/my_images", params={"ref": branch}, headers=h, timeout=60)
    if r.status_code == 404:
        return 0, 0
    r.raise_for_status()
    MY.mkdir(exist_ok=True)
    got = same = 0
    for f in r.json():
        if f.get("type") != "file":
            continue
        dst = MY / f["name"]
        if dst.exists() and f["name"] != "credits.json" and _blob_sha(dst) == f.get("sha"):
            same += 1
            continue
        rr = requests.get(f["url"], params={"ref": branch}, headers=h, timeout=120)
        rr.raise_for_status()
        data = base64.b64decode(rr.json().get("content") or "")
        if f["name"] == "credits.json":
            merged = {**json.loads(data.decode("utf-8") or "{}"), **_j(CREDITS, {})}
            CREDITS.write_text(json.dumps(merged, ensure_ascii=False, indent=1), encoding="utf-8")
        elif f["name"] == "cuts_manifest.json" and dst.exists():
            merged = {**_j(dst, {}), **json.loads(data.decode("utf-8") or "{}")}   # 후보 정보는 GitHub(최근 실행) 것이 우선
            dst.write_text(json.dumps(merged, ensure_ascii=False, indent=1), encoding="utf-8")
        else:
            dst.write_bytes(data)
        got += 1
    return got, same


def sync_up(repo, branch="main"):
    """이 PC my_images/ -> GitHub (같은 파일은 건너뜀). GITHUB_TOKEN 필요"""
    from gh_push import push_file
    tok = os.environ.get("GITHUB_TOKEN", "").strip()
    if not tok:
        raise SystemExit("GITHUB_TOKEN 환경변수가 없습니다.")
    n = 0
    for f in sorted(MY.glob("*")):
        if f.is_file() and (f.suffix.lower() in EXT or f.name in ("credits.json", "cuts_manifest.json")):
            if push_file(repo, branch, tok, "my_images/" + f.name, f"my_images: {f.name}") == "pushed":
                n += 1
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--shorts", action="store_true", help="쇼츠: 대본이 끝나고 아직 영상이 없는 소재의 컷 시트+후보 시트를 만든다 (--limit/--start)")
    ap.add_argument("--limit", type=int, default=2)
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--sync", choices=["down", "up"], default="")
    ap.add_argument("--repo", default="")
    ap.add_argument("--pick", default="")
    ap.add_argument("--freeze", default="", help="소재 번호(예: 40,47,71-73)의 현재 장면 사진을 my_images 로 복사 (GitHub 에서 같은 사진으로 다시 만들 때)")
    ap.add_argument("--paste", default="", help="컷/저작권/원본링크 표(텍스트 파일)를 읽어 my_images/credits.json 에 저장")
    ap.add_argument("--cands", default="", help="후보 시트를 만들 소재 번호 (쉼표)")
    a = ap.parse_args()
    if a.sync:
        if not a.repo:
            sys.exit("--repo 가 필요합니다")
        if a.sync == "down":
            g, sm = sync_down(a.repo)
            print(f"GitHub에서 my_images {g}개 받음 (같은 파일 {sm}개)")
        else:
            print(f"GitHub로 my_images {sync_up(a.repo)}개 올림")
        return
    if a.freeze:
        from build_longform import parse_indexes as _pi
        db_ = _j(BASE / "facts_db.json", [])
        m_, sk_ = freeze(db_, _pi(a.freeze))
        print(f"현재 사진 {m_}장을 my_images 로 복사 (이미 있던 {sk_}장은 그대로)")
        return
    if a.paste:
        n_, notes_ = save_pasted(Path(a.paste).read_text(encoding="utf-8"))
        print(f"출처 {n_}개 저장")
        for x in notes_:
            print("  확인 필요:", x)
        return
    if a.pick:
        pick(a.pick)
    if a.shorts:
        from common import pending_render
        db = _j(BASE / "facts_db.json", [])
        mem = [i for i, _ in pending_render(db, a.start)][:a.limit]
        if not mem:
            sys.exit("대본이 끝난 소재가 없습니다.")
        OUT.mkdir(exist_ok=True)
        txt, rows = cutsheet(db, mem)
        (OUT / "cutsheet.txt").write_text(txt, encoding="utf-8")
        import csv
        with open(OUT / "cutsheet.csv", "w", encoding="utf-8-sig", newline="") as f_:
            csv.writer(f_).writerows(rows)
        make_candidates(db, mem)
    if a.cands:
        db = _j(BASE / "facts_db.json", [])
        make_candidates(db, [int(x) for x in a.cands.split(",") if x.strip()])


if __name__ == "__main__":
    main()
