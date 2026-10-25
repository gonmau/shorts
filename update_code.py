# -*- coding: utf-8 -*-
"""GitHub 저장소의 최신 코드를 이 폴더에 받아 덮어쓴다 (zip 풀어서 넣을 필요 없음).

  python update_code.py            # 바뀐 코드 파일만 받아서 덮어씀 (원래 파일은 _backup/ 에 보관)
  python update_code.py --check    # 무엇이 바뀌는지만 보여줌 (아무것도 쓰지 않음)
  python update_code.py --push     # 반대로, 이 PC의 코드를 GitHub 저장소에 올림 (GITHUB_TOKEN 필요, 채널이 다르면 멈춤)
  python update_code.py --repo gonmau/shorts --branch main

- 받는 것: 폴더 최상위의 *.py, requirements.txt (+ local_ui.py). 소재 DB, 이력, 설정, 토큰, 영상 등 데이터 파일은 절대 건드리지 않습니다.
- 채널 안전장치: 이 폴더가 한국어 채널인데 영어 저장소 코드가 오는 것처럼 채널이 다르면 멈춥니다 (--force 로만 무시).
- 비공개 저장소면 GITHUB_TOKEN 환경변수가 필요합니다. 끝나면 UI(bat)를 다시 실행하세요."""
import argparse
import base64
import hashlib
import json
import os
import shutil
import sys
import time
from pathlib import Path

import requests

BASE = Path(__file__).resolve().parent
KEEP_BACKUPS = 5


def _utf8():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def local_channel():
    """이 폴더의 채널 'ko' / 'en' / None(판별 불가). local_ui.py·longform 과 같은 규칙"""
    has_en, has_ko = (BASE / "generate_topics.py").exists(), (BASE / "generate_culture_facts.py").exists()
    if has_en and has_ko:
        try:
            return "en" if (BASE / "channel.txt").read_text(encoding="utf-8").strip().lower() == "en" else "ko"
        except Exception:
            return None
    return "en" if has_en else ("ko" if has_ko else None)


def remote_channel(names):
    en, ko = "generate_topics.py" in names, "generate_culture_facts.py" in names
    return "en" if en and not ko else ("ko" if ko and not en else None)


def default_repo(ch):
    try:
        r = json.load(open(BASE / "tts_settings.json", encoding="utf-8")).get("gh_repo")
        if r:
            return r
    except Exception:
        pass
    return "gonmau/shortsEN" if ch == "en" else "gonmau/shorts"


def blob_sha(path):
    data = Path(path).read_bytes()
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def wanted(path):
    return "/" not in path and (path.endswith(".py") or path == "requirements.txt")


def fetch_tree(repo, branch, h):
    r = requests.get(f"https://api.github.com/repos/{repo}/git/trees/{branch}", params={"recursive": "0"}, headers=h, timeout=60)
    if r.status_code == 404:
        raise SystemExit(f"저장소/브랜치를 찾을 수 없습니다 ({repo}@{branch}). 비공개면 GITHUB_TOKEN 환경변수를 설정하세요.")
    r.raise_for_status()
    return {t["path"]: t["sha"] for t in r.json().get("tree", []) if t.get("type") == "blob"}


def main():
    _utf8()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo")
    ap.add_argument("--branch", default="main")
    ap.add_argument("--push", action="store_true", help="PC의 코드(*.py, requirements.txt, .github/workflows/*.yml, .gitignore)를 GitHub에 올림")
    ap.add_argument("--check", action="store_true", help="바뀔 파일만 보여주고 쓰지 않음")
    ap.add_argument("--quiet", action="store_true", help="--check 와 함께: 바뀐 게 있을 때만 한 줄 출력 (UI 시작 점검용)")
    ap.add_argument("--force", action="store_true", help="채널이 달라도 진행 (권장하지 않음)")
    a = ap.parse_args()
    ch = local_channel()
    repo = a.repo or default_repo(ch)
    tok = os.environ.get("GITHUB_TOKEN", "").strip()
    h = {"Accept": "application/vnd.github+json", **({"Authorization": f"Bearer {tok}"} if tok else {})}
    tree = fetch_tree(repo, a.branch, h)
    rch = remote_channel(tree)
    if ch and rch and ch != rch and not a.force:
        raise SystemExit(f"⛔ 채널이 다릅니다: 이 폴더는 {'한국어' if ch == 'ko' else '영어'} 채널인데 {repo} 는 {'한국어' if rch == 'ko' else '영어'} 채널 코드입니다. 저장소 이름을 확인하세요. (무시하려면 --force)")
    if a.push:
        if not tok:
            raise SystemExit("GITHUB_TOKEN 환경변수가 없습니다 (해당 저장소 Contents 읽기/쓰기, workflow 파일도 올리려면 workflow 권한).")
        from gh_push import push_file
        files = [p for p in sorted(os.listdir(BASE)) if wanted(p)] + [str(x.relative_to(BASE)).replace("\\", "/") for x in sorted((BASE / ".github" / "workflows").glob("*.yml"))] \
            + ([".gitignore"] if (BASE / ".gitignore").exists() else [])
        n = bad = 0
        for p in files:
            if tree.get(p) == blob_sha(BASE / p):
                continue
            try:
                if push_file(repo, a.branch, tok, p, msg=f"update {p} from PC") == "pushed":
                    print(f"  ⬆ {p}")
                    n += 1
            except Exception as e:
                bad += 1
                print(f"  ✖ {p}: {type(e).__name__}: {str(e)[:120]}")
        print(f"✅ GitHub에 {n}개 파일 올림" + (f", 실패 {bad}개 (workflow 파일은 토큰에 workflow 권한 필요)" if bad else "") if n or bad else f"✅ GitHub와 같아 올릴 게 없습니다 ({repo})")
        return
    todo = []
    for p, sha in sorted(tree.items()):
        if not wanted(p):
            continue
        f = BASE / p
        if not f.exists():
            todo.append((p, sha, "새 파일"))
        elif blob_sha(f) != sha:
            todo.append((p, sha, "변경"))
    if not todo:
        if not a.quiet:
            print(f"✅ 이미 최신입니다 ({repo}@{a.branch})")
        return
    if a.check:
        if a.quiet:
            print(f"새 코드 {len(todo)}개 있음 ({', '.join(p for p, _, _ in todo[:4])}{'…' if len(todo) > 4 else ''})")
        else:
            print(f"업데이트할 파일 {len(todo)}개 ({repo}@{a.branch}):")
            for p, _, why in todo:
                print(f"  - {p} ({why})")
        return
    bk = BASE / "_backup" / time.strftime("%Y%m%d_%H%M%S")
    restart = False
    for p, sha, why in todo:
        r = requests.get(f"https://api.github.com/repos/{repo}/git/blobs/{sha}", headers=h, timeout=60)
        r.raise_for_status()
        data = base64.b64decode(r.json()["content"])
        f = BASE / p
        if f.exists():
            bk.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, bk / p)
        tmp = f.with_name(f.name + ".new")
        tmp.write_bytes(data)
        os.replace(tmp, f)
        restart = True
        print(f"  ✔ {p} ({why})")
    olds = sorted([d for d in (BASE / "_backup").glob("*") if d.is_dir()]) if (BASE / "_backup").exists() else []
    for d in olds[:-KEEP_BACKUPS]:
        shutil.rmtree(d, ignore_errors=True)
    print(f"✅ {len(todo)}개 파일을 업데이트했습니다. 이전 파일은 {bk.name if bk.exists() else '(없음)'} 에 보관" + ("\n⚠️ UI를 쓰고 있다면 창을 닫고 bat을 다시 실행하세요." if restart else ""))
    try:
        import history
        history.add("코드업데이트", f"{repo}: {len(todo)}개 ({', '.join(p for p, _, _ in todo[:6])})", "success", None, "")
    except Exception:
        pass


if __name__ == "__main__":
    main()
