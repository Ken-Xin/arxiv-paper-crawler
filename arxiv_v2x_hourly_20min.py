import os
import io
import time
import datetime
import urllib.request
import arxiv
import math
import requests
from datetime import datetime as dt
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

def get_paper_metrics(arxiv_id):
    """Semantic Scholar APIを用いて被引用数とVenue・出版年を取得"""
    base_id = arxiv_id.split('v')[0]
    url = f"https://api.semanticscholar.org/graph/v1/paper/ARXIV:{base_id}?fields=citationCount,venue,publicationDate"
    
    try:
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            data = response.json()
            return {
                "citations": data.get("citationCount", 0),
                "venue": data.get("venue", "").lower(),
                "pub_year": int(data.get("publicationDate", "2000-01-01")[:4]) if data.get("publicationDate") else None
            }
    except Exception as e:
        print(f"   [APIエラー] 外部データ取得失敗: {e}")
    
    return {"citations": 0, "venue": "", "pub_year": None}

def calculate_score(metrics, current_year):
    """簡易スコアの算出とフィルタリング判定"""
    citations = metrics["citations"]
    venue = metrics["venue"]
    pub_year = metrics["pub_year"] or current_year
    
    # Recency Weight (例: 過去5年以内なら年数に応じて加点)
    age = current_year - pub_year
    recency_weight = max(0, 5 - age) 
    
    # Venue Weight (例: V2X/通信系のトップカンファレンスやジャーナルを優遇)
    venue_weight = 0
    premium_venues = ["ieee", "infocom", "globecom", "icc", "jsac", "tmc", "twc"]
    if any(pv in venue for pv in premium_venues):
        venue_weight = 3
        
    # スコア計算: venue_weight + log(citations+1) + recency_weight
    score = venue_weight + math.log1p(citations) + recency_weight
    
    # 被引用数フィルタ（例: 1年以内なら5以上、それ以外は20以上）
    is_passed = (age <= 1 and citations >= 5) or (citations >= 20)
    
    return score, is_passed

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

    current_year = dt.now().year
    scored_results = []

    # 1. スコアリングとフィルタリング
    for result in results:
        raw_id = result.get_short_id()
        base_id = raw_id.split("v")[0]

        if base_id in existing_ids:
            continue
            
        # Semantic Scholar APIのレートリミット（1秒に約1リクエスト）対策
        time.sleep(1.1) 
        
        metrics = get_paper_metrics(base_id)
        score, is_passed = calculate_score(metrics, current_year)
        
        if is_passed:
            scored_results.append((score, result, metrics))
            print(f"[候補追加]: {base_id} (スコア: {score:.2f}, 引用: {metrics['citations']})")
        else:
            print(f"[スキップ] 基準未達: {base_id} (引用: {metrics['citations']})")

    # 2. スコアの降順にソートし、上位のみ出力（ここでは例として上位5件）
    scored_results.sort(key=lambda x: x[0], reverse=True)
    top_results = scored_results[:5]

    # 3. 実際のダウンロードとDrive保存
    for score, result, metrics in top_results:
        raw_id = result.get_short_id()
        base_id = raw_id.split("v")[0]

        print(f"\n[新着ダウンロード開始]: {base_id} - {result.title}")
        print(f"   (スコア: {score:.2f}, 引用数: {metrics['citations']}, Venue: {metrics['venue']})")
        
        safe_title = "".join(c for c in result.title if c.isalnum() or c in (' ', '_', '-')).rstrip()
        filename = f"{raw_id}_{safe_title[:50]}.pdf"

        # arXivへのアクセス間隔
        time.sleep(DOWNLOAD_INTERVAL)

        try:
            req = urllib.request.Request(
                result.pdf_url,
                headers={"User-Agent": "ArXiv-Research-Collector/1.0"}
            )
            with urllib.request.urlopen(req) as response:
                pdf_bytes = response.read()

            file_metadata = {"name": filename, "parents": [folder_id]}
            media = MediaIoBaseUpload(io.BytesIO(pdf_bytes), mimetype="application/pdf")
            drive_service.files().create(
                body=file_metadata, media_body=media, fields="id"
            ).execute()

            print(f"   ✓ Google Driveへ保存完了: {filename}")
            existing_ids.add(base_id)
            downloaded += 1

        except Exception as e:
            print(f"   ✗ ダウンロード失敗 ({base_id}): {e}")

    print(f"\n[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 実行完了 (新規保存: {downloaded} 件)")

if __name__ == "__main__":
    main()