from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.report_schema import (
    DISCORD_COLOR_BREAKING,
    DISCORD_COLOR_NORMAL,
    DISCORD_COLOR_WARN,
    build_header_table,
    extract_judgement,
    extract_summary,
    is_empty_release,
    parse_sections,
    pick_discord_color,
    validate_report,
)


def test_parse_sections_new_format() -> None:
    markdown = """
<!-- section:summary -->
### 要約
- 重要な更新です。

<!-- section:judgement -->
### 判定
- **影響度**: 中

<!-- section:links -->
### 関連リンク
- https://github.com/example/repo
"""

    sections = parse_sections(markdown)

    assert sections["summary"] == "- 重要な更新です。"
    assert sections["judgement"] == "- **影響度**: 中"
    assert sections["links"] == "- https://github.com/example/repo"


def test_parse_sections_legacy_aliases() -> None:
    markdown = """
### 先に押さえるポイント
- 先の内容

### 要対応・確認事項
- 後の内容

### 新機能
- 新しい機能
"""

    sections = parse_sections(markdown)

    assert sections["highlights"] == "- 後の内容"
    assert sections["changes"] == "- 新しい機能"


def test_parse_sections_anchor_priority() -> None:
    markdown = """
<!-- section:summary -->
### 要ゃく
- アンカーで要約として扱う。
"""

    sections = parse_sections(markdown)

    assert sections["summary"] == "- アンカーで要約として扱う。"


def test_extract_summary_skips_meta() -> None:
    sections = {
        "summary": """
- **影響度**: 中
- 純粋な要約文です。
""".strip()
    }

    assert extract_summary(sections) == "純粋な要約文です。"


def test_extract_judgement_all_keys() -> None:
    sections = {"judgement": _judgement_block()}

    assert extract_judgement(sections) == {
        "影響度": "中",
        "破壊的変更": "公式リリースノート上の明示なし",
        "変更記載": "あり",
        "推奨アクション": "次回更新時に確認",
    }


def test_extract_judgement_full_width_colon() -> None:
    sections = {
        "judgement": """
- **影響度**：中
- **破壊的変更**：公式リリースノート上の明示なし
- **変更記載**：あり
- **推奨アクション**：様子見
""".strip()
    }

    assert extract_judgement(sections)["影響度"] == "中"
    assert extract_judgement(sections)["推奨アクション"] == "様子見"


def test_extract_judgement_emphasis_variant() -> None:
    sections = {
        "judgement": """
- **影響度:** 高
- **破壊的変更:** あり
- **変更記載:** あり
- **推奨アクション:** 即対応
""".strip()
    }

    assert extract_judgement(sections) == {
        "影響度": "高",
        "破壊的変更": "あり",
        "変更記載": "あり",
        "推奨アクション": "即対応",
    }


def test_extract_judgement_missing_key_returns_partial() -> None:
    sections = {
        "judgement": """
- **影響度**: 低
- **破壊的変更**: 要確認
- **変更記載**: あり
""".strip()
    }

    assert extract_judgement(sections) == {
        "影響度": "低",
        "破壊的変更": "要確認",
        "変更記載": "あり",
    }


def test_is_empty_release_true() -> None:
    assert is_empty_release({"変更記載": "具体的な変更記載なし"}) is True


def test_is_empty_release_false() -> None:
    assert is_empty_release({"変更記載": "あり"}) is False


def test_pick_discord_color_breaking() -> None:
    assert pick_discord_color({"破壊的変更": "あり", "影響度": "低"}) == DISCORD_COLOR_BREAKING


def test_pick_discord_color_warn() -> None:
    assert pick_discord_color({"影響度": "要確認", "破壊的変更": "要確認"}) == DISCORD_COLOR_WARN


def test_pick_discord_color_warn_on_empty() -> None:
    assert pick_discord_color({"変更記載": "具体的な変更記載なし"}) == DISCORD_COLOR_WARN


def test_pick_discord_color_normal() -> None:
    judgement = {
        "影響度": "中",
        "破壊的変更": "公式リリースノート上の明示なし",
        "変更記載": "あり",
    }

    assert pick_discord_color(judgement) == DISCORD_COLOR_NORMAL


def test_validate_report_ok() -> None:
    assert validate_report(_full_report()) == []


def test_validate_report_missing_links() -> None:
    markdown = _full_report().replace(
        """
<!-- section:links -->
### 関連リンク
- [GitHub Release](https://github.com/anthropics/claude-code/releases/tag/v2.1.101)
- [公式ドキュメント](https://docs.anthropic.com/claude-code/overview)

""",
        "",
    )

    errors = validate_report(markdown)

    assert errors
    assert any("関連リンク" in error for error in errors)


def test_validate_report_empty_release() -> None:
    markdown = """
# Claude Code 更新レポート / v2.1.100

<!-- section:summary -->
### 要約
- 公開情報の変更がありません。

<!-- section:judgement -->
### 判定
- **影響度**: 要確認
- **破壊的変更**: 要確認
- **変更記載**: 具体的な変更記載なし
- **推奨アクション**: 様子見

<!-- section:links -->
### 関連リンク
- [公式ドキュメント](https://docs.anthropic.com/claude-code/overview)
- [変更履歴](https://docs.anthropic.com/claude-code/changelog)
"""

    assert validate_report(markdown) == []


def test_build_header_table() -> None:
    judgement = {
        "影響度": "中",
        "変更記載": "あり",
    }

    assert build_header_table(judgement, "2026-04-10") == (
        "| リリース日 | 影響度 | 破壊的変更 | 変更記載 | 推奨アクション |\n"
        "|---|---|---|---|---|\n"
        "| 2026-04-10 | 中 | — | あり | — |\n"
    )


def _full_report() -> str:
    return """
# Claude Code 更新レポート / v2.1.101

<!-- section:summary -->
### 要約
- 通常の更新です。

<!-- section:judgement -->
### 判定
- **影響度**: 中
- **破壊的変更**: 公式リリースノート上の明示なし
- **変更記載**: あり
- **推奨アクション**: 次回更新時に確認

<!-- section:links -->
### 関連リンク
- [GitHub Release](https://github.com/anthropics/claude-code/releases/tag/v2.1.101)
- [公式ドキュメント](https://docs.anthropic.com/claude-code/overview)

<!-- section:highlights -->
### 先に押さえるポイント
- 重要点です。

<!-- section:changes -->
### 変更内容
- 変更があります。

<!-- section:breaking_changes -->
### 破壊的変更
- 公式リリースノート上の明示なし。

<!-- section:impact -->
### 影響範囲
- 一部利用者に影響します。

<!-- section:recommended_action -->
### 推奨対応
- 次回更新時に確認します。
"""


def _judgement_block() -> str:
    return """
- **影響度**: 中
- **破壊的変更**: 公式リリースノート上の明示なし
- **変更記載**: あり
- **推奨アクション**: 次回更新時に確認
""".strip()


def test_parse_sections_changes_with_subheadings() -> None:
    """変更内容セクションに #### サブ見出しが含まれても本文に残る。"""
    markdown = """<!-- section:summary -->
### 要約
- テスト用の要約です。

<!-- section:judgement -->
### 判定
- **影響度**: 中
- **破壊的変更**: 公式リリースノート上の明示なし
- **変更記載**: あり
- **推奨アクション**: 次回更新時に確認

<!-- section:links -->
### 関連リンク
- [GitHub Release](https://github.com/anthropics/claude-code/releases/tag/v1.0.0)
- [公式ドキュメント](https://docs.anthropic.com/ja/docs/claude-code)

<!-- section:highlights -->
### 先に押さえるポイント
- ポイント1

<!-- section:changes -->
### 変更内容

#### 新機能
- **`/foo` コマンド追加**
  - 関連: `/foo`

#### バグ修正
- **X の修正**

<!-- section:breaking_changes -->
### 破壊的変更
なし

<!-- section:impact -->
### 影響範囲
- 影響1

<!-- section:recommended_action -->
### 推奨対応
- 対応1

<!-- section:notes -->
### 補足
なし
"""
    sections = parse_sections(markdown)
    assert "#### 新機能" in sections["changes"]
    assert "#### バグ修正" in sections["changes"]
    assert "`/foo` コマンド追加" in sections["changes"]


def test_validate_report_accepts_changes_with_subheadings() -> None:
    """変更内容にサブ見出しがあっても validate_report は通る。"""
    markdown = """# タイトル

<!-- section:summary -->
### 要約
- テスト用の要約。

<!-- section:judgement -->
### 判定
- **影響度**: 中
- **破壊的変更**: 公式リリースノート上の明示なし
- **変更記載**: あり
- **推奨アクション**: 次回更新時に確認

<!-- section:links -->
### 関連リンク
- [GitHub Release](https://github.com/anthropics/claude-code/releases/tag/v1.0.0)
- [公式ドキュメント](https://docs.anthropic.com/ja/docs/claude-code)

<!-- section:highlights -->
### 先に押さえるポイント
- ポイント

<!-- section:changes -->
### 変更内容

#### 新機能
- **追加**

<!-- section:breaking_changes -->
### 破壊的変更
なし

<!-- section:impact -->
### 影響範囲
- 影響

<!-- section:recommended_action -->
### 推奨対応
- 対応

<!-- section:notes -->
### 補足
なし
"""
    errors = validate_report(markdown)
    assert errors == []
