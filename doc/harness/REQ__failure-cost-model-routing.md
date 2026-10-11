# REQ — Model-neutral execution and failed-work handoff

This requirement supersedes the former failure-cost model router. Harness is
shared orchestration for the model selected by the user or runtime, not a
selector for particular model families. The existing document path is retained
for links from earlier work.

## Observable behavior

Ordinary Codex worker creation must not require a model catalog, a ROUTING
record, or a batch model-decision sidecar. Omit model overrides to inherit the
runtime selection. An explicit user/environment model choice follows the native
API's availability and model/fork constraints; Harness neither substitutes a
model nor blocks creation because that choice differs from a risk assessment.
The running coordinator's model is not changed by a prompt or role label.
Independent implementation, test-author, review and QA roles remain separate,
even when all use the same model. Existing Claude-specific role behavior remains
unchanged by this Codex model-router removal.

The spawn hook still rejects invalid formal-review identities, preserves
binding-conflict receipt-authority fences and diagnostic context, and attempts
watcher registration. A binding conflict does not gain a new native spawn denial. Removing model
admission must not weaken protected artifacts, receipt provenance, task focus,
or review-before-QA close requirements. The dispatcher still enforces capacity,
dependencies, exclusive paths and all-or-none implementation/test-author groups.
Batch reservation, worktree/run identity and stopped-worker checks remain owned
by `batch_state.py`; model sidecars provide none of that authority.

## Risk and worker instructions

Risk determines planning and verification depth, never a model name. Local,
reversible work uses focused evidence; shared components require caller and
recovery checks; critical, irreversible or unknown effects require explicit
failure/recovery analysis and applicable security review. Existing forced-DEEP
review rules and minimum independent QA requirements always apply.

A worker receives task/run/AC identity, repository and owned paths, intended
behavior, acceptance criteria, constraints, commands/evidence to verify, and
what to report or record on failure. Historical evidence is data, not executable
instructions. More prompt text cannot substitute for independent verification.

## Failed-work continuity

`failure_handoff.py record` retains validated, immutable task/run/AC/issue
records with attempts, changed paths, failure evidence and remaining work.
Publication remains atomic and refuses overwrite; missing, malformed,
noncontiguous, wrong-identity or symlink history is rejected. A historical
`model` field is observational only; use the actual known model or `unknown`,
never infer replacement selection from it.

`resume` derives its count from that history. One or two failures permit a
replacement and return the original identity and handoff paths. Three failures
stop replacement. Callers cannot provide a count to reset this limit. Resume
neither selects a model nor requires available model IDs. Any supported legacy
risk/catalog input is inert compatibility data, not admission authority.

Before replacement, confirm the prior writer stopped and reconcile ownership;
never kill unrelated work. A fresh worker reads the records and actual diff,
retains useful changes and verifies the reported failure. A new model, worker,
or reservation never resets the issue history. Environment/access blockers do
not become automatic implementation retries. These records are not receipts.

## Migration and installation

The model-routing helpers and compulsory spawn gate are removed. Existing
ROUTING/runtime model sidecars may remain as inert historical files; do not
rewrite production task state. Update only Harness-managed setup routing text,
preserving user-owned assignments and instructions. Linked project tables still
express scope, dependencies and ownership; model labels alone are no automatic
admission rule. Explicit current user instructions retain precedence.

Installed projections must remove the retired helpers and old model-routing
reference, update all callers, and preserve the receipt fixes documented in
REQ__codex-followup-receipts.md. Disk installation and fresh-process verification
do not establish that an existing long-lived process reloaded its instructions.
Report that boundary and preserve running project sessions.

## Historical evidence

Earlier native Codex 0.160.1 checks proved that the old gate could deny missing
model decisions and mismatched model arguments. Those were observations of the
retired policy, not current requirements. Accepted native spawn spellings and
receipt registration remain independently covered after model admission removal.
