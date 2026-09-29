"""Goal packs consume real batch integration and archival evidence."""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugin/scripts"))
import goal_batch

GOAL = "GOAL__parallel"
CHILD = "TASK__integration"


def request(*args, **kwargs):
    from test_batch_state import request as batch_request
    return batch_request(*args, **kwargs)


def pytest_generate_tests(metafunc):
    if "requests" in metafunc.fixturenames:
        metafunc.parametrize("requests", [[], [request("a")],
            [dict(request("a"), ignored_intent="change something else"), request("b")],
            [request("a", dependencies=["missing"])],
            [request("a", dependencies=["b"]), request("b", dependencies=["a"])],
            [request("a", "../escape"), request("b")],
            [request("a", "*.py"), request("b")], [request("integration"), request("b")]])
    if "change" in metafunc.fixturenames:
        metafunc.parametrize("change", ["ancestry", "branch", "archive_symlink", "run", "checkpoint", "harvest"])
    if "proof" in metafunc.fixturenames:
        metafunc.parametrize("proof", ["missing", "tampered"])
    if "used_identity" in metafunc.fixturenames:
        metafunc.parametrize("used_identity", ["task", "archive", "pool", "goal_pack", "goal_child"])


def requests():
    return [request("a"), request("b")]


def pack(tmp_path, monkeypatch):
    from test_batch_state import Pool
    pool = Pool(tmp_path, monkeypatch)
    spec = goal_batch.make_spec(str(pool.repo), GOAL, CHILD, requests())
    pool.batch = spec["batch_id"]
    return pool, spec


def route(pool, spec):
    return goal_batch.route(str(pool.repo), GOAL, CHILD, spec)


def integrated(pool):
    from test_batch_state import complete
    pool.init(requests())
    pool.claim()
    complete(pool)
    complete(pool, "b", "worker-b")
    pool.cli("finish", "--slug", "a")
    pool.cli("finish", "--slug", "b")
    pool.cli("close")


def test_missing_pack_routes_without_creating_state(tmp_path, monkeypatch):
    pool, spec = pack(tmp_path, monkeypatch)
    result = route(pool, spec)
    assert result["route"] == "batch" and result["batch_state"] == "missing"
    assert not pool.state.exists()
    assert goal_batch.make_spec(str(pool.repo), GOAL, CHILD, requests()) == spec
    assert goal_batch.make_spec(str(pool.repo), "GOAL__other", CHILD, requests())["batch_id"] != spec["batch_id"]
    assert goal_batch.make_spec(str(pool.repo), GOAL, "TASK__other", requests())["batch_id"] != spec["batch_id"]


def test_invalid_intake_refused(tmp_path, monkeypatch, requests):
    import pytest
    from test_batch_state import Pool
    pool = Pool(tmp_path, monkeypatch)
    with pytest.raises(ValueError):
        goal_batch.make_spec(str(pool.repo), GOAL, CHILD, requests)


def test_mcp_rejects_used_lead_identity_without_attaching_pack(tmp_path, monkeypatch, used_identity):
    from test_automatic_parallel_routing_contract import make_context, current_bytes
    pool, call, items = make_context(tmp_path, monkeypatch)
    if used_identity in {"task", "archive"}:
        parent = "tasks" if used_identity == "task" else "archive/batch"
        directory = pool.repo / "doc/harness" / parent / "TASK__a"
        directory.mkdir(parents=True)
        (directory / "TASK.json").write_text('{"status":"closed"}\n')
    elif used_identity == "pool":
        pool.init(items)
    elif used_identity == "goal_pack":
        first = call("goal_add_task", {"task_id": "TASK__first", "batch_requests": items})
        assert not first.get("isError"), first
    else:
        first = call("goal_add_task", {"task_id": "TASK__a"})
        assert not first.get("isError"), first
    before = current_bytes(pool)
    refused = call("goal_add_task", {"task_id": CHILD, "batch_requests": items})
    assert refused.get("isError"), refused
    assert "identity already" in refused["structuredContent"]["error"]
    assert current_bytes(pool) == before
    corrected = [dict(item, slug="unused-" + item["slug"]) for item in items]
    accepted = call("goal_add_task", {"task_id": CHILD, "batch_requests": corrected})
    assert not accepted.get("isError"), accepted


def test_mcp_pack_redeclaration_after_init_and_reserved_lead_child(tmp_path, monkeypatch):
    from test_automatic_parallel_routing_contract import make_context, declare, current_bytes
    context = make_context(tmp_path, monkeypatch)
    pool, call, items = context
    declare(context)
    pool.init(items)
    accepted = call("goal_add_task", {"task_id": CHILD, "batch_requests": items})
    assert not accepted.get("isError"), accepted
    before = current_bytes(pool)
    refused = call("goal_add_task", {"task_id": "TASK__a"})
    assert refused.get("isError"), refused
    assert current_bytes(pool) == before


def test_submodule_intent_preserved_without_derived_fields():
    items = [dict(request("a", "vendor/pkg"), submodules=["vendor/pkg"]), request("b")]
    spec = goal_batch._spec(GOAL, CHILD, items)
    assert spec["requests"] == items
    items[0]["submodules"].append("other")
    assert spec["requests"][0]["submodules"] == ["vendor/pkg"]


def test_pending_and_unrelated_pool_cannot_complete(tmp_path, monkeypatch):
    import pytest
    pool, spec = pack(tmp_path, monkeypatch)
    pool.init(requests())
    assert route(pool, spec)["unfinished"] == {"a": "queued", "b": "queued"}
    with pytest.raises(ValueError, match="unfinished"):
        goal_batch.require_integrated(str(pool.repo), GOAL, CHILD, spec)
    changed = copy.deepcopy(spec)
    changed["requests"][0]["request"] = "Different intent"
    with pytest.raises(ValueError, match="intake differs"):
        route(pool, changed)
    with pytest.raises(ValueError, match="identity mismatch"):
        goal_batch.route(str(pool.repo), "GOAL__other", CHILD, spec)


def test_integrated_pack_requires_archive_and_destination_proof(tmp_path, monkeypatch):
    import pytest
    pool, spec = pack(tmp_path, monkeypatch)
    integrated(pool)
    assert route(pool, spec)["route"] == "integration"
    goal_batch.require_integrated(str(pool.repo), GOAL, CHILD, spec)
    archive = pool.repo / "doc/harness/archive/batch/TASK__a/PLAN.md"
    archive.write_text("changed archived evidence")
    with pytest.raises(ValueError, match="archive fingerprint"):
        route(pool, spec)


def test_all_integrated_still_requires_batch_close(tmp_path, monkeypatch):
    from test_batch_state import complete
    pool, spec = pack(tmp_path, monkeypatch)
    pool.init(requests())
    pool.claim()
    complete(pool)
    complete(pool, "b", "worker-b")
    pool.cli("finish", "--slug", "a")
    pool.cli("finish", "--slug", "b")
    assert route(pool, spec)["route"] == "batch"
    assert "Close the fully integrated batch" in route(pool, spec)["next_action"]


def test_abandoned_closed_pack_stays_unfinished(tmp_path, monkeypatch):
    pool, spec = pack(tmp_path, monkeypatch)
    pool.init(requests())
    pool.cli("abandon", "--slug", "a", "--worker-stopped", "--reason", "not dispatched")
    pool.cli("abandon", "--slug", "b", "--worker-stopped", "--reason", "not dispatched")
    pool.cli("close")
    result = route(pool, spec)
    assert result["route"] == "batch" and result["unfinished"] == {"a": "abandoned", "b": "abandoned"}
    assert "cannot complete" in result["next_action"]


def test_halted_pool_routes_recovery(tmp_path, monkeypatch):
    pool, spec = pack(tmp_path, monkeypatch)
    pool.init(requests())
    state = json.loads(pool.state.read_text())
    state["halted"] = True
    pool.state.write_text(json.dumps(state))
    assert "Recover" in route(pool, spec)["next_action"]


def test_integrated_labels_do_not_substitute_for_evidence(tmp_path, monkeypatch, change):
    import pytest
    from test_batch_state import _git
    pool, spec = pack(tmp_path, monkeypatch)
    integrated(pool)
    state = json.loads(pool.state.read_text())
    item = state["requests"][0]
    if change == "ancestry":
        _git("reset", "--hard", state["initial_head"], cwd=pool.repo)
    elif change == "branch":
        _git("checkout", "-qb", "elsewhere", cwd=pool.repo)
    elif change == "archive_symlink":
        archive = pool.repo / "doc/harness/archive/batch/TASK__a"
        target = archive.with_name("moved")
        archive.rename(target)
        archive.symlink_to(target, target_is_directory=True)
    elif change == "run":
        item["run_id"] = item["checkpoint"]["run_id"] = "0198c349-5800-7000-8000-000000000002"
        pool.state.write_text(json.dumps(state))
    elif change == "harvest":
        item["checkpoint"]["harvest"] = None
        pool.state.write_text(json.dumps(state))
    else:
        del item["checkpoint"]
        pool.state.write_text(json.dumps(state))
    with pytest.raises(ValueError):
        route(pool, spec)


def test_symlinked_missing_state_parent_is_refused(tmp_path, monkeypatch):
    import pytest
    pool, spec = pack(tmp_path, monkeypatch)
    runtime = pool.repo / "doc/harness/runtime"
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    runtime.symlink_to(elsewhere, target_is_directory=True)
    with pytest.raises(ValueError, match="unsafe"):
        route(pool, spec)


def mcp_integration(tmp_path, monkeypatch):
    from test_automatic_parallel_routing_contract import make_context, declare
    from test_harness_mcp_server import HarnessMcpServerTests

    context = make_context(tmp_path, monkeypatch)
    pool, call, _ = context
    declare(context)
    integrated(pool)
    selected = call("goal_next_task", {})
    assert not selected.get("isError"), selected
    assert selected["structuredContent"]["dispatch"]["route"] == "integration"
    assert selected["structuredContent"]["task"]["task_id"] == CHILD
    started = call("task_start", {"task_id": CHILD})
    assert not started.get("isError"), started
    planned = call("write_plan", {"task_id": CHILD, "plan": "# Integration\nReview and test the combined result.\n",
                                  "required_lenses": ["review-code", "qa-cli"]})
    assert not planned.get("isError"), planned
    directory = pool.repo / "doc/harness/tasks" / CHILD
    # Established isolated receipt fixture, never production attestation.
    HarnessMcpServerTests()._write_subagent_receipt(str(directory))
    verified = call("task_verify", {"task_id": CHILD})
    assert not verified.get("isError"), verified
    assert verified["structuredContent"]["runtime_verdict"] == "PASS"
    return pool, call, directory


def damage_pack_proof(pool, proof):
    if proof == "missing":
        pool.state.unlink()
    else:
        archive = pool.repo / "doc/harness/archive/batch/TASK__a/PLAN.md"
        archive.write_text("altered preserved evidence\n")


def test_mcp_completed_pack_closes_integration_child_and_goal(tmp_path, monkeypatch):
    pool, call, directory = mcp_integration(tmp_path, monkeypatch)
    closed = call("task_close", {"task_id": CHILD})
    assert not closed.get("isError"), closed
    current = call("goal_context", {})["structuredContent"]["goal"]
    assert current["tasks"][0]["status"] == "closed"
    finished = call("goal_finish", {"status": "complete"})
    assert not finished.get("isError"), finished
    assert finished["structuredContent"]["goal"]["status"] == "complete"


def test_mcp_close_refuses_damaged_pack_without_closing_child(tmp_path, monkeypatch, proof):
    pool, call, directory = mcp_integration(tmp_path, monkeypatch)
    goal_file = pool.repo / "doc/harness/goals/current.json"
    before = (directory / "TASK.json").read_bytes(), goal_file.read_bytes()
    damage_pack_proof(pool, proof)
    closed = call("task_close", {"task_id": CHILD})
    assert closed.get("isError"), closed
    assert "Goal batch" in closed["structuredContent"]["error"]
    assert ((directory / "TASK.json").read_bytes(), goal_file.read_bytes()) == before


def test_mcp_finish_rechecks_pack_after_integration_child_closed(tmp_path, monkeypatch, proof):
    pool, call, directory = mcp_integration(tmp_path, monkeypatch)
    closed = call("task_close", {"task_id": CHILD})
    assert not closed.get("isError"), closed
    goal_file = pool.repo / "doc/harness/goals/current.json"
    before = (directory / "TASK.json").read_bytes(), goal_file.read_bytes()
    damage_pack_proof(pool, proof)
    finished = call("goal_finish", {"status": "complete"})
    assert finished.get("isError"), finished
    assert "Goal batch" in finished["structuredContent"]["error"]
    assert ((directory / "TASK.json").read_bytes(), goal_file.read_bytes()) == before
