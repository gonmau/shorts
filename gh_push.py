# -*- coding: utf-8 -*-
"""로컬 파일(기본 longform_db.json)을 GitHub 저장소에 그대로 커밋한다. (GITHUB_TOKEN 필요: 해당 저장소 Contents 읽기/쓰기)
쇼츠 DB(facts_db.json)는 이 스크립트가 아니라 `sync_db.py --apply --push` 로 병합해서 올립니다.
  python gh_push.py --repo gonmau/shorts [--file longform_db.json ...] [--branch main]
내용이 GitHub와 같으면 커밋하지 않습니다."""
import argparse
import base64
import os
import sys

import requests


def _utf8_out():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def push_file(repo, branch, token, path, msg=None):
    h = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    url = f"https://api.github.com/repos/{repo}/contents/{path}"
    data = open(path, "rb").read()
    r = requests.get(url, params={"ref": branch}, headers=h, timeout=60)
    sha = None
    if r.status_code == 200:
        meta = r.json()
        sha = meta.get("sha")
        if meta.get("content") and base64.b64decode(meta["content"]) == data:
            return "same"
    elif r.status_code != 404:
        r.raise_for_status()
    body = {"message": msg or f"update {path} from local UI", "branch": branch, "content": base64.b64encode(data).decode()}
    if sha:
        body["sha"] = sha
    r = requests.put(url, json=body, headers=h, timeout=120)
    r.raise_for_status()
    return "pushed"


def main():
    _utf8_out()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", required=True)
    ap.add_argument("--branch", default="main")
    ap.add_argument("--file", action="append", default=None)
    a = ap.parse_args()
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if not token:
        sys.exit("GITHUB_TOKEN 환경변수가 없습니다.")
    bad = 0
    for f in (a.file or ["longform_db.json"]):
        if not os.path.exists(f):
            print(f"{f}: 파일이 없어 건너뜀")
            continue
        try:
            print(f"{f}: " + {"same": "GitHub와 같아 변경 없음", "pushed": "GitHub에 올렸습니다"}[push_file(a.repo, a.branch, token, f)])
        except Exception as e:
            bad += 1
            print(f"{f}: 실패 ({type(e).__name__}: {e})")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
