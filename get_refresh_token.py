# PC에서 한 번 실행: get_token.bat 더블클릭 (또는 python get_refresh_token.py client_secret.json)
# 받은 토큰을 .local_secrets.json 에 자동 저장합니다 → UI(업로드 버튼)가 바로 읽습니다. 환경변수(setx)는 필요 없습니다.
# GitHub Actions 에서 쓰려면 출력된 YT_REFRESH_TOKEN 을 GitHub Secrets 에도 넣으세요.
# 업로드 + 영상 목록 + 분석(조회수·시청 지속률) 읽기 권한을 한 번에 받습니다. 채널(계정)마다 따로 실행하세요.
import json
import os
import sys

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
    "https://www.googleapis.com/auth/youtube.force-ssl",   # 썸네일 자동 설정용
]
secret = sys.argv[1] if len(sys.argv) > 1 else "client_secret.json"
if not os.path.exists(secret):
    raise SystemExit(f"{secret} 파일이 없습니다. 구글 클라우드에서 받은 OAuth 클라이언트 JSON을 이 폴더에 client_secret.json 이름으로 두세요.")
flow = InstalledAppFlow.from_client_secrets_file(secret, SCOPES)
creds = flow.run_local_server(port=0, access_type="offline", prompt="consent")
print("\nYT_REFRESH_TOKEN =", creds.refresh_token)
try:
    sec = json.load(open(".local_secrets.json", encoding="utf-8"))
except Exception:
    sec = {}
sec.update(yt_refresh_token=creds.refresh_token, yt_client_id=creds.client_id, yt_client_secret=creds.client_secret)
json.dump(sec, open(".local_secrets.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("✔ .local_secrets.json 에 저장했습니다. UI(bat)를 다시 실행하면 업로드 버튼이 동작합니다.")
print("승인 화면에서 '유튜브 분석 보기' 권한까지 체크했는지 확인하세요.")
