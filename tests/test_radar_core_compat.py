"""共有実装への委譲で、通知の切り詰め結果が変わらないことを確認する。"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from radar_core import discord

from scripts import notification_delivery as delivery


def legacy_clip(value: str, limit: int) -> str:
    """移行前の実装を互換性の比較基準として保持する。"""
    if len(value.encode("utf-16-le")) // 2 <= limit:
        return value
    return (
        value.encode("utf-16-le")[: (limit - 1) * 2].decode(
            "utf-16-le", errors="ignore"
        )
        + "…"
    )


@pytest.mark.parametrize(
    "value",
    [
        "",
        "通知",
        "a\n\nb\r\nc",
        "🚀" * 20,
        "a🚀b👩\u200d💻e\u0301通知" * 200,
        "更新" * 4000,
    ],
)
@pytest.mark.parametrize("limit", [-10, -1, 0, 1, 2, 3, 4, 5, 10, 256, 600, 800, 1900])
def test_clip_matches_legacy(value: str, limit: int) -> None:
    assert delivery.clip(value=value, limit=limit) == legacy_clip(value, limit)


def test_positive_limit_delegates_to_core(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, int]] = []

    def core_clip(text: str, limit: int) -> str:
        calls.append((text, limit))
        return "共有実装"

    monkeypatch.setattr(discord, "clip", core_clip)
    assert delivery.clip("通知", 256) == "共有実装"
    assert calls == [("通知", 256)]


def test_nonpositive_limit_keeps_legacy_without_core(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected_clip(text: str, limit: int) -> str:
        pytest.fail("0以下の上限を共有実装に渡してはいけません")

    monkeypatch.setattr(discord, "clip", unexpected_clip)
    assert delivery.clip("通知", 0) == "通…"
    assert delivery.clip("", 0) == ""
    assert delivery.clip("通知", -1) == "…"


def test_invalid_surrogate_keeps_encoding_error() -> None:
    with pytest.raises(UnicodeEncodeError):
        delivery.clip("\ud800", 256)


def test_state_import_works_before_dependency_installation() -> None:
    """workflow冒頭の復元処理と、直接実行時のimport経路を維持する。"""
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [
            sys.executable,
            "-S",
            "-c",
            "import sys; sys.path.insert(0, 'scripts'); "
            "import notification_delivery; "
            "assert 'radar_core.discord' not in sys.modules; "
            "assert callable(notification_delivery.NotificationStore)",
        ],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
