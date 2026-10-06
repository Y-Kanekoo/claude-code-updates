"""Exercise publication bookkeeping with local Git only and stubbed delivery."""

import json
import os
from pathlib import Path
import re
import subprocess

import pytest

from scripts import notification_delivery as delivery

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/claude-updates.yml"


def step_script(name):
    block = WORKFLOW.read_text().split(f"      - name: {name}\n", 1)[1]
    block = block.split("\n      - name:", 1)[0]
    return "\n".join(line[10:] for line in block.split("        run: |\n", 1)[1].splitlines())


def git(root, *args):
    return subprocess.check_output(["git", *args], cwd=root, text=True).strip()


@pytest.mark.parametrize("kind", ["cache", "report", "none", "push_failure"])
def test_publication_commit_and_alert_contract(tmp_path, monkeypatch, kind):
    remote = tmp_path / "remote.git"
    git(tmp_path, "init", "--bare", str(remote))
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-b", "main")
    git(root, "config", "user.name", "Test")
    git(root, "config", "user.email", "test@example.invalid")
    reports = root / "reports/claude-code"
    reports.mkdir(parents=True)
    old = reports / "2026-10-05-v2.1.289.md"
    old.write_text("Existing finished report\n")
    (reports / "last-checked.json").write_text(json.dumps({"last_version": "v2.1.289"}))
    git(root, "add", ".")
    git(root, "commit", "-m", "baseline")
    git(root, "remote", "add", "origin", str(remote))
    git(root, "push", "-u", "origin", "main")
    before = git(root, "rev-parse", "HEAD")
    if kind in ("cache", "push_failure"):
        cache = reports / "summary-cache"
        cache.mkdir()
        for number in range(17):
            (cache / f"batch-{number}.json").write_text('{"saved": true}')
    elif kind == "report":
        (reports / "2026-10-06-v2.1.290.md").write_text("Completed new report\n")
        (reports / "last-checked.json").write_text(json.dumps({"last_version": "v2.1.290"}))
    if kind == "push_failure":
        hook = remote / "hooks/pre-receive"
        hook.write_text("#!/bin/sh\nexit 1\n")
        hook.chmod(0o755)
    output = tmp_path / "output"
    output.touch()
    env = {**os.environ, "GITHUB_OUTPUT": str(output)}
    subprocess.run(["bash", "-e", "-c", step_script("変更を確認")], cwd=root, env=env, check=True)
    check = dict(line.split("=", 1) for line in output.read_text().splitlines())
    assert check["has_changes"] == str(kind != "none").lower()
    output.write_text("")
    script = step_script("変更をコミット＆プッシュ").replace(
        "${{ steps.check_changes.outputs.version }}", check.get("version", "latest")
    )
    result = subprocess.run(["bash", "-e", "-c", script], cwd=root, env=env, capture_output=True)
    assert (result.returncode == 0) == (kind != "push_failure")
    status = dict(line.split("=", 1) for line in output.read_text().splitlines())
    assert status.get("reports_published", "false") == str(kind == "report").lower()
    assert status.get("checkpoints_saved", "false") == str(kind == "cache").lower()
    assert status.get("pushed", "false") == str(kind in ("cache", "report")).lower()
    if kind == "none":
        assert git(root, "rev-parse", "HEAD") == before
    elif kind == "cache":
        message = git(root, "log", "-1", "--format=%s")
        assert "チェックポイント" in message
        assert "レポートを追加" not in message
        assert "v2.1.289" not in message
        assert len(git(remote, "ls-tree", "-r", "--name-only", "main", "reports/claude-code/summary-cache").splitlines()) == 17
    elif kind == "report":
        assert "v2.1.290 の更新レポートを追加" in git(root, "log", "-1", "--format=%s")
    else:
        assert git(remote, "rev-parse", "main") == before
    assert old.read_text() == "Existing finished report\n"

    # Availability preserves retry of previously published pending notifications.
    monkeypatch.setattr(delivery, "REPORTS_DIR", reports)
    available = kind != "push_failure"
    store = delivery.NotificationStore(reports / delivery.STATE_NAME)
    store.enqueue("v2.1.289", {"content": "Previously published report"})
    calls = []
    monkeypatch.setattr(delivery, "post_webhook", lambda url, payload: calls.append(payload) or "1")
    for key, value in {
        "DISCORD_WEBHOOK_URL": "https://example.invalid/stub",
        "REPORTS_AVAILABLE": str(available).lower(),
        "REPORTS_PUBLISHED": status.get("reports_published", "false"),
        "CHECKPOINTS_SAVED": status.get("checkpoints_saved", "false"),
        "RUN_FAILED": "true" if kind != "none" else "false",
        "FAILURE_TYPE": "groq_rate_limit" if kind != "none" else "",
        "FAILED_VERSION": "v2.1.290",
        "RUN_DEFERRED": "false",
    }.items():
        monkeypatch.setenv(key, value)
    assert delivery.main() == 0
    if available:
        assert calls[0]["content"] == "Previously published report"
    if kind == "cache":
        assert "チェックポイントを保存" in calls[-1]["content"]
        assert "新しいレポートは公開していません" in calls[-1]["content"]
        assert "公開済みの途中進捗" not in calls[-1]["content"]
    elif kind == "report":
        assert "完成したレポートを公開" in calls[-1]["content"]
    elif kind == "none":
        assert len(calls) == 1
    else:
        assert "公開は未確認" in calls[-1]["content"]
        assert "チェックポイントを保存" not in calls[-1]["content"]


def test_workflow_distinguishes_delivery_readiness_from_new_publication():
    text = WORKFLOW.read_text()
    assert "REPORTS_AVAILABLE:" in text
    assert "steps.commit_reports.outputs.pushed == 'true'" in text
    assert "steps.check_changes.outputs.has_changes == 'false'" in text
    assert re.search(r"REPORTS_PUBLISHED:.*outputs.reports_published", text)
    assert re.search(r"CHECKPOINTS_SAVED:.*outputs.checkpoints_saved", text)
