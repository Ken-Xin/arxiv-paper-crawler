import os
import io
import time
import datetime
import urllib.request
import arxiv
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from google.oauth2.credentials import Credentials

# ================= 設定 =================
CLIENT_ID = os.environ.get("GDRIVE_CLIENT_ID")
CLIENT_SECRET = os.environ.get("GDRIVE_CLIENT_SECRET")
REFRESH_TOKEN = os.environ.get("GDRIVE_REFRESH_TOKEN")
TARGET_FOLDER_ID = os.environ.get("GDRIVE_FOLDER_ID")

SEARCH_QUERY = '(ti:"semantic" OR abs:"semantic") AND (ti:"V2X" OR ti:"vehicular" OR ti:"autonomous driving" OR abs:"V2X" OR abs:"vehicular")'
MAX_SEARCH_RESULTS = 10
DOWNLOAD_INTERVAL = 10.0
# =======================================

def get_drive_service():
    """OAuth 2.0 Credentials (Refresh Token) からDrive APIクライアントを初期化"""
    if not (CLIENT_ID and CLIENT_SECRET and REFRESH_TOKEN):
        raise ValueError("OAuth認証情報が設定されていません。")

    creds = Credentials(
        None,
        refresh_token=REFRESH_TOKEN,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        scopes=["https://www.googleapis.com/auth/drive.file"]
    )
    return build("drive", "v3", credentials=creds)

def get_existing_arxiv_ids(drive_service, folder_id):
    """指定フォルダ内の既存ファイルからarXiv IDを収集"""
    existing_ids = set()
    query = f"'{folder_id}' in parents and trashed = false"
    page_token = None
    
    while True:
        results = drive_service.files().list(
            q=query,
            fields="nextPageToken, files(name)",
            pageToken=page_token
        ).execute()
        
        for item in results.get("files", []):
            name = item.get("name", "")
            parts = name.split("_")
            if len(parts) > 1:
                existing_ids.add(parts[0].split("v")[0])
                
        page_token = results.get("nextPageToken")
        if not page_token:
            break
            
    return existing_ids

def main():
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{now_str}] arXiv 論文自動収集タスクを開始します...")

    drive_service = get_drive_service()
    folder_id = TARGET_FOLDER_ID
    print(f"ターゲットフォルダID: {folder_id}")

    existing_ids = get_existing_arxiv_ids(drive_service, folder_id)
    print(f"現在Drive内に存在する論文数: {len(existing_ids)} 件")

    client = arxiv.Client(
        page_size=MAX_SEARCH_RESULTS,
        delay_seconds=DOWNLOAD_INTERVAL,
        num_retries=3
    )
    search = arxiv.Search(
        query=SEARCH_QUERY,
        max_results=MAX_SEARCH_RESULTS,
        sort_by=arxiv.SortCriterion.SubmittedDate,
        sort_order=arxiv.SortOrder.Descending
    )

    downloaded = 0
    results = list(client.results(search))
    print(f"検索ヒット数: {len(results)} 件")

    for result in results:
        raw_id = result.get_short_id()
        base_id = raw_id.split("v")[0]

        if base_id in existing_ids:
            print(f"[スキップ (取得済み)]: {base_id} - {result.title[:40]}...")
            continue

        print(f"\n[新着ダウンロード開始]: {base_id} - {result.title}")
        safe_title = "".join(c for c in result.title if c.isalnum() or c in (' ', '_', '-')).rstrip()
        filename = f"{raw_id}_{safe_title[:50]}.pdf"

        print(f"   (arXivアクセス間隔として {DOWNLOAD_INTERVAL} 秒待機中...)")
        time.sleep(DOWNLOAD_INTERVAL)

        try:
            req = urllib.request.Request(
                result.pdf_url,
                headers={"User-Agent": "ArXiv-Research-Collector/1.0 (academic research)"}
            )
            with urllib.request.urlopen(req) as response:
                pdf_bytes = response.read()

            file_metadata = {
                "name": filename,
                "parents": [folder_id]
            }
            media = MediaIoBaseUpload(io.BytesIO(pdf_bytes), mimetype="application/pdf")
            drive_service.files().create(
                body=file_metadata,
                media_body=media,
                fields="id"
            ).execute()

            print(f"   ✓ Google Driveへ保存完了: {filename}")
            existing_ids.add(base_id)
            downloaded += 1

        except Exception as e:
            print(f"   ✗ ダウンロード失敗 ({base_id}): {e}")

    print(f"\n[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 実行完了 (新規保存: {downloaded} 件)")

if __name__ == "__main__":
    main()