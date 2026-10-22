# -*- coding: utf-8 -*-
"""PC의 facts_db.json 과 GitHub 저장소의 facts_db.json 을 비교·병합한다.

사용 (코드 폴더에서):
  python sync_db.py --repo gonmau/저장소이름                 # 차이만 보여줌 (아무것도 안 바꿈)
  python sync_db.py --repo gonmau/저장소이름 --apply          # PC 파일을 병합본으로 갱신 (백업 .bak 생성)
  python sync_db.py --repo gonmau/저장소이름 --apply --push   # 병합본을 GitHub에도 커밋 (GITHUB_TOKEN 필요)
옵션: --branch main  --local facts_db.json  --prefer local|github (진행 순서로 못 가르는 충돌의 기본 선택, 기본 local)

병합 규칙
 - 한쪽에만 있는 값은 그대로 가져온다. 업로드 정보(youtube_id 등)는 있는 쪽을 쓴다.
 - 상태(status)는 더 진행된 쪽 (unverified < verified < scripted < tts_done < video_done).
   폐기(rejected)는 진행 순서로 비교할 수 없어 '충돌'로 표시하고 --prefer 쪽을 따른다.
 - 영상/음성 파일 경로(PC·GitHub 환경마다 다름)는 비교하지 않고 각자 값을 유지한다.
 - 그 밖의 칸(대본/제목 등)이 서로 다르면 '충돌'로 표시하고 --prefer 쪽을 따른다.
 - 소재 순서(번호)는 영상 파일명에 쓰이므로 바꾸지 않는다. 양쪽에 서로 다른 새 소재가 추가됐으면 뒤에 이어 붙이고 경고한다.
GitHub 읽기: GITHUB_TOKEN 이 있으면 API로, 없으면 공개 저장소의 raw 주소로 읽는다.
"""
import argparse
import base64
import json
import os
import shutil
import sys

import requests

ENV_KEYS = {"video_path_v6", "audio_path_v2", "timing_path_v2"}
RANK = {"unverified": 0, "verified": 1, "scripted": 2, "tts_done": 3, "video_done": 4}
KEEP_NONEMPTY = {"youtube_id", "youtube_privacy", "uploaded_at"}


def key(f):
    return (str(f.get("country", "")), str(f.get("topic", "")))


def fetch_github(repo, branch, token=None):
    """(list, sha)"""
    if token:
        h = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
        r = requests.get(f"https://api.github.com/repos/{repo}/contents/facts_db.json", params={"ref": branch}, headers=h, timeout=60)
        r.raise_for_status()
        meta = r.json()
        if meta.get("content"):
            raw = base64.b64decode(meta["content"])
        else:
            b = requests.get(f"https://api.github.com/repos/{repo}/git/blobs/{meta['sha']}", headers=h, timeout=60)
            b.raise_for_status()
            raw = base64.b64decode(b.json()["content"])
        return json.loads(raw.decode("utf-8")), meta["sha"]
    r = requests.get(f"https://raw.githubusercontent.com/{repo}/{branch}/facts_db.json", timeout=60)
    r.raise_for_status()
    return json.loads(r.content.decode("utf-8")), None


def push_github(repo, branch, token, db, sha, msg):
    body = {"message": msg, "branch": branch, "sha": sha,
            "content": base64.b64encode(json.dumps(db, ensure_ascii=False, indent=2).encode("utf-8")).decode()}
    r = requests.put(f"https://api.github.com/repos/{repo}/contents/facts_db.json", json=body,
                     headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}, timeout=60)
    r.raise_for_status()


def align(G, L):
    """[(g 또는 None, l 또는 None)] — 앞에서부터 소재 키가 같은 구간은 위치로, 나머지는 키로 맞춘다. 경고도 돌려준다."""
    p = 0
    while p < min(len(G), len(L)) and key(G[p]) == key(L[p]):
        p += 1
    pairs = [(G[i], L[i]) for i in range(p)]
    warns = []
    lm = {}
    for l in L[p:]:
        lm.setdefault(key(l), []).append(l)
    used = set()
    rest = []
    for g in G[p:]:
        l = next((c for c in lm.get(key(g), []) if id(c) not in used), None)
        if l is not None:
            used.add(id(l))
        rest.append((g, l))
    rest += [(None, l) for l in L[p:] if id(l) not in used]
    pairs += rest
    g_only = sum(1 for g, l in rest if l is None)
    l_only = sum(1 for g, l in rest if g is None)
    if any(g is not None and l is not None for g, l in rest):
        warns.append(f"앞 {p}개 이후 소재 순서가 서로 달라 (국가,주제) 키로 맞췄습니다. 번호가 바뀐 소재가 있을 수 있으니 확인하세요.")
    if g_only and l_only:
        warns.append(f"양쪽에 서로 다른 새 소재가 추가됨 (GitHub {g_only}개 / PC {l_only}개): 뒤에 이어 붙이며 번호가 밀립니다. 영상 파일명(번호)을 확인하세요.")
    return pairs, warns


def merge_item(g, l, side, prefer):
    """(병합 결과, 충돌 목록[(칸, g값, l값, 선택)])"""
    if g is None:
        return dict(l), []
    if l is None:
        return dict(g), []
    out, conf = {}, []
    for k in list(dict.fromkeys(list(g) + list(l))):
        gv, lv = g.get(k), l.get(k)
        if k in ENV_KEYS:
            out[k] = (lv if side == "local" else gv) if (lv if side == "local" else gv) is not None else (gv if side == "local" else lv)
            continue
        if gv == lv:
            out[k] = gv
        elif k not in g or gv in (None, "", []):
            out[k] = lv
        elif k not in l or lv in (None, "", []):
            out[k] = gv
        elif k in KEEP_NONEMPTY:
            out[k] = lv
        elif k in ("status", "status_v6") and gv in RANK and lv in RANK:
            out[k] = gv if RANK[gv] > RANK[lv] else lv
        else:
            pick = lv if prefer == "local" else gv
            out[k] = pick
            conf.append((k, gv, lv, "PC" if prefer == "local" else "GitHub"))
    # 상태 일관성: 영상이 끝난 쪽의 status_v6 가 이겼는데 status 가 뒤처지면 맞춘다
    return out, conf


def short(v, n=40):
    s = json.dumps(v, ensure_ascii=False) if not isinstance(v, str) else v
    return s if len(s) <= n else s[:n] + "…"


def merge_all(G, L, side, prefer):
    pairs, warns = align(G, L)
    merged, report = [], []
    for g, l in pairs:
        m, conf = merge_item(g, l, side, prefer)
        merged.append(m)
        ref = g or l
        idx = len(merged) - 1
        if g is None:
            report.append((idx, ref, "PC에만 있는 소재", []))
        elif l is None:
            report.append((idx, ref, "GitHub에만 있는 소재", []))
        elif conf or any(g.get(k) != l.get(k) for k in set(g) | set(l) if k not in ENV_KEYS):
            report.append((idx, ref, "내용 차이", conf))
    return merged, report, warns


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", required=True)
    ap.add_argument("--branch", default="main")
    ap.add_argument("--local", default="facts_db.json")
    ap.add_argument("--prefer", choices=["local", "github"], default="local")
    ap.add_argument("--apply", action="store_true", help="PC 파일을 병합본으로 갱신")
    ap.add_argument("--push", action="store_true", help="병합본을 GitHub에도 커밋 (--apply 와 함께)")
    a = ap.parse_args()
    token = os.environ.get("GITHUB_TOKEN")

    L = json.load(open(a.local, encoding="utf-8")) if os.path.exists(a.local) else []
    G, sha = fetch_github(a.repo, a.branch, token)
    print(f"PC {len(L)}개 / GitHub {len(G)}개 소재")
    merged, report, warns = merge_all(G, L, "local", a.prefer)
    for w in warns:
        print("⚠️ " + w)
    if not report:
        print("✅ 두 파일의 내용이 같습니다 (경로 제외).")
    for idx, ref, kind, conf in report:
        print(f"\n[{idx}] {ref.get('country', '')} - {kind}")
        g_, l_ = None, None
        for k, gv, lv, pick in conf:
            print(f"   ⚔ {k}: GitHub={short(gv)} | PC={short(lv)} → {pick} 선택")
    n_conf = sum(len(c) for *_, c in report)
    print(f"\n차이 {len(report)}개 소재 · 충돌 {n_conf}칸 (--prefer {a.prefer})")
    if not a.apply:
        print("미리보기입니다. 적용하려면 --apply (GitHub에도 올리려면 --apply --push)")
        return
    shutil.copy(a.local, a.local + ".bak") if os.path.exists(a.local) else None
    json.dump(merged, open(a.local, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"✔ {a.local} 갱신 (백업: {a.local}.bak)")
    if a.push:
        if not token:
            sys.exit("GITHUB_TOKEN 환경변수가 없어 GitHub에는 올리지 못했습니다.")
        merged_gh, _, _ = merge_all(G, L, "github", a.prefer)
        _, sha = fetch_github(a.repo, a.branch, token)   # 가장 최신 sha
        push_github(a.repo, a.branch, token, merged_gh, sha, "chore: sync facts_db.json from PC [skip ci]")
        print("✔ GitHub에 커밋했습니다.")


if __name__ == "__main__":
    main()
