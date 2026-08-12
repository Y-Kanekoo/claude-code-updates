#!/usr/bin/env python3
"""Groq API キーの期限を確認し、指定日に Discord へ通知する。"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import date, datetime, timezone
from urllib import error, request
from urllib.parse import urlsplit

EXPIRY_ENV_NAME = "CLAUDE_UPDATES_GROQ_API_KEY_EXPIRES_AT"
WEBHOOK_ENV_NAME = "DISCORD_WEBHOOK_URL"
NOTIFICATION_DAYS = frozenset({14, 7, 1, 0})
EXPIRY_DATE_PATTERN = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")


def parse_expiry_date(value: str) -> date:
    """YYYY-MM-DD 形式の期限日を返す。"""
    if not EXPIRY_DATE_PATTERN.fullmatch(value):
        raise ValueError(
            f"{EXPIRY_ENV_NAME} は YYYY-MM-DD 形式で設定してください: {value!r}"
        )
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(
            f"{EXPIRY_ENV_NAME} は YYYY-MM-DD 形式で設定してください: {value!r}"
        ) from exc


def should_notify(days_remaining: int) -> bool:
    """通知対象の日数かを判定する。期限切れ後は復旧まで毎日通知する。"""
    return days_remaining in NOTIFICATION_DAYS or days_remaining < 0


def build_message(expiry_date: date, days_remaining: int, actions_run_url: str) -> str:
    """Discord に送る日本語メッセージを組み立てる。"""
    if days_remaining < 0:
        timing = f"{abs(days_remaining)}日前に期限切れになりました"
        urgency = "🚨"
    elif days_remaining == 0:
        timing = "本日が有効期限です"
        urgency = "🚨"
    else:
        timing = f"有効期限まであと{days_remaining}日です"
        urgency = "⚠️"

    message = (
        f"{urgency} Groq API キー（`CLAUDE_UPDATES_GROQ_API_KEY`）は"
        f"{expiry_date.isoformat()}が期限で、{timing}。"
        "Groq でキーを再生成し、GitHub Actions の Secret と Repository variable "
        "`CLAUDE_UPDATES_GROQ_API_KEY_EXPIRES_AT` を更新してください。"
    )
    if actions_run_url:
        message += f" [Actions 実行ログ]({actions_run_url})"
    return message


def send_discord_notification(webhook_url: str, message: str) -> None:
    """Discord Webhook へ通知する。"""
    payload = json.dumps({"content": message}).encode("utf-8")
    try:
        parsed = urlsplit(webhook_url)
        port = parsed.port
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or (port is not None and not 1 <= port <= 65535)
        ):
            raise ValueError("有効な HTTPS URL ではありません")
        webhook_request = request.Request(
            webhook_url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with request.urlopen(webhook_request, timeout=15) as response:
            if response.status >= 300:
                raise RuntimeError(
                    f"Discord 通知に失敗しました: HTTP {response.status}"
                )
    except (error.URLError, TimeoutError, ValueError) as exc:
        raise RuntimeError(
            f"Discord 通知に失敗しました: {type(exc).__name__}"
        ) from exc


def main() -> int:
    """環境変数から設定を読み込み、必要な場合だけ通知する。"""
    expiry_value = os.getenv(EXPIRY_ENV_NAME, "").strip()
    if not expiry_value:
        print(
            f"警告: Repository variable {EXPIRY_ENV_NAME} が未設定のため、"
            "Groq API キーの期限通知をスキップします。"
        )
        return 0

    try:
        expiry_date = parse_expiry_date(expiry_value)
    except ValueError as exc:
        print(f"エラー: {exc}", file=sys.stderr)
        return 1

    today = datetime.now(timezone.utc).date()
    days_remaining = (expiry_date - today).days
    if not should_notify(days_remaining):
        print(
            f"Groq API キーの期限は {expiry_date.isoformat()} "
            f"（残り {days_remaining} 日）です。通知対象日ではありません。"
        )
        return 0

    message = build_message(
        expiry_date,
        days_remaining,
        os.getenv("ACTIONS_RUN_URL", "").strip(),
    )
    webhook_url = os.getenv(WEBHOOK_ENV_NAME, "").strip()
    if not webhook_url:
        print(
            f"警告: {WEBHOOK_ENV_NAME} が未設定のため、Discord 通知を送信できません。"
        )
        print(message)
        return 0

    try:
        send_discord_notification(webhook_url, message)
    except RuntimeError as exc:
        print(
            f"警告: {exc}。期限通知のみ失敗したため、更新チェックは続行します。",
            file=sys.stderr,
        )
        return 0

    print(f"Groq API キーの期限通知を送信しました（残り {days_remaining} 日）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
