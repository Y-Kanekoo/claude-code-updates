from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final

try:
    from report_schema import (
        BREAKING_LEVELS,
        CHANGE_RECORD_LEVELS,
        IMPACT_LEVELS,
        RECOMMENDED_ACTION_LEVELS,
    )
except ImportError:  # pragma: no cover - package import時の経路
    from scripts.report_schema import (
        BREAKING_LEVELS,
        CHANGE_RECORD_LEVELS,
        IMPACT_LEVELS,
        RECOMMENDED_ACTION_LEVELS,
    )


CATEGORY_HEADINGS: Final[tuple[str, ...]] = (
    "新機能",
    "改善",
    "バグ修正",
    "仕様変更",
    "廃止予定",
    "削除",
    "セキュリティ",
    "その他",
)

_SOURCE_PREFIX_CATEGORIES: Final[tuple[tuple[str, str], ...]] = (
    ("Added", "新機能"),
    ("Improved", "改善"),
    ("Reduced", "改善"),
    ("Fixed", "バグ修正"),
    ("Changed", "仕様変更"),
    ("Updated", "仕様変更"),
    ("Completed", "仕様変更"),
    ("Capped", "仕様変更"),
    ("Deprecated", "廃止予定"),
    ("Removed", "削除"),
    ("Hardened", "セキュリティ"),
)

_BACKTICK_RE: Final[re.Pattern[str]] = re.compile(r"`([^`]+)`")

# Groq Strict Structured OutputsはuniqueItemsを受理しないため、
# 配列要素の重複はvalidate_structured_report()で検証する。
STRUCTURED_REPORT_JSON_SCHEMA: Final[dict[str, object]] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$defs": {
        "groundedText": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "minLength": 1},
                "source_ids": {
                    "type": "array",
                    "items": {"type": "string", "pattern": "^R[1-9][0-9]*$"},
                    "minItems": 1,
                },
            },
            "required": ["text", "source_ids"],
            "additionalProperties": False,
        }
    },
    "type": "object",
    "properties": {
        "summary": {"$ref": "#/$defs/groundedText"},
        "judgement": {
            "type": "object",
            "properties": {
                "影響度": {"type": "string", "enum": IMPACT_LEVELS},
                "破壊的変更": {"type": "string", "enum": BREAKING_LEVELS},
                "変更記載": {"type": "string", "enum": CHANGE_RECORD_LEVELS},
                "推奨アクション": {
                    "type": "string",
                    "enum": RECOMMENDED_ACTION_LEVELS,
                },
            },
            "required": ["影響度", "破壊的変更", "変更記載", "推奨アクション"],
            "additionalProperties": False,
        },
        "highlights": {
            "type": "array",
            "items": {"$ref": "#/$defs/groundedText"},
            "maxItems": 3,
        },
        "changes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "category": {"type": "string", "enum": list(CATEGORY_HEADINGS)},
                    "title": {"type": "string", "minLength": 1},
                    "detail": {"type": "string"},
                    "identifiers": {
                        "type": "array",
                        "items": {"type": "string", "minLength": 1},
                    },
                    "source_ids": {
                        "type": "array",
                        "items": {"type": "string", "pattern": "^R[1-9][0-9]*$"},
                        "minItems": 1,
                        "maxItems": 1,
                    },
                },
                "required": [
                    "category",
                    "title",
                    "detail",
                    "identifiers",
                    "source_ids",
                ],
                "additionalProperties": False,
            },
            "maxItems": 12,
        },
        "breaking_changes": {
            "type": "array",
            "items": {"$ref": "#/$defs/groundedText"},
            "maxItems": 3,
        },
        "impact": {
            "type": "array",
            "items": {"$ref": "#/$defs/groundedText"},
            "maxItems": 3,
        },
        "recommended_action": {
            "type": "array",
            "items": {"$ref": "#/$defs/groundedText"},
            "maxItems": 3,
        },
        "notes": {
            "type": "array",
            "items": {"$ref": "#/$defs/groundedText"},
            "maxItems": 3,
        },
    },
    "required": [
        "summary",
        "judgement",
        "highlights",
        "changes",
        "breaking_changes",
        "impact",
        "recommended_action",
        "notes",
    ],
    "additionalProperties": False,
}


@dataclass(frozen=True)
class SourceBullet:
    """公式リリースノートの箇条書き1件。"""

    source_id: str
    text: str
    category: str


@dataclass(frozen=True)
class GroundedText:
    """根拠となる公式箇条書きIDを伴う日本語テキスト。"""

    text: str
    source_ids: tuple[str, ...]


@dataclass(frozen=True)
class StructuredChange:
    """公式箇条書き1件から作る変更項目。"""

    category: str
    title: str
    detail: str
    identifiers: tuple[str, ...]
    source_ids: tuple[str, ...]


@dataclass(frozen=True)
class StructuredReport:
    """LLMから受け取るMarkdown非依存のレポート表現。"""

    summary: GroundedText
    judgement: Mapping[str, str]
    highlights: tuple[GroundedText, ...]
    changes: tuple[StructuredChange, ...]
    breaking_changes: tuple[GroundedText, ...]
    impact: tuple[GroundedText, ...]
    recommended_action: tuple[GroundedText, ...]
    notes: tuple[GroundedText, ...]


class StructuredReportError(ValueError):
    """LLM構造化出力がスキーマまたは原文根拠を満たさない。"""


def build_source_bullets(release_notes: str) -> tuple[SourceBullet, ...]:
    """Markdown箇条書きを安定した ``R1`` 形式の根拠へ変換する。"""
    raw_items: list[str] = []
    current: list[str] = []

    for line in release_notes.splitlines():
        if line.startswith("- "):
            if current:
                raw_items.append(" ".join(current).strip())
            current = [line[2:].strip()]
            continue
        if current and line.strip() and not line.lstrip().startswith("#"):
            current.append(line.strip())

    if current:
        raw_items.append(" ".join(current).strip())

    return tuple(
        SourceBullet(
            source_id=f"R{index}",
            text=text,
            category=classify_source_category(text),
        )
        for index, text in enumerate(raw_items, start=1)
    )


def classify_source_category(text: str) -> str:
    """公式ノート先頭の動詞を変更カテゴリへ決定的に変換する。"""
    stripped = text.strip()
    for prefix, category in _SOURCE_PREFIX_CATEGORIES:
        if stripped.startswith(f"{prefix} ") or stripped == prefix:
            return category
    return "その他"


def build_structured_request_payload(release_notes: str) -> str:
    """LLMへ渡す根拠付きJSON入力を生成する。

    固定の指示はsystem messageに置き、この戻り値は外部データとしてuser
    messageへ渡すことを想定する。
    """
    sources = build_source_bullets(release_notes)
    payload: dict[str, object] = {
        "sources": [
            {
                "source_id": source.source_id,
                "category": source.category,
                "text": source.text,
            }
            for source in sources
        ],
        "output_contract": {
            "summary": {"text": "日本語1文", "source_ids": ["R1"]},
            "judgement": {
                "影響度": IMPACT_LEVELS,
                "破壊的変更": BREAKING_LEVELS,
                "変更記載": CHANGE_RECORD_LEVELS,
                "推奨アクション": RECOMMENDED_ACTION_LEVELS,
            },
            "highlights": [{"text": "日本語1文", "source_ids": ["R1"]}],
            "changes": [
                {
                    "category": "入力sourceのcategoryと同じ値",
                    "title": "日本語の要旨",
                    "detail": "追加説明または空文字",
                    "identifiers": ["原文に存在する識別子"],
                    "source_ids": ["R1"],
                }
            ],
            "breaking_changes": [],
            "impact": [],
            "recommended_action": [],
            "notes": [],
        },
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def build_groq_response_format() -> dict[str, object]:
    """Groq Strict Structured Outputsへ渡す ``response_format`` を返す。"""
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "claude_code_release_report",
            "strict": True,
            "schema": STRUCTURED_REPORT_JSON_SCHEMA,
        },
    }


def parse_structured_report(
    payload: Mapping[str, object],
    sources: Sequence[SourceBullet],
) -> StructuredReport:
    """LLMのJSONオブジェクトを型付き表現へ変換し、根拠まで検証する。"""
    report = StructuredReport(
        summary=_parse_grounded_text(payload.get("summary"), "summary"),
        judgement=_parse_judgement(payload.get("judgement")),
        highlights=_parse_grounded_list(payload.get("highlights"), "highlights"),
        changes=_parse_changes(payload.get("changes")),
        breaking_changes=_parse_grounded_list(
            payload.get("breaking_changes"), "breaking_changes"
        ),
        impact=_parse_grounded_list(payload.get("impact"), "impact"),
        recommended_action=_parse_grounded_list(
            payload.get("recommended_action"), "recommended_action"
        ),
        notes=_parse_grounded_list(payload.get("notes"), "notes"),
    )
    errors = validate_structured_report(report, sources)
    if errors:
        raise StructuredReportError("\n".join(f"- {error}" for error in errors))
    return report


def build_empty_release_report() -> StructuredReport:
    """原文に具体的な箇条書きがない場合の決定的フォールバックを返す。"""
    no_source = ("R0",)
    return StructuredReport(
        summary=GroundedText(
            text="公式リリースノートに具体的な変更記載はありません。",
            source_ids=no_source,
        ),
        judgement={
            "影響度": "要確認",
            "破壊的変更": "要確認",
            "変更記載": "具体的な変更記載なし",
            "推奨アクション": "様子見",
        },
        highlights=(),
        changes=(),
        breaking_changes=(),
        impact=(),
        recommended_action=(),
        notes=(),
    )


def build_source_fallback_report(
    sources: Sequence[SourceBullet],
) -> StructuredReport:
    """LLM生成不能時に公式箇条書きを欠落なく原文で保持する。"""
    if not sources:
        return build_empty_release_report()

    report = StructuredReport(
        summary=GroundedText(
            text=(
                "Groqによる構造化要約を生成できなかったため、"
                "公式リリースノートの変更項目を原文のまま掲載します。"
            ),
            source_ids=(sources[0].source_id,),
        ),
        judgement={
            "影響度": "要確認",
            "破壊的変更": "要確認",
            "変更記載": "あり",
            "推奨アクション": "次回更新時に確認",
        },
        highlights=(),
        changes=tuple(
            StructuredChange(
                category=source.category,
                title=source.text,
                detail="",
                identifiers=(),
                source_ids=(source.source_id,),
            )
            for source in sources
        ),
        breaking_changes=(),
        impact=(),
        recommended_action=(),
        notes=(),
    )
    errors = validate_structured_report(report, sources)
    if errors:
        raise StructuredReportError(
            "公式リリースノートの決定的フォールバック生成に失敗しました:\n"
            + "\n".join(f"- {error}" for error in errors)
        )
    return report


def parse_or_build_empty_release(
    payload: Mapping[str, object] | None,
    release_notes: str,
) -> StructuredReport:
    """空の公式ノートではLLMを使わず固定レポートへフォールバックする。"""
    sources = build_source_bullets(release_notes)
    if not sources:
        return build_empty_release_report()
    if payload is None:
        raise StructuredReportError("変更記載があるため構造化LLM出力が必要です。")
    return parse_structured_report(payload, sources)


def validate_structured_report(
    report: StructuredReport,
    sources: Sequence[SourceBullet],
) -> list[str]:
    """source ID・分類・識別子を公式原文と照合する。"""
    errors: list[str] = []
    source_by_id = {source.source_id: source for source in sources}

    if len(source_by_id) != len(sources):
        errors.append("source_idが重複しています。")

    grounded_fields: list[tuple[str, GroundedText]] = [("summary", report.summary)]
    for field_name, values in (
        ("highlights", report.highlights),
        ("breaking_changes", report.breaking_changes),
        ("impact", report.impact),
        ("recommended_action", report.recommended_action),
        ("notes", report.notes),
    ):
        grounded_fields.extend((field_name, value) for value in values)

    for field_name, value in grounded_fields:
        errors.extend(
            _validate_grounding(
                field_name,
                value.text,
                value.source_ids,
                source_by_id,
            )
        )

    for index, change in enumerate(report.changes, start=1):
        field_name = f"changes[{index}]"
        if change.category not in CATEGORY_HEADINGS:
            errors.append(f"{field_name}.categoryが未許可です: {change.category}")
        if len(set(change.identifiers)) != len(change.identifiers):
            errors.append(f"{field_name}.identifiersが重複しています。")
        if len(change.source_ids) != 1:
            errors.append(f"{field_name}.source_idsは1件だけ指定してください。")
        errors.extend(
            _validate_grounding(
                field_name,
                f"{change.title}\n{change.detail}",
                change.source_ids,
                source_by_id,
            )
        )

        referenced_sources = [
            source_by_id[source_id]
            for source_id in change.source_ids
            if source_id in source_by_id
        ]
        if len(referenced_sources) == 1:
            source = referenced_sources[0]
            if change.category != source.category:
                errors.append(
                    f"{field_name}.categoryが原文分類と一致しません。"
                    f"期待値: {source.category} / 実際: {change.category}"
                )
            source_text = source.text
            identifiers = set(change.identifiers)
            identifiers.update(_BACKTICK_RE.findall(change.title))
            identifiers.update(_BACKTICK_RE.findall(change.detail))
            for identifier in sorted(identifiers):
                if identifier not in source_text:
                    errors.append(
                        f"{field_name}の識別子「{identifier}」が参照元"
                        f"{source.source_id}に存在しません。"
                    )

    change_source_ids = [
        source_id for change in report.changes for source_id in change.source_ids
    ]
    duplicate_change_sources = sorted(
        source_id
        for source_id in set(change_source_ids)
        if change_source_ids.count(source_id) > 1
    )
    if duplicate_change_sources:
        errors.append(
            "複数のchanges項目が同じsource_idを参照しています: "
            + ", ".join(duplicate_change_sources)
        )

    empty_release = report.judgement.get("変更記載") == "具体的な変更記載なし"
    if empty_release and report.changes:
        errors.append("具体的な変更記載なしのレポートにchangesを指定できません。")
    if not empty_release and not report.changes:
        errors.append("変更記載ありのレポートにはchangesが1件以上必要です。")

    return errors


def render_summary_markdown(report: StructuredReport) -> str:
    """検証済み構造化データをH2正規Markdown断片へ決定的に変換する。"""
    parts = [
        _render_grounded_section("summary", "要約", (report.summary,)),
        _render_judgement(report.judgement),
        _render_grounded_section("highlights", "先に押さえるポイント", report.highlights),
        _render_changes(report.changes),
        _render_grounded_section(
            "breaking_changes", "破壊的変更", report.breaking_changes
        ),
        _render_grounded_section("impact", "影響範囲", report.impact),
        _render_grounded_section(
            "recommended_action", "推奨対応", report.recommended_action
        ),
        _render_grounded_section("notes", "補足", report.notes),
    ]
    return "\n\n".join(parts)


def _parse_grounded_text(value: object, field_name: str) -> GroundedText:
    if not isinstance(value, Mapping):
        raise StructuredReportError(f"{field_name}はオブジェクトで指定してください。")
    text = value.get("text")
    if not isinstance(text, str) or not text.strip():
        raise StructuredReportError(f"{field_name}.textは空でない文字列が必要です。")
    source_ids = _parse_string_sequence(value.get("source_ids"), f"{field_name}.source_ids")
    return GroundedText(text=text.strip(), source_ids=source_ids)


def _parse_grounded_list(value: object, field_name: str) -> tuple[GroundedText, ...]:
    if not isinstance(value, list):
        raise StructuredReportError(f"{field_name}は配列で指定してください。")
    return tuple(
        _parse_grounded_text(item, f"{field_name}[{index}]")
        for index, item in enumerate(value, start=1)
    )


def _parse_judgement(value: object) -> Mapping[str, str]:
    if not isinstance(value, Mapping):
        raise StructuredReportError("judgementはオブジェクトで指定してください。")
    allowed = {
        "影響度": IMPACT_LEVELS,
        "破壊的変更": BREAKING_LEVELS,
        "変更記載": CHANGE_RECORD_LEVELS,
        "推奨アクション": RECOMMENDED_ACTION_LEVELS,
    }
    result: dict[str, str] = {}
    for key, allowed_values in allowed.items():
        item = value.get(key)
        if not isinstance(item, str) or item not in allowed_values:
            raise StructuredReportError(
                f"judgement.{key}は次から選択してください: {' / '.join(allowed_values)}"
            )
        result[key] = item
    return result


def _parse_changes(value: object) -> tuple[StructuredChange, ...]:
    if not isinstance(value, list):
        raise StructuredReportError("changesは配列で指定してください。")
    changes: list[StructuredChange] = []
    for index, item in enumerate(value, start=1):
        if not isinstance(item, Mapping):
            raise StructuredReportError(f"changes[{index}]はオブジェクトが必要です。")
        category = item.get("category")
        title = item.get("title")
        detail = item.get("detail", "")
        if not isinstance(category, str) or not category:
            raise StructuredReportError(f"changes[{index}].categoryが不正です。")
        if not isinstance(title, str) or not title.strip():
            raise StructuredReportError(f"changes[{index}].titleが不正です。")
        if not isinstance(detail, str):
            raise StructuredReportError(f"changes[{index}].detailが不正です。")
        changes.append(
            StructuredChange(
                category=category,
                title=title.strip(),
                detail=detail.strip(),
                identifiers=_parse_string_sequence(
                    item.get("identifiers", []), f"changes[{index}].identifiers"
                ),
                source_ids=_parse_string_sequence(
                    item.get("source_ids"), f"changes[{index}].source_ids"
                ),
            )
        )
    return tuple(changes)


def _parse_string_sequence(value: object, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise StructuredReportError(f"{field_name}は文字列配列で指定してください。")
    return tuple(item for item in value if item)


def _validate_grounding(
    field_name: str,
    text: str,
    source_ids: Sequence[str],
    source_by_id: Mapping[str, SourceBullet],
) -> list[str]:
    errors: list[str] = []
    if not text.strip():
        errors.append(f"{field_name}の本文が空です。")
    if not source_ids:
        errors.append(f"{field_name}.source_idsが空です。")
    if len(set(source_ids)) != len(source_ids):
        errors.append(f"{field_name}.source_idsが重複しています。")
    for source_id in source_ids:
        if source_id not in source_by_id:
            errors.append(f"{field_name}が未知のsource_idを参照しています: {source_id}")
    return errors


def _render_grounded_section(
    section_id: str,
    title: str,
    values: Sequence[GroundedText],
) -> str:
    lines = [f"<!-- section:{section_id} -->", f"## {title}"]
    if not values:
        lines.append("なし")
        return "\n".join(lines)
    for value in values:
        lines.append(f"<!-- sources:{','.join(value.source_ids)} -->")
        lines.append(f"- {value.text}")
    return "\n".join(lines)


def _render_judgement(judgement: Mapping[str, str]) -> str:
    return "\n".join(
        [
            "<!-- section:judgement -->",
            "## 判定",
            f"- **影響度**: {judgement['影響度']}",
            f"- **破壊的変更**: {judgement['破壊的変更']}",
            f"- **変更記載**: {judgement['変更記載']}",
            f"- **推奨アクション**: {judgement['推奨アクション']}",
        ]
    )


def _render_changes(changes: Sequence[StructuredChange]) -> str:
    lines = ["<!-- section:changes -->", "## 変更内容"]
    if not changes:
        lines.append("なし")
        return "\n".join(lines)

    by_category: dict[str, list[StructuredChange]] = {}
    for change in changes:
        by_category.setdefault(change.category, []).append(change)

    for category in CATEGORY_HEADINGS:
        category_changes = by_category.get(category, [])
        if not category_changes:
            continue
        lines.extend(["", f"### {category}"])
        for change in category_changes:
            lines.append(f"<!-- sources:{','.join(change.source_ids)} -->")
            lines.append(f"- **{change.title}**")
            if change.identifiers:
                identifiers = " / ".join(f"`{item}`" for item in change.identifiers)
                lines.append(f"  - 関連: {identifiers}")
            if change.detail:
                lines.append(f"  - {change.detail}")
    return "\n".join(lines)
