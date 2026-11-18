"""소재 자동 선별 + 대본 점검 + 잘된 영상 플롯 분석 (사람이 하던 '쓸지 말지 결정'과 대본 피드백의 자동화)

  python curate.py --playbook            잘된/저조 영상 대본을 비교해 script_playbook.json(훅·흐름·피할 것·소재 특징) 생성
  python curate.py --score [--cutoff 7]  대기 소재(unverified/verified)를 1~10점으로 채점, 기준 미만은 폐기, 상위 N개는 curate_top 표시
  python curate.py --review [--review-max 10]   대본 완료·영상 미제작(scripted) 소재 대본 점검 (규칙 검사는 토큰 0, 재작성은 최대 N개)
  (여러 개를 함께 지정 가능. 인자 없이 실행하면 셋 다)  --top 10  --dry-run  --force

토큰 절약: 소재는 25개씩 묶어 한 번에 채점. 한도(429)에 걸리면 거기까지 저장하고 멈춤(다시 실행하면 이어서).
폐기는 prev_status 를 남기므로 UI에서 되살릴 수 있다.
"""
import argparse
import json
import os
import re
import shutil
import sys
from pathlib import Path

from groq import Groq

import generate_script as gs

PLAYBOOK = Path("script_playbook.json")
BATCH = 25
REJ = []      # 이번 실행에서 폐기한 소재 번호
REV = {"rewritten": [], "manual": [], "ok": 0}


# 직접 검수·수정한 대본 142건(narration_original → narration) 비교에서 나온 규칙 (2026-11)
EDIT_RULES = [
    "자료·위키 본문에 없는 숫자·시각·장소·범위를 쓰지 않는다. '~도 금지', '체포' 같은 과장 대신 정확한 표현(예: 밤 12시 이후 클럽 춤 금지)",
    "짧게 쓴다. 8~10문장, 330~360자 안팎. 같은 말을 되풀이하는 문장과 장식 문장을 뺀다",
    "첫 문장은 '~알고 계셨나요?' 같은 빈 질문보다 구체적인 사실·숫자·대비를 단정형으로 시작한다 (질문은 구체적 상황을 물을 때만)",
    "'전해지는 이야기에 따르면', '묘사되곤 합니다', '~하는 경우가 있습니다' 같은 전언·모호체를 쓰지 않는다",
    "소재와 무관한 나라·사례를 끼워 넣지 않는다 (예: 프랑스 레베 소재에 캐나다 새해 행사)",
    "귀족·신하·특정 집단을 '국민'·'모두'로 일반화하지 않는다. 일부를 전체로 말하지 않는다",
    "마지막 문장은 첫 문장의 궁금증에 답하거나 구체적 여운으로 끝낸다 (감상문 같은 마무리 금지)",
]


def load_playbook():
    try:
        return json.loads(PLAYBOOK.read_text(encoding="utf-8"))
    except Exception:
        return {}


def playbook_text(kind="script"):
    """대본/재작성 프롬프트에 붙일 문장. 없으면 빈 문자열"""
    pb = load_playbook()
    lines = [f"- 직접 수정 패턴: {x}" for x in EDIT_RULES]
    for key, label in (("hook", "첫 문장(훅) 패턴"), ("flow", "전개 흐름"), ("avoid", "피할 것")):
        for x in (pb.get(key) or [])[:3]:
            lines.append(f"- {label}: {x}")
    if not lines:
        return ""
    return ("\n\n[직접 검수·수정한 대본 142건과 조회수·시청률이 높았던 영상에서 뽑은 규칙 — 참고용입니다. "
            "다른 영상의 문장을 그대로 쓰지 말고 사실은 주어진 자료에서만 가져오세요]\n" + "\n".join(lines))


def _json_from(text):
    m = re.search(r"[\[{].*[\]}]", text or "", re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None


def _stats_rows(db):
    """최신 yt_stats 스냅샷에서 직접 만든 영상의 성과 + 대본"""
    try:
        snaps = json.loads(Path("yt_stats.json").read_text(encoding="utf-8"))
    except Exception:
        return []
    best = {}
    for snap in snaps if isinstance(snaps, list) else [snaps]:
        for v in snap.get("videos", []):
            if v.get("kind") == "short" and v.get("own") and isinstance(v.get("idx"), int):
                cur = best.get(v["idx"])
                if not cur or v.get("views", 0) >= cur.get("views", 0):
                    best[v["idx"]] = v
    rows = []
    for idx, v in best.items():
        if idx >= len(db) or not db[idx].get("narration"):
            continue
        views, pct, subs = v.get("views", 0), v.get("averageViewPercentage", 0) or 0, v.get("subscribersGained", 0) or 0
        rows.append({"idx": idx, "score": views * pct / 100 + 30 * subs, "views": views, "pct": pct,
                     "title": v.get("title", ""), "narration": db[idx]["narration"],
                     "reviewed": db[idx].get("fact_risk") == "user-reviewed"})
    rows.sort(key=lambda r: -r["score"])
    return rows


def build_playbook(client, models, db):
    rows = _stats_rows(db)
    if len(rows) < 8:
        print(f"[플레이북] 성과 데이터가 부족합니다 ({len(rows)}개)")
        return {}
    top, bottom = rows[:6], rows[-6:]
    def fmt(rs):
        return "\n".join(f"- [{r['views']}회, 평균시청 {r['pct']:.0f}%{', 직접검수' if r['reviewed'] else ''}] {r['title']}\n  {r['narration'][:380]}" for r in rs)
    prompt = f"""한국어 유튜브 쇼츠 채널의 영상 성과 비교입니다. 잘된 영상과 저조한 영상의 대본 차이를 분석해 앞으로 대본을 쓸 때 지킬 규칙을 뽑으세요.
시청층은 주로 20~40대 남성이며 전쟁·군사·영토·역사·금지/처벌·돈 소재에 반응이 좋습니다.

[잘된 영상]
{fmt(top)}

[저조한 영상]
{fmt(bottom)}

JSON만 출력: {{"hook": ["첫 문장 패턴 3개 이내(구체적 예시 구조)"], "flow": ["전개 흐름 규칙 3~4개 (몇 번째 문장에 무엇을)"], "avoid": ["저조한 영상에 공통으로 보이는 약점 3개"], "topic": ["잘된 소재의 공통 특징 3개"]}}
각 항목은 한 문장, 60자 이내."""
    out = gs.ask_models(client, models, "당신은 유튜브 쇼츠 대본 분석가입니다. JSON만 출력합니다.", prompt, 1500, 2,
                        lambda t: _json_from(t) if isinstance(_json_from(t), dict) else None)
    if not out:
        print("[플레이북] 생성 실패 (모델 한도일 수 있음)")
        return {}
    out["based_on"] = {"top": [r["idx"] for r in top], "bottom": [r["idx"] for r in bottom]}
    PLAYBOOK.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print("[플레이북] 저장:", json.dumps({k: out[k] for k in ("hook", "flow", "avoid", "topic") if k in out}, ensure_ascii=False)[:600])
    return out


def _examples(db):
    rows = _stats_rows(db)
    good = [f"{r['title']}" for r in rows[:8]]
    bad = []
    for f in db:
        rr = str(f.get("reject_reason") or "")
        if rr.startswith("UI에서") and not rr.startswith("UI에서 폐기sfd") and f.get("topic"):
            bad.append(f"{f.get('country', '')} - {f['topic']}")
    return good, bad[-10:]


def score_topics(client, models, db, cutoff, top_n, force, dry):
    pb = load_playbook()
    good, bad = _examples(db)
    cand = [i for i, f in enumerate(db) if f.get("status") in ("unverified", "verified", "scripted")
            and not f.get("curate_keep") and (force or f.get("curate_score") is None)]
    print(f"[선별] 채점 대상 {len(cand)}개 (기준 {cutoff}점 미만 폐기)")
    traits = "\n".join("- " + x for x in (pb.get("topic") or []))
    stop = False
    for b in range(0, len(cand), BATCH):
        chunk = cand[b:b + BATCH]
        lines = "\n".join(f"{i}. {db[i].get('country', '')} | {db[i].get('topic', '')} | {str(db[i].get('hook', ''))[:70]}" for i in chunk)
        prompt = f"""쇼츠 소재 후보를 채점하세요. 시청층: 20~40대 남성, 전쟁·군사·영토·권력·돈·금지/처벌·역사 반전에 반응. 목표는 첫 3초에 멈춰 세우고 끝까지 보게 하는 소재입니다.
채점 기준(10점 만점): 첫 문장에 구체적 숫자·대비·걸린 것(목숨/돈/영토/처벌)을 넣을 수 있는가 / 장면이 눈에 그려지는가 / 사실 확인이 되는가 / 평범한 의례·축제·음식 소개나 국가 일반화는 감점.
{traits}
[잘된 영상 제목] {' / '.join(good)}
[직접 버린 소재 예] {' / '.join(bad)}

[후보]
{lines}

JSON 배열만 출력: [{{"i": 번호, "s": 1~10 정수, "why": "20자 이내 이유"}}] (모든 후보를 빠짐없이)"""
        res = gs.ask_models(client, models, "당신은 유튜브 쇼츠 소재 선별 담당입니다. JSON만 출력합니다.", prompt, 2500, 2,
                            lambda t: _json_from(t) if isinstance(_json_from(t), list) else None)
        if not res:
            print(f"[선별] 모델 한도/실패 → {b}번째 묶음에서 중단 (지금까지 결과는 저장, 다시 실행하면 이어서)")
            stop = True
            break
        got = 0
        for r in res:
            try:
                i, s = int(r["i"]), int(r["s"])
            except Exception:
                continue
            if i not in chunk:
                continue
            db[i]["curate_score"] = max(1, min(10, s))
            db[i]["curate_why"] = str(r.get("why", ""))[:40]
            got += 1
        print(f"  묶음 {b // BATCH + 1}: {got}/{len(chunk)}개 채점")
    rejected = 0
    scored = [i for i in cand if db[i].get("curate_score") is not None]
    for i in scored:
        f = db[i]
        if f["status"] in ("unverified", "verified") and f["curate_score"] < cutoff and not dry:
            f["prev_status"] = f["status"]
            f["status"] = "rejected"
            f["reject_reason"] = f"자동 선별 {f['curate_score']}점: {f.get('curate_why', '')}"
            rejected += 1
            REJ.append(i)
    alive = sorted([i for i, f in enumerate(db) if f.get("status") in ("unverified", "verified", "scripted")
                    and f.get("curate_score") is not None], key=lambda i: -db[i]["curate_score"])
    for rank, i in enumerate(alive):
        db[i]["curate_top"] = rank < top_n
    print(f"[선별] 폐기 {rejected}개 · 남은 소재 {len(alive)}개 · 상위 {min(top_n, len(alive))}개 표시")
    for i in alive[:top_n]:
        print(f"   {i:4d} [{db[i]['curate_score']}점] {db[i].get('country', '')} - {db[i].get('topic', '')}  ({db[i].get('curate_why', '')})")
    return stop


def review_scripts(client, models, db, review_max, dry):
    """대본 완료·영상 미제작(scripted) 소재: 규칙 검사(토큰 0) → 문제 있는 것만 재작성(최대 review_max개, 소재 점수 높은 순)"""
    ids = [i for i, f in enumerate(db) if f.get("status") == "scripted" and f.get("narration")]
    flagged = []
    for i in ids:
        issues, _, _ = gs.check_hook(db[i]["narration"])
        if issues:
            flagged.append((i, issues))
    print(f"[대본점검] 대상 {len(ids)}개 · 규칙 검사에서 문제 {len(flagged)}개 · 재작성은 최대 {review_max}개")
    flagged.sort(key=lambda x: -(db[x[0]].get("curate_score") or 0))
    fl = {i for i, _ in flagged}
    rest = sorted([i for i in ids if i not in fl and not (db[i].get("hook_check") or {}).get("ground_done")],
                  key=lambda i: -(db[i].get("curate_score") or 0))
    flagged += [(i, []) for i in rest]          # 규칙 검사를 통과한 대본도 위키 본문과 대조(근거 점검)
    done = 0
    for i, issues in flagged:
        f = db[i]
        if done >= review_max or dry or client is None:
            if not issues:
                continue
            f["hook_check"] = {"ok": False, "issues": issues, "rounds": 0, "first": (gs._split_sents(f["narration"]) or [""])[0]}
            f["review_needed"] = True
            REV["manual"].append(i)
            continue
        done += 1
        print(f"  {i} {f.get('country', '')}: " + " / ".join(issues))
        try:
            f["narration"] = gs.refine_script(client, models, f, f["narration"])
            f.setdefault("hook_check", {})["ground_done"] = True
            f["status"] = "scripted"
            (REV["rewritten"] if not f.get("review_needed") else REV["manual"]).append(i)
        except Exception as e:
            print("   재작성 실패:", type(e).__name__, e)
    ok = sum(1 for i in ids if not db[i].get("review_needed"))
    REV["ok"] = ok
    print(f"[대본점검] 통과 {ok}개 · 수동 검수 필요 {len(ids) - ok}개")


def notify(db, a):
    """결과 요약을 디스코드로 (DISCORD_WEBHOOK_URL 이 있을 때)"""
    url = os.environ.get("DISCORD_WEBHOOK_URL", "")
    if not url:
        print("DISCORD_WEBHOOK_URL 없음 → 알림 생략")
        return
    from notify_discord import post_long
    def t(i):
        return f"`{i}` {db[i].get('country', '')} — {' '.join(str(db[i].get('topic') or '').split())[:50]}"
    L = [f"🧹 **소재 선별·대본 점검 결과**{' (미리보기, 변경 없음)' if a.dry_run else ''}"]
    pb = load_playbook()
    if pb and a.playbook:
        L.append("📈 **잘된 영상 플롯 규칙**")
        for k, lab in (("hook", "훅"), ("flow", "흐름"), ("avoid", "피할 것")):
            for x in (pb.get(k) or [])[:3]:
                L.append(f"· {lab}: {x}")
    if a.score:
        alive = sorted([i for i, f in enumerate(db) if f.get("curate_top")], key=lambda i: -(db[i].get("curate_score") or 0))
        L.append(f"⭐ **상위 {len(alive)}개 소재** (기준 {a.cutoff}점, 폐기 {len(REJ)}개)")
        for i in alive[:15]:
            L.append(f"{db[i]['curate_score']}점 {t(i)} · {db[i].get('curate_why', '')}")
        if REJ:
            L.append("🗑 **폐기 예시**")
            for i in REJ[:8]:
                L.append(f"{db[i].get('curate_score')}점 {t(i)} · {db[i].get('curate_why', '')}")
            if len(REJ) > 8:
                L.append(f"… 외 {len(REJ) - 8}개 (사유는 DB reject_reason, 되살리기: prev_status)")
    if a.review:
        L.append(f"📝 **대본 점검**: 통과 {REV['ok']}개 · 다시 쓴 것 {len(REV['rewritten'])}개 · 수동 검수 필요 {len(REV['manual'])}개")
        for i in REV["manual"][:10]:
            iss = (db[i].get("hook_check") or {}).get("issues") or []
            L.append(f"검수 {t(i)} — {'; '.join(iss)[:80]}")
    web = os.environ.get("WEB_UI_URL", "").strip()
    if web:
        L.append(f"👉 {web.rstrip('/')}/?ch=ko")
    post_long(url, "\n".join(L))
    print("디스코드 알림 전송")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--playbook", action="store_true")
    ap.add_argument("--score", action="store_true")
    ap.add_argument("--review", action="store_true")
    ap.add_argument("--cutoff", type=int, default=7)
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--review-max", type=int, default=10)
    ap.add_argument("--force", action="store_true", help="이미 채점한 소재도 다시")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    if not (a.playbook or a.score or a.review):
        a.playbook = a.score = a.review = True
    db = gs.load_db()
    if Path("facts_db.json").exists() and not a.dry_run:
        shutil.copy("facts_db.json", "facts_db.json.bak")
    key = os.getenv("GROQ_API_KEY")
    client = Groq(api_key=key, timeout=90.0) if key else None
    models = gs.pick_models(client, None) if client else []
    if not client and (a.playbook or a.score):
        sys.exit("GROQ_API_KEY 가 없습니다 (채점·플레이북은 AI 호출이 필요합니다)")
    try:
        if a.playbook:
            build_playbook(client, models, db)
        stop = score_topics(client, models, db, a.cutoff, a.top, a.force, a.dry_run) if a.score else False
        if a.review:
            review_scripts(client, models if not stop else [], db, a.review_max, a.dry_run or stop and False)
    finally:
        if not a.dry_run:
            gs.save_db(db)
    try:
        notify(db, a)
    except Exception as e:
        print("알림 실패:", type(e).__name__, e)


if __name__ == "__main__":
    main()
