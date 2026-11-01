#!/usr/bin/env python3
"""디스크 정리: 업로드가 끝난 소재(youtube_id 있음)의 영상·음성·썸네일·장면 사진(+선택: 롱폼용 클립) 용량을 보여주고 지운다.

  python cleanup_media.py                 # 용량만 표시 (아무것도 안 지움)
  python cleanup_media.py --delete        # 업로드 완료 소재 파일 삭제 (영상·음성·썸네일·사진)
  python cleanup_media.py --delete --clips      # 롱폼 클립(clips/)도 삭제
  python cleanup_media.py --delete --rejected   # 폐기(rejected) 소재 파일도 삭제
  python cleanup_media.py --delete --indexes 3,5-9   # 지정한 번호만

지우지 않는 것: facts_db.json(소재·대본), my_images/(내가 고른 사진), 롱폼 영상(longform_out 등).
삭제 후 이 소재를 다시 만들려면 이미지부터 다시 받아야 한다 (대본은 DB에 그대로 있음).
"""
import argparse, json, shutil
from pathlib import Path

BASE = Path(__file__).resolve().parent
DIRS = ["videos", "audio", "thumbnails", "visuals"]
CLIP_DIRS = ["clips"]


def _size(p):
    try:
        if p.is_file():
            return p.stat().st_size
        return sum(f.stat().st_size for f in p.rglob("*") if f.is_file())
    except OSError:
        return 0


def parse_idx(s):
    out = set()
    for part in str(s or "").replace(" ", "").split(","):
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            out.update(range(int(a), int(b) + 1))
        else:
            out.add(int(part))
    return out


def targets(db, include_rejected=False, indexes=None, clips=False):
    """-> [(idx, label, [Path...], bytes)] 용량 큰 순"""
    dirs = DIRS + (CLIP_DIRS if clips else [])
    found = {}
    for d in dirs:
        root = BASE / d
        if not root.is_dir():
            continue
        for p in root.iterdir():
            n = p.name[:4]
            if n.isdigit() and p.name[4:5] == "_":
                found.setdefault(int(n), []).append(p)
    rows = []
    for i, f in enumerate(db):
        if indexes is not None and i not in indexes:
            continue
        done = bool(f.get("youtube_id"))
        rej = f.get("status") == "rejected"
        if not (done or (include_rejected and rej)):
            continue
        ps = found.get(i, [])
        if not ps:
            continue
        rows.append((i, f.get("label") or f.get("country") or "", ps, sum(_size(p) for p in ps)))
    rows.sort(key=lambda r: -r[3])
    return rows


def fmt(b):
    return f"{b/1024/1024:,.0f} MB" if b < 1024**3 else f"{b/1024**3:,.2f} GB"


def folder_sizes():
    return {d: _size(BASE / d) for d in DIRS + CLIP_DIRS + ["my_images"] if (BASE / d).exists()}


def delete(rows):
    freed = n = 0
    for _, _, ps, b in rows:
        for p in ps:
            try:
                shutil.rmtree(p) if p.is_dir() else p.unlink()
                n += 1
            except OSError as e:
                print(f"  삭제 실패 {p.name}: {e}")
        freed += b
    return n, freed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--delete", action="store_true")
    ap.add_argument("--clips", action="store_true")
    ap.add_argument("--rejected", action="store_true")
    ap.add_argument("--indexes", default="")
    a = ap.parse_args()
    db = json.loads((BASE / "facts_db.json").read_text(encoding="utf-8"))
    print("폴더별 용량:")
    for d, b in folder_sizes().items():
        print(f"  {d:<12}{fmt(b):>12}")
    rows = targets(db, a.rejected, parse_idx(a.indexes) if a.indexes else None, a.clips)
    tot = sum(r[3] for r in rows)
    print(f"\n정리 대상 {len(rows)}개 소재 / {fmt(tot)}")
    for i, lb, ps, b in rows[:15]:
        print(f"  [{i}] {lb[:30]:<30}{fmt(b):>10}")
    if len(rows) > 15:
        print(f"  … 외 {len(rows)-15}개")
    if a.delete and rows:
        n, freed = delete(rows)
        print(f"\n✅ 파일/폴더 {n}개 삭제, {fmt(freed)} 확보")
    elif not a.delete:
        print("\n(미리보기입니다. 지우려면 --delete)")


if __name__ == "__main__":
    main()
