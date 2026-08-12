from __future__ import annotations

from scripts.report_schema import validate_canonical_report


def _canonical_report() -> str:
    return """# Claude Code 更新レポート / v1.2.3

| リリース日 | 影響度 | 破壊的変更 | 変更記載 | 推奨アクション |
|---|---|---|---|---|
| 2026-01-02 | 低 | 公式リリースノート上の明示なし | あり | 次回更新時に確認 |

<!-- section:links -->
## 関連リンク
- [GitHub Release](https://github.com/anthropics/claude-code/releases/tag/v1.2.3)
- [公式ドキュメント](https://docs.anthropic.com/ja/docs/claude-code)

<!-- section:summary -->
## 要約
<!-- sources:R1 -->
- 修正です。

<!-- section:judgement -->
## 判定
- **影響度**: 低
- **破壊的変更**: 公式リリースノート上の明示なし
- **変更記載**: あり
- **推奨アクション**: 次回更新時に確認

<!-- section:highlights -->
## 先に押さえるポイント
<!-- sources:R1 -->
- 修正です。

<!-- section:changes -->
## 変更内容
### バグ修正
<!-- sources:R1 -->
- **修正**

<!-- section:breaking_changes -->
## 破壊的変更
なし

<!-- section:impact -->
## 影響範囲
<!-- sources:R1 -->
- CLI利用者に影響します。

<!-- section:recommended_action -->
## 推奨対応
<!-- sources:R1 -->
- 次回更新時に確認してください。

<!-- section:notes -->
## 補足
なし
"""


def test_strict_report_accepts_canonical_h2_and_sources() -> None:
    assert validate_canonical_report(
        _canonical_report(),
        filename="2026-01-02-v1.2.3.md",
        require_sources=True,
    ) == []


def test_strict_report_rejects_h3_and_wrong_order() -> None:
    markdown = _canonical_report().replace("## 関連リンク", "### 関連リンク")
    summary = markdown.index("<!-- section:summary -->")
    judgement = markdown.index("<!-- section:judgement -->")
    summary_block = markdown[summary:judgement]
    markdown = markdown[:summary] + markdown[judgement:]
    links = markdown.index("<!-- section:links -->")
    markdown = markdown[:links] + summary_block + markdown[links:]

    errors = validate_canonical_report(markdown, filename="2026-01-02-v1.2.3.md")

    assert any("セクション順" in error for error in errors)
    assert any("H2" in error or "## 関連リンク" in error for error in errors)


def test_strict_report_rejects_table_filename_and_tag_mismatches() -> None:
    markdown = _canonical_report().replace(
        "| 2026-01-02 | 低 |",
        "| 2026-01-03 | 中 |",
    ).replace("releases/tag/v1.2.3", "releases/tag/v1.2.4")

    errors = validate_canonical_report(markdown, filename="2026-01-02-v1.2.3.md")

    assert any("ヘッダー判定表" in error for error in errors)
    assert any("Release URL" in error for error in errors)
    assert any("リリース日" in error for error in errors)


def test_strict_report_rejects_claim_without_source_marker() -> None:
    markdown = _canonical_report().replace("<!-- sources:R1 -->\n- 修正です。", "- 修正です。", 1)

    errors = validate_canonical_report(
        markdown,
        filename="2026-01-02-v1.2.3.md",
        require_sources=True,
    )

    assert any("sourcesコメント" in error for error in errors)
