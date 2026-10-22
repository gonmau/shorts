# -*- coding: utf-8 -*-
"""내 유튜브 채널 영상 일괄 정리 (PC에서 실행). 쓰기 권한(youtube) 로그인이 필요하다.

3단계:
  1) plan     : 채널 영상 전체 + facts_db.json 소재 매칭 + 제목 정리 제안 + 중복 후보 → channel_plan.csv
  2) (엑셀에서 channel_plan.csv 를 열어 '새제목' '새공개' '삭제' 칸을 고친다. 저장은 CSV UTF-8로)
  3) apply    : 미리보기(기본) / --go 로 실제 적용.  삭제는 --go 후 개수를 직접 타이핑해야 실행
  4) sync-db  : CSV의 소재번호를 facts_db.json 의 youtube_id/youtube_privacy 로 기록 (업로드 완료 구분)

사용:
  python manage_channel.py plan client_secret.json --token token_ko_rw.json
  python manage_channel.py apply channel_plan.csv client_secret.json --token token_ko_rw.json [--go]
  python manage_channel.py sync-db channel_plan.csv [--prune]
CSV 칸: 새제목(빈칸=유지) / 새공개(공개·비공개·일부공개, 빈칸=유지) / 삭제(DELETE 라고 쓴 행만 삭제)
쿼터: 수정·삭제는 건당 50 (하루 1만) → 하루 약 200건까지.
"""
import argparse
import csv
import difflib
import json
import re
import shutil
import sys
import time
from pathlib import Path

PRIV_KO = {"public": "공개", "private": "비공개", "unlisted": "일부공개"}
PRIV_EN = {v: k for k, v in PRIV_KO.items()}
SCOPES = ["https://www.googleapis.com/auth/youtube"]
OLD_BEFORE = "2026-09-01"   # 이 날짜 이전 업로드는 쇼츠 채널 소재가 아닌 기존 영상으로 취급
COLS = ["영상ID", "현재공개", "현재제목", "업로드일", "종류", "소재번호", "매칭근거", "메모", "새제목", "새공개", "삭제", "링크"]


# ---------- 순수 함수 (테스트 가능) ----------
def clean_title(t):
    """번호 접두사(0044 )와 한글 앞의 영어 나라명(Japan 일본…)을 떼어 한글 제목으로 통일."""
    n = re.sub(r"^\d{4}\s+", "", t.strip())
    n = re.sub(r"^[A-Za-z][A-Za-z.'’ -]*?\s+(?=[가-힣])", "", n)
    n = " ".join(n.split())
    return n[:100].rstrip() if n else t


def norm(t):
    t = re.sub(r"#\S+", "", t.lower())
    t = re.sub(r"^\d{4}\s+", "", t.strip())
    return re.sub(r"[^\w가-힣]", "", t)


def db_title(item):
    t = " ".join(filter(None, [item.get("title_line1"), item.get("title_line2")])) or item.get("topic", "")
    c = str(item.get("country", "")).strip()
    return f"{c} {t}" if c and c not in t else t


def match_video(title, db, used):
    """(소재번호, 근거) 또는 ("", "")"""
    m = re.match(r"^(\d{4})\s", title)
    if m and int(m.group(1)) < len(db):
        return int(m.group(1)), "번호"
    nt = norm(title)
    best, second, bi = 0.0, 0.0, None
    for i, f in enumerate(db):
        cand = norm(db_title(f))
        if not cand or not nt:
            continue
        r = 1.0 if cand == nt else difflib.SequenceMatcher(None, nt, cand).ratio()
        if r > best:
            best, second, bi = r, best, i
        elif r > second:
            second = r
    if bi is not None and best >= 0.72 and best - second >= 0.08:
        return bi, f"제목유사 {best:.2f}"
    return "", ""


def _country(title):
    """정리된 제목의 첫 단어(나라 이름) — '태국 - 화폐…' → '태국'"""
    w = re.split(r"[\s\-–,·]+", clean_title(title).strip(), maxsplit=1)[0]
    return w if re.fullmatch(r"[가-힣]{2,6}", w) else ""


def find_duplicates(rows):
    """같은 소재번호이거나 제목이 매우 비슷한 영상끼리 묶어 {영상ID: 메모}."""
    memo = {}
    cand = [r for r in rows if r["업로드일"] >= OLD_BEFORE]
    for a in range(len(cand)):
        for b in range(a + 1, len(cand)):
            x, y = cand[a], cand[b]
            same = x["소재번호"] != "" and x["소재번호"] == y["소재번호"]
            nx, ny = norm(clean_title(x["현재제목"])), norm(clean_title(y["현재제목"]))
            r = difflib.SequenceMatcher(None, nx, ny).ratio()
            fx, fy = _country(x["현재제목"]), _country(y["현재제목"])
            # 같은 소재번호 / 매우 비슷한 제목 / 같은 나라이면서 어느 정도 비슷한 제목
            sim = r >= 0.8 or (fx and fx == fy and r >= 0.35)
            if same or sim:
                for p, q in ((x, y), (y, x)):
                    memo.setdefault(p["영상ID"], []).append(f"중복후보: [{q['현재공개']}] {q['현재제목'][:25]}")
    return {k: " / ".join(v[:2]) for k, v in memo.items()}


def build_rows(videos, db):
    rows = []
    for v in videos:
        sn, st = v["snippet"], v["status"]
        title, date = sn["title"], sn["publishedAt"][:10]
        if date >= OLD_BEFORE:
            idx, why = match_video(title, db, None)
        else:
            idx, why = "", ""
        new = clean_title(title) if date >= OLD_BEFORE else title
        rows.append({
            "영상ID": v["id"], "현재공개": PRIV_KO.get(st.get("privacyStatus"), st.get("privacyStatus")),
            "현재제목": title, "업로드일": date, "종류": "쇼츠" if _secs(v["contentDetails"].get("duration")) <= 180 else "롱폼",
            "소재번호": idx, "매칭근거": why, "메모": "기존/개인 영상(쇼츠 채널 소재 아님)" if date < OLD_BEFORE else "",
            "새제목": new if new != title else "", "새공개": "", "삭제": "", "링크": f"https://youtu.be/{v['id']}",
        })
    dups = find_duplicates(rows)
    for r in rows:
        d = dups.get(r["영상ID"])
        if d:
            r["메모"] = (r["메모"] + " " + d).strip()
    order = {"공개": 0, "일부공개": 1, "비공개": 2}
    rows.sort(key=lambda r: (order.get(r["현재공개"], 9), r["업로드일"]))
    return rows


def _secs(iso):
    m = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso or "")
    h, mi, s = (int(x or 0) for x in m.groups()) if m else (0, 0, 0)
    return h * 3600 + mi * 60 + s


# ---------- YouTube ----------
def get_yt(secret, token_path):
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
    creds, tp = None, Path(token_path)
    if tp.exists():
        creds = Credentials.from_authorized_user_file(str(tp), SCOPES)
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    if not creds or not creds.valid:
        creds = InstalledAppFlow.from_client_secrets_file(secret, SCOPES).run_local_server(port=0)
    tp.write_text(creds.to_json(), encoding="utf-8")
    return build("youtube", "v3", credentials=creds)


def fetch_all(yt):
    ch = yt.channels().list(part="contentDetails,snippet", mine=True).execute()["items"][0]
    print(f"채널: {ch['snippet']['title']}")
    pl, ids, tok = ch["contentDetails"]["relatedPlaylists"]["uploads"], [], None
    while True:
        r = yt.playlistItems().list(part="contentDetails", playlistId=pl, maxResults=50, pageToken=tok).execute()
        ids += [i["contentDetails"]["videoId"] for i in r["items"]]
        tok = r.get("nextPageToken")
        if not tok:
            break
    out = []
    for i in range(0, len(ids), 50):
        out += yt.videos().list(part="snippet,status,contentDetails", id=",".join(ids[i:i + 50])).execute()["items"]
    return out


def load_db(path="facts_db.json"):
    return json.load(open(path, encoding="utf-8")) if Path(path).exists() else []


def read_csv(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


# ---------- 명령 ----------
def cmd_plan(a):
    yt = get_yt(a.secret, a.token)
    rows = build_rows(fetch_all(yt), load_db(a.db))
    with open(a.out, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        w.writeheader()
        w.writerows(rows)
    matched = sum(1 for r in rows if r["소재번호"] != "")
    print(f"영상 {len(rows)}개 · 소재 매칭 {matched}개 · 제목 정리 제안 {sum(1 for r in rows if r['새제목'])}개 · 중복후보 {sum(1 for r in rows if '중복후보' in r['메모'])}개")
    print(f"저장: {a.out}  → 엑셀로 열어 새제목/새공개/삭제 칸을 확인·수정하세요 (삭제는 DELETE 입력)")


def plan_actions(rows, current):
    """CSV 행 → 실제로 할 일 목록. current: {id: video(dict)}"""
    acts = []
    for r in rows:
        vid = (r.get("영상ID") or "").strip()
        v = current.get(vid)
        if not v:
            continue
        if (r.get("삭제") or "").strip().upper() == "DELETE":
            acts.append(("delete", vid, v["snippet"]["title"], None))
            continue
        nt = (r.get("새제목") or "").strip()
        if nt and nt != v["snippet"]["title"]:
            if len(nt) > 100:
                print(f"[건너뜀] 제목 100자 초과: {nt[:30]}…")
            else:
                acts.append(("title", vid, v["snippet"]["title"], nt))
        npv = (r.get("새공개") or "").strip()
        if npv:
            en = PRIV_EN.get(npv, npv)
            if en not in PRIV_KO:
                print(f"[건너뜀] 새공개 값 오류({npv}): {vid}")
            elif en != v["status"].get("privacyStatus"):
                acts.append(("privacy", vid, v["snippet"]["title"], en))
    return acts


def cmd_apply(a):
    yt = get_yt(a.secret, a.token)
    cur = {v["id"]: v for v in fetch_all(yt)}
    acts = plan_actions(read_csv(a.csv), cur)
    if not acts:
        print("적용할 변경이 없습니다.")
        return
    for kind, vid, old, new in acts:
        label = {"title": "제목", "privacy": "공개", "delete": "삭제"}[kind]
        print(f"[{label}] {old[:40]}" + (f"  →  {PRIV_KO.get(new, new)}" if kind == "privacy" else f"  →  {new}" if new else "  (삭제)"))
    n_del = sum(1 for k, *_ in acts if k == "delete")
    if not a.go:
        print(f"\n미리보기입니다 (변경 {len(acts)}건 / 삭제 {n_del}건). 실제 적용은 --go 를 붙이세요.")
        return
    if n_del:
        ans = input(f"\n영상 {n_del}개를 영구 삭제합니다. 되돌릴 수 없습니다. 계속하려면 개수({n_del})를 입력: ").strip()
        if ans != str(n_del):
            print("취소했습니다 (아무것도 바꾸지 않음).")
            return
    ok = fail = 0
    for kind, vid, old, new in acts:
        try:
            v = cur[vid]
            if kind == "delete":
                yt.videos().delete(id=vid).execute()
            elif kind == "title":
                sn = dict(v["snippet"])
                sn["title"] = new
                body = {"id": vid, "snippet": {k: sn[k] for k in ("title", "description", "categoryId", "tags", "defaultLanguage") if k in sn}}
                yt.videos().update(part="snippet", body=body).execute()
            else:
                stt = {k: v["status"][k] for k in ("embeddable", "license", "publicStatsViewable", "selfDeclaredMadeForKids") if k in v["status"]}
                stt["privacyStatus"] = new
                yt.videos().update(part="status", body={"id": vid, "status": stt}).execute()
            ok += 1
            print(f"  ✔ {kind} {vid}")
        except Exception as e:
            fail += 1
            print(f"  ✖ {kind} {vid}: {str(e)[:150]}")
            if "quota" in str(e).lower():
                print("  쿼터 초과: 내일 다시 실행하세요 (이미 된 것은 건너뜁니다).")
                break
        time.sleep(0.3)
    print(f"\n완료 {ok}건 / 실패 {fail}건. 이어서: python manage_channel.py plan … 으로 목록을 다시 받고 sync-db 를 실행하세요.")


def cmd_sync_db(a):
    rows = read_csv(a.csv)
    db = load_db(a.db)
    if not db:
        print(f"{a.db} 가 없습니다.")
        return
    shutil.copy(a.db, a.db + ".bak")
    seen, n = set(), 0
    for r in rows:
        s = (r.get("소재번호") or "").strip()
        if not s.isdigit() or int(s) >= len(db):
            continue
        item, vid = db[int(s)], r["영상ID"]
        seen.add(vid)
        priv = PRIV_EN.get(r["현재공개"], r["현재공개"])
        if item.get("youtube_id") not in (None, "", vid) and item.get("youtube_id") != vid:
            print(f"[주의] 소재 {s} 는 이미 다른 영상({item['youtube_id']})과 연결돼 있어 중복 영상 {vid} 는 건너뜁니다.")
            continue
        changed = item.get("youtube_id") != vid or item.get("youtube_privacy") != priv
        item["youtube_id"], item["youtube_privacy"], item["uploaded_at"] = vid, priv, r["업로드일"]
        n += changed
    pruned = 0
    if a.prune:
        for item in db:
            if item.get("youtube_id") and item["youtube_id"] not in {(r.get("영상ID") or "").strip() for r in rows}:
                for k in ("youtube_id", "youtube_privacy", "uploaded_at"):
                    item.pop(k, None)
                pruned += 1
    json.dump(db, open(a.db, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    up = sum(1 for f in db if f.get("youtube_id"))
    done_no = sum(1 for f in db if f.get("status_v6") == "video_done" and not f.get("youtube_id"))
    print(f"{a.db} 갱신: 변경 {n}건" + (f" / 연결 해제 {pruned}건" if a.prune else "") + f" · 업로드됨 {up}개 · 영상완료지만 미업로드 {done_no}개 (백업: {a.db}.bak)")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("plan")
    p.add_argument("secret"); p.add_argument("--token", default="yt_rw_token.json")
    p.add_argument("--out", default="channel_plan.csv"); p.add_argument("--db", default="facts_db.json")
    p.set_defaults(fn=cmd_plan)
    p = sub.add_parser("apply")
    p.add_argument("csv"); p.add_argument("secret"); p.add_argument("--token", default="yt_rw_token.json")
    p.add_argument("--go", action="store_true")
    p.set_defaults(fn=cmd_apply)
    p = sub.add_parser("sync-db")
    p.add_argument("csv"); p.add_argument("--db", default="facts_db.json"); p.add_argument("--prune", action="store_true")
    p.set_defaults(fn=cmd_sync_db)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
