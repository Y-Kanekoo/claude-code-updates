#!/usr/bin/env python3
"""
Claude Code リリース一覧インデックス生成スクリプト

reports/claude-code/ 内のレポートファイルを走査し、
index.md（人間向け一覧）と index.json（機械処理用）を生成する。
新旧の両レポートフォーマットに対応している。
"""

import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent))
from report_schema import extract_judgement, extract_summary, parse_sections

REPORTS_DIR = Path(__file__).parent.parent / "reports" / "claude-code"
INDEX_MD = REPORTS_DIR / "index.md"
INDEX_JSON = REPORTS_DIR / "index.json"
# インデックス生成時に除外するファイル名
EXCLUDE_FILES = {"index.md", "last-checked.json"}
JUDGEMENT_META_RE = re.compile(
    r"^\s*-\s*\*\*(影響度|破壊的変更)(?:(?:[:：]\*\*)|(?:\*\*\s*[:：]))\s*(.+?)\s*$"
)


def extract_version(content: str) -> Optional[str]:
    """## vX.X.X または ## vX.X.X (date) 形式からバージョンを抽出"""
    match = re.search(r"^## (v[\d.]+)", content, re.MULTILINE)
    return match.group(1) if match else None


def extract_date(content: str) -> Optional[str]:
    """リリース日を抽出（新旧2種類のフォーマットに対応）"""
    # 新フォーマット: - **リリース日**: YYYY-MM-DD
    match = re.search(r"\*\*リリース日\*\*[：:]\s*(\d{4}-\d{2}-\d{2})", content)
    if match:
        return match.group(1)
    # 旧フォーマット（テーブル）: | YYYY-MM-DD | [GitHub →](...) |
    match = re.search(r"\|\s*(\d{4}-\d{2}-\d{2})\s*\|", content)
    if match:
        return match.group(1)
    # ## vX.X.X (YYYY-MM-DD) 形式
    match = re.search(r"^## v[\d.]+\s+\((\d{4}-\d{2}-\d{2})\)", content, re.MULTILINE)
    return match.group(1) if match else None


def _extract_legacy_tldr(content: str) -> str:
    """旧フォーマットのTL;DR要約文を抽出する。"""
    # 見出し形式: ### TL;DR セクションの最初の非メタ行
    in_tldr = False
    for line in content.splitlines():
        if line.startswith("### TL;DR"):
            in_tldr = True
            continue
        if in_tldr:
            if line.startswith("### "):
                break
            stripped = line.lstrip("- ").strip()
            # **影響度**: 等のメタ行を除外し、最初の要約文を返す
            if stripped and not stripped.startswith("**"):
                return stripped
    # 旧フォーマット: > **TL;DR**: text
    match = re.search(r">\s*\*\*TL;DR\*\*[：:]\s*(.+)", content)
    if match:
        return match.group(1).strip()
    return ""


def _version_tuple(version: str) -> tuple[int, ...]:
    """vX.Y.Z形式を比較用の整数タプルに変換する。"""
    return tuple(int(part) for part in version.lstrip("v").split(".") if part.isdigit())


def _allows_tldr_judgement_fallback(version: str) -> bool:
    """移行期メタ行の補完対象を新フォーマット導入後に限定する。"""
    return _version_tuple(version) >= (2, 1, 101)


def _extract_judgement_with_fallback(
    sections: dict[str, str], version: str
) -> dict[str, str]:
    """判定セクションを主に使い、移行期のTL;DRメタ行も補助的に拾う。"""
    judgement = extract_judgement(sections)
    if "影響度" in judgement and "破壊的変更" in judgement:
        return judgement
    if not _allows_tldr_judgement_fallback(version):
        return judgement

    summary = sections.get("summary", "")
    for line in summary.splitlines():
        match = JUDGEMENT_META_RE.match(line)
        if match is None:
            continue

        key = match.group(1)
        if key not in judgement:
            judgement[key] = match.group(2).strip()

    return judgement


def _escape_table_cell(value: str) -> str:
    """Markdownテーブルのセル値を安全に整形する。"""
    return value.replace("\n", " ").replace("|", r"\|")


def _format_table_row(release: dict[str, str]) -> str:
    """リリース1件をMarkdownテーブル行に整形する。"""
    version_label = f"[{release['version']}](./{release['file']})"
    if release["breaking"] == "あり":
        version_label = f"⚠️ {version_label}"

    tldr = release["tldr"] or "—"
    return (
        f"| {version_label} | {release['date']} | "
        f"{_escape_table_cell(release['impact'])} | "
        f"{_escape_table_cell(release['breaking'])} | "
        f"{_escape_table_cell(tldr)} |"
    )


def parse_report(path: Path) -> Optional[dict[str, str]]:
    """レポートファイルを解析してメタデータ辞書を返す"""
    try:
        content = path.read_text(encoding="utf-8")
    except IOError as e:
        print(f"警告: {path.name} の読み込みに失敗しました: {e}")
        return None

    version = extract_version(content)
    if not version:
        return None

    sections = parse_sections(content)
    judgement = _extract_judgement_with_fallback(sections, version)
    tldr = extract_summary(sections) or _extract_legacy_tldr(content)

    return {
        "version": version,
        "date": extract_date(content) or "",
        "file": path.name,
        "tldr": tldr,
        "impact": judgement.get("影響度", "—"),
        "breaking": judgement.get("破壊的変更", "—"),
    }


def generate_index() -> None:
    """index.md と index.json を生成"""
    # 除外ファイルを除く .md ファイルを収集し、ファイル名降順（新しい順）でソート
    report_files = sorted(
        (f for f in REPORTS_DIR.glob("*.md") if f.name not in EXCLUDE_FILES),
        reverse=True,
    )

    releases = [r for f in report_files if (r := parse_report(f)) is not None]

    now = datetime.now()
    generated_at = now.isoformat(timespec="seconds")
    today = now.strftime("%Y-%m-%d")

    # --- index.md の生成 ---
    latest = releases[0] if releases else None

    table_rows = "\n".join(_format_table_row(r) for r in releases)

    latest_section = ""
    if latest:
        latest_lines = [
            f"- **バージョン**: {latest['version']}",
            f"- **リリース日**: {latest['date']}",
        ]
        if latest["impact"] != "—":
            latest_lines.append(f"- **影響度**: {latest['impact']}")
        if latest["breaking"] != "—":
            latest_lines.append(f"- **破壊的変更**: {latest['breaking']}")

        latest_section = "\n## 最新リリース\n\n" + "\n".join(latest_lines) + "\n"

    index_md_content = f"""# Claude Code 更新レポート 一覧

> 自動生成されています。最終更新: {today}
{latest_section}
## 全リリース一覧

| バージョン | リリース日 | 影響度 | 破壊的変更 | 要点 |
|---|---:|---|---|---|
{table_rows}
"""

    INDEX_MD.write_text(index_md_content, encoding="utf-8")
    print(f"index.md を生成しました ({len(releases)} 件): {INDEX_MD}")

    # --- index.json の生成 ---
    index_data = {
        "generated_at": generated_at,
        "releases": releases,
    }
    INDEX_JSON.write_text(
        json.dumps(index_data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"index.json を生成しました: {INDEX_JSON}")


if __name__ == "__main__":
    generate_index()
