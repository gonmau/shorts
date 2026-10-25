# -*- coding: utf-8 -*-
"""작업 이력 기록/요약/동기화 (PC와 GitHub Actions 공용, 한국어·영어 채널 공용).

  run_history.jsonl  : 작업 1건당 1줄 (append 전용, id로 중복 제거 → 여러 곳에서 써도 합쳐짐)
  run_history.md     : 사람이 읽는 요약 (날짜별 작업, 종류별 성공/실패, 최근 작업)
  history_items.csv  : 소재별 현재 상태 한눈에 (facts_db.json / longform_db.json 기준)

사용:
  python history.py add --kind 롱폼 --title "롱폼 3개" --status success [--secs 600] [--detail "..."] [--source Actions]
  python history.py report            # run_history.md, history_items.csv 다시 만들기
  python history.py sync --repo gonmau/shorts    # GitHub와 양방향 병합 (GITHUB_TOKEN 필요)
  python history.py backfill --repo gonmau/shorts   # GitHub Actions 실행·DB 커밋의 과거 기록을 한 번 채우기 (여러 번 해도 중복 없음)
  python history.py show [--n 30]
"""
import argparse
import base64
import csv
import json
import os
import sys
import time
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parent
FILE = BASE / "run_history.jsonl"
REPORT = BASE / "run_history.md"
ITEMS = BASE / "history_items.csv"
KST = timezone(timedelta(hours=9))


def _is_en():
    has_en, has_ko = (BASE / "generate_topics.py").exists(), (BASE / "generate_culture_facts.py").exists()
    if has_en and has_ko:
        try:
            return (BASE / "channel.txt").read_text(encoding="utf-8").strip().lower() == "en"
        except Exception:
            return False
    return has_en and not has_ko


CHANNEL = "EN" if _is_en() else "KO"


def _utf8():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def now_kst():
    return datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")


def add(kind, title, status="success", secs=None, detail="", source=None):
    """이력 1건 추가. 실패해도 작업을 막지 않는다."""
    try:
        source = source or ("Actions" if os.environ.get("GITHUB_ACTIONS") else "PC")
        rec = {"id": f"{int(time.time() * 1000)}-{uuid.uuid4().hex[:6]}", "time": now_kst(), "channel": CHANNEL, "source": source,
               "kind": str(kind)[:30], "title": str(title)[:200], "status": str(status)[:20],
               "secs": None if secs is None else round(float(secs), 1), "detail": str(detail or "")[:600]}
        with open(FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        return rec
    except Exception as e:
        print(f"[이력] 기록 실패: {e}")
        return None


def parse(text):
    out = {}
    for ln in (text or "").splitlines():
        ln = ln.strip()
        if not ln:
            continue
        try:
            r = json.loads(ln)
            if isinstance(r, dict) and r.get("id"):
                out[r["id"]] = r
        except Exception:
            pass
    return out


def read():
    try:
        d = parse(FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        d = {}
    return sorted(d.values(), key=lambda r: (r.get("time", ""), r["id"]))


def dump(recs):
    return "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in sorted(recs, key=lambda r: (r.get("time", ""), r["id"])))


def _fmt_secs(s):
    if s is None:
        return ""
    s = int(s)
    return f"{s // 3600}시간 {s % 3600 // 60}분" if s >= 3600 else (f"{s // 60}분 {s % 60}초" if s >= 60 else f"{s}초")


def items_csv():
    rows = []
    try:
        db = json.load(open(BASE / "facts_db.json", encoding="utf-8"))
    except Exception:
        db = []
    lf = {}
    try:
        for r in json.load(open(BASE / "longform_db.json", encoding="utf-8")):
            for m in r.get("members", []):
                lf.setdefault(m, []).append(r.get("id"))
    except Exception:
        pass
    for i, f in enumerate(db):
        ic = f.get("image_check") or {}
        rows.append({"번호": i, "나라/주제": f.get("country", ""), "소재": f.get("topic", ""), "상태": f.get("status", ""),
                     "생성일": str(f.get("created_at", ""))[:19], "교차검증": f.get("cross_verdict", ""),
                     "이미지검증": (ic.get("verdict") or ic.get("status") or "") if isinstance(ic, dict) else str(ic)[:20],
                     "영상": "O" if (f.get("video_path_v6") or f.get("video_path")) else "", "유튜브ID": f.get("youtube_id", ""),
                     "롱폼": ",".join(str(x) for x in lf.get(i, []))})
    with open(ITEMS, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()) if rows else ["번호"])
        w.writeheader()
        w.writerows(rows)
    return len(rows)


def report():
    recs = read()
    n_items = items_csv()
    L = [f"# 작업 이력 ({CHANNEL} 채널)", "", f"- 갱신: {now_kst()} (KST) · 기록 {len(recs)}건 · 소재 {n_items}개 (소재별 상태는 history_items.csv)", ""]
    kinds = {}
    for r in recs:
        k = kinds.setdefault(r["kind"], {"ok": 0, "bad": 0, "secs": 0.0})
        k["ok" if r["status"] in ("success", "완료", "ok") else "bad"] += 1
        k["secs"] += r.get("secs") or 0
    if kinds:
        L += ["## 종류별 요약", "", "| 종류 | 성공 | 실패 | 누적 시간 |", "|---|---|---|---|"]
        L += [f"| {k} | {v['ok']} | {v['bad']} | {_fmt_secs(v['secs'])} |" for k, v in sorted(kinds.items())]
        L.append("")
    days = {}
    for r in recs:
        days.setdefault(r["time"][:10], []).append(r)
    L.append("## 날짜별 작업 (최근 30일)")
    for day in sorted(days, reverse=True)[:30]:
        L += ["", f"### {day}", "", "| 시각 | 곳 | 종류 | 작업 | 결과 | 소요 | 비고 |", "|---|---|---|---|---|---|---|"]
        for r in sorted(days[day], key=lambda r: r["time"], reverse=True):
            L.append(f"| {r['time'][11:16]} | {r.get('source', '')} | {r['kind']} | {r['title'].replace('|', '/')} | "
                     f"{'✅' if r['status'] in ('success', '완료', 'ok') else '❌ ' + r['status']} | {_fmt_secs(r.get('secs'))} | {str(r.get('detail', '')).replace('|', '/').replace(chr(10), ' ')[:120]} |")
    REPORT.write_text("\n".join(L) + "\n", encoding="utf-8")
    return len(recs)


def notify(text, url=None):
    """디스코드 웹훅으로 한 줄 알림. 실패해도 예외 없음. -> 성공 여부"""
    import urllib.request
    url = (url or os.environ.get("DISCORD_WEBHOOK_URL", "")).strip()
    if not url:
        return False
    try:
        req = urllib.request.Request(url, data=json.dumps({"content": text[:1900]}).encode("utf-8"),
                                     headers={"Content-Type": "application/json", "User-Agent": "shorts-history-bot"})
        urllib.request.urlopen(req, timeout=20)
        return True
    except Exception as e:
        print("디스코드 전송 실패:", e)
        return False


def sync(repo, branch="main", token=None):
    """GitHub의 이력과 양방향 병합 → 로컬 갱신, 달라졌으면 GitHub에도 올림. (PC에서만 사용: Actions는 git으로 직접 커밋)"""
    import requests
    token = token or os.environ.get("GITHUB_TOKEN", "").strip()
    if not token:
        raise SystemExit("GITHUB_TOKEN 환경변수가 없습니다.")
    h = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    url = f"https://api.github.com/repos/{repo}/contents/{FILE.name}"
    r = requests.get(url, params={"ref": branch}, headers=h, timeout=60)
    sha, remote = None, {}
    if r.status_code == 200:
        sha = r.json().get("sha")
        remote = parse(base64.b64decode(r.json()["content"]).decode("utf-8"))
    elif r.status_code != 404:
        r.raise_for_status()
    local = parse(FILE.read_text(encoding="utf-8")) if FILE.exists() else {}
    merged = {**remote, **local}
    new_local = len(merged) - len(local)
    new_remote = len(merged) - len(remote)
    if new_local:
        FILE.write_text(dump(merged.values()), encoding="utf-8")
    msg = f"GitHub에서 {new_local}건 가져옴"
    if new_remote:
        body = {"message": "chore: update run_history.jsonl from PC", "branch": branch,
                "content": base64.b64encode(dump(merged.values()).encode("utf-8")).decode()}
        if sha:
            body["sha"] = sha
        requests.put(url, json=body, headers=h, timeout=120).raise_for_status()
        msg += f", GitHub에 {new_remote}건 올림"
    report()
    from gh_push import push_file
    for f in (REPORT.name, ITEMS.name):
        try:
            push_file(repo, branch, token, f, msg=f"chore: update {f} from PC")
        except Exception as e:
            msg += f" ({f} 올리기 실패: {e})"
    return msg


def _kst(iso):
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(KST)


def backfill(repo, branch="main", token=None, max_runs=1000):
    """GitHub의 과거 기록을 이력으로 채운다: ① Actions 실행(성공/실패, 시작 시각, 소요) ② DB 파일 커밋(Actions 자동 커밋 / PC 업로드).
    id가 실행·커밋 번호로 고정이라 여러 번 돌려도 중복되지 않는다. 기존 기록은 건드리지 않고 없는 것만 추가한다. -> (추가한 건수, 설명)"""
    import requests
    token = token or os.environ.get("GITHUB_TOKEN", "").strip()
    h = {"Accept": "application/vnd.github+json", **({"Authorization": f"Bearer {token}"} if token else {})}
    have = parse(FILE.read_text(encoding="utf-8")) if FILE.exists() else {}
    new = []
    n_run = 0
    page = 1
    while n_run < max_runs:
        r = requests.get(f"https://api.github.com/repos/{repo}/actions/runs", params={"per_page": 100, "page": page}, headers=h, timeout=60)
        r.raise_for_status()
        runs = r.json().get("workflow_runs", [])
        if not runs:
            break
        for w in runs:
            n_run += 1
            rid = f"gh-run-{w['id']}"
            if w.get("status") != "completed" or rid in have:
                continue
            try:
                t0, t1 = _kst(w.get("run_started_at") or w["created_at"]), _kst(w["updated_at"])
            except Exception:
                continue
            name = w.get("name") or ""
            kind = "롱폼" if "longform" in name.lower() else ("쇼츠" if "shorts" in name.lower() else name[:20])
            new.append({"id": rid, "time": t0.strftime("%Y-%m-%d %H:%M:%S"), "channel": CHANNEL, "source": "Actions(과거)", "kind": kind,
                        "title": f"{name} #{w.get('run_number')} ({w.get('event', '')})", "status": w.get("conclusion") or "unknown",
                        "secs": max(0.0, round((t1 - t0).total_seconds(), 1)), "detail": w.get("html_url", "")})
        page += 1
    n_commit = 0
    for path in ("facts_db.json", "longform_db.json"):
        page = 1
        while page <= 10:
            r = requests.get(f"https://api.github.com/repos/{repo}/commits", params={"path": path, "sha": branch, "per_page": 100, "page": page}, headers=h, timeout=60)
            if r.status_code != 200:
                break
            cs = r.json()
            if not cs:
                break
            for c in cs:
                cid = f"gh-commit-{c['sha'][:10]}-{path[:5]}"
                msg = (c["commit"]["message"] or "").splitlines()[0]
                if cid in have or "run history" in msg:
                    continue
                who = (c["commit"]["author"] or {}).get("name", "")
                bot = "bot" in who.lower() or "github-actions" in who.lower()
                new.append({"id": cid, "time": _kst(c["commit"]["author"]["date"]).strftime("%Y-%m-%d %H:%M:%S"), "channel": CHANNEL,
                            "source": "Actions(과거)" if bot else "PC(과거)", "kind": "DB커밋", "title": f"{path}: {msg}"[:200], "status": "success",
                            "secs": None, "detail": c.get("html_url", "")})
                n_commit += 1
            page += 1
    if new:
        with open(FILE, "a", encoding="utf-8") as f:
            for rec in new:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    report()
    return len(new), f"Actions 실행 {sum(1 for x in new if x['id'].startswith('gh-run'))}건, DB 커밋 {n_commit}건 추가 (이미 있던 기록 {len(have)}건은 그대로)"


def main():
    _utf8()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add")
    a.add_argument("--kind", required=True)
    a.add_argument("--title", required=True)
    a.add_argument("--status", default="success")
    a.add_argument("--secs", type=float)
    a.add_argument("--detail", default="")
    a.add_argument("--source")
    sub.add_parser("report")
    s = sub.add_parser("sync")
    s.add_argument("--repo", required=True)
    s.add_argument("--branch", default="main")
    sh = sub.add_parser("show")
    sh.add_argument("--n", type=int, default=30)
    b = sub.add_parser("backfill")
    b.add_argument("--repo", required=True)
    b.add_argument("--branch", default="main")
    b.add_argument("--max", type=int, default=1000)
    n = sub.add_parser("notify")
    n.add_argument("text")
    x = ap.parse_args()
    if x.cmd == "add":
        r = add(x.kind, x.title, x.status, x.secs, x.detail, x.source)
        report()
        print("이력 기록:", r and f"{r['time']} {r['kind']} {r['title']} ({r['status']})")
    elif x.cmd == "report":
        print(f"이력 {report()}건 → {REPORT.name}, {ITEMS.name}")
    elif x.cmd == "sync":
        print("이력 동기화:", sync(x.repo, x.branch))
    elif x.cmd == "show":
        for r in read()[-x.n:]:
            print(f"{r['time']} [{r.get('source', '')}] {r['kind']:<8} {r['status']:<8} {_fmt_secs(r.get('secs')):<10} {r['title']}")
    elif x.cmd == "backfill":
        print("과거 이력:", backfill(x.repo, x.branch, max_runs=x.max)[1])
    elif x.cmd == "notify":
        print("전송" if notify(x.text) else "실패(웹훅 없음?)")


if __name__ == "__main__":
    main()
