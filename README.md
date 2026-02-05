# Claude Code 更新監視

Claude Codeのリリースを監視し、日本語でレポートを自動生成するツールです。

## 概要

このプロジェクトは、Claude Codeの最新リリース情報を定期的に取得し、Gemini APIを使用して日本語で要約されたレポートを自動生成します。GitHub Actionsによる自動化により、最新の更新情報を見逃しません。

## 機能

- **自動監視**: GitHub ActionsでClaude Codeのリリースを毎日チェック
- **日本語要約**: Gemini APIでリリースノートを日本語に翻訳・要約
- **自動レポート生成**: Markdownレポートを自動生成・コミット
- **履歴管理**: 過去のリリース情報をreportsディレクトリに保存

## セットアップ手順

### 1. リポジトリの準備

```bash
# リポジトリをクローン
git clone <your-repo-url>
cd claude-code-updates

# 依存パッケージをインストール
pip install -r requirements.txt
```

### 2. GitHub Secretsの設定

1. GitHubリポジトリの「Settings」→「Secrets and variables」→「Actions」を開く
2. 「New repository secret」をクリック
3. 以下のシークレットを追加:
   - **Name**: `GEMINI_API_KEY`
   - **Value**: あなたのGemini APIキー

### 3. GitHub Actionsの有効化

1. リポジトリの「Actions」タブを開く
2. ワークフローを有効化
3. 毎日自動的に実行されます（UTC 0:00）

## ローカル実行方法

```bash
# 環境変数を設定
export GEMINI_API_KEY="your-api-key-here"

# スクリプトを実行
python scripts/check_updates.py
```

実行後、`reports/`ディレクトリに最新のレポートが生成されます。

## ディレクトリ構成

```
claude-code-updates/
├── .github/
│   └── workflows/
│       └── check-updates.yml    # GitHub Actions ワークフロー定義
├── reports/                      # 生成されたレポートを保存
│   └── YYYY-MM-DD.md            # 日付ごとのレポート
├── scripts/
│   └── check_updates.py         # メイン監視スクリプト
├── requirements.txt              # Python依存パッケージ
└── README.md                     # このファイル
```

## 動作の仕組み

1. **定期実行**: GitHub Actionsが毎日UTC 0:00に起動
2. **リリース取得**: GitHub APIからClaude Codeの最新リリース情報を取得
3. **日本語要約**: Gemini APIでリリースノートを日本語に翻訳・要約
4. **レポート生成**: Markdown形式でレポートを生成
5. **自動コミット**: 新しいレポートをリポジトリに自動コミット

## ライセンス

MIT License

## 注意事項

- Gemini APIキーは絶対にコミットしないでください
- GitHub Secretsに保存することで安全に管理できます
- APIの利用制限に注意してください
