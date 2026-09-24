---
date: 2026-09-24
task: TASK__developer-ponytail-gap-followups
tags: [developer, ac-worker, develop, ponytail, eval, codex]
---

# The developer contract now reaches every implementer and has a behavior eval

Claude develop now tells the coordinator to Read the `developer.md` role core
before its first sequential edit, matching Codex; parent context is not
propagation. The developer core ends with a fixed output contract:
`Status: implemented | blocked | needs-coordinator-review` (the same tokens as
an AC worker's `AC-NNN:` line, and the coordinator treats both forms as
equivalent), plus one `Known ceiling: <ceiling> — upgrade when <trigger>` line
per deliberate ceiling and one `Assumption: <choice> — because <evidence>` line
per defaulted choice. A new package is admitted only for a current AC, when it
beats a small local implementation, and when the manifest and lockfile are the
implementer's to change. Guards against states the code already rules out are
out.

Ambiguity is split in the core, in `ac-worker.md`, and in both develop
Confusion Protocols. Blocking ambiguity, where a wrong guess changes the
outcome, scope, safety, or external state and PLAN/code cannot settle it,
stops. Defaultable ambiguity is decided, reported as `Assumption:`, and work
continues.

`fix-first-pattern.md` is now a short self-check (delete / reuse / stdlib /
native / yagni) plus the unchanged 3-attempt escalation rule. Its AUTO-FIX table
used to add null guards, constants, and DRY extractions automatically, which
contradicted the ladder. Develop no longer points at a nonexistent `investigate`
skill; escalation uses `hypothesis-driven-debugging.md`. Phase 3.5 and 4.85
require new tests only for non-trivial changed behavior, and Phase 6 alone
owns commit order.

Develop Phase 8.6 copies each reported ceiling into the durable doc that owns
the behavior, or into this kind of change doc, before `task_verify`, so
`grep -rn "Known ceiling" doc/` is the ceiling ledger. Old reports without
these lines need no migration.

`tests/evals/developer_behavior/` adds five scenarios: `impossible-guard`,
`new-dependency`, `trivial-no-test`, `known-ceiling`, and
`defaultable-assumption`. `grade.py --selftest` runs in pytest and proves each
check against known-good and known-bad references with no network.
`run_live.py` is opt-in. It runs a baseline arm and a developer-core arm
through a CLI and reports the pass delta. Run it on any change to the developer
role core.
