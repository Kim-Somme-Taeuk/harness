---
tags: [harness, lifecycle, worktree, batch, mcp, contracts]
summary: 한 Claude 세션이 과제마다 격리 worktree 리드 서브에이전트를 띄워 여러 harness 과제를 병렬로 진행한다. MCP task 도구는 검증된 workspace 인자로 worktree 안의 과제를 다루고, 세션 식별은 본 체크아웃에 남는다. 병합 후 통합 과제가 전체 검증과 설치를 맡는다.
updated: 2026-09-27
freshness: current
invalidated_by_paths:
  - plugin/mcp/harness_server.py
  - plugin/scripts/_lib.py
  - plugin/scripts/batch_harvest.py
  - plugin/agents/task-lead.md
  - plugin/skills/batch/SKILL.md
  - CONTRACTS.md
freshness_updated: 2026-09-27T09:25:53Z
---

# REQ — parallel tasks in one session via worktree leads

## Standing user requirements (2026-09-27)

- Parallelism happens inside **one** Claude Code session. Multiple terminals or
  sessions, `claude -p` background sessions, and agent teams are not the
  answer for this user, even though other tools run many agents that way.
- The repository runs in a container at a different path than the Windows
  host, where it is inspected with GitKraken. The user explicitly chose
  **not** to use relative-path worktrees and accepted "work in a worktree,
  then merge", with the host looking at branches and commits only.

## Requirement

- One Claude Code session can run several harness tasks at once. The main
  session is the coordinator. It spawns one `harness:task-lead` subagent per
  task, and each lead runs in its own linked git worktree (Claude Code
  `isolation: worktree`, under `<repo>/.claude/worktrees/<name>`).
- Each linked worktree is a separate checkout with its own write focus (C-09).
  Task state under `doc/harness/tasks/` is gitignored, so every worktree has
  its own task namespace, focus markers, and `RECEIPTS.jsonl`.
- A lead runs the normal lifecycle (`task_start` → plan → develop → review/QA
  → `task_close`) inside its worktree and commits on its branch. It never asks
  the user; undelegated material decisions go back to the coordinator.
- The coordinator merges lead branches into the main checkout one at a time,
  harvests each lead's task evidence, then removes the worktree and branch.
  After all merges it opens one integration task in the main checkout that runs
  the full suite, review, QA, and — in the harness source repo — the verified
  install. Leads never run `install_verified.py`.
- The coordinator procedure (intake, preflight, spawn, merge/conflict path,
  harvest, integration) is owned by `plugin/skills/batch/SKILL.md`; the lead's
  rules and its JSON return shape by `plugin/agents/task-lead.md`.
- While a wave runs, no harness task may be open in the main checkout for the
  same session. A late lens stop from a lead whose worktree was already
  removed resolves its `cwd` up to the main checkout, and it must find no open
  task there to bind to.

## MCP `workspace` argument

`task_start`, `task_context`, `write_plan`, `task_verify`, `task_close`, and
`task_blocked` accept an optional `workspace` string. It must name a registered
linked worktree of the repository the MCP server controls:

- absolute and already canonical (`realpath(workspace) == workspace`);
- `<workspace>/.git` is a regular (non-symlink) gitfile whose `gitdir:` target
  sits directly under `<control>/.git/worktrees/`;
- that target's `gitdir` back-pointer names `<workspace>/.git`;
- the workspace carries its own tracked harness manifest, so
  `harness_root_resolution(workspace)` returns the workspace itself.

Anything else is refused with `WORKSPACE_NOT_REGISTERED_WORKTREE` and nothing
is written; a non-string value is refused with `reason: wrong_type`. On the
Claude runtime a `workspace` equal to the control root is the same as omitting
it. On the Codex runtime any `workspace` is refused
(`reason: unsupported_runtime`). Omitting it keeps the previous behavior
exactly.

Task paths, focus markers, scaffolds, and `request_file` resolve under the
workspace. Session identity (the Claude session hint), watcher diagnostics, and
gate-warn learnings stay on the control root, because only the main checkout
receives `UserPromptSubmit` and every lead shares the main session id.

Hooks need no argument: they already resolve the repo from the payload `cwd`,
and a nested reviewer/QA subagent spawned by a lead runs with the worktree as
its cwd, so its receipts bind to the worktree task.

## Host visibility

The repository may be mounted into a container at a different path than the
host sees (e.g. `/project/...` over a Windows drvfs mount). Worktree metadata
stores absolute container paths, so:

- inspect lead work on the host through **branches and commits only**;
- never open a worktree folder with a host git client;
- never run `git worktree prune` (or a host client's worktree cleanup) while
  any lead worktree exists. From the host every container path looks missing,
  and prune deletes the metadata of every **unlocked** worktree. Claude Code's
  agent lock protects a running lead; kept blocked/failed worktrees and the
  moment between `git worktree unlock` and `git worktree remove` do not have
  that protection.

Relative-path worktrees (git ≥ 2.48 `extensions.relativeWorktrees`) are out of
scope by the user's decision; host clients that lack the extension also cannot
open the repository at all.

## Guards observed (live probes, 2026-09-27)

- Receipt binding (AC-003 gate, run before the lead agent and batch skill were
  written): a real `isolation: worktree` subagent at
  `.claude/worktrees/agent-aeae57aab7846dbfb` started `TASK__worktree-probe`
  through the `workspace` handler and spawned one nested
  `harness:code-reviewer`. That worktree task's `RECEIPTS.jsonl` then held
  exactly one `started` and one `completed`/`PASS` row for
  `runtime_id claude:2774b58d-f281-4368-8f64-34972245bcc3:adfefaec07fe5afcf`
  under `task_run_id 01a0e225-300e-7298-940b-c47ffdf31b0d`, and
  `task_context` reported `review_verdict: PASS`. The probe worktree was
  removed afterwards without harvest, so the rows themselves are gone; the
  repeatable regression is
  `tests/test_worktree_workspace.py::test_nested_lens_start_and_stop_in_worktree_bind_to_worktree_task`.

- Claude Code refuses the `Write` tool from an `isolation: worktree` lead to a
  main-checkout path ("This agent is isolated in the worktree ..."), and the
  same refusal holds for a nested subagent the lead spawns without isolation.
  Bash writes are not guarded by it, which matches C-05 (Harness does not
  intercept shell mutation).
- After a lead returns, its worktree stays locked
  (`locked claude agent <name> (pid ...)`) while the coordinator session
  runs, so the coordinator runs `git worktree unlock` before
  `git worktree remove`. Never unlock a worktree whose lead is still running.
- `git worktree remove` deletes gitignored files, which is why harvest runs
  first.

## Preconditions and limits

- Project `.claude/settings.json` sets `"worktree": {"baseRef": "head"}` so
  leads branch from the coordinator's local HEAD, not the remote default
  branch. Each lead refuses to start when its HEAD differs from the
  coordinator HEAD it was given.
- `.claude/worktrees/` is gitignored. This repository ignores it directly; the
  batch preflight checks it in any project and tells the user to add it.
  Adding it to setup's managed operational ignores requires a manifest
  version bump and migration (`doc/harness/REQ__versioned-project-file-migrations.md`)
  and is a follow-up.
- Default concurrency is 3 leads; more only on explicit user request. Each
  worktree builds its own `.venv`, and on a 9p/drvfs mount pytest `-n auto` per
  lead oversubscribes CPU and IO, so leads pass `-n 4`.
- Leads run the installed harness plugin, not the `plugin/` tree in their own
  worktree.
- Claude Code only. Goal tools stay on the control root; batch leads are not
  Goal children. `task_close` links a closed task only to the Goal of the
  checkout that owns it, and a lead's worktree has no Goal, so closing a lead
  never changes the coordinator's Goal. The MCP server refuses `workspace` on
  the Codex runtime (`reason: unsupported_runtime`).
- Known limit: from a lead's worktree `cwd`, the prewrite gate resolves the
  worktree as its root and lets Edit/Write targets outside it through before
  the C-05 protected-artifact check, so the main checkout's or a sibling
  worktree's `TASK.json`/`PLAN.md`/`RECEIPTS.jsonl` are not gate-denied from
  there. Claude Code's worktree isolation refuses such Write calls (observed
  above), and C-05 already leaves Bash unguarded, so this is no new
  privilege. Follow-up: apply the protected-artifact check against the target's
  own harness root.
- A failed or blocked lead's worktree is kept and reported, never
  force-removed. Evidence harvest (`plugin/scripts/batch_harvest.py`) copies
  `<worktree>/doc/harness/tasks/<task_id>` to
  `doc/harness/archive/batch/<task_id>/` and appends the lead's learnings
  before `git worktree remove` and `git branch -d`. It refuses to replace an
  existing archive that holds different evidence for the same task id.

## Verification cues

- `tests/test_worktree_workspace.py`: accepted registered worktree; refusals for
  plain directory, other repository, relative/symlinked path, missing manifest,
  forged back-pointer, non-string value, and the Codex runtime; control root
  treated as omitted; marker file named after the control-root session hint;
  `task_blocked` and full-lifecycle `task_close` leave the main checkout
  byte-identical; a lead close never touches the coordinator Goal; hook
  start and stop receipts from `cwd=<worktree>` land in the worktree task.
- `tests/test_mcp_tool_name_contracts.py`: the six task tools declare optional
  `workspace`; goal tools do not.
- `tests/test_batch_harvest.py`: copy, append, idempotence, refusal for an
  unregistered or unmerged worktree, links/FIFOs, archive collision, ambient
  `GIT_DIR`, non-canonical paths.
- `tests/test_batch_skill_contract.py`: lead frontmatter and carve-outs, every
  coordinator step, the C-09 clause in both contract files, root CLAUDE.md
  clauses, and this repository's `baseRef`/ignore settings.
- Live probe: a real worktree subagent starts a task with `workspace` and its
  nested reviewer's start/stop receipts appear in the worktree task.
