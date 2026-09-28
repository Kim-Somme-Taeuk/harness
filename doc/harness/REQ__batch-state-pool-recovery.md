# Batch state, bounded scheduling and recovery

The coordinator records a batch before dispatching any lead. Its operational
record survives interruption at `doc/harness/runtime/batches/<id>.json`; it is
not task control or review/QA evidence. Only the existing task lifecycle can
publish a closed task. A returned `closed` result must match its recorded
worker, worktree, branch, task and current run, with valid close evidence.

## Coordinator commands

Use `python3 plugin/scripts/batch_state.py --repo ROOT --batch-id ID COMMAND`.
The runtime-installed script uses the same interface.

| Command | Observable behavior |
|---|---|
| `init --requests-file FILE [--max-leads N]` | Store distinct requests, scopes, dependencies, destination branch and capacity. Refuse conflicting existing state. |
| `status` | Read reported state and current observations without writing; show retained work and next actions. |
| `claim` | Atomically reserve eligible requests up to capacity and return current spawn HEAD and off-limits paths. |
| `bootstrap --slug S --worktree W --branch B` | Create only the validated Git-visible retention marker in the reserved checkout; do not write task evidence or batch records. |
| `bind --slug S --worker-id ID --worktree W --branch B` | Bind a reservation to a registered worktree on the expected branch and starting commit. |
| `result --slug S --worker-id ID --result-file FILE` | Record a structurally matched actual lead result; validate close authority for `closed`. |
| `finish --slug S [--resume]` | Serialize existing rebase, fast-forward, harvest and cleanup with durable checkpoints. |
| `recover --slug S --worker-stopped` | Reconcile interruption using exact saved integration and archive evidence; uncertainty stays visible. |
| `resume --slug S --worker-stopped` | Reserve capacity for the same retained worktree/task generation and provide its handoff. |
| `abandon --slug S --worker-stopped --reason TEXT` | Record explicit abandonment while preserving work, evidence and unresolved scope ownership. |
| `release --slug S --worker-stopped --no-external-work` | Release an unused reservation only after the coordinator confirms no external work exists. |
| `close` | Refuse unresolved active work or cleanup; distinguish retained abandonment from integrated completion. |

Requests are a JSON list of objects with `slug`, `request`, `scopes` and
optional `depends_on`. Scopes are literal paths, never shell expressions.
Unknown dependencies, dependency cycles, duplicate slugs and reused task/archive
identities refuse intake. A batch has at most 100 requests.

The effective cap is explicit `--max-leads`, then optional manifest
`batch.max_leads`, then 3. Positive integers above 8 clamp to 8. Invalid explicit
values fail; invalid manifest values fall back to 3 with the source reported.
Booleans and quoted strings are not integers. Setup need not write this key.

## Pool and ownership

Reserved and running requests consume slots. A completed lead releases its
worker slot; the coordinator serially integrates closed results and immediately
refills eligible slots from the current destination HEAD. A dependency becomes
ready only after its predecessor is integrated and cleaned up. Overlapping
scopes cannot run concurrently; blocked, failed, kept and abandoned sources
continue to reserve their scopes across batches while unresolved.

Only one pool may have reserved/running/integrating requests in a control root.
All mutations use the same persistent advisory lock. Status does not wait for
that lock and never rewrites reported state from observations. A busy lock is
reported separately from invalid data. External Git writers do not obey this
lock, so current branch identity, Git operation state, cleanliness and ownership
must be rechecked at their actual use boundaries.

Dispatch is a handshake: reserve, spawn a bootstrap-only agent, receive its
worktree/branch/HEAD, bind it, then authorize that exact agent to begin work.
The bootstrap must not edit source or start a task before binding. It creates
only `.harness-batch-bootstrap`, a nonignored untracked regular file containing
the exact `{batch_id,slug,spawn_head}` reservation payload. Bind accepts only
that validated operational marker as a bootstrap change and rejects halted or
unresolved integration, including reservations made before the halt. Never expire
a reservation solely because time passed. A failed spawn requires explicit
stopped/no-external-work confirmation before release.

Claude removes unchanged isolation worktrees on completion; its retention rules
keep worktrees with untracked work. The marker therefore remains through native
bootstrap completion, blocked/failed returns and closed tasks with no source
change. Never stage it or remove it in a lead. For lead QA, only this validated
operational marker is excepted from source cleanliness; implementation changes
still require commits. Continue the exact bound native agent with `SendMessage`
when available. Managed finish validates the marker at cleanliness boundaries
and removes it only after durable harvest, immediately before ordinary worktree
removal. Unknown or unsafe marker content never permits a dirty-worktree bypass.
See [Claude subagents](https://code.claude.com/docs/en/sub-agents#frontmatter-reference)
and [worktree retention](https://code.claude.com/docs/en/worktrees#clean-up-subagent-and-background-session-worktrees).

No main-checkout Harness task is open while live worktree leads can emit
lifecycle events. After all writers stop, the coordinator runs the integration
task's independent review, QA, verified installation and close. Operational
batch closure never substitutes for those gates.

## Interruption and retained work

`batch_finish.py` remains the integration owner. Its optional checkpoint
callback does not change ordinary callers. Before unlock/removal, persist the
exact post-rebase integrated tip, intended destination ref, task/run/close
identity and harvested archive tree fingerprint. Atomic replacement includes
file and directory synchronization. Before publishing the cleanup checkpoint,
synchronize the archived files, directories, their publication parents and
preserved learnings. Any synchronization or checkpoint failure stops cleanup.

Recovery compares saved facts against current Git registration, branch,
ancestry, task closure and archive contents. It never guesses a rebased tip
from the old returned SHA, treats an archive's existence as PASS, or replays
receipts. Missing evidence leaves a recovery-required result. If only branch
deletion remains, report that branch rather than a nonexistent worktree.
Conflicts, fast-forward refusal or unknown integration halt further dispatch
and integration until explicit validated recovery.

Resume accepts blocked/failed work and interrupted running workers whose writers
the coordinator has confirmed stopped. It does not require a fabricated failed
result. If the running worker's generation was never observed, validate and pin
the current open/blocked task run, or explicit task absence, before handoff.
Previously recorded task absence must still hold. Bind rechecks this identity
and refuses a task that appears or changes after handoff. Resume and bind both
refuse while a main-checkout task is open. A failed continuation bootstrap keeps
its bound reservation and retries in the same worktree after stopped-writer
confirmation; releasing a bound worktree as unused is forbidden.

Resume uses the original native agent when available; otherwise use the
non-isolating `task-lead-resume` agent in the exact existing worktree. Ordinary
`task-lead` isolation would allocate another checkout and is not a resume.
Call `task_start(workspace=W, task_id=existing_id)` without `fresh_run` so
existing evidence survives. A changed task generation or branch refuses.

Abandonment is an explicit user choice. It does not delete unintegrated source,
force-delete branches, modify task status, or satisfy the Goal. Retained work
and the next disposition action remain visible. Queued requests, including
dependents of an abandoned request, can be explicitly abandoned without ever
being dispatched; report this separately from retained external work. A stopped
integration failure can be abandoned only after reconciling its exact destination
and branch facts as confirmed unintegrated with no Git operation in progress.
Unknown post-effect outcomes or pending integrated cleanup remain recoverable
and cannot be hidden by abandonment. Recompute the halt only after a safe
disposition. Verified integration cleanup
continues to use the shared temporary-worktree completion procedure.

## Trust, delivery and verification

State records are versioned and bounded. Unknown schemas, malformed records,
unsafe state parents, symlinks, non-regular or multiply linked files and foreign
ownership refuse mutation. Excess history refuses rather than silently dropping
old scope reservations. Worker identity and stopped-writer flags are assertions
by the coordinator based on host results, not an operating-system liveness
proof. No generic process-killing or agent-spawning service is introduced.

The installed script, workflow and resume-agent definitions ship together.
Claude supports worktree task lifecycle; Codex can develop and exercise the
shared CLI but still refuses worktree `workspace` lifecycle calls. Submodule
exclusions remain until the separate S1 support change lands. Ignored nested
repositories remain ordinary sequential tasks.

Verification uses real Git repositories for pool refill, dependencies, retained
scope collisions, concurrent claims, exact resume, rebase/fast-forward and
checkpoint crashes before and after removal. Corrupt task closure and archive
proof must refuse. Status and abandonment tests compare task/evidence bytes to
prove they remain untouched. Retention tests cover the documented Git-visible
host cleanup condition; durability tests assert synchronization order and
retention on sync failures, without claiming to simulate power loss. Contract tests check workflow routing and both
runtime payloads; full QA and native receipt gates remain required.

## Known ceiling

Native Claude bootstrap/bind/continuation was not exercised in the local Codex
development runtime. The same installed helpers are tested with real Git and
process interruption; validate native dispatch when a live Claude runtime is
available. A host without a continuation channel retains the reservation and
worktree and reports that blocker; it does not authorize an unbound worker.
