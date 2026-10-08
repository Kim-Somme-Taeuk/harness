"""Advisory native events must not poison strict formal receipt capture."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
from unittest import mock

import pytest

import test_codex_lifecycle_watcher as fixtures


REPO = Path(__file__).resolve().parents[1]
UX = ("ux-api", "ux-browser", "ux-cli", "ux-desktop")
FORMAL = ("review-code", "review-security", "qa-api", "qa-browser", "qa-cli", "qa-desktop")


@pytest.mark.parametrize("lens", (*UX, *FORMAL, "ordinary_worker"))
def test_spawn_admission_preserves_generic_ancestry(lens):
    mod = fixtures._load()
    name = lens.replace("-", "_") + "_advisory_boundary"
    event = fixtures._spawn_events("root", "child", name, "/root/" + name)[0]
    identity = ("call_runtime_123456", name)
    assert mod._spawn_call(event, lens_only=False) == identity
    assert mod._spawn_call(event) == (identity if lens in FORMAL else None)
    if lens in UX:
        assert mod._infer_receipt_lens(name) == lens, "advisory inference remains available"


@pytest.mark.parametrize("lens", UX)
def test_start_publication_rejects_advisory_before_writer(tmp_path, lens):
    # Exercise the second admission guard independently of spawn filtering.
    # This unit test cannot confer runtime authority; integration below uses
    # the untouched production writer and trust helpers in a fresh process.
    mod = fixtures._load()
    watcher = mod.Watcher(str(tmp_path), "root")
    name = lens.replace("-", "_") + "_boundary"
    watcher.calls["call_guard123"] = {
        "task_name": name, "output_path": "/root/" + name,
        "agent_path": "/root/" + name, "child_id": "child",
        "task_dir": str(tmp_path), "task_run_id": fixtures.RUN_ID,
    }
    with mock.patch.object(mod, "_coordinator_identity", return_value={}), \
         mock.patch.object(mod, "_require_task_binding", return_value=fixtures._active_binding(tmp_path)), \
         mock.patch.object(mod, "record_subagent_receipt", side_effect=AssertionError("advisory write")), \
         mock.patch.object(mod, "active_session_transaction", side_effect=AssertionError("advisory publication")):
        watcher._maybe_start("call_guard123")
    assert watcher.calls["call_guard123"]["invalid"]


PROBE = r'''
import json, os, sys
from pathlib import Path
sys.path[:0] = [str(Path(sys.argv[1]) / 'tests'), str(Path(sys.argv[1]) / 'plugin/scripts')]
import codex_lifecycle_watcher as mod
import test_codex_lifecycle_watcher as fixtures

base = Path(sys.argv[2])
ux = sys.argv[3]
repo = base / 'repo'
(repo / '.git').mkdir(parents=True)
home = base / 'codex'
os.environ['CODEX_HOME'] = str(home)
root = '019f825b-f25f-70c3-8ee8-071f79fa1c42'
task_id, run_id = fixtures._write_exact_session_binding(repo, root)
task = repo / 'doc/harness/tasks' / task_id
rollout = fixtures._rollout_path(home, root)
fixtures._write_jsonl(rollout, [{'type': 'session_meta', 'payload': {
    'id': root, 'session_id': root, 'cwd': str(repo), 'thread_source': 'user',
}}])
assert mod.ensure(str(repo), root, task_id=task_id, run_id=run_id)
registration = json.loads(mod._state_path(str(repo), root).read_text())
formal = ('review-code', 'review-security', 'qa-api', 'qa-browser', 'qa-cli', 'qa-desktop')
expected = []
events = []
for index, lens in enumerate(formal):
    # Advisory spawn/final/followup precedes every formal pair, including the
    # review-to-QA boundary; each child has independent native evidence.
    for advisory, kind in ((True, ux), (False, lens)):
        name = kind.replace('-', '_') + '_boundary_' + str(index)
        agent = '/root/' + name
        child = '019f82a6-ce64-75a3-b01d-' + ('%012x' % (100 + index * 2 + int(advisory)))
        call = 'call_boundary_' + str(index) + ('_ux' if advisory else '_formal')
        final = 'VERDICT: PASS\nFINDING_COUNTS: FIX_NOW=0 INVESTIGATE=0 OPTIONAL=0\n' + name
        child_events = fixtures._child_events(root, child, agent, str(repo), final)
        fixtures._write_jsonl(fixtures._rollout_path(home, child), child_events)
        events.extend(fixtures._spawn_events(root, child, name, agent, call))
        events.append(fixtures._delivery(agent, final))
        if advisory:
            followup = call + '_followup'
            events.extend([
                {'timestamp': '2026-08-12T04:00:00Z', 'type': 'response_item', 'payload': {
                    'type': 'function_call', 'namespace': 'collaboration', 'name': 'followup_task',
                    'call_id': followup, 'arguments': json.dumps({'target': agent, 'message': 'Repeat UX'})}},
                {'type': 'event_msg', 'payload': {'type': 'item_completed', 'item': {
                    'type': 'SubAgentActivity', 'kind': 'interacted', 'id': followup,
                    'agent_thread_id': child, 'agent_path': agent}}},
                {'type': 'response_item', 'payload': {
                    'type': 'function_call_output', 'call_id': followup, 'output': ''}},
                fixtures._delivery(agent, final),
            ])
        else:
            expected.append({'lens': lens, 'agent_id': agent,
                             'runtime_id': 'codex:' + root + ':' + call + ':' + child})
with rollout.open('a') as handle:
    for event in events:
        handle.write(json.dumps(event) + '\n')

def run():
    errors = []
    status = mod.watch(str(repo), root, registration['rollout'], registration['offset'],
                       task_id=task_id, run_id=run_id, idle_seconds=.05, recovering=True,
                       on_error=errors.append)
    assert status == 0, {'status': status, 'errors': errors}

run()
receipt_path = task / 'RECEIPTS.jsonl'
original = receipt_path.read_bytes()
rows = [json.loads(line) for line in original.splitlines()]
run()
assert receipt_path.read_bytes() == original, 'replay must not append duplicate evidence'
print(json.dumps({'rows': rows, 'expected': expected, 'run_id': run_id}))
'''


@pytest.mark.parametrize("ux", UX)
def test_real_writer_survives_interleaved_advisory_and_replay(tmp_path, ux):
    environment = dict(os.environ, HOME=str(tmp_path / "home"),
                       XDG_STATE_HOME=str(tmp_path / "state"), PYTHONDONTWRITEBYTECODE="1")
    result = subprocess.run([sys.executable, "-B", "-c", PROBE, str(REPO), str(tmp_path), ux],
                            cwd=REPO, env=environment, text=True, capture_output=True, timeout=20)
    assert result.returncode == 0, result.stderr
    output = json.loads(result.stdout)
    rows = output["rows"]
    assert len(rows) == 2 * len(FORMAL)
    assert {row["lens"] for row in rows} == set(FORMAL)
    for expected in output["expected"]:
        pair = [row for row in rows if row["runtime_id"] == expected["runtime_id"]]
        assert [(row["event"], row["verdict"]) for row in pair] == [("started", ""), ("completed", "PASS")]
        assert all(all(row[key] == value for key, value in expected.items()) for row in pair)
        assert all(row["task_run_id"] == output["run_id"] for row in pair)
