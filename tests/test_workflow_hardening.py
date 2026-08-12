from __future__ import annotations

import json
import re
from pathlib import Path

ROOT_DIR = Path(__file__).parent.parent
WORKFLOWS_DIR = ROOT_DIR / ".github" / "workflows"
REPORT_WORKFLOW = WORKFLOWS_DIR / "claude-updates.yml"
SLIDES_WORKFLOW = WORKFLOWS_DIR / "slides.yml"


def read(path: Path) -> str:
    """検査対象ファイルをUTF-8で読み込む。"""
    return path.read_text(encoding="utf-8")


def test_all_remote_actions_are_pinned_to_full_commit_sha() -> None:
    """第三者Actionを可変タグへ戻さない。"""
    remote_use = re.compile(r"^\s*uses:\s*([^./\s][^@\s]*)@([^\s#]+)", re.MULTILINE)

    references = [
        match.groups()
        for workflow in WORKFLOWS_DIR.glob("*.yml")
        for match in remote_use.finditer(read(workflow))
    ]

    assert references
    assert all(re.fullmatch(r"[0-9a-f]{40}", revision) for _, revision in references)


def test_report_workflow_refreshes_and_scopes_git_changes() -> None:
    """待機runの古いcheckoutと、無関係ファイルのcommitを防ぐ。"""
    workflow = read(REPORT_WORKFLOW)

    assert "ref: ${{ github.ref_name }}" in workflow
    assert "git status --porcelain -- reports/claude-code" in workflow
    assert "git add --all -- reports/claude-code" in workflow
    assert "git diff --cached --quiet -- reports/claude-code" in workflow
    assert "git add ." not in workflow


def test_report_version_comes_from_checkpoint_without_mtime() -> None:
    """commit対象versionをmtimeではなく完了checkpointから取得する。"""
    workflow = read(REPORT_WORKFLOW)

    assert 'Path("reports/claude-code/last-checked.json")' in workflow
    assert '.get("last_version", "latest")' in workflow
    assert " -nt " not in workflow


def test_slides_use_locked_marp_and_skip_noop_runs() -> None:
    """Marpをlockから導入し、更新artifactがない日次runは公開しない。"""
    report_workflow = read(REPORT_WORKFLOW)
    slides_workflow = read(SLIDES_WORKFLOW)

    assert "name: slides-trigger" in report_workflow
    assert 'select(.name == "slides-trigger"' in slides_workflow
    assert "should_publish == 'true'" in slides_workflow
    assert "run: npm ci" in slides_workflow
    assert "npm install -g" not in slides_workflow


def test_python_locks_require_hashes() -> None:
    """実行用・開発用lockの各パッケージにhashを必須化する。"""
    for lock_name in ("requirements.txt", "requirements-dev.txt"):
        lock = read(ROOT_DIR / lock_name)
        package_lines = [
            index
            for index, line in enumerate(lock.splitlines())
            if line and not line.startswith(("#", " ")) and "==" in line
        ]
        lines = lock.splitlines()
        assert package_lines
        for index in package_lines:
            following = "\n".join(lines[index : index + 4])
            assert "--hash=sha256:" in following, lines[index]


def test_node_lock_pins_marp_cli() -> None:
    """package-lockがMarp CLIの指定版を固定する。"""
    package = json.loads(read(ROOT_DIR / "package.json"))
    lock = json.loads(read(ROOT_DIR / "package-lock.json"))

    expected = package["devDependencies"]["@marp-team/marp-cli"]
    assert lock["packages"]["node_modules/@marp-team/marp-cli"]["version"] == expected
