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
    monkeypatch.setattr(updates.time, 'time', lambda: clock[0])
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
    assert len(list(cache.glob('v*.json'))) == 17
    before = {p.name: p.read_bytes() for p in cache.glob('v*.json')}
    calls_before = len(calls)
    with pytest.raises(updates.ProcessingDeferred):
        checker(clock[0] + 1200).summarize_release_notes(notes, 'v1.2.3')
    assert len(calls) == calls_before
    clock[0] += server_delay
    result = checker(clock[0] + 1200).summarize_release_notes(notes, 'v1.2.3')
    assert len(calls) == 33  # 17成功+1失敗+残り15。完了分への追加callなし。
    assert calls[18] == 'R103'
    assert all((cache / name).read_bytes() == data for name, data in before.items())
    assert all(f'<!-- sources:R{i} -->' in result for i in range(1, 193))


def test_retry_after_survives_new_process_state_until_exact_deadline(tmp_path, monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(updates.time, 'time', lambda: now[0])
    waits = []
    monkeypatch.setattr(updates.time, 'sleep', waits.append)
    calls = []

    def new_checker():
        obj = object.__new__(updates.ReleaseChecker)
        obj.summary_cache_dir = tmp_path / 'summary-cache'
        return obj

    def limited():
        calls.append('limited')
        raise RateLimit(90000)

    with pytest.raises(updates.ProcessingDeferred):
        new_checker()._call_groq_api(limited, 'summary')
    state = tmp_path / 'summary-cache/groq-not-before.json'
    assert state.is_file()
    payload = json.loads(state.read_text())
    assert payload == {'schema_version': 1, 'not_before': 91000.0}
    for current in (1000, 87400, 90999.99):
        now[0] = current
        with pytest.raises(updates.ProcessingDeferred):
            new_checker()._call_groq_api(lambda: calls.append('early'), 'authentication')
    assert calls == ['limited'] and waits == []
    now[0] = 91000
    assert new_checker()._call_groq_api(lambda: 'resumed', 'summary') == 'resumed'


@pytest.mark.parametrize('data', ['{', '{"schema_version":true,"not_before":9000}', '{"schema_version":1,"not_before":"9000"}', '{"schema_version":1,"not_before":NaN}', '{"schema_version":1,"not_before":9000,"extra":1}'])
def test_invalid_cooldown_never_calls_provider(tmp_path, monkeypatch, data):
    checker = object.__new__(updates.ReleaseChecker)
    checker.summary_cache_dir = tmp_path
    (tmp_path / 'groq-not-before.json').write_text(data)
    calls = []
    with pytest.raises(ValueError):
        checker._call_groq_api(lambda: calls.append(1), 'summary')
    assert calls == []


def test_cooldown_write_failure_stops_without_retry(tmp_path, monkeypatch):
    checker = object.__new__(updates.ReleaseChecker)
    checker.summary_cache_dir = tmp_path
    monkeypatch.setattr(updates, '_atomic_write_text', lambda *a: (_ for _ in ()).throw(OSError('disk unavailable')))
    calls = []
    def operation():
        calls.append(1)
        raise RateLimit(3600)
    with pytest.raises(OSError):
        checker._call_groq_api(operation, 'summary')
    assert calls == [1]


def test_cooldown_checkpoint_roundtrip_through_workflow_and_fresh_process(tmp_path, monkeypatch):
    import os
    import subprocess
    import sys
    from test_publication_status import git, step_script

    remote = tmp_path / 'remote.git'
    git(tmp_path, 'init', '--bare', str(remote))
    root = tmp_path / 'repo'
    root.mkdir()
    git(root, 'init', '-b', 'main')
    git(root, 'config', 'user.name', 'Test')
    git(root, 'config', 'user.email', 'test@example.invalid')
    reports = root / 'reports/claude-code'
    reports.mkdir(parents=True)
    (reports / 'last-checked.json').write_text('{"last_version":"v2.1.289"}')
    git(root, 'add', '.')
    git(root, 'commit', '-m', 'baseline')
    git(root, 'remote', 'add', 'origin', str(remote))
    git(root, 'push', '-u', 'origin', 'main')
    checker = object.__new__(updates.ReleaseChecker)
    checker.summary_cache_dir = reports / 'summary-cache'
    monkeypatch.setattr(updates.time, 'time', lambda: 1000)
    with pytest.raises(updates.ProcessingDeferred):
        checker._call_groq_api(lambda: (_ for _ in ()).throw(RateLimit(90000)), 'summary')
    original = (checker.summary_cache_dir / 'groq-not-before.json').read_bytes()
    output = tmp_path / 'output'
    output.touch()
    env = {**os.environ, 'GITHUB_OUTPUT': str(output)}
    script = step_script('変更をコミット＆プッシュ').replace('${{ steps.check_changes.outputs.version }}', 'v2.1.289')
    subprocess.run(['bash', '-e', '-c', script], cwd=root, env=env, capture_output=True, check=True)
    status = dict(line.split('=', 1) for line in output.read_text().splitlines())
    assert status == {'pushed':'true', 'reports_published':'false', 'checkpoints_saved':'true'}
    next_root = tmp_path / 'next'
    git(tmp_path, 'clone', '--branch', 'main', str(remote), str(next_root))
    cache = next_root / 'reports/claude-code/summary-cache'
    assert (cache / 'groq-not-before.json').read_bytes() == original
    driver = '''
import importlib.util,sys
from pathlib import Path
sys.path.insert(0, str(Path(sys.argv[1]).parent))
spec=importlib.util.spec_from_file_location("fresh",sys.argv[1]);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
x=object.__new__(m.ReleaseChecker);x.summary_cache_dir=Path(sys.argv[2]);m.time.time=lambda:float(sys.argv[3])
calls=[]
try:
 x._call_groq_api(lambda:calls.append(1),"authentication")
except m.ProcessingDeferred:
 assert not calls
 print("deferred")
else:
 assert calls==[1]
 print("resumed")
'''
    for now, expected in ((87400, 'deferred'), (90999.99, 'deferred'), (91000, 'resumed')):
        result = subprocess.run([sys.executable, '-c', driver, str(ROOT / 'scripts/check-claude-updates.py'), str(cache), str(now)], capture_output=True, text=True, check=True)
        assert result.stdout.strip() == expected


@pytest.mark.parametrize('daily', [False, True])
def test_failed_429_also_preserves_retry_deadline(tmp_path, monkeypatch, daily):
    checker = object.__new__(updates.ReleaseChecker)
    checker.summary_cache_dir = tmp_path
    monkeypatch.setattr(updates.time, 'time', lambda: 1000)
    monkeypatch.setattr(updates.time, 'sleep', lambda delay: None)
    calls = []

    def operation():
        calls.append(1)
        error = RateLimit(5)
        if daily:
            error.response.headers = {'x-ratelimit-reset-requests':'2h', 'x-ratelimit-remaining-requests':'0'}
        raise error

    with pytest.raises(updates.GroqRateLimitError):
        checker._call_groq_api(operation, 'summary')
    assert len(calls) == (1 if daily else 3)
    saved = json.loads((tmp_path / 'groq-not-before.json').read_text())
    assert saved['not_before'] == (8200 if daily else 1005)
    next_checker = object.__new__(updates.ReleaseChecker)
    next_checker.summary_cache_dir = tmp_path
    with pytest.raises(updates.ProcessingDeferred):
        next_checker._call_groq_api(lambda: calls.append('unexpected'), 'authentication')
    assert 'unexpected' not in calls
