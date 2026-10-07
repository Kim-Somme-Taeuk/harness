"""Codex routing must admit complete groups without owning routing persistence."""
import copy
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / 'plugin/scripts/parallel_dispatch.py'
spec = importlib.util.spec_from_file_location('parallel_model_dispatch', SCRIPT)
dispatcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dispatcher)


def snapshot(tmp_path):
    return dict(runtime='codex', routing=dict(task_dir=str(tmp_path),
                available_models=['gpt-6.1-sol', 'gpt-6-astra']), host_capacity=5,
                live_agents=[dict(id='root', role='coordinator')], acs=[
                    dict(id=f'AC-{n}', files=[f'src/{n}.py'], tests=[f'tests/{n}.py'],
                         routing=dict(impact=impact, recovery='easy', reason='bounded change',
                                      issue_id=f'issue-{n}', workers={
                                          'implementation': f'impl_{n}', 'test-author': f'test_{n}'}))
                    for n, impact in enumerate(('local', 'critical'))])


def install_router(monkeypatch, override=None):
    calls = []

    def calculate(task_dir, request):
        calls.append((task_dir, copy.deepcopy(request)))
        if override:
            result = override(request)
            if result:
                return result
        high = request['assessment']['impact'] == 'critical'
        model = 'gpt-6-astra' if high else 'gpt-6.1-sol'
        return dict(action='spawn', worker=request['worker'], model=model,
                    risk='high' if high else 'low',
                    spawn_args=dict(model=model, fork_turns='none'))

    monkeypatch.setitem(sys.modules, 'routing_state', SimpleNamespace(calculate=calculate))
    return calls


def test_mixed_risk_routes_every_worker_without_mutating_snapshot(monkeypatch, tmp_path):
    data = snapshot(tmp_path)
    before = copy.deepcopy(data)
    calls = install_router(monkeypatch)
    result = dispatcher.schedule(data)
    assert len(calls) == 4
    for index, group in enumerate(result['dispatch']):
        expected = 'gpt-6-astra' if index else 'gpt-6.1-sol'
        for offset, worker in enumerate(group['workers']):
            task_dir, request = calls[index * 2 + offset]
            assert task_dir == str(tmp_path)
            assert worker['routing_request'] == request
            assert worker['model'] == expected
            assert worker['spawn_args'] == dict(model=expected, fork_turns='none')
            assert worker['worker'] == request['worker']
            assert worker['risk'] == ('high' if index else 'low')
            assert request['ac_id'] == group['ac_id']
            assert request['issue_id'] == f'issue-{index}'
            assert request['reason'] == 'bounded change'
    assert result['remaining_slots'] == 0
    assert data == before
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize('section,field', [
    ('snapshot', 'routing'), ('global', 'task_dir'), ('global', 'available_models'),
    ('ac', 'routing'), ('lane', 'impact'), ('lane', 'recovery'), ('lane', 'reason'),
    ('lane', 'issue_id'), ('lane', 'workers'), ('workers', 'test-author'),
])
def test_missing_routing_fields_fail_closed(tmp_path, section, field):
    data = snapshot(tmp_path)
    target = {'snapshot': data, 'global': data['routing'], 'ac': data['acs'][0],
              'lane': data['acs'][0]['routing'],
              'workers': data['acs'][0]['routing']['workers']}[section]
    del target[field]
    with pytest.raises(dispatcher.DispatchError, match='routing'):
        dispatcher.schedule(data)


def test_duplicate_worker_names_rejected(tmp_path):
    data = snapshot(tmp_path)
    data['acs'][1]['routing']['workers']['test-author'] = 'impl_0'
    with pytest.raises(dispatcher.DispatchError, match='globally unique'):
        dispatcher.schedule(data)


@pytest.mark.parametrize('action', ['blocked', 'stop'])
def test_blocked_pair_releases_capacity_and_ownership(monkeypatch, tmp_path, action):
    data = snapshot(tmp_path)
    data['host_capacity'] = 3
    data['ac_cap'] = 1
    data['acs'][1]['files'] = data['acs'][0]['files']
    calls = install_router(monkeypatch, lambda request: dict(action=action, reason='route unavailable')
                           if request['worker'] == 'test_0' else None)
    result = dispatcher.schedule(data)
    assert [group['ac_id'] for group in result['dispatch']] == ['AC-1']
    assert result['remaining_slots'] == 0
    assert len(calls) == 4
    assert action in result['deferred'][0]['reason']
    assert 'route unavailable' in result['deferred'][0]['reason']


def test_existing_admission_constraints_precede_routing(monkeypatch, tmp_path):
    data = snapshot(tmp_path)
    data['acs'][1]['depends_on'] = ['AC-0']
    calls = install_router(monkeypatch)
    result = dispatcher.schedule(data)
    assert len(calls) == 2
    assert 'dependency' in result['deferred'][0]['reason']


@pytest.mark.parametrize('runtime', [None, 'claude'])
def test_default_and_claude_ignore_codex_routing(monkeypatch, tmp_path, runtime):
    data = snapshot(tmp_path)
    data.pop('runtime')
    if runtime:
        data['runtime'] = runtime
    data['routing'] = None
    for ac in data['acs']:
        ac.pop('routing')
    calls = install_router(monkeypatch)
    result = dispatcher.schedule(data)
    assert len(result['dispatch']) == 2
    assert not calls
    assert all(set(worker) == {'role', 'paths'}
               for group in result['dispatch'] for worker in group['workers'])


def test_real_router_mixed_models_and_missing_model_are_read_only(tmp_path):
    import json

    task = tmp_path / 'doc/harness/tasks/TASK__routing'
    task.mkdir(parents=True)
    control = task / 'TASK.json'
    control.write_text(json.dumps(dict(run_id='01a114f8-cf7f-7084-830f-7d25fb5d30b6',
                                      execution_mode='standard', required_lenses=['review-code', 'qa-cli'],
                                      close_receipt_fingerprint=None)))
    before = control.read_bytes()
    data = snapshot(task)
    result = dispatcher.schedule(data)
    assert [group['workers'][0]['model'] for group in result['dispatch']] == [
        'gpt-6.1-sol', 'gpt-6-astra']
    data['routing']['available_models'] = ['gpt-6.1-sol']
    result = dispatcher.schedule(data)
    assert [group['ac_id'] for group in result['dispatch']] == ['AC-0']
    assert 'blocked' in result['deferred'][0]['reason']
    assert result['remaining_slots'] == 2
    assert list(task.iterdir()) == [control]
    assert control.read_bytes() == before
