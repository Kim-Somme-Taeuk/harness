"""Codex dispatch uses capacity and ownership, without model admission."""
import copy
import json
import subprocess
import sys

import pytest

from test_parallel_dispatch import SCRIPT, dispatcher, snapshot, ids


@pytest.mark.parametrize('runtime', ['codex', 'claude', None])
def test_dispatch_without_catalog_or_sidecars(tmp_path, runtime):
    data = snapshot(capacity=5, count=2)
    if runtime:
        data['runtime'] = runtime
    before = copy.deepcopy(data)
    result = subprocess.run([sys.executable, str(SCRIPT)], input=json.dumps(data),
                            cwd=tmp_path, text=True, capture_output=True, timeout=10)
    assert result.returncode == 0, result.stderr
    answer = json.loads(result.stdout)
    assert ids(answer) == ['AC-0', 'AC-1']
    assert answer['remaining_slots'] == 0
    for group, ac in zip(answer['dispatch'], data['acs']):
        assert group['workers'] == [dict(role='implementation', paths=ac['files']),
                                    dict(role='test-author', paths=ac['tests'])]
    assert data == before
    assert list(tmp_path.iterdir()) == []


def test_legacy_model_metadata_has_no_admission_authority():
    data = snapshot(capacity=5, count=2) | {'runtime': 'codex'}
    expected = dispatcher.schedule(data)
    data['routing'] = {'available_models': [], 'task_dir': '/nonexistent'}
    for ac in data['acs']:
        ac['routing'] = {'impact': 'critical', 'workers': {'implementation': 'same'}}
    assert dispatcher.schedule(data) == expected


def test_codex_pair_capacity_and_ownership_remain_atomic():
    data = snapshot(capacity=4, count=3) | {'runtime': 'codex'}
    answer = dispatcher.schedule(data)
    assert ids(answer) == ['AC-0']
    assert answer['dispatch'][0]['slots'] == 2
    assert answer['remaining_slots'] == 1
    data['host_capacity'] = 7
    data['acs'][1]['files'] = data['acs'][0]['files']
    data['acs'][2]['depends_on'] = ['AC-0']
    answer = dispatcher.schedule(data)
    assert ids(answer) == ['AC-0']
    assert any('scope overlaps' in row['reason'] for row in answer['deferred'])
    assert any('dependency' in row['reason'] for row in answer['deferred'])
    data['progress'] = {'AC-0': dict(status='completed', verified=True, workers_released=True)}
    assert ids(dispatcher.schedule(data)) == ['AC-1', 'AC-2']
