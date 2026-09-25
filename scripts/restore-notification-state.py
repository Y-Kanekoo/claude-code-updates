#!/usr/bin/env python3
"""直近の送信確認をActions成果物から復元し、状態push失敗後の再送を防ぐ。"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path

try:
    from notification_delivery import NotificationStore, REPORTS_DIR, STATE_NAME
except ModuleNotFoundError:
    from scripts.notification_delivery import NotificationStore, REPORTS_DIR, STATE_NAME


def gh_json(arguments: list[str]) -> object:
    """認証情報やAPI応答本文をエラーログへ出さず、読み取りだけを行う。"""
    result = subprocess.run(
        ["gh", *arguments], check=True, capture_output=True, text=True
    )
    return json.loads(result.stdout)


def restore_latest_checkpoint(repository: str, branch: str, path: Path) -> bool:
    """同じworkflow・branchの直近の完了runから、送信済み情報だけを復元する。"""
    runs = gh_json(
        [
            "run",
            "list",
            "--repo",
            repository,
            "--workflow",
            "claude-updates.yml",
            "--branch",
            branch,
            "--status",
            "completed",
            "--limit",
            "20",
            "--json",
            "databaseId",
        ]
    )
    for run in runs:
        run_id = str(int(run["databaseId"]))
        result = gh_json(["api", f"repos/{repository}/actions/runs/{run_id}/artifacts"])
        if not any(
            item.get("name") == "notification-checkpoint" and not item.get("expired")
            for item in result["artifacts"]
        ):
            continue
        with tempfile.TemporaryDirectory(
            prefix="claude-notification-recovery-"
        ) as directory:
            subprocess.run(
                [
                    "gh",
                    "run",
                    "download",
                    run_id,
                    "--repo",
                    repository,
                    "--name",
                    "notification-checkpoint",
                    "--dir",
                    directory,
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            checkpoint = Path(directory) / STATE_NAME
            if not checkpoint.is_file():
                raise RuntimeError("通知確認の成果物に状態ファイルがありません。")
            store = NotificationStore(path)
            changed = store.merge_acknowledgements(NotificationStore(checkpoint))
            print(
                f"通知確認の復元を完了しました（対象run: {run_id}、変更: {changed}）。"
            )
            return changed
    print("復元対象の送信確認はありません。リポジトリの通知状態から処理します。")
    return False


def main() -> int:
    try:
        restore_latest_checkpoint(
            os.environ["GITHUB_REPOSITORY"],
            os.environ["GITHUB_REF_NAME"],
            REPORTS_DIR / STATE_NAME,
        )
    except (RuntimeError, ValueError, KeyError, OSError, subprocess.CalledProcessError):
        print(
            "過去の送信確認を復元できません。重複送信を防ぐため今回は通知を停止します。"
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
