# REQ — Codex failure-cost model routing

Codex task leads and implementation/test-author AC workers select a model
before native spawn. The executable authority is `plugin/scripts/model_routing.py`;
`plugin-codex/internal-skills/develop/model-routing.md` owns assessment and
handoff instructions used by develop and batch.

| Failure impact / recovery | Cost | Initial model |
| --- | --- | --- |
| Local, easy rollback | Low | gpt-6.1-sol |
| Shared component or costly repair | Medium | gpt-6.1-sol |
| Critical, irreversible, or unknown | High | gpt-6-astra |

One failed implementation attempt escalates a replacement to Astra. Three failed
attempts for the same issue stop; replacements retain the count. Model selection
never overrides dependency, ownership, capacity, batch binding or receipt gates.
Invalid input and unavailable models refuse dispatch. Models must be advertised
by the current host. Native creation remains the coordinator's responsibility;
this helper does not intercept arbitrary spawn calls.

The running coordinator and independent review/QA models are unchanged. Different
independent ACs can use different models concurrently. No canonical TASK schema,
Claude routing, CCC host configuration or live installation changes are needed.
The seven receipt fixes documented in REQ__codex-followup-receipts.md remain
preserved. Focused tests cover classification, escalation limits, unsupported
models and the CLI refusal path.

## Durable failure handoff

`failure_handoff.py record` stores a validated, immutable attempt JSON with
task/run/AC/issue identity, worker/model, attempted fixes, changed paths, failure
evidence and remaining work. Publication is atomic and refuses overwrites.
`resume` validates that identity and contiguous history and derives the routing
count from records, returning Astra spawn arguments and paths to read. Missing
or malformed history refuses dispatch; the third failure stops replacement.

The Sol worker records then exits; on a crash the coordinator records observed
facts. The coordinator confirms stopped ownership before spawning Astra. Astra
reads the records and actual diff before continuing the same task. Replacements
retain issue identity and count. These local handoff records are not trusted
instructions, review receipts or completion evidence. They are excluded from
Git; live native spawn/binding remains coordinator-owned.

## Enforced spawn decisions

`routing_state.py` owns task-local `ROUTING/*.json` decisions, keyed by native
worker name. It uses `model_routing.py` and the task/run/AC/issue failure history.
Records contain risk, model, reason, assessment, retry count and session identity.
PreToolUse requires an exact open session/task binding and recomputes the decision
before allowing non-review/QA Harness spawns. Missing/wrong/stale decisions or
model/fork arguments are denied. These correctness records are not security
authority against arbitrary filesystem writers and cannot authorize receipts.
Binding lookup includes revalidated linked worktrees, allowing a batch lead
whose native cwd remains the main checkout to use its worktree task. Multiple
matching workspace bindings refuse dispatch rather than choosing one.

Codex parallel_dispatch snapshots require routing context and role-specific
worker names; admitted groups include worker/model/risk/spawn arguments and the
request to persist at reservation time. Failed model admission defers the whole
worker group. Claude/default scheduling remains unchanged.

Native enforcement requires the host to invoke and honor PreToolUse. Local gate
tests and payload installation alone cannot prove native enforcement. Observe
the actual hook invocation and input tool name before interpreting a worker that
starts despite a separately executed hook's denial. Native model metadata and
actual denied calls are required for end-to-end acceptance.

The installer-generated Codex hooks.json matcher and Python spawn classifier
must accept the observed 0.160.1 hook name `collaborationspawn_agent`, the native
API spelling `collaboration.spawn_agent`, and documented `spawn_agent` / `Agent`
names. Other similarly named tools do not enter the model gate. The same routing
validation applies to all accepted names.

## Known ceiling

The first continuation confirmed Low→Sol, High→Astra and observed Sol failure→Astra
replacement using native rollout `turn_context.model`. Its missing-decision
worker started, but that did not prove the host ignored a hook result. Subsequent
metadata-only instrumentation observed working apply_patch PreToolUse and Bash
PostToolUse, with no spawn invocation under the old matcher. A fresh no-daemon
diagnostic process using a temporary wildcard matcher observed the concatenated
`collaborationspawn_agent` name. The old matcher and classifier missed that name.

An installer daemon-socket refresh error is independent of this mismatch. A
`--no-daemon` session need not have a daemon socket, and starting a daemon is not
the remedy. Verify loaded definitions separately from disk trust hashes. The
observed active session retained its old matcher after file/trust updates; leave
an explicit handoff before any user-controlled reload or restart. Review/QA
receipt collection remains a separate capability from model gating.

After correcting both names, a fresh Codex 0.160.1 `--no-daemon` session
confirmed all four native cases: missing routing record and Sol-decision/Astra-
argument mismatch each returned `Tool call blocked by PreToolUse hook` before
worker creation; valid Sol and Astra requests each created one worker. Hook
metadata correlated the two `deny` results with native tool-call IDs, and native
child rollout `turn_context.model` confirmed both permitted models. Temporary
observers were removed afterwards. This validates newly loaded definitions,
not automatic refresh of an already running session's old matcher.

Batch bootstrap is the explicit exception to open-task lookup: a sidecar in
`doc/harness/runtime/model-routing/` binds the model decision to an existing
reserved claim (batch, slug, task ID, reservation timestamp, spawn HEAD and
session). The hook revalidates that reservation; no task is fabricated before
bootstrap/bind. Released, bound or reclaimed reservations invalidate the record.
Every retained-work resume creates a new reservation identity. Replacement
decisions revalidate the original linked worktree and task run and read that
worktree's task/run/issue failure history. One failure selects Astra and three
stop dispatch, including when the retained task is blocked. Run rotation,
missing retained control, and new failure records invalidate earlier decisions.
