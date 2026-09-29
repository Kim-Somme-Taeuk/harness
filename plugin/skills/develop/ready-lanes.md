# Ready-lane dispatch

Use `scripts/parallel_dispatch.py` on both runtimes to calculate which declared
ACs can start. It returns proposals; the coordinator owns actual tool calls and
must reserve the whole returned group against fresh host inventory before
spawning. It never writes task state or receipts.

Build an ephemeral JSON snapshot from PLAN and observed worker state:

```json
{
  "repo": "/absolute/checkout",
  "host_capacity": 4,
  "ac_cap": 4,
  "acs": [
    {"id": "AC-001", "files": ["src/a.py"], "tests": ["tests/test_a.py"], "depends_on": []},
    {"id": "AC-002", "files": ["src/b.py"], "tests": [], "depends_on": []}
  ],
  "progress": {},
  "live_agents": [{"id": "root", "role": "coordinator"}]
}
```

Run `PYTHONDONTWRITEBYTECODE=1 python3 ${CLAUDE_PLUGIN_ROOT}/scripts/parallel_dispatch.py --input <snapshot>`.
The snapshot can live in an ignored task work directory. Do not add fields to
TASK.json or PROGRESS.md: this is disposable scheduling input, not new task
authority. Use literal repo-relative paths and pass the checkout to resolve
aliases. Unknown dependencies, cycles and unsafe paths refuse dispatch.

Read `develop.fanout_cap` once: absent/invalid -> 4; positive integer -> min(8,
value), excluding booleans. Record the effective cap/source in the lane table.
The host's actual total agent limit is a second, stricter bound. Inventory
includes the coordinator, all live workers/reviewers, and reserved-but-not-yet-
spawned slots. When finished agents still consume host capacity, keep them in
inventory until the host releases them. If the host exposes no numerical
capacity, do not invent a numeric snapshot: bypass parallel admission and run
one scoped worker at a time (or inline if spawn is unavailable), explicitly
unpaired, reporting the capability fallback. Never retry a failed spawn by
blindly spawning more.

For each `dispatch` group, reserve its `slots` before issuing worker calls.
`paired` requires an implementation worker and test-author together; prompts
give each only its returned paths. With only one usable host worker slot, the
explicit `unpaired` fallback assigns both sets to one worker. A temporarily busy
host waits for pair capacity rather than silently weakening pairing.

After a worker result, release only slots the host has actually freed. Mark the
AC `verifying` until its own implementation and test author finish; run scoped
checks, then mark `completed` with `verified: true, workers_released: true`.
Full-tree verification commands wait until all relevant writers stop. Do not
wait for unrelated siblings before refilling ready lanes. Failed/blocked ACs
keep dependents waiting; retained live writers keep their paths reserved.
`reservation_failed` never triggers another spawn until the coordinator has
observed what started, released only unused reservations, and reset the lane.

Recompute after each completion, failure, release or host-capacity change.
Keep running groups in inventory when a limit falls; start nothing above it.
The coordinator remains the sole progress writer. Review-before-QA order and
independent close evidence are unchanged; scheduler output is never a verdict.

Nested workers need explicitly allocated spare slots from the coordinator's
same inventory. A lane cap does not grant each worker its own fresh host cap.
No assigned spare slots means no nested fanout.
