from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import ClassVar

ROOT_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT_DIR / "scripts"))

UPDATES_SPEC = importlib.util.spec_from_file_location(
    "check_updates_deterministic_fallback",
    ROOT_DIR / "scripts" / "check-claude-updates.py",
)
assert UPDATES_SPEC is not None and UPDATES_SPEC.loader is not None
updates = importlib.util.module_from_spec(UPDATES_SPEC)
UPDATES_SPEC.loader.exec_module(updates)


class GeneratedJsonError(Exception):
    status_code = 400
    body: ClassVar[dict[str, object]] = {
        "error": {"code": "json_validate_failed"}
    }


def test_repeated_generated_json_errors_preserve_all_official_sources() -> None:
    checker = object.__new__(updates.ReleaseChecker)
    call_count = 0

    def create(**_kwargs: object) -> object:
        nonlocal call_count
        call_count += 1
        raise GeneratedJsonError("生成JSONが必須キーを満たしません")

    checker.client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))
    )
    checker._call_groq_api = lambda operation, _name: operation()

    markdown = checker.summarize_release_notes(
        "- Added `/foo` command\n- Fixed timeout handling",
        "v2.1.233",
    )

    assert call_count == 3
    assert "公式リリースノートの変更項目を原文のまま掲載します" in markdown
    assert "### 新機能" in markdown
    assert "**Added `/foo` command**" in markdown
    assert "### バグ修正" in markdown
    assert "**Fixed timeout handling**" in markdown
    assert "<!-- sources:R1 -->" in markdown
    assert "<!-- sources:R2 -->" in markdown
