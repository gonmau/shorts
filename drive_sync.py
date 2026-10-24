# -*- coding: utf-8 -*-
"""작업 결과물(썸네일/이미지/음성/영상/자막/롱폼/DB)을 구글 드라이브와 주고받는다. (PC용, 선택 기능)

  1회 인증:  python drive_sync.py auth client_secret.json        -> token_drive.json 저장 (드라이브 'drive.file' 권한: 이 프로그램이 만든 파일만 접근)
  올리기:    python drive_sync.py push [--only thumbs,subs,audio,images,videos,longform,db] [--index 100-120,130] [--dry-run]
  받기:      python drive_sync.py pull [--only ...] [--index ...] [--dry-run]     (다른 PC/외부에서 이어서 작업할 때. DB는 받지 않음 - DB는 GitHub로)
  현황:      python drive_sync.py status

- 드라이브에는 '<루트 폴더>/<로컬과 같은 경로>' 로 올라갑니다 (루트 기본값: 한국어 culture-shorts-ko / 영어 korea-shorts-en, --root 또는 DRIVE_ROOT 로 변경).
- drive_manifest.json 에 올린 파일의 크기/수정시각/드라이브 ID를 기록해, 바뀐 파일만 올립니다 (안 바뀌면 API 호출 없음).
- 다른 PC에서 받으려면 같은 token_drive.json 과 같은 client_secret 이 있어야 합니다 (drive.file 권한은 이 프로그램이 만든 파일만 보입니다).
- 실패한 파일은 건너뛰고 계속하며, 마지막에 개수를 알려줍니다.
- GitHub Actions에서도 같은 드라이브 폴더에 올립니다: Secrets DRIVE_CLIENT_ID / DRIVE_CLIENT_SECRET / DRIVE_REFRESH_TOKEN
  (token_drive.json 안의 client_id, client_secret, refresh_token 값). 워크플로의 '구글 드라이브 저장' 단계가 사용합니다.
"""
import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent
SCOPES = ["https://www.googleapis.com/auth/drive.file"]
TOKEN = BASE / "token_drive.json"
MANIFEST = BASE / "drive_manifest.json"
FOLDER = "application/vnd.google-apps.folder"
CATS = ["thumbs", "subs", "audio", "images", "videos", "longform", "db"]
LABEL = {"thumbs": "썸네일", "subs": "자막(SRT)", "audio": "음성", "images": "이미지", "videos": "영상", "longform": "롱폼", "db": "DB/설정"}
DB_FILES = ["facts_db.json", "longform_db.json", "tts_settings.json", "review.txt"]


def default_root():
    return "culture-shorts-ko" if (BASE / "generate_culture_facts.py").exists() else "korea-shorts-en"


def _skip(p):
    return any(s.startswith(".") or s == "__pycache__" for s in p.parts) or p.suffix in (".tmp", ".part")


def local_files(cats):
    """-> {상대경로(posix): Path}"""
    out = {}

    def add(sub, pat="*"):
        d = BASE / sub
        if d.is_dir():
            for p in d.rglob(pat):
                if p.is_file() and not _skip(p.relative_to(BASE)):
                    out[p.relative_to(BASE).as_posix()] = p
    if "thumbs" in cats:
        add("thumbnails")
    if "subs" in cats:
        add("videos", "*.srt")
    if "audio" in cats:
        add("audio")
    if "images" in cats:
        add("visuals")
    if "videos" in cats:
        add("videos", "*.mp4")
    if "longform" in cats:
        add("longform_out")
    if "db" in cats:
        for n in DB_FILES:
            if (BASE / n).is_file():
                out[n] = BASE / n
    return out


def parse_index(text):
    s = set()
    for part in re.split(r"[,\s]+", (text or "").strip()):
        m = re.fullmatch(r"(\d+)-(\d+)", part)
        if m:
            s.update(range(int(m.group(1)), int(m.group(2)) + 1))
        elif part.isdigit():
            s.add(int(part))
    return s


def index_of(rel):
    """경로 안의 'NNNN_국가' 패턴에서 소재 번호. 없으면 None (DB 등)"""
    for part in rel.split("/"):
        m = re.match(r"^(\d{1,5})_", part)
        if m:
            return int(m.group(1))
    return None


def load_manifest():
    try:
        d = json.loads(MANIFEST.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def save_manifest(m):
    tmp = MANIFEST.with_suffix(".tmp")
    tmp.write_text(json.dumps(m, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(MANIFEST)


def sig(p):
    st = p.stat()
    return {"size": st.st_size, "mtime": int(st.st_mtime)}


# ---------------------------------------------------------------- 드라이브 (실제)
class GDrive:
    def __init__(self):
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
        env_ok = all(os.environ.get(k, "").strip() for k in ("DRIVE_REFRESH_TOKEN", "DRIVE_CLIENT_ID", "DRIVE_CLIENT_SECRET"))
        if env_ok:   # GitHub Actions: Secrets의 값으로 인증 (token_drive.json 안의 refresh_token / client_id / client_secret)
            creds = Credentials(token=None, refresh_token=os.environ["DRIVE_REFRESH_TOKEN"].strip(), token_uri="https://oauth2.googleapis.com/token",
                                client_id=os.environ["DRIVE_CLIENT_ID"].strip(), client_secret=os.environ["DRIVE_CLIENT_SECRET"].strip(), scopes=SCOPES)
            creds.refresh(Request())
        else:
            if not TOKEN.exists():
                raise SystemExit("token_drive.json 이 없습니다. 먼저 `python drive_sync.py auth client_secret.json` 을 실행하세요.")
            creds = Credentials.from_authorized_user_file(str(TOKEN), SCOPES)
            if not creds.valid:
                creds.refresh(Request())
                TOKEN.write_text(creds.to_json(), encoding="utf-8")
        self.svc = build("drive", "v3", credentials=creds, cache_discovery=False)

    def _do(self, req):
        from googleapiclient.errors import HttpError
        for k in range(4):
            try:
                return req.execute()
            except HttpError as e:
                if getattr(e.resp, "status", 0) in (429, 500, 502, 503, 504) and k < 3:
                    time.sleep(2 ** (k + 1))
                    continue
                raise

    def find(self, parent, name, folder=False):
        q = f"name='{name.replace(chr(39), chr(92) + chr(39))}' and trashed=false"
        q += f" and '{parent}' in parents" if parent else ""
        q += f" and mimeType{'=' if folder else '!='}'{FOLDER}'"
        r = self._do(self.svc.files().list(q=q, fields="files(id,size,appProperties)", pageSize=5))
        f = r.get("files", [])
        return f[0] if f else None

    def mkdir(self, parent, name):
        body = {"name": name, "mimeType": FOLDER, **({"parents": [parent]} if parent else {})}
        return self._do(self.svc.files().create(body=body, fields="id"))["id"]

    def children(self, parent):
        out, tok = [], None
        while True:
            r = self._do(self.svc.files().list(q=f"'{parent}' in parents and trashed=false",
                                               fields="nextPageToken, files(id,name,mimeType,size)", pageSize=1000, pageToken=tok))
            out += r.get("files", [])
            tok = r.get("nextPageToken")
            if not tok:
                return out

    def upload(self, parent, name, path, existing_id=None):
        from googleapiclient.http import MediaFileUpload
        media = MediaFileUpload(str(path), resumable=True, chunksize=8 * 1024 * 1024)
        if existing_id:
            req = self.svc.files().update(fileId=existing_id, media_body=media, fields="id")
        else:
            req = self.svc.files().create(body={"name": name, "parents": [parent]}, media_body=media, fields="id")
        resp = None
        for k in range(5):
            try:
                while resp is None:
                    _, resp = req.next_chunk()
                return resp["id"]
            except Exception as e:
                if k == 4:
                    raise
                time.sleep(2 ** (k + 1))
        return resp["id"]

    def download(self, file_id, dest):
        import io
        from googleapiclient.http import MediaIoBaseDownload
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(dest.name + ".part")
        with open(tmp, "wb") as f:
            dl = MediaIoBaseDownload(f, self.svc.files().get_media(fileId=file_id), chunksize=8 * 1024 * 1024)
            done = False
            while not done:
                _, done = dl.next_chunk()
        tmp.replace(dest)


# ---------------------------------------------------------------- 동기화 로직 (원격 객체를 받아 테스트 가능)
def ensure_folder(remote, man, rel_dir, root_id):
    """상대 폴더 경로 -> 드라이브 폴더 ID (없으면 만든다)"""
    if not rel_dir:
        return root_id
    fold = man.setdefault("folders", {})
    if rel_dir in fold:
        return fold[rel_dir]
    parent_rel, _, name = rel_dir.rpartition("/")
    parent = ensure_folder(remote, man, parent_rel, root_id)
    f = remote.find(parent, name, folder=True)
    fid = f["id"] if f else remote.mkdir(parent, name)
    fold[rel_dir] = fid
    return fid


def get_root(remote, man, root_name):
    if man.get("root_name") == root_name and man.get("root_id"):
        return man["root_id"]
    f = remote.find(None, root_name, folder=True)
    rid = f["id"] if f else remote.mkdir(None, root_name)
    man.clear()
    man.update({"root_name": root_name, "root_id": rid, "folders": {}, "files": {}})
    return rid


def want(rel, idxs):
    if not idxs:
        return True
    n = index_of(rel)
    return n is None or n in idxs


def push(remote, cats, idxs, root_name, dry=False, log=print):
    man = load_manifest()
    files = {r: p for r, p in local_files(cats).items() if want(r, idxs)}
    todo = []
    for rel, p in sorted(files.items()):
        rec = (man.get("files") or {}).get(rel)
        if man.get("root_name") == root_name and rec and rec.get("size") == sig(p)["size"] and rec.get("mtime") == sig(p)["mtime"]:
            continue
        todo.append(rel)
    mb = sum(files[r].stat().st_size for r in todo) / 1e6
    log(f"올릴 파일 {len(todo)}개 ({mb:.0f}MB) / 대상 {len(files)}개 (이미 올라간 {len(files) - len(todo)}개는 건너뜀)")
    if dry or not todo:
        return {"uploaded": 0, "failed": 0, "todo": len(todo)}
    root_id = get_root(remote, man, root_name)
    ok = fail = 0
    for k, rel in enumerate(todo, 1):
        p = files[rel]
        try:
            parent = ensure_folder(remote, man, rel.rpartition("/")[0], root_id)
            rec = man.setdefault("files", {}).get(rel)
            fid = rec.get("id") if rec else None
            if not fid:
                ex = remote.find(parent, p.name)
                fid = ex["id"] if ex else None
            nid = remote.upload(parent, p.name, p, fid)
            man["files"][rel] = {"id": nid, **sig(p)}
            ok += 1
            log(f"  [{k}/{len(todo)}] 올림: {rel}")
            if ok % 10 == 0:
                save_manifest(man)
        except Exception as e:
            fail += 1
            log(f"  [{k}/{len(todo)}] 실패: {rel} ({type(e).__name__}: {str(e)[:120]})")
    save_manifest(man)
    log(f"완료: 올림 {ok}개 · 실패 {fail}개" + (" (실패한 파일은 다시 실행하면 이어서 올립니다)" if fail else ""))
    return {"uploaded": ok, "failed": fail, "todo": len(todo)}


def walk_remote(remote, folder_id, prefix=""):
    for c in remote.children(folder_id):
        rel = f"{prefix}{c['name']}"
        if c.get("mimeType") == FOLDER:
            yield from walk_remote(remote, c["id"], rel + "/")
        else:
            yield rel, c


def pull(remote, cats, idxs, root_name, dry=False, log=print):
    cats = [c for c in cats if c != "db"]
    man = load_manifest()
    f = remote.find(None, root_name, folder=True)
    if not f:
        log(f"드라이브에 '{root_name}' 폴더가 없습니다. 먼저 다른 PC에서 올리세요.")
        return {"downloaded": 0, "failed": 0, "todo": 0}
    allowed = set(local_files_patterns(cats))
    todo = []
    for rel, c in walk_remote(remote, f["id"]):
        if not any(rel.startswith(pre) and rel.endswith(suf) for pre, suf in allowed) or not want(rel, idxs):
            continue
        dest = BASE / rel
        size = int(c.get("size") or 0)
        if dest.exists() and dest.stat().st_size == size:
            continue
        todo.append((rel, c, size))
    log(f"받을 파일 {len(todo)}개 ({sum(t[2] for t in todo) / 1e6:.0f}MB)")
    if dry or not todo:
        return {"downloaded": 0, "failed": 0, "todo": len(todo)}
    if man.get("root_name") != root_name:
        man.clear()
        man.update({"root_name": root_name, "root_id": f["id"], "folders": {}, "files": {}})
    ok = fail = 0
    for k, (rel, c, size) in enumerate(todo, 1):
        try:
            remote.download(c["id"], BASE / rel)
            man.setdefault("files", {})[rel] = {"id": c["id"], **sig(BASE / rel)}
            ok += 1
            log(f"  [{k}/{len(todo)}] 받음: {rel}")
        except Exception as e:
            fail += 1
            log(f"  [{k}/{len(todo)}] 실패: {rel} ({type(e).__name__}: {str(e)[:120]})")
    save_manifest(man)
    log(f"완료: 받음 {ok}개 · 실패 {fail}개")
    return {"downloaded": ok, "failed": fail, "todo": len(todo)}


def local_files_patterns(cats):
    """pull에서 받을 수 있는 (경로 접두어, 접미어) 목록"""
    pat = {"thumbs": [("thumbnails/", "")], "subs": [("videos/", ".srt")], "audio": [("audio/", "")],
           "images": [("visuals/", "")], "videos": [("videos/", ".mp4")], "longform": [("longform_out/", "")]}
    return [x for c in cats for x in pat.get(c, [])]


def auth(secret):
    from google_auth_oauthlib.flow import InstalledAppFlow
    flow = InstalledAppFlow.from_client_secrets_file(secret, SCOPES)
    creds = flow.run_local_server(port=0, access_type="offline", prompt="consent")
    TOKEN.write_text(creds.to_json(), encoding="utf-8")
    print(f"저장했습니다: {TOKEN}\n(Google Cloud 콘솔에서 'Google Drive API'를 사용 설정해야 업로드가 됩니다)")


def _utf8_out():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def main():
    _utf8_out()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["auth", "push", "pull", "status"])
    ap.add_argument("secret", nargs="?", help="auth 일 때 client_secret.json 경로")
    ap.add_argument("--only", default=",".join(CATS), help="쉼표 목록: " + ",".join(CATS))
    ap.add_argument("--index", default="", help="소재 번호 범위 (예: 100-120,130). 비우면 전체")
    ap.add_argument("--root", default=os.environ.get("DRIVE_ROOT", "") or default_root())
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    if a.cmd == "auth":
        if not a.secret:
            raise SystemExit("사용법: python drive_sync.py auth client_secret.json")
        return auth(a.secret)
    cats = [c.strip() for c in a.only.split(",") if c.strip() in CATS]
    if not cats:
        raise SystemExit("--only 에 올바른 종류가 없습니다: " + ",".join(CATS))
    idxs = parse_index(a.index)
    if a.cmd == "status":
        man = load_manifest()
        fl = local_files(cats)
        done = sum(1 for r, p in fl.items() if (man.get("files") or {}).get(r, {}).get("size") == p.stat().st_size)
        print(f"루트 폴더: {a.root} | 로컬 파일 {len(fl)}개 중 드라이브에 올라간 것 {done}개 | 인증 {'있음' if TOKEN.exists() else '없음 (auth 필요)'}")
        for c in cats:
            fc = local_files([c])
            d = sum(1 for r, p in fc.items() if (man.get('files') or {}).get(r, {}).get('size') == p.stat().st_size)
            print(f"  {LABEL[c]}: {len(fc)}개 중 {d}개 올라감")
        return
    remote = GDrive()
    res = (push if a.cmd == "push" else pull)(remote, cats, idxs, a.root, a.dry_run)
    if res.get("failed"):
        sys.exit(1)


if __name__ == "__main__":
    main()
