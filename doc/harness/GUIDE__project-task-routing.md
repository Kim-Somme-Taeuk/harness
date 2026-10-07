# Discover project task routing before choosing work

Before selecting, dispatching, or resuming implementation work, read the project's
AGENTS.md and active PLAN, then open the task classification/routing table they
explicitly link. Conversation history does not substitute for this read. Re-read
the table before choosing each next task so another session's progress is visible.

A project may assign one persistent Sol session all Sol tasks and one persistent
Astra session all Astra tasks. Select only ready tasks assigned to the current
session's role. Respect dependencies, stopped/completed ownership, and exclusive
file scopes; the table does not permit concurrent writes to shared files or
override Harness's single active task focus. Claim/release work using the project's
existing ownership procedure, without inventing a Harness state schema.

Check the actual running model from runtime evidence separately from the assigned
role. If they differ, report both and hand off to the matching session or wait for
the operator to resolve the mismatch before implementation. A role label cannot
switch the current model. An explicitly authorized worker delegation still uses
the existing routing and ownership protocol; it does not change the coordinator.

The table supplies project scope, dependencies, ownership and intended assignment.
`model_routing.py` and `routing_state.py` remain authoritative for model calculation
and spawn admission, including failure escalation. Reconcile a disagreement with
the table before implementation; never force an old table model past the router.

If no table is declared, continue the ordinary Harness route without inventing a
role or requiring a table for trivial tasks. If the user explicitly requests a
persistent multi-session division and no table exists, persist that division under
the project's `doc/` and explicitly link it from AGENTS.md or the active PLAN
before implementation. A declared but missing or ambiguous table is a routing
blocker to report and resolve, not permission to reconstruct it from memory.

New setups emit discovery guidance through setup_finalize.py's bounded routing
block. Canonical Codex run startup reads the linked table before task selection;
develop/model-routing.md carries that intent into model admission. Project-specific
table paths and task IDs stay in project instructions, not generic Harness code.
