"""Context inspection must never admit a session or revoke receipt ownership."""
import json
from pathlib import Path
from unittest import mock

import pytest

from test_worktree_workspace import _call, _payload, _repo, _snapshot, _worktree
from test_codex_worktree_receipts import _conflict_task, ROOT, LEAD
from test_codex_hook_wrappers import _load


CONTEXT_TOOLS = (
    "task_context", "mcp__harness__task_context",
    "mcp__plugin_harness_harness__task_context",
)


@pytest.fixture(autouse=True)
def isolated_session_environment(monkeypatch):
    for key in ("CODEX_THREAD_ID", "CODEX_SESSION_ID", "HARNESS_SESSION_ID", "CLAUDE_SESSION_ID"):
        monkeypatch.delenv(key, raising=False)


def _hook_payload(repo, task, session=ROOT, tool="mcp__harness__task_start", tool_input=None):
    return json.dumps({"cwd": str(repo), "thread_id": session,
        "tool_name": tool, "tool_input": tool_input or {},
        "tool_response": {"structuredContent": task}}).encode()


@pytest.mark.parametrize("context_tool", CONTEXT_TOOLS)
def test_context_a_then_start_b_binds_only_b(tmp_path, monkeypatch, context_tool):
    repo = _repo(tmp_path / "repo")
    monkeypatch.setenv("HARNESS_RUNTIME", "codex")
    monkeypatch.delenv("CODEX_THREAD_ID", raising=False)
    monkeypatch.delenv("CODEX_SESSION_ID", raising=False)
    a = _conflict_task(repo, "TASK__a")
    b = _conflict_task(repo, "TASK__b")
    hook = _load("codex_hook_registration")
    before = _snapshot(repo)
    context = _call(repo, "task_context", {"task_id": a["task_id"]})
    assert not context.get("isError"), context
    with mock.patch.object(hook, "_ensure_with_deadline", return_value=True):
        assert not hook.register_task_result(_hook_payload(repo, _payload(context), tool=context_tool))
        assert _snapshot(repo) == before
        assert hook.register_task_result(_hook_payload(repo, b))
    assert hook.resolve_session_task_binding(str(repo), ROOT)["task_dir"] == b["task_dir"]
    assert "conflicts" not in hook.read_active_session_marker(str(repo), ROOT)


def test_independent_root_sessions_inspect_then_start_separate_tasks(tmp_path, monkeypatch):
    repo = _repo(tmp_path / "repo")
    monkeypatch.setenv("HARNESS_RUNTIME", "codex")
    hook = _load("codex_hook_registration")
    a, b = (_conflict_task(repo, "TASK__" + name) for name in ("a", "b"))
    with mock.patch.object(hook, "_ensure_with_deadline", return_value=True):
        for session, inspected, started in ((ROOT, b, a), (LEAD, a, b)):
            assert not hook.register_task_result(_hook_payload(repo, inspected, session, CONTEXT_TOOLS[1]))
            assert hook.register_task_result(_hook_payload(repo, started, session))
    assert hook.resolve_session_task_binding(str(repo), ROOT)["task_dir"] == a["task_dir"]
    assert hook.resolve_session_task_binding(str(repo), LEAD)["task_dir"] == b["task_dir"]


@pytest.mark.parametrize("workspace", [False, True])
@pytest.mark.parametrize("marker_kind", ["exact", "default", "fence", "overflow"])
def test_direct_and_hook_context_preserve_all_focus_and_registration(
    tmp_path, monkeypatch, workspace, marker_kind,
):
    repo = _repo(tmp_path / "repo")
    target = _worktree(repo, "lead") if workspace else repo
    monkeypatch.setenv("HARNESS_RUNTIME", "codex")
    monkeypatch.setenv("CODEX_THREAD_ID", ROOT)
    monkeypatch.setenv("CODEX_SESSION_ID", ROOT)
    hook = _load("codex_hook_registration")
    owned = _conflict_task(repo, "TASK__owned")
    other = _conflict_task(target, "TASK__other")
    markers = repo / "doc/harness/tasks/.active_sessions"
    markers.mkdir(exist_ok=True)
    value = dict(owned, session_id=ROOT)
    if marker_kind == "fence":
        value = {"session_id": ROOT, "conflicts": [owned, other]}
    elif marker_kind == "overflow":
        value = {"session_id": ROOT, "conflicts": [], "conflicts_overflow": True}
    (markers / f"{ROOT}.json").write_text(json.dumps(value))
    (markers / "default.json").write_text(json.dumps(dict(owned, session_id="default")))
    (repo / "doc/harness/tasks/.active").write_text(owned["task_dir"] + "\n")
    if marker_kind == "default":
        monkeypatch.delenv("CODEX_THREAD_ID")
        monkeypatch.delenv("CODEX_SESSION_ID")
        monkeypatch.delenv("HARNESS_SESSION_ID", raising=False)
        monkeypatch.delenv("CLAUDE_SESSION_ID", raising=False)
    before = (_snapshot(repo), _snapshot(target))
    args = {"task_id": other["task_id"]}
    if workspace:
        args["workspace"] = str(target)
    with mock.patch.object(hook, "invalidate_registration") as invalidate, \
            mock.patch.object(hook, "_ensure_with_deadline") as ensure:
        context = _call(repo, "task_context", args)
        assert not context.get("isError"), context
        assert not hook.register_task_result(_hook_payload(
            repo, _payload(context), tool=CONTEXT_TOOLS[1], tool_input=args,
        ))
        invalidate.assert_not_called()
        ensure.assert_not_called()
    assert (_snapshot(repo), _snapshot(target)) == before


def test_real_conflicting_starts_still_fence(tmp_path):
    repo = _repo(tmp_path / "repo")
    hook = _load("codex_hook_registration")
    a, b = (_conflict_task(repo, "TASK__" + name) for name in ("a", "b"))
    with mock.patch.object(hook, "_ensure_with_deadline", return_value=True):
        assert hook.register_task_result(_hook_payload(repo, a))
        assert not hook.register_task_result(_hook_payload(repo, b))
    assert hook.resolve_session_task_binding(str(repo), ROOT) == {}
    assert {item["task_id"] for item in hook.read_active_session_marker(str(repo), ROOT)["conflicts"]} == {a["task_id"], b["task_id"]}


def test_unrelated_context_preserves_real_watcher_registration(tmp_path, monkeypatch):
    from test_codex_lifecycle_watcher import _write_exact_session_binding, _rollout_path, _write_jsonl
    from test_worktree_workspace import harness_server
    import codex_lifecycle_watcher as watcher

    repo = _repo(tmp_path / "repo")
    home = tmp_path / "codex"
    monkeypatch.setenv("CODEX_HOME", str(home))
    monkeypatch.setenv("HARNESS_RUNTIME", "codex")
    monkeypatch.setenv("CODEX_THREAD_ID", ROOT)
    monkeypatch.setattr(harness_server, "_server_runtime", lambda: "codex")
    monkeypatch.setattr(harness_server, "_SERVER", None)
    task_id, _ = _write_exact_session_binding(repo, ROOT)
    task_dir = str(repo / "doc/harness/tasks" / task_id)
    _write_jsonl(_rollout_path(home, ROOT), [{"type": "session_meta", "payload": {
        "id": ROOT, "session_id": ROOT, "cwd": str(repo), "thread_source": "user",
    }}])
    registration = harness_server._register_task_start_watcher(
        str(repo), task_dir, harness_server.read_task_control(task_dir),
    )
    assert registration["registered"], registration
    before_registration = watcher.registrations(str(repo))
    assert len(before_registration) == 1
    state_path = watcher._state_path(str(repo), ROOT)
    before_state = state_path.read_bytes()
    other = _conflict_task(repo, "TASK__other")
    before_tasks = _snapshot(repo)
    context = _call(repo, "task_context", {"task_id": other["task_id"]})
    assert not context.get("isError"), context
    hook = _load("codex_hook_registration")
    assert not hook.register_task_result(_hook_payload(repo, _payload(context), tool=CONTEXT_TOOLS[1]))
    assert state_path.read_bytes() == before_state
    assert watcher.registrations(str(repo)) == before_registration
    assert _snapshot(repo) == before_tasks


def test_closed_context_does_not_reopen_or_bind(tmp_path, monkeypatch):
    repo = _repo(tmp_path / "repo")
    monkeypatch.setenv("HARNESS_RUNTIME", "codex")
    monkeypatch.setenv("CODEX_THREAD_ID", ROOT)
    task = _conflict_task(repo, "TASK__closed")
    from test_worktree_workspace import lib
    control_path = Path(task["task_dir"]) / "TASK.json"
    control = json.loads(control_path.read_text())
    control["close_receipt_fingerprint"] = lib.receipt_stream_fingerprint(task["task_dir"])
    control_path.write_text(json.dumps(control))
    assert lib.task_control_status(task["task_dir"]) == "closed"
    before = _snapshot(repo)
    result = _call(repo, "task_context", {"task_id": task["task_id"]})
    assert not result.get("isError"), result
    assert _snapshot(repo) == before
    hook = _load("codex_hook_registration")
    assert hook.resolve_session_task_binding(str(repo), ROOT) == {}
