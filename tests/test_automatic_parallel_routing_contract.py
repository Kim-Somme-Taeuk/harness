"""Exercise Goal-to-pool entry points and runtime payloads, not forged receipts."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import subprocess
import sys



REPO = Path(__file__).resolve().parents[1]
CHILD = 'TASK__integration'
GOAL = 'GOAL__automatic-pack'


def make_context(tmp_path, monkeypatch):
    from test_batch_state import Pool, request, _git
    from test_harness_mcp_server import HarnessMcpServerTests

    pool = Pool(tmp_path, monkeypatch)
    # Match the repository's operational Goal-state ignore rule, so a Goal
    # declaration does not make the batch destination dirty.
    ignore = pool.repo / '.gitignore'
    ignore.write_text(ignore.read_text() + 'doc/harness/goals/\n')
    _git('add', '.gitignore', cwd=pool.repo)
    _git('commit', '-qm', 'ignore operational goals', cwd=pool.repo)
    server = HarnessMcpServerTests()

    def call(name, args):
        return server._call_in_repo(str(pool.repo), name, args)

    result = call('goal_start', dict(objective='Integrate independent work', goal_id=GOAL))
    assert not result.get('isError'), result
    return pool, call, [request('a'), request('b')]


def declare(context):
    pool, call, requests = context
    result = call('goal_add_task', dict(task_id=CHILD, batch_requests=requests))
    assert not result.get('isError'), result
    child = result['structuredContent']['goal']['tasks'][0]
    pool.batch = child['batch']['batch_id']
    return child


def current_bytes(pool):
    return (pool.repo / 'doc/harness/goals/current.json').read_bytes()


def test_mcp_declares_pack_then_routes_without_opening_task(tmp_path, monkeypatch):
    context = make_context(tmp_path, monkeypatch)
    pool, call, requests = context
    child = declare(context)
    assert child['batch']['requests'] == requests
    assert child['task_id'] == CHILD
    assert not (pool.repo / 'doc/harness/tasks' / CHILD).exists()
    assert not pool.state.exists()
    result = call('goal_next_task', {})
    assert not result.get('isError'), result
    body = result['structuredContent']
    assert body['dispatch']['route'] == 'batch'
    assert body['dispatch']['batch_id'] == child['batch']['batch_id']
    assert body['dispatch']['requests'] == requests
    assert body['dispatch']['batch_state'] == 'missing'
    assert not pool.state.exists()


def test_integration_task_start_refuses_before_scaffold(tmp_path, monkeypatch):
    context = make_context(tmp_path, monkeypatch)
    pool, call, _ = context
    declare(context)
    result = call('task_start', dict(task_id=CHILD, title='Integration'))
    assert result.get('isError'), result
    assert 'unfinished' in result['structuredContent']['error']
    assert not (pool.repo / 'doc/harness/tasks' / CHILD).exists()


def test_goal_resync_and_child_status_update_preserve_immutable_pack(tmp_path, monkeypatch):
    context = make_context(tmp_path, monkeypatch)
    pool, call, requests = context
    child = declare(context)
    resync = call('goal_start', dict(goal_id=GOAL, objective='Updated objective', source={'kind': 'native_goal'}))
    assert resync['structuredContent']['goal']['tasks'][0]['batch'] == child['batch']
    update = call('goal_add_task', dict(task_id=CHILD, status='active', title='Updated title'))
    assert update['structuredContent']['goal']['tasks'][0]['batch'] == child['batch']
    before = current_bytes(pool)
    changed = copy.deepcopy(requests)
    changed[0]['request'] = 'Change the declared intent'
    rejected = call('goal_add_task', dict(task_id=CHILD, batch_requests=changed))
    assert rejected.get('isError'), rejected
    assert 'immutable' in rejected['structuredContent']['error']
    assert current_bytes(pool) == before


def test_ordinary_child_keeps_legacy_routing(tmp_path, monkeypatch):
    context = make_context(tmp_path, monkeypatch)
    pool, call, _ = context
    result = call('goal_add_task', dict(task_id='TASK__ordinary'))
    child = result['structuredContent']['goal']['tasks'][0]
    assert 'batch' not in child
    result = call('goal_next_task', {})
    assert result['structuredContent']['task']['task_id'] == 'TASK__ordinary'
    assert 'dispatch' not in result['structuredContent']


def test_malformed_pack_is_rejected_without_goal_mutation(tmp_path, monkeypatch, malformed):
    context = make_context(tmp_path, monkeypatch)
    pool, call, _ = context
    before = current_bytes(pool)
    result = call('goal_add_task', dict(task_id=CHILD, batch_requests=malformed))
    assert result.get('isError'), result
    assert current_bytes(pool) == before
    assert not (pool.repo / 'doc/harness/tasks' / CHILD).exists()


def test_goal_finish_refuses_unfinished_pack_even_with_closed_child_fixture(tmp_path, monkeypatch, pool_state):
    context = make_context(tmp_path, monkeypatch)
    from test_batch_state import task

    pool, call, requests = context
    declare(context)
    if pool_state != 'missing':
        pool.init(requests)
        if pool_state == 'abandoned':
            for slug in ['a', 'b']:
                pool.cli('abandon', '--slug', slug, '--worker-stopped', '--reason', 'not dispatched')
            pool.cli('close')
    # Existing isolated test fixture proves the pack adds a gate beyond the
    # child's valid control fingerprint; this is not production attestation.
    task(pool.repo, slug='integration', closed=True)
    update = call('goal_add_task', dict(task_id=CHILD, status='closed'))
    assert not update.get('isError'), update
    before = current_bytes(pool)
    result = call('goal_finish', dict(status='complete'))
    assert result.get('isError'), result
    assert 'unfinished' in result['structuredContent']['error']
    assert current_bytes(pool) == before


def test_batch_claim_respects_actual_available_slots_and_rejects_negative(tmp_path, monkeypatch):
    context = make_context(tmp_path, monkeypatch)
    pool, _, requests = context
    pool.init(requests, cap=8)
    assert pool.cli('claim', '--available-slots', '0')['claims'] == []
    before = pool.state.read_bytes()
    result = pool.cli('claim', '--available-slots', '-1', ok=False)
    assert result['status'] != 'ok'
    assert pool.state.read_bytes() == before
    claimed = pool.cli('claim', '--available-slots', '1')['claims']
    assert [item['slug'] for item in claimed] == ['a']
    assert pool.cli('claim', '--available-slots', '0')['claims'] == []
    state = json.loads(pool.state.read_text())
    assert [item['status'] for item in state['requests']] == ['reserved', 'queued']


def test_both_runtime_payloads_ship_executable_dispatch_and_ready_lane_guide(tmp_path):
    from test_install_writable_payload import _load_install_module

    install = _load_install_module()
    claude = tmp_path / 'claude'
    codex = tmp_path / 'codex'
    install._build_claude_payload(claude)
    install._build_codex_payload(codex, codex)
    snapshot = dict(host_capacity=3, acs=[dict(id='AC-1', files=['src/a.py'], tests=['tests/a.py'])],
                    live_agents=[dict(id='root', role='coordinator')])
    results = []
    for root, skills in [(claude / 'plugin', 'skills'), (codex, 'internal-skills')]:
        assert (root / 'scripts/goal_batch.py').is_file()
        assert (root / skills / 'develop/ready-lanes.md').is_file()
        completed = subprocess.run([sys.executable, str(root / 'scripts/parallel_dispatch.py')],
                                   input=json.dumps(snapshot), capture_output=True, text=True)
        assert completed.returncode == 0, completed.stderr
        result = json.loads(completed.stdout)
        assert result['dispatch'][0]['mode'] == 'paired'
        results.append(result)
    assert results[0] == results[1]
    guide = (codex / 'internal-skills/develop/ready-lanes.md').read_text()
    assert '${CLAUDE_PLUGIN_ROOT}' not in guide
    assert '${HARNESS_PLUGIN_ROOT}' in guide
    assert (codex / 'internal-skills/batch/SKILL.md').is_file()


def pytest_generate_tests(metafunc):
    cases = {
        'malformed': [None, {}, 'batch', [], [None], [dict(slug='only', request='one', scopes=['a.txt'])]],
        'pool_state': ['missing', 'queued', 'abandoned'],
    }
    for names, values in cases.items():
        if all(name in metafunc.fixturenames for name in names.split(',')):
            metafunc.parametrize(names, values)
