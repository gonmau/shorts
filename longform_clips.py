# -*- coding: utf-8 -*-
"""롱폼용 스톡 영상(B-roll) 검색/다운로드. Pexels(PEXELS_API_KEY) 와 Pixabay 영상(PIXABAY_API_KEY)에서 받는다. (선택 기능)

- 소재마다 검색어 몇 개로 5~40초짜리 가로 영상을 받아 clips/<번호_이름>/clip_N.mp4 에 둔다 (720p 안팎으로 받아 용량을 줄임).
- 영상 한가운데 한 프레임을 뽑아 이미지 검증(CLIP/Ollama)이 켜져 있으면 검색어와 맞는지 확인하고, 안 맞으면 다음 후보를 쓴다.
  검증 도구가 없으면 검색어와 태그/주소 단어가 가장 많이 겹치는 영상을 쓴다.
- 영상을 못 받아도 롱폼은 사진으로 계속 만든다. 라이선스: Pexels/Pixabay 모두 상업적 이용 가능, 출처 표기 의무 없음(설명란에 출처는 적어 둠).
환경변수: PEXELS_API_KEY (무료), PIXABAY_API_KEY, LF_BROLL_CHECK=0 (프레임 검증 끄기)
"""
import os
import re
import shutil
import subprocess
from pathlib import Path

import requests

BASE = Path(__file__).resolve().parent
CLIPS = BASE / "clips"
UA = {"User-Agent": "culture-shorts-bot/1.0"}
MAX_BYTES = 90 * 1024 * 1024


def keys():
    return os.environ.get("PEXELS_API_KEY", "").strip(), os.environ.get("PIXABAY_API_KEY", "").strip()


def available():
    return any(keys())


def _words(q):
    return {w for w in re.findall(r"[a-z0-9]+", str(q).lower()) if len(w) >= 3}


def search(query, per=10):
    """-> [dict(source, id, url, dur, w, h, user, page, text)] (후보)"""
    pex, pix = keys()
    out = []
    if pex:
        try:
            r = requests.get("https://api.pexels.com/videos/search", params={"query": query, "per_page": per, "orientation": "landscape"},
                             headers={"Authorization": pex, **UA}, timeout=30)
            r.raise_for_status()
            for v in r.json().get("videos", []):
                files = [f for f in v.get("video_files", []) if str(f.get("file_type", "")).endswith("mp4") and 800 <= int(f.get("width") or 0) <= 1920]
                if not files:
                    continue
                f = min(files, key=lambda f: abs(int(f.get("width") or 0) - 1280))
                out.append({"source": "pexels", "id": f"pexels{v['id']}", "url": f["link"], "dur": float(v.get("duration") or 0),
                            "w": int(f.get("width") or 0), "h": int(f.get("height") or 0), "user": (v.get("user") or {}).get("name", ""),
                            "page": v.get("url", ""), "text": v.get("url", "").replace("-", " ")})
        except Exception as e:
            print(f"    [스톡영상] Pexels 검색 실패 ({type(e).__name__}: {str(e)[:80]})", flush=True)
    if pix:
        try:
            r = requests.get("https://pixabay.com/api/videos/", params={"key": pix, "q": query[:100], "per_page": min(per, 20), "safesearch": "true"},
                             headers=UA, timeout=30)
            r.raise_for_status()
            for h in r.json().get("hits", []):
                vs = h.get("videos") or {}
                v = next((vs[k] for k in ("medium", "large", "small") if (vs.get(k) or {}).get("url")), None)
                if not v:
                    continue
                out.append({"source": "pixabay", "id": f"pixabay{h['id']}", "url": v["url"], "dur": float(h.get("duration") or 0),
                            "w": int(v.get("width") or 0), "h": int(v.get("height") or 0), "user": h.get("user", ""),
                            "page": h.get("pageURL", ""), "text": h.get("tags", "")})
        except Exception as e:
            print(f"    [스톡영상] Pixabay 검색 실패 ({type(e).__name__}: {str(e)[:80]})", flush=True)
    qw = _words(query)
    for c in out:
        c["score"] = len(qw & _words(c["text"]))
    # 길이 5~40초, 가로 영상 우선 -> 단어 겹침 -> 출처(Pexels 우선)
    ok = [c for c in out if 4 <= c["dur"] <= 45 and c["w"] >= c["h"]]
    return sorted(ok, key=lambda c: (-c["score"], c["source"] != "pexels"))


def _ffmpeg():
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


def frame_png(video, png, at=None):
    exe = _ffmpeg()
    if not exe:
        return False
    cmd = [exe, "-y", "-loglevel", "error", "-ss", str(at if at is not None else 2), "-i", str(video), "-frames:v", "1", str(png)]
    return subprocess.run(cmd).returncode == 0 and Path(png).exists()


def download(url, dest):
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    n = 0
    with requests.get(url, headers=UA, stream=True, timeout=60) as r:
        r.raise_for_status()
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                n += len(chunk)
                if n > MAX_BYTES:
                    raise RuntimeError("영상이 너무 큼")
                f.write(chunk)
    tmp.replace(dest)


def check_match(video, query):
    """영상 한 프레임이 검색어와 맞는지. -> (통과 여부, 설명)"""
    if os.environ.get("LF_BROLL_CHECK", "1") == "0":
        return True, "검증 안 함"
    try:
        import image_check as IC
        png = Path(video).with_suffix(".check.png")
        if not frame_png(video, png):
            return True, "프레임 추출 실패"
        j = IC.judge(png, query)
        try:
            png.unlink()
        except Exception:
            pass
        return j["verdict"] != "bad", j["verdict"]
    except Exception as e:
        return True, f"검증 불가({type(e).__name__})"


def fetch_query(query, dest, used):
    """검색어 하나 -> 영상 1개 다운로드. 성공하면 크레딧 dict, 아니면 None"""
    for c in search(query)[:6]:
        if c["id"] in used:
            continue
        try:
            download(c["url"], dest)
        except Exception as e:
            print(f"    [스톡영상] 다운로드 실패 {c['id']} ({type(e).__name__})", flush=True)
            continue
        ok, why = check_match(dest, query)
        if ok:
            used.add(c["id"])
            return {"query": query, "path": str(dest), "source": c["source"], "user": c["user"], "page": c["page"], "id": c["id"], "check": why}
        print(f"    [스톡영상] '{query}' 후보 {c['id']} 불일치({why}) -> 다음 후보", flush=True)
        try:
            Path(dest).unlink()
        except Exception:
            pass
    return None


def fetch_for(idx, item, queries, old=None, max_clips=3):
    """소재 하나의 영상들. old(이전 결과)에서 같은 검색어+파일이 있으면 재사용. -> credit dict 목록"""
    import common
    folder = CLIPS / f"{idx:04d}_{common.safe_dirname(common.safe_country(item))}"
    old_by_q = {c.get("query"): c for c in (old or []) if c.get("path") and Path(c["path"]).exists()}
    res, used = [], set()
    for k, q in enumerate([x for x in queries if str(x).strip()][:max_clips], 1):
        if q in old_by_q:
            res.append(old_by_q[q])
            used.add(old_by_q[q].get("id"))
            continue
        got = fetch_query(q, folder / f"clip_{k:02d}.mp4", used)
        if got:
            res.append(got)
            print(f"    [스톡영상] {idx} '{q}' -> {got['source']}", flush=True)
        else:
            print(f"    [스톡영상] {idx} '{q}' 쓸 만한 영상을 못 찾음 (사진 사용)", flush=True)
    return res


def credit_lines(recs):
    src = {c.get("source") for r in recs for c in (r.get("clips") or [])}
    lines = []
    if "pexels" in src:
        lines.append("Stock videos: Pexels (pexels.com)")
    if "pixabay" in src:
        lines.append("Stock videos: Pixabay (pixabay.com)")
    return lines
