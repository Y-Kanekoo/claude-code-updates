from __future__ import annotations

import importlib.util
from datetime import date
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).parent.parent / "scripts" / "check-groq-key-expiry.py"
SPEC = importlib.util.spec_from_file_location("check_groq_key_expiry", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
check_expiry = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(check_expiry)


def test_parse_expiry_date() -> None:
    assert check_expiry.parse_expiry_date("2026-11-11") == date(2026, 11, 11)


def test_parse_expiry_date_rejects_invalid_format() -> None:
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        check_expiry.parse_expiry_date("2026/11/11")


@pytest.mark.parametrize("days_remaining", [14, 7, 1, 0, -1, -30])
def test_should_notify_on_milestone_or_after_expiry(days_remaining: int) -> None:
    assert check_expiry.should_notify(days_remaining)


@pytest.mark.parametrize("days_remaining", [15, 13, 8, 6, 2])
def test_should_not_notify_outside_milestones(days_remaining: int) -> None:
    assert not check_expiry.should_notify(days_remaining)


def test_build_message_contains_expiry_and_actions_url() -> None:
    message = check_expiry.build_message(
        date(2026, 11, 11),
        7,
        "https://github.example/actions/runs/123",
    )

    assert "2026-11-11" in message
    assert "あと7日" in message
    assert "CLAUDE_UPDATES_GROQ_API_KEY_EXPIRES_AT" in message
    assert "https://github.example/actions/runs/123" in message


def test_main_skips_when_expiry_variable_is_missing(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv(check_expiry.EXPIRY_ENV_NAME, raising=False)

    assert check_expiry.main() == 0
    assert "未設定" in capsys.readouterr().out


def test_main_continues_when_discord_notification_fails(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv(check_expiry.EXPIRY_ENV_NAME, "2026-11-11")
    monkeypatch.setenv(check_expiry.WEBHOOK_ENV_NAME, "https://discord.example/webhook")
    monkeypatch.setattr(check_expiry, "should_notify", lambda _days: True)

    def raise_notification_error(_webhook_url: str, _message: str) -> None:
        raise RuntimeError("Discord 通知に失敗しました")

    monkeypatch.setattr(
        check_expiry,
        "send_discord_notification",
        raise_notification_error,
    )

    assert check_expiry.main() == 0
    captured = capsys.readouterr()
    assert "更新チェックは続行します" in captured.err
