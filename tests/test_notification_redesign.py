"""通知の再送・重複抑制・公開順序の回帰テスト。"""

from __future__ import annotations

import io
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError

import pytest

from scripts import notification_delivery as delivery
from scripts.report_generation import (
    build_source_bullets,
    build_source_fallback_report,
    render_summary_markdown,
)
from scripts.report_schema import render_reader_report, validate_canonical_report


def test_pending_survives_failure_and_only_unacknowledged_messages_are_retried(
    tmp_path: Path,
) -> None:
    path = tmp_path / "state.json"
    store = delivery.NotificationStore(path)
    store.enqueue("v1", {"content": "更新1"})
    store.enqueue("v2", {"content": "更新2"})
    calls = []

    def send(payload):
        calls.append(payload["content"])
        if len(calls) == 2:
            raise RuntimeError("一時障害")
        return "123"

    with pytest.raises(RuntimeError):
        store.deliver(send, published=True)
    restored = delivery.NotificationStore(path)
    assert list(restored.data["pending"]) == ["v2"]
    assert list(restored.data["delivered"]) == ["v1"]
    restored.enqueue("v1", {"content": "更新1"})
    restored.deliver(
        lambda payload: calls.append(payload["content"]) or "456", published=True
    )
    assert calls == ["更新1", "更新2", "更新2"]
    assert not delivery.NotificationStore(path).data["pending"]


def test_updates_wait_until_publication(tmp_path: Path) -> None:
    store = delivery.NotificationStore(tmp_path / "state.json")
    store.enqueue("v1", {"content": "更新"})
    calls = []
    store.deliver(
        lambda payload: calls.append(payload) or "1",
        published=False,
        failure_type="workflow_failure",
    )
    assert len(calls) == 1
    assert "公開は未確認" in calls[0]["content"]
    assert "v1" in store.data["pending"]
    assert store.data["delivered"] == {}


def test_incident_is_suppressed_until_reminder_then_recovers_once(
    tmp_path: Path,
) -> None:
    path = tmp_path / "state.json"
    calls = []

    def send(payload):
        return calls.append(payload) or "1"

    now = datetime(2026, 9, 26, tzinfo=timezone.utc)
    for days in (0, 1, 6, 7):
        delivery.NotificationStore(path).deliver(
            send,
            published=True,
            failure_type="groq_rate_limit",
            failed_version="v2.1.280",
            now=now + timedelta(days=days),
        )
    assert len(calls) == 2
    assert "v2.1.280" in calls[0]["content"]
    assert "利用上限" in calls[0]["content"]
    for _ in range(2):
        delivery.NotificationStore(path).deliver(send, published=True)
    assert len(calls) == 3
    assert "復旧" in calls[-1]["content"]


def test_changed_cause_is_not_suppressed(tmp_path: Path) -> None:
    store = delivery.NotificationStore(tmp_path / "state.json")
    calls = []
    for cause in ("groq_rate_limit", "groq_authentication"):
        store.deliver(
            lambda payload: calls.append(payload) or "1",
            published=True,
            failure_type=cause,
        )
    assert len(calls) == 2
    assert "認証" in calls[-1]["content"]


def test_unacknowledged_incident_is_retried(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    store = delivery.NotificationStore(path)
    with pytest.raises(RuntimeError):
        store.deliver(
            lambda _payload: (_ for _ in ()).throw(RuntimeError("失敗")),
            published=True,
            failure_type="groq_rate_limit",
        )
    assert delivery.NotificationStore(path).data["incident"] is None


def test_corrupt_notification_state_is_not_reset(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    path.write_text("{")
    with pytest.raises(RuntimeError, match="復旧"):
        delivery.NotificationStore(path)
    assert path.read_text() == "{"


def test_discord_payload_is_bounded_and_omits_source_comments(monkeypatch) -> None:
    monkeypatch.delenv("GITHUB_REF_NAME", raising=False)
    monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
    release = {
        "tag_name": "v2.1.280",
        "published_at": "2026-09-20T00:00:00Z",
        "html_url": "https://github.com/anthropics/claude-code/releases/tag/v2.1.280",
    }
    markdown = (
        "<!-- section:summary -->\n## 要約\n<!-- sources:R1 -->\n- " + "🚀" * 5000
    )
    for name in ("highlights", "recommended_action", "impact"):
        markdown += (
            f"\n<!-- section:{name} -->\n## {name}\n<!-- sources:R1 -->\n- "
            + "長文" * 5000
        )
    payload = delivery.build_release_payload(release, markdown)
    encoded = json.dumps(payload, ensure_ascii=False)
    assert "<!--" not in encoded
    assert "github.io" not in encoded
    assert payload["allowed_mentions"] == {"parse": []}
    embed = payload["embeds"][0]
    assert "/blob/main/reports/claude-code/" in embed["url"]

    def length(text):
        return len(text.encode("utf-16-le")) // 2

    assert length(embed["description"]) <= 4096
    assert all(length(field["value"]) <= 1024 for field in embed["fields"])
    total = (
        length(embed["title"])
        + length(embed["description"])
        + length(embed["footer"]["text"])
    )
    total += sum(
        length(field["name"]) + length(field["value"]) for field in embed["fields"]
    )
    assert total <= 6000


def test_webhook_requests_confirmation_and_honors_retry_after(monkeypatch) -> None:
    calls, delays = [], []

    class Response(io.BytesIO):
        status = 200

    def urlopen(req, timeout):
        assert timeout == 30
        calls.append(req)
        if len(calls) == 1:
            raise HTTPError(
                req.full_url, 429, "制限", {}, io.BytesIO(b'{"retry_after": 2.5}')
            )
        return Response(b'{"id": "123"}')

    monkeypatch.setattr(delivery.request, "urlopen", urlopen)
    monkeypatch.setattr(delivery.time, "sleep", delays.append)
    assert (
        delivery.post_webhook(
            "https://discord.com/api/webhooks/123/token?thread_id=4",
            {"content": "更新"},
        )
        == "123"
    )
    assert "wait=true" in calls[0].full_url
    assert "thread_id=4" in calls[0].full_url
    assert delays == [2.5]


def test_webhook_failure_does_not_expose_secret(monkeypatch) -> None:
    secret_url = "https://discord.com/api/webhooks/123/secret-token"
    monkeypatch.setattr(
        delivery.request,
        "urlopen",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            HTTPError(secret_url, 404, "失敗", {}, io.BytesIO())
        ),
    )
    with pytest.raises(RuntimeError) as captured:
        delivery.post_webhook(secret_url, {"content": "更新"})
    assert "secret-token" not in str(captured.value)
    assert "404" in str(captured.value)


def test_reader_report_puts_action_before_detail_and_keeps_source_provenance() -> None:
    summary = render_summary_markdown(
        build_source_fallback_report(build_source_bullets("- Fixed crash"))
    )
    links = "- [公式](https://github.com/anthropics/claude-code/releases/tag/v2.1.280)\n- [資料](https://docs.anthropic.com/ja/docs/claude-code)"
    report = render_reader_report("v2.1.280", "2026-09-20", summary, links, "model")
    assert (
        validate_canonical_report(
            report, filename="2026-09-20-v2.1.280.md", require_sources=True
        )
        == []
    )
    assert (
        report.index("## 要約")
        < report.index("## 推奨対応")
        < report.index("## 変更内容")
        < report.index("## 関連リンク")
    )
    assert report.count("<!-- section:judgement -->") == 1
    assert "- **影響度**:" not in report
    assert "<!-- sources:R1 -->" in report
    assert "<!-- generation:source-fallback -->" in report
    assert "原文を含む暫定レポート" in report


def test_expiry_reminder_does_not_depend_on_report_publication(tmp_path: Path) -> None:
    store = delivery.NotificationStore(tmp_path / "state.json")
    store.enqueue("v1", {"content": "更新"})
    store.enqueue("key-expiry", {"content": "期限確認"}, requires_publication=False)
    calls = []
    store.deliver(lambda payload: calls.append(payload) or "1", published=False)
    assert calls == [{"content": "期限確認"}]
    assert list(store.data["pending"]) == ["v1"]


def test_broken_incident_timestamp_requires_restoration(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "pending": {},
                "delivered": {},
                "incident": {"key": "error", "sent_at": "昨日"},
            }
        )
    )
    with pytest.raises(RuntimeError, match="復旧"):
        delivery.NotificationStore(path)


def test_acknowledged_state_is_recovered_before_pending_replay(tmp_path: Path) -> None:
    remote = delivery.NotificationStore(tmp_path / "remote.json")
    remote.enqueue("v1", {"content": "更新1"})
    checkpoint = delivery.NotificationStore(tmp_path / "artifact.json")
    checkpoint.enqueue("v1", {"content": "更新1"})
    checkpoint.enqueue("v2", {"content": "未公開の更新2"})
    calls = []

    def send(payload):
        calls.append(payload)
        if payload["content"] == "未公開の更新2":
            raise RuntimeError("停止")
        return "123"

    with pytest.raises(RuntimeError):
        checkpoint.deliver(send, published=True)
    assert remote.merge_acknowledgements(checkpoint)
    assert remote.data["pending"] == {}
    assert remote.data["delivered"]["v1"]["message_id"] == "123"
    assert "v2" not in remote.data["pending"]
    remote.deliver(lambda payload: calls.append(payload) or "123", published=True)
    assert len(calls) == 2
    assert not remote.merge_acknowledgements(checkpoint)


def test_recovered_incident_state_prevents_repeated_recovery(tmp_path: Path) -> None:
    remote = delivery.NotificationStore(tmp_path / "remote.json")
    checkpoint = delivery.NotificationStore(tmp_path / "artifact.json")
    now = datetime(2026, 9, 26, tzinfo=timezone.utc)
    remote.deliver(
        lambda payload: "1", published=True, failure_type="groq_rate_limit", now=now
    )
    checkpoint.data = json.loads(json.dumps(remote.data))
    checkpoint.deliver(
        lambda payload: "2", published=True, now=now + timedelta(hours=1)
    )
    assert remote.merge_acknowledgements(checkpoint)
    assert remote.data["incident"] is None
    calls = []
    remote.deliver(lambda payload: calls.append(payload) or "3", published=True)
    assert calls == []
