# Claude Code 更新レポート

Claude Code（Anthropic）の GitHub リリースを毎日監視し、日本語要約レポートを自動生成するツールです。

## 動作フロー

```
GitHub Actions（毎日 JST 9:00）
  ↓
GitHub API でリリース一覧を取得
  ↓
新リリースがあれば Groq API（LLaMA 3.3 70B）で日本語要約
  ↓
Markdown レポートを reports/ に保存 → index.md / index.json を更新
  ↓
Discord に通知
```

## レポート一覧

→ [reports/claude-code/index.md](./reports/claude-code/index.md)

## セットアップ

GitHub リポジトリの **Settings → Secrets and variables → Actions** に以下を登録してください。

| シークレット名 | 必須 | 用途 |
|---|---|---|
| `CLAUDE_UPDATES_GROQ_API_KEY` | ✅ | Groq API（LLaMA 3.3 70B）でリリースノートを日本語要約 |
| `CLAUDE_UPDATES_DISCORD_WEBHOOK_URL` | 任意 | 新リリース・失敗時の Discord 通知 |

### Groq API キーの取得

1. [console.groq.com](https://console.groq.com) でアカウント作成
2. **API Keys → Create API Key**（有効期限: No expiration 推奨）
3. 生成したキーを `CLAUDE_UPDATES_GROQ_API_KEY` に登録

## 使用技術

| 項目 | 内容 |
|---|---|
| 実行環境 | GitHub Actions（ubuntu-latest） |
| 言語 | Python 3.11 |
| LLM | Groq API / LLaMA 3.3 70B（無料枠: 14,400 リクエスト/日） |
| 監視対象 | [anthropics/claude-code](https://github.com/anthropics/claude-code/releases) |
| スケジュール | 毎日 0:00 UTC（JST 9:00） |

## ファイル構成

```
├── scripts/
│   ├── check-claude-updates.py   # メインスクリプト（リリース取得・要約・通知）
│   └── generate-index.py         # インデックス生成スクリプト
├── reports/
│   └── claude-code/
│       ├── index.md              # リリース一覧（自動生成）
│       ├── index.json            # 機械処理用 JSON（自動生成）
│       ├── last-checked.json     # 最終チェックバージョン記録
│       └── YYYY-MM-DD-vX.X.X.md # 各リリースの日本語レポート
├── .github/
│   └── workflows/
│       └── claude-updates.yml    # GitHub Actions ワークフロー
└── requirements.txt
```
