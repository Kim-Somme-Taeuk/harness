#!/usr/bin/env python3
"""Offline grader for the developer-behavior eval scenarios.

Quickstart:
    python3 tests/evals/developer_behavior/grade.py --selftest
    python3 tests/evals/developer_behavior/run_live.py --list
    python3 tests/evals/developer_behavior/run_live.py --dry-run --scenario impossible-guard

Each scenario in scenarios.json ships an inline known-good and known-bad
reference developer final output (a unified diff plus a short report) and a
list of named checks. Every check is a regex/substring test over plain text
and returns (ok, reason); no network access and no third-party imports are
used anywhere in this module.

`--selftest` proves the instrument itself is sound before any model spend:
every check must pass on its scenario's good reference, and the scenario's
bad reference must fail at least the check(s) marked as scenario-specific
(`bad_expect: false` in scenarios.json). Every distinct check name must also be
seen rejecting at least one bad reference somewhere in the set, so no regex
ships without a negative case. It prints one line per
check/reference in the form:

    SELFTEST PASS|FAIL <id>/<check>: <good|bad> reference <reason>

Exit codes: 0 all pass, 1 any FAIL, 2 any ERROR or usage error.

`run_live.py` imports `load_scenarios` and `grade_output` from this module to
grade real model transcripts against the same checks.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

SCENARIOS_PATH = Path(__file__).resolve().parent / "scenarios.json"


def load_scenarios(path=None):
    """Load and return the list of scenario dicts from scenarios.json."""
    scenarios_path = Path(path) if path else SCENARIOS_PATH
    with open(scenarios_path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    return data["scenarios"]


def find_scenario(scenarios, scenario_id):
    """Return the scenario dict with the given id, or None."""
    for scenario in scenarios:
        if scenario["id"] == scenario_id:
            return scenario
    return None


def _compile_pattern(check):
    flags = 0
    for flag_name in check.get("flags", ["MULTILINE"]):
        flags |= getattr(re, flag_name)
    return re.compile(check["pattern"], flags)


def run_check(check, text):
    """Evaluate one check against text. Returns (ok, reason).

    ok is True/False for a normal result, or None if the check itself could
    not be evaluated (bad pattern or unknown mode) — an ERROR condition.
    """
    try:
        regex = _compile_pattern(check)
    except re.error as exc:
        return None, f"invalid pattern for check {check['name']!r}: {exc}"

    found = regex.search(text) is not None
    mode = check.get("mode", "must_match")
    if mode == "must_match":
        ok = found
        reason = "pattern found" if ok else f"expected pattern not found: {check['pattern']!r}"
    elif mode == "must_not_match":
        ok = not found
        reason = "forbidden pattern absent, as required" if ok else f"forbidden pattern present: {check['pattern']!r}"
    else:
        return None, f"unknown mode {mode!r} for check {check['name']!r}"
    return ok, reason


def grade_output(scenario, text):
    """Run every check in scenario against text.

    Returns a list of (check_name, ok, reason) tuples, one per check.
    """
    return [(check["name"], *run_check(check, text)) for check in scenario["checks"]]


def run_selftest(scenarios):
    """Print SELFTEST PASS|FAIL lines for every scenario/check/reference.

    Returns the process exit code: 0 all pass, 1 any FAIL, 2 any ERROR.
    """
    exit_code = 0
    rejected_by = {}
    for scenario in scenarios:
        sid = scenario["id"]
        bad_failed_any = False
        for ref in ("good", "bad"):
            text = scenario[ref]
            for check in scenario["checks"]:
                ok, reason = run_check(check, text)
                if ok is None:
                    print(f"SELFTEST FAIL {sid}/{check['name']}: {ref} reference ERROR: {reason}")
                    exit_code = max(exit_code, 2)
                    continue
                if ref == "good":
                    expected = True
                else:
                    expected = check.get("bad_expect", True)
                    rejected_by.setdefault(check["name"], False)
                    if ok is False:
                        bad_failed_any = True
                        rejected_by[check["name"]] = True
                passed = ok == expected
                status = "PASS" if passed else "FAIL"
                print(f"SELFTEST {status} {sid}/{check['name']}: {ref} reference {reason}")
                if not passed:
                    exit_code = max(exit_code, 1)
        if not bad_failed_any:
            print(f"SELFTEST FAIL {sid}/_bad_coverage: bad reference did not fail any check")
            exit_code = max(exit_code, 1)
    for name, rejected in sorted(rejected_by.items()):
        if not rejected:
            print(f"SELFTEST FAIL _negative_coverage/{name}: no bad reference is rejected by this check")
            exit_code = max(exit_code, 1)
    return exit_code


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--selftest", action="store_true", help="Run the good/bad selftest over every scenario and exit.")
    parser.add_argument("--scenarios", default=None, help="Path to scenarios.json (default: alongside this script).")
    args = parser.parse_args(argv)

    try:
        scenarios = load_scenarios(args.scenarios)
    except (OSError, json.JSONDecodeError, KeyError) as exc:
        print(f"ERROR: failed to load scenarios: {exc}", file=sys.stderr)
        return 2

    if args.selftest:
        return run_selftest(scenarios)

    parser.print_usage(sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
