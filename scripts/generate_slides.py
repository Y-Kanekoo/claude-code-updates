from __future__ import annotations

import argparse
import html
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

try:
    from report_schema import SECTION_TITLES, parse_sections
except ImportError:  # pragma: no cover - package import時の経路
    from scripts.report_schema import SECTION_TITLES, parse_sections


MARP_FRONT_MATTER = """---
marp: true
theme: default
paginate: true
size: 16:9
---
"""

REPORT_NAME_PATTERN = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2})-(?P<version>v[\w.-]+)$"
)
MAX_SLIDE_CONTENT_LINES = 20
CHANGE_CATEGORY_RE = re.compile(r"^###\s+(.+?)\s*$", re.MULTILINE)


@dataclass(frozen=True)
class SlideEntry:
    """スライド一覧ページに表示する1件分の情報。"""

    html_filename: str
    label: str
    version_key: tuple[int, ...]
    date: str


def preprocess_for_marp(source: str) -> str:
    """アンカー基準でレポートをMarpスライドへ変換する。

    H2/H3そのものを境界にせず、安定した ``section:`` アンカーを使う。
    ``変更内容`` はカテゴリごとに分割し、1枚が行数上限を超えないよう
    箇条書き単位でページ分割する。
    """
    if "<!-- section:" not in source:
        return _preprocess_legacy_headings(source)

    sections = parse_sections(source)
    title_block = _extract_title_block(source)
    slide_bodies: list[str] = []
    if title_block:
        slide_bodies.extend(_split_to_budget(title_block))

    for section_id in (
        "links",
        "summary",
        "judgement",
        "highlights",
        "changes",
        "breaking_changes",
        "impact",
        "recommended_action",
        "notes",
    ):
        body = sections.get(section_id)
        if not body:
            continue
        if section_id == "changes":
            slide_bodies.extend(_build_change_slides(body))
            continue
        heading = SECTION_TITLES[section_id]
        section_markdown = (
            f"<!-- section:{section_id} -->\n## {heading}\n\n{body}"
        ).strip()
        slide_bodies.extend(_split_to_budget(section_markdown))

    processed = "\n\n---\n\n".join(slide_bodies).rstrip() + "\n"
    return f"{MARP_FRONT_MATTER}\n{processed}"


def _preprocess_legacy_headings(source: str) -> str:
    """アンカー導入前の入力に対する後方互換前処理。"""
    processed_lines: list[str] = []
    for line in source.splitlines(keepends=True):
        if line.startswith("### "):
            processed_lines.append("\n---\n\n")
        processed_lines.append(line)
    processed = "".join(processed_lines)
    if processed and not processed.endswith("\n"):
        processed += "\n"
    return f"{MARP_FRONT_MATTER}\n{processed}"


def validate_slide_budget(markdown: str) -> list[str]:
    """Marp Markdownの各スライドが内容行上限内か検証する。"""
    body = markdown.removeprefix(MARP_FRONT_MATTER).lstrip("\n")
    errors: list[str] = []
    for slide_number, slide in enumerate(body.split("\n---\n"), start=1):
        content_lines = _content_line_count(slide)
        if content_lines > MAX_SLIDE_CONTENT_LINES:
            errors.append(
                f"スライド{slide_number}が{content_lines}行です。"
                f"上限は{MAX_SLIDE_CONTENT_LINES}行です。"
            )
    return errors


def _extract_title_block(source: str) -> str:
    """最初のアンカー前にあるタイトル・判定表を取り出す。"""
    first_anchor = source.find("<!-- section:")
    prefix = source if first_anchor < 0 else source[:first_anchor]
    return prefix.strip()


def _build_change_slides(body: str) -> list[str]:
    """変更内容をカテゴリごとの独立スライドへ変換する。"""
    matches = list(CHANGE_CATEGORY_RE.finditer(body))
    if not matches:
        return _split_to_budget(
            f"<!-- section:changes -->\n## 変更内容\n\n{body}".strip()
        )

    slides: list[str] = []
    prefix = body[: matches[0].start()].strip()
    if prefix:
        slides.extend(
            _split_to_budget(
                f"<!-- section:changes -->\n## 変更内容\n\n{prefix}"
            )
        )
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        category = match.group(1).strip()
        category_body = body[match.end() : end].strip()
        slides.extend(
            _split_to_budget(
                (
                    f"<!-- section:changes -->\n"
                    f"## 変更内容 — {category}\n\n{category_body}"
                ).strip()
            )
        )
    return slides


def _split_to_budget(markdown: str) -> list[str]:
    """見出しを複製しながら箇条書きブロック単位で分割する。"""
    if _content_line_count(markdown) <= MAX_SLIDE_CONTENT_LINES:
        return [markdown]

    lines = markdown.splitlines()
    heading = lines[0]
    body_lines = lines[1:]
    blocks: list[list[str]] = []
    current: list[str] = []
    for line in body_lines:
        if line.startswith("- ") and current:
            blocks.append(current)
            current = [line]
        else:
            current.append(line)
    if current:
        blocks.append(current)

    slides: list[str] = []
    current_lines = [heading]
    for block in blocks:
        candidate = current_lines + [""] + block
        if len(current_lines) > 1 and _content_line_count("\n".join(candidate)) > MAX_SLIDE_CONTENT_LINES:
            slides.append("\n".join(current_lines).strip())
            current_lines = [heading, "（続き）", "", *block]
        else:
            current_lines = candidate
    if current_lines:
        slides.append("\n".join(current_lines).strip())

    oversized = [slide for slide in slides if _content_line_count(slide) > MAX_SLIDE_CONTENT_LINES]
    if oversized:
        raise ValueError(
            "単一の箇条書きがスライド行数上限を超えています。"
            f"上限: {MAX_SLIDE_CONTENT_LINES}行"
        )
    return slides


def _content_line_count(markdown: str) -> int:
    return sum(
        1
        for line in markdown.splitlines()
        if line.strip() and not line.strip().startswith("<!--")
    )


def collect_report_files(reports_dir: Path) -> list[Path]:
    """入力ディレクトリからスライド化対象のレポートMarkdownを列挙する。"""
    if not reports_dir.exists():
        raise FileNotFoundError(f"reports directory not found: {reports_dir}")

    return sorted(
        path
        for path in reports_dir.glob("*.md")
        if path.is_file() and path.name != "index.md"
    )


def version_sort_key(version: str) -> tuple[int, ...]:
    """バージョン文字列を降順ソート用の数値タプルに変換する。"""
    numbers = tuple(int(part) for part in re.findall(r"\d+", version))
    return numbers if numbers else (0,)


def build_slide_entry(markdown_path: Path) -> SlideEntry:
    """生成したMarkdownファイル名から一覧ページ用の表示情報を作る。"""
    match = REPORT_NAME_PATTERN.match(markdown_path.stem)
    html_filename = f"{markdown_path.stem}.html"

    if match is None:
        return SlideEntry(
            html_filename=html_filename,
            label=markdown_path.stem,
            version_key=(0,),
            date="",
        )

    date = match.group("date")
    version = match.group("version")
    return SlideEntry(
        html_filename=html_filename,
        label=f"{version} ({date})",
        version_key=version_sort_key(version),
        date=date,
    )


def build_index_html(entries: Sequence[SlideEntry]) -> str:
    """生成済みスライドへのリンク一覧HTMLを生成する。"""
    sorted_entries = sorted(
        entries,
        key=lambda entry: (entry.version_key, entry.date, entry.html_filename),
        reverse=True,
    )
    links = "\n".join(
        "    "
        f'<li><a href="./{html.escape(entry.html_filename, quote=True)}">'
        f"{html.escape(entry.label)}</a></li>"
        for entry in sorted_entries
    )

    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <title>Claude Code 更新スライド一覧</title>
  <style>
    body {{ font-family: system-ui; max-width: 800px; margin: 2em auto; padding: 0 1em; }}
    h1 {{ border-bottom: 1px solid #ccc; padding-bottom: 0.3em; }}
    ul {{ list-style: none; padding: 0; }}
    li {{ padding: 0.5em 0; }}
    a {{ color: #2563eb; text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
  </style>
</head>
<body>
  <h1>Claude Code 更新スライド一覧</h1>
  <ul>
{links}
  </ul>
</body>
</html>
"""


def generate_slides(reports_dir: Path, output_dir: Path) -> int:
    """レポートMarkdownを前処理し、スライド用Markdownと一覧HTMLを書き出す。"""
    report_files = collect_report_files(reports_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    for stale_file in output_dir.glob("*.md"):
        stale_file.unlink()

    generated_paths: list[Path] = []
    for report_path in report_files:
        source = report_path.read_text(encoding="utf-8")
        output_path = output_dir / report_path.name
        processed = preprocess_for_marp(source)
        budget_errors = validate_slide_budget(processed)
        if budget_errors:
            raise ValueError("\n".join(budget_errors))
        output_path.write_text(processed, encoding="utf-8")
        generated_paths.append(output_path)

    index_path = output_dir.parent / "index.html"
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(
        build_index_html([build_slide_entry(path) for path in generated_paths]),
        encoding="utf-8",
    )

    return len(generated_paths)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """コマンドライン引数を解析する。"""
    parser = argparse.ArgumentParser(
        description="Claude Code更新レポートをMarpスライド用Markdownへ変換します。"
    )
    parser.add_argument(
        "--reports-dir",
        type=Path,
        default=Path("reports/claude-code"),
        help="入力元のレポートMarkdownディレクトリ",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("docs/slides/src"),
        help="スライド用Markdownの出力先ディレクトリ",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """CLIエントリーポイント。"""
    args = parse_args(argv)
    count = generate_slides(args.reports_dir, args.output_dir)
    print(f"スライド用Markdownを生成: {count}件")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
