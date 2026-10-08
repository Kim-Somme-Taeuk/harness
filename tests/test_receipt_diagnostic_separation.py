"""AC-001: diagnostic detail never grants receipt or session authority."""
from __future__ import annotations

from types import SimpleNamespace
from unittest import mock


ROOT = "019f825b-f25f-70c3-8ee8-071f79fa1c42"
OTHER_ROOT = "019f825b-f25f-70c3-8ee8-071f79fa1c43"
CHILD = "019f82a6-ce64-75a3-b01d-92f7b0b4fe6f"
RUN = "019feefa-2a00-7000-8000-000000000001"


def _pair(model, task, lens, offsets, verdict="PASS", root=ROOT):
    for event, offset in zip(("started", "completed"), offsets):
        extra = {} if offset is None else {"event_order": f"codex:{root}:{offset}"}
        model._receipt(
            task, lens, lens, event, verdict if event == "completed" else "",
            source="codex_session_watcher:collaboration",
            runtime_id=f"codex:{root}:call_{lens.replace('-', '')}:{CHILD}", **extra,
        )


def test_paired_mixed_origin_is_ordering_not_missing_start(tmp_path):
    import test_no_git_receipt_model as model

    task = model._task(tmp_path)
    _pair(model, task, "review-code", (10, None))
    assert model.lib.nonparsing_completion_lenses(task) == {"review-code": "ordering"}
    assert model.lib.receipt_runtime_verdict(task) == "PENDING"


def test_equal_and_reversed_pair_orders_remain_non_attesting(tmp_path):
    import test_no_git_receipt_model as model

    for index, offsets in enumerate(((10, 10), (20, 10))):
        task = model._task(tmp_path / str(index))
        _pair(model, task, "review-code", offsets)
        assert model.lib.nonparsing_completion_lenses(task) == {"review-code": "ordering"}
        assert model.lib.receipt_runtime_verdict(task) == "PENDING"


def test_individually_valid_pairs_with_incomparable_origins_are_diagnosed(tmp_path):
    import test_no_git_receipt_model as model

    for index, (offsets, root) in enumerate((((None, None), ROOT), ((30, 40), OTHER_ROOT))):
        task = model._task(tmp_path / str(index))
        _pair(model, task, "review-code", (10, 20))
        _pair(model, task, "qa-cli", offsets, root=root)
        assert model.lib.nonparsing_completion_lenses(task) == {
            "qa-cli": "ordering", "review-code": "ordering",
        }
        assert model.lib.receipt_runtime_verdict(task) == "PENDING"


def test_missing_start_and_duplicate_completion_still_report_unpaired(tmp_path):
    import test_no_git_receipt_model as model

    for defect in ("missing", "duplicate"):
        task = model._task(tmp_path / defect)
        _pair(model, task, "review-code", (10, 20))
        path = task / "RECEIPTS.jsonl"
        rows = path.read_text().splitlines()
        path.write_text("\n".join(rows[1:] if defect == "missing" else rows + rows[1:]) + "\n")
        assert model.lib.nonparsing_completion_lenses(task) == {"review-code": "unpaired"}
        assert model.lib.receipt_runtime_verdict(task) == "PENDING"


def test_order_diagnostics_do_not_weaken_negative_verdicts(tmp_path):
    import test_no_git_receipt_model as model

    for lens in ("review-code", "qa-cli"):
        for verdict in ("FAIL", "BLOCKED_ENV"):
            task = model._task(tmp_path / lens / verdict)
            _pair(model, task, lens, (10, None), verdict)
            before = model.lib.receipt_runtime_verdict(task)
            model.lib.nonparsing_completion_lenses(task)
            assert before == verdict
            assert model.lib.receipt_runtime_verdict(task) == verdict


def test_legacy_and_causal_pass_paths_are_unchanged(tmp_path):
    import test_no_git_receipt_model as model

    for index, offsets in enumerate(((None, None, None, None), (10, 20, 30, 40))):
        task = model._task(tmp_path / str(index))
        _pair(model, task, "review-code", offsets[:2])
        _pair(model, task, "qa-cli", offsets[2:])
        assert model.lib.nonparsing_completion_lenses(task) == {}
        assert model.lib.receipt_runtime_verdict(task) == "PASS"


def _manager(tmp_path):
    import test_codex_lifecycle_watcher as lifecycle

    mod = lifecycle._load()
    (tmp_path / ".git").mkdir(exist_ok=True)
    return mod, mod.WatcherManager(str(tmp_path))


def _observe(manager, repo, thread, *, task="TASK__x", run=RUN, alive=False, result=None):
    generation = ("/rollout", 10, 1.0, task, run)
    manager.worker_observations[thread] = (generation, str(repo.resolve()))
    manager.seen[thread] = generation
    if alive:
        manager.worker_generations[thread] = generation
        manager.workers[thread] = SimpleNamespace(is_alive=lambda: True)
    if result is not None:
        manager.worker_results[thread] = result
        manager.worker_result_generations[thread] = generation


def test_task_snapshot_filters_exact_repo_task_run_and_lists_multiple_workers(tmp_path):
    _, manager = _manager(tmp_path)
    _observe(manager, tmp_path, ROOT, alive=True)
    _observe(manager, tmp_path, OTHER_ROOT, alive=True)
    _observe(manager, tmp_path, "stale-run", run="old")
    _observe(manager, tmp_path, "other-task", task="TASK__other")
    _observe(manager, tmp_path / "other", "foreign-repo")
    result = manager.task_worker_status(str(tmp_path), "TASK__x", RUN)
    assert result["scope"] == "process-local"
    assert result["advisory"] is True
    assert result["status"] == "running"
    assert {row["thread_id"] for row in result["workers"]} == {ROOT, OTHER_ROOT}
    assert all(row["status"] == "running" for row in result["workers"])
    assert result["limitation"]


def test_task_snapshot_retains_cleaned_up_success_and_failure(tmp_path):
    _, manager = _manager(tmp_path)
    _observe(manager, tmp_path, ROOT, result=0)
    _observe(manager, tmp_path, OTHER_ROOT, result=4)
    # scan_once removes failed generations from seen; observations must survive.
    manager.seen.pop(OTHER_ROOT)
    manager.worker_errors[OTHER_ROOT] = "failure\n\t" + "x" * 1000
    manager.worker_error_generations[OTHER_ROOT] = manager.worker_observations[OTHER_ROOT][0]
    result = manager.task_worker_status(str(tmp_path), "TASK__x", RUN)
    workers = {row["thread_id"]: row for row in result["workers"]}
    assert workers[ROOT]["status"] == "exited"
    assert workers[OTHER_ROOT]["status"] == "failed"
    error = workers[OTHER_ROOT]["error"]
    assert len(error) <= 320 and "\n" not in error and "\t" not in error


def test_task_snapshot_unknown_and_output_bound(tmp_path):
    _, manager = _manager(tmp_path)
    for identity in (("", "TASK__x", RUN), (str(tmp_path), "", RUN),
                     (str(tmp_path), "TASK__x", ""), (str(tmp_path), "TASK__x", RUN)):
        result = manager.task_worker_status(*identity)
        assert result["status"] == "unknown"
        assert result["workers"] == []
    _observe(manager, tmp_path, ROOT)
    assert manager.task_worker_status(str(tmp_path), "TASK__x", RUN)["workers"][0]["status"] == "unknown"
    for index in range(40):
        _observe(manager, tmp_path, f"worker-{index}", result=4)
        manager.worker_errors[f"worker-{index}"] = "e" * 10000
        manager.worker_error_generations[f"worker-{index}"] = manager.worker_observations[f"worker-{index}"][0]
    result = manager.task_worker_status(str(tmp_path), "TASK__x", RUN)
    assert len(result["workers"]) <= 32
    assert result["truncated"] is True
    assert all(len(row["error"]) <= 320 for row in result["workers"])


def test_manager_records_worker_observation_through_scan_and_cleanup(tmp_path):
    mod, manager = _manager(tmp_path)
    registration = {"thread_id": ROOT, "rollout": "/rollout", "offset": 10,
                    "registered_at": 1.0, "task_id": "TASK__x", "run_id": RUN}
    lease = SimpleNamespace(close=mock.Mock())
    with mock.patch.object(mod, "workspace_roots", return_value=[str(tmp_path)]), \
         mock.patch.object(mod, "registrations", return_value=[registration]), \
         mock.patch.object(mod, "_acquire_registration_lease", return_value=lease), \
         mock.patch.object(mod, "watch", return_value=0):
        assert manager.scan_once() == 1
        manager.workers[ROOT].join(timeout=2)
        assert not manager.workers[ROOT].is_alive()
        assert manager.scan_once() == 0
    assert ROOT not in manager.workers
    result = manager.task_worker_status(str(tmp_path), "TASK__x", RUN)
    assert result["status"] == "exited"
    assert result["workers"][0]["thread_id"] == ROOT
    lease.close.assert_called_once()


def test_refreshed_generation_preserves_recovery_but_hides_old_diagnostics(tmp_path):
    import threading

    mod, manager = _manager(tmp_path)
    registration = {"thread_id": ROOT, "rollout": "/rollout", "offset": 10,
                    "registered_at": 1.0, "task_id": "TASK__x", "run_id": RUN}
    entered, release = threading.Event(), threading.Event()
    recovery = []

    def watch(*args, recovering, on_error, **kwargs):
        if args[3] == 10:
            return 4
        recovery.append((recovering, manager.worker_error(ROOT), manager.worker_results[ROOT]))
        entered.set()
        release.wait(5)
        on_error("")
        return 0

    with mock.patch.object(mod, "workspace_roots", return_value=[str(tmp_path)]), \
         mock.patch.object(mod, "registrations", side_effect=lambda *_: [registration.copy()]), \
         mock.patch.object(mod, "_acquire_registration_lease", side_effect=lambda *_: SimpleNamespace(close=lambda: None)), \
         mock.patch.object(mod, "watch", side_effect=watch):
        assert manager.scan_once() == 1
        manager.workers[ROOT].join(timeout=2)
        assert manager.worker_results[ROOT] == 4
        registration.update(offset=20, registered_at=2.0)
        assert manager.scan_once() == 1
        worker = manager.workers[ROOT]
        try:
            assert entered.wait(2)
            assert recovery == [(True, "watcher exited with status 4", 4)]
            result = manager.task_worker_status(str(tmp_path), "TASK__x", RUN)
            assert result["status"] == "running"
            assert result["workers"][0]["error"] == ""
            # A stale terminal result cannot describe the fresh generation even
            # when it has no live worker observation (e.g. during cleanup).
            with manager._lock:
                manager.workers.pop(ROOT)
            result = manager.task_worker_status(str(tmp_path), "TASK__x", RUN)
            assert result["status"] == "unknown"
            assert result["workers"][0]["error"] == ""
        finally:
            release.set()
            worker.join(timeout=2)
        assert not worker.is_alive()
    assert manager.task_worker_status(str(tmp_path), "TASK__x", RUN)["status"] == "exited"


def test_binding_conflicts_survive_watch_notification_and_manager_result(tmp_path):
    import test_codex_lifecycle_watcher as lifecycle

    mod, manager = _manager(tmp_path)
    rollout = lifecycle._rollout_path(tmp_path / ".codex", ROOT)
    lifecycle._write_jsonl(rollout, [{"type": "session_meta", "payload": {
        "session_id": ROOT, "id": ROOT, "cwd": str(tmp_path), "thread_source": "user",
    }}])
    registration = {"thread_id": ROOT, "rollout": str(rollout),
                    "offset": rollout.stat().st_size, "registered_at": 1.0,
                    "repo_root": str(tmp_path), "task_id": "TASK__x", "run_id": RUN}
    generation = mod._registration_generation(registration)
    manager.worker_observations[ROOT] = (generation, str(tmp_path.resolve()))
    reasons = ("binding unavailable", "unacknowledged coordinator conflict fence",
               "conflicting workspace bindings", "workspace binding unavailable",
               "untrusted arbitrary exception text")
    for reason in reasons:
        lease = SimpleNamespace(close=mock.Mock())
        with mock.patch.object(mod, "_sessions_root", return_value=tmp_path / ".codex/sessions"), \
             mock.patch.object(mod, "_find_rollout", return_value=rollout), \
             mock.patch.object(mod, "_require_task_binding", side_effect=mod._BindingUnavailable(reason)):
            manager._worker(registration, lease)
        expected = "binding unavailable" if reason == reasons[-1] else reason
        assert manager.worker_results[ROOT] == 5
        assert manager.worker_error(ROOT) == expected
        result = manager.task_worker_status(str(tmp_path), "TASK__x", RUN)
        assert result["status"] == "failed"
        assert result["workers"][0]["error"] == expected
        lease.close.assert_called_once()


def test_real_exact_conflict_fence_is_diagnosed_without_admitting_binding(tmp_path):
    import json
    import test_codex_lifecycle_watcher as lifecycle

    mod, _ = _manager(tmp_path)
    rollout = lifecycle._rollout_path(tmp_path / ".codex", ROOT)
    lifecycle._write_jsonl(rollout, [{"type": "session_meta", "payload": {
        "session_id": ROOT, "id": ROOT, "cwd": str(tmp_path), "thread_source": "user",
    }}])
    marker_dir = tmp_path / "doc/harness/tasks/.active_sessions"
    marker_dir.mkdir(parents=True)
    # A fence for another coordinator must not explain this coordinator's loss.
    foreign = marker_dir / f"{OTHER_ROOT}.json"
    foreign.write_text(json.dumps({"session_id": OTHER_ROOT, "conflicts": []}))
    expected_generation = (str(rollout), rollout.stat().st_size, 1.0, "TASK__x", RUN)

    def attempt():
        errors = []
        assert mod._active_task_binding_for_session(str(tmp_path), ROOT) == {}
        result = mod.watch(
            str(tmp_path), ROOT, str(rollout), expected_generation[1],
            task_id="TASK__x", run_id=RUN, idle_seconds=1,
            expected_generation=expected_generation, on_error=errors.append,
        )
        assert result == 5
        return errors

    with mock.patch.object(mod, "_sessions_root", return_value=tmp_path / ".codex/sessions"), \
         mock.patch.object(mod, "_find_rollout", return_value=rollout):
        assert attempt() == ["binding unavailable"]
        marker = marker_dir / f"{ROOT}.json"
        marker.write_text(json.dumps({"session_id": ROOT, "conflicts": []}))
        assert attempt() == ["unacknowledged coordinator conflict fence"]
        with mock.patch.object(mod, "read_active_session_marker", side_effect=OSError("unreadable")):
            assert attempt() == ["binding unavailable"]
    assert not list(tmp_path.rglob("RECEIPTS.jsonl"))


def test_task_snapshot_cannot_select_session_worker_or_promote_readiness(tmp_path, monkeypatch):
    import test_receipt_watcher_fail_closed as readiness

    server = readiness._server()
    monkeypatch.delenv("CODEX_THREAD_ID", raising=False)
    snapshot = {"scope": "process-local", "advisory": True, "status": "running",
                "workers": [{"thread_id": ROOT, "status": "running", "error": ""}],
                "truncated": False, "limitation": "Only this manager is observed."}
    manager = SimpleNamespace(is_running=lambda: True, worker_error=mock.Mock(),
                              task_worker_status=mock.Mock(return_value=snapshot))
    host = SimpleNamespace(watcher_manager=manager, last_watcher_error="", watcher_thread_id="")
    with mock.patch.object(server, "_SERVER", host), \
         mock.patch.object(server, "_server_runtime", return_value="codex"), \
         mock.patch.object(server, "_current_session_identity", return_value=""), \
         mock.patch.object(server, "_control_root", return_value=str(tmp_path)), \
         mock.patch.object(server, "receipt_capability_warning", return_value=""), \
         mock.patch.object(server, "_hook_capability_marker", return_value=False), \
         mock.patch.object(server, "_run_has_receipts", return_value=True), \
         mock.patch.object(server, "_diagnostics_for_this_session", return_value={"root_thread_id": OTHER_ROOT}):
        result = server._watcher_status(task_id="TASK__x", run_id=RUN)
        manager.task_worker_status.assert_called_once_with(str(tmp_path), "TASK__x", RUN)
        manager.task_worker_status.side_effect = RuntimeError("unavailable\n" + "x" * 10000)
        unavailable = server._watcher_status(task_id="TASK__x", run_id=RUN)
    assert result["task_workers"] == snapshot
    assert result["receipts_recordable"] is None
    assert result["root_thread_id"] is None
    assert unavailable["task_workers"]["status"] == "unknown"
    assert unavailable["receipts_recordable"] is None
    assert len(str(unavailable["task_workers"])) < 2000
    manager.worker_error.assert_not_called()
    assert host.watcher_thread_id == ""
