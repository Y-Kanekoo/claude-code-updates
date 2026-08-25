from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT_DIR / "scripts"))

UPDATES_SPEC = importlib.util.spec_from_file_location(
    "check_updates_rate_limit_headers",
    ROOT_DIR / "scripts" / "check-claude-updates.py",
)
assert UPDATES_SPEC is not None and UPDATES_SPEC.loader is not None
updates = importlib.util.module_from_spec(UPDATES_SPEC)
UPDATES_SPEC.loader.exec_module(updates)


class RateLimitError(Exception):
    status_code = 429

    def __init__(self, headers: dict[str, str]) -> None:
        super().__init__("HTTP 429")
        self.response = SimpleNamespace(status_code=429, headers=headers)


def build_checker() -> object:
    checker = object.__new__(updates.ReleaseChecker)
    checker.max_releases_per_run = 10
    return checker


def test_active_token_limit_does_not_misclassify_daily_request_reset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checker = build_checker()
    attempts = 0
    delays: list[float] = []

    def operation() -> str:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RateLimitError(
                {
                    "retry-after": "6",
                    "x-ratelimit-reset-requests": "23h",
                    "x-ratelimit-remaining-requests": "998",
                    "x-ratelimit-reset-tokens": "6s",
                    "x-ratelimit-remaining-tokens": "0",
                }
            )
        return "success"

    monkeypatch.setattr(updates.time, "sleep", delays.append)

    assert checker._call_groq_api(operation, "テスト") == "success"
    assert delays == [6.5]


def test_exhausted_daily_request_limit_still_fails_fast(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checker = build_checker()
    sleep_calls: list[float] = []

    monkeypatch.setattr(updates.time, "sleep", sleep_calls.append)

    with pytest.raises(updates.GroqRateLimitError, match="60秒を超える"):
        checker._call_groq_api(
            lambda: (_ for _ in ()).throw(
                RateLimitError(
                    {
                        "x-ratelimit-reset-requests": "23h",
                        "x-ratelimit-remaining-requests": "0",
                        "x-ratelimit-reset-tokens": "6s",
                        "x-ratelimit-remaining-tokens": "0",
                    }
                )
            ),
            "テスト",
        )

    assert sleep_calls == []
