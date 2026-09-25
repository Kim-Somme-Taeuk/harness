"""Setup must not write a manifest field that nothing reads.

2026-09-26: the setup interview recorded a fixed Q3 answer as
`execution_mode_default` in doc/harness/manifest.yaml. No code read it, and it
suggested an install-time loop-strength setting that does not exist: execution
mode, planning procedure, and review depth are chosen per task. It was removed.
"""
from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
FIELD = "execution_mode" + "_default"


def test_the_dead_execution_mode_default_field_is_gone():
    hits = [
        str(path.relative_to(REPO))
        for root in ("plugin", "plugin-codex")
        for path in (REPO / root).rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
        and FIELD in path.read_text(encoding="utf-8", errors="ignore")
    ]
    assert hits == [], hits


def test_setup_interview_writes_no_status_quo_answer():
    interview = (REPO / "plugin/skills/setup/project-interview.md").read_text(encoding="utf-8")
    assert "Q3 status quo:" not in interview
    assert "Q3 (Status quo)" not in interview
    assert "q3_status_quo" not in interview
    # Ranges that span the retired question would still name it.
    assert "Q2-Q4" not in interview and "Q2–Q4" not in interview
