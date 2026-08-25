from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

REPORT_SECTION_ORDER: list[str] = [
    "links",
    "summary",
    "judgement",
    "highlights",
    "changes",
    "breaking_changes",
    "impact",
    "recommended_action",
    "notes",
]

# 後方互換の公開名。順序は実際のレポート出力順に統一する。
CANONICAL_SECTIONS: list[str] = REPORT_SECTION_ORDER

SECTION_TITLES: dict[str, str] = {
    "links": "関連リンク",
    "summary": "要約",
    "judgement": "判定",
    "highlights": "先に押さえるポイント",
    "changes": "変更内容",
    "breaking_changes": "破壊的変更",
    "impact": "影響範囲",
    "recommended_action": "推奨対応",
    "notes": "補足",
}

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
_HEADING_RE: Final[re.Pattern[str]] = re.compile(
    r"^\s*(?P<marks>#{2,3})\s+(?P<title>.+?)\s*$"
)
_TITLE_RE: Final[re.Pattern[str]] = re.compile(
    r"^#\s+Claude Code 更新レポート\s*/\s*(?P<version>v\d+(?:\.\d+)+)\s*$",
    re.MULTILINE,
)
_FILENAME_RE: Final[re.Pattern[str]] = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2})-(?P<version>v\d+(?:\.\d+)+)\.md$"
)
_HEADER_DATA_RE: Final[re.Pattern[str]] = re.compile(
    r"^\|\s*(?P<date>\d{4}-\d{2}-\d{2})\s*"
    r"\|\s*(?P<impact>[^|]+?)\s*"
    r"\|\s*(?P<breaking>[^|]+?)\s*"
    r"\|\s*(?P<change_record>[^|]+?)\s*"
    r"\|\s*(?P<recommended_action>[^|]+?)\s*\|\s*$",
    re.MULTILINE,
)
_RELEASE_URL_RE: Final[re.Pattern[str]] = re.compile(
    r"https://github\.com/anthropics/claude-code/releases/tag/"
    r"(?P<version>v\d+(?:\.\d+)+)"
)
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


def validate_report(
    markdown: str,
    *,
    canonical: bool = False,
    filename: str | None = None,
    require_sources: bool = False,
) -> list[str]:
    """レポート本文が固定スキーマを満たすか検証する。

    ``canonical=False`` は既存のH3レポートを読み取るための互換モード。
    新規生成物とリポジトリ内コーパスは ``canonical=True`` で検証する。
    """
    sections = parse_sections(markdown)
    judgement = extract_judgement(sections)
    empty_release = is_empty_release(judgement)
    required_sections = ["summary", "judgement", "links"]
    if not empty_release:
        required_sections.extend(
            [
                "highlights",
                "changes",
                "breaking_changes",
                "impact",
                "recommended_action",
            ]
        )
        if canonical:
            required_sections.append("notes")

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

    if canonical:
        errors.extend(
            _validate_canonical_structure(
                markdown,
                sections=sections,
                judgement=judgement,
                empty_release=empty_release,
                filename=filename,
                require_sources=require_sources,
            )
        )

    return errors


def validate_canonical_report(
    markdown: str,
    *,
    filename: str | None = None,
    require_sources: bool = False,
) -> list[str]:
    """H2正規形式とファイルメタデータの整合性を厳格に検証する。"""
    return validate_report(
        markdown,
        canonical=True,
        filename=filename,
        require_sources=require_sources,
    )


def _validate_canonical_structure(
    markdown: str,
    *,
    sections: dict[str, str],
    judgement: dict[str, str],
    empty_release: bool,
    filename: str | None,
    require_sources: bool,
) -> list[str]:
    """正規形式にだけ適用する構造・メタデータ検証を行う。"""
    errors: list[str] = []
    lines = markdown.splitlines()
    anchor_entries = _collect_anchor_entries(lines)
    anchor_ids = [section_id for _, section_id in anchor_entries]
    counts = {section_id: anchor_ids.count(section_id) for section_id in set(anchor_ids)}

    unknown_anchors = sorted(set(anchor_ids) - _CANONICAL_SECTION_SET)
    for section_id in unknown_anchors:
        errors.append(f"未知のアンカーコメントです: <!-- section:{section_id} -->")

    for section_id, count in sorted(counts.items()):
        if count > 1:
            errors.append(f"アンカーコメントが重複しています: section:{section_id} ({count}件)")

    expected_order = ["links", "summary", "judgement"]
    if not empty_release:
        expected_order.extend(
            [
                "highlights",
                "changes",
                "breaking_changes",
                "impact",
                "recommended_action",
                "notes",
            ]
        )
    known_anchor_ids = [item for item in anchor_ids if item in _CANONICAL_SECTION_SET]
    if known_anchor_ids != expected_order:
        errors.append(
            "セクション順が正規形式と一致しません。"
            f"期待値: {' -> '.join(expected_order)} / 実際: {' -> '.join(known_anchor_ids)}"
        )

    for line_index, section_id in anchor_entries:
        expected_title = SECTION_TITLES.get(section_id)
        if expected_title is None:
            continue
        heading_index = _next_nonblank_line_index(lines, line_index + 1)
        if heading_index is None:
            errors.append(f"section:{section_id} の直後にH2見出しがありません。")
            continue
        expected_heading = f"## {expected_title}"
        if lines[heading_index].strip() != expected_heading:
            errors.append(
                f"section:{section_id} の見出しは「{expected_heading}」である必要があります。"
            )

    for section_id in expected_order:
        if not sections.get(section_id, "").strip():
            errors.append(f"セクション「{SECTION_TITLES[section_id]}」の本文が空です。")

    title_match = _TITLE_RE.search(markdown)
    if title_match is None:
        errors.append("H1タイトルが正規形式ではありません。")
        title_version = None
    else:
        title_version = title_match.group("version")

    header_match = _HEADER_DATA_RE.search(markdown)
    if header_match is None:
        errors.append("ヘッダー判定表のデータ行が正規形式ではありません。")
        header_date = None
    else:
        header_date = header_match.group("date")
        table_values = {
            "影響度": header_match.group("impact").strip(),
            "破壊的変更": header_match.group("breaking").strip(),
            "変更記載": header_match.group("change_record").strip(),
            "推奨アクション": header_match.group("recommended_action").strip(),
        }
        for key, table_value in table_values.items():
            judgement_value = judgement.get(key)
            if judgement_value is not None and table_value != judgement_value:
                errors.append(
                    f"ヘッダー判定表の「{key}」が判定セクションと一致しません。"
                    f"表: {table_value} / 判定: {judgement_value}"
                )

    release_versions = _RELEASE_URL_RE.findall(markdown)
    if title_version is not None:
        if not release_versions:
            errors.append("正規のGitHub Release URLがありません。")
        elif any(version != title_version for version in release_versions):
            errors.append("GitHub Release URLのタグがH1タイトルのバージョンと一致しません。")

    if filename is not None:
        filename_match = _FILENAME_RE.fullmatch(filename)
        if filename_match is None:
            errors.append(f"レポートファイル名が正規形式ではありません: {filename}")
        else:
            file_version = filename_match.group("version")
            file_date = filename_match.group("date")
            if title_version is not None and file_version != title_version:
                errors.append("ファイル名とH1タイトルのバージョンが一致しません。")
            if header_date is not None and file_date != header_date:
                errors.append("ファイル名とヘッダー判定表のリリース日が一致しません。")

    if require_sources and not empty_release:
        errors.extend(_validate_source_claims(markdown, anchor_entries))

    return errors


def _collect_anchor_entries(lines: list[str]) -> list[tuple[int, str]]:
    entries: list[tuple[int, str]] = []
    for line_index, line in enumerate(lines):
        match = _ANCHOR_RE.match(line)
        if match is not None:
            entries.append((line_index, match.group(1)))
    return entries


def _next_nonblank_line_index(lines: list[str], start_index: int) -> int | None:
    index = start_index
    while index < len(lines) and not lines[index].strip():
        index += 1
    return index if index < len(lines) else None


def _validate_source_claims(
    markdown: str,
    anchor_entries: list[tuple[int, str]],
) -> list[str]:
    """LLMが生成する主張にsource markerが隣接していることを検証する。"""
    errors: list[str] = []
    lines = markdown.splitlines()
    claim_sections = {
        "summary",
        "highlights",
        "changes",
        "breaking_changes",
        "impact",
        "recommended_action",
        "notes",
    }
    source_re = re.compile(r"^\s*<!--\s*sources:(R[1-9]\d*(?:,R[1-9]\d*)*)\s*-->\s*$")

    for entry_index, (anchor_line, section_id) in enumerate(anchor_entries):
        if section_id not in claim_sections:
            continue
        end_line = (
            anchor_entries[entry_index + 1][0]
            if entry_index + 1 < len(anchor_entries)
            else len(lines)
        )
        last_source_line: int | None = None
        for line_index in range(anchor_line + 1, end_line):
            stripped = lines[line_index].strip()
            if source_re.match(stripped):
                last_source_line = line_index
                continue
            if not stripped or stripped.startswith("#") or stripped == "なし":
                continue
            is_claim = lines[line_index].startswith("- ") and not stripped.startswith(
                "- **影響度**"
            )
            if is_claim:
                if last_source_line is None or last_source_line != line_index - 1:
                    errors.append(
                        f"section:{section_id} の主張に直前のsourcesコメントがありません: "
                        f"{stripped}"
                    )
                last_source_line = None
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
    has_section_anchors = any(_ANCHOR_RE.match(line) is not None for line in lines)

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
            # アンカー付き正規形式のH3は「変更内容」配下のカテゴリ見出し。
            # アンカーのない旧レポートだけH3をトップレベルとして互換解析する。
            if has_section_anchors and heading_match.group("marks") == "###":
                continue
            heading = _normalize_heading(heading_match.group("title"))
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
