# -*- coding: utf-8 -*-
"""채널에 실제로 있는 영상과 facts_db.json 의 업로드 기록을 비교해 점검한다 (기본은 보기만, DB를 바꾸지 않음).

 1) 삭제됐거나 없는 영상: DB에는 youtube_id 가 있는데 채널(비공개 포함)에는 없음
 2) 채널 안의 중복 영상: 같은 소재로 보이는 영상이 2개 이상 (제목이 거의 같거나, 같은 소재에 연결됨)
 3) 한 영상 id 가 DB 소재 여러 개에 연결된 경우
 4) 채널에는 있는데 DB에 연결 안 된 영상 (DB 소재와 비슷한 것 / 비슷한 소재가 없는 것)
 5) DB가 연결한 영상과 내용이 많이 다른 소재 (DB 기록이 틀렸을 가능성)
  python check_uploads.py                  # 점검만 (upload_check.md 저장)
  python check_uploads.py --clear-missing  # 1)의 소재에서 업로드 기록(youtube_id 등)을 지워 '미업로드'로 되돌림
필요: YT_CLIENT_ID, YT_CLIENT_SECRET, YT_REFRESH_TOKEN (youtube.readonly 권한 포함). 영상 삭제는 유튜브 스튜디오에서 직접 하세요."""
import argparse
import difflib
import json
import os
from pathlib import Path

from sync_uploads import list_videos, n, score

DB = Path("facts_db.json")
UP_KEYS = ("youtube_id", "youtube_privacy", "uploaded_at", "uploaded_manually", "publish_at")
PRIV = {"public": "공개", "private": "비공개", "unlisted": "일부공개"}


def groups_of_duplicates(db, vids, thr=0.85):
    """채널 영상들을 같은 소재끼리 묶어 2개 이상인 묶음만 돌려준다. -> [(영상목록, 근거목록, DB와 관련 있는지)]"""
    vids = list({v["id"]: v for v in vids}.values())          # 같은 영상이 목록에 두 번 들어와도 한 번만 센다
    reasons = {}
    parent = {v["id"]: v["id"] for v in vids}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        parent[find(a)] = find(b)

    linked = {}
    for i, f in enumerate(db):
        yid = f.get("youtube_id")
        if yid in parent:
            linked.setdefault(i, []).append(yid)
            reasons.setdefault(yid, []).append(f"DB [{i}]에 기록된 id")
    # 연결 안 된 영상: 가장 잘 맞는 소재(0.8 이상)에 묶는다
    have = {y for ys in linked.values() for y in ys}
    cand = [(i, f) for i, f in enumerate(db) if f.get("narration")]
    for v in vids:
        if v["id"] in have:
            continue
        best, bi = 0.0, None
        for i, f in cand:
            s = score(f, v)[0]
            if s > best:
                best, bi = s, i
        if bi is not None and best >= 0.8:
            linked.setdefault(bi, []).append(v["id"])
            reasons.setdefault(v["id"], []).append(f"DB [{bi}]와 내용 일치 ({best:.2f}, {score(db[bi], v)[1]})")
    for ys in linked.values():
        for y in ys[1:]:
            union(ys[0], y)
    titles = {v["id"]: n(v["title"]) for v in vids}
    ids = [v["id"] for v in vids]
    for a in range(len(ids)):                      # 제목이 거의 같은 영상도 묶는다
        for b in range(a + 1, len(ids)):
            ta, tb = titles[ids[a]], titles[ids[b]]
            if ta and tb:
                r = difflib.SequenceMatcher(None, ta, tb).ratio()
                if r >= thr:
                    union(ids[a], ids[b])
                    reasons.setdefault(ids[a], []).append(f"{ids[b]} 와 제목 유사 ({r:.2f})")
                    reasons.setdefault(ids[b], []).append(f"{ids[a]} 와 제목 유사 ({r:.2f})")
    g = {}
    for v in vids:
        g.setdefault(find(v["id"]), []).append(v)
    res = []
    for x in g.values():
        if len(x) >= 2:
            x = sorted(x, key=lambda v: v["published"])
            has_db = any(v["id"] in {f.get("youtube_id") for f in db} or any("DB [" in r for r in reasons.get(v["id"], [])) for v in x)
            res.append((x, {v["id"]: reasons.get(v["id"], []) for v in x}, has_db))
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--clear-missing", action="store_true", help="채널에 없는 영상의 업로드 기록을 DB에서 지움")
    a = ap.parse_args()
    for k in ("YT_CLIENT_ID", "YT_CLIENT_SECRET", "YT_REFRESH_TOKEN"):
        if not os.environ.get(k):
            raise SystemExit(f"{k} 가 없습니다 (get_refresh_token.py 로 받거나 GitHub Secrets 확인)")
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    c = Credentials(None, refresh_token=os.environ["YT_REFRESH_TOKEN"], token_uri="https://oauth2.googleapis.com/token",
                    client_id=os.environ["YT_CLIENT_ID"], client_secret=os.environ["YT_CLIENT_SECRET"],
                    scopes=["https://www.googleapis.com/auth/youtube.readonly"])
    yt = build("youtube", "v3", credentials=c, cache_discovery=False)
    vids = list_videos(yt)
    db = json.loads(DB.read_text(encoding="utf-8"))
    by_id = {v["id"]: v for v in vids}
    out = [f"# 업로드 현황 점검", "", f"채널 영상 {len(vids)}개 (비공개 포함) · DB 소재 {len(db)}개 · DB에 업로드 기록이 있는 소재 {sum(1 for f in db if f.get('youtube_id'))}개", ""]

    missing = [(i, f) for i, f in enumerate(db) if f.get("youtube_id") and f["youtube_id"] not in by_id]
    out.append(f"## 1) 채널에 없는 영상 (삭제됐거나 id 오류): {len(missing)}개")
    for i, f in missing:
        out.append(f"- [{i}] {f.get('country', '')} / {f.get('title_line1', '')} {f.get('title_line2', '')} · id {f['youtube_id']} · 기록상 {f.get('youtube_privacy', '?')}, 업로드 {str(f.get('uploaded_at', ''))[:10]}")
    out.append("")

    allg = groups_of_duplicates(db, vids)
    dups = [g for g in allg if g[2]]
    others = [g for g in allg if not g[2]]
    out.append(f"## 2) 채널 안의 중복으로 보이는 영상 묶음: {len(dups)}개")
    out.append("(묶은 근거를 영상마다 적었습니다. 근거가 약하면 실제로는 다른 영상일 수 있으니 직접 확인하세요)")
    link = {f.get("youtube_id"): i for i, f in enumerate(db) if f.get("youtube_id")}
    for k, (grp, rs, _h) in enumerate(dups, 1):
        out.append(f"- 묶음 {k}")
        for v in grp:
            tag = f"DB [{link[v['id']]}]에 연결" if v["id"] in link else "DB 연결 없음"
            out.append(f"  - https://youtu.be/{v['id']} · {PRIV.get(v['privacy'], v['privacy'])} · {v['published'][:10]} · {v['title'][:50]} · {tag}")
            for r in rs[v["id"]]:
                out.append(f"      · 근거: {r}")
    out.append("")
    if others:
        out.append(f"## 2-2) DB 소재와 관계없이 제목만 비슷한 영상 (라이브 등 직접 올린 영상일 수 있음): {len(others)}묶음")
        for grp, _rs, _h in others:
            out.append("- " + " / ".join(f"{v['id']}({v['published'][:10]})" for v in grp) + f" · {grp[0]['title'][:40]}")
        out.append("")

    shared = {}
    for i, f in enumerate(db):
        if f.get("youtube_id"):
            shared.setdefault(f["youtube_id"], []).append(i)
    shared = {y: ix for y, ix in shared.items() if len(ix) >= 2}
    out.append(f"## 3) 한 영상이 여러 소재에 연결된 경우: {len(shared)}개")
    for y, ix in shared.items():
        out.append(f"- https://youtu.be/{y} ← 소재 {', '.join(map(str, ix))}")
    out.append("")

    have_ids = {f.get("youtube_id") for f in db if f.get("youtube_id")}
    cand = [(i, f) for i, f in enumerate(db) if f.get("narration")]
    unl_match, unl_none = [], []
    for v in vids:
        if v["id"] in have_ids:
            continue
        best, bi = 0.0, None
        for i, f in cand:
            sc = score(f, v)[0]
            if sc > best:
                best, bi = sc, i
        (unl_match if (bi is not None and best >= 0.6) else unl_none).append((v, bi, best))
    out.append(f"## 4) 채널에는 있는데 DB에 연결 안 된 영상: {len(unl_match) + len(unl_none)}개")
    out.append(f"### 4-1) 내용이 DB 소재와 비슷함 (연결만 안 된 듯, sync_uploads 로 연결 가능): {len(unl_match)}개")
    for v, bi, sc in sorted(unl_match, key=lambda x: -x[2]):
        f = db[bi]
        cur = f" ※ 그 소재는 이미 다른 영상({f['youtube_id']})에 연결됨 → 중복 가능" if f.get("youtube_id") else ""
        out.append(f"- https://youtu.be/{v['id']} · {PRIV.get(v['privacy'], v['privacy'])} · {v['published'][:10]} · {v['title'][:40]} ≈ DB [{bi}] {f.get('country', '')} {f.get('title_line1', '')} ({sc:.2f}){cur}")
    out.append(f"### 4-2) 비슷한 DB 소재가 없음 (직접 올린 라이브·옛 영상이거나, DB에서 빠진 소재): {len(unl_none)}개")
    for v, bi, sc in sorted(unl_none, key=lambda x: x[0]["published"], reverse=True):
        out.append(f"- https://youtu.be/{v['id']} · {PRIV.get(v['privacy'], v['privacy'])} · {v['published'][:10]} · {v['title'][:50]}")
    out.append("")

    bad = []
    for i, f in enumerate(db):
        v = by_id.get(f.get("youtube_id"))
        if v and f.get("narration"):
            sc = score(f, v)[0]
            if sc < 0.5:
                bad.append((i, f, v, sc))
    out.append(f"## 5) DB가 연결한 영상과 내용이 많이 다른 소재 (DB 기록이 틀렸을 수 있음): {len(bad)}개")
    for i, f, v, sc in sorted(bad, key=lambda x: x[3]):
        out.append(f"- DB [{i}] {f.get('country', '')} {f.get('title_line1', '')} {f.get('title_line2', '')} ↔ https://youtu.be/{v['id']} 「{v['title'][:40]}」 ({sc:.2f})")
    out.append("")

    if a.clear_missing and missing:
        import time as _t
        for _i, f in missing:
            for k in UP_KEYS:
                f.pop(k, None)
            f["upload_cleared_ts"] = _t.time()     # sync_db 가 GitHub의 옛 youtube_id 로 되돌리지 못하게 하는 표시
        DB.write_text(json.dumps(db, ensure_ascii=False, indent=2), encoding="utf-8")
        out.append(f"✔ 채널에 없는 영상 {len(missing)}개의 업로드 기록을 지워 '미업로드'로 되돌렸습니다.")
    elif missing:
        out.append("※ 1)의 기록을 지우려면 --clear-missing (UI의 '삭제된 영상 기록 지우기'). 영상 삭제는 유튜브 스튜디오에서 직접 하세요.")
    rep = "\n".join(out)
    Path("upload_check.md").write_text(rep + "\n", encoding="utf-8")
    print(rep)


if __name__ == "__main__":
    main()
