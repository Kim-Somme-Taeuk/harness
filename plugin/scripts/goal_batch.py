"""Read-only bridge from a Goal integration child to the existing batch pool.

The spec is intent, not close evidence. Batch state and preserved task evidence
must still agree before the canonical integration child may run or finish.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import re

import batch_state as batch


def _spec(goal_id: str, task_id: str, requests: list) -> dict:
    if not isinstance(goal_id, str) or not re.fullmatch(r"GOAL__[A-Za-z0-9_.-]{1,180}", goal_id):
        raise ValueError("canonical Goal identity required")
    if not isinstance(task_id, str) or not re.fullmatch(r"TASK__[A-Za-z0-9_.-]{1,180}", task_id):
        raise ValueError("canonical integration child identity required")
    batch.requests_valid(requests)
    batch.require(len(requests) >= 2, "Goal batch requires at least two requests")
    batch.require(all(set(item) <= {"slug", "request", "scopes", "depends_on", "submodules"}
                      for item in requests), "unknown Goal batch request field")
    normalized = copy.deepcopy(batch.normalize_requests(requests))
    batch.require(len(json.dumps(normalized).encode()) <= batch.LIMIT, "Goal batch intake exceeds 1 MiB")
    if any("TASK__" + item["slug"] == task_id for item in normalized):
        raise ValueError("integration child cannot also be a batch lead")
    identity = json.dumps([goal_id, task_id], separators=(",", ":")).encode()
    return {"batch_id": "goal-" + hashlib.sha256(identity).hexdigest(), "requests": normalized}


def make_spec(repo_root: str, goal_id: str, task_id: str, requests: list) -> dict:
    """Validate new intake without reserving, opening tasks, or writing state."""
    try:
        spec = _spec(goal_id, task_id, requests)
        repo = os.path.realpath(repo_root)
        directory = os.path.join(repo, "doc/harness/runtime/batches")
        records = {}
        ancestor = directory
        while not os.path.lexists(ancestor):
            ancestor = os.path.dirname(ancestor)
        batch.parents(ancestor)
        if os.path.lexists(directory):
            records = batch.load_all(directory, repo)
        existing = records.get(spec["batch_id"])
        if existing is not None:
            batch.require(batch.normalize_requests(existing["requests"]) == spec["requests"],
                          "Goal batch intake differs from existing pool")
        else:
            batch.require(len(records) < batch.MAX_BATCHES, "batch history limit reached")
            batch.require_unused_task_ids(repo, spec["requests"], records)
        for item in spec["requests"]:
            # preflight may attach derived module ownership; keep intent only.
            batch.preflight(repo, copy.deepcopy(item))
        return spec
    except (batch.Refusal, OSError) as exc:
        raise ValueError("Goal batch intake refused: " + str(exc)) from exc


def _integrated_proof(repo: str, data: dict) -> None:
    ref = data["destination_ref"]
    current_ref = batch.finish_helper._git(repo, "symbolic-ref", "-q", "HEAD").stdout.strip()
    batch.require(current_ref == ref, "Goal batch destination branch changed")
    commits = [data["initial_head"]]
    for item in data["requests"]:
        checkpoint = item.get("checkpoint", {})
        tip = checkpoint.get("integrated_tip")
        archive = os.path.join(repo, "doc/harness/archive/batch", item["task_id"])
        batch.require(checkpoint.get("stage") == "harvested"
                      and isinstance(tip, str) and batch.finish_helper.COMMIT_RE.fullmatch(tip)
                      and checkpoint.get("branch_tip") == tip,
                      "Goal batch integration checkpoint missing")
        harvest = checkpoint.get("harvest")
        batch.require(isinstance(harvest, dict) and harvest.get("archived") == archive,
                      "Goal batch archive identity mismatch")
        batch.require(batch.fingerprint(archive) == checkpoint.get("archive_fingerprint"),
                      "Goal batch archive fingerprint changed")
        batch.control(item, base=archive, closed=True)
        if item.get("submodule_manifest"):
            batch.batch_submodules.preserved_proof(repo, item["submodule_manifest"])
        commits.append(tip)
    for commit in commits:
        batch.require(batch.finish_helper._git(
            repo, "merge-base", "--is-ancestor", commit, ref,
        ).returncode == 0, "Goal batch commit is missing from destination ancestry")


def route(repo_root: str, goal_id: str, task_id: str, spec: dict) -> dict:
    """Return batch dispatch/resume or integration routing; refuse corrupt proof.

No state is created here. A missing batch is initialized through batch_state;
an existing pool keeps its reservation, recovery, and cleanup ownership.
"""
    try:
        batch.require(isinstance(spec, dict), "invalid Goal batch spec")
        expected = _spec(goal_id, task_id, spec.get("requests"))
        batch.require(spec == expected, "Goal batch spec identity mismatch")
        repo = os.path.realpath(repo_root)
        directory = os.path.join(repo, "doc/harness/runtime/batches")
        path = os.path.join(directory, expected["batch_id"] + ".json")
        result = {**copy.deepcopy(expected), "route": "batch", "batch_state": "missing",
                  "next_action": "Initialize this exact batch intake, then dispatch ready reservations through batch_state."}
        if not os.path.lexists(directory):
            # Validate existing ancestors even when this is the first pool.
            existing = directory
            while not os.path.lexists(existing):
                existing = os.path.dirname(existing)
            batch.parents(existing)
            return result
        batch.parents(directory)
        if not os.path.lexists(path):
            return result
        data = batch.validate(batch.read_json(path), repo, expected["batch_id"])
        batch.require(batch.normalize_requests(data["requests"]) == expected["requests"],
                      "Goal batch intake differs from existing pool")
        result["batch_state"] = data["status"]
        unfinished = {item["slug"]: item["status"] for item in data["requests"]
                      if item["status"] != "integrated"}
        if data["halted"] or unfinished:
            result["unfinished"] = unfinished
            if data["halted"] or any(status in {"integrating", "recovery-required", "kept"}
                                     for status in unfinished.values()):
                result["next_action"] = "Recover the retained batch integration through batch_state before dispatch or integration review."
            elif any(status in {"abandoned", "blocked", "failed"} for status in unfinished.values()):
                result["next_action"] = "Resolve unfinished batch work through its existing recovery or disposition workflow; this pack cannot complete the Goal."
            else:
                result["next_action"] = "Resume this exact batch, dispatch ready reservations, and integrate returned leads through batch_state."
            return result
        _integrated_proof(repo, data)
        if data["status"] != "closed":
            result["next_action"] = "Close the fully integrated batch through batch_state, then start the canonical integration child."
            return result
        result.update(route="integration", next_action="Start or resume the canonical integration child; independently review and verify the integrated result before closing it.")
        return result
    except (batch.Refusal, OSError, KeyError, TypeError) as exc:
        raise ValueError("Goal batch proof refused: " + str(exc)) from exc


def require_integrated(repo_root: str, goal_id: str, task_id: str, spec: dict) -> None:
    """Guard Goal completion in addition to its canonical child close checks."""
    result = route(repo_root, goal_id, task_id, spec)
    if result["route"] != "integration":
        raise ValueError("Goal batch is unfinished: " + result["next_action"])
