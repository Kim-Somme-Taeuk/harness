---
name: batch
description: Coordinator procedure for running several independent harness tasks in parallel from one session, one harness:task-lead per linked git worktree, merged and verified afterward.
argument-hint: <N requests, each with a slug and declared path scope>
user-invocable: true
allowed-tools: Read, Glob, Grep, Bash, Agent, Skill
---

Run N independent harness tasks in parallel, one `harness:task-lead` subagent
per task in its own linked git worktree, then merge, harvest, and verify.

See `doc/harness/REQ__parallel-tasks-via-worktree-leads.md` for the full model
and rationale.

## a) Intake

Collect N requests. Each needs a slug and a declared path scope (the files or
directories it is expected to touch). Requests whose declared scopes overlap,
or where one depends on another's output, are not independent: sequence them
into a later wave instead of running them in the same parallel batch.

Slugs must be distinct within the batch, and none may already name a task in
the main checkout (`doc/harness/tasks/TASK__<slug>`) or an archived lead
(`doc/harness/archive/batch/TASK__<slug>`). Harvest refuses an archive
collision, but only after the merge, so reject a reused slug here instead.

The preflight script (step b.1) classifies every declared scope path. Only a
`tracked-area` scope may run in a lead. A request with a scope
`inside-submodule` or `inside-ignored-nested-repo` is not batched: run it as
an ordinary harness task in the main checkout, before or after the wave, never
while one runs (step b.4). An `outside-root` scope cannot run in a batch lead
at all.

## b) Preflight

Before spawning anything:

1. Run the repo-shape preflight for exactly the wave you are about to spawn,
   one `--request` per declared scope path (repeat the slug for a second
   path; a comma list is refused):
   `PYTHONDONTWRITEBYTECODE=1 python3 ${CLAUDE_PLUGIN_ROOT}/scripts/batch_preflight.py --repo <main checkout> --request <slug>=<path> --request <slug>=<path2> ...`
   Spawn only when it exits 0 (`verdict: "ok"`) and steps b.2–b.5 hold. It
   prints a JSON report:
   - `verdict: "refuse"`: batch must not start; stop and tell the user the
     `refusals`. Every control-root shape but `ok` refuses: a
     `submodule-checkout`, a `linked-worktree`, a `non-git` directory, or a
     `separate-git-dir` checkout. The clean check covers more than the main
     checkout: `git status --porcelain` must be empty there, in every
     populated submodule, and in every ignored nested repo, so tell the user
     to commit or stash in the named repo. A post-checkout hook that mentions
     `submodule` in a repository with submodules also refuses, because it
     would initialize them in every lead worktree. So does a directory the
     script cannot read: it could hide a nested repo.
   - `verdict: "adjust"`: drop each `excluded_requests` entry (step a), move
     one request of each `overlaps` pair to a later wave, and rerun.
2. `.claude/settings.json` must have `"worktree": {"baseRef": "head"}`. If it
   is missing or set to anything else, stop and instruct the user to add it —
   this skill does not edit a project's own settings file (C-15: user-owned
   settings are not overwritten by a skill).
3. `.claude/worktrees/` must be gitignored (`git check-ignore .claude/worktrees/x`).
   If it is not ignored, stop and instruct the user to add it.
4. No harness task may be open in the main checkout for this session while a
   wave runs: if the session's `[harness-context]` names an open task, park it
   with `task_blocked` or close it first. A lead's late lens stop that
   outlives its removed worktree resolves to the main checkout and must find
   nothing to bind to there.
5. Record `git rev-parse HEAD` in the main checkout. Every lead gets this sha
   and refuses to start if its own worktree HEAD differs.

## c) Spawn one wave

Spawn every lead of the current wave in **one assistant message** — this is
what makes them concurrent. Each spawn:

```
Agent(subagent_type: "harness:task-lead", prompt: "<request text>\nslug: <slug>\nscope: <declared path scope>\noff-limits: <preflight off_limits, comma-separated, or none>\ncoordinator HEAD: <sha from step b.5>\npytest worker cap: 4")
```

`off-limits` lists every submodule and nested repo path from the preflight
report. An ignored nested repo does not exist in a lead worktree, so the lead
cannot see what it must not write.

Do not pass `name=`: with agent teams enabled a named spawn launches a
teammate, which gets no `isolation: worktree`. Default to at most **3 concurrent leads** per wave; raise
the cap only when the user explicitly asks for more in this conversation — a
9p/drvfs mount, a `.venv` built per worktree, and `pytest -n auto` per lead
oversubscribe CPU and IO past that point (see the REQ doc).

## d) Collect results and merge

Each lead returns a fenced JSON block: `{"task_id","worktree","branch","commit","verdict","blocked_reason"}`.

For every lead with `verdict: "closed"`, **in order**, in the main checkout:

1. `git merge --no-ff <branch>`
2. On conflict: `git merge --abort` immediately, stop merging further leads
   from this wave, and carry the conflict into the integration task (step e).
   Do not resolve conflicts here.
3. On a clean merge: run
   `PYTHONDONTWRITEBYTECODE=1 python3 ${CLAUDE_PLUGIN_ROOT}/scripts/batch_harvest.py --worktree <W> --task-id <id>`
   to copy the lead's gitignored task evidence and learnings into the main
   checkout before the worktree is gone. A non-zero exit (unmerged branch,
   symlinked or non-regular evidence, an archive that already holds different
   evidence for the same task id) stops removal of that worktree.
4. The lead has returned, but Claude Code keeps its agent lock on the
   worktree, so release it first: `git worktree unlock <W>`. Then
   `git worktree remove <W>` and `git branch -d <branch>`. Never pass
   `--force` to either — a failure there (dirty worktree, unmerged branch)
   means something is wrong and must be looked at, not overridden. Never
   unlock a worktree whose lead is still running. If `git worktree remove`
   refuses because a submodule was initialized in the worktree, keep it and
   report it like a blocked lead: `--force` would delete the worktree's
   module store and any submodule commit that exists nowhere else.

A lead with `verdict: "blocked"` or `"failed"`: report it, and leave its
worktree and branch in place — never remove or force-remove them. The
coordinator or the user resolves it directly in that worktree later.

## e) Integration task

When step d ends — every closed lead merged, or merging stopped at a conflict
carried from step d.2 — open
`TASK__batch-integrate-<slug>` in the **main checkout** through the normal
`harness:run` lifecycle (`task_start` → plan → develop → QA → close). Under
that task:

1. Resolve any conflicts carried from step d.2: `git merge --no-ff <branch>`
   again under this task, resolve, commit, then harvest and remove that
   lead's worktree exactly as in steps d.3–d.4. Then continue steps d.1–d.4
   in order for every remaining closed lead of the wave, resolving any further
   conflicts under this same task, so every closed lead is merged before the
   full suite runs.
2. Run the full suite (e.g. `uv run pytest tests/ -q`).
3. Run `review-code` and `qa-cli`.
4. In this plugin source repo, before `task_close`, run
   `python3 plugin/scripts/install_verified.py --task-dir <integration task dir>`
   — this is the only place `install_verified.py` runs in batch mode; leads
   skip it.
5. Close.

## f) Host visibility

Tell the user their host git client (e.g. GitKraken over a drvfs mount) can
inspect this work through **branches and commits only**. Never instruct the
user to open a worktree folder directly on the host. Never run
`git worktree prune` or a host client's worktree cleanup while any lead
worktree exists: from the host every container worktree path looks missing,
and prune deletes the metadata of every **unlocked** one (the Claude lock is
what protects a running lead and, while this session runs, a returned one;
kept blocked/failed worktrees lose it once that lock is released, and the
unlock → remove gap never has it).

## g) Report

Give the user a table: task slug → branch → verdict → merge commit (or
"kept, unmerged" for blocked/failed leads). Add a row for every request the
preflight kept out of the wave: "excluded (ordinary task, done or pending)",
"deferred to a later wave", or "outside the root, not batchable". End with
the integration task's verdict.
