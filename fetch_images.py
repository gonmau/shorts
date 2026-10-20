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

import re

import requests
from PIL import Image

import commons

from common import load_db, save_db, pending_render, visual_dir

BASE_DIR = Path(__file__).resolve().parent
API_URL = "https://pixabay.com/api/"
SCENE_COUNT = 6
IMAGE_TYPE = "photo"  # Pixabay image_type: photo / illustration / vector (--scene 단독 실행에서만 바뀜)
HEADERS = {"User-Agent": "culture-shorts-bot/1.0"}


def search(session, key, query, min_size):
    params = {
        "key": key,
        "q": query[:100],
        "image_type": IMAGE_TYPE,
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


STOP = {"the", "and", "with", "for", "from", "near", "view", "traditional"}


def _words(q):
    return [w for w in re.findall(r"[a-z0-9]+", q.lower()) if len(w) >= 3 and w not in STOP]


def _score(hit, qwords):
    tags = set(re.findall(r"[a-z0-9]+", str(hit.get("tags", "")).lower()))
    return sum(1 for w in qwords if w in tags)


def pick(session, key, query, used):
    """검색어 -> (사진, 주제와 맞는지). Pixabay 태그가 검색어 단어와 충분히 겹치면 '맞는' 사진.
    맞는 사진이 없으면 가장 비슷한 사진을 돌려주되 맞지 않는다고 표시한다(Commons를 먼저 시도하게)."""
    words = query.split()
    qw = _words(query)
    need = min(2, len(qw)) or 1
    attempts = [(query, 800), (query, 0)]
    if len(words) > 2:
        attempts.append((" ".join(words[:2]), 0))
    best, best_score = None, -1
    for q, min_size in attempts:
        for hit in search(session, key, q, min_size):
            if hit["id"] in used or not hit.get("largeImageURL"):
                continue
            sc = _score(hit, qw)
            if sc >= need:
                return hit, True
            if sc > best_score:
                best, best_score = hit, sc
        time.sleep(0.7)
    return best, False


def download(session, url, dest, headers=None):
    r = session.get(url, headers=headers or HEADERS, timeout=60)
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

    # 검색어가 바뀐 장면만(대본 수정 등) 예전 이미지를 지우고 새로 받는다. 안 바뀐 장면은 그대로 둔다
    done = item.get("image_queries_done")
    changed_scenes = set()
    if done is not None and list(done) != list(queries):
        changed_scenes = {n for n, q in enumerate(queries, start=1) if n > len(done) or done[n - 1] != q}
        print(f"    이미지 검색어가 바뀐 장면만 새로 받습니다: {sorted(changed_scenes)}")
    anchor = " ".join(str(item.get("verify_note") or "").split()[:3])
    old = {} if force else {c.get("scene"): c for c in (item.get("image_credits") or [])}
    new_credits, used, got = {}, set(), 0
    for n, query in enumerate(queries, start=1):
        dest = folder / f"scene_{n:02d}.png"
        redo_scene = force or n in changed_scenes
        if dest.exists() and not redo_scene:
            got += 1
            continue
        if dest.exists():
            dest.unlink()  # 검색어가 바뀐 경우 예전 사진이 남지 않게 한다
        try:
            hit, relevant = pick(session, key, query, used)
            credit = None
            if hit and relevant:  # 1순위: Pixabay에서 주제와 맞는 사진
                used.add(hit["id"])
                download(session, hit["largeImageURL"], dest)
                credit = {"scene": n, "source": "pixabay", "user": hit.get("user", ""), "page": hit.get("pageURL", ""), "id": hit["id"]}
            else:  # 2순위: Wikimedia Commons (CC0/퍼블릭도메인/CC BY만)
                c = None
                for q in (query, anchor):
                    if not q:
                        continue
                    try:
                        c = commons.search(session, q, used)
                    except Exception as e:
                        print(f"    scene_{n:02d}: Commons 검색 실패 ({type(e).__name__}) -> Pixabay로 대체")
                        c = None
                    if c:
                        break
                    time.sleep(1.0)
                if c:
                    used.add(c["id"])
                    download(session, c["url"], dest, {"User-Agent": commons.UA})
                    credit = {"scene": n, "source": "commons", "user": c["artist"], "license": c["license"],
                              "title": c["title"], "page": c["page"], "id": c["id"]}
                elif hit:  # 3순위: 주제와 덜 맞아도 Pixabay에서 가장 비슷한 사진
                    used.add(hit["id"])
                    download(session, hit["largeImageURL"], dest)
                    credit = {"scene": n, "source": "pixabay", "user": hit.get("user", ""), "page": hit.get("pageURL", ""), "id": hit["id"]}
                else:
                    print(f"    scene_{n:02d}: 결과 없음 ({query}) -> 대체 카드")
                    continue
            new_credits[n] = credit
            got += 1
            print(f"    scene_{n:02d}: {query} -> {credit['source']}" + (f" ({credit['license']})" if credit.get("license") else ""))
        except Exception as e:  # 한 장 실패해도 나머지는 계속
            print(f"    scene_{n:02d}: 실패 ({type(e).__name__}: {e}) -> 대체 카드")
        time.sleep(0.7)

    item["image_queries_done"] = list(queries)
    merged = {**{k: v for k, v in old.items() if k not in changed_scenes and (folder / f"scene_{int(k):02d}.png").exists()}, **new_credits}
    if merged:
        item["image_credits"] = [merged[k] for k in sorted(merged)]
        item["image_source"] = "pixabay" if any(c.get("source", "pixabay") == "pixabay" for c in merged.values()) else "commons"
    return got


def refetch_scene(session, key, idx, item, n, source):
    """한 장면만 지정한 출처(pixabay / commons)에서 다시 받는다. 현재 사진은 제외하고 다른 사진을 고른다.
    실패하면 기존 사진을 그대로 둔다. 성공하면 True"""
    folder = visual_dir(BASE_DIR, idx, item)
    queries = item.get("image_queries") or []
    if not (1 <= n <= len(queries)):
        print(f"장면 {n}: 이미지 검색어가 없습니다.")
        return False
    query = queries[n - 1]
    dest = folder / f"scene_{n:02d}.png"
    cur = next((c for c in (item.get("image_credits") or []) if c.get("scene") == n), {})
    used = {cur["id"]} if cur.get("id") else set()
    if source == "commons":
        anchor = " ".join(str(item.get("verify_note") or "").split()[:3])
        c = None
        for q in (query, anchor):
            if not q:
                continue
            c = commons.search(session, q, used)
            if c:
                break
            time.sleep(1.0)
        if not c:
            print(f"장면 {n}: Commons에서 쓸 수 있는 사진(CC0/퍼블릭도메인/CC BY)을 못 찾았습니다 ({query}). 기존 사진 유지")
            return False
        download(session, c["url"], dest, {"User-Agent": commons.UA})
        credit = {"scene": n, "source": "commons", "user": c["artist"], "license": c["license"],
                  "title": c["title"], "page": c["page"], "id": c["id"]}
    else:
        hit, _ = pick(session, key, query, used)
        if not hit:
            print(f"장면 {n}: Pixabay에서 사진을 못 찾았습니다 ({query}). 기존 사진 유지")
            return False
        download(session, hit["largeImageURL"], dest)
        credit = {"scene": n, "source": "pixabay", "user": hit.get("user", ""), "page": hit.get("pageURL", ""), "id": hit["id"], "type": IMAGE_TYPE}
    merged = {c_.get("scene"): c_ for c_ in (item.get("image_credits") or []) if (folder / f"scene_{int(c_.get('scene', 0)):02d}.png").exists()}
    merged[n] = credit
    item["image_credits"] = [merged[k] for k in sorted(merged)]
    item["image_source"] = "pixabay" if any(c_.get("source", "pixabay") == "pixabay" for c_ in merged.values()) else "commons"
    print(f"장면 {n}: {source}" + (f"({IMAGE_TYPE})" if source == "pixabay" else "") + "에서 새로 받음" + (f" ({credit['license']}, {credit['user']})" if source == "commons" else ""))
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=5)
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--force", action="store_true", help="이미 받은 이미지도 다시 받기")
    ap.add_argument("--index", type=int, default=None, help="이 번호 소재 하나만 처리 (상태와 상관없이. 롱폼 합치기용)")
    ap.add_argument("--scene", type=int, default=None, help="--index 와 함께: 이 장면 하나만 다시 받기")
    ap.add_argument("--type", dest="img_type", choices=["photo", "illustration", "vector"], default="photo", help="--source pixabay 일 때 이미지 종류")
    ap.add_argument("--source", choices=["pixabay", "commons"], default="pixabay", help="--scene 과 함께: 받을 출처")
    ap.add_argument("--any", action="store_true", help="음성이 아직 없어도 대본이 끝난 소재의 이미지를 받음 (이미지를 먼저 확인할 때)")
    args = ap.parse_args()

    key = os.environ.get("PIXABAY_API_KEY", "").strip()
    if not key and not (args.scene is not None and args.source == "commons"):
        print("PIXABAY_API_KEY가 없어 이미지 다운로드를 건너뜁니다. (대체 카드로 영상 제작)")
        return

    db = load_db()
    targets = []
    if args.index is not None:
        if not (0 <= args.index < len(db)):
            raise SystemExit(f"--index {args.index} 범위 오류")
        targets = [(args.index, db[args.index])]
    else:
        for idx, item in pending_render(db, args.start):
            ap_ = item.get("audio_path_v2")
            if args.any or (item.get("status_tts_v2") == "done" and ap_ and Path(ap_).exists()):
                targets.append((idx, item))
            if len(targets) >= args.limit:
                break

    if args.scene is not None:
        global IMAGE_TYPE
        IMAGE_TYPE = args.img_type
        if args.index is None:
            raise SystemExit("--scene 은 --index 와 함께 써야 합니다")
        ok = refetch_scene(requests.Session(), key, args.index, db[args.index], args.scene, args.source)
        if ok:
            save_db(db)
        raise SystemExit(0 if ok else 1)

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
