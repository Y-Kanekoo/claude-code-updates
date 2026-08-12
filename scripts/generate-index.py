#!/usr/bin/env python3
"""
Claude Code リリース一覧インデックス生成スクリプト

reports/claude-code/ 内のレポートファイルを走査し、
index.md（人間向け一覧）と index.json（機械処理用）を生成する。
新旧の両レポートフォーマットに対応している。
"""

import argparse
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from report_schema import (
    extract_judgement,
    extract_summary,
    parse_sections,
    validate_canonical_report,
)

REPORTS_DIR = Path(__file__).parent.parent / "reports" / "claude-code"
INDEX_MD = REPORTS_DIR / "index.md"
INDEX_JSON = REPORTS_DIR / "index.json"
# インデックス生成時に除外するファイル名
EXCLUDE_FILES = {"index.md", "last-checked.json"}
JUDGEMENT_META_RE = re.compile(
    r"^\s*-\s*\*\*(影響度|破壊的変更)(?:(?:[:：]\*\*)|(?:\*\*\s*[:：]))\s*(.+?)\s*$"
)


def extract_version(content: str) -> str | None:
    """新旧レポート見出しからバージョンを抽出する。"""
    match = re.search(
        r"^(?:##\s+|#\s+Claude Code 更新レポート\s*/\s*)"
        r"(v\d+(?:\.\d+)+)(?:\s|$)",
        content,
        re.MULTILINE,
    )
    return match.group(1) if match else None


def extract_date(content: str) -> str | None:
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


class IndexGenerationError(RuntimeError):
    """レポート集合から安全に索引を生成できない。"""


def parse_report(
    path: Path, *, canonical: bool = False
) -> dict[str, str] | None:
    """レポートファイルを解析してメタデータ辞書を返す"""
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as e:
        print(f"警告: {path.name} の読み込みに失敗しました: {e}")
        return None

    version = extract_version(content)
    if not version:
        return None

    if canonical:
        errors = validate_canonical_report(content, filename=path.name)
        if errors:
            joined = "\n".join(f"- {error}" for error in errors)
            raise IndexGenerationError(f"{path.name} の検証に失敗しました。\n{joined}")

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


def _collect_releases() -> list[dict[str, str]]:
    """全レポートをfail-closedで解析し、semver降順に返す。"""
    # 除外ファイルを除く .md ファイルを収集し、ファイル名降順（新しい順）でソート
    report_files = sorted(
        (f for f in REPORTS_DIR.glob("*.md") if f.name not in EXCLUDE_FILES),
        reverse=True,
    )

    releases: list[dict[str, str]] = []
    failures: list[str] = []
    for report_file in report_files:
        try:
            release = parse_report(report_file, canonical=True)
        except IndexGenerationError as error:
            failures.append(str(error))
            continue
        if release is None:
            failures.append(f"{report_file.name}: バージョンを抽出できません。")
            continue
        releases.append(release)

    if failures:
        joined = "\n".join(f"- {failure}" for failure in failures)
        raise IndexGenerationError(f"索引対象レポートの解析に失敗しました。\n{joined}")

    versions = [release["version"] for release in releases]
    duplicate_versions = sorted(
        version for version in set(versions) if versions.count(version) > 1
    )
    if duplicate_versions:
        raise IndexGenerationError(
            "バージョンが重複しています: " + ", ".join(duplicate_versions)
        )

    releases.sort(key=lambda release: _version_tuple(release["version"]), reverse=True)
    return releases


def _render_index_contents(
    releases: list[dict[str, str]], generated_at: str
) -> tuple[str, str]:
    """索引2形式を同じ入力からメモリ上で構築する。"""
    try:
        generated_datetime = datetime.fromisoformat(generated_at)
    except ValueError as error:
        raise IndexGenerationError(f"generated_atがISO形式ではありません: {generated_at}") from error

    today = generated_datetime.strftime("%Y-%m-%d")

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

    index_data = {
        "generated_at": generated_at,
        "releases": releases,
    }
    index_json_content = json.dumps(index_data, ensure_ascii=False, indent=2) + "\n"
    return index_md_content, index_json_content


def _atomic_write_text(path: Path, content: str) -> None:
    """同一ディレクトリの一時ファイルを置換して途中書き込みを防ぐ。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            temporary_file.write(content)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
            temporary_path = Path(temporary_file.name)
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def _existing_generated_at() -> str:
    """--check用に既存JSONの生成時刻を再利用する。"""
    try:
        data = json.loads(INDEX_JSON.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise IndexGenerationError(f"既存index.jsonを読み込めません: {error}") from error
    generated_at = data.get("generated_at")
    if not isinstance(generated_at, str):
        raise IndexGenerationError("既存index.jsonにgenerated_at文字列がありません。")
    return generated_at


def generate_index(*, check: bool = False) -> bool:
    """index.md と index.json を生成、または既存内容との一致を検査する。"""
    releases = _collect_releases()
    generated_at = (
        _existing_generated_at()
        if check
        else datetime.now(timezone.utc).isoformat(timespec="seconds")
    )
    index_md_content, index_json_content = _render_index_contents(
        releases, generated_at
    )

    if check:
        mismatches: list[str] = []
        for path, expected in (
            (INDEX_MD, index_md_content),
            (INDEX_JSON, index_json_content),
        ):
            try:
                actual = path.read_text(encoding="utf-8")
            except OSError:
                actual = ""
            if actual != expected:
                mismatches.append(path.name)
        if mismatches:
            print(
                "索引が最新ではありません: " + ", ".join(mismatches),
                file=sys.stderr,
            )
            return False
        print(f"索引整合性を確認しました ({len(releases)} 件)")
        return True

    _atomic_write_text(INDEX_MD, index_md_content)
    _atomic_write_text(INDEX_JSON, index_json_content)
    print(f"index.md を生成しました ({len(releases)} 件): {INDEX_MD}")
    print(f"index.json を生成しました: {INDEX_JSON}")
    return True


def parse_args() -> argparse.Namespace:
    """CLI引数を解析する。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="索引を書き換えず、全レポートとの一致を検査する",
    )
    return parser.parse_args()


def main() -> int:
    """CLIエントリーポイント。"""
    args = parse_args()
    try:
        return 0 if generate_index(check=args.check) else 1
    except IndexGenerationError as error:
        print(f"エラー: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
