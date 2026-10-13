# -*- coding: utf-8 -*-
"""소재마다 장면 이미지 6장을 Pixabay(무료 API)에서 내려받아 visuals/<번호_국가>/scene_01~06.png 로 저장.

- 검색어는 generate_script.py가 만든 item["image_queries"] (영어 6개)를 씁니다.
- 검색 결과가 없는 장면은 저장하지 않고 건너뜁니다 -> build_video가 그 장면만 대체 카드로 채움.
- API 키가 없으면 아무것도 하지 않고 정상 종료합니다. (전부 대체 카드로 제작)

환경변수: PIXABAY_API_KEY  (https://pixabay.com/api/docs/ 에서 로그인하면 키가 보임)
"""
import argparse
import io
import os
import time
from pathlib import Path

import requests
from PIL import Image

from common import load_db, save_db, pending_render, visual_dir

BASE_DIR = Path(__file__).resolve().parent
API_URL = "https://pixabay.com/api/"
SCENE_COUNT = 6
HEADERS = {"User-Agent": "culture-shorts-bot/1.0"}


def search(session, key, query, min_size):
    params = {
        "key": key,
        "q": query[:100],
        "image_type": "photo",
        "safesearch": "true",
        "per_page": 20,
        "order": "popular",
    }
    if min_size:
        params["min_width"] = params["min_height"] = min_size
    r = session.get(API_URL, params=params, headers=HEADERS, timeout=30)
    if r.status_code == 429:
        time.sleep(30)
        r = session.get(API_URL, params=params, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.json().get("hits", [])


def pick(session, key, query, used):
    """검색어 -> 아직 안 쓴 사진 1장 (hit). 결과가 없으면 검색어를 줄여서 다시 시도."""
    words = query.split()
    attempts = [(query, 800), (query, 0)]
    if len(words) > 2:
        attempts.append((" ".join(words[:2]), 0))
    for q, min_size in attempts:
        for hit in search(session, key, q, min_size):
            if hit["id"] not in used and hit.get("largeImageURL"):
                return hit
        time.sleep(0.7)
    return None


def download(session, url, dest):
    r = session.get(url, headers=HEADERS, timeout=60)
    r.raise_for_status()
    im = Image.open(io.BytesIO(r.content)).convert("RGB")
    if min(im.size) < 400:
        raise RuntimeError(f"이미지가 너무 작음: {im.size}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    im.save(dest, "PNG")


def fetch_item(session, key, idx, item, force):
    folder = visual_dir(BASE_DIR, idx, item)
    queries = item.get("image_queries") or []
    if len(queries) < SCENE_COUNT:
        country = str(item.get("country", "")).strip()
        base = queries[0] if queries else f"{country} travel"
        queries = (queries + [base] * SCENE_COUNT)[:SCENE_COUNT]

    # 검색어가 바뀌었으면(대본 수정 등) 예전 이미지를 지우고 새로 받는다
    done = item.get("image_queries_done")
    if done is not None and done != queries:
        force = True
        print("    이미지 검색어가 바뀌어 새로 받습니다")
    used, credits, got = set(), [], 0
    for n, query in enumerate(queries, start=1):
        dest = folder / f"scene_{n:02d}.png"
        if dest.exists() and not force:
            got += 1
            continue
        try:
            hit = pick(session, key, query, used)
            if not hit:
                print(f"    scene_{n:02d}: 결과 없음 ({query}) -> 대체 카드")
                continue
            used.add(hit["id"])
            download(session, hit["largeImageURL"], dest)
            credits.append({"scene": n, "user": hit.get("user", ""), "page": hit.get("pageURL", "")})
            got += 1
            print(f"    scene_{n:02d}: {query} -> {hit['id']}")
        except Exception as e:  # 한 장 실패해도 나머지는 계속
            print(f"    scene_{n:02d}: 실패 ({type(e).__name__}: {e}) -> 대체 카드")
        time.sleep(0.7)

    item["image_queries_done"] = list(queries)
    if credits:
        item["image_source"] = "pixabay"
        item["image_credits"] = credits
    return got


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=5)
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--force", action="store_true", help="이미 받은 이미지도 다시 받기")
    args = ap.parse_args()

    key = os.environ.get("PIXABAY_API_KEY", "").strip()
    if not key:
        print("PIXABAY_API_KEY가 없어 이미지 다운로드를 건너뜁니다. (대체 카드로 영상 제작)")
        return

    db = load_db()
    targets = []
    for idx, item in pending_render(db, args.start):
        ap_ = item.get("audio_path_v2")
        if item.get("status_tts_v2") == "done" and ap_ and Path(ap_).exists():
            targets.append((idx, item))
        if len(targets) >= args.limit:
            break

    print(f"이미지 다운로드 대상: {len(targets)}개")
    session = requests.Session()
    for n, (idx, item) in enumerate(targets, start=1):
        print(f"[{n}/{len(targets)}] {idx:04d} {item.get('country', '')}")
        try:
            got = fetch_item(session, key, idx, item, args.force)
            print(f"  완료: {got}/{SCENE_COUNT}장")
            save_db(db)
        except Exception as e:
            print(f"  실패: {type(e).__name__}: {e} (대체 카드로 제작)")


if __name__ == "__main__":
    main()
