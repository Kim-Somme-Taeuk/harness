# Automatic parallel routing

Status: implemented; live native execution remains capability-dependent.

Goal orchestration routes declared independent work packs through the existing
batch reservation, worktree, integration and recovery engine before opening a
main-checkout integration task. A legacy child without a declared pack retains
sequential behavior. Declared paths and dependencies determine independence;
the coordinator must not invent it from task titles.

## Goal/MCP contract

Before creating the integration task, call `goal_add_task` with its canonical
`task_id` and `batch_requests`, an array of 2–100 objects. Each object has a
unique `slug`, nonempty `request`, and nonempty `scopes` of literal relative
paths. Optional `depends_on` names request slugs in the same pack; unknown
dependencies, duplicates and cycles refuse publication. Optional `submodules`
selects modules under the existing S1 rules. Unknown fields, traversal,
unsupported scopes and intake above 1 MiB also refuse. The integration child
cannot also be a lead. Before publishing new intent, intake rejects lead
identities already used by task directories, preserved archives, recorded pools,
or other declared Goal children/packs; exact existing-pack resynchronization
remains allowed. This does not reserve identities against arbitrary later
external writes. Existing batch preflight remains authoritative.

```json
{
  "task_id": "TASK__integrate-feature",
  "batch_requests": [
    {"slug": "feature-api", "request": "Implement the approved API change", "scopes": ["src/api"], "depends_on": []},
    {"slug": "feature-docs", "request": "Update its independent documentation", "scopes": ["docs"], "depends_on": []}
  ]
}
```

The call stores intent under the Goal child and creates no TASK.json or worktree.
Its deterministic batch identity derives from the exact Goal and integration
child IDs. An existing task cannot be retrofitted with a new pack. A changed
pack for the same child refuses; use a newly authorized integration child for
new scope. Omit `batch_requests` on status/title updates to preserve existing
intake. Explicit null is invalid. Goal resynchronization preserves the pack.

For a selected pack child, `goal_next_task` returns ordinary `goal` and `task`
plus `dispatch`: `route` (`batch` or `integration`), `batch_id`, normalized
`requests`, `batch_state` (`missing`, `open`, or `closed`) and `next_action`.
Unfinished existing pools also return an `unfinished` slug-to-status map.
Missing state routes to initializing that exact batch; existing state routes
to resuming it. Recovery, failed/blocked and abandoned requests remain batch
work with explicit guidance. Exact intake mismatches, unsafe state or invalid
integration/archive proof return an error without changing task or Goal state.

Only a closed pool whose every request is integrated, with preserved archive
fingerprints, valid closed task generations and commits still on the expected
destination branch's ancestry, returns `route: integration`. `task_start` and
`task_close` for that integration child recheck the proof. `goal_finish` also
rechecks it alongside the ordinary canonical child-close gate. No pack status,
manually labeled Goal child, or lead receipt replaces integration review/QA.
Legacy children without pack metadata retain their existing sequential route.

A Goal work pack is complete only after every required request is integrated,
its preserved evidence is valid, and the main integration task has passed its
own independent review and QA and closed. Abandoned or retained requests,
unresolved recovery, and a merely closed batch never establish completion.

Codex workspace support must authenticate each native coordinator and its lens
children, preserve exact task/run/worktree ownership and reject stale, foreign,
unbound or sibling evidence. A workspace argument or prompt is not identity. Explicit-workspace Codex calls and main calls without an exact environment
thread identity defer binding to trusted native PostToolUse. Main calls with an
exact environment identity retain eager binding, with cross-workspace exclusion
checked under shared session locks before publication.
Missing native capabilities are reported explicitly; they never authorize
fabricated receipts, concurrent ownership of one task binding, or an early close.
For native shared-cwd edits, the prewrite gate resolves a validated linked
target checkout before operational-path exemptions and applies that checkout's
PLAN and protected-artifact rules. Nesting a worktree beneath `.claude/` must
not exempt its source files. Ordinary foreign repository writes retain their
existing handling; this route is limited to registered same-repository worktrees.

Within-task scheduling admits dependency-ready disjoint lanes against the actual
available agent slots. Paired implementation and test authors consume separate
slots. A completed lane permits refill while independent siblings remain live;
verification of a paired AC waits for both of its own writers. A failed lane
does not release its dependent ACs. Full review and QA still run on the completed
combined tree in the required order.

Verification: behavioral Goal/batch integration, hostile native rollout identity,
ready-lane capacity and refill tests, plus existing real-Git batch recovery,
receipt ordering, runtime payload and contract regressions.

## Known ceiling

Known ceiling: Dispatch results are proposals; caller must reserve against fresh host inventory before spawning — upgrade when a shared host reservation API exists.

Known ceiling: Large cold ancestry scans may exceed the existing 0.5-second hook budget and fail closed — upgrade when live workloads require longer histories.

Known ceiling: Nested native ancestors must share cwd; explicit worktree targeting and separate native worktree roots are supported — upgrade when native spawning supports isolated child cwd.

No helper
can prove host capacity from an invented inventory. Runtime fixtures prove
protocol handling, not a live end-to-end worktree run or measured throughput.
Native ancestry validation remains bounded by depth 16 and 64 MiB rollout
inputs; worktree discovery refuses more than 256 registry entries. Long cold
ancestry reads can exceed the hook's existing registration budget and then
fail closed. The shared watcher manager retains its maximum of 16 workers.
