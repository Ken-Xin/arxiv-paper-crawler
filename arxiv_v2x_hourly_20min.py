import os
import io
import time
import json
import datetime
import urllib.request
import arxiv
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from google.oauth2.service_account import Credentials

# ================= 設定 =================
# GitHub Secrets からJSON文字列を取得
SERVICE_ACCOUNT_JSON_STR = os.environ.get("GDRIVE_SERVICE_ACCOUNT_JSON")
TARGET_FOLDER_NAME = "V2X_SemCom_Research"     # 対象のGoogle Driveフォルダ名

# 車両 × セマンティック通信の検索クエリ
SEARCH_QUERY = '(ti:"semantic" OR abs:"semantic") AND (ti:"V2X" OR ti:"vehicular" OR ti:"autonomous driving" OR abs:"V2X" OR abs:"vehicular")'

MAX_SEARCH_RESULTS = 10      # 1回の実行でチェックする最新論文数
DOWNLOAD_INTERVAL = 10.0     # arXiv負荷軽減のための待機秒数（10秒以上を厳守）
# =======================================

def get_drive_service():
    """環境変数のJSON文字列からGoogle Drive APIクライアントを初期化"""
    if not SERVICE_ACCOUNT_JSON_STR:
        raise ValueError("環境変数 GDRIVE_SERVICE_ACCOUNT_JSON が設定されていません。GitHub Secretsを確認してください。")
    
    info = json.loads(SERVICE_ACCOUNT_JSON_STR)
    creds = Credentials.from_service_account_info(
        info,
        scopes=["https://www.googleapis.com/auth/drive"]
    )
    return build("drive", "v3", credentials=creds)

def find_folder_id_by_name(drive_service, folder_name):
    """フォルダ名からGoogle Drive上のフォルダIDを取得"""
    query = f"name = '{folder_name}' and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    results = drive_service.files().list(q=query, fields="files(id, name)").execute()
    files = results.get("files", [])
    
    if not files:
        raise FileNotFoundError(f"Google Drive上にフォルダ '{folder_name}' が見つかりませんでした。サービスアカウントへの共有設定を確認してください。")
    
    return files[0]["id"]

def get_existing_arxiv_ids(drive_service, folder_id):
    """フォルダ内のファイル名から既存のarXiv IDを走査して重複を防止"""
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
                # バージョン表記(v1等)を除去したベースIDを記録
                existing_ids.add(parts[0].split("v")[0])
                
        page_token = results.get("nextPageToken")
        if not page_token:
            break
            
    return existing_ids

def main():
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{now_str}] arXiv 論文自動収集タスクを開始します...")

    drive_service = get_drive_service()
    folder_id = find_folder_id_by_name(drive_service, TARGET_FOLDER_NAME)
    print(f"ターゲットフォルダを確認: {TARGET_FOLDER_NAME} (ID: {folder_id})")

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

        # 重複チェック
        if base_id in existing_ids:
            print(f"[スキップ (取得済み)]: {base_id} - {result.title[:40]}...")
            continue

        print(f"\n[新着ダウンロード開始]: {base_id} - {result.title}")
        safe_title = "".join(c for c in result.title if c.isalnum() or c in (' ', '_', '-')).rstrip()
        filename = f"{raw_id}_{safe_title[:50]}.pdf"

        # arXiv規約遵守のためのウェイト
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