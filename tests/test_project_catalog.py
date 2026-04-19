from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest


# scripts/ を sys.path に追加
import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from project_catalog import (
    build_catalog,
    extract_intent,
    extract_last_active,
    extract_stack,
)


def test_extract_stack_from_package_json(tmp_path: Path) -> None:
    """package.json から dependencies 上位3件を抽出する。"""
    (tmp_path / "package.json").write_text(
        '{"dependencies": {"react": "18", "next": "14", "axios": "1", "tailwind": "3"}}',
        encoding="utf-8",
    )
    stack = extract_stack(tmp_path)
    assert stack == ["react", "next", "axios"]


def test_extract_stack_from_requirements_txt(tmp_path: Path) -> None:
    """requirements.txt からパッケージ名のみ抽出する。"""
    (tmp_path / "requirements.txt").write_text(
        "pandas==2.1.0\nnumpy>=1.24\nrequests\nmatplotlib==3.8",
        encoding="utf-8",
    )
    stack = extract_stack(tmp_path)
    assert stack == ["pandas", "numpy", "requests"]


def test_extract_stack_empty_when_nothing(tmp_path: Path) -> None:
    """何もない場合は空リスト。"""
    stack = extract_stack(tmp_path)
    assert stack == []


def test_extract_intent_from_claude_md(tmp_path: Path) -> None:
    """CLAUDE.md の ## Intent: 行を優先する。"""
    (tmp_path / "CLAUDE.md").write_text(
        "# Title\n\n## Intent: テスト用のプロジェクト\n\n本文",
        encoding="utf-8",
    )
    assert extract_intent(tmp_path) == "テスト用のプロジェクト"


def test_extract_intent_fallback_to_readme(tmp_path: Path) -> None:
    """CLAUDE.md がなければ README.md の先頭非空行を返す。"""
    (tmp_path / "README.md").write_text(
        "# My Project\n\nThis is a sample project for testing.\n",
        encoding="utf-8",
    )
    intent = extract_intent(tmp_path)
    assert intent == "This is a sample project for testing."


def test_extract_intent_empty_when_nothing(tmp_path: Path) -> None:
    """両方ない場合は空文字。"""
    assert extract_intent(tmp_path) == ""


def test_extract_last_active_non_git(tmp_path: Path) -> None:
    """git リポジトリでないディレクトリは空文字。"""
    assert extract_last_active(tmp_path) == ""


def test_build_catalog_excludes_self(tmp_path: Path) -> None:
    """自分自身（claude-code-updates）と隠しディレクトリを除外する。"""
    (tmp_path / "claude-code-updates").mkdir()
    (tmp_path / ".hidden").mkdir()
    (tmp_path / "my-project").mkdir()
    (tmp_path / "my-project" / "README.md").write_text(
        "# My Project\n\nA test project.\n", encoding="utf-8"
    )
    # ファイル（ディレクトリでない）は除外
    (tmp_path / "some-note.md").write_text("note", encoding="utf-8")

    result = build_catalog(tmp_path, self_name="claude-code-updates")
    projects = result["projects"]
    assert isinstance(projects, list)
    names = [p["name"] for p in projects if isinstance(p, dict)]
    assert "claude-code-updates" not in names
    assert ".hidden" not in names
    assert "some-note.md" not in names
    assert "my-project" in names
