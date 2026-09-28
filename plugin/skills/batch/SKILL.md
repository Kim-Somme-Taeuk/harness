---
name: batch
description: Coordinator procedure for running several independent harness tasks in parallel from one session, one harness:task-lead per linked git worktree, rebased, fast-forwarded, and verified afterward.
argument-hint: <N requests, each with a slug and declared path scope>
user-invocable: true
allowed-tools: Read, Glob, Grep, Bash, Agent, Skill
---

Run N independent harness tasks in parallel, one `harness:task-lead` subagent
per task in its own linked git worktree, then rebase and fast-forward,
harvest, and verify.

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
collision, but only after the fast-forward, so reject a reused slug here
instead.

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
     script cannot read: it could hide a nested repo. So does a
     `.claude/worktrees/` that is not gitignored (step b.3).
   - `verdict: "adjust"`: drop each `excluded_requests` entry (step a), move
     one request of each `overlaps` pair to a later wave, and rerun.
2. `.claude/settings.json` must have `"worktree": {"baseRef": "head"}`. If it
   is missing or set to anything else, stop and instruct the user to add it —
   this skill does not edit a project's own settings file (C-15: user-owned
   settings are not overwritten by a skill).
3. `.claude/worktrees/` must be gitignored. The step b.1 script checks this
   at the path git actually sees (report key `worktrees_ignore`) and refuses
   otherwise; a `.claude` symlink that leads outside the repository passes.
   On that refusal, stop and instruct the user to add the path the refusal
   names to `.gitignore`.
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

## d) Collect results, rebase, and fast-forward

Each lead returns a fenced JSON block: `{"task_id","worktree","branch","commit","verdict","blocked_reason"}`.

Leads are integrated by rebase and fast-forward, never by a merge commit, so
the main branch history stays linear. `batch_finish.py` runs this whole step
for one lead.

Before invoking the helper, read
`${CLAUDE_PLUGIN_ROOT}/skills/run/worktree-completion.md` and apply its
ownership, stopped-writer and evidence-preservation checks, including ignored
content. Keep the normal helper order: rebase, fast-forward, harvest, remove,
then combined review/QA in step e.

1. For every lead with `verdict: "closed"`, **in order**, from the main
   checkout:
   `PYTHONDONTWRITEBYTECODE=1 python3 ${CLAUDE_PLUGIN_ROOT}/scripts/batch_finish.py --repo <main checkout> --worktree <W> --branch <branch> --task-id <id> --commit <commit>`
   It first checks, and changes nothing when a check fails: `<commit>` is the
   branch tip, the lead worktree is clean, the main checkout is clean and on
   a branch, and the branch holds no merge commit
   (`git rev-list --merges "$(git rev-parse HEAD)..<branch>"` prints
   nothing), because a rebase would drop whatever a merge commit itself
   changed. Then it rebases inside the lead's worktree, where the branch is
   checked out (`git -C <W> rebase --no-autostash "$(git rev-parse HEAD)"`),
   fast-forwards the main checkout (`git merge --ff-only <branch>`), copies
   the lead's gitignored task evidence and learnings into the main checkout
   with `batch_harvest.py` before the worktree is gone, releases Claude
   Code's agent lock only when `git worktree list --porcelain` shows one
   (`git worktree unlock <W>`), and runs `git worktree remove <W>` and
   `git branch -d <branch>`. The script never stashes or passes `--force`;
   around it, never stash, pass `--force`, or fall back to a merge commit
   either. Run it only for a lead that has returned: never unlock a worktree
   whose lead is still running.
2. It prints one JSON result (`status`, `reason`, `conflicted_paths`,
   `returned_commit`, `branch_tip`, `integrated_tip`, `trailer_present`,
   `harvest`, `cleanup`). Act on `status`:
   - `integrated` (exit 0): record `integrated_tip`, the main HEAD after the
     fast-forward; the lead's returned `commit` is its pre-rebase tip, and
     every lead after the first gets new commit ids. Go on to the next
     closed lead.
   - `kept` (exit 3): keep the worktree, report the lead as kept like a
     blocked lead with `reason`, and go on to the next closed lead. Causes: a
     failed check (merge commit, dirty lead worktree, a returned commit that
     is not the tip, a rebase already in progress); a rebase failure without
     conflicted paths (an untracked file the rebase would overwrite, a hook
     or signing failure), after which the script lists
     `git -C <W> diff --name-only --diff-filter=U` and, when a rebase is in
     progress, runs `git -C <W> rebase --abort`, which puts the lead's branch
     and worktree back exactly as the lead left them; a harvest refusal; a
     removal refusal; or a `git branch -d` refusal. When `integrated_tip` is
     set, the lead's commits are already on the main branch and only what
     `cleanup` shows as not removed was kept: the worktree (and, after a
     harvest refusal, its evidence), which rerunning the step d.1 command
     with `--resume` finishes once the cause is fixed; or, when
     `cleanup.removed` is true, just the branch, which you delete with
     `git branch -d <branch>` once the cause is fixed. If `git worktree remove`
     refused because a submodule was initialized in the worktree, keep it
     and report it like a blocked lead: `--force` would delete the
     worktree's module store and any submodule commit that exists nowhere
     else.
   - `conflict` (exit 4): the rebase stopped on `conflicted_paths` and the
     script aborted it. Stop integrating further leads from this wave and
     carry the conflict into the integration task (step e). Do not resolve
     conflicts here.
   - `ff-refused` (exit 5): the main checkout is not clean, is detached or
     changed branch identity, or `git merge --ff-only` refused because it
     moved. Stop integrating and report it before step e. Check
     `integrated_tip`: the original main branch may already hold the lead
     when a post-merge hook switches checkout. When `branch_tip`
     differs from `returned_commit`, the branch was already rebased: finish
     that lead later with `--resume`.
   - Any other exit (1: unexpected error, 2: usage): stop integrating and
     report the output. A usage error caused by a value the lead returned
     (for example `"commit": null`) only concerns that lead: report it as
     kept and go on to the next closed lead.

   Whatever the status, a non-null `integrated_tip` means the lead's commits
   are already on the main branch.

A lead with `verdict: "blocked"` or `"failed"`: report it and retain its
worktree and branch while unresolved. Prefer resuming in that worktree. Once
already-copied recovery is independently reviewed and QA-passed, the coordinator
may dispose of the stopped originals only through the shared procedure's
per-change accounting, byte-verified archive and unchanged-inventory checks.
Never fabricate a closed lead result for `batch_finish.py` or change original
task status/receipts to enable cleanup.

## e) Integration task

When step d ends — every closed lead fast-forwarded or kept, or integration
stopped at a conflict carried from step d.2 — open
`TASK__batch-integrate-<slug>` in the **main checkout** through the normal
`harness:run` lifecycle (`task_start` → plan → develop → QA → close). Under
that task:

1. Resolve any conflict carried from step d.2 under this task: rerun the
   rebase in that lead's worktree
   (`git -C <W> rebase --no-autostash "$(git rev-parse HEAD)"`), resolve each
   stopped commit in the worktree's files, `git -C <W> add <paths>`, and
   `GIT_EDITOR=true git -C <W> rebase --continue` (without an editor,
   `--continue` fails); repeat for each commit the rebase stops at. Then
   rerun the step d.1 command with `--resume`: the branch tip is no longer
   the `commit` the lead returned, which `--resume` accepts, and the script
   fast-forwards, harvests, and removes that lead's worktree as in step d.
   Then continue step d in order for every remaining closed lead of the
   wave, resolving any further conflicts under this same task, so every
   closed lead not kept in step d is on the main branch before the full
   suite runs.
2. Run the full suite (e.g. `uv run pytest tests/ -q`).
3. Run `review-code` and `qa-cli`. Scope `review-code` by § Batch integration
   review scope in `plugin/skills/develop/quality-audit-pipeline.md`: give the
   reviewer each lead's `old_base`, `old_tip`, `new_base`, and `new_tip`, its
   patch-id result, and carried or residual status.
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

Give the user a table: task slug → branch → verdict → the lead's returned
`commit` → integrated tip (`integrated_tip` from `batch_finish.py`). Instead
of a tip, write "kept, unmerged" for blocked/failed leads and, with the
`reason`, for closed leads the script kept before the fast-forward (merge
commit, dirty worktree, rebase failure); write "integrated, worktree kept"
with the tip and the `reason` for a `kept` result that carries an
`integrated_tip` (harvest or removal refusal), or "integrated, branch kept"
when its `cleanup.removed` is true (`git branch -d` refusal). A confirmed
`integrated_tip` takes precedence over status, including `error` or
`ff-refused`: report that integration succeeded and include the failure and
remaining cleanup. For a failed merge attempt with a null tip, inspect
`reason`: report "integration unknown" when reconciliation could not finish,
and "not integrated" only when absence was confirmed. Closed leads whose
integration was never attempted are "not integrated". Note every lead
whose result has `trailer_present: false`: its commits carry no
`Harness-Task` trailer. Add a row for every request the
preflight kept out of the wave: "excluded (ordinary task, done or pending)",
"deferred to a later wave", or "outside the root, not batchable". End with
the integration task's verdict. Distinguish unresolved retained originals from
verified recovery: report the recovery destination/tip and actual worktree and
branch removal, or the retained path/branch, blocker and next action. Do not
claim overall completion while owned cleanup remains unresolved.
