from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import ClassVar

import pytest
import requests

ROOT_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT_DIR / "scripts"))

UPDATES_SPEC = importlib.util.spec_from_file_location(
    "check_updates_api_hardening",
    ROOT_DIR / "scripts" / "check-claude-updates.py",
)
assert UPDATES_SPEC is not None and UPDATES_SPEC.loader is not None
updates = importlib.util.module_from_spec(UPDATES_SPEC)
UPDATES_SPEC.loader.exec_module(updates)

EXPIRY_SPEC = importlib.util.spec_from_file_location(
    "check_expiry_api_hardening",
    ROOT_DIR / "scripts" / "check-groq-key-expiry.py",
)
assert EXPIRY_SPEC is not None and EXPIRY_SPEC.loader is not None
expiry = importlib.util.module_from_spec(EXPIRY_SPEC)
EXPIRY_SPEC.loader.exec_module(expiry)


def build_checker() -> object:
    checker = object.__new__(updates.ReleaseChecker)
    checker.max_releases_per_run = 10
    return checker


def test_max_releases_per_run_rejects_value_above_ten(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MAX_RELEASES_PER_RUN", "11")

    with pytest.raises(ValueError, match="上限 10"):
        updates.ReleaseChecker._read_max_releases_per_run()


@pytest.mark.parametrize("value", ["20261111", "2026-W45-3"])
def test_expiry_date_rejects_non_calendar_iso_formats(value: str) -> None:
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        expiry.parse_expiry_date(value)


def test_expiry_webhook_rejects_malformed_url_without_leaking_it() -> None:
    secret_url = "discord.example/api/webhooks/secret-token"

    with pytest.raises(RuntimeError) as error_info:
        expiry.send_discord_notification(secret_url, "test")

    assert secret_url not in str(error_info.value)


def test_checkpoint_corruption_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    checkpoint = tmp_path / "last-checked.json"
    checkpoint.write_text("{broken", encoding="utf-8")
    monkeypatch.setattr(updates, "REPORTS_DIR", tmp_path)
    monkeypatch.setattr(updates, "LAST_CHECKED_FILE", checkpoint)
    checker = build_checker()

    with pytest.raises(RuntimeError, match="チェックポイントを復旧"):
        checker.get_last_checked_version()


def test_checkpoint_missing_metadata_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    checkpoint = tmp_path / "last-checked.json"
    checkpoint.write_text('{"last_version":"v2.1.228"}', encoding="utf-8")
    monkeypatch.setattr(updates, "REPORTS_DIR", tmp_path)
    monkeypatch.setattr(updates, "LAST_CHECKED_FILE", checkpoint)
    checker = build_checker()

    with pytest.raises(RuntimeError, match="チェックポイントを復旧"):
        checker.get_last_checked_version()


def test_missing_checkpoint_with_reports_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    (tmp_path / "2026-08-13-v2.1.229.md").write_text("report", encoding="utf-8")
    monkeypatch.setattr(updates, "REPORTS_DIR", tmp_path)
    monkeypatch.setattr(updates, "LAST_CHECKED_FILE", tmp_path / "last-checked.json")
    checker = build_checker()

    with pytest.raises(RuntimeError, match="既存レポート"):
        checker.get_last_checked_version()


def test_checkpoint_save_uses_atomic_replace(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    checkpoint = tmp_path / "last-checked.json"
    monkeypatch.setattr(updates, "LAST_CHECKED_FILE", checkpoint)
    replace_calls: list[tuple[Path, Path]] = []
    original_replace = updates.os.replace

    def record_replace(source: Path, destination: Path) -> None:
        replace_calls.append((Path(source), Path(destination)))
        original_replace(source, destination)

    monkeypatch.setattr(updates.os, "replace", record_replace)
    checker = build_checker()

    checker.save_last_checked_version("v2.1.229", "2026-08-13")

    assert replace_calls and replace_calls[0][1] == checkpoint
    assert json.loads(checkpoint.read_text(encoding="utf-8"))["last_version"] == "v2.1.229"
    assert list(tmp_path.glob("*.tmp")) == []


@pytest.mark.parametrize(
    "release",
    [
        {"tag_name": "latest", "published_at": "2026-08-13T00:00:00Z", "body": "x"},
        {"tag_name": "v2.1.229", "published_at": "invalid", "body": "x"},
        {"tag_name": "v2.1.229", "published_at": "2026-08-13T00:00:00Z", "body": 1},
    ],
)
def test_release_validation_rejects_invalid_api_fields(
    release: dict[str, object],
) -> None:
    with pytest.raises(ValueError):
        updates.ReleaseChecker._validate_release(release)


def test_github_api_uses_version_headers_and_retries_server_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checker = build_checker()
    calls: list[dict[str, object]] = []
    delays: list[float] = []

    class Response:
        def __init__(self, status_code: int):
            self.status_code = status_code
            self.headers: dict[str, str] = {}

        def raise_for_status(self) -> None:
            if self.status_code >= 400:
                raise requests.HTTPError("server error", response=self)

        def json(self) -> list[object]:
            return []

    responses = iter([Response(503), Response(200)])

    def fake_get(_url: str, **kwargs: object) -> Response:
        calls.append(kwargs)
        return next(responses)

    monkeypatch.setattr(updates.requests, "get", fake_get)
    monkeypatch.setattr(updates.time, "sleep", delays.append)

    response = checker._get_github_releases_page({}, 1)

    assert response.status_code == 200
    assert delays == [1.0]

    checker.github_token = None
    monkeypatch.setattr(
        updates.requests,
        "get",
        lambda _url, **kwargs: calls.append(kwargs) or Response(200),
    )
    checker.fetch_releases(None)
    headers = calls[-1]["headers"]
    assert isinstance(headers, dict)
    assert headers["X-GitHub-Api-Version"] == updates.GITHUB_API_VERSION
    assert headers["User-Agent"] == updates.GITHUB_USER_AGENT


def test_groq_models_response_with_invalid_data_fails_closed() -> None:
    checker = build_checker()
    checker.client = SimpleNamespace(
        models=SimpleNamespace(list=lambda: SimpleNamespace(data=None))
    )
    checker._call_groq_api = lambda operation, _name: operation()

    with pytest.raises(updates.GroqModelUnavailableError, match="空または不正"):
        checker.validate_groq_authentication()


def test_groq_long_daily_reset_fails_fast(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checker = build_checker()
    sleep_calls: list[float] = []

    class RateLimitError(Exception):
        status_code = 429
        response = SimpleNamespace(
            status_code=429,
            headers={"x-ratelimit-reset-requests": "2m"},
        )

    monkeypatch.setattr(updates.time, "sleep", sleep_calls.append)

    with pytest.raises(updates.GroqRateLimitError, match="60秒を超える"):
        checker._call_groq_api(lambda: (_ for _ in ()).throw(RateLimitError()), "test")

    assert sleep_calls == []


def test_discord_release_notification_retries_without_logging_url(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    checker = build_checker()
    secret_url = "https://discord.example/api/webhooks/secret-token"
    attempts = 0
    delays: list[float] = []

    class Response:
        status_code = 429
        headers: ClassVar[dict[str, str]] = {"retry-after": "2"}

        def raise_for_status(self) -> None:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise requests.HTTPError("rate limit", response=self)

    monkeypatch.setattr(updates.requests, "post", lambda *_args, **_kwargs: Response())
    monkeypatch.setattr(updates.time, "sleep", delays.append)

    checker._post_discord_payload(secret_url, {"content": "test"})

    assert attempts == 2
    assert delays == [2.0]
    assert secret_url not in capsys.readouterr().out


def test_authentication_failure_aborts_before_release_processing() -> None:
    checker = build_checker()
    calls: list[str] = []
    checker.get_last_checked_version = lambda: "v2.1.228"
    checker.validate_groq_authentication = lambda: (_ for _ in ()).throw(
        updates.GroqAuthenticationError("認証失敗")
    )
    checker.fetch_releases = lambda _version: calls.append("fetch") or []
    checker.summarize_release_notes = lambda *_args: calls.append("summarize") or ""
    checker.create_report = lambda *_args: calls.append("create") or ""

    with pytest.raises(SystemExit) as exit_info:
        checker.run()

    assert exit_info.value.code == 1
    assert calls == []


def test_checkpoint_is_saved_before_best_effort_notification() -> None:
    checker = build_checker()
    events: list[str] = []
    release = {"tag_name": "v2.1.229", "body": "notes"}
    checker.get_last_checked_version = lambda: "v2.1.228"
    checker.validate_groq_authentication = lambda: None
    checker.fetch_releases = lambda _version: [release]
    checker.summarize_release_notes = lambda *_args: "summary"
    checker.create_report = lambda *_args: events.append("report") or "2026-08-13"
    checker.save_last_checked_version = lambda *_args: events.append("checkpoint")
    checker.send_discord_notification = lambda *_args: events.append("notification")

    checker.run()

    assert events == ["report", "checkpoint", "notification"]
