# Codex failure-cost routing

Before each implementation/task-lead spawn, run
`python3 "${HARNESS_PLUGIN_ROOT}/scripts/model_routing.py"` with a JSON object
on stdin. Use its `spawn_args` in the native `spawn_agent` call; only `action:
spawn` authorizes model selection. The helper does not admit workers or execute
them: retain `parallel_dispatch.py` capacity, dependency and path-ownership gates.

Assess each task or AC from PLAN and inspected code, recording the reason in the
existing routing table. `impact` is `local` for an isolated failure,
`component` for a recoverable shared-component failure, or `critical` for
security/permissions, data integrity, production availability or irreversible
external effects. `recovery` is `easy` for a verified ordinary rollback,
`costly` for manual repair, or `irreversible` for unrecoverable effects. Missing
or uncertain evidence uses `unknown`; do not infer low risk from small size.
A task lead assesses the whole task; each AC assesses its own affected surface.

Example input (take model IDs from the actual native tool schema):
```json
{"impact":"local","recovery":"easy","failed_attempts":0,"available_models":["gpt-6.1-sol","gpt-6-astra"]}
```
Low/Medium use Sol, High uses Astra. Unsupported models block dispatch; do not
silently downgrade. This explicitly authorizes these model overrides. New
agents use `fork_turns: none`; provide task/run/AC identity, repository/worktree,
PLAN context, ownership, constraints, acceptance tests and relevant evidence in
the prompt. The coordinator's own model is unchanged. Independent ACs may use
different models concurrently. Review/QA retain their existing model policy.
Paired test authors use the same AC assessment and native spawn arguments.

After an implementation attempt fails its scoped acceptance checks, increment
`failed_attempts` for that same issue in the existing coordinator progress notes
and rerun the helper. The first failure selects Astra; three failed attempts
stop for coordinator/user resolution. Model changes never reset this count.
Environment/authentication failures and ownership disputes are blockers to
resolve, not reasons to repeatedly buy another model attempt.

For escalation, stop the old writer and confirm it has stopped, reconcile its
changes and release ownership/host capacity before admitting a replacement.
`followup_task` cannot change models: spawn a new uniquely named Astra worker
with the original task/run/AC and exact failure evidence. For a bound batch
lead use the batch release/reclaim/bind protocol; if replacement cannot be bound,
report that capability blocker. Never forge a binding or reuse stale PASS.
Keep all receipt generations and normal independent review-before-QA gates.
