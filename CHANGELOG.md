# Changelog

## Unreleased

- **Manifest version messages** — a future manifest version now reports `manifest version N is newer than supported version 6; upgrade Harness` from both `--migrate-harness-version` and SessionStart; the setup skill's version check trims whitespace and reports `UPGRADE_AVAILABLE: unknown (...)` for a non-integer `version:` instead of `no`.

### Changed

- **Unsafe install ancestors name their fix** — when `install.py --if-stale`
  refuses a writable directory above the payload, the output now prints the
  command that fixes it (`chmod go-w`, or `sudo chown … && chmod go-w` for a
  root-owned config dir in your home) instead of a `--force` that cannot help.
- **Install guard watches the Claude plugin cache** — the suite's removal guard
  and the verification-gate snapshot now include
  `~/.claude/plugins/cache/harness/harness`, skipping only versions the Claude
  CLI had already orphaned before the run.
- **A lens that pauses is named, not crashed** — Claude lens agents run
  verification in the foreground and never end a turn while their own work is
  running. A resumed lens's second start and different final now write nothing
  and log `resumed-after-completion` / `completion-already-recorded` instead of
  a gate-crash and a misleading retryable-failure result.
- **No dead execution-mode setting** — setup no longer writes
  `execution_mode_default` to the manifest; nothing read it. Execution mode,
  planning procedure, and review depth stay per-task decisions; there is no
  install-time loop-strength setting.
- **Suite survives another interpreter's bytecode** — `tests/conftest.py`
  prunes `plugin/**/__pycache__` before collection and writes no bytecode, so a
  cache left by another CPython build sharing the `cpython-312` tag no longer
  fails collection with `StaleBytecodeCacheError`.
- **Install-tree snapshot is locale-safe** — the develop verification-gate
  Step 0.5 snapshot now runs `comm` under `LC_ALL=C` like its `sort`, so the
  removal check no longer fails on UTF-8 hosts; its executed-doc test no longer
  inherits the host `BASH_ENV`/`ENV`.
- **Installs reach the Claude plugin cache** — the installed mirror's
  `plugin.json` version carries a payload hash (`<base>+h<sha8>`) and every
  Claude install path ends with `claude plugin update harness@harness`, so hook
  changes reach the cache Claude runs from without a manual reinstall. See
  `doc/changes/2026-09-26-install-refreshes-claude-plugin-cache.md`.
- **Completion receipts without a third-party start banner** — a Claude
  `SubagentStop` whose transcript carries no `SubagentStart` attachment now binds
  to the hook-owned `started` receipt for the same runtime and run, so
  harness-only installs record completions again. See
  `doc/changes/2026-09-25-claude-stop-binds-to-hook-owned-start.md`.
- **task_blocked kept as the park record** — the planned deletion of
  `task_blocked` / `BLOCKED.md` is withdrawn now that the Claude Stop hook is
  gone. C-17 gains a Parking clause (park is not completion, no PASS, C-04
  still gates close, resume with `task_start`); existing projects get it on
  re-setup. See `doc/changes/2026-09-25-keep-task-blocked-docs-alignment.md`.
- **One plan reviewer, no develop completion audit** — full planning runs a
  single Phase 1 Plan Review (CEO premise/scope + Eng architecture/tests, 900s)
  with a UI-states/journey/accessibility checklist when `ui_scope` is true; the
  separate Design, Eng, and DX phases and `dx_scope` detection are gone.
  Develop Phase 4 haiku Plan Completion Audit is removed; formal code review's
  per-AC proof covers it. See
  `doc/changes/2026-09-24-plan-review-single-reviewer-consolidation.md`.
- **Developer contract reaches every implementer** — Claude develop now has
  the sequential coordinator Read the `developer.md` role core before editing
  (Codex parity). The core ends with `Status:` / `Known ceiling:` /
  `Assumption:` output lines, admits new packages only under an explicit rule,
  and splits blocking from defaultable ambiguity (also in `ac-worker.md` and
  both Confusion Protocols). `fix-first-pattern.md` is now a short self-check
  plus the 3-attempt rule; its AUTO-FIX table is gone. Phase 3.5/4.85 require
  new tests only for non-trivial behavior, and Phase 8.6 copies reported
  ceilings into durable docs. New `tests/evals/developer_behavior/`:
  `grade.py --selftest` in pytest, opt-in `run_live.py` baseline-vs-core eval.
  See `doc/changes/2026-09-24-developer-ponytail-gap-followups.md`.
- **Single manifest version** — the manifest `harness_version` integer is
  merged into the top-level `version` field (now 6); `doc/harness/.version`
  and `doc/harness/.format-version` are removed. **Action required:** run
  `python3 plugin/scripts/setup_finalize.py --repo <root> --migrate-harness-version`
  and commit the updated `.gitignore`, `doc/harness/manifest.yaml`, and the
  deletion of `doc/harness/.version`.
- **Plan skill review pipeline** — plan-time review phases now spawn exactly
  one independent reviewer subagent per phase instead of two (Voice A + Voice
  B). Cross-model transport, the consensus table, and the dual-voice
  degradation matrix are removed on both Claude and Codex. See
  `doc/common/REQ__process__plan-skill-review-pipeline.md`.
- **Claude `Stop` hook removed** — `plugin/hooks/hooks.json` no longer
  registers a Stop-event gate script; it produced repeated empty turns while
  the coordinator waited on background reviewers. Turn-end is no longer
  hook-gated on Claude; task completion still requires receipt-backed
  `runtime_verdict: PASS` via `task_close`, and persistent non-stop
  continuation is native `/goal` (put the close condition, e.g. "task_close
  PASS", in the goal condition). **Action required:** reinstall
  (`python3 install.py`) and reload the Claude session to drop the stale
  registration from an already-installed runtime.
- **`CONTRACTS.md` C-17 refreshed** — existing projects pick up the new,
  soft-level turn-end/continuation wording through the normal setup
  managed-block regeneration (`contract_lint.py` / setup).
- **Dormant stop-gate scripts deleted (2026-09-23)** — `plugin/scripts/stop_gate.py`
  and `plugin/scripts/hook_stop.py` had no registered caller in either runtime
  since the removal above and are removed from the tree; the revert path is
  `git revert` of the deleting commit, not a dormant file. Their
  stop_gate-only helpers (`_lib.receipt_outage_block_instruction`,
  `_lib.receipt_outage_next_action`, `subagent_lifecycle.wait_for_clear`) are
  removed with them.

## Unreleased — v2.3.0 (dual-runtime v1)

Opt-in support for OpenAI Codex CLI alongside Claude Code. Pure-additive: existing `plugin/` is untouched.

### Added

- `plugin-codex/` — Codex runtime tree. Mirrors `.claude-plugin/` with `.codex-plugin/plugin.json`, `hooks.json` (schema-identical), and generated `skills/` / `agents/` ports.
- `plugin/runtime-sync/` (planned per AC-005 in `doc/harness/tasks/TASK__dual-runtime-plugin-claude-codex/PLAN.md`) — sync engine that emits Codex tree from canonical sources.
- `plugin/scripts/_lib.runtime_is_stale` — single-source-of-truth staleness check shared by MCP `task_close` gate and Stop hook. `emit_compact_context` now always returns `stale` / `stale_path` keys.
- `doc/harness/runtime-matrix.md` — per-feature capability matrix (Claude / Codex). Read before adopting on Codex.
- `doc/harness/codex-payload-deltas.md` — Codex hook payload schemas with Claude delta. Empirically grounded in codex source + figma plugin reference.
- `doc/harness/apply-patch-matrix.md` — 13-pattern `apply_patch` vs `Edit` matrix. Binding spec for AC-005 sync engine.
- `doc/harness/codex-troubleshooting.md` — error message strings + remediation commands.
- `README.codex.md` — Codex-specific install + first-run walkthrough.

### Changed

- **CONTRACTS.md § C-17** — Staleness clause added. Stop hook permits `BLOCKED_ENV`-based stops ONLY when no `touched_paths` mtime post-dates `CRITIC__qa.md`. Closes the 2026-05-14 loophole where stale verdicts from earlier in a session permitted stops after subsequent work.
- **`plugin/scripts/stop_gate.py`** — BLOCKED_ENV branch consults `ctx["stale"]`; stale verdicts fall through to block payload with an explanatory `stale_note`.
- **`plugin/mcp/harness_server.py`** — replaced inline `_runtime_is_stale` duplicate with import from `_lib`. Single source of truth.

### Deprecated

- **`CLAUDE_PLUGIN_ROOT` env var** — renamed to `HARNESS_PLUGIN_ROOT` (AC-006). Dual-name fallback in `_lib.plugin_root_env()` reads either during deprecation. Old name will be removed in **v2.5.0**. Update your wrappers, shell rc files, and Docker images.

### Compatibility

- v1 keeps `plugin/` untouched. Claude Code users on `claude plugin update` get no surprise sibling tree — `plugin-codex/` materializes only when `harness.codex_enabled: true` in `marketplace.json` (default `false`).
- Cross-runtime task handoff (start on Claude, resume on Codex) is NOT supported in v1. Single-runtime-per-repo. Use `fcntl.flock` on `TASK_STATE.yaml` is a v2 prerequisite for parallel.

## v2.2.0

See git history.
