"""429の待機指示・実行予算・既存checkpointの独立した回帰契約。"""
import importlib.util
import json
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('updates_bounded', ROOT / 'scripts/check-claude-updates.py')
updates = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(updates)


class RateLimit(Exception):
    status_code = 429

    def __init__(self, seconds):
        super().__init__('sensitive-provider-body')
        self.response = SimpleNamespace(headers={'retry-after': str(seconds)})


def test_repeated_429_backoff_does_not_shrink(monkeypatch, capsys):
    checker = object.__new__(updates.ReleaseChecker)
    attempts = []
    waits = []

    def operation():
        attempts.append(1)
        if len(attempts) < 3:
            raise RateLimit([20, 3][len(attempts) - 1])
        return 'recovered'

    monkeypatch.setattr(updates.time, 'sleep', waits.append)
    assert checker._call_groq_api(operation, 'summary') == 'recovered'
    assert len(attempts) == 3
    assert waits == [20.5, 41.0]
    assert 'sensitive-provider-body' not in capsys.readouterr().out


@pytest.mark.parametrize('remaining', [0, 44, 45, 50])
def test_deadline_reserves_request_timeout_before_wait_or_call(monkeypatch, remaining):
    checker = object.__new__(updates.ReleaseChecker)
    checker.processing_deadline = 100 + remaining
    attempts = []
    waits = []
    monkeypatch.setattr(updates.time, 'monotonic', lambda: 100)
    monkeypatch.setattr(updates.time, 'sleep', waits.append)

    def operation():
        attempts.append(1)
        raise RateLimit(10)

    with pytest.raises(updates.ProcessingDeferred):
        checker._call_groq_api(operation, 'summary')
    assert waits == []
    assert len(attempts) == (1 if remaining > 45 else 0)


def test_three_failed_attempts_keep_failure_and_bound_total_wait(monkeypatch):
    checker = object.__new__(updates.ReleaseChecker)
    waits = []
    attempts = []
    monkeypatch.setattr(updates.time, 'sleep', waits.append)

    def operation():
        attempts.append(1)
        raise RateLimit(40)

    with pytest.raises(updates.GroqRateLimitError):
        checker._call_groq_api(operation, 'summary')
    assert len(attempts) == 3
    assert waits == [40.5, 60.0]


@pytest.mark.parametrize("server_delay", [10, 3600])
def test_checkpoint_resume_with_actual_retry_and_deadline(tmp_path, monkeypatch, server_delay):
    # 32分割のfixtureを同じコードで生成し、17個で停止→残りだけ再開する。
    notes = '\n'.join(f'- Fixed item {i}' for i in range(192))
    cache = tmp_path / 'cache'
    clock = [0.0]
    calls = []
    monkeypatch.setattr(updates.time, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(updates.time, 'sleep', lambda delay: clock.__setitem__(0, clock[0] + delay))

    def create(**kwargs):
        sources = tuple(updates.SourceBullet(**s) for s in json.loads(kwargs['messages'][1]['content'])['sources'])
        calls.append(sources[0].source_id)
        if len(calls) == 18:
            raise RateLimit(server_delay)
        clock[0] += 1
        payload = asdict(updates.build_source_fallback_report(sources))
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))])

    def checker(deadline):
        obj = object.__new__(updates.ReleaseChecker)
        obj.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        obj.summary_cache_dir = cache
        obj.processing_deadline = deadline
        return obj

    with pytest.raises(updates.ProcessingDeferred):
        checker(65).summarize_release_notes(notes, 'v1.2.3')
    assert len(list(cache.glob('*.json'))) == 17
    before = {p.name: p.read_bytes() for p in cache.glob('*.json')}
    result = checker(1200).summarize_release_notes(notes, 'v1.2.3')
    assert len(calls) == 33  # 17成功+1失敗+残り15。完了分への追加callなし。
    assert calls[18] == 'R103'
    assert all((cache / name).read_bytes() == data for name, data in before.items())
    assert all(f'<!-- sources:R{i} -->' in result for i in range(1, 193))
