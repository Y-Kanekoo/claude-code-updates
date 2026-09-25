"""長大ノートによるHTTP 413と途中再開の回帰テスト。"""

from __future__ import annotations

import importlib.util
import json
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.report_generation import build_source_bullets, split_sources

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "updates_batching", ROOT / "scripts/check-claude-updates.py"
)
updates = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(updates)


def checker_with(create):
    checker = object.__new__(updates.ReleaseChecker)
    checker.client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))
    )
    checker._call_groq_api = lambda operation, name: operation()
    return checker


def response_for(kwargs):
    sources = json.loads(kwargs["messages"][1]["content"])["sources"]
    normalized = tuple(updates.SourceBullet(**source) for source in sources)
    payload = asdict(updates.build_source_fallback_report(normalized))
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))]
    )


def test_actual_114_item_release_is_split_without_losing_sources() -> None:
    release = json.loads((ROOT / "tests/fixtures/release-v2.1.280.json").read_text())
    calls = []

    def create(**kwargs):
        calls.append(kwargs)
        return response_for(kwargs)

    markdown = checker_with(create).summarize_release_notes(
        release["body"], release["tag_name"]
    )
    assert len(calls) == 19
    sources = build_source_bullets(release["body"])
    assert len(sources) == 114
    for source in sources:
        assert source.text in markdown
        assert f"<!-- sources:{source.source_id} -->" in markdown
    assert all(call["max_completion_tokens"] == 3072 for call in calls)


def test_413_bisects_instead_of_repeating_identical_input() -> None:
    calls = []

    class TooLarge(Exception):
        status_code = 413

    def create(**kwargs):
        ids = tuple(
            item["source_id"]
            for item in json.loads(kwargs["messages"][1]["content"])["sources"]
        )
        calls.append(ids)
        if len(ids) > 1:
            raise TooLarge("入力超過")
        return response_for(kwargs)

    markdown = checker_with(create).summarize_release_notes(
        "- Added first\n- Fixed second", "v1.2.3"
    )
    assert calls == [("R1", "R2"), ("R1",), ("R2",)]
    assert "Added first" in markdown and "Fixed second" in markdown


def test_single_oversized_item_uses_marked_source_fallback() -> None:
    class TooLarge(Exception):
        status_code = 413

    calls = []

    def create(**kwargs):
        calls.append(kwargs)
        raise TooLarge("入力超過")

    markdown = checker_with(create).summarize_release_notes(
        "- Fixed very long item", "v1.2.3"
    )
    assert len(calls) == 1
    assert "<!-- generation:source-fallback -->" in markdown
    assert "Fixed very long item" in markdown


def test_cache_resumes_completed_batches_after_rate_limit(tmp_path: Path) -> None:
    notes = "\n".join(f"- Fixed item {i}" for i in range(7))
    calls = []

    def create(**kwargs):
        calls.append(kwargs)
        if len(calls) == 2:
            raise updates.GroqRateLimitError("利用上限")
        return response_for(kwargs)

    checker = checker_with(create)
    checker.summary_cache_dir = tmp_path
    with pytest.raises(updates.GroqRateLimitError):
        checker.summarize_release_notes(notes, "v1.2.3")
    assert len(list(tmp_path.glob("*.json"))) == 1
    checker = checker_with(create)
    checker.summary_cache_dir = tmp_path
    result = checker.summarize_release_notes(notes, "v1.2.3")
    assert len(calls) == 3
    assert "Fixed item 6" in result


def test_utf8_budget_preserves_whole_items() -> None:
    sources = build_source_bullets(
        "- Fixed " + "日本語" * 300 + "\n- Added " + "日本語" * 300
    )
    batches = split_sources(sources)
    assert len(batches) == 2
    assert tuple(source for batch in batches for source in batch) == sources


def test_queue_failure_prevents_checkpoint_advancing(
    monkeypatch, tmp_path: Path
) -> None:
    checker = checker_with(None)
    checker.report_content_by_version = {}
    checker.max_releases_per_run = 10
    release = {
        "tag_name": "v1.2.3",
        "published_at": "2026-09-20T00:00:00Z",
        "body": "- Fixed crash",
        "html_url": "https://github.com/anthropics/claude-code/releases/tag/v1.2.3",
    }
    checker.get_last_checked_version = lambda: "v1.2.2"
    checker.validate_groq_authentication = lambda: None
    checker.fetch_releases = lambda _last: [release]
    checker.summarize_release_notes = lambda *args: updates.render_summary_markdown(
        updates.build_source_fallback_report(
            updates.build_source_bullets(release["body"])
        )
    )
    saved = []
    checker.save_last_checked_version = lambda *args: saved.append(args)
    monkeypatch.setattr(updates, "REPORTS_DIR", tmp_path)
    monkeypatch.setattr(
        updates.NotificationStore,
        "enqueue",
        lambda *args: (_ for _ in ()).throw(OSError("保存失敗")),
    )
    with pytest.raises(SystemExit):
        checker.run()
    assert saved == []


def test_batch_output_contract_references_ids_from_that_batch() -> None:
    sources = tuple(
        updates.SourceBullet(f"R{i}", "Fixed crash", "バグ修正") for i in (13, 14)
    )
    payload = json.loads(updates.build_structured_request_payload("", sources))
    assert payload["output_contract"]["summary"]["source_ids"] == ["R13"]
    assert payload["output_contract"]["changes"][0]["source_ids"] == ["R13"]
