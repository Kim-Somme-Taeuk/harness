---
tags: [harness, codex, receipts, lifecycle]
summary: Authenticated native Codex followups create fresh receipt generations without reviving an earlier PASS.
updated: 2026-10-07
freshness: current
invalidated_by_paths:
  - plugin/scripts/_lib.py
  - plugin/scripts/codex_lifecycle_watcher.py
  - plugin/scripts/codex_hook_registration.py
  - plugin/scripts/hook_pre_tool_use.py
  - plugin/scripts/hook_post_tool_use.py
---

# REQ — Codex followup receipts

## Expected behavior

A completed native Codex review or QA child may receive substantive new work
through direct `collaboration.followup_task`. The watcher must distinguish that
new generation from the child's earlier final. A correlated followup start
makes the earlier generation's PASS insufficient; only independently matched
native evidence for the new generation can complete it. Successful followup
output without authenticated activity also invalidates the earlier PASS but
cannot establish a new start by itself.

Malformed, missing, overlapping, or conflicting followup evidence must never
restore an earlier PASS. Native turn ids bind task boundaries and completions;
inherited fork history cannot supply the child's own completion. An ordinary
message or repeated final text is not followup authority. This requirement is
specific to Codex; it does not change Claude resumed-agent receipt behavior.

Receipt delivery can lag behind native execution. Gate ordering must therefore
use authenticated coordinator event positions when available, including review
completion before QA start. Incomparable origins cannot establish PASS, while
valid negative evidence remains visible. Legacy-only streams retain their
existing ordering behavior.

Rollout discovery must accommodate writers using different calendar timezones
without scanning history: only a unique trusted candidate within the UTC day
derived from the thread UUIDv7 and its neighboring days is eligible.

When task bindings conflict, hooks must explain the conflict and explicit
future-only recovery. Inspecting another open task with `task_context` can bind
the session; users must not be directed to replay or fabricate receipts, alter
another session's state, or repair a timeout that was never observed. Overflow
fences require a new coordinator.

## Normative ownership

[Single direct Codex receipt protocol](patterns/ADR__single-direct-codex-receipt-protocol.md)
owns acquisition, identity, native turns, discovery, and binding recovery.
[Consolidated task artifacts](patterns/ADR__consolidated-task-artifacts.md)
owns persisted schema and gate ordering. This requirement records observable
outcomes without introducing another receipt authority.

## Verification

`tests/test_installed_receipt_port.py` covers causal order, native followups,
fork history, calendar lookup, and hook conflict guidance. Existing watcher,
hook-wrapper, receipt-model, and worktree suites retain the trust, replay,
binding, and legacy regression boundaries.

## Fork provenance and preservation

This fork ports seven differing files from the installed Harness payload at
`/home/ccc/.codex/harness/plugins/harness`, against upstream base
`bbe06d8fcadb1a295a8fc41c3976635e8ed04b46`. The installed payload itself is not
modified or reinstalled by this port.

| Installed path | Fork source path | Reason to preserve |
| --- | --- | --- |
| `scripts/_lib.py` | `plugin/scripts/_lib.py` | Causal receipt ordering and followup generation gates |
| `scripts/codex_lifecycle_watcher.py` | `plugin/scripts/codex_lifecycle_watcher.py` | Native followups, fork-history exclusion, origin tracking, and bounded calendar lookup |
| `scripts/codex_hook_registration.py` | `plugin/scripts/codex_hook_registration.py` | Distinct positive binding-conflict status and recovery guidance |
| `scripts/hook_pre_tool_use.py` | `plugin/scripts/hook_pre_tool_use.py` | Surface conflict guidance before a new spawn |
| `scripts/hook_post_tool_use.py` | `plugin/scripts/hook_post_tool_use.py` | Surface conflict guidance after task binding |
| `scripts/README.md` | `plugin/scripts/README.md` | Describe adjacent-day rollout lookup |
| `internal-skills/run/SKILL.md` | `plugin-codex/internal-skills/run/SKILL.md` | Preserve the installed Codex receipt workflow guidance |

Subsequent upstream synchronization or model-routing work must preserve these
fork changes and their supporting tests/docs. Do not overwrite them wholesale
with upstream versions. Resolve overlapping upstream changes by comparing the
protocol behavior, reviewing the resulting diff, and rerunning the receipt and
contract regressions before accepting a replacement. Model routing is outside
this port's scope.

### Subsequent model gate

The fork adds a model-decision gate to `hook_pre_tool_use.py` before best-effort
watcher registration. Existing binding-conflict and receipt behavior remains;
review/QA model exemptions preserve substantive lenses when watcher registration
is unavailable. Model-decision failures are separate from receipt failures.

### Eager MCP registration

When the MCP process receives its exact native coordinator identity, eager
registration must preserve the current task/run generation even when the caller
supplies an additional exact-binding predicate. That predicate supplements the
session/task checks; it must not select generationless registration. A successful
registry write with empty task/run is insufficient: the watcher manager rejects
it. Regression coverage must exercise real MCP registration, restore, registry
publication, and manager enumeration together, including missing bindings.
