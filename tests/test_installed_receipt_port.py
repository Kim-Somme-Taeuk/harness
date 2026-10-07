"""Regression contract for the installed Codex receipt protocol port."""
from __future__ import annotations

import contextlib
import io
import json
from datetime import datetime, timedelta, timezone
from unittest import mock

import pytest

import test_codex_lifecycle_watcher as lifecycle
import test_codex_hook_wrappers as hooks
import test_no_git_receipt_model as model


ROOT_ID = "019f825b-f25f-70c3-8ee8-071f79fa1c42"
CHILD_ID = "019f82a6-ce64-75a3-b01d-92f7b0b4fe6f"
TURN_ID = "019ff16c-e8de-78c3-8f18-879fd945e8bc"
NEXT_TURN = "019ff16d-e8de-78c3-8f18-879fd945e8bc"
AGENT = "/root/qa_cli_port"
FINAL = "VERDICT: PASS"


def _ordered_pair(task, lens, call, start, end, verdict="PASS"):
    runtime = f"codex:{ROOT_ID}:{call}:{CHILD_ID}"
    for event, offset in (("started", start), ("completed", end)):
        extra = {} if offset is None else {"event_order": f"codex:{ROOT_ID}:{offset}"}
        model._receipt(task, lens, call, event, verdict if event == "completed" else "",
                       source="codex_session_watcher:collaboration", runtime_id=runtime, **extra)


def _child_receipt(task, lens, call, event, offset, verdict="", **extra):
    """Keep native child identity stable while a followup changes call identity."""
    return model._receipt(
        task, lens, f"/root/{lens}", event, verdict,
        source="codex_session_watcher:collaboration",
        runtime_id=f"codex:{ROOT_ID}:{call}:{CHILD_ID}",
        event_order=f"codex:{ROOT_ID}:{offset}", **extra,
    )


@pytest.mark.parametrize("lens", ["review-code", "qa-cli"])
def test_real_gate_followup_start_and_malformed_completion_revoke_previous_pass(tmp_path, lens):
    task = model._task(tmp_path)
    for initial_lens, call, start in (("review-code", "call_review123", 10),
                                      ("qa-cli", "call_qa123456", 30)):
        _child_receipt(task, initial_lens, call, "started", start)
        _child_receipt(task, initial_lens, call, "completed", start + 10, "PASS")
    assert model.lib.receipt_runtime_verdict(task) == "PASS"

    _child_receipt(task, lens, "call_followup123", "started", 50)
    assert model.lib.receipt_runtime_verdict(task) == "PENDING"
    assert model.lib.receipt_review_verdict(task) == ("PENDING" if lens == "review-code" else "PASS")

    malformed = _child_receipt(task, lens, "call_followup123", "completed", 60,
                               summary="Finished again; no formal verdict was delivered.")
    assert malformed["verdict"] == "PENDING"
    assert model.lib.receipt_runtime_verdict(task) == "PENDING"
    assert model.lib.receipt_review_verdict(task) == ("PENDING" if lens == "review-code" else "PASS")

    # A fresh authenticated turn repairs the report; duplicate terminals in the
    # malformed generation must not be used as a substitute for another turn.
    _child_receipt(task, lens, "call_repair123", "started", 70)
    _child_receipt(task, lens, "call_repair123", "completed", 80, "PASS")
    assert model.lib.receipt_review_verdict(task) == "PASS"
    if lens == "review-code":
        assert model.lib.receipt_runtime_verdict(task) == "PENDING"
        _child_receipt(task, "qa-cli", "call_recheck123", "started", 90)
        _child_receipt(task, "qa-cli", "call_recheck123", "completed", 100, "PASS")
    assert model.lib.receipt_runtime_verdict(task) == "PASS"


@pytest.mark.parametrize("late_verdict", ["PASS", "FAIL", "BLOCKED_ENV"])
def test_real_gate_late_old_turn_cannot_finish_or_override_new_turn(tmp_path, late_verdict):
    task = model._task(tmp_path)
    _child_receipt(task, "review-code", "call_review123", "started", 10)
    _child_receipt(task, "review-code", "call_review123", "completed", 20, "PASS")
    _child_receipt(task, "qa-cli", "call_qa123456", "started", 30)
    _child_receipt(task, "qa-cli", "call_qa123456", "completed", 40, "PASS")
    assert model.lib.receipt_runtime_verdict(task) == "PASS"
    _child_receipt(task, "qa-cli", "call_delayed123", "started", 50)
    _child_receipt(task, "qa-cli", "call_current123", "started", 60)
    _child_receipt(task, "qa-cli", "call_delayed123", "completed", 70, late_verdict)
    assert model.lib.receipt_runtime_verdict(task) == "PENDING"
    _child_receipt(task, "qa-cli", "call_current123", "completed", 80, "PASS")
    assert model.lib.receipt_runtime_verdict(task) == "PASS"

    # Arrival order is not causal order: move the obsolete final to the end.
    path = task / "RECEIPTS.jsonl"
    rows = path.read_text().splitlines()
    rows.append(rows.pop(-2))
    path.write_text("\n".join(rows) + "\n")
    assert model.lib.receipt_runtime_verdict(task) == "PASS"


@pytest.mark.parametrize("order", [(2, 3, 0, 1), (3, 1, 2, 0), (1, 0, 3, 2)])
def test_native_causality_survives_receipt_append_reordering(tmp_path, order):
    task = model._task(tmp_path)
    _ordered_pair(task, "review-code", "call_review123", 10, 20)
    _ordered_pair(task, "qa-cli", "call_qa123456", 30, 40)
    path = task / "RECEIPTS.jsonl"
    lines = path.read_text().splitlines()
    path.write_text("\n".join(lines[i] for i in order) + "\n")
    assert model.lib.receipt_review_verdict(task) == "PASS"
    assert model.lib.receipt_runtime_verdict(task) == "PASS"


@pytest.mark.parametrize("origins", [(None, None, None, None), (10, 20, 30, 40)])
def test_legacy_and_native_ordered_receipts_remain_accepted(tmp_path, origins):
    task = model._task(tmp_path)
    _ordered_pair(task, "review-code", "call_review123", *origins[:2])
    _ordered_pair(task, "qa-cli", "call_qa123456", *origins[2:])
    assert model.lib.receipt_runtime_verdict(task) == "PASS"


@pytest.mark.parametrize("origins", [(10, 20, None, None), (10, 20, 20, 30),
                                     (10, 30, 20, 40), (10, 10, 30, 40)])
def test_missing_equal_or_early_origins_cannot_authorize_pass(tmp_path, origins):
    task = model._task(tmp_path)
    _ordered_pair(task, "review-code", "call_review123", *origins[:2])
    _ordered_pair(task, "qa-cli", "call_qa123456", *origins[2:])
    assert model.lib.receipt_runtime_verdict(task) == "PENDING"


def test_wrong_origin_session_cannot_authorize_pass(tmp_path):
    task = model._task(tmp_path)
    _ordered_pair(task, "review-code", "call_review123", 10, 20)
    path = task / "RECEIPTS.jsonl"
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    rows[1]["event_order"] = f"codex:{CHILD_ID}:20"
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    with pytest.raises(RuntimeError, match="entry-semantics"):
        model.lib.receipt_review_verdict(task)


@pytest.mark.parametrize("verdict", ["FAIL", "BLOCKED_ENV"])
def test_mixed_origin_stream_retains_authentic_negative(tmp_path, verdict):
    task = model._task(tmp_path)
    _ordered_pair(task, "review-code", "call_review123", 10, 20)
    _ordered_pair(task, "qa-cli", "call_qa123456", None, None, verdict)
    assert model.lib.receipt_runtime_verdict(task) == verdict


@pytest.mark.parametrize("day_delta", [-1, 0, 1])
def test_rollout_discovery_covers_unique_utc_adjacent_day(tmp_path, monkeypatch, day_delta):
    mod = lifecycle._load()
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    created = datetime.fromtimestamp(int(CHILD_ID.replace("-", "")[:12], 16) / 1000,
                                     timezone.utc) + timedelta(days=day_delta)
    path = tmp_path / "sessions" / created.strftime("%Y/%m/%d") / f"rollout-{CHILD_ID}.jsonl"
    lifecycle._write_jsonl(path, [{"type": "session_meta", "payload": {"id": CHILD_ID}}])
    assert mod._find_rollout(CHILD_ID) == path
    assert mod._find_rollout(CHILD_ID, deadline=mod.time.monotonic() - 1) is None


def _native_turn(turn_id, final=FINAL, *, complete=True):
    boundary = lifecycle._child_events(ROOT_ID, CHILD_ID, AGENT, "/unused")[-1]
    boundary["payload"]["internal_chat_message_metadata_passthrough"] = {"turn_id": turn_id}
    events = [{"timestamp": "2026-08-12T05:00:00Z", "type": "event_msg",
               "payload": {"type": "task_started", "turn_id": turn_id}}, boundary]
    if complete:
        events.extend([
            {"type": "event_msg", "payload": {"type": "agent_message", "phase": "final_answer", "message": final}},
            {"type": "event_msg", "payload": {"type": "task_complete", "turn_id": turn_id, "last_agent_message": final}},
        ])
    return events


def _native_child(repo):
    return lifecycle._child_events(ROOT_ID, CHILD_ID, AGENT, str(repo))[:1] + _native_turn(TURN_ID)


@pytest.mark.parametrize("fault", [None, "wrong_turn", "wrong_final", "incomplete"])
def test_native_child_turn_matches_completion_and_ignores_fork_history(tmp_path, monkeypatch, fault):
    mod = lifecycle._load()
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / ".codex"))
    events = _native_child(tmp_path)
    events[0]["payload"]["forked_from_id"] = ROOT_ID
    events[1:1] = _native_turn(ROOT_ID, "VERDICT: FAIL")
    if fault == "wrong_turn":
        events[-1]["payload"]["turn_id"] = NEXT_TURN
    elif fault == "wrong_final":
        events[-1]["payload"]["last_agent_message"] = "VERDICT: FAIL"
    elif fault == "incomplete":
        events.pop()
    child = lifecycle._rollout_path(tmp_path / ".codex", CHILD_ID)
    lifecycle._write_jsonl(child, events)
    status, _, final = mod._child_status(CHILD_ID, ROOT_ID, AGENT, str(tmp_path))
    assert status == ("complete" if fault is None else "running" if fault == "incomplete" else "invalid")
    if fault is None:
        assert final == FINAL


@pytest.mark.parametrize("fault", [None, "missing_activity", "wrong_child", "duplicate_activity", "nonempty_output"])
def test_followup_fences_old_pass_and_requires_authenticated_new_turn(tmp_path, monkeypatch, fault):
    mod = lifecycle._load()
    home = tmp_path / ".codex"
    monkeypatch.setenv("CODEX_HOME", str(home))
    task = model._task(tmp_path)
    lifecycle._write_task_control(task)
    child = lifecycle._rollout_path(home, CHILD_ID)
    events = _native_child(tmp_path)
    lifecycle._write_jsonl(child, events)
    rows = []

    def record(_task, receipt):
        row = dict(receipt)
        rows.append(row)
        return row

    monkeypatch.setattr(mod, "_active_task_binding_for_session", lambda *_: lifecycle._active_binding(task))
    monkeypatch.setattr(mod, "record_subagent_receipt", record)
    monkeypatch.setattr(mod, "receipt_snapshot", lambda *_: lifecycle._snapshot(rows))
    watcher = mod.Watcher(str(tmp_path), ROOT_ID)
    spawn = lifecycle._spawn_events(ROOT_ID, CHILD_ID, "qa_cli_port", AGENT)
    for i, event in enumerate(spawn):
        watcher.feed(event, origin_offset=10 + i * 10)
    watcher.feed(lifecycle._delivery(AGENT, FINAL), origin_offset=40)
    assert rows[-1]["verdict"] == "PASS"
    assert rows[0]["event_order"] == f"codex:{ROOT_ID}:10"
    assert rows[-1]["event_order"] == f"codex:{ROOT_ID}:40"
    first_runtime = rows[-1]["runtime_id"]
    call = {"timestamp": "2026-08-12T04:00:00Z", "type": "response_item", "payload": {
        "type": "function_call", "namespace": "collaboration", "name": "followup_task",
        "call_id": "call_followup123", "arguments": json.dumps({"target": AGENT, "message": "Repeat QA"}),
    }}
    activity = {"type": "event_msg", "payload": {"type": "item_completed", "item": {
        "type": "SubAgentActivity", "kind": "interacted", "id": "call_followup123",
        "agent_thread_id": ROOT_ID if fault == "wrong_child" else CHILD_ID, "agent_path": AGENT,
    }}}
    output = {"type": "response_item", "payload": {"type": "function_call_output",
        "call_id": "call_followup123", "output": "unexpected" if fault == "nonempty_output" else ""}}
    watcher.feed(call, origin_offset=50)
    if fault != "missing_activity":
        watcher.feed(activity, origin_offset=60)
        if fault == "duplicate_activity":
            watcher.feed(activity, origin_offset=65)
    watcher.feed(output, origin_offset=70)
    assert rows[-1].get("verdict") != "PASS"
    lifecycle._write_jsonl(child, events + _native_turn(NEXT_TURN))
    watcher.feed(lifecycle._delivery(AGENT, FINAL), origin_offset=80)
    if fault is None:
        assert rows[-1]["verdict"] == "PASS"
        assert rows[-1]["runtime_id"] != first_runtime
        assert rows[-1]["event_order"] == f"codex:{ROOT_ID}:80"
        count = len(rows)
        replay = mod.Watcher(str(tmp_path), ROOT_ID)
        for i, event in enumerate(spawn):
            replay.feed(event, origin_offset=10 + i * 10)
        replay.feed(lifecycle._delivery(AGENT, FINAL), origin_offset=40)
        for offset, event in [(50, call), (60, activity), (70, output), (80, lifecycle._delivery(AGENT, FINAL))]:
            replay.feed(event, origin_offset=offset)
        assert len(rows) == count
    else:
        assert rows[-1].get("verdict") != "PASS"


def test_registration_reports_observed_conflict_without_attempting_ensure(tmp_path, monkeypatch):
    mod = hooks._load("codex_hook_registration")
    monkeypatch.delenv("CODEX_THREAD_ID", raising=False)
    status = {}
    monkeypatch.setattr(mod, "find_harness_root", lambda _: str(tmp_path))
    monkeypatch.setattr(mod, "_bound_workspace_roots", lambda *_: None)
    with mock.patch.object(mod, "_ensure_with_deadline") as ensure:
        assert not mod.restore_watcher_registration(
            json.dumps({"cwd": str(tmp_path), "session_id": ROOT_ID}).encode(), status_out=status)
    assert status["status"] == "binding_conflict"
    ensure.assert_not_called()


@pytest.mark.parametrize("hook", ["hook_pre_tool_use", "hook_post_tool_use"])
def test_binding_conflict_hook_explains_recovery_and_remains_fail_open(monkeypatch, hook):
    mod = hooks._load(hook)

    def conflict(_payload, **kwargs):
        kwargs["status_out"].update(status="binding_conflict", reason="conflicting workspace bindings")
        return False

    callback = "restore_watcher_registration" if hook == "hook_pre_tool_use" else "register_task_result"
    monkeypatch.setattr(mod, callback, conflict)
    if hook == "hook_pre_tool_use":
        monkeypatch.setattr(mod, "_update_diagnostics", lambda *_: None)
    payload = {"cwd": str(hooks.REPO_ROOT), "session_id": ROOT_ID,
               "tool_name": "collaboration.spawn_agent" if hook == "hook_pre_tool_use" else "mcp__harness__task_context",
               "tool_input": {"task_name": "qa_cli_port"}, "tool_response": {}}
    monkeypatch.setattr("sys.stdin", hooks._BytesStdin(json.dumps(payload)))
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        assert mod.main() == 0
    data = json.loads(output.getvalue())["hookSpecificOutput"]
    assert "permissionDecision" not in data
    guidance = data["additionalContext"]
    assert "task_context" in guidance and "task_start" in guidance
    assert "future starts" in guidance and "non-attesting" in guidance
    assert "timeout" not in guidance.lower()
