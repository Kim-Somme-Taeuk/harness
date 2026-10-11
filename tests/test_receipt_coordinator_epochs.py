"""Preserved-run recovery must use complete, authenticated origin intervals."""
import json
import uuid
from datetime import datetime, timezone
from unittest import mock

import pytest
import test_no_git_receipt_model as model

lib = model.lib


def root(hour):
    milliseconds = int(datetime(2026, 10, 12, hour, tzinfo=timezone.utc).timestamp() * 1000)
    return str(uuid.UUID(int=(milliseconds << 80) | (7 << 76) | (2 << 62) | 1))


OLD, NEW, THIRD = root(10), root(12), root(14)
CHILD = root(15)


def row(task, origin, lens, call, event, offset, stamp, verdict="PASS"):
    with mock.patch.object(lib, "_receipt_now_iso", return_value=stamp):
        return model._receipt(
            task, lens, call, event, verdict if event == "completed" else "",
            source="codex_session_watcher:collaboration",
            runtime_id=f"codex:{origin}:{call}:{CHILD}",
            event_order=f"codex:{origin}:{offset}",
        )


def pair(task, origin, lens, call, offset, stamp, verdict="PASS"):
    return [row(task, origin, lens, call, event, offset + delta, stamp, verdict)
            for event, delta in (("started", 0), ("completed", 10))]


def snapshot(task):
    return [dict(item) for item in lib.receipt_snapshot(task).entries]


def rewrite(task, rows):
    (task / "RECEIPTS.jsonl").write_text("".join(json.dumps(item) + "\n" for item in rows))


def recovered(task):
    pair(task, OLD, "review-code", "call_oldreview", 100, "2026-10-12T10:10:00Z")
    row(task, OLD, "qa-cli", "call_oldqa", "started", 120, "2026-10-12T10:11:00Z")
    pair(task, NEW, "review-code", "call_newreview", 10, "2026-10-12T12:10:00Z")
    pair(task, NEW, "qa-cli", "call_newqa", 30, "2026-10-12T12:11:00Z")


def test_preserved_run_fresh_cycle_passes_without_rewriting_old_evidence(tmp_path):
    task = model._task(tmp_path)
    recovered(task)
    before = (task / "RECEIPTS.jsonl").read_bytes()
    assert lib.receipt_review_verdict(task) == "PASS"
    assert lib.receipt_runtime_verdict(task) == "PASS"
    assert lib.nonparsing_completion_lenses(task) == {}
    assert (task / "RECEIPTS.jsonl").read_bytes() == before
    # Receipt arrival order and offsets across coordinators are not causality.
    rewrite(task, list(reversed(snapshot(task))))
    assert lib.receipt_runtime_verdict(task) == "PASS"


def test_review_and_qa_can_straddle_proven_epochs(tmp_path):
    task = model._task(tmp_path)
    pair(task, OLD, "review-code", "call_review", 100, "2026-10-12T10:10:00Z")
    pair(task, NEW, "qa-cli", "call_qa", 10, "2026-10-12T12:10:00Z")
    assert lib.receipt_runtime_verdict(task) == "PASS"
    # A third coordinator's start suppresses PASS until its substantive final.
    row(task, THIRD, "qa-cli", "call_thirdqa", "started", 1, "2026-10-12T14:01:00Z")
    assert lib.receipt_runtime_verdict(task) == "PENDING"
    row(task, THIRD, "qa-cli", "call_thirdqa", "completed", 2, "2026-10-12T14:02:00Z")
    assert lib.receipt_runtime_verdict(task) == "PASS"


@pytest.mark.parametrize("stamp", [
    "2026-10-12T12:00:00Z",  # equality is not strict precedence
    "2026-10-12T12:00:00.001Z",  # overlap
    "2026-10-12T09:59:59Z",  # receipt before its own root birth
    "2026-10-12T10:10:00", "bad", "",  # no trusted temporal bound
])
def test_uncertain_epoch_rejects_pass(tmp_path, stamp):
    task = model._task(tmp_path)
    recovered(task)
    rows = snapshot(task)
    rows[0]["ts"] = stamp
    if stamp:
        rewrite(task, rows)
        assert lib.receipt_runtime_verdict(task) == "PENDING"
    else:
        # An empty stamp is rejected even earlier by persisted schema validation.
        assert lib._ordered_receipt_events(rows, rows) is None


@pytest.mark.parametrize("bad_root", [OLD.replace("-7", "-4", 1), OLD.replace("-8", "-0", 1)])
def test_non_v7_origin_cannot_establish_epoch(tmp_path, bad_root):
    task = model._task(tmp_path)
    recovered(task)
    rows = snapshot(task)
    for item in rows:
        item["runtime_id"] = item["runtime_id"].replace(OLD, bad_root)
        item["event_order"] = item["event_order"].replace(OLD, bad_root)
    rewrite(task, rows)
    assert lib.receipt_runtime_verdict(task) == "PENDING"


@pytest.mark.parametrize("verdict,expected", [("PASS", "PENDING"), ("FAIL", "FAIL"),
                                             ("BLOCKED_ENV", "BLOCKED_ENV")])
def test_late_old_completion_cannot_hide_negative_or_revive_pass(tmp_path, verdict, expected):
    task = model._task(tmp_path)
    recovered(task)
    row(task, OLD, "qa-cli", "call_oldqa", "completed", 140,
        "2026-10-12T12:20:00Z", verdict)
    assert lib.receipt_runtime_verdict(task) == expected


def test_other_lens_overlap_invalidates_the_shared_proof(tmp_path):
    task = model._task(tmp_path)
    recovered(task)
    row(task, OLD, "qa-api", "call_other", "started", 200, "2026-10-12T12:20:00Z")
    rows = snapshot(task)
    review = [item for item in rows if item["lens"] == "review-code"]
    assert lib._ordered_receipt_events(review, rows) is None
    assert not lib._receipt_precedes(review[1], review[2], rows)
    assert lib.receipt_review_verdict(task) == "PENDING"
    assert lib.receipt_runtime_verdict(task) == "PENDING"


def test_other_run_does_not_contaminate_proof(tmp_path):
    task = model._task(tmp_path)
    recovered(task)
    rows = snapshot(task)
    unrelated = dict(rows[0], task_run_id=root(9), ts="2026-10-12T16:00:00Z")
    assert lib._ordered_receipt_events(rows, [*rows, unrelated]) is not None


def test_legacy_causal_mix_in_another_lens_is_not_attesting(tmp_path):
    task = model._task(tmp_path)
    recovered(task)
    model._receipt(task, "qa-api", "legacy", "started")
    assert lib.receipt_runtime_verdict(task) == "PENDING"
    legacy = snapshot(task)[-1:]
    assert lib._ordered_receipt_events(legacy, snapshot(task)) is None


def test_duplicate_terminal_still_rejects_pass(tmp_path):
    task = model._task(tmp_path)
    recovered(task)
    row(task, NEW, "qa-cli", "call_newqa", "completed", 41, "2026-10-12T12:12:00Z")
    assert lib.receipt_runtime_verdict(task) == "PENDING"


def test_single_origin_and_legacy_need_no_epoch_timestamp_proof(tmp_path):
    task = model._task(tmp_path)
    pair(task, OLD, "review-code", "call_review", 100, "unneeded-single-root-stamp")
    pair(task, OLD, "qa-cli", "call_qa", 120, "unneeded-single-root-stamp")
    assert lib.receipt_runtime_verdict(task) == "PASS"
    task2 = model._task(tmp_path / "legacy")
    model._pass_review(task2)
    model._receipt(task2, "qa-cli", "qa", "started")
    model._receipt(task2, "qa-cli", "qa", "completed", "PASS")
    assert lib.receipt_runtime_verdict(task2) == "PASS"
