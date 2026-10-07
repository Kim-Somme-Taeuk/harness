import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / 'plugin/scripts'
sys.path.insert(0, str(SCRIPTS))
import failure_handoff as handoff


def failure(attempt=1, **updates):
    return dict(task_id='TASK__test', run_id='run', ac_id='AC-001', issue_id='issue',
                attempt=attempt, worker='sol-worker', model='gpt-6.1-sol',
                summary='assertion failed', attempted=['fix'], changed_files=['a.py'],
                checks=['pytest: exit 1 assertion mismatch'], remaining='fix assertion',
                recorded_by='worker') | updates


def request(**updates):
    return {k: failure()[k] for k in handoff.IDENTITY} | dict(
        available_models=['gpt-6.1-sol', 'gpt-6-astra']) | updates


def test_roundtrip_and_retry_limit(tmp_path):
    for attempt in range(1, 4):
        saved = handoff.record_failure(tmp_path, failure(attempt))
        assert json.loads(Path(saved['path']).read_text()) == failure(attempt)
        decision = handoff.resume(tmp_path, request())
        assert decision['failed_attempts'] == attempt
        assert len(decision['handoff_paths']) == attempt
        if attempt < 3:
            assert decision['spawn_args'] == dict(model='gpt-6-astra', fork_turns='none')
        else:
            assert decision['action'] == 'stop'
            assert 'spawn_args' not in decision


def test_duplicate_does_not_overwrite(tmp_path):
    path = Path(handoff.record_failure(tmp_path, failure())['path'])
    before = path.read_bytes()
    with pytest.raises(ValueError):
        handoff.record_failure(tmp_path, failure(summary='replacement'))
    assert path.read_bytes() == before


@pytest.mark.parametrize('field', handoff.IDENTITY)
def test_wrong_identity_cannot_resume(tmp_path, field):
    handoff.record_failure(tmp_path, failure())
    with pytest.raises(ValueError):
        handoff.resume(tmp_path, request(**{field: 'different'}))


@pytest.mark.parametrize('mode', ['corrupt', 'gap', 'identity', 'symlink'])
def test_invalid_history_refused(tmp_path, mode):
    path = Path(handoff.record_failure(tmp_path, failure())['path'])
    if mode == 'corrupt':
        path.write_text('{')
    elif mode == 'gap':
        handoff.record_failure(tmp_path, failure(2))
        path.unlink()
    elif mode == 'identity':
        path.write_text(json.dumps(failure(run_id='other')))
    else:
        source = tmp_path / 'other'
        path.rename(source)
        path.symlink_to(source)
    with pytest.raises(ValueError):
        handoff.resume(tmp_path, request())


def test_crash_observation_and_no_manual_count(tmp_path):
    handoff.record_failure(tmp_path, failure(recorded_by='coordinator', attempted=[], changed_files=[]))
    assert handoff.resume(tmp_path, request())['action'] == 'spawn'
    with pytest.raises(ValueError):
        handoff.resume(tmp_path, request(failed_attempts=0))


@pytest.mark.parametrize('update', [dict(attempt=True), dict(attempt=0), dict(attempt=4),
    dict(checks=[]), dict(remaining=''), dict(recorded_by='unknown')])
def test_invalid_record(tmp_path, update):
    with pytest.raises(ValueError):
        handoff.record_failure(tmp_path, failure(**update))
    assert not list(tmp_path.iterdir())


def test_cli_persist_then_read_in_new_process(tmp_path):
    command = [sys.executable, str(SCRIPTS / 'failure_handoff.py')]
    def call(action, data):
        return subprocess.run(command + [action, '--directory', str(tmp_path)],
                              input=json.dumps(data), text=True, capture_output=True)
    assert call('resume', request()).returncode == 2
    assert call('record', failure()).returncode == 0
    result = call('resume', request())
    assert result.returncode == 0
    assert json.loads(result.stdout)['spawn_args']['model'] == 'gpt-6-astra'
    assert call('record', failure()).returncode == 2
