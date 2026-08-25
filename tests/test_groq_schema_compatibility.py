from __future__ import annotations

from collections.abc import Mapping

import pytest

from scripts.report_generation import (
    STRUCTURED_REPORT_JSON_SCHEMA,
    StructuredReportError,
    build_source_bullets,
    parse_structured_report,
)


def _valid_payload() -> dict[str, object]:
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


def test_groq_schema_does_not_use_unsupported_unique_items() -> None:
    def assert_compatible(node: object) -> None:
        if isinstance(node, Mapping):
            assert "uniqueItems" not in node
            for value in node.values():
                assert_compatible(value)
        elif isinstance(node, list):
            for value in node:
                assert_compatible(value)

    assert_compatible(STRUCTURED_REPORT_JSON_SCHEMA)


def test_python_validation_rejects_duplicate_grounding_source_ids() -> None:
    payload = _valid_payload()
    payload["summary"] = {
        "text": "`/foo` が追加されました。",
        "source_ids": ["R1", "R1"],
    }

    with pytest.raises(StructuredReportError, match="source_idsが重複"):
        parse_structured_report(
            payload,
            build_source_bullets("- Added `/foo` command"),
        )


def test_python_validation_rejects_duplicate_identifiers() -> None:
    payload = _valid_payload()
    payload["changes"] = [
        {
            "category": "新機能",
            "title": "`/foo` コマンド追加",
            "detail": "",
            "identifiers": ["/foo", "/foo"],
            "source_ids": ["R1"],
        }
    ]

    with pytest.raises(StructuredReportError, match="identifiersが重複"):
        parse_structured_report(
            payload,
            build_source_bullets("- Added `/foo` command"),
        )
