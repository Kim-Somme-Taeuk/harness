# Discover project ownership before choosing work

Before selecting, dispatching or resuming implementation, read AGENTS.md and the
active PLAN, then any task classification/routing table they explicitly link.
Re-read before selecting the next task so another session's progress is visible.
Conversation history does not substitute for current ownership evidence.

Select ready work assigned to the session's responsibility, respecting
dependencies, exclusive file scopes and stopped/completed ownership. A table
does not permit concurrent writes to shared files or override Harness task focus.
Use the project's existing claim/release procedure without a new state schema.

Harness does not require model-specific session roles. Model labels in older
tables do not create an automatic runtime admission gate. Use the user's or
runtime's selected model; honor explicit current model instructions within the
native API's capabilities. Never claim that a role label switched a running
coordinator's model. Independent review and QA remain required for any model.

If no table is declared, proceed without inventing one. If the user requests a
persistent multi-session division and no table exists, document responsibilities
under project doc/ and link from AGENTS.md or PLAN before implementation. Resolve
a declared missing or ambiguous ownership table; do not reconstruct it from memory.

New setups emit this guidance through setup_finalize.py's bounded managed
routing block. Refresh that block without rewriting unmanaged project text.
Codex run startup reads linked assignments; develop/failure-handoff.md supplies
model-neutral worker context and retry procedure. Project-specific paths and
IDs belong in project instructions, not generic Harness code.
