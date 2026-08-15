import os
import io
import time
import datetime
import urllib.request
import arxiv
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from google.oauth2.service_account import Credentials

# ================= 設定 =================
SERVICE_ACCOUNT_FILE = "service_account.json"  # GCPで作成した認証JSONファイル
TARGET_FOLDER_NAME = "V2X_SemCom_Research"     # 対象のGoogle Driveフォルダ名

# 車両 × セマンティック通信の検索クエリ
SEARCH_QUERY = '(ti:"semantic" OR abs:"semantic") AND (ti:"V2X" OR ti:"vehicular" OR ti:"autonomous driving" OR abs:"V2X" OR abs:"vehicular")'

MAX_SEARCH_RESULTS = 10      # 1回の巡回でチェックする最新論文数
DOWNLOAD_INTERVAL = 10.0     # arXiv負荷軽減のための待機秒数（10秒以上を厳守）
TARGET_MINUTE = 20           # 実行する分（毎時20分）
# =======================================

def get_drive_service():
    """Google Drive APIクライアントの初期化"""
    creds = Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE,
        scopes=["https://www.googleapis.com/auth/drive"]
    )
    return build("drive", "v3", credentials=creds)

def find_folder_id_by_name(drive_service, folder_name):
    """フォルダ名からGoogle Drive上のフォルダIDを自動取得"""
    query = f"name = '{folder_name}' and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    results = drive_service.files().list(q=query, fields="files(id, name)").execute()
    files = results.get("files", [])
    
    if not files:
        raise FileNotFoundError(f"Google Drive上にフォルダ '{folder_name}' が見つかりませんでした。共有設定を確認してください。")
    
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

def run_crawl_and_upload(drive_service, folder_id):
    """毎時20分に実行されるクローラー本体"""
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"\n[{now_str}] 毎時20分の定期チェックを開始します...")

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

    for result in results:
        raw_id = result.get_short_id()
        base_id = raw_id.split("v")[0]

        # 重複チェック
        if base_id in existing_ids:
            continue

        print(f"-> 新着論文を発見: [{base_id}] {result.title[:45]}...")
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

            print(f"   ✓ Google Drive ({TARGET_FOLDER_NAME}) へ保存完了: {filename}")
            existing_ids.add(base_id)
            downloaded += 1

        except Exception as e:
            print(f"   ✗ ダウンロード失敗 ({base_id}): {e}")

    print(f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 巡回完了 (新規保存: {downloaded} 件)")

def sleep_until_next_target_minute(target_minute):
    """次の毎時 XX 分 00 秒までの秒数を計算してスリープ"""
    now = datetime.datetime.now()
    # 次の目標時刻を計算
    if now.minute < target_minute:
        next_run = now.replace(minute=target_minute, second=0, microsecond=0)
    else:
        # 次の時間の目標分
        next_run = (now + datetime.timedelta(hours=1)).replace(minute=target_minute, second=0, microsecond=0)
    
    sleep_seconds = (next_run - now).total_seconds()
    print(f"次回実行時刻: {next_run.strftime('%Y-%m-%d %H:%M:%S')} (約 {int(sleep_seconds // 60)} 分待機)")
    time.sleep(sleep_seconds)

def main():
    print("=== V2X×SemCom 論文自動取得デーモンを起動しました ===")
    print(f"実行スケジュール: 毎時 {TARGET_MINUTE} 分")
    
    drive_service = get_drive_service()
    folder_id = find_folder_id_by_name(drive_service, TARGET_FOLDER_NAME)
    print(f"ターゲットフォルダIDを確認: {folder_id}")

    # 初回起動時に即時1回実行するか、次の20分を待つか
    # ここでは即座に初回チェックを行い、以降20分周期に乗せます
    try:
        run_crawl_and_upload(drive_service, folder_id)
    except Exception as e:
        print(f"[警告] 初回実行エラー: {e}")

    while True:
        try:
            sleep_until_next_target_minute(TARGET_MINUTE)
            run_crawl_and_upload(drive_service, folder_id)
        except Exception as e:
            print(f"[警告] ループ実行中にエラーが発生しました（次回再試行）: {e}")
            time.sleep(60)

if __name__ == "__main__":
    main()