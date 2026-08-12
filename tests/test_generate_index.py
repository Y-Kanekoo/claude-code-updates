from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

SPEC = importlib.util.spec_from_file_location("generate_index", SCRIPTS_DIR / "generate-index.py")
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

extract_version = MODULE.extract_version
parse_report = MODULE.parse_report


def test_extract_version_from_current_report_heading() -> None:
    """現行レポートのH1見出しからバージョンを抽出できる。"""
    content = "# Claude Code 更新レポート / v2.1.228\n"

    assert extract_version(content) == "v2.1.228"


def test_extract_version_from_legacy_report_heading() -> None:
    """旧形式のH2見出しも引き続き解析できる。"""
    content = "## v2.1.100 (2026-04-10)\n"

    assert extract_version(content) == "v2.1.100"


def test_parse_current_report(tmp_path: Path) -> None:
    """現行レポートをインデックス項目へ変換できる。"""
    report = tmp_path / "2026-08-11-v2.1.228.md"
    report.write_text(
        """# Claude Code 更新レポート / v2.1.228

| リリース日 | 影響度 | 破壊的変更 | 変更記載 | 推奨アクション |
|---|---|---|---|---|
| 2026-08-11 | 低 | 公式リリースノート上の明示なし | あり | 次回更新時に確認 |

<!-- section:summary -->
### 要約
- バグ修正と改善が中心です。

<!-- section:judgement -->
### 判定
- **影響度**: 低
- **破壊的変更**: 公式リリースノート上の明示なし
""",
        encoding="utf-8",
    )

    assert parse_report(report) == {
        "version": "v2.1.228",
        "date": "2026-08-11",
        "file": report.name,
        "tldr": "バグ修正と改善が中心です。",
        "impact": "低",
        "breaking": "公式リリースノート上の明示なし",
    }
