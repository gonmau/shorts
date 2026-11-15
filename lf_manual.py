# -*- coding: utf-8 -*-
"""롱폼 직접 입력: 쇼츠 소재 없이 내가 쓴 대본으로 챕터를 만든다.
- add_chapter(): facts_db.json 끝에 status='lf_manual' 소재를 추가하고 롱폼 대본(잠금)을 저장 -> 번호
  (쇼츠 파이프라인은 이 상태를 건드리지 않음). 이후 ② 확인/수정 화면에서 사진·키워드·비교 카드·시나리오를 똑같이 고칠 수 있다.
- plan_add()/plan_remove(): longform_plan.json 의 구성(챕터 목록)에 넣고 뺀다.
"""
import json
import re
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent
DB = BASE / "facts_db.json"
PLAN = BASE / "longform_plan.json"


def _load(p, d):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:
        return d


def add_chapter(label, title1, narration, queries=(), title2="", recap=""):
    import longform_script as LS
    narration = re.sub(r"[ \t]+", " ", str(narration or "")).strip()
    if len(re.sub(r"\s+", "", narration)) < 10:
        raise ValueError("대본이 너무 짧습니다 (10자 이상)")
    title1 = str(title1 or "").strip() or narration[:14]
    label = str(label or "").strip() or title1[:14]
    qs = [q.strip() for q in queries if q and q.strip()][:30]
    db = _load(DB, [])
    db.append({"country": label, "topic": title1, "title_line1": title1[:14], "title_line2": title2.strip() or label, "narration": narration,
               "status": "lf_manual", "theme": "", "hook": "", "body": "", "twist": "",
               "image_queries": qs, "scene_count": max(6, len(qs)) if qs else 6})
    DB.write_text(json.dumps(db, ensure_ascii=False, indent=2), encoding="utf-8")
    idx = len(db) - 1
    LS.update_rec(idx, {"narration": narration, "keywords": [], "compare": None, "recap": recap.strip() or title1[:30],
                        "broll": [], "clip_queries": [], "clips": [], "images": [], "compare_at": 0,
                        "title1": title1[:20], "title2": (title2.strip() or label)[:20]})
    return idx


def plan_add(idx):
    pl = _load(PLAN, {}) or {}
    mem = list(pl.get("members") or [])
    if idx not in mem:
        mem.append(idx)
    pl["members"] = mem
    pl.setdefault("created", time.strftime("%Y-%m-%d %H:%M"))
    pl["order_changed"] = bool(pl.get("order_changed", False))
    for k in ("intro_text", "outro_text"):   # 챕터 구성이 바뀌면 자동 멘트가 어긋나므로 직접 고친 문구는 유지하되 UI 에서 다시 확인하게 둔다
        pass
    PLAN.write_text(json.dumps(pl, ensure_ascii=False, indent=1), encoding="utf-8")
    return pl
