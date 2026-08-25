from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT_DIR / "scripts"))

UPDATES_SPEC = importlib.util.spec_from_file_location(
    "check_updates_rate_limit_discord",
    ROOT_DIR / "scripts" / "check-claude-updates.py",
)
assert UPDATES_SPEC is not None and UPDATES_SPEC.loader is not None
updates = importlib.util.module_from_spec(UPDATES_SPEC)
UPDATES_SPEC.loader.exec_module(updates)


class RateLimitError(Exception):
    status_code = 429
    response = SimpleNamespace(status_code=429, headers={"retry-after": "0"})


def build_checker() -> object:
    checker = object.__new__(updates.ReleaseChecker)
    checker.max_releases_per_run = 10
    return checker


def test_final_429_is_normalized_to_groq_rate_limit_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checker = build_checker()
    attempts = 0

    def operation() -> str:
        nonlocal attempts
        attempts += 1
        raise RateLimitError("HTTP 429")

    monkeypatch.setattr(updates.time, "sleep", lambda _delay: None)

    with pytest.raises(updates.GroqRateLimitError, match="再試行後も継続"):
        checker._call_groq_api(operation, "テスト")

    assert attempts == updates.GROQ_MAX_ATTEMPTS


def test_run_records_groq_rate_limit_failure_type(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    checker = build_checker()
    output_path = tmp_path / "github-output.txt"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output_path))
    checker.get_last_checked_version = lambda: "v2.1.245"
    checker.validate_groq_authentication = lambda: (_ for _ in ()).throw(
        updates.GroqRateLimitError("利用上限")
    )

    with pytest.raises(SystemExit) as exit_info:
        checker.run()

    assert exit_info.value.code == 1
    assert output_path.read_text(encoding="utf-8") == (
        "failure_type=groq_rate_limit\n"
    )


def test_workflow_has_specific_groq_limit_message_and_recovery_links() -> None:
    workflow = (ROOT_DIR / ".github" / "workflows" / "claude-updates.yml").read_text(
        encoding="utf-8"
    )

    assert "FAILURE_TYPE: ${{ steps.generate_report.outputs.failure_type }}" in workflow
    assert "Groq APIの利用上限に到達しました" in workflow
    assert "途中進捗は保持され、次回実行で続きから再開します" in workflow
    assert "https://console.groq.com/settings/limits" in workflow
    assert "https://console.groq.com/settings/billing/manage" in workflow
    assert "Actionsログを確認" in workflow
