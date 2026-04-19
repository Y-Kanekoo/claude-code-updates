from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final


CANONICAL_SECTIONS: list[str] = [
    "summary",
    "judgement",
    "links",
    "highlights",
    "changes",
    "breaking_changes",
    "impact",
    "recommended_action",
    "notes",
]

SECTION_ALIASES: dict[str, str] = {
    "TL;DR": "summary",
    "要約": "summary",
    "判定": "judgement",
    "関連リンク": "links",
    "先に押さえるポイント": "highlights",
    "要対応・確認事項": "highlights",
    "HIGHLIGHTS": "highlights",
    "変更内容": "changes",
    "破壊的変更": "breaking_changes",
    "影響範囲": "impact",
    "推奨対応": "recommended_action",
    "推奨アクション": "recommended_action",
    "補足": "notes",
    "新機能": "changes",
    "改善": "changes",
    "バグ修正": "changes",
}

JUDGEMENT_KEYS: list[str] = ["影響度", "破壊的変更", "変更記載", "推奨アクション"]
IMPACT_LEVELS: list[str] = ["高", "中", "低", "要確認"]
BREAKING_LEVELS: list[str] = ["あり", "公式リリースノート上の明示なし", "要確認"]
CHANGE_RECORD_LEVELS: list[str] = ["あり", "具体的な変更記載なし"]
RECOMMENDED_ACTION_LEVELS: list[str] = ["即対応", "次回更新時に確認", "様子見"]
DISCORD_COLOR_NORMAL: int = 0x8B5CF6
DISCORD_COLOR_WARN: int = 0xF59E0B
DISCORD_COLOR_BREAKING: int = 0xEF4444

_CANONICAL_SECTION_SET: Final[set[str]] = set(CANONICAL_SECTIONS)
_ANCHOR_RE: Final[re.Pattern[str]] = re.compile(r"^\s*<!--\s*section:([A-Za-z0-9_]+)\s*-->\s*$")
_HEADING_RE: Final[re.Pattern[str]] = re.compile(r"^\s*###\s+(.+?)\s*$")
_URL_RE: Final[re.Pattern[str]] = re.compile(r"https?://[^\s<>)\]]+")
_JUDGEMENT_RE: Final[re.Pattern[str]] = re.compile(
    r"^\s*-\s*\*\*"
    r"(?P<key>影響度|破壊的変更|変更記載|推奨アクション)"
    r"(?:(?:[:：]\*\*)|(?:\*\*\s*[:：]))"
    r"\s*(?P<value>.+?)\s*$"
)

_LEVELS_BY_KEY: Final[dict[str, list[str]]] = {
    "影響度": IMPACT_LEVELS,
    "破壊的変更": BREAKING_LEVELS,
    "変更記載": CHANGE_RECORD_LEVELS,
    "推奨アクション": RECOMMENDED_ACTION_LEVELS,
}


@dataclass(frozen=True)
class _SectionMarker:
    """セクション境界と、採用する場合の内部IDを保持する。"""

    line_index: int
    content_start: int
    section_id: str | None


def parse_sections(markdown: str) -> dict[str, str]:
    """Markdown断片から既知セクションを内部IDに正規化して返す。"""
    lines = markdown.splitlines()
    markers = _collect_section_markers(lines)
    sections: dict[str, str] = {}

    for index, marker in enumerate(markers):
        if marker.section_id is None:
            continue

        end = markers[index + 1].line_index if index + 1 < len(markers) else len(lines)
        body = _clean_section_body(lines[marker.content_start : end])
        sections[marker.section_id] = body

    return sections


def extract_summary(sections: dict[str, str]) -> str:
    """要約セクションから最初の非メタ箇条書きだけを取り出す。"""
    summary = sections.get("summary", "")
    for line in summary.splitlines():
        stripped = line.strip()
        if not stripped.startswith("- "):
            continue

        item = stripped[2:].strip()
        if item.startswith("**"):
            continue
        if item:
            return item

    return ""


def extract_judgement(sections: dict[str, str]) -> dict[str, str]:
    """判定セクションから4種類の判定値を抽出する。"""
    judgement: dict[str, str] = {}

    for line in sections.get("judgement", "").splitlines():
        match = _JUDGEMENT_RE.match(line)
        if match is None:
            continue

        key = match.group("key")
        value = match.group("value").strip()
        judgement[key] = value

    return judgement


def is_empty_release(judgement: dict[str, str]) -> bool:
    """変更記載なしの空リリースかどうかを判定する。"""
    return judgement.get("変更記載") == "具体的な変更記載なし"


def validate_report(markdown: str) -> list[str]:
    """レポート本文が固定スキーマを満たすか検証する。"""
    sections = parse_sections(markdown)
    judgement = extract_judgement(sections)
    empty_release = is_empty_release(judgement)
    required_sections = ["summary", "judgement", "links"]
    if not empty_release:
        required_sections.extend(
            ["highlights", "changes", "breaking_changes", "impact", "recommended_action"]
        )

    errors: list[str] = []
    present_anchors = _find_present_anchors(markdown)

    for section_id in required_sections:
        if section_id not in present_anchors:
            errors.append(f"必須アンカーコメントがありません: <!-- section:{section_id} -->")

    links = sections.get("links", "")
    urls = _URL_RE.findall(links)
    if len(urls) < 2:
        errors.append("関連リンクセクションにはHTTP(S) URLが2つ以上必要です。")

    if empty_release:
        if not any("docs.anthropic.com" in url for url in urls):
            errors.append("空リリースの関連リンクにはdocs.anthropic.comのURLが必要です。")
    elif not (
        any("github.com" in url for url in urls)
        and any("docs.anthropic.com" in url for url in urls)
    ):
        errors.append("関連リンクにはgithub.comとdocs.anthropic.comの両方のURLが必要です。")

    for key in JUDGEMENT_KEYS:
        value = judgement.get(key)
        if value is None:
            errors.append(f"判定セクションに「{key}」がありません。")
            continue

        allowed_values = _LEVELS_BY_KEY[key]
        if value not in allowed_values:
            joined = " / ".join(allowed_values)
            errors.append(f"判定「{key}」の値「{value}」は許可されていません。許可値: {joined}")

    return errors


def pick_discord_color(judgement: dict[str, str]) -> int:
    """判定値からDiscord Embedの色を選ぶ。"""
    if judgement.get("破壊的変更") == "あり":
        return DISCORD_COLOR_BREAKING
    if judgement.get("影響度") == "要確認" or is_empty_release(judgement):
        return DISCORD_COLOR_WARN
    return DISCORD_COLOR_NORMAL


def build_header_table(judgement: dict[str, str], release_date: str) -> str:
    """判定値を5列1行のMarkdownテーブルに整形する。"""
    fallback = "—"
    impact = judgement.get("影響度", fallback)
    breaking = judgement.get("破壊的変更", fallback)
    change_record = judgement.get("変更記載", fallback)
    recommended_action = judgement.get("推奨アクション", fallback)

    return (
        "| リリース日 | 影響度 | 破壊的変更 | 変更記載 | 推奨アクション |\n"
        "|---|---|---|---|---|\n"
        f"| {release_date} | {impact} | {breaking} | {change_record} | {recommended_action} |\n"
    )


def _collect_section_markers(lines: list[str]) -> list[_SectionMarker]:
    markers: list[_SectionMarker] = []
    skipped_heading_indexes: set[int] = set()

    for line_index, line in enumerate(lines):
        if line_index in skipped_heading_indexes:
            continue

        anchor_match = _ANCHOR_RE.match(line)
        if anchor_match is not None:
            section_id = anchor_match.group(1)
            content_start = line_index + 1
            heading_index = _find_following_heading_index(lines, content_start)
            if heading_index is not None:
                skipped_heading_indexes.add(heading_index)
                content_start = heading_index + 1

            markers.append(
                _SectionMarker(
                    line_index=line_index,
                    content_start=content_start,
                    section_id=section_id if section_id in _CANONICAL_SECTION_SET else None,
                )
            )
            continue

        heading_match = _HEADING_RE.match(line)
        if heading_match is not None:
            heading = _normalize_heading(heading_match.group(1))
            markers.append(
                _SectionMarker(
                    line_index=line_index,
                    content_start=line_index + 1,
                    section_id=SECTION_ALIASES.get(heading),
                )
            )

    return markers


def _find_following_heading_index(lines: list[str], start_index: int) -> int | None:
    index = start_index
    while index < len(lines) and lines[index].strip() == "":
        index += 1

    if index < len(lines) and _HEADING_RE.match(lines[index]) is not None:
        return index

    return None


def _normalize_heading(heading: str) -> str:
    return heading.strip().removesuffix("###").strip()


def _clean_section_body(lines: list[str]) -> str:
    body_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped == "---" or stripped.startswith("<sub>"):
            break
        body_lines.append(line)

    return "\n".join(body_lines).strip()


def _find_present_anchors(markdown: str) -> set[str]:
    anchors: set[str] = set()
    for line in markdown.splitlines():
        match = _ANCHOR_RE.match(line)
        if match is not None:
            anchors.add(match.group(1))
    return anchors
