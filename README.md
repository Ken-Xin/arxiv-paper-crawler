# arXiv V2X & Semantic Communication Paper Crawler with Gemini Agent Integration

arXivから **V2X（車車間・路車間通信）× セマンティック通信（Semantic Communication）** に関連する最新論文を自動検索・ダウンロードし、Google Driveへ自動蓄積する自律型クローラーです。

Google Driveに蓄積された論文PDFは、Google Workspace連携により **Gemini (AI Agent)** に自動連携され、研究トレンドの把握や論文の**新規性・差分分析、新規研究テーマの発掘**にシームレスに活用されます。

---

## システムアーキテクチャ & ワークフロー

```text
[ arXiv API ] 
      │ (毎時 定期巡回 / 新着走査)
      ▼
[ GitHub Actions (Python Script) ]
      │ (重複除外 & PDF取得)
      ▼
[ Google Drive (V2X_SemCom_Research) ]
      │ (Google Workspace 連携)
      ▼
[ Gemini AI Agent ] 
      ├─ 論文の要約 & 技術的コントリビューション抽出
      ├─ 既存研究との差分・ギャップ分析
      └─ 次世代V2X×セマンティック通信の新規性・研究アイデアの自動発見
---

## 主な特徴

- **自動定期実行:** GitHub Actions により、毎時クラウド上で定期実行（スケジューリング）。
- **重複防止メカニズム:** Google Drive 内の既存ファイル名から arXiv ID を自動走査し、取得済みの論文を自動スキップ。
- **OAuth 2.0 連携:** サービスアカウントの容量制限を回避し、個人のGoogle Driveストレージへ直接アップロード。
- **arXiv API 規約遵守:** リクエスト間隔（10秒）の確保および適切な User-Agent を設定。

---

## ディレクトリ構成

```text
.
├── .github/
│   └── workflows/
│       └── hourly_collector.yml  # GitHub Actions ワークフロー定義
├── arxiv_v2x_hourly_20min.py     # 論文収集 & Driveアップロード用メインスクリプト
├── get_token.py                  # 【初回認証用】OAuthリフレッシュトークン取得スクリプト（非公開）
├── .gitignore                    # 秘密鍵・トークン等の除外設定
└── README.md
