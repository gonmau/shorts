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
   폐기(rejected)와 영상완료가 갈리면 영상완료, 그 밖의 폐기 충돌은 '충돌'로 표시하고 --prefer 쪽을 따른다.
 - 영상/음성 파일 경로(PC·GitHub 환경마다 다름)는 비교하지 않고 각자 값을 유지한다.
 - 폐기(rejected)와 영상완료(video_done)가 갈리면 폐기를 따른다 (PC에서 폐기한 소재가 되살아나지 않도록). 예전처럼 영상완료를 따르려면 --video-wins.
 - 그 밖의 칸(대본/제목 등)이 서로 다르면 '충돌'로 표시하고 --prefer 쪽을 따른다.
 - 소재 순서(번호)는 영상 파일명에 쓰이므로 --base(기본 PC) 쪽 번호를 유지하고, 상대쪽에만 있는 소재는 맨 뒤에 붙인다.
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
REJECT_WINS = True    # 폐기와 영상완료가 갈리면 폐기를 따른다 (PC에서 폐기한 소재가 되살아나지 않게). --video-wins 로 예전 방식


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


def align(G, L, base="local"):
    """[(g 또는 None, l 또는 None)] — base 쪽의 순서(번호)를 그대로 유지하고, 상대쪽에만 있는 소재는 맨 뒤에 붙인다."""
    P, S = (L, G) if base == "local" else (G, L)
    sm = {}
    for x in S:
        sm.setdefault(key(x), []).append(x)
    used, pairs = set(), []
    moved = 0
    for i, p in enumerate(P):
        x = next((c for c in sm.get(key(p), []) if id(c) not in used), None)
        if x is not None:
            used.add(id(x))
            if i >= len(S) or key(S[i]) != key(p):
                moved += 1
        pairs.append((p, x))
    only_s = [x for x in S if id(x) not in used]
    pairs += [(None, x) for x in only_s]
    if base == "local":
        pairs = [(x, p) for p, x in pairs]
    else:
        pairs = [(p, x) for p, x in pairs]
    # pairs 는 이제 (g, l)
    warns = []
    if moved:
        warns.append(f"양쪽 소재 순서가 달라 {moved}개 소재의 번호가 다릅니다. {'PC' if base == 'local' else 'GitHub'} 번호를 기준으로 유지합니다.")
    if only_s:
        warns.append(f"{'GitHub' if base == 'local' else 'PC'}에만 있는 소재 {len(only_s)}개는 맨 뒤에 번호가 새로 붙습니다 "
                     f"({len(P)}번부터). 그쪽에서 이미 영상 파일을 만들었다면 파일명 번호가 달라집니다.")
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
        elif k == "status" and {gv, lv} == {"rejected", "video_done"}:
            if REJECT_WINS:
                out[k] = "rejected"
                conf.append((k, gv, lv, "폐기 우선"))
            else:   # 이미 영상을 만든 소재는 폐기 표시보다 영상완료를 우선 (UI에서 언제든 다시 폐기 가능)
                out[k] = "video_done"
                conf.append((k, gv, lv, "video_done 우선"))
        elif k in ("status", "status_v6") and gv in RANK and lv in RANK:
            out[k] = gv if RANK[gv] > RANK[lv] else lv
        else:
            pick = lv if prefer == "local" else gv
            out[k] = pick
            conf.append((k, gv, lv, "PC" if prefer == "local" else "GitHub"))
    # 다시 만들기(redo) 표시: 더 최근에 redo 한 쪽의 상태를 따른다 (안 그러면 GitHub의 옛 video_done 이 이겨서 redo 가 되돌려짐)
    gt, lt = float(g.get("redo_ts") or 0), float(l.get("redo_ts") or 0)
    if gt != lt:
        win = l if lt > gt else g
        for k in ("redo_ts", "status", "status_v6", "audio_path_v2", "timing_path_v2", "tts_voice_v2", "status_tts_v2", "video_path_v6",
                  "narration", "title_line1", "title_line2", "highlights", "image_queries", "ko_title", "ko_description"):
            if k in win:
                out[k] = win[k]
            else:
                out.pop(k, None)
    if out.get("status") != "rejected":
        out.pop("reject_reason", None)
    # 상태 일관성: 영상이 끝난 쪽의 status_v6 가 이겼는데 status 가 뒤처지면 맞춘다
    return out, conf


def short(v, n=40):
    s = json.dumps(v, ensure_ascii=False) if not isinstance(v, str) else v
    return s if len(s) <= n else s[:n] + "…"


def merge_all(G, L, side, prefer, base="local"):
    pairs, warns = align(G, L, base)
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


def _utf8_out():
    """윈도우 cp949 콘솔/리다이렉트(>)에서 ✔ ⚠ 같은 문자가 에러 나지 않게"""
    for st in (sys.stdout, sys.stderr):
        try:
            st.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def main():
    _utf8_out()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", required=True)
    ap.add_argument("--branch", default="main")
    ap.add_argument("--local", default="facts_db.json")
    ap.add_argument("--prefer", choices=["local", "github"], default="local")
    ap.add_argument("--base", choices=["local", "github"], default="local", help="소재 번호(순서)를 어느 쪽 기준으로 유지할지 (기본 PC)")
    ap.add_argument("--detail", action="store_true", help="상태 충돌과, 영상/업로드가 걸린 대본 충돌을 소재별로 자세히 출력")
    ap.add_argument("--reject-wins", action="store_true", help="(기본값) 폐기와 영상완료가 갈리면 폐기를 따른다")
    ap.add_argument("--video-wins", action="store_true", help="폐기와 영상완료가 갈리면 영상완료를 따른다 (예전 방식)")
    ap.add_argument("--auto", action="store_true", help="UI 자동 동기화용: GitHub에만 있는 소재가 10개를 넘으면(번호/제목이 어긋났을 가능성) 적용하지 않고 멈춘다")
    ap.add_argument("--apply", action="store_true", help="PC 파일을 병합본으로 갱신")
    ap.add_argument("--push", action="store_true", help="병합본을 GitHub에도 커밋 (--apply 와 함께)")
    a = ap.parse_args()
    token = os.environ.get("GITHUB_TOKEN")
    global REJECT_WINS
    REJECT_WINS = not a.video_wins

    L = json.load(open(a.local, encoding="utf-8")) if os.path.exists(a.local) else []
    G, sha = fetch_github(a.repo, a.branch, token)
    print(f"PC {len(L)}개 / GitHub {len(G)}개 소재")
    merged, report, warns = merge_all(G, L, "local", a.prefer, a.base)
    for w in warns:
        print("⚠️ " + w)
    if not report:
        print("✅ 두 파일의 내용이 같습니다 (경로 제외).")
    for idx, ref, kind, conf in report:
        print(f"\n[{idx}] {ref.get('country', '')} - {kind}")
        g_, l_ = None, None
        for k, gv, lv, pick in conf:
            print(f"   ⚔ {k}: GitHub={short(gv)} | PC={short(lv)} → {pick} 선택")
    if a.detail:
        gm = {key(g): g for g in G}
        lm = {key(l): l for l in L}
        print("\n[상세] 상태 충돌 + 영상/업로드가 걸린 대본 충돌")
        for idx, ref, kind, conf in report:
            g, l = gm.get(key(ref)), lm.get(key(ref))
            if not g or not l:
                continue
            ck = {c[0] for c in conf}
            risky = any(x.get("youtube_id") or x.get("status_v6") == "video_done" for x in (g, l))
            if "status" in ck or ("narration" in ck and risky):
                def st(x):
                    return f"{x.get('status')}{'/영상' if x.get('status_v6') == 'video_done' else ''}{'/업로드' if x.get('youtube_id') else ''}"
                print(f"[PC번호 {idx}] {ref.get('country', '')} - {str(ref.get('topic', ''))[:25]}")
                print(f"   GitHub: {st(g)} | 대본 {len(str(g.get('narration') or ''))}자 '{str(g.get('narration') or '')[:22]}'")
                print(f"   PC    : {st(l)} | 대본 {len(str(l.get('narration') or ''))}자 '{str(l.get('narration') or '')[:22]}'")
    n_conf = sum(len(c) for *_, c in report)
    from collections import Counter
    kinds = Counter(k for _, _, kind, _ in report for k in [kind])
    fields = Counter(c[0] for *_, cf in report for c in cf)
    print("\n[요약] " + " · ".join(f"{k} {n}" for k, n in kinds.items()))
    if fields:
        print("[충돌 칸 종류] " + " · ".join(f"{k} {n}" for k, n in fields.most_common()))
    # 값만 다르고 의미는 같은 흔한 경우(예: status 가 한쪽만 다름)를 보기 쉽게
    stat = Counter((c[1], c[2]) for *_, cf in report for c in cf if c[0] == "status")
    for (gv, lv), n in stat.most_common(8):
        print(f"   status GitHub={gv} / PC={lv}: {n}개")
    print(f"\n차이 {len(report)}개 소재 · 충돌 {n_conf}칸 (--prefer {a.prefer})")
    if a.auto:
        gh_only = sum(1 for *_, kind, _c in report if kind == "GitHub에만 있는 소재")
        if gh_only > 10:
            print(f"자동 동기화 보류: GitHub에만 있는 소재가 {gh_only}개입니다 (소재 제목이 어긋났을 수 있음). 동기화 탭의 '차이 보기'로 확인한 뒤 수동으로 가져오세요.")
            sys.exit(2)
    if not a.apply:
        print("미리보기입니다. 적용하려면 --apply (GitHub에도 올리려면 --apply --push)")
        return
    shutil.copy(a.local, a.local + ".bak") if os.path.exists(a.local) else None
    json.dump(merged, open(a.local, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"✔ {a.local} 갱신 (백업: {a.local}.bak)")
    if a.push:
        if not token:
            sys.exit("GITHUB_TOKEN 환경변수가 없어 GitHub에는 올리지 못했습니다.")
        merged_gh, _, _ = merge_all(G, L, "github", a.prefer, a.base)
        G2, sha = fetch_github(a.repo, a.branch, token)   # 가장 최신 sha
        if json.dumps(G2, ensure_ascii=False, sort_keys=True) == json.dumps(merged_gh, ensure_ascii=False, sort_keys=True):
            print("✔ GitHub와 내용이 같아 커밋하지 않았습니다.")
            return
        push_github(a.repo, a.branch, token, merged_gh, sha, "chore: sync facts_db.json from PC [skip ci]")
        print("✔ GitHub에 커밋했습니다.")


if __name__ == "__main__":
    main()
