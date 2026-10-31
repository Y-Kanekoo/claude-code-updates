# 品質プロセス（claude-code-updates）

development-hub の [開発プロセスの標準](https://github.com/Y-Kanekoo/development-hub/blob/main/docs/delivery-practices.md) と [敵対的検証の標準](https://github.com/Y-Kanekoo/development-hub/blob/main/docs/adversarial-verification.md) から生成しました。変更の大きさに応じて、下表の必須項目を埋めます。

| 項目 | 小さな変更 | 通常の機能追加 | 大きな変更 | ファイル |
| --- | --- | --- | --- | --- |
| 要件・受け入れ条件・トレーサビリティ | 受け入れ条件のみ必須 | 必須 | 必須 | REQUIREMENTS.md |
| 設計レビュー | 不要 | 推奨 | 必須（実装前） | DESIGN_REVIEW.md |
| リスク | 不要 | 推奨 | 必須 | RISKS.md |
| リリース・ロールバック・監視 | 不要 | 推奨 | 必須 | RELEASE.md |
| 振り返り | 不要 | 手戻りがあれば必須 | 必須 | RETROSPECTIVE.md |
| 技術的負債 | 見つけたら必須 | 見つけたら必須 | 見つけたら必須 | TECH_DEBT.md |
| 敵対的検証 | 必須観点 | 必須観点 | 必須＋推奨観点 | ADVERSARIAL_CHECKLIST.md |

大きな変更: 設計・公開API・データ形式・課金・権限・データ削除に関わる変更。

## 完了の定義（DoD）

- [ ] テスト標準の4段階（static → unit → api → e2e）が成功し、スキップは理由を docs/TESTING.md に記録した
- [ ] 受け入れ条件をすべて満たし、各条件に対応するテストがある
- [ ] 敵対的検証の必須観点を確認し、結果を記録した
- [ ] `acv check --base origin/main` が合格した（指摘があれば理由をレビュー済みとして記録した）
- [ ] README・docs・AGENTS.md の該当箇所を更新した
- [ ] 人間の作業を HUMAN_TODO.md に書いた
- [ ] 手戻りや想定外の挙動を knowledge/ に記録した（伏せ字済み）
