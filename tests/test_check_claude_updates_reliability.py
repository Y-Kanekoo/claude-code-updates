from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

_spec = importlib.util.spec_from_file_location(
    "check_claude_updates_reliability",
    Path(__file__).parent.parent / "scripts" / "check-claude-updates.py",
)
assert _spec is not None and _spec.loader is not None
check_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_module)

ReleaseChecker = check_module.ReleaseChecker
GroqAuthenticationError = check_module.GroqAuthenticationError


class StatusError(Exception):
    def __init__(
        self,
        status_code: int,
        headers: dict[str, str] | None = None,
        message: str | None = None,
    ):
        super().__init__(message or f"HTTP {status_code}")
        self.status_code = status_code
        self.response = SimpleNamespace(
            status_code=status_code,
            headers=headers or {},
        )


class FakeResponse:
    def __init__(self, payload: object):
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> object:
        return self.payload


def build_checker(max_releases_per_run: int = 10) -> ReleaseChecker:
    checker = ReleaseChecker.__new__(ReleaseChecker)
    checker.max_releases_per_run = max_releases_per_run
    return checker


def test_max_releases_per_run_defaults_to_ten(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MAX_RELEASES_PER_RUN", raising=False)

    assert ReleaseChecker._read_max_releases_per_run() == 10


def test_max_releases_per_run_accepts_positive_integer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MAX_RELEASES_PER_RUN", "3")

    assert ReleaseChecker._read_max_releases_per_run() == 3


@pytest.mark.parametrize("value", ["0", "-1", "invalid", "1.5", ""])
def test_max_releases_per_run_rejects_non_positive_integer(
    monkeypatch: pytest.MonkeyPatch,
    value: str,
) -> None:
    monkeypatch.setenv("MAX_RELEASES_PER_RUN", value)

    with pytest.raises(ValueError, match="正の整数"):
        ReleaseChecker._read_max_releases_per_run()


def test_fetch_releases_paginates_until_last_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checker = build_checker()
    checker.github_token = None
    pages = {
        1: [{"tag_name": f"v{version}"} for version in range(250, 150, -1)],
        2: [{"tag_name": f"v{version}"} for version in range(150, 50, -1)],
    }
    requested_pages: list[tuple[int, int]] = []

    def fake_get(_url: str, **kwargs: object) -> FakeResponse:
        params = kwargs["params"]
        assert isinstance(params, dict)
        per_page = params["per_page"]
        page = params["page"]
        assert isinstance(per_page, int)
        assert isinstance(page, int)
        requested_pages.append((per_page, page))
        return FakeResponse(pages[page])

    monkeypatch.setattr(check_module.requests, "get", fake_get)

    releases = checker.fetch_releases("v75")
    new_releases = checker.filter_new_releases(releases, "v75")
    selected_releases = checker.select_releases_for_run(new_releases)

    assert requested_pages == [(100, 1), (100, 2)]
    assert len(releases) == 200
    assert selected_releases[0]["tag_name"] == "v76"


def test_fetch_releases_initial_run_only_fetches_first_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checker = build_checker()
    checker.github_token = None
    requested_pages: list[int] = []

    def fake_get(_url: str, **kwargs: object) -> FakeResponse:
        params = kwargs["params"]
        assert isinstance(params, dict)
        page = params["page"]
        assert isinstance(page, int)
        requested_pages.append(page)
        return FakeResponse([{"tag_name": "v2"}, {"tag_name": "v1"}])

    monkeypatch.setattr(check_module.requests, "get", fake_get)

    releases = checker.fetch_releases(None)

    assert requested_pages == [1]
    assert [release["tag_name"] for release in releases] == ["v2", "v1"]


def test_fetch_releases_rejects_non_list_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checker = build_checker()
    checker.github_token = None
    monkeypatch.setattr(
        check_module.requests,
        "get",
        lambda *_args, **_kwargs: FakeResponse({"message": "unexpected"}),
    )

    with pytest.raises(ValueError, match="レスポンスが配列ではありません"):
        checker.fetch_releases("v1")


@pytest.mark.parametrize(
    "last_page",
    [
        [{"tag_name": "v150"}],
        [],
    ],
    ids=["short-page", "empty-page"],
)
def test_fetch_releases_fails_when_last_version_is_not_in_all_pages(
    monkeypatch: pytest.MonkeyPatch,
    last_page: list[dict[str, str]],
) -> None:
    checker = build_checker()
    checker.github_token = None
    full_page = [
        {"tag_name": f"v{version}"}
        for version in range(250, 150, -1)
    ]
    pages = {1: full_page, 2: last_page}
    requested_pages: list[int] = []

    def fake_get(_url: str, **kwargs: object) -> FakeResponse:
        params = kwargs["params"]
        assert isinstance(params, dict)
        page = params["page"]
        assert isinstance(page, int)
        requested_pages.append(page)
        return FakeResponse(pages[page])

    monkeypatch.setattr(check_module.requests, "get", fake_get)

    with pytest.raises(RuntimeError, match="重複処理を防ぐため処理を停止"):
        checker.fetch_releases("missing-version")

    assert requested_pages == [1, 2]


def test_fetch_releases_stops_safely_at_page_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checker = build_checker()
    checker.github_token = None
    requested_pages: list[int] = []

    def fake_get(_url: str, **kwargs: object) -> FakeResponse:
        params = kwargs["params"]
        assert isinstance(params, dict)
        page = params["page"]
        assert isinstance(page, int)
        requested_pages.append(page)
        return FakeResponse(
            [
                {"tag_name": f"v{page}-{index}"}
                for index in range(check_module.GITHUB_RELEASES_PER_PAGE)
            ]
        )

    monkeypatch.setattr(check_module.requests, "get", fake_get)

    with pytest.raises(RuntimeError, match="取りこぼしを防ぐため処理を停止"):
        checker.fetch_releases("missing-version")

    assert requested_pages == list(
        range(1, check_module.GITHUB_RELEASES_MAX_PAGES + 1)
    )


def test_release_limit_processes_oldest_first_and_carries_over() -> None:
    checker = build_checker(max_releases_per_run=2)
    releases = [{"tag_name": f"v{version}"} for version in range(5, 0, -1)]

    first_new_releases = checker.filter_new_releases(releases, "v0")
    first_batch = checker.select_releases_for_run(first_new_releases)
    second_new_releases = checker.filter_new_releases(releases, "v2")
    second_batch = checker.select_releases_for_run(second_new_releases)

    assert [release["tag_name"] for release in first_batch] == ["v1", "v2"]
    assert [release["tag_name"] for release in second_batch] == ["v3", "v4"]


def test_run_validates_auth_and_saves_checkpoint_after_each_release() -> None:
    checker = build_checker(max_releases_per_run=2)
    releases = [
        {"tag_name": f"v{version}", "body": "notes"}
        for version in range(3, 0, -1)
    ]
    events: list[str] = []
    saved: list[tuple[str, str]] = []

    checker.get_last_checked_version = lambda: "v0"
    fetched_with: list[str | None] = []
    checker.fetch_releases = (
        lambda last_version: fetched_with.append(last_version) or releases
    )
    checker.validate_groq_authentication = lambda: events.append("validate")
    checker.summarize_release_notes = (
        lambda _notes, version: events.append(f"summarize:{version}") or "summary"
    )
    checker.create_report = lambda release, _summary, _previous: "2026-08-13"
    checker.send_discord_notification = lambda _release, _summary: None
    checker.save_last_checked_version = (
        lambda version, release_date: saved.append((version, release_date))
    )

    checker.run()

    assert events == ["validate", "summarize:v1", "summarize:v2"]
    assert fetched_with == ["v0"]
    assert saved == [("v1", "2026-08-13"), ("v2", "2026-08-13")]


def test_run_preserves_partial_checkpoint_when_later_release_fails() -> None:
    checker = build_checker(max_releases_per_run=3)
    releases = [
        {"tag_name": f"v{version}", "body": "notes"}
        for version in range(3, 0, -1)
    ]
    saved: list[tuple[str, str]] = []

    checker.get_last_checked_version = lambda: "v0"
    checker.fetch_releases = lambda _last_version: releases
    checker.validate_groq_authentication = lambda: None

    def summarize(_notes: str, version: str) -> str:
        if version == "v2":
            raise RuntimeError("要約に失敗")
        return "summary"

    checker.summarize_release_notes = summarize
    checker.create_report = lambda _release, _summary, _previous: "2026-08-13"
    checker.send_discord_notification = lambda _release, _summary: None
    checker.save_last_checked_version = (
        lambda version, release_date: saved.append((version, release_date))
    )

    with pytest.raises(SystemExit) as exit_info:
        checker.run()

    assert exit_info.value.code == 1
    assert saved == [("v1", "2026-08-13")]


@pytest.mark.parametrize("status_code", [429, 500, 503])
def test_groq_retries_only_retryable_http_errors(
    monkeypatch: pytest.MonkeyPatch,
    status_code: int,
) -> None:
    checker = build_checker()
    attempts = 0
    delays: list[float] = []

    def operation() -> str:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise StatusError(status_code)
        return "success"

    monkeypatch.setattr(check_module.time, "sleep", delays.append)

    assert checker._call_groq_api(operation, "テスト") == "success"
    assert attempts == 3
    assert delays == [1.0, 2.0]


@pytest.mark.parametrize(
    ("headers", "expected_delay"),
    [
        ({"retry-after-ms": "6130"}, 6.63),
        ({"retry-after": "6.13"}, 6.63),
        ({"x-ratelimit-reset-tokens": "6.13s"}, 6.63),
        ({"x-ratelimit-reset-tokens": "1m2.5s"}, 60.0),
    ],
    ids=["retry-after-ms", "retry-after", "token-reset", "compound-token-reset"],
)
def test_groq_429_uses_server_retry_headers(
    monkeypatch: pytest.MonkeyPatch,
    headers: dict[str, str],
    expected_delay: float,
) -> None:
    checker = build_checker()
    attempts = 0
    delays: list[float] = []

    def operation() -> str:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise StatusError(429, headers=headers)
        return "success"

    monkeypatch.setattr(check_module.time, "sleep", delays.append)

    assert checker._call_groq_api(operation, "テスト") == "success"
    assert delays == [expected_delay]


def test_groq_429_uses_message_retry_delay_as_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checker = build_checker()
    attempts = 0
    delays: list[float] = []

    def operation() -> str:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise StatusError(
                429,
                message="Rate limit reached. Please try again in 6.13s.",
            )
        return "success"

    monkeypatch.setattr(check_module.time, "sleep", delays.append)

    assert checker._call_groq_api(operation, "テスト") == "success"
    assert delays == [6.63]


def test_groq_429_caps_excessive_server_retry_delay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checker = build_checker()
    attempts = 0
    delays: list[float] = []

    def operation() -> str:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise StatusError(429, headers={"retry-after": "3600"})
        return "success"

    monkeypatch.setattr(check_module.time, "sleep", delays.append)

    assert checker._call_groq_api(operation, "テスト") == "success"
    assert delays == [check_module.GROQ_MAX_RETRY_DELAY_SECONDS]


@pytest.mark.parametrize(
    "headers",
    [
        {"retry-after-ms": "invalid"},
        {"retry-after": "NaN"},
        {"x-ratelimit-reset-tokens": "soon"},
        {"retry-after": "-1"},
    ],
    ids=["invalid-ms", "not-finite", "invalid-duration", "negative"],
)
def test_groq_429_ignores_invalid_retry_headers(
    monkeypatch: pytest.MonkeyPatch,
    headers: dict[str, str],
) -> None:
    checker = build_checker()
    attempts = 0
    delays: list[float] = []

    def operation() -> str:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise StatusError(429, headers=headers)
        return "success"

    monkeypatch.setattr(check_module.time, "sleep", delays.append)

    assert checker._call_groq_api(operation, "テスト") == "success"
    assert delays == [check_module.GROQ_RETRY_BASE_DELAY_SECONDS]


def test_groq_retries_connection_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    checker = build_checker()
    attempts = 0
    delays: list[float] = []

    class FakeConnectionError(Exception):
        pass

    monkeypatch.setattr(
        check_module,
        "groq_sdk",
        SimpleNamespace(APIConnectionError=FakeConnectionError),
    )
    monkeypatch.setattr(check_module.time, "sleep", delays.append)

    def operation() -> str:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise FakeConnectionError("connection failed")
        return "success"

    assert checker._call_groq_api(operation, "テスト") == "success"
    assert attempts == 2
    assert delays == [1.0]


@pytest.mark.parametrize("status_code", [401, 403])
def test_groq_authentication_errors_are_clear_and_not_retried(
    monkeypatch: pytest.MonkeyPatch,
    status_code: int,
) -> None:
    checker = build_checker()
    attempts = 0
    sleep_calls: list[float] = []

    def operation() -> None:
        nonlocal attempts
        attempts += 1
        raise StatusError(status_code)

    monkeypatch.setattr(check_module.time, "sleep", sleep_calls.append)

    with pytest.raises(
        GroqAuthenticationError,
        match=rf"認証に失敗しました（HTTP {status_code}）.*GROQ_API_KEY",
    ):
        checker._call_groq_api(operation, "認証確認")

    assert attempts == 1
    assert sleep_calls == []


def test_groq_does_not_retry_other_client_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checker = build_checker()
    attempts = 0
    sleep_calls: list[float] = []

    def operation() -> None:
        nonlocal attempts
        attempts += 1
        raise StatusError(400)

    monkeypatch.setattr(check_module.time, "sleep", sleep_calls.append)

    with pytest.raises(StatusError):
        checker._call_groq_api(operation, "テスト")

    assert attempts == 1
    assert sleep_calls == []


def test_validate_groq_authentication_uses_models_endpoint() -> None:
    checker = build_checker()
    calls: list[str] = []
    checker.client = SimpleNamespace(
        models=SimpleNamespace(list=lambda: calls.append("models.list"))
    )

    checker.validate_groq_authentication()

    assert calls == ["models.list"]
