"""Task-local model decisions consumed by the Codex pre-spawn gate.

These records explain dispatch; they never authorize task completion or receipts.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile

from model_routing import route
from failure_handoff import history


def control(task_dir):
    from _lib import read_task_control, task_control_status
    path = Path(task_dir).resolve()
    data = read_task_control(str(path))
    if not data or task_control_status(str(path), data) != 'open':
        raise ValueError('routing requires an open Harness task')
    return path, data


def calculate(task_dir, request):
    task, state = control(task_dir)
    if not isinstance(request, dict) or set(request) != {'worker', 'ac_id', 'issue_id', 'reason', 'assessment'}:
        raise ValueError('routing request requires worker/ac_id/issue_id/reason/assessment')
    for key in ('worker', 'ac_id', 'issue_id', 'reason'):
        if not isinstance(request[key], str) or not request[key].strip():
            raise ValueError(f'{key} must be nonblank')
    if not re.fullmatch(r'[a-z0-9_]+', request['worker']):
        raise ValueError('worker must be a native task_name')
    assessment = request['assessment']
    if not isinstance(assessment, dict) or set(assessment) - {'impact', 'recovery', 'available_models'}:
        raise ValueError('assessment may only contain impact/recovery/available_models')
    # Canonical task layout: <repo>/doc/harness/tasks/TASK__id.
    if task.parent.name != 'tasks' or task.parent.parent.name != 'harness' or task.parent.parent.parent.name != 'doc':
        raise ValueError('task_dir must be in doc/harness/tasks')
    identity = dict(task_id=task.name, run_id=state['run_id'], ac_id=request['ac_id'], issue_id=request['issue_id'])
    records = history(task.parent.parent / 'handoffs', identity)
    decision = route(assessment | {'failed_attempts': len(records)})
    return dict(decision, worker=request['worker'], ac_id=request['ac_id'], issue_id=request['issue_id'],
                reason=decision.get('reason', request['reason']), assessment=assessment, task_id=task.name, run_id=state['run_id'],
                risk=decision['failure_cost'], model=decision.get('spawn_args', {}).get('model'),
                failed_attempts=len(records), handoff_paths=[str(p.resolve()) for p, _ in records])


def decision_path(task, worker):
    return task / 'ROUTING' / (hashlib.sha256(worker.encode()).hexdigest() + '.json')


def prepare(task_dir, session_id, request):
    if not isinstance(session_id, str) or not session_id.strip():
        raise ValueError('session_id required')
    decision = calculate(task_dir, request)
    if decision['action'] != 'spawn':
        return decision
    task, _ = control(task_dir)
    return persist(decision_path(task, request['worker']), session_id, request, decision)


def persist(target, session_id, request, decision, **context):
    if target.parent.is_symlink():
        raise ValueError('symlink routing directory refused')
    target.parent.mkdir(parents=True, exist_ok=True)
    record = {'session_id': session_id, 'request': request, 'decision': decision, **context}
    if target.exists() or target.is_symlink():
        if target.is_symlink() or json.loads(target.read_text()) != record:
            raise ValueError('worker name already has another decision; use a new name')
    else:
        fd, temporary = tempfile.mkstemp(prefix='.routing-', dir=target.parent)
        try:
            with os.fdopen(fd, 'w') as stream:
                json.dump(record, stream, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            os.link(temporary, target)
        finally:
            os.unlink(temporary)
    return decision | {'routing_path': str(target)}


def batch_decision(repo, batch_id, slug, request):
    # Bootstrap precedes task_start; bind to the real reserved claim instead.
    import batch_state
    repo = str(Path(repo).resolve())
    directory = str(Path(repo) / 'doc/harness/runtime/batches')
    batch_state.parents(directory)
    records = batch_state.load_all(directory, repo)
    batch = records.get(batch_id, {})
    if batch.get('status') != 'open' or batch.get('halted'):
        raise ValueError('batch is not open for bootstrap')
    item = next((r for r in batch.get('requests', []) if r['slug'] == slug), {})
    if item.get('status') != 'reserved' or not item.get('reserved_at'):
        raise ValueError('bootstrap requires a current reserved claim')
    batch_state.no_main_task(repo)
    if not isinstance(request, dict) or set(request) != {'worker','ac_id','issue_id','reason','assessment'}:
        raise ValueError('invalid bootstrap routing request')
    if request['ac_id'] != 'task' or not isinstance(request['worker'], str) or not re.fullmatch(r'[a-z0-9_]+', request['worker']):
        raise ValueError('bootstrap requires ac_id=task and native worker name')
    if any(not isinstance(request[k], str) or not request[k].strip() for k in ('issue_id','reason')):
        raise ValueError('bootstrap requires issue and reason')
    assessment = request['assessment']
    if not isinstance(assessment, dict) or set(assessment) - {'impact','recovery','available_models'}:
        raise ValueError('invalid bootstrap assessment')
    records = []
    run_id = None
    worktree_head = None
    if item.get('resuming'):
        worktree_head = batch_state.bound(repo, item)
        run_id = batch_state.resume_control(item)
        if run_id:
            identity = dict(task_id=item['task_id'], run_id=run_id, ac_id='task', issue_id=request['issue_id'])
            records = history(Path(item['worktree']) / 'doc/harness/handoffs', identity)
    decision = route(assessment | {'failed_attempts': len(records)})
    return dict(decision, worker=request['worker'], task_id=item['task_id'], ac_id='task',
                batch_id=batch_id, slug=slug, reserved_at=item['reserved_at'], spawn_head=item['spawn_head'],
                issue_id=request['issue_id'], run_id=run_id, resuming=bool(item.get('resuming')),
                worktree=item.get('worktree'), branch=item.get('branch'), previous_worker=item.get('worker_id'),
                worktree_head=worktree_head, failed_attempts=len(records),
                handoff_paths=[str(p.resolve()) for p, _ in records],
                risk=decision['failure_cost'], model=decision.get('spawn_args',{}).get('model'),
                reason=decision.get('reason',request['reason']), assessment=assessment)


def bootstrap_path(repo, worker):
    return Path(repo) / 'doc/harness/runtime/model-routing' / (hashlib.sha256(worker.encode()).hexdigest()+'.json')


def prepare_batch(repo, batch_id, slug, session_id, request):
    if not isinstance(session_id, str) or not session_id.strip():
        raise ValueError('session_id required')
    decision = batch_decision(repo,batch_id,slug,request)
    if decision['action'] != 'spawn':
        return decision
    return persist(bootstrap_path(repo,request['worker']),session_id,request,decision,
                   batch_id=batch_id,slug=slug)


def validate_bootstrap(repo, session_id, arguments):
    if not isinstance(arguments.get('task_name'), str):
        raise ValueError('native task_name required')
    target = bootstrap_path(repo,arguments['task_name'])
    if target.is_symlink() or target.parent.is_symlink():
        raise ValueError('symlink bootstrap record refused')
    record = json.loads(target.read_text())
    if record['session_id'] != session_id or record['request']['worker'] != arguments['task_name']:
        raise ValueError('bootstrap session/worker mismatch')
    current = batch_decision(repo,record['batch_id'],record['slug'],record['request'])
    if current != record['decision'] or current['action'] != 'spawn':
        raise ValueError('stale bootstrap reservation')
    if arguments.get('model') != current['model'] or arguments.get('fork_turns') != 'none':
        raise ValueError('bootstrap model/fork must match router')
    return current


def validate_spawn(task_dir, session_id, arguments):
    task, _ = control(task_dir)
    if not isinstance(arguments, dict) or not isinstance(arguments.get('task_name'), str):
        raise ValueError('native spawn task_name is required')
    target = decision_path(task, arguments['task_name'])
    if target.is_symlink() or target.parent.is_symlink():
        raise ValueError('symlink routing record refused')
    record = json.loads(target.read_text())
    if not isinstance(record, dict) or record.get('session_id') != session_id:
        raise ValueError('routing decision belongs to another session')
    request = record['request']
    if request['worker'] != arguments['task_name']:
        raise ValueError('routing decision belongs to another worker')
    current = calculate(task, request)
    if current != record['decision'] or current['action'] != 'spawn':
        raise ValueError('stale routing decision: run, assessment or failure history changed')
    if arguments.get('model') != current['model']:
        raise ValueError(f"model must match router: {current['model']}")
    if arguments.get('fork_turns') != current['spawn_args']['fork_turns']:
        raise ValueError('routed spawn requires fork_turns=none and explicit handoff')
    return current


def gate(payload):
    """Return a deny reason, or empty string for a permitted/non-Harness spawn."""
    from _lib import find_harness_root, resolve_session_task_binding, _infer_receipt_lens
    root = find_harness_root(payload.get('cwd', ''))
    if not root:
        return ''
    arguments = next((payload[k] for k in ('tool_input', 'input', 'arguments') if k in payload), {})
    if isinstance(arguments, str):
        arguments = json.loads(arguments)
    if not isinstance(arguments, dict):
        raise ValueError('spawn arguments must be an object')
    # Existing independently attested review/QA roles retain their model policy.
    lens = _infer_receipt_lens(arguments.get('task_name', ''))
    if lens and (lens.startswith('review-') or lens.startswith('qa-')):
        return ''
    session = payload.get('session_id') or payload.get('thread_id') or os.environ.get('CODEX_THREAD_ID', '')
    from codex_lifecycle_watcher import workspace_roots
    roots = workspace_roots(root)
    if not roots:
        raise ValueError('workspace enumeration unavailable')
    bindings = [binding for workspace in roots
                if (binding := resolve_session_task_binding(workspace, session))]
    if len(bindings) > 1:
        raise ValueError('multiple workspaces bind this session')
    if not bindings:
        validate_bootstrap(root, session, arguments)
        return ''
    validate_spawn(bindings[0]['task_dir'], session, arguments)
    return ''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--task-dir')
    mode.add_argument('--batch-repo')
    parser.add_argument('--batch-id')
    parser.add_argument('--slug')
    parser.add_argument('--session-id', required=True)
    args = parser.parse_args()
    try:
        request = json.load(sys.stdin)
        result = (prepare(args.task_dir, args.session_id, request) if args.task_dir else
                  prepare_batch(args.batch_repo,args.batch_id,args.slug,args.session_id,request))
    except (ValueError, TypeError, KeyError, OSError, RuntimeError) as exc:
        print(json.dumps({'action': 'blocked', 'reason': str(exc)}))
        return 2
    print(json.dumps(result))
    return 0 if result['action'] == 'spawn' else 1


if __name__ == '__main__':
    sys.exit(main())
