"""장면 이미지 보관/복원 (GitHub Actions 캐시용). 같은 소재를 다시 만들거나 랩 버전을 만들 때 이미지(Cloudflare/Pixabay)를 다시 받지 않게 한다.
  python img_cache.py restore   # img_cache/<소재번호>/scene_NN.jpg -> visuals 폴더에 scene_NN.png (없는 것만)
  python img_cache.py save      # visuals 폴더의 scene_NN.png -> img_cache/<소재번호>/ (JPEG q90, 새 것만) + 오래된 것 정리
랩 소재는 원본 번호(rap_of) 아래에 보관 -> 랩 버전을 만들 때 원본 이미지를 그대로 쓴다."""
import shutil, sys
from pathlib import Path
from PIL import Image

BASE = Path(__file__).resolve().parent
CACHE = BASE / "img_cache"
KEEP = 80          # 소재 80개 분량만 보관 (대략 200MB 이내, GitHub 캐시 한도 10GB 안에서 가장 오래 안 쓴 것부터 자동 삭제)


def restore_item(src_dir, dst_dir):
    n = 0
    dst_dir.mkdir(parents=True, exist_ok=True)
    for f in sorted(Path(src_dir).glob("scene_*.jpg")):
        out = dst_dir / (f.stem + ".png")
        if not out.exists():
            Image.open(f).convert("RGB").save(out); n += 1
    return n


def restore():
    from common import load_db, visual_dir
    db = load_db(); tot = 0
    for d in sorted(CACHE.glob("*")) if CACHE.exists() else []:
        if d.name.isdigit() and int(d.name) < len(db):
            tot += restore_item(d, visual_dir(BASE, int(d.name), db[int(d.name)]))
    print(f"이미지 캐시 복원: {tot}장")


def save():
    from common import load_db, visual_dir
    db = load_db(); new = 0
    for i, it in enumerate(db):
        key = it.get("rap_of") if it.get("rap") and it.get("rap_of") is not None else i
        fol = visual_dir(BASE, i, it)
        files = sorted(fol.glob("scene_*.png")) if fol.exists() else []
        if not files: continue
        d = CACHE / str(key)
        if d.exists() and len(list(d.glob("scene_*.jpg"))) >= len(files): continue
        d.mkdir(parents=True, exist_ok=True)
        for f in files:
            out = d / (f.stem + ".jpg")
            if not out.exists():
                Image.open(f).convert("RGB").save(out, "JPEG", quality=90); new += 1
    dirs = sorted((x for x in CACHE.glob("*") if x.is_dir()), key=lambda p: p.stat().st_mtime) if CACHE.exists() else []
    for old in dirs[:-KEEP]: shutil.rmtree(old, ignore_errors=True)
    print(f"이미지 캐시 저장: 새 {new}장, 소재 {min(len(dirs), KEEP)}개 보관")


if __name__ == "__main__":
    {"restore": restore, "save": save}[sys.argv[1] if len(sys.argv) > 1 else "save"]()
