from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
SPEC = importlib.util.spec_from_file_location(
    "generate_index_strict", SCRIPTS_DIR / "generate-index.py"
)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _write_minimal_report(directory: Path, version: str, release_date: str) -> Path:
    path = directory / f"{release_date}-{version}.md"
    path.write_text(
        f"""# Claude Code 更新レポート / {version}

| リリース日 | 影響度 | 破壊的変更 | 変更記載 | 推奨アクション |
|---|---|---|---|---|
| {release_date} | 要確認 | 要確認 | 具体的な変更記載なし | 様子見 |

<!-- section:links -->
## 関連リンク
- [GitHub Release](https://github.com/anthropics/claude-code/releases/tag/{version})
- [公式ドキュメント](https://docs.anthropic.com/ja/docs/claude-code)

<!-- section:summary -->
## 要約
- 公式リリースノートに具体的な変更記載はありません。

<!-- section:judgement -->
## 判定
- **影響度**: 要確認
- **破壊的変更**: 要確認
- **変更記載**: 具体的な変更記載なし
- **推奨アクション**: 様子見
""",
        encoding="utf-8",
    )
    return path


def test_collect_releases_sorts_by_semver(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _write_minimal_report(tmp_path, "v2.10.0", "2026-01-01")
    _write_minimal_report(tmp_path, "v2.9.9", "2026-12-31")
    monkeypatch.setattr(MODULE, "REPORTS_DIR", tmp_path)

    releases = MODULE._collect_releases()

    assert [release["version"] for release in releases] == ["v2.10.0", "v2.9.9"]


def test_collect_releases_fails_on_unparseable_report(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (tmp_path / "broken.md").write_text("# 壊れたレポート\n", encoding="utf-8")
    monkeypatch.setattr(MODULE, "REPORTS_DIR", tmp_path)

    with pytest.raises(MODULE.IndexGenerationError, match="バージョンを抽出"):
        MODULE._collect_releases()


def test_check_detects_stale_index_without_writing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    report_dir = tmp_path / "reports"
    report_dir.mkdir()
    _write_minimal_report(report_dir, "v1.0.0", "2026-01-01")
    index_md = report_dir / "index.md"
    index_json = report_dir / "index.json"
    index_md.write_text("stale\n", encoding="utf-8")
    index_json.write_text(
        json.dumps({"generated_at": "2026-01-02T00:00:00", "releases": []}) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(MODULE, "REPORTS_DIR", report_dir)
    monkeypatch.setattr(MODULE, "INDEX_MD", index_md)
    monkeypatch.setattr(MODULE, "INDEX_JSON", index_json)

    assert MODULE.generate_index(check=True) is False
    assert index_md.read_text(encoding="utf-8") == "stale\n"
