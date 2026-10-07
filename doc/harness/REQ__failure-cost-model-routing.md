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

Native enforcement requires the host to invoke and honor PreToolUse. An October
7 probe in this container started an invalid-review-name worker even though the
installed hook returned deny for the same input. Therefore local gate tests and
payload installation alone cannot prove native enforcement. Native model metadata
and actual denied calls are required for the requested end-to-end acceptance.

## Known ceiling

The continuation probe confirmed Low→Sol, High→Astra and an observed Sol
assertion failure followed by an Astra replacement, using native rollout
`turn_context.model` metadata. A missing-decision worker still started despite
local hook denial in both the target and native cwd. Model selection and handoff
are therefore observed, while host-enforced denial remains unmet. Review/QA
receipt collection is a separate host capability and cannot be inferred from
these model probes.

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
