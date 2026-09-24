"""AC-006: offline developer-behavior eval is sound and never spends a model call.

Covers `tests/evals/developer_behavior/grade.py --selftest` (the instrument
proves itself against inline good/bad references) and
`tests/evals/developer_behavior/run_live.py --dry-run` (prints both arm
prompts, harness arm carries the live developer role core, baseline arm does
not, and no subprocess to a model CLI is spawned).
"""

from __future__ import annotations

import importlib
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
EVAL_DIR = REPO_ROOT / "tests" / "evals" / "developer_behavior"
GRADE_PY = EVAL_DIR / "grade.py"
RUN_LIVE_PY = EVAL_DIR / "run_live.py"


def _import_eval_module(name):
    """Import grade.py / run_live.py from tests/evals/developer_behavior by
    absolute path, isolated from any other `grade`/`run_live` module on
    sys.path (xdist-safe: no shared global import cache mutation survives the
    call)."""
    spec = importlib.util.spec_from_file_location(
        f"_developer_behavior_eval_{name}", EVAL_DIR / f"{name}.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class GradeSelftestTests(unittest.TestCase):
    def test_grade_selftest_passes(self):
        result = subprocess.run(
            [sys.executable, str(GRADE_PY), "--selftest"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(
            0,
            result.returncode,
            msg=(
                f"grade.py --selftest exited {result.returncode}\n"
                f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
            ),
        )
        self.assertIn("SELFTEST PASS", result.stdout)


class RunLiveListTests(unittest.TestCase):
    def test_run_live_list_prints_all_five_fixed_scenario_ids(self):
        result = subprocess.run(
            [sys.executable, str(RUN_LIVE_PY), "--list"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(
            0,
            result.returncode,
            msg=f"run_live.py --list exited {result.returncode}\nstderr:\n{result.stderr}",
        )
        for scenario_id in (
            "impossible-guard",
            "new-dependency",
            "trivial-no-test",
            "known-ceiling",
            "defaultable-assumption",
        ):
            self.assertIn(scenario_id, result.stdout)


class RunLiveDryRunTests(unittest.TestCase):
    def test_both_arms_share_the_output_format_so_baseline_can_pass(self):
        """The baseline arm is told the same line format as the harness arm,
        and every scenario's good reference passes grading; so a baseline
        output that behaves correctly can pass, and the delta measures
        behavior rather than format knowledge."""
        run_live = _import_eval_module("run_live")
        grade = _import_eval_module("grade")
        role_core = run_live.read_role_core()
        for scenario in grade.load_scenarios():
            baseline_prompt, harness_prompt = run_live.build_prompts(scenario, role_core)
            self.assertIn(run_live.OUTPUT_FORMAT_FOOTER, baseline_prompt)
            self.assertTrue(harness_prompt.endswith(baseline_prompt), scenario["id"])
            self.assertNotIn(role_core, baseline_prompt)

    def test_dry_run_prints_both_arm_prompts(self):
        """`run_live.py --dry-run --scenario impossible-guard` prints both arm
        prompts; the harness arm carries the live role core text and the
        baseline arm does not."""
        result = subprocess.run(
            [sys.executable, str(RUN_LIVE_PY), "--dry-run", "--scenario", "impossible-guard"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(
            0,
            result.returncode,
            msg=(
                f"run_live.py --dry-run exited {result.returncode}\n"
                f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
            ),
        )
        stdout = result.stdout
        self.assertIn("baseline prompt", stdout)
        self.assertIn("harness prompt", stdout)

        run_live = _import_eval_module("run_live")
        grade = _import_eval_module("grade")
        role_core = run_live.read_role_core()
        scenario = grade.find_scenario(grade.load_scenarios(), "impossible-guard")
        baseline_prompt, harness_prompt = run_live.build_prompts(scenario, role_core)

        # The subprocess actually printed these two exact prompts.
        self.assertIn(baseline_prompt, stdout)
        self.assertIn(harness_prompt, stdout)

        # Harness arm carries the live role core text; baseline arm does not.
        self.assertIn(role_core, harness_prompt)
        self.assertNotIn(role_core, baseline_prompt)

    def test_dry_run_never_invokes_a_model_subprocess(self):
        """--dry-run must return before any subprocess.run call to the CLI."""
        run_live = _import_eval_module("run_live")
        with mock.patch.object(run_live.subprocess, "run") as mock_run:
            exit_code = run_live.main(["--dry-run", "--scenario", "impossible-guard"])
        self.assertEqual(0, exit_code)
        mock_run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
