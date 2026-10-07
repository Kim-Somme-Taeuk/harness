import json
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / 'plugin/scripts'
sys.path.insert(0, str(SCRIPTS))
import routing_state as routing
from failure_handoff import record_failure


@pytest.fixture
def task(tmp_path):
    path = tmp_path / 'doc/harness/tasks/TASK__routing'
    path.mkdir(parents=True)
    (path / 'TASK.json').write_text(json.dumps(dict(run_id='01a114f8-cf7f-7084-830f-7d25fb5d30b6', execution_mode='standard',
        required_lenses=['review-code', 'qa-cli'], close_receipt_fingerprint=None)))
    return path


def request(**updates):
    return dict(worker='worker_low', ac_id='AC-001', issue_id='original', reason='Local reversible change',
                assessment=dict(impact='local', recovery='easy', available_models=['gpt-6.1-sol', 'gpt-6-astra'])) | updates


def arguments(**updates):
    return dict(task_name='worker_low', model='gpt-6.1-sol', fork_turns='none') | updates


def failure(task, attempt=1):
    return dict(task_id=task.name, run_id='01a114f8-cf7f-7084-830f-7d25fb5d30b6', ac_id='AC-001', issue_id='original',
                attempt=attempt, worker='worker_low', model='gpt-6.1-sol', summary='failed check',
                attempted=['fix'], changed_files=['a.py'], checks=['pytest exit 1'],
                remaining='resolve assertion', recorded_by='worker')


def test_persist_and_validate(task):
    result = routing.prepare(task, 'session', request())
    assert result['risk'] == 'low' and result['model'] == 'gpt-6.1-sol'
    record = json.loads(Path(result['routing_path']).read_text())
    assert record['decision']['reason'] == 'Local reversible change'
    assert routing.validate_spawn(task, 'session', arguments())['model'] == 'gpt-6.1-sol'


@pytest.mark.parametrize('args', [arguments(model='gpt-6-astra'), arguments(model=None),
    arguments(fork_turns='all'), arguments(fork_turns=None), arguments(task_name='other')])
def test_wrong_native_arguments_denied(task, args):
    routing.prepare(task, 'session', request())
    with pytest.raises((ValueError, OSError)):
        routing.validate_spawn(task, 'session', args)


def test_missing_record_and_wrong_session_denied(task):
    with pytest.raises(FileNotFoundError):
        routing.validate_spawn(task, 'session', arguments())
    routing.prepare(task, 'session', request())
    with pytest.raises(ValueError):
        routing.validate_spawn(task, 'different', arguments())


def test_new_failure_invalidates_old_decision_and_escalates(task):
    routing.prepare(task, 'session', request())
    directory = task.parent.parent / 'handoffs'
    record_failure(directory, failure(task))
    with pytest.raises(ValueError, match='stale'):
        routing.validate_spawn(task, 'session', arguments())
    result = routing.prepare(task, 'session', request(worker='worker_retry'))
    assert result['model'] == 'gpt-6-astra' and result['failed_attempts'] == 1
    assert routing.validate_spawn(task, 'session', arguments(task_name='worker_retry', model='gpt-6-astra'))
    record_failure(directory, failure(task, 2))
    record_failure(directory, failure(task, 3))
    result = routing.prepare(task, 'session', request(worker='worker_fourth'))
    assert result['action'] == 'stop'
    assert not routing.decision_path(task, 'worker_fourth').exists()


def test_run_rotation_and_tampering_denied(task):
    result = routing.prepare(task, 'session', request())
    path = Path(result['routing_path'])
    record = json.loads(path.read_text())
    record['decision']['model'] = 'gpt-6-astra'
    path.write_text(json.dumps(record))
    with pytest.raises(ValueError):
        routing.validate_spawn(task, 'session', arguments(model='gpt-6-astra'))
    control = json.loads((task/'TASK.json').read_text())
    control['run_id'] = '01a114f8-cf7f-7084-830f-7d25fb5d30b7'
    (task/'TASK.json').write_text(json.dumps(control))
    with pytest.raises(ValueError):
        routing.validate_spawn(task, 'session', arguments())


def test_prepare_idempotent_but_refuses_overwrite(task):
    first = routing.prepare(task, 'session', request())
    assert routing.prepare(task, 'session', request()) == first
    with pytest.raises(ValueError):
        routing.prepare(task, 'session', request(reason='different'))


def test_gate_current_binding_and_exemptions(task):
    payload = dict(cwd=str(task.parents[3]), session_id='session', tool_input=arguments())
    with patch('_lib.find_harness_root', return_value=str(task.parents[3])), \
         patch('_lib.resolve_session_task_binding', return_value={'task_dir':str(task), 'run_id':'01a114f8-cf7f-7084-830f-7d25fb5d30b6'}):
        with pytest.raises(FileNotFoundError):
            routing.gate(payload)
        routing.prepare(task, 'session', request())
        assert routing.gate(payload) == ''
        for name in ('code_review_case', 'qa_cli_case'):
            assert routing.gate(payload | {'tool_input': {'task_name': name}}) == ''
    with patch('_lib.find_harness_root', return_value=str(task.parents[3])), \
         patch('_lib.resolve_session_task_binding', return_value={}):
        with pytest.raises(FileNotFoundError):
            routing.gate(payload)


def test_hook_emits_deny_on_routing_error(task):
    import hook_pre_tool_use as hook
    from io import BytesIO, StringIO
    import contextlib
    class Input:
        buffer = BytesIO(json.dumps(dict(tool_name='collaboration.spawn_agent',
            cwd=str(task.parents[3]), tool_input=arguments())).encode())
    out = StringIO()
    with patch.object(sys, 'stdin', Input()), patch('routing_state.gate', side_effect=ValueError('model mismatch')), \
         patch.object(hook, 'restore_watcher_registration') as watcher, contextlib.redirect_stdout(out):
        assert hook.main() == 0
    assert json.loads(out.getvalue())['hookSpecificOutput']['permissionDecision'] == 'deny'
    watcher.assert_not_called()


def test_cli_roundtrip(task):
    result = subprocess.run([sys.executable, str(SCRIPTS/'routing_state.py'), '--task-dir', str(task),
                             '--session-id', 'session'], input=json.dumps(request()), text=True, capture_output=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)['model'] == 'gpt-6.1-sol'


@pytest.fixture
def pool(tmp_path, monkeypatch):
    from test_batch_state import Pool
    value = Pool(tmp_path, monkeypatch)
    value.init()
    value.claim()
    return value


def batch_request(**updates):
    return request(ac_id='task') | updates


def test_batch_real_claim_cli_and_native_arguments(pool):
    result = subprocess.run([sys.executable, str(SCRIPTS/'routing_state.py'),
        '--batch-repo', str(pool.repo), '--batch-id', pool.batch, '--slug', 'a',
        '--session-id', 'session'], input=json.dumps(batch_request()), text=True, capture_output=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert routing.validate_bootstrap(pool.repo, 'session', arguments())['task_id'] == 'TASK__a'
    for session, args in [('other', arguments()), ('session', arguments(model='gpt-6-astra')),
                          ('session', arguments(fork_turns='all')), ('session', arguments(task_name='missing'))]:
        with pytest.raises((ValueError, OSError)):
            routing.validate_bootstrap(pool.repo, session, args)
    assert not (pool.repo/'doc/harness/tasks/TASK__a').exists()


@pytest.mark.parametrize('transition', ['bind', 'release', 'reclaim', 'missing', 'halt'])
def test_batch_claim_changes_invalidate_decision(pool, transition):
    import batch_state
    routing.prepare_batch(pool.repo, pool.batch, 'a', 'session', batch_request())
    if transition == 'bind':
        pool.bind()
    elif transition in ('release', 'reclaim'):
        pool.cli('release', '--slug', 'a', '--worker-stopped', '--no-external-work')
        if transition == 'reclaim':
            pool.claim()
    elif transition == 'missing':
        pool.state.unlink()
    else:
        state = json.loads(pool.state.read_text())
        state['halted'] = True
        pool.state.write_text(json.dumps(state))
    with pytest.raises((ValueError, OSError, batch_state.Refusal)):
        routing.validate_bootstrap(pool.repo, 'session', arguments())


def test_batch_retained_replacement_preserves_run_and_failure_history(pool):
    from test_batch_state import task as make_task, RUN
    worktree, branch = pool.bind()
    task_dir = make_task(worktree)
    (task_dir/'BLOCKED.md').write_text('fixture blocked task\n')
    record = failure(task_dir) | dict(run_id=RUN, ac_id='task')
    handoffs = task_dir.parent.parent/'handoffs'
    record_failure(handoffs, record)
    pool.cli(*pool.result('a', worktree, branch, run_id=RUN))
    pool.cli('resume', '--slug', 'a', '--worker-stopped')
    decision = routing.prepare_batch(pool.repo, pool.batch, 'a', 'session', batch_request())
    assert decision['model'] == 'gpt-6-astra'
    assert decision['run_id'] == RUN and decision['failed_attempts'] == 1
    assert len(decision['handoff_paths']) == 1
    args = arguments(model='gpt-6-astra')
    assert routing.validate_bootstrap(pool.repo, 'session', args)
    record_failure(handoffs, record | dict(attempt=2))
    with pytest.raises(ValueError, match='stale'):
        routing.validate_bootstrap(pool.repo, 'session', args)
    record_failure(handoffs, record | dict(attempt=3))
    assert routing.prepare_batch(pool.repo, pool.batch, 'a', 'session',
                                 batch_request(worker='worker_stop'))['action'] == 'stop'


def test_batch_repeated_resume_invalidates_old_reservation(pool):
    worktree, branch = pool.bind()
    pool.cli(*pool.result('a', worktree, branch))
    pool.cli('resume', '--slug', 'a', '--worker-stopped')
    routing.prepare_batch(pool.repo, pool.batch, 'a', 'session', batch_request())
    pool.cli('resume', '--slug', 'a', '--worker-stopped')
    with pytest.raises(ValueError, match='stale'):
        routing.validate_bootstrap(pool.repo, 'session', arguments())


@pytest.mark.parametrize('change', ['run', 'missing', 'new-task', 'main-task'])
def test_batch_live_task_changes_refuse_stale_bootstrap(pool, change):
    import batch_state
    from test_batch_state import task as make_task
    worktree, branch = pool.bind()
    task_dir = None if change == 'new-task' else make_task(worktree)
    pool.cli(*pool.result('a', worktree, branch))
    pool.cli('resume', '--slug', 'a', '--worker-stopped')
    routing.prepare_batch(pool.repo, pool.batch, 'a', 'session', batch_request())
    if change == 'run':
        path = task_dir/'TASK.json'
        data = json.loads(path.read_text())
        data['run_id'] = '0198c349-5800-7000-8000-000000000002'
        path.write_text(json.dumps(data))
    elif change == 'missing':
        (task_dir/'TASK.json').unlink()
    elif change == 'new-task':
        make_task(worktree)
    else:
        make_task(pool.repo, slug='main')
    with pytest.raises((ValueError, OSError, batch_state.Refusal)):
        routing.validate_bootstrap(pool.repo, 'session', arguments())


def test_gate_accepts_reserved_batch_without_task_binding(pool):
    routing.prepare_batch(pool.repo, pool.batch, 'a', 'session', batch_request())
    payload = dict(cwd=str(pool.repo), session_id='session', tool_input=arguments())
    with patch('_lib.resolve_session_task_binding', return_value={}):
        assert routing.gate(payload) == ''


def test_gate_resolves_lead_binding_from_main_cwd_and_refuses_ambiguity(pool):
    from test_batch_state import task as make_task, RUN
    def bind_fixture(task_dir):
        directory = task_dir.parent/'.active_sessions'
        directory.mkdir(exist_ok=True)
        (directory/'session.json').write_text(json.dumps(dict(session_id='session',
            task_dir=str(task_dir), task_id=task_dir.name, run_id=RUN)))
    worktree, _ = pool.bind()
    task_dir = make_task(worktree)
    bind_fixture(task_dir)
    routing.prepare(task_dir, 'session', request())
    payload = dict(cwd=str(pool.repo), session_id='session', tool_input=arguments())
    assert routing.gate(payload) == ''
    main_task = make_task(pool.repo, slug='main')
    bind_fixture(main_task)
    with pytest.raises(ValueError, match='multiple workspaces'):
        routing.gate(payload)
