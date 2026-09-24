#!/usr/bin/env python3
"""Opt-in live runner for the developer-behavior eval. Spends real model calls.

Quickstart:
    python3 tests/evals/developer_behavior/run_live.py --list
    python3 tests/evals/developer_behavior/run_live.py --dry-run --scenario impossible-guard
    python3 tests/evals/developer_behavior/run_live.py --scenario impossible-guard --repeat 3

Prerequisite: `claude -p "ok"` must succeed in this environment before running
any non-dry-run invocation of this script.

Cadence: run this whenever the developer role core changes
(plugin/agents/developer.md, between the `<!-- harness:role-core:start -->`
and `<!-- harness:role-core:end -->` markers), to see whether the harness role
core actually shifts graded behavior relative to a plain baseline prompt.

Each scenario runs in two arms:
  - baseline: the scenario prompt plus OUTPUT_FORMAT_FOOTER, no role core.
  - harness:  the developer.md role core text, read fresh from
              plugin/agents/developer.md at run time (never copied into this
              file), prepended to that same baseline prompt.
Both arms are told the same output line format, so the delta measures
behavior the role core changes, not whether an arm knew the format.

Both arms are sent to `claude -p --tools ""` (DEFAULT_CLI, overridable with
--cli) on stdin, in a fresh temporary working directory, with a per-call
timeout. `--tools ""` disables all tools for the session (confirmed present
via `claude --help` at the time this runner was written), so the model can
only respond with text in either arm — the isolation this eval needs for an
honest baseline-vs-harness delta; never `shell=True`.

Note: user-level Claude Code plugins, hooks, and settings are not sandboxed
by `--tools ""` and may still load into both arms identically; a delta this
runner reports is evidence, not proof the role core acts in isolation from
that environment.

Grading is regex/substring only (tests/evals/developer_behavior/grade.py);
outputs are never written into the repo. CLI missing, non-zero exit, empty
output, or a timeout is graded as a per-call ERROR (neither pass nor fail)
and this script exits 2 for the whole run.
"""

from __future__ import annotations

import argparse
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from grade import find_scenario, grade_output, load_scenarios  # noqa: E402

DEVELOPER_AGENT_PATH = Path(__file__).resolve().parents[3] / "plugin" / "agents" / "developer.md"
ROLE_CORE_START = "<!-- harness:role-core:start -->"
ROLE_CORE_END = "<!-- harness:role-core:end -->"

DEFAULT_CLI = 'claude -p --tools ""'
DEFAULT_TIMEOUT = 120.0


class LiveRunError(RuntimeError):
    """A per-call ERROR condition: missing CLI, non-zero exit, empty output, timeout."""


def read_role_core(path=None):
    """Return the role core text between the harness:role-core markers.

    Read fresh from plugin/agents/developer.md at call time; this text is
    never copied verbatim into this module so the eval always exercises the
    live role core.
    """
    agent_path = Path(path) if path else DEVELOPER_AGENT_PATH
    text = agent_path.read_text(encoding="utf-8")
    start = text.index(ROLE_CORE_START) + len(ROLE_CORE_START)
    end = text.index(ROLE_CORE_END, start)
    return text[start:end].strip()


# Both arms get the same output-format footer, so a scenario check measures
# behavior rather than whether the arm was told the line format.
OUTPUT_FORMAT_FOOTER = (
    "End your final response with a `Status: implemented`, `Status: blocked`, or "
    "`Status: needs-coordinator-review` line, a `Changed:` line, and a "
    "`Verification:` line. Add one `Known ceiling: <ceiling> — upgrade when "
    "<trigger>` line per deliberate ceiling and one `Assumption: <choice> — "
    "because <evidence>` line per choice you defaulted; omit those two when "
    "there is none."
)


def build_prompts(scenario, role_core):
    """Return (baseline_prompt, harness_prompt) for one scenario."""
    task = f"{scenario['prompt']}\n\n{OUTPUT_FORMAT_FOOTER}"
    baseline_prompt = task
    harness_prompt = f"{role_core}\n\n{task}"
    return baseline_prompt, harness_prompt


def call_cli(argv, prompt, cwd, timeout):
    """Run argv with prompt on stdin in cwd. Returns decoded stdout.

    Raises LiveRunError for any condition the eval must grade as ERROR.
    """
    try:
        proc = subprocess.run(
            argv,
            input=prompt.encode("utf-8"),
            cwd=cwd,
            timeout=timeout,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except subprocess.TimeoutExpired as exc:
        raise LiveRunError(f"timed out after {timeout}s") from exc
    except OSError as exc:
        raise LiveRunError(f"failed to start CLI {argv!r}: {exc}") from exc
    if proc.returncode != 0:
        stderr_text = proc.stderr.decode("utf-8", errors="replace").strip()
        raise LiveRunError(f"CLI exited {proc.returncode}: {stderr_text[:500]}")
    output = proc.stdout.decode("utf-8", errors="replace")
    if not output.strip():
        raise LiveRunError("CLI produced empty output")
    return output


def _safe_reconfigure_utf8():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--scenario", action="append", default=None, help="Scenario id to run (repeatable). Default: all scenarios.")
    parser.add_argument("--list", action="store_true", help="List scenario ids and titles, then exit. Never invokes a model.")
    parser.add_argument("--dry-run", action="store_true", help="Print the resolved CLI argv and both arm prompts, then exit. Never invokes a model.")
    parser.add_argument("--repeat", type=int, default=1, help="Repeat each arm this many times per scenario (default: 1). Delta is evidence only at --repeat >= 3.")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT, help=f"Per-call timeout in seconds (default: {DEFAULT_TIMEOUT}).")
    parser.add_argument("--cli", default=DEFAULT_CLI, help=f"CLI command line to invoke (default: {DEFAULT_CLI!r}).")
    args = parser.parse_args(argv)

    _safe_reconfigure_utf8()

    try:
        scenarios = load_scenarios()
    except (OSError, ValueError, KeyError) as exc:
        print(f"ERROR: failed to load scenarios: {exc}", file=sys.stderr)
        return 2

    if args.list:
        for scenario in scenarios:
            print(f"{scenario['id']}: {scenario['title']}")
        return 0

    if args.scenario:
        selected = []
        for sid in args.scenario:
            scenario = find_scenario(scenarios, sid)
            if scenario is None:
                print(f"ERROR: unknown scenario id {sid!r}. Use --list to see valid ids.", file=sys.stderr)
                return 2
            selected.append(scenario)
    else:
        selected = scenarios

    try:
        cli_argv = shlex.split(args.cli, posix=os.name != "nt")
    except ValueError as exc:
        print(f"ERROR: could not parse --cli {args.cli!r}: {exc}", file=sys.stderr)
        return 2
    if not cli_argv:
        print("ERROR: --cli resolved to an empty command", file=sys.stderr)
        return 2

    try:
        role_core = read_role_core()
    except (OSError, ValueError) as exc:
        print(f"ERROR: could not read the developer role core: {exc}", file=sys.stderr)
        return 2

    if args.dry_run:
        print(f"argv: {cli_argv}")
        for scenario in selected:
            baseline_prompt, harness_prompt = build_prompts(scenario, role_core)
            print(f"--- {scenario['id']} baseline prompt ---")
            print(baseline_prompt)
            print(f"--- {scenario['id']} harness prompt ---")
            print(harness_prompt)
        return 0

    if shutil.which(cli_argv[0]) is None:
        print(
            f"ERROR: CLI executable {cli_argv[0]!r} not found on PATH. "
            "Install it, or pass --cli '<path-to-cli> ...'.",
            file=sys.stderr,
        )
        return 2

    repeat = max(1, args.repeat)
    any_error = False
    for scenario in selected:
        baseline_prompt, harness_prompt = build_prompts(scenario, role_core)
        arm_pass_counts = {}
        for arm_name, prompt in (("baseline", baseline_prompt), ("harness", harness_prompt)):
            passed = failed = errored = 0
            for _ in range(repeat):
                with tempfile.TemporaryDirectory() as tmp_cwd:
                    try:
                        output = call_cli(cli_argv, prompt, tmp_cwd, args.timeout)
                    except LiveRunError as exc:
                        print(f"ERROR {scenario['id']}/{arm_name}: {exc}", file=sys.stderr)
                        errored += 1
                        any_error = True
                        continue
                    results = grade_output(scenario, output)
                    if all(ok for _name, ok, _reason in results):
                        passed += 1
                    else:
                        failed += 1
            arm_pass_counts[arm_name] = passed
            print(f"{scenario['id']}/{arm_name}: pass={passed} fail={failed} error={errored}")
        delta = (arm_pass_counts["harness"] - arm_pass_counts["baseline"]) / repeat
        note = "" if repeat >= 3 else " (evidence only at --repeat >= 3)"
        print(f"{scenario['id']}: delta(harness-baseline) pass rate = {delta:+.2f}{note}")

    return 2 if any_error else 0


if __name__ == "__main__":
    raise SystemExit(main())
