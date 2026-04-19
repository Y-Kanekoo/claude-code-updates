from __future__ import annotations

import argparse
import html
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


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


@dataclass(frozen=True)
class SlideEntry:
    """スライド一覧ページに表示する1件分の情報。"""

    html_filename: str
    label: str
    version_key: tuple[int, ...]
    date: str


def preprocess_for_marp(source: str) -> str:
    """既存レポートMarkdownをMarp向けMarkdownに変換する。"""
    processed_lines: list[str] = []

    for line in source.splitlines(keepends=True):
        if line.startswith("### "):
            processed_lines.append("\n---\n\n")
        processed_lines.append(line)

    processed = "".join(processed_lines)
    if processed and not processed.endswith("\n"):
        processed += "\n"

    return f"{MARP_FRONT_MATTER}\n{processed}"


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
        output_path.write_text(preprocess_for_marp(source), encoding="utf-8")
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
