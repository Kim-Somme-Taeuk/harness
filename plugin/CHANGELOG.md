# harness plugin changelog

All notable changes to the harness Claude Code plugin.

## [Unreleased]

### Added

- One session can run several harness tasks in parallel with the new
  `harness:batch` skill. It spawns one `harness:task-lead` subagent per task,
  each in its own Claude Code `isolation: worktree` checkout. The coordinator
  integrates leads one at a time by rebasing each lead branch onto the main
  HEAD inside its worktree and fast-forwarding the main checkout, so batch
  history is linear with no merge commits, and harvests evidence with
  `plugin/scripts/batch_harvest.py`. An integration task then runs
  the full verification and the verified install. The task MCP tools accept an
  optional `workspace`, which must be a validated, registered linked worktree
  of the controlled repository. Task paths and focus markers resolve there,
  while session identity stays on the main checkout. Contract C-09 adds that
  each linked worktree has its own write focus. See
  `doc/harness/REQ__parallel-tasks-via-worktree-leads.md`.
- `plugin/scripts/batch_preflight.py` classifies the repository shape and each
  batch request before leads spawn. Batch refuses a control root that is a
  submodule checkout, a linked worktree, a separate-git-dir checkout, or not a
  git repository. It also refuses when the main checkout, a populated
  submodule, or an ignored nested repository is dirty or unreadable. Requests
  scoped inside a submodule or nested repository are excluded and run as
  ordinary tasks. Leads never run `git submodule` subcommands other than
  `status`.

### Removed

- Harness setup no longer creates, imports, validates, or writes
  `CONTRACTS.local.md`. Existing project-owned files are left untouched but are
  no longer loaded by the canonical managed contract. Move any still-relevant
  guidance to `AGENTS.md`, `CLAUDE.md`, or the matching durable `doc/` surface.

### Changed

- **Wave 2 parallel execution and integration** — AC plans declare owned files,
  tests and dependencies; a paired test-author and bounded one-level AC sub-split
  increase parallel work, with `develop.fanout_cap` defaulting to 4 (range 1–8).
  The coordinator runs the complete AC verification after workers return.
  See `doc/harness/patterns/ADR__within-task-parallel-width.md`.
- **Batch finish helper** — `batch_finish.py` checks a closed lead, rebases and
  fast-forwards it, harvests evidence, and reports partial integration or cleanup
  failures without forcing removal. Leads use a one-hour prompt cache and a
  `Harness-Task` commit trailer. Preflight checks the actual worktree ignore path.
- **Batch integration review scope** — Claude may carry a closed lead's proven
  patch-equivalent range; the reviewer verifies every carry and sweeps the residual.
  Combined QA and the full suite remain required.
- **Protected writes survive large payloads and child failures** — the prewrite
  gate reads the whole payload with UTF-8 surrogateescape. Claude allows 10 seconds;
  Codex allows its gate child 3 seconds and checks C-05 targets in-process after
  timeout or crash. Other writes remain fail-open; killing the whole hook can
  still bypass protection. Environment bypasses apply while set, not just once.
- **Test ledger isolation** — formerly polluting gate/codifier tests use temporary
  roots, and a session guard detects new checkout-ledger rows except documented
  live-hook writers. A receipt-readiness test also isolates `CODEX_THREAD_ID`.
- **Current contracts and documentation** — C-09 describes session focus refusal,
  C-14 describes stop-payload verdicts, stale close/cache/install guidance is
  corrected, and CI uses Python 3.12 with the project's dev dependency group.

- **Breaking:** manifest version 7. Setup's managed operational ignores now
  include `.claude/worktrees/` in every project. Existing v6 projects are
  reminded at session start and migrate with `--migrate-harness-version`,
  which refuses without stamping if anything under that path is tracked.
- The prewrite gate denies C-05 protected artifacts of *another* checkout (a
  lead writing into the main checkout's or a sibling worktree's task, goal, or
  focus files). `verify_runner` resolves a linked worktree's own root, so
  `task_verify(run_commands=true, workspace=...)` runs there.
- Codex task binding now occurs in successful `task_start`/`task_context`
  PostToolUse using the exact hook session and returned task generation. The
  shared session hint/default marker no longer selects receipt ownership,
  pre-spawn recovery never promotes it, delayed watchers replay complete real
  lifecycles from their pre-spawn checkpoint, conflicting open task results
  invalidate receipt authority instead of preserving or replacing an ambiguous
  binding and force a fresh-offset watcher registration on recovery, foreign
  MCP namespaces cannot impersonate task-result authority by
  suffix, replayed conflict results cannot cross a fence while both exact task
  generations remain open, conflict recovery locks both task controls against
  concurrent resume, and watcher failure still never blocks the agent.
- Plan review no longer turns full-depth analysis into repeated approvals.
  Explicit requests and clarifications authorize matching premises and scope;
  unresolved material decisions are collected into one post-review interaction,
  and unchanged plans proceed directly to develop unless pre-code approval was
  explicitly requested.
- `task_blocked` preserves each valid blocker field verbatim through an
  inclusive 120 KiB UTF-8 limit, rejects oversized content before mutation,
  and reports the argument that actually failed without echoing blocker prose.
  Selector guidance now matches the forms accepted by each named field. An
  already-running MCP host must be restarted after upgrade to load this fix.
- Claude subagent lifecycle state now lives only in the task's unified
  `RECEIPTS.jsonl`. The separate background registry, lock, RMW/prune state
  machine, and diagnostic records were removed; Stop-hook active-work waiting
  derives unmatched current-run/current-session starts directly from receipts.
- Receipt rows use ten string fields with one namespaced `runtime_id`. Detailed
  completion text stays in the runtime transcript while receipts retain the
  validated verdict, review counts, and a detail digest. `task_context` and
  `task_verify` no longer embed receipt summaries or duplicate report paths.
- The paired develop and four plan-review skills now stay below the 500-line
  budget by deleting repeated orchestration prose while retaining role-specific
  gates, rubrics, output contracts, and runtime interaction differences.
- Old receipt schemas and side streams have no compatibility reader. Resume
  starts a fresh `TASK.json.run_id` and resets the unified stream.
- The MCP-hosted Codex watcher correlates direct collaboration spawn, output,
  structured child activity, and final events. When activity is absent, one
  uniquely discovered trusted child rollout supplies the child identity.
- Codex installation now packages every lazily loaded methodology file named by
  its internal skills, while preserving one canonical source copy in the Claude
  skill tree.

### Fixed

- Verified delivery compares each canonical reviewed runtime payload against
  its installed tree, skips synchronized runtimes, and refreshes only stale
  payloads while pruning removed files.
- Nested-worktree micro tasks read `execution_mode` from the canonical
  four-field `TASK.json` without requiring `PLAN.md`.

## [2.2.0] — 2026-04-16

### Removed
- `plugin/agents/harness.md` — the orchestrator agent is gone. The main Claude session now routes through native Goal orchestration and internal sub-skills directly. No more agent-switching.

### Changed
- `plugin/skills/setup/bootstrap.md` §3.4 — setup emits an idempotent `## Harness routing` block (marker: `<!-- harness:routing-injected -->`) into the user's CLAUDE.md that maps normal use to native Goal orchestration plus `Skill(harness:setup)`; child-task execution, plan, develop, and review helpers are internal.
- `plugin/skills/setup/bootstrap.md` §3.4 — added migration step that strips the legacy `Default agent is harness` line from existing CLAUDE.md on Repair/Upgrade runs.
- `plugin/skills/setup/SKILL.md` — routing-injection now references the bootstrap §3.4 template with idempotency marker.
- `plugin/skills/setup/verify-report.md` — verifies routing block presence and (new) pytest availability for CLI/library projects with pytest-based test_command.
- `plugin/CLAUDE.md` — reframed intro: harness rules apply to any caller running the canonical loop (skills, MCP clients), not a specific orchestrator agent.
- `CLAUDE.md` (repo root) and `CLAUDE_CODE_HARNESS_BLUEPRINT.md` — aligned with the routing-first wording.

### Migration (existing users)
Run `/harness:setup` and choose Repair or Upgrade. Setup will:
1. Strip any legacy `Default agent is harness` line from your CLAUDE.md
2. Inject the new `## Harness routing` block (idempotent — safe to re-run)
3. Stamp `doc/harness/.version` with 2.2.0

### Fixed
- `plugin/skills/setup/SKILL.md` — `_HARNESS_VERSION` was stuck at 2.0.0 despite plugin.json being 2.1.0. Now synced to 2.2.0.
- Removed 3 stale test files (`tests/test_plugin_agent_contracts.py`, `tests/test_prompt_budget.py`, `tests/test_workflow_surface_lock.py`) that referenced non-existent paths (`plugin/settings.json`, `plugin/agents/critic-runtime.md`, `plugin/scripts/hctl.py`, `plugin/docs/orchestration-modes.md`) that never existed on `feature/v3`.
