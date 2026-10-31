# radar-coreの段階的導入

## 第1段階の範囲

`scripts.notification_delivery.clip(value, limit)` の公開パス・引数名・戻り値を維持し、
正の上限だけを `scripts.discord_compat` 経由で `radar_core.discord.clip` へ委譲します。
UTF-16単位での上限、絵文字の途中で切らない処理、省略記号「…」は従来と同じです。
上限が0以下の場合、共有実装は例外になりますが、従来実装は文字列を返すため、従来処理を残します。
互換性テストでは移行前の式と境界値・日本語・絵文字・改行を比較します。

通知文面・payload・CLI・ログ・通知状態のJSON形式は変更しません。
依存導入前の状態復元とキー期限通知を維持するため、共有実装は切り詰め時に読み込みます。

## 依存の固定とインストール

指定元は `requirements-core.in` の次のタグ固定依存です。

```text
radar-core @ git+https://github.com/Y-Kanekoo/radar-core@v0.1.0
```

`requirements-core.txt` は注釈付きタグの参照先コミット
`d4301e178c1fd17e1c4688e9442f4ddd0c2ebe02` に固定しています。
タグの移動による実行コードの変化を防ぎます。公開HTTPSリポジトリなので追加の認証情報は不要です。

git依存は `pip --require-hashes` と混在できないため、本体のlockを分離しました
（[pipのハッシュ検証仕様](https://pip.pypa.io/en/stable/topics/secure-installs/#hash-checking-mode)）。
実行時依存の `httpx` / `feedparser` とその推移依存に加え、ビルド用の `hatchling` と
その推移依存も、従来の `requirements.txt` / `requirements-dev.txt` にハッシュ固定します。
本体は `--no-deps --no-build-isolation` で導入し、依存とビルド環境の未固定ダウンロードを防ぎます。
CIと日次レポートworkflowには本体のインストールだけを追加し、状態復元などの実行順は維持します。

Python 3.11とgitを用意し、リポジトリ直下で実行します。実行用は開発用lockを
`requirements.txt` に読み替えて、同じ2段階でインストールしてください。

```bash
python3.11 -m venv .venv
source .venv/bin/activate
.venv/bin/pip install --require-hashes -r requirements-dev.txt
.venv/bin/pip install --no-deps --no-build-isolation -r requirements-core.txt
.venv/bin/pip check
.venv/bin/ruff check --select E7,E9,F scripts
.venv/bin/mypy --strict --follow-imports=silent scripts/discord_compat.py
.venv/bin/pytest -q
.venv/bin/python scripts/generate-index.py --check
.venv/bin/pip install --dry-run --require-hashes -r requirements.txt
.venv/bin/pip install --dry-run --require-hashes -r requirements-dev.txt
actionlint
```

既存のCIではformatterと全体の型検査は未導入です。今回の型検査は追加した互換層に限定します。
既存テストは変更せず、テストは実APIを使わずモックで検証します。
GitHub Actionsは無料枠の制約により実行せず、同等コマンドをローカルで検証します。

今回のローカル検証では、一時ファイル・キャッシュをworktree内の `.cache/` に置きました。
`TMPDIR` がworktree内の場合は `GIT_CEILING_DIRECTORIES="$PWD"` を設定し、
「Gitリポジトリではない一時ディレクトリ」が親のworktreeを見つけないようにします。
テスト用Gitリポジトリへの個人設定・フックの影響も避けるため、検証時だけ
`GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1` を設定しました。
既存テストが呼ぶ `python` もPython 3.11になるよう、仮想環境を有効にしてください。

lock再生成時は次を実行し、タグと解決後コミットの対応も確認してください。

```bash
uv pip compile --python-version 3.11 --generate-hashes --no-emit-index-url --output-file requirements.txt requirements.in
uv pip compile --python-version 3.11 --generate-hashes --no-emit-index-url --output-file requirements-dev.txt requirements-dev.in
uv pip compile --python-version 3.11 --no-deps --no-emit-index-url --output-file requirements-core.txt requirements-core.in
git ls-remote https://github.com/Y-Kanekoo/radar-core refs/tags/v0.1.0 'refs/tags/v0.1.0^{}'
```

## 次の段階の候補

| 対象 | 現行との差分・今回置き換えない理由 |
|---|---|
| Webhook送信 | `notification_delivery.post_webhook` は `urllib`、旧 `check-claude-updates.py` の送信は `requests`。共有実装は `httpx` なので、既存のモック・タイムアウト・例外・ログ・戻り値と一致しない。現行のURL検証も共有実装より厳しい。 |
| 再試行 | 現行は429に加えて5xx・接続障害も再試行。共有実装は429だけなので、再送条件が変わる。 |
| 429の `retry_after` | 現行は不正値なら試行回数に応じた指数待機、30秒超なら持ち越し。共有実装は不正なJSON値からヘッダへフォールバックし、既定1秒で上限なし。例外型やヘッダのみの応答の扱いも異なる。 |
| content分割・embed組み立て | 現行は1通知1payloadで独自の文字数・文面を構築。共有実装は分割・正規化し、空要素の除去や6000文字への調整も行う。分割ごとの送信確認を保存する設計も別途必要。 |
| 旧field切り詰め | `_truncate_discord_field` はPythonの文字数・箇条書き単位で詰め、独自のレポート誘導文を付ける。共有のUTF-16切り詰めとは通知文面が異なる。 |
| Webhook URLマスク | 現行はURLをログへ出さず、通信例外を固定の日本語エラーに変換。共有マスクを追加する同等処理がなく、導入しても置換対象にならない。 |
| フィード取得・解析・正規化 | この利用側はGitHubリリースAPIと独自のレポート形式を使用しており、RSS用APIへ置き換えられる同等処理がない。 |
