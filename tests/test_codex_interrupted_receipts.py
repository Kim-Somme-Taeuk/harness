"""Native interrupted browser QA, through the protected writer and real gate.

The topology follows the incident: initial QA precedes reviews, its native
turn aborts, reviews finish, and an exact followup produces its own final.
Only temporary fixture rollouts are authored; receipt rows are never seeded.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


REPO = Path(__file__).resolve().parents[1]
PROBE = r'''
import copy, json, os, sys, time, threading
from pathlib import Path
sys.path[:0] = [str(Path(sys.argv[1]) / 'tests'), str(Path(sys.argv[1]) / 'plugin/scripts')]
import codex_lifecycle_watcher as mod
import _lib as lib
import test_codex_lifecycle_watcher as f

base, mode = Path(sys.argv[2]), sys.argv[3]
repo = base / 'repo'
(repo / '.git').mkdir(parents=True)
home = base / '.codex'
os.environ['CODEX_HOME'] = str(home)
root = '019f825b-f25f-70c3-8ee8-071f79fa1c42'
child = '019f82a6-ce64-75a3-b01d-92f7b0b4fe6f'
turns = ['019ff16c-e8de-78c3-8f18-879fd945e8bc',
         '019ff16d-e8de-78c3-8f18-879fd945e8bc',
         '019ff16e-e8de-78c3-8f18-879fd945e8bc']
agent = '/root/qa_browser_incident'
final = 'VERDICT: PASS\nBrowser assertions and screenshots verified in resumed turn.'
task = repo / 'doc/harness/tasks/TASK__interrupted'
task.mkdir(parents=True)
control = {'run_id': f.RUN_ID, 'execution_mode': 'standard',
           'required_lenses': ['review-code', 'review-security', 'qa-browser'],
           'close_receipt_fingerprint': None}
(task / 'TASK.json').write_text(json.dumps(control) + '\n')
markers = task.parent / '.active_sessions'
markers.mkdir()
(markers / (root + '.json')).write_text(json.dumps({
    'session_id': root, 'task_dir': str(task), 'task_id': task.name,
    'run_id': f.RUN_ID, 'updated': '2026-08-11T05:00:00Z'}) + '\n')
rollout = f._rollout_path(home, root)
f._write_jsonl(rollout, [{'type': 'session_meta', 'payload': {
    'id': root, 'session_id': root, 'cwd': str(repo), 'thread_source': 'user'}}])
assert mod.ensure(str(repo), root, task_id=task.name, run_id=f.RUN_ID)
registration = json.loads(mod._state_path(str(repo), root).read_text())

def timestamp(minute):
    return '2026-08-12T12:%02d:00Z' % minute

def native_turn(turn, minute, terminal, *, who=agent, cid=child, text=final):
    boundary = f._child_events(root, cid, who, str(repo))[-1]
    boundary['payload']['internal_chat_message_metadata_passthrough'] = {'turn_id': turn}
    events = [{'timestamp': timestamp(minute), 'type': 'event_msg',
               'payload': {'type': 'task_started', 'turn_id': turn}}, boundary]
    if terminal == 'abort':
        events.append({'timestamp': timestamp(minute + 1), 'type': 'event_msg',
                       'payload': {'type': 'turn_aborted', 'turn_id': turn, 'reason': 'interrupted'}})
    if terminal == 'complete':
        events += [
            {'timestamp': timestamp(minute + 1), 'type': 'event_msg',
             'payload': {'type': 'agent_message', 'phase': 'final_answer', 'message': text}},
            {'timestamp': timestamp(minute + 1), 'type': 'event_msg',
             'payload': {'type': 'task_complete', 'turn_id': turn, 'last_agent_message': text}}]
    return events

def followup(index, minute):
    call = 'call_followup_%d' % index
    events = [
        {'timestamp': timestamp(minute), 'type': 'response_item', 'payload': {
            'type': 'function_call', 'namespace': 'collaboration', 'name': 'followup_task',
            'call_id': call, 'arguments': json.dumps({'target': agent, 'message': 'Resume browser QA'})}},
        {'type': 'event_msg', 'payload': {'type': 'item_completed', 'item': {
            'type': 'SubAgentActivity', 'kind': 'interacted', 'id': call,
            'agent_thread_id': child, 'agent_path': agent}}},
        {'type': 'response_item', 'payload': {
            'type': 'function_call_output', 'call_id': call, 'output': ''}}]
    if mode == 'missing_activity' or (mode.startswith('live_') and index == 1):
        events.pop(1)
    elif mode == 'wrong_activity':
        events[1]['payload']['item']['agent_thread_id'] = root
    elif mode == 'duplicate_activity':
        events.insert(2, copy.deepcopy(events[1]))
    elif mode == 'missing_output':
        events.pop()
    elif mode == 'wrong_output':
        events[-1]['payload']['output'] = 'unexpected'
    elif mode == 'message_only':
        events[0]['payload']['name'] = 'send_message'
    elif mode == 'ambiguous_agent':
        events[1]['payload']['item']['agent_thread_id'] = '019f82a6-ce64-75a3-b01d-92f7b0b4fe70'
    return events

first = native_turn(turns[0], 0, 'complete' if mode.startswith('live_') or mode in {'completed_predecessor', 'delayed_complete', 'old_final_reuse'} else 'abort',
                    text='VERDICT: PASS\nOld generation.')
if mode == 'wrong_abort_id':
    first[-1]['payload']['turn_id'] = turns[1]
elif mode == 'wrong_abort_reason':
    first[-1]['payload']['reason'] = 'cancelled'
elif mode == 'duplicate_abort':
    first.append(copy.deepcopy(first[-1]))
elif mode in {'abort_and_final', 'abort_and_complete'}:
    conflicting = native_turn(turns[0], 0, 'complete')
    first.append(conflicting[-2 if mode == 'abort_and_final' else -1])
elif mode == 'missing_boundary':
    first.pop(1)
elif mode == 'duplicate_boundary':
    first.insert(2, copy.deepcopy(first[1]))
elif mode in {'missing_terminal', 'running_overlap'}:
    first.pop()
elif mode == 'terminal_after_followup':
    first[-1]['timestamp'] = timestamp(9)
elif mode == 'naive_terminal_time':
    first[-1]['timestamp'] = '2026-08-12T12:01:00'

metadata = f._child_events(root, child, agent, str(repo))[:1]
if mode == 'wrong_parent':
    metadata[0]['payload']['parent_thread_id'] = child
child_events = metadata + first
parent_events = f._spawn_events(root, child, 'qa_browser_incident', agent, 'call_initial_browser')
if mode.startswith('live_') or mode in {'completed_predecessor', 'delayed_complete', 'old_final_reuse'}:
    parent_events.append(f._delivery(agent, 'VERDICT: PASS\nOld generation.'))
if mode == 'ambiguous_agent':
    other = '019f82a6-ce64-75a3-b01d-92f7b0b4fe70'
    f._write_jsonl(f._rollout_path(home, other),
        f._child_events(root, other, agent, str(repo))[:1] +
        native_turn(turns[0], 0, 'abort', cid=other) +
        native_turn(turns[1], 6, 'complete', cid=other))
    parent_events += f._spawn_events(root, other, 'qa_browser_incident', agent, 'call_ambiguous_browser')
# Both review completions must precede the *resumed* browser start, not the
# aborted initial start. This exercises the gate's actual causal ordering.
browser_prefix = len(parent_events)
for i, name in enumerate(['review_code_incident', 'review_security_incident']):
    cid = '019f82a6-ce64-75a3-b01d-%012x' % (200 + i)
    who = '/root/' + name
    text = 'VERDICT: PASS\nFINDING_COUNTS: FIX_NOW=0 INVESTIGATE=0 OPTIONAL=0\nReviewed.'
    f._write_jsonl(f._rollout_path(home, cid),
        f._child_events(root, cid, who, str(repo))[:1] +
        native_turn(turns[0], 2, 'complete', who=who, cid=cid, text=text))
    parent_events += f._spawn_events(root, cid, name, who, 'call_review_%d' % i)
    parent_events.append(f._delivery(who, text))

if mode.startswith('live_'):
    # An obsolete browser PASS would be gate-eligible in this ordering. The
    # newer accepted followup must fence it even while child evidence lags.
    parent_events = parent_events[browser_prefix:] + parent_events[:browser_prefix]
parent_events += followup(1, 5)
if mode in {'repeated_abort', 'live_repeated_chain'}:
    child_events += native_turn(turns[1], 6, 'abort')
    parent_events += followup(2, 9)
    child_events += native_turn(turns[2], 10, 'complete')
else:
    child_events += native_turn(turns[1], 6, 'complete')
if mode == 'old_final_reuse':
    child_events = metadata + first + native_turn(turns[1], 6, None)
delivery = f._delivery(agent, 'VERDICT: PASS\nOld generation.' if mode == 'old_final_reuse'
                       else 'VERDICT: PASS\nWrong final' if mode == 'wrong_final' else final)
if mode == 'early_final':
    parent_events.insert(len(parent_events) - 3, delivery)
else:
    parent_events.append(delivery)
if mode == 'late_interrupt':
    parent_events += [
        {'type': 'response_item', 'payload': {'type': 'function_call', 'namespace': 'collaboration',
         'name': 'interrupt_agent', 'call_id': 'call_late_interrupt', 'arguments': json.dumps({'target': agent})}},
        {'type': 'event_msg', 'payload': {'type': 'item_completed', 'item': {
         'type': 'SubAgentActivity', 'kind': 'interrupted', 'id': 'call_late_interrupt',
         'agent_thread_id': child, 'agent_path': agent}}},
        {'type': 'response_item', 'payload': {'type': 'function_call_output',
         'call_id': 'call_late_interrupt', 'output': json.dumps({'status': 'completed'})}}]
child_path = f._rollout_path(home, child)
f._write_jsonl(child_path, metadata + first[:-1] if mode.startswith('live_') or mode in {'delayed', 'delayed_complete'} else child_events)
with rollout.open('a') as handle:
    for event in parent_events:
        handle.write(json.dumps(event) + '\n')
if mode == 'wrong_run':
    control['run_id'] = f.PRIOR_RUN_ID
    (task / 'TASK.json').write_text(json.dumps(control) + '\n')

def rows():
    path = task / 'RECEIPTS.jsonl'
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

def watch():
    return mod.watch(str(repo), root, registration['rollout'], registration['offset'],
                     task_id=registration['task_id'], run_id=registration['run_id'],
                     idle_seconds=.08, recovering=True)

attempts = 0
before = []
if mode.startswith('live_'):
    def publish_activity():
        event = {'type': 'event_msg', 'payload': {'type': 'item_completed', 'item': {
            'type': 'SubAgentActivity', 'kind': 'interacted', 'id': 'call_followup_1',
            'agent_thread_id': child, 'agent_path': agent}}}
        with rollout.open('a') as handle:
            handle.write(json.dumps(event) + '\n')
    timers = [threading.Timer(.3, f._write_jsonl, args=(child_path, child_events))]
    if mode != 'live_missing_activity':
        timers.append(threading.Timer(.45, publish_activity))
    for timer in timers:
        timer.start()
    try:
        first_result = mod.watch(str(repo), root, registration['rollout'], registration['offset'],
                                 task_id=registration['task_id'], run_id=registration['run_id'],
                                 idle_seconds=.7, recovering=True)
    finally:
        for timer in timers:
            timer.join()
elif mode in {'delayed', 'delayed_complete'}:
    # First a real bounded worker expires on unpublished native evidence. A
    # brand new manager must replay its immutable checkpoint after publication.
    first_result = watch()
    before = rows()
    f._write_jsonl(child_path, child_events)
    mod.watch.__kwdefaults__['idle_seconds'] = .08
    manager = mod.WatcherManager(str(repo), scan_seconds=.02)
    deadline = time.monotonic() + 4
    try:
        while time.monotonic() < deadline:
            attempts += manager.scan_once()
            if lib.receipt_runtime_verdict(task) == 'PASS':
                break
            time.sleep(.02)
    finally:
        manager.stop()
else:
    first_result = watch()
initial = rows()
gate_before_replay = lib.receipt_runtime_verdict(task)
receipt = task / 'RECEIPTS.jsonl'
first_bytes = receipt.read_bytes() if receipt.exists() else b''
replay_result = watch()
print(json.dumps({'rows': initial, 'replayed': rows(), 'first_result': first_result,
                  'gate_before_replay': gate_before_replay,
                  'replay_result': replay_result,
                  'same_bytes': first_bytes == (receipt.read_bytes() if receipt.exists() else b''),
                  'gate': lib.receipt_runtime_verdict(task), 'before': before, 'attempts': attempts,
                  'registration_unchanged': registration == json.loads(mod._state_path(str(repo), root).read_text())}))
'''


def run_probe(tmp_path, mode):
    home = tmp_path / 'home'
    home.mkdir()
    env = dict(os.environ, HOME=str(home), XDG_STATE_HOME=str(home / 'state'),
               PYTHONDONTWRITEBYTECODE='1')
    result = subprocess.run([sys.executable, '-B', '-c', PROBE, str(REPO), str(home), mode],
                            cwd=REPO, env=env, text=True, capture_output=True, timeout=15)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


@pytest.mark.parametrize('mode', ['replay', 'repeated_abort', 'late_interrupt', 'completed_predecessor'])
def test_authenticated_resume_reaches_real_browser_gate(tmp_path, mode):
    result = run_probe(tmp_path, mode)
    assert result['gate'] == 'PASS', result
    assert result['first_result'] == 0, 'an interrupted predecessor must not keep a successful successor pending'
    browser = [r for r in result['rows'] if r['lens'] == 'qa-browser']
    assert len(browser) == (4 if mode in {'repeated_abort', 'completed_predecessor'} else 3)
    initial = [r for r in browser if ':call_initial_browser:' in r['runtime_id']]
    assert [r['event'] for r in initial] == (['started', 'completed'] if mode == 'completed_predecessor' else ['started'])
    if mode == 'repeated_abort':
        assert [r['event'] for r in browser if ':call_followup_1:' in r['runtime_id']] == ['started']
    assert browser[-1]['event'] == 'completed' and browser[-1]['verdict'] == 'PASS'
    assert result['same_bytes'] and result['replayed'] == result['rows']
    assert result['registration_unchanged']
    assert result['replay_result'] == 0


@pytest.mark.parametrize('mode', ['delayed', 'delayed_complete'])
def test_delayed_terminal_and_final_survive_worker_expiry_and_manager_restart(tmp_path, mode):
    result = run_probe(tmp_path, mode)
    assert result['first_result'] != 0, 'unpublished terminal must remain retryable'
    assert not any(r['lens'] == 'qa-browser' and r['event'] == 'completed' for r in result['before'])
    assert result['attempts'] >= 1
    assert result['gate'] == 'PASS', result
    assert len(result['rows']) == (8 if mode == 'delayed_complete' else 7)
    assert result['same_bytes'] and result['replayed'] == result['rows']
    assert result['registration_unchanged']
    assert result['replay_result'] == 0


@pytest.mark.parametrize('mode', [
    'wrong_abort_id', 'wrong_abort_reason', 'duplicate_abort', 'abort_and_final',
    'abort_and_complete', 'missing_boundary', 'duplicate_boundary', 'missing_terminal', 'running_overlap',
    'terminal_after_followup', 'naive_terminal_time', 'missing_activity', 'wrong_activity',
    'duplicate_activity', 'missing_output', 'wrong_output', 'message_only',
    'wrong_parent', 'wrong_run', 'old_final_reuse', 'wrong_final', 'early_final', 'ambiguous_agent',
])
def test_invalid_resume_cannot_authorize_browser_pass(tmp_path, mode):
    result = run_probe(tmp_path, mode)
    assert result['gate'] != 'PASS', result
    assert not any(r['lens'] == 'qa-browser' and r['event'] == 'completed' and r['verdict'] == 'PASS'
                   and (mode != 'old_final_reuse' or ':call_initial_browser:' not in r['runtime_id'])
                   for r in result['rows']), result
    assert result['same_bytes'] and result['replayed'] == result['rows']


def test_live_missing_activity_fences_delayed_old_pass_before_replay(tmp_path):
    result = run_probe(tmp_path, 'live_missing_activity')
    assert result['gate_before_replay'] != 'PASS', result
    assert result['gate'] != 'PASS', result
    assert not any(r['lens'] == 'qa-browser' and ':call_followup_1:' in r['runtime_id']
                   and r['event'] == 'completed' for r in result['rows'])


@pytest.mark.parametrize('mode', ['live_delayed_activity', 'live_repeated_chain'])
def test_live_delayed_activity_recovers_authenticated_successor(tmp_path, mode):
    result = run_probe(tmp_path, mode)
    assert result['first_result'] == 0, result
    assert result['gate_before_replay'] == 'PASS', result
    browser = [r for r in result['rows'] if r['lens'] == 'qa-browser']
    call = 'call_followup_2' if mode == 'live_repeated_chain' else 'call_followup_1'
    assert any(':' + call + ':' in r['runtime_id'] and r['event'] == 'completed'
               and r['verdict'] == 'PASS' for r in browser), result
    assert result['replay_result'] == 0 and result['gate'] == 'PASS'
    assert result['same_bytes'] and result['registration_unchanged']
