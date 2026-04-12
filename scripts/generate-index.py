#!/usr/bin/env python3
"""
Claude Code リリース一覧インデックス生成スクリプト

reports/claude-code/ 内のレポートファイルを走査し、
index.md（人間向け一覧）と index.json（機械処理用）を生成する。
新旧の両レポートフォーマットに対応している。
"""

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

REPORTS_DIR = Path(__file__).parent.parent / "reports" / "claude-code"
INDEX_MD = REPORTS_DIR / "index.md"
INDEX_JSON = REPORTS_DIR / "index.json"
# インデックス生成時に除外するファイル名
EXCLUDE_FILES = {"index.md", "last-checked.json"}


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


def extract_tldr(content: str) -> str:
    """TL;DR要約文を抽出（新旧フォーマットに対応）"""
    # 新フォーマット: ### TL;DR セクションの最初の非メタ行
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


def parse_report(path: Path) -> Optional[dict]:
    """レポートファイルを解析してメタデータ辞書を返す"""
    try:
        content = path.read_text(encoding="utf-8")
    except IOError as e:
        print(f"警告: {path.name} の読み込みに失敗しました: {e}")
        return None

    version = extract_version(content)
    if not version:
        return None

    return {
        "version": version,
        "date": extract_date(content) or "",
        "file": path.name,
        "tldr": extract_tldr(content),
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

    table_rows = "\n".join(
        f"| [{r['version']}](./{r['file']}) | {r['date']} | {r['tldr'] or '—'} |"
        for r in releases
    )

    latest_section = ""
    if latest:
        latest_section = f"""
## 最新リリース

- **バージョン**: {latest['version']}
- **リリース日**: {latest['date']}
"""

    index_md_content = f"""# Claude Code 更新レポート 一覧

> 自動生成されています。最終更新: {today}
{latest_section}
## 全リリース一覧

| バージョン | リリース日 | 概要 |
|-----------|-----------|------|
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
