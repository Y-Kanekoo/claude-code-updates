# Claude Code 更新レポート

Claude Code（Anthropic）の GitHub リリースを毎日監視し、日本語要約レポートを自動生成するツールです。

## 動作フロー

```
GitHub Actions（毎日 JST 9:00）
  ↓
GitHub API でリリース一覧を取得
  ↓
新リリースを変更項目ごとに分割し、Groq APIで日本語要約
  ↓ （完了した分割要約は保存し、停止後に再利用）
レポート・未送信通知・チェックポイントを保存 → 一覧を更新
  ↓
GitHub にレポートを公開
  ↓
未送信分を Discord に送信 → 送信確認と障害の状態を保存
```

## レポート一覧

→ [reports/claude-code/index.md](./reports/claude-code/index.md)

## セットアップ

GitHub リポジトリの **Settings → Secrets and variables → Actions** に以下を登録してください。

| シークレット名 | 必須 | 用途 |
|---|---|---|
| `CLAUDE_UPDATES_GROQ_API_KEY` | ✅ | Groq API（GPT-OSS 120B）でリリースノートを日本語要約 |
| `CLAUDE_UPDATES_DISCORD_WEBHOOK_URL` | 任意 | 新リリース・失敗時の Discord 通知 |

**Repository variables** には以下を登録してください。

| 変数名 | 必須 | 既定値・形式 | 用途 |
|---|---|---|---|
| `MAX_RELEASES_PER_RUN` | 任意 | `10` | 1回の実行で処理するリリース数の上限 |
| `CLAUDE_UPDATES_GROQ_API_KEY_EXPIRES_AT` | 推奨 | `YYYY-MM-DD` | Groq API キーの有効期限通知 |
| `CLAUDE_UPDATES_GROQ_MODEL` | 任意 | `openai/gpt-oss-120b` | Strict Structured Outputs対応の `openai/gpt-oss-120b` / `openai/gpt-oss-20b`。切替前にModel Permissionsを確認 |

### Groq API キーの取得

1. [console.groq.com](https://console.groq.com) でアカウント作成
2. **API Keys → Create API Key** でキーを生成
3. **Secrets** の `CLAUDE_UPDATES_GROQ_API_KEY` を新しいキーで更新
4. **Variables** の `CLAUDE_UPDATES_GROQ_API_KEY_EXPIRES_AT` をキーの有効期限（`YYYY-MM-DD`）で更新
5. 失敗していたワークフローを再実行し、成功を確認

キー期限の14日前・7日前・1日前・当日に通知します。期限切れ後は週単位で通知をまとめ、再実行でも送信済みの通知を繰り返しません。通知を受けたら期限前にキーを再発行し、Secret と期限変数を必ずセットで更新してください。期限通知を利用する場合は `CLAUDE_UPDATES_DISCORD_WEBHOOK_URL` の登録も必要です。

### 依存関係とCIの運用

- Pythonの直接依存は `requirements.in` / `requirements-dev.in`、ハッシュ付きlockは `requirements.txt` / `requirements-dev.txt` で管理します。更新時はPython 3.11向けにlockを再生成し、CIのhash検証を通してください。
- Marp CLIは `package-lock.json` に固定し、ローカル・Actionsとも `npm ci` で再現します。
- GitHub Actionsは完全なcommit SHAへ固定し、同じ行のバージョンコメントをDependabotが更新します。
- `CI / Python・Workflow・lock検証` をmainの必須checkにする場合、レポート更新ワークフローの `github-actions[bot]` にRuleset bypassを許可するか、レポート更新自体をPR作成方式へ移行してください。現在はbotによるmainへの直接pushとの互換性を維持しています。
- Ruffは既存違反を一括変更しないため、CIでは重大な構文・未定義名に絞って `E7,E9,F` を検査します。全rule適用は既存違反を目的別に解消した後の別段階とします。

## 通知とレポートの読み方

- 更新通知は「何が変わったか」「必要な対応」「対象の使い方」に絞り、公開済みの日本語レポートと公式原文へリンクします。スライドは公開が別工程のため、更新通知には未公開のURLを載せません。
- レポートは要約、判定、推奨対応、影響範囲、詳細の順に読めます。判定は自動要約による目安です。原文に対応の指定がない場合、必須の作業を作りません。
- 長いリリースは最大6項目・原文約4,500バイトを目安に分割します。HTTP 413ではさらに分割し、1項目でも処理できなければその原文を保持して暫定レポートと明示します。項目は切り捨てません。
- Discord送信に失敗した通知は `notification-state.json` に残り、次回に再送されます。Webhook未設定時も送信待ちを保持します。
- 障害通知には原因・停止したバージョン・次の対応を表示します。同じ原因・対象の通知は7日間抑制し、原因変更時と復旧時に通知します。Discord自体に障害がある場合はActionsの失敗とログで確認できます。

### 本番APIを使う送信なしの検証

Actionsの **Claude Code Updates Report → Run workflow** で `dry_run` を有効にします。生成したレポートと通知データを `report-preview` 成果物から確認できます。この実行ではGitへの保存、スライド公開、Discord送信を行いません。

```bash
.venv/bin/pytest -q
.venv/bin/ruff check --select E7,E9,F scripts
.venv/bin/python scripts/generate-index.py --check
actionlint
```

構成と復旧手順は [通知・レポート再設計](docs/design/notification-redesign.md) を参照してください。

## 使用技術

| 項目 | 内容 |
|---|---|
| 実行環境 | GitHub Actions（ubuntu-latest） |
| 言語 | Python 3.11 |
| LLM | Groq API / GPT-OSS 120B（`openai/gpt-oss-120b`、利用上限はGroqコンソールで確認） |
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
