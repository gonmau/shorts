# 한 번만 PC에서 실행: python get_refresh_token.py client_secret.json
# 출력된 refresh_token을 GitHub Secrets(YT_REFRESH_TOKEN)에 저장하세요.
import sys
from google_auth_oauthlib.flow import InstalledAppFlow

flow = InstalledAppFlow.from_client_secrets_file(
    sys.argv[1], ["https://www.googleapis.com/auth/youtube.upload"])
creds = flow.run_local_server(port=0, access_type="offline", prompt="consent")
print("\nYT_REFRESH_TOKEN =", creds.refresh_token)
