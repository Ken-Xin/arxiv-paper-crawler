# get_token.py
from google_auth_oauthlib.flow import InstalledAppFlow

# ステップ1で取得した情報を入力
CLIENT_ID = "488590706418-ujt6jgmhahk9nhp47cdivj2ch4m66lb1.apps.googleusercontent.com"
CLIENT_SECRET = "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"

SCOPES = ['https://www.googleapis.com/auth/drive.file']

flow = InstalledAppFlow.from_client_config(
    {
        "installed": {
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    },
    scopes=SCOPES
)

creds = flow.run_local_server(port=0)
print("\n=== 以下のリフレッシュトークンをコピーしてください ===")
print(creds.refresh_token)