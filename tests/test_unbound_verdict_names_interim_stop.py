"""Unbound-verdict diagnostics list the interim mid-work stop as a cause.

2026-09-26: a lens that ended its turn while its own suite was still running
had its interim text recorded as a PENDING completion. Both diagnostics then
blamed the verdict block's position. The receipt row cannot tell the two apart,
so the texts enumerate the interim case with its remedy instead of asserting
either cause (REQ__subagent-lifecycle-receipt-boundaries).
"""
from __future__ import annotations

import sys

from conftest import SCRIPTS_DIR

sys.path.insert(0, SCRIPTS_DIR)
import _lib  # noqa: E402


def _flat(text: str) -> str:
    return " ".join(text.split())


def test_the_write_side_breadcrumb_names_the_interim_case():
    _shows, action = _lib._UNBOUND_COMPLETION_CAUSES["verdict"]
    action = _flat(action)
    assert "Re-deliver that lens final with exactly one verdict block on line 1" in action
    assert "interim message from a lens waiting on its own work" in action
    assert "spawn it fresh in the foreground" in action


def test_the_written_ledger_line_keeps_the_remedy(tmp_path):
    """`_log_gate_error` caps the line at 400 chars; the remedy must survive it."""
    import json
    from pathlib import Path

    (tmp_path / ".git").mkdir()
    (tmp_path / "doc/harness").mkdir(parents=True)
    (tmp_path / "doc/harness/manifest.yaml").write_text("type: test\n", encoding="utf-8")
    task_dir = tmp_path / "doc/harness/tasks" / ("TASK__" + "x" * 60)
    task_dir.mkdir(parents=True)
    entry = {"lens": "review-code", "verdict": "PENDING",
             "summary": "VERDICT: PENDING\nFIRST_LINE: The full suite is still running."}
    _lib.log_unbound_completion(str(task_dir), "review-code", entry)
    rows = [json.loads(line) for line in
            (Path(tmp_path) / "doc/harness/learnings.jsonl").read_text().splitlines()]
    error = next(r["error"] for r in rows if r.get("source") == "receipts:verdict-unbound")
    assert error.rstrip().endswith("spawn it fresh in the foreground."), error


def test_the_task_verify_note_names_the_interim_case():
    note = _flat(_lib.nonparsing_completion_note({"qa-cli": "shape"}))
    assert "ended its turn while its own work was still running" in note
    assert "REQ__subagent-lifecycle-receipt-boundaries" in note
    assert "Spawn that lens fresh" in note


def test_other_causes_are_unchanged():
    for key in ("counts", "contradiction"):
        assert "interim" not in _lib._UNBOUND_COMPLETION_CAUSES[key][1]
    for kind in ("inconsistent", "unpaired", "shape_named"):
        assert "interim" not in _lib.nonparsing_completion_note({"review-code": kind})
