from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import ClassVar

ROOT_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT_DIR / "scripts"))

UPDATES_SPEC = importlib.util.spec_from_file_location(
    "check_updates_generated_json_retry",
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


def valid_payload() -> dict[str, object]:
    return {
        "summary": {"text": "`/foo` が追加されました。", "source_ids": ["R1"]},
        "judgement": {
            "影響度": "中",
            "破壊的変更": "公式リリースノート上の明示なし",
            "変更記載": "あり",
            "推奨アクション": "次回更新時に確認",
        },
        "highlights": [],
        "changes": [
            {
                "category": "新機能",
                "title": "`/foo` コマンド追加",
                "detail": "",
                "identifiers": ["/foo"],
                "source_ids": ["R1"],
            }
        ],
        "breaking_changes": [],
        "impact": [],
        "recommended_action": [],
        "notes": [],
    }


def test_generated_json_schema_error_is_repaired_with_complete_key_instruction() -> None:
    checker = object.__new__(updates.ReleaseChecker)
    calls: list[dict[str, object]] = []

    def create(**kwargs: object) -> object:
        calls.append(kwargs)
        if len(calls) == 1:
            raise GeneratedJsonError("生成JSONが必須キーを満たしません")
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content=json.dumps(valid_payload(), ensure_ascii=False)
                    )
                )
            ]
        )

    checker.client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))
    )
    checker._call_groq_api = lambda operation, _name: operation()

    markdown = checker.summarize_release_notes(
        "- Added `/foo` command",
        "v2.1.232",
    )

    assert "`/foo` コマンド追加" in markdown
    assert len(calls) == 2
    messages = calls[1]["messages"]
    assert isinstance(messages, list)
    assert "recommended_action、notesをすべて出力" in messages[1]["content"]
