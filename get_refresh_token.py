# 한 번만 PC에서 실행: python get_refresh_token.py client_secret.json
# 출력된 refresh_token을 GitHub Secrets(YT_REFRESH_TOKEN)에 저장하세요.
# 업로드 + 영상 목록 + 분석(조회수·시청 지속률) 읽기 권한을 한 번에 받습니다. 채널(계정)마다 따로 실행하세요.
import sys
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
]
flow = InstalledAppFlow.from_client_secrets_file(sys.argv[1], SCOPES)
creds = flow.run_local_server(port=0, access_type="offline", prompt="consent")
print("\nYT_REFRESH_TOKEN =", creds.refresh_token)
print("승인 화면에서 '유튜브 분석 보기' 권한까지 체크했는지 확인하세요.")
