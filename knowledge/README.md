# knowledge（claude-code-updates の学習記録）

失敗・手戻り・ツールの誤検知を1件1ファイルで knowledge/records/ に記録し、繰り返すものを標準・テンプレート・自動チェックへ昇格させます。手順の詳細は development-hub の [学習ループ](https://github.com/Y-Kanekoo/development-hub/blob/main/docs/learning-loop.md) を参照してください。

## 書き方

1. TEMPLATE.md を `records/YYYY-MM-DD-短い英語の要約.md` にコピーして埋める。
2. 記録とコミットの前に、パス・トークン・メールアドレス・IPアドレスを伏せる。development-hub の `python -m hub.redact --check knowledge` で確認できる。人名・顧客名・会話本文は手で削る。
3. ログ全文やセッション本文は貼らない。必要な部分だけを引用する。

## 昇格

同じ原因で2回以上起きた、severity が high、または自動チェックで防げるときは、反映先（テスト・lint・テンプレート・docs）を決めて対策し、`status: promoted` と `promoted_to` を書きます。見送るなら理由を書きます。
