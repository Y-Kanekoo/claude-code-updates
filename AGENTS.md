# claude-code-updates 開発ルール

既存リポジトリ。目的は README.md を参照する。

## プロジェクト固有

- 目的・非対象・受け入れ条件は README.md に書く。未記入の項目を推測で埋めない。
- 技術スタック、ディレクトリ構成、プロジェクト固有の禁止事項をこの節に追記する。

<!-- development-hub:standards v1 -->
## 共通基準（development-hub v1）

この節は development-hub（https://github.com/Y-Kanekoo/development-hub）のテンプレートから生成した。共通部分の変更はハブで行い、プロジェクト固有の規則は上の節に書く。

### 言語・作業範囲

- 回答、ドキュメント、コメント、ログは日本語で書く。識別子は英語。
- 依頼範囲だけを変更する。設計変更や大規模リファクタリングは、選択肢と推奨を示して確認する。
- 作業は git worktree で行い、未コミット変更のあるチェックアウトを書き換えない。
- コミットは `[type] 日本語の要約` 形式で、1目的1コミットにする。force push、履歴の書き換え、ブランチ削除はしない。

### 検証

- 完了を報告する前に `local-ci run .`（設定は `local-ci plan .` で確認） を実行し、全件の成功を確認する。失敗、skip、空のテストは合格としない。
- テストは development-hub のテスト標準（docs/testing-standard.md）に従い、static（lint・format・型・秘密情報）→ unit（カバレッジ下限あり）→ api（外部通信はモックかローカルのフェイク）→ e2e の順に実行する。前の段階が失敗したら止める。段階を飛ばすときは、理由を local-ci 設定の skip_reason と docs/TESTING.md の両方に記録する。
- GitHub Actions の無料枠に依存しない。既定の検証は local-ci（https://github.com/Y-Kanekoo/local-ci）でローカルに行う。
- 既存テストを削除・弱体化・skip化しない。エージェントの差分は agent-change-verifier の `acv check --base origin/main` で確認する。
- E2E は外部通信を遮断し、固定時間の sleep に頼らない。
- 指示書の矛盾と陳腐化は agents-md-lint で確認する。
- 完了前に development-hub の敵対的検証の標準（docs/adversarial-verification.md）の必須観点を確認し、変更の大きさに応じて開発プロセスの標準（docs/delivery-practices.md）の必須項目（受け入れ条件・DoD など）を満たす。
- 失敗・手戻り・ツールの誤検知は学習ループ（docs/learning-loop.md）に従い、パス・トークン・メールアドレスを伏せて knowledge/ に記録し、繰り返すものは標準へ昇格させる。

### 安全・費用

- 有料APIキー（OPENAI_API_KEY、ANTHROPIC_API_KEY など）を前提にしない。完全無料の範囲で運用する。
- 秘密値、Webhook URL、.env をコミットしない。通知を追加するときは development-hub の通知契約テンプレートに従う。
- アカウント作成、外部サービス連携、secret登録は行わず、HUMAN_TODO.md に記録する。

### 人間の作業

- 人間が必要な作業は HUMAN_TODO.md に `- [ ] 内容 #p1〜#p3 #タグ` の形式で書く。gh-daily-digest が日次で集計する。

### モデル選定（2026-10-31 時点の方針）

- 既定は Codex の gpt-6.1-sol、推論強度 medium。xhigh と max は既定にせず、必要なときだけ上げる。
- 設計は gpt-6.1-sol の xhigh（影響の大きい設計は gpt-6-astra の medium）。実装は gpt-6.1-sol の medium（バグ修正や多ファイル変更は high）。
- レビューは gpt-6.1-sol の high（セキュリティ・課金・データ破壊に関わる差分は gpt-6-astra の high）。
- 大量の定型作業は gpt-6-luna の high。画面や画像の読み取りを含む E2E は gpt-6.1-terra の medium。原因不明の難所は gpt-6-astra の medium から xhigh。
- Claude Code は設計とレビューに opus、日常の実装に sonnet、単純作業に haiku を使う。クレジット課金になり得る fable は明示選択しない。
- 失敗したら、文脈不足ならプロンプトと AGENTS.md を直し、手抜きなら推論強度を上げ、理解不足なら上位モデルへ切り替える。
