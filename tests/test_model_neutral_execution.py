"""Exercise the shipped pre-spawn hook with real task binding and no router."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / 'plugin/scripts'
sys.path.insert(0, str(SCRIPTS))
import _lib

SESSION = '019f834e-1e91-7662-9024-f548103d751e'
RUN = '01a114f8-cf7f-7084-830f-7d25fb5d30b6'


@pytest.fixture
def workspace(tmp_path):
    repo = tmp_path / 'repo'
    task = repo / 'doc/harness/tasks/TASK__neutral'
    task.mkdir(parents=True)
    (repo / '.git').mkdir()
    (repo / 'doc/harness/manifest.yaml').write_text('version: 7\nname: test\ntype: cli\n')
    (task / 'TASK.json').write_text(json.dumps(dict(run_id=RUN, execution_mode='standard',
        required_lenses=['review-code', 'qa-cli'], close_receipt_fingerprint=None)))
    markers = task.parent / '.active_sessions'
    markers.mkdir()
    (markers / f'{SESSION}.json').write_text(json.dumps(dict(session_id=SESSION,
        task_dir=str(task), task_id=task.name, run_id=RUN, updated=_lib.now_iso())))
    assert _lib.resolve_session_task_binding(str(repo), SESSION)['task_dir'] == str(task)
    return repo, task


def invoke(workspace, tmp_path, arguments, tool='collaboration.spawn_agent', response=None):
    repo, _ = workspace
    home = tmp_path / 'home'
    home.mkdir(exist_ok=True)
    env = dict(os.environ, HOME=str(home), XDG_CONFIG_HOME=str(home / 'config'),
               XDG_DATA_HOME=str(home / 'data'), XDG_CACHE_HOME=str(home / 'cache'),
               CODEX_HOME=str(home / '.codex'), PYTHONDONTWRITEBYTECODE='1')
    env.pop('CODEX_THREAD_ID', None)
    payload = dict(cwd=str(repo), session_id=SESSION, tool_name=tool, tool_input=arguments)
    script = 'hook_pre_tool_use.py'
    if response is not None:
        payload.update(tool_response={'structuredContent': response}, tool_use_id='conflicting-task')
        script = 'hook_post_tool_use.py'
    result = subprocess.run([sys.executable, str(SCRIPTS / script)],
        input=json.dumps(payload),
        env=env, cwd=repo, capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert 'Traceback' not in result.stderr
    return json.loads(result.stdout)['hookSpecificOutput'] if result.stdout.strip() else {}


@pytest.mark.parametrize('tool', ['collaboration.spawn_agent', 'collaborationspawn_agent', 'spawn_agent', 'Agent'])
@pytest.mark.parametrize('override', [{}, {'model': 'user-selected-unlisted-model', 'fork_turns': 'none'}])
def test_worker_spawn_requires_no_model_record(workspace, tmp_path, tool, override):
    repo, task = workspace
    before = (task / 'TASK.json').read_bytes()
    output = invoke(workspace, tmp_path, dict(task_name='implementation_worker') | override, tool)
    assert output.get('permissionDecision') != 'deny', output
    assert not list(repo.rglob('ROUTING*'))
    assert not list(repo.rglob('model-decisions*'))
    assert (task / 'TASK.json').read_bytes() == before
    assert not (task / 'RECEIPTS.jsonl').exists()


def test_invalid_review_identity_still_denied_without_router(workspace, tmp_path):
    output = invoke(workspace, tmp_path, dict(task_name='review_final',
                                            model='user-selected-unlisted-model', fork_turns='none'))
    assert output['permissionDecision'] == 'deny'
    assert 'review_code_<suffix>' in output['permissionDecisionReason']


def test_conflict_fence_still_prevents_receipt_binding(workspace, tmp_path):
    repo, task = workspace
    other = task.parent / 'TASK__other'
    other.mkdir()
    (other / 'TASK.json').write_bytes((task / 'TASK.json').read_bytes())
    invoke(workspace, tmp_path, {}, tool='task_start',
           response=dict(task_dir=str(other), task_id=other.name, run_id=RUN))
    marker = task.parent / '.active_sessions' / f'{SESSION}.json'
    assert len(json.loads(marker.read_text())['conflicts']) == 2
    before = marker.read_bytes()
    output = invoke(workspace, tmp_path, dict(task_name='code_review_final'))
    assert 'Conflicting task bindings prevent receipt recording' in output['additionalContext']
    assert output.get('permissionDecision') != 'deny'
    assert _lib.resolve_session_task_binding(str(repo), SESSION) == {}
    assert marker.read_bytes() == before
    assert not (task / 'RECEIPTS.jsonl').exists()
    assert not (other / 'RECEIPTS.jsonl').exists()
