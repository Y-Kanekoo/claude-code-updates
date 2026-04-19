#!/usr/bin/env python3
from __future__ import annotations

"""ローカルProjects配下のプロジェクト概要カタログを生成する。"""

import argparse
import json
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Union, cast

JSONValue = Union[str, int, float, bool, None, List["JSONValue"], Dict[str, "JSONValue"]]

REPO_ROOT = Path(__file__).resolve().parents[1]
REPORTS_DIR = REPO_ROOT / "reports" / "claude-code"
DEFAULT_PROJECTS_DIR = Path.home() / "Projects"
DEFAULT_OUTPUT_PATH = REPORTS_DIR / ".project_catalog.json"
STACK_LIMIT = 3
INTENT_LIMIT = 60
EXCLUDED_PROJECT_NAMES = {"node_modules", "__pycache__"}


def extract_stack(project_dir: Path) -> List[str]:
    """プロジェクト定義ファイルから主要スタック名を最大3件抽出する。"""
    extractors = [
        _extract_package_json_stack,
        _extract_pyproject_stack,
        _extract_requirements_stack,
        _extract_cargo_stack,
        _extract_go_mod_stack,
    ]

    for extractor in extractors:
        stack = extractor(project_dir)
        if stack:
            return stack[:STACK_LIMIT]
    return []


def extract_intent(project_dir: Path) -> str:
    """CLAUDE.md または README.md からプロジェクト意図を短く抽出する。"""
    claude_path = project_dir / "CLAUDE.md"
    if claude_path.exists():
        try:
            for line in _read_limited_lines(claude_path, 100):
                stripped = line.strip()
                if stripped.startswith("## Intent:"):
                    return stripped.split(":", 1)[1].strip()[:INTENT_LIMIT]
        except OSError as exc:
            print(f"警告: {claude_path} の読み込みに失敗しました: {exc}")

    readme_path = project_dir / "README.md"
    if readme_path.exists():
        try:
            for line in _read_limited_lines(readme_path, 10):
                stripped = line.strip()
                if stripped and not stripped.startswith("#"):
                    return stripped[:INTENT_LIMIT]
        except OSError as exc:
            print(f"警告: {readme_path} の読み込みに失敗しました: {exc}")

    return ""


def extract_last_active(project_dir: Path) -> str:
    """git log から最終コミット日を YYYY-MM-DD 形式で取得する。"""
    try:
        result = subprocess.run(
            ["git", "log", "-1", "--format=%cs"],
            cwd=project_dir,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except subprocess.TimeoutExpired:
        print(f"警告: {project_dir} の git log がタイムアウトしました")
        return ""
    except OSError as exc:
        print(f"警告: {project_dir} の git log 実行に失敗しました: {exc}")
        return ""

    if result.returncode != 0:
        return ""

    last_active = result.stdout.strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", last_active):
        return last_active
    return ""


def build_catalog(
    projects_dir: Path = DEFAULT_PROJECTS_DIR,
    self_name: str = REPO_ROOT.name,
) -> Dict[str, JSONValue]:
    """Projects配下を走査してカタログJSON用データを組み立てる。"""
    projects: List[Dict[str, JSONValue]] = []

    if not projects_dir.exists():
        print(f"警告: Projectsディレクトリが存在しません: {projects_dir}")
        return _catalog_payload(projects)

    try:
        entries = sorted(projects_dir.iterdir(), key=lambda path: path.name.lower())
    except OSError as exc:
        print(f"警告: Projectsディレクトリの走査に失敗しました: {exc}")
        return _catalog_payload(projects)

    for entry in entries:
        if not _is_project_candidate(entry, self_name):
            continue

        try:
            projects.append({
                "name": entry.name,
                "stack": extract_stack(entry),
                "intent": extract_intent(entry),
                "last_active": extract_last_active(entry),
            })
        except Exception as exc:
            print(f"警告: {entry} の抽出に失敗しました: {exc}")

    projects.sort(
        key=lambda project: cast(str, project.get("last_active", "")) or "0000-00-00",
        reverse=True,
    )
    return _catalog_payload(projects)


def save_catalog(catalog: Mapping[str, JSONValue], output_path: Path) -> None:
    """カタログJSONを指定パスへ保存する。"""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(catalog, f, ensure_ascii=False, indent=2)
        f.write("\n")


def main(argv: Optional[Sequence[str]] = None) -> int:
    """CLI引数を解釈してプロジェクトカタログを生成する。"""
    parser = argparse.ArgumentParser(description="Projectsカタログを生成します。")
    parser.add_argument(
        "--projects-dir",
        type=Path,
        default=DEFAULT_PROJECTS_DIR,
        help="走査対象のProjectsディレクトリ",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help="出力先JSONファイル",
    )
    args = parser.parse_args(argv)

    catalog = build_catalog(args.projects_dir)
    try:
        save_catalog(catalog, args.output)
    except OSError as exc:
        print(f"警告: カタログ保存に失敗しました: {exc}")
        return 1

    projects = catalog.get("projects", [])
    count = len(projects) if isinstance(projects, list) else 0
    print(f"生成完了: {count}件のプロジェクト")
    return 0


def _catalog_payload(projects: List[Dict[str, JSONValue]]) -> Dict[str, JSONValue]:
    """生成日時とプロジェクト一覧を持つJSONペイロードを返す。"""
    return {
        "generated_at": datetime.now().replace(microsecond=0).isoformat(),
        "projects": projects,
    }


def _is_project_candidate(path: Path, self_name: str) -> bool:
    """Projects直下の走査対象ディレクトリか判定する。"""
    return (
        path.is_dir()
        and path.name != self_name
        and path.name not in EXCLUDED_PROJECT_NAMES
        and not path.name.startswith(".")
    )


def _extract_package_json_stack(project_dir: Path) -> List[str]:
    """package.json の dependencies キーからスタックを抽出する。"""
    package_path = project_dir / "package.json"
    if not package_path.exists():
        return []

    try:
        with open(package_path, "r", encoding="utf-8") as f:
            data = cast(Mapping[str, object], json.load(f))
    except (json.JSONDecodeError, OSError) as exc:
        print(f"警告: {package_path} の解析に失敗しました: {exc}")
        return []

    dependencies = data.get("dependencies")
    if not isinstance(dependencies, dict):
        return []
    return [str(key) for key in dependencies.keys()][:STACK_LIMIT]


def _extract_pyproject_stack(project_dir: Path) -> List[str]:
    """pyproject.toml から依存パッケージ名を抽出する。"""
    pyproject_path = project_dir / "pyproject.toml"
    if not pyproject_path.exists():
        return []

    try:
        text = pyproject_path.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"警告: {pyproject_path} の読み込みに失敗しました: {exc}")
        return []

    poetry_stack = _parse_poetry_dependencies(text)
    if poetry_stack:
        return poetry_stack[:STACK_LIMIT]

    project_stack = _parse_project_dependencies(text)
    return project_stack[:STACK_LIMIT]


def _extract_requirements_stack(project_dir: Path) -> List[str]:
    """requirements.txt の先頭依存からパッケージ名を抽出する。"""
    requirements_path = project_dir / "requirements.txt"
    if not requirements_path.exists():
        return []

    stack: List[str] = []
    try:
        for line in requirements_path.read_text(encoding="utf-8").splitlines()[:STACK_LIMIT]:
            name = _dependency_name(line)
            if name:
                stack.append(name)
    except OSError as exc:
        print(f"警告: {requirements_path} の読み込みに失敗しました: {exc}")
        return []
    return stack


def _extract_cargo_stack(project_dir: Path) -> List[str]:
    """Cargo.toml の [dependencies] セクションからキーを抽出する。"""
    cargo_path = project_dir / "Cargo.toml"
    if not cargo_path.exists():
        return []

    try:
        lines = cargo_path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        print(f"警告: {cargo_path} の読み込みに失敗しました: {exc}")
        return []

    stack: List[str] = []
    in_dependencies = False
    for line in lines:
        stripped = _strip_inline_comment(line).strip()
        if not stripped:
            continue
        if stripped.startswith("[") and stripped.endswith("]"):
            in_dependencies = stripped == "[dependencies]"
            continue
        if in_dependencies and "=" in stripped:
            key = _clean_toml_key(stripped.split("=", 1)[0])
            if key:
                stack.append(key)
            if len(stack) >= STACK_LIMIT:
                break
    return stack


def _extract_go_mod_stack(project_dir: Path) -> List[str]:
    """go.mod の require ブロックからモジュール名を抽出する。"""
    go_mod_path = project_dir / "go.mod"
    if not go_mod_path.exists():
        return []

    try:
        lines = go_mod_path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        print(f"警告: {go_mod_path} の読み込みに失敗しました: {exc}")
        return []

    stack: List[str] = []
    in_require_block = False
    for line in lines:
        stripped = _strip_inline_comment(line).strip()
        if not stripped:
            continue
        if stripped == "require (":
            in_require_block = True
            continue
        if in_require_block and stripped == ")":
            break
        if in_require_block:
            module = stripped.split()[0]
            if module:
                stack.append(module)
        elif stripped.startswith("require "):
            parts = stripped.split()
            if len(parts) >= 2:
                stack.append(parts[1])
        if len(stack) >= STACK_LIMIT:
            break
    return stack


def _parse_poetry_dependencies(text: str) -> List[str]:
    """tool.poetry.dependencies のキーを抽出する。"""
    stack: List[str] = []
    in_section = False
    for line in text.splitlines():
        stripped = _strip_inline_comment(line).strip()
        if not stripped:
            continue
        if stripped.startswith("[") and stripped.endswith("]"):
            in_section = stripped == "[tool.poetry.dependencies]"
            continue
        if in_section and "=" in stripped:
            key = _clean_toml_key(stripped.split("=", 1)[0])
            if key and key != "python":
                stack.append(key)
            if len(stack) >= STACK_LIMIT:
                break
    return stack


def _parse_project_dependencies(text: str) -> List[str]:
    """project.dependencies 配列からパッケージ名を抽出する。"""
    lines = text.splitlines()
    stack: List[str] = []
    in_project = False
    collecting_dependencies = False
    buffer: List[str] = []

    for line in lines:
        stripped = _strip_inline_comment(line).strip()
        if not stripped:
            continue
        if stripped.startswith("[") and stripped.endswith("]"):
            if collecting_dependencies:
                break
            in_project = stripped == "[project]"
            continue
        if not in_project:
            continue
        if collecting_dependencies:
            buffer.append(stripped)
            if "]" in stripped:
                break
            continue
        if stripped.startswith("dependencies") and "=" in stripped:
            value = stripped.split("=", 1)[1].strip()
            buffer.append(value)
            if "]" not in value:
                collecting_dependencies = True
            else:
                break

    for dependency in _extract_quoted_values(" ".join(buffer)):
        name = _dependency_name(dependency)
        if name:
            stack.append(name)
        if len(stack) >= STACK_LIMIT:
            break
    return stack


def _extract_quoted_values(text: str) -> List[str]:
    """文字列内のシングル/ダブルクォート値を抽出する。"""
    return [match.group(2) for match in re.finditer(r"(['\"])(.*?)\1", text)]


def _dependency_name(line: str) -> str:
    """バージョン指定を除いた依存名を返す。"""
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return ""
    without_marker = stripped.split(";", 1)[0].strip()
    without_extra = without_marker.split("[", 1)[0].strip()
    return re.split(r"\s*(?:==|>=|<=|~=|!=|>|<|=|\s)\s*", without_extra, maxsplit=1)[0]


def _read_limited_lines(path: Path, limit: int) -> Iterable[str]:
    """ファイル先頭から指定行数だけ読み込む。"""
    with open(path, "r", encoding="utf-8") as f:
        for index, line in enumerate(f):
            if index >= limit:
                break
            yield line


def _strip_inline_comment(line: str) -> str:
    """TOML/Go風の単純な行末コメントを取り除く。"""
    return line.split("#", 1)[0].split("//", 1)[0]


def _clean_toml_key(key: str) -> str:
    """TOMLキー表記から引用符と空白を取り除く。"""
    return key.strip().strip("'\"")


if __name__ == "__main__":
    raise SystemExit(main())
