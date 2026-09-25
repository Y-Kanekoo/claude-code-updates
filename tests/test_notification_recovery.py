"""Actions成果物から送信結果だけを復元する処理を検証する。"""

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

from scripts.notification_delivery import NotificationStore

SPEC = importlib.util.spec_from_file_location(
    "restore_notification_state",
    Path(__file__).parents[1] / "scripts/restore-notification-state.py",
)
restore = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(restore)


def test_restore_uses_same_workflow_and_branch_and_skips_missing_artifacts(
    monkeypatch, tmp_path: Path
) -> None:
    store = NotificationStore(tmp_path / "state.json")
    store.enqueue("v1", {"content": "更新"})
    calls = []

    def gh_json(arguments):
        calls.append(arguments)
        if arguments[0] == "run":
            assert arguments[arguments.index("--workflow") + 1] == "claude-updates.yml"
            assert arguments[arguments.index("--branch") + 1] == "main"
            assert arguments[arguments.index("--status") + 1] == "completed"
            return [{"databaseId": 3}, {"databaseId": 2}]
        if "/3/" in arguments[1]:
            return {"artifacts": []}
        return {"artifacts": [{"name": "notification-checkpoint", "expired": False}]}

    def run(arguments, **kwargs):
        assert arguments[:4] == ["gh", "run", "download", "2"]
        folder = Path(arguments[arguments.index("--dir") + 1])
        (folder / "notification-state.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "pending": {"v2": {"payload": {"content": "未公開"}}},
                    "delivered": {
                        "v1": {
                            "message_id": "123",
                            "sent_at": "2026-09-26T00:00:00+00:00",
                        }
                    },
                    "incident": None,
                }
            )
        )
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(restore, "gh_json", gh_json)
    monkeypatch.setattr(restore.subprocess, "run", run)
    assert restore.restore_latest_checkpoint("owner/repo", "main", store.path)
    restored = NotificationStore(store.path)
    assert restored.data["pending"] == {}
    assert restored.data["delivered"]["v1"]["message_id"] == "123"
    assert len(calls) == 3


def test_restore_skips_expired_artifacts_without_replacing_state(
    monkeypatch, tmp_path: Path
) -> None:
    path = tmp_path / "state.json"

    def gh_json(arguments):
        if arguments[0] == "run":
            return [{"databaseId": 1}]
        return {"artifacts": [{"name": "notification-checkpoint", "expired": True}]}

    monkeypatch.setattr(restore, "gh_json", gh_json)
    assert not restore.restore_latest_checkpoint("owner/repo", "main", path)
    assert not path.exists()


def test_restore_failure_returns_failure_instead_of_allowing_replay(
    monkeypatch,
) -> None:
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    monkeypatch.setenv("GITHUB_REF_NAME", "main")
    monkeypatch.setattr(
        restore,
        "gh_json",
        lambda _arguments: (_ for _ in ()).throw(OSError("通信失敗")),
    )
    assert restore.main() == 1
