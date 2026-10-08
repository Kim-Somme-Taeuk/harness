"""Valid native events survive exhausted transient storage retries.

The integration probe uses the production protected writer in a fresh process;
only the OS open operation is fault-injected, never the evidence/trust helpers.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]

PROBE = r'''
import json, os, sys, time
from pathlib import Path
from unittest import mock
sys.path[:0] = [str(Path(sys.argv[1]) / "tests"), str(Path(sys.argv[1]) / "plugin/scripts")]
import codex_lifecycle_watcher as mod
import test_codex_lifecycle_watcher as fixtures

base = Path(sys.argv[2])
mode = sys.argv[3]
repo = base / 'repo'
(repo / '.git').mkdir(parents=True)
home = base / 'codex'
os.environ['CODEX_HOME'] = str(home)
os.environ['XDG_STATE_HOME'] = str(base / 'state')
roots = ['019f825b-f25f-70c3-8ee8-071f79fa1c42', '019f825b-f25f-70c3-8ee8-071f79fa1c43']
registrations = []
tasks = []
delayed_children = []
for root_index, root in enumerate(roots):
    task = repo / 'doc/harness/tasks' / ('TASK__retry_' + str(root_index))
    task.mkdir(parents=True)
    fixtures._write_task_control(task)
    markers = task.parent / '.active_sessions'
    markers.mkdir(exist_ok=True)
    (markers / (root + '.json')).write_text(json.dumps({
        'session_id': root, 'task_dir': str(task), 'task_id': task.name,
        'run_id': fixtures.RUN_ID, 'updated': '2026-08-11T05:00:00Z',
    }) + '\n')
    rollout = fixtures._rollout_path(home, root)
    fixtures._write_jsonl(rollout, [{'type': 'session_meta', 'payload': {
        'id': root, 'session_id': root, 'cwd': str(repo), 'thread_source': 'user',
    }}])
    assert mod.ensure(str(repo), root, task_id=task.name, run_id=fixtures.RUN_ID)
    registration = json.loads(mod._state_path(str(repo), root).read_text())
    registrations.append(registration)
    tasks.append(task)
    events = []
    for index in range(2):
        child = '019f82a6-ce64-75a3-b01d-' + ('%012x' % (100 + root_index * 2 + index))
        name = 'qa_api_retry_' + str(index)
        agent = '/root/' + name
        final = 'VERDICT: PASS\nAuthenticated child ' + child
        child_events = fixtures._child_events(root, child, agent, str(repo), final)
        if mode == 'wrong_child' and index == 0:
            child_events[0]['payload']['parent_thread_id'] = roots[1-root_index]
        child_path = fixtures._rollout_path(home, child)
        if mode == "delayed_child" and index == 0:
            delayed_children.append((child_path, child_events))
        else:
            fixtures._write_jsonl(child_path, child_events)
        events += fixtures._spawn_events(root, child, name, agent, 'call_retry_' + str(index))
        events += [{'type': 'response_item', 'payload': {
            'type': 'agent_message', 'author': agent, 'recipient': '/root',
            'content': [{'type': 'input_text', 'text': 'Message Type: FINAL_ANSWER\nPayload:\n' + final}],
        }}]
    with rollout.open('a') as handle:
        for event in events:
            handle.write(json.dumps(event) + '\n')

original_open = os.open
failures = 0
def transient_open(path, flags, *args, **kwargs):
    global failures
    # Fail the real protected append, after all identity/binding validation.
    if (mode not in {'wrong_child', 'stale', 'delayed_child'} and str(path) == 'RECEIPTS.jsonl'
            and flags & os.O_APPEND and failures < 3
            and os.path.realpath('/proc/self/fd/' + str(kwargs.get('dir_fd'))) == str(tasks[0])):
        failures += 1
        raise OSError('injected temporary receipt storage outage')
    return original_open(path, flags, *args, **kwargs)

def rows(task):
    path = task / 'RECEIPTS.jsonl'
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

if mode == 'wrong_run':
    fixtures._write_task_control(tasks[0], run_id=fixtures.PRIOR_RUN_ID)

if mode == 'stale':
    for registration in registrations:
        os.utime(registration['rollout'], (1, 1))

with mock.patch.object(os, 'open', side_effect=transient_open):
    if mode in {'bounded', 'wrong_run'}:
        registration = registrations[0]
        result = mod.watch(str(repo), roots[0], registration['rollout'], registration['offset'],
                           idle_seconds=1)
        print(json.dumps({'result': result, 'failures': failures, 'rows': rows(tasks[0])}))
    else:
        original_idle = mod.watch.__kwdefaults__['idle_seconds']
        if mode == 'delayed_child':
            mod.watch.__kwdefaults__['idle_seconds'] = .1
        manager = mod.WatcherManager(str(repo), scan_seconds=.02)
        attempts = 0
        made_stale = False
        published_after_expiry = False
        target = 2 if mode == 'wrong_child' else 4
        deadline = time.monotonic() + 5
        try:
            while time.monotonic() < deadline:
                if (mode == 'stale_recovery' and not made_stale
                        and manager.worker_results.get(roots[0], 0) != 0):
                    os.utime(registrations[0]['rollout'], (1, 1))
                    made_stale = True
                if mode == 'delayed_child' and not published_after_expiry and all(
                    root in manager.worker_results for root in roots
                ):
                    for child_path, child_events in delayed_children:
                        fixtures._write_jsonl(child_path, child_events)
                    published_after_expiry = True
                attempts += manager.scan_once()
                if all(len(rows(task)) == target for task in tasks):
                    break
                time.sleep(.02)
        finally:
            manager.stop()
            mod.watch.__kwdefaults__['idle_seconds'] = original_idle
        first_rows = [rows(task) for task in tasks]
        # Replay the exact unchanged registration through the production writer.
        for root, registration in zip(roots, registrations):
            os.utime(registration['rollout'], None)
            assert mod.watch(str(repo), root, registration['rollout'], registration['offset'],
                             task_id=registration['task_id'], run_id=registration['run_id'],
                             idle_seconds=.1, recovering=True) == 0
        print(json.dumps({'attempts': attempts, 'failures': failures, 'rows': first_rows,
                          'made_stale': made_stale, 'published_after_expiry': published_after_expiry,
                          'replayed': [rows(task) for task in tasks],
                          'registrations': [json.loads(mod._state_path(str(repo), root).read_text())
                                            for root in roots],
                          'initial_registrations': registrations}))
'''


def run_probe(tmp_path, mode):
    result = subprocess.run(
        [sys.executable, '-c', PROBE, str(REPO), str(tmp_path), mode],
        cwd=REPO, text=True, capture_output=True, timeout=20,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_exhausted_valid_record_returns_failure_instead_of_successful_skip(tmp_path):
    result = run_probe(tmp_path, 'bounded')
    assert result['failures'] == 3
    assert result['result'] != 0, 'a skipped valid event must remain eligible for manager replay'


def test_manager_recovers_parallel_children_for_two_roots_without_duplicate_receipts(tmp_path):
    result = run_probe(tmp_path, 'recovery')
    assert result['failures'] == 3
    assert [len(rows) for rows in result['rows']] == [4, 4], 'all children must persist before any test replay'
    assert result['attempts'] >= 3, 'the failed worker must be restarted from its original registration'
    assert result['registrations'] == result['initial_registrations']
    assert result['replayed'] == result['rows']
    runtime_sets = []
    for rows in result['rows']:
        assert len(rows) == 4, rows
        runtime_ids = {row['runtime_id'] for row in rows}
        assert len(runtime_ids) == 2
        runtime_sets.append(runtime_ids)
        for runtime_id in runtime_ids:
            pair = [row for row in rows if row['runtime_id'] == runtime_id]
            assert [(row['event'], row['verdict']) for row in pair] == [('started', ''), ('completed', 'PASS')]
            assert pair[0]['agent_id'] == pair[1]['agent_id']
            assert pair[0]['task_run_id'] == pair[1]['task_run_id']
    assert runtime_sets[0].isdisjoint(runtime_sets[1])


def test_retry_does_not_admit_wrong_child_identity(tmp_path):
    result = run_probe(tmp_path, 'wrong_child')
    assert result['replayed'] == result['rows']
    for rows in result['rows']:
        assert len(rows) == 2
        assert {row['agent_id'] for row in rows} == {'/root/qa_api_retry_1'}
        assert [(row['event'], row['verdict']) for row in rows] == [('started', ''), ('completed', 'PASS')]


def test_fresh_manager_reads_old_unread_checkpoint_backlog(tmp_path):
    result = run_probe(tmp_path, 'stale')
    assert result['attempts'] == 2
    assert result['registrations'] == result['initial_registrations']
    assert result['replayed'] == result['rows']
    assert [len(rows) for rows in result['rows']] == [4, 4]


def test_failed_worker_recovers_even_if_rollout_has_become_idle(tmp_path):
    result = run_probe(tmp_path, 'stale_recovery')
    assert result['made_stale']
    assert result['failures'] == 3
    assert result['attempts'] >= 3
    assert [len(rows) for rows in result['rows']] == [4, 4]
    assert result['replayed'] == result['rows']


def test_retry_does_not_admit_changed_task_run(tmp_path):
    result = run_probe(tmp_path, 'wrong_run')
    assert result['result'] != 0
    assert result['rows'] == []


def test_manager_retries_child_evidence_published_after_idle_expiry(tmp_path):
    result = run_probe(tmp_path, 'delayed_child')
    assert result['published_after_expiry']
    assert result['attempts'] >= 4
    assert [len(rows) for rows in result['rows']] == [4, 4]
    assert result['replayed'] == result['rows']
    assert result['registrations'] == result['initial_registrations']
