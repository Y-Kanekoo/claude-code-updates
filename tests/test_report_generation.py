from __future__ import annotations

from collections.abc import Mapping

import pytest

from scripts.report_generation import (
    STRUCTURED_REPORT_JSON_SCHEMA,
    StructuredReportError,
    build_empty_release_report,
    build_groq_response_format,
    build_source_bullets,
    classify_source_category,
    parse_or_build_empty_release,
    parse_structured_report,
    render_summary_markdown,
)


def _valid_payload() -> dict[str, object]:
    return {
        "summary": {"text": "`/foo` コマンドが追加されました。", "source_ids": ["R1"]},
        "judgement": {
            "影響度": "中",
            "破壊的変更": "公式リリースノート上の明示なし",
            "変更記載": "あり",
            "推奨アクション": "次回更新時に確認",
        },
        "highlights": [
            {"text": "`/foo` を利用できます。", "source_ids": ["R1"]}
        ],
        "changes": [
            {
                "category": "新機能",
                "title": "`/foo` コマンド追加",
                "detail": "新しい操作を利用できます。",
                "identifiers": ["/foo"],
                "source_ids": ["R1"],
            }
        ],
        "breaking_changes": [],
        "impact": [{"text": "CLI利用者が対象です。", "source_ids": ["R1"]}],
        "recommended_action": [
            {"text": "次回更新時に確認してください。", "source_ids": ["R1"]}
        ],
        "notes": [],
    }


def _sources():
    return build_source_bullets("## What's changed\n\n- Added `/foo` command for CLI users")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Added a command", "新機能"),
        ("Fixed a crash", "バグ修正"),
        ("Improved rendering", "改善"),
        ("Changed the default", "仕様変更"),
        ("Deprecated an option", "廃止予定"),
        ("Removed an option", "削除"),
        ("Hardened path validation", "セキュリティ"),
        ("Bug fixes and reliability improvements", "その他"),
    ],
)
def test_classify_source_category(text: str, expected: str) -> None:
    assert classify_source_category(text) == expected


def test_strict_json_schema_closes_every_object() -> None:
    def walk(node: object) -> None:
        if isinstance(node, Mapping):
            if node.get("type") == "object":
                assert node.get("additionalProperties") is False
                properties = node.get("properties")
                assert isinstance(properties, Mapping)
                assert set(node.get("required", [])) == set(properties)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(STRUCTURED_REPORT_JSON_SCHEMA)
    response_format = build_groq_response_format()
    assert response_format["type"] == "json_schema"
    json_schema = response_format["json_schema"]
    assert isinstance(json_schema, Mapping)
    assert json_schema["strict"] is True


def test_parse_and_render_source_grounded_report() -> None:
    report = parse_structured_report(_valid_payload(), _sources())

    markdown = render_summary_markdown(report)

    assert "<!-- section:summary -->\n## 要約" in markdown
    assert "<!-- sources:R1 -->" in markdown
    assert "<!-- section:changes -->\n## 変更内容" in markdown
    assert "### 新機能" in markdown
    assert "  - 関連: `/foo`" in markdown


def test_rejects_unknown_source_id() -> None:
    payload = _valid_payload()
    payload["summary"] = {"text": "要約", "source_ids": ["R99"]}

    with pytest.raises(StructuredReportError, match="未知のsource_id"):
        parse_structured_report(payload, _sources())


def test_rejects_category_changed_by_model() -> None:
    payload = _valid_payload()
    payload["changes"] = [
        {
            "category": "バグ修正",
            "title": "`/foo` コマンド追加",
            "detail": "",
            "identifiers": ["/foo"],
            "source_ids": ["R1"],
        }
    ]

    with pytest.raises(StructuredReportError, match="原文分類と一致"):
        parse_structured_report(payload, _sources())


def test_rejects_identifier_not_present_in_source() -> None:
    payload = _valid_payload()
    payload["changes"] = [
        {
            "category": "新機能",
            "title": "`/bar` コマンド追加",
            "detail": "",
            "identifiers": ["/bar"],
            "source_ids": ["R1"],
        }
    ]

    with pytest.raises(StructuredReportError, match="参照元R1に存在しません"):
        parse_structured_report(payload, _sources())


def test_rejects_combining_multiple_sources_into_one_change() -> None:
    sources = build_source_bullets("- Added `/foo`\n- Added `/bar`")
    payload = _valid_payload()
    payload["changes"] = [
        {
            "category": "新機能",
            "title": "コマンド追加",
            "detail": "",
            "identifiers": [],
            "source_ids": ["R1", "R2"],
        }
    ]

    with pytest.raises(StructuredReportError, match="1件だけ"):
        parse_structured_report(payload, sources)


def test_rejects_source_id_reused_by_multiple_changes() -> None:
    payload = _valid_payload()
    first_change = payload["changes"][0]  # type: ignore[index]
    assert isinstance(first_change, dict)
    payload["changes"] = [first_change, dict(first_change, title="別の要旨")]

    with pytest.raises(StructuredReportError, match="同じsource_id"):
        parse_structured_report(payload, _sources())


def test_empty_release_uses_deterministic_fallback() -> None:
    report = parse_or_build_empty_release(None, "## What's changed\n")

    assert report == build_empty_release_report()
    assert report.judgement["変更記載"] == "具体的な変更記載なし"
    assert report.changes == ()


def test_nonempty_release_requires_structured_payload() -> None:
    with pytest.raises(StructuredReportError, match="構造化LLM出力が必要"):
        parse_or_build_empty_release(None, "- Added `/foo`")
