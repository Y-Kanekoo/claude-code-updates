# テスト（claude-code-updates）

development-hub のテスト標準（https://github.com/Y-Kanekoo/development-hub/blob/main/docs/testing-standard.md）に従います。段階は static → unit → api → e2e の順で、前の段階が失敗したら止めます。

## 段階とコマンド

| 段階 | コマンド |
| --- | --- |
| static | `npm run lint` / `npm run format:check` / `npm run typecheck` / `npm run secrets` |
| unit | `npm run test:unit` |
| api | `npm run test:api`（外部通信は `startFakeServer()` で代替） |
| e2e | `npx playwright test --grep @smoke`（UI がある場合） |

まとめて実行: `npm run check`、またはコミット後に `local-ci run .`（段階の絞り込み: `--stage static,unit`）。

## カバレッジ

- unit 段階の下限: 導入時の実測値（記入: ○○%）。引き下げない
- 下限は引き下げない。計測から外したファイルと理由:（なし）

## スキップの記録

スキップは `.local-ci.yml` の `skip: true` と `skip_reason` に加えて、この表にも書きます。テストコードに `skip` を追加しません。

| 段階 | 理由 | 解除条件 | 記録日 |
| --- | --- | --- | --- |
| - | （なし） | - | - |

## 弱体化の確認（レビュー時）

- [ ] `acv check --base origin/main` が合格（テスト削除・件数減少・skip追加・閾値引き下げなし）
- [ ] 期待値を緩めていない（完全一致を部分一致や存在確認にしていない）
- [ ] カバレッジの除外・`.local-ci.yml` の skip・段階の削除を追加していない（追加したなら理由をこの文書に記録）
- [ ] 外部通信はモックかローカルのフェイクだけ
