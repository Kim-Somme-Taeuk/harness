---
tags: [harness, lifecycle, worktree, batch, mcp, contracts]
summary: 한 Claude 세션이 과제마다 격리 worktree 리드 서브에이전트를 띄워 여러 harness 과제를 병렬로 진행한다. MCP task 도구는 검증된 workspace 인자로 worktree 안의 과제를 다루고, 세션 식별은 본 체크아웃에 남는다. 병합 후 통합 과제가 전체 검증과 설치를 맡는다.
updated: 2026-09-28
freshness: current
invalidated_by_paths:
  - plugin/mcp/harness_server.py
  - plugin/scripts/prewrite_gate.py
  - plugin/scripts/_lib.py
  - plugin/scripts/batch_harvest.py
  - plugin/scripts/setup_finalize.py
  - plugin/scripts/batch_preflight.py
  - plugin/agents/task-lead.md
  - plugin/skills/batch/SKILL.md
  - CONTRACTS.md
freshness_updated: 2026-09-27T16:48:34Z
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
- (2026-09-28) Lead work lands on the main branch by **rebase and
  fast-forward**, not by merge commits: "batch작업 worktree로 분할하고
  합칠때 그냥 rebase fast-forward로 해줘". The main branch history stays
  linear.

## Requirement

- One Claude Code session can run several harness tasks at once. The main
  session is the coordinator. It spawns one `harness:task-lead` subagent per
  task, and each lead runs in its own linked git worktree (Claude Code
  `isolation: worktree`, under `<repo>/.claude/worktrees/<name>`; see
  "Worktree location").
- Each linked worktree is a separate checkout with its own write focus (C-09).
  Task state under `doc/harness/tasks/` is gitignored, so every worktree has
  its own task namespace, focus markers, and `RECEIPTS.jsonl`.
- A lead runs the normal lifecycle (`task_start` → plan → develop → review/QA
  → `task_close`) inside its worktree and commits on its branch. It never asks
  the user; undelegated material decisions go back to the coordinator.
- The coordinator integrates lead branches into the main checkout one at a
  time. For each closed lead it rebases the lead branch onto the main
  checkout's current HEAD inside the lead's worktree
  (`git -C <W> rebase --no-autostash <main HEAD>`), fast-forwards the main
  checkout (`git merge --ff-only <branch>`), harvests the lead's task
  evidence, then removes the worktree and branch. No merge commit is
  created. After every lead is integrated it opens one integration task in the
  main checkout that runs
  the full suite, review, QA, and — in the harness source repo — the verified
  install. Leads never run `install_verified.py`.
- The coordinator procedure (intake, preflight, spawn, rebase/conflict path,
  harvest, integration) is owned by `plugin/skills/batch/SKILL.md`; the lead's
  rules and its JSON return shape by `plugin/agents/task-lead.md`.
- While a wave runs, no harness task may be open in the main checkout for the
  same session. A late lens stop from a lead whose worktree was already
  removed resolves its `cwd` up to the main checkout, and it must find no open
  task there to bind to.

## Integration by rebase and fast-forward

- The rebase runs inside the lead's worktree because the lead branch is
  checked out there; git refuses to rebase it from the main checkout.
- `batch_harvest.py` accepts a lead only when the worktree HEAD is on a
  branch and is an ancestor of the main HEAD. After the rebase and
  fast-forward the two are equal. After a completed rebase without the
  fast-forward, or after a cherry-pick into main, the worktree HEAD is off
  the main history and harvest refuses. A rebase that stopped midway
  (conflict, signing failure) leaves the worktree HEAD detached; stopped at
  its first commit, that HEAD is the main HEAD itself, which passes the
  ancestor check, so harvest also refuses any detached HEAD.
  The lead's evidence is never archived for commits that did not land.
- A lead branch must hold no merge commit. A lead may not merge, but nothing
  else enforces it, and a rebase linearizes a merge and silently drops any
  change made in the merge commit itself; every later guard then passes. The
  coordinator checks `git rev-list --merges <main HEAD>..<branch>` first and
  keeps such a lead unintegrated.
- The rebase targets the main HEAD sha, not a branch name, because the main
  checkout's branch name differs between projects. `--no-autostash` makes a
  dirty lead worktree stop the rebase instead of being stashed and replayed.
- A failed rebase is aborted at once (`git -C <W> rebase --abort` restores
  the lead's exact tip and a clean tree, and only prints "No rebase in
  progress?" when the rebase never started). A conflict and a dirty-worktree
  refusal both exit 1, so the coordinator tells them apart by the conflicted
  paths (`git -C <W> diff --name-only --diff-filter=U`) listed before the
  abort. A conflict stops the wave and is carried into the integration task,
  which reruns the rebase, resolves in the worktree, and continues with
  `GIT_EDITOR=true git -C <W> rebase --continue` once per stopped commit;
  without an editor, `--continue` fails. Any other failure (dirty worktree,
  an untracked file the rebase would overwrite, a hook or signing failure)
  keeps only that lead, because leads are independent, and the wave
  continues. An `--ff-only` refusal means the main checkout moved; the
  coordinator stops and reports it.
- Known limit: a rebase treats ignored files as expendable. If the main
  history tracks a file at a path that is ignored task evidence in a lead
  worktree (only possible by force-adding it), the rebase overwrites that
  evidence silently before harvest copies it.
- Every lead after the first gets new commit ids. Those rebased commits are
  not the exact tree that lead's reviewers and QA saw; the integration task's
  full suite, review, and QA run on the combined result, as they did for merge
  commits before. The lead's returned `commit` is its pre-rebase tip, so the
  coordinator records the main HEAD after each fast-forward, and the report
  lists both.
- The coordinator checks for a merge commit in prose only: the check must run
  before the rebase, after which the merge is gone and every later guard
  passes, and no script owns that step yet. A coordinator helper script for
  step d is a planned follow-up.
- In batch surfaces, "merge" and "post-merge" name this fast-forward
  (`git merge --ff-only`); no batch step creates a merge commit.

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
  agent lock protects a running lead and, while the coordinator session runs,
  a returned one; kept blocked/failed worktrees lose it once that lock is
  released (for example after the coordinator session ends), and the moment
  between `git worktree unlock` and `git worktree remove` never has it.

Relative-path worktrees (git ≥ 2.48 `extensions.relativeWorktrees`) are out of
scope by the user's decision; host clients that lack the extension also cannot
open the repository at all.

## Worktree location

- The runtime picks where a lead worktree lives. Claude Code
  `isolation: worktree` always creates `<repo>/.claude/worktrees/<name>` (its
  `worktree.location` setting is not read for agent isolation); the Codex app
  uses `$CODEX_HOME/worktrees`, outside the repository.
- Harness is location-agnostic: it validates registration, not path. The MCP
  `workspace` check (`resolve_registered_worktree`) and `batch_harvest.py`
  accept a linked worktree because its gitdir is registered under
  `<control>/.git/worktrees/` with a matching back-pointer, wherever the
  checkout sits; `batch_preflight.py` recognizes lead worktrees by the paths
  `git worktree list --porcelain` registers, not by where they live. The only
  location-specific step is batch SKILL preflight step b.3, which checks that
  Claude's default `.claude/worktrees/` is gitignored.
- Placing worktrees under `.git` (for example `.git/harness-worktrees/<name>`)
  was evaluated and rejected:
  - Claude Code treats any absolute path with a `.git` segment as protected,
    so every lead Edit/Write prompts (default, acceptEdits), goes to the
    classifier (auto), or is denied (dontAsk); only bypassPermissions lets it
    through, and neither a settings allow rule nor a PreToolUse `allow`
    bypasses it.
  - Claude only relocates a worktree through a WorktreeCreate hook. A
    hook-made worktree loses the agent lock, the creation marker that keeps
    the periodic sweep away from it, `.worktreeinclude`, and `baseRef`; the
    hook replaces worktree creation for the whole settings scope, and it
    cannot keep C-12's `|| true` fail-safe because a failing hook aborts
    creation.
  - The Codex workspace-write sandbox makes `<writable root>/.git` read-only.
  - `.git` and `.claude` sit on the same 9p mount, so there is no speed gain.
  - None of the surveyed prior-art tools (eleven) puts worktrees under `.git`;
    they use a dedicated in-repo directory, a sibling, or a tool-owned
    directory outside the repository.
- The cost of the kept location: `.claude/worktrees/` must be ignored, and
  `git clean -ffdx` in the main checkout deletes it, lead work included,
  despite the ignore. Never run it while any lead worktree exists.

## Multi-repo and submodules

Batch supports exactly one shape: a single git control root whose scopes lie
in its own tracked area. A repository with submodules or nested repos still
batches the requests scoped to its tracked area; only the requests scoped
inside a submodule or nested repo are sequenced outside the wave. Three other
shapes exist:

- (a) **Submodules**: mode-160000 gitlinks, normally declared in
  `.gitmodules`.
- (b) **Ignored nested repos inside a git root**: directories holding their
  own `.git` that the superproject does not track (for example sibling
  service repos under an ignored `repos/`).
- (c) **A non-git parent with child repos**: no control root at all.

What happens without the stop-gap:

- `git worktree add` never initializes submodules (it has no recursive option
  and `submodule.recurse` does not change that), and neither Claude Code nor
  Codex does, so every submodule is an empty directory in a lead worktree —
  unless the repository's post-checkout hook initializes them, which Claude
  Code does not suppress.
- An ignored nested repo does not exist in a lead worktree at all. Its only
  copy is in the main checkout, which no lead may write, and a plain
  `git status --porcelain` there does not report its changes.
- (c) cannot host a batch: Claude Code cannot create an isolation worktree
  without a git root, and the workspace validator refuses it. A control root
  that is itself a linked worktree, an absorbed submodule checkout (whose
  `.git` is a gitfile), or a separate-git-dir checkout is refused by the
  validator too, because it requires `<control>/.git/worktrees`; a submodule
  checkout with an embedded `.git` directory passes the validator, so only the
  preflight's superproject check refuses it.

Stop-gap rules (current):

- `plugin/scripts/batch_preflight.py` runs at intake and preflight for exactly
  the wave about to be spawned, and the coordinator spawns only on exit 0
  (`verdict: ok`). It refuses a control root whose shape is
  `submodule-checkout`, `linked-worktree`, `non-git`, or `separate-git-dir`;
  refuses when `git status --porcelain` is not empty in the main checkout
  (submodule changes included, whatever `submodule.<name>.ignore` says), in
  any populated submodule, or in any ignored nested repo; and refuses when a
  post-checkout hook (the default hooks dir or `core.hooksPath`) mentions
  `submodule` in a repository with submodules. It fails closed: a directory
  it cannot read while looking for nested repos or placing a declared scope,
  a tracked or untracked path git reports it could not open (git itself only
  warns and exits 0), a submodule directory it cannot inspect, and an
  unreadable or non-regular `.gitmodules` all refuse instead of being
  skipped, because each could hide a nested repo, a submodule, or
  uncommitted work. It never writes: every git call uses the trusted
  environment, `--no-optional-locks`, and `core.fsmonitor=false`.
- Verdict and exit status: the script prints one JSON report whose `verdict`
  is `ok` (exit 0), `adjust` (exit 1: a request is listed in
  `excluded_requests` or two requests are listed in `overlaps`), or `refuse`
  (exit 1: anything in `refusals`), with precedence refuse > adjust > ok.
  Every failure the report depends on — a failed git command, an unreadable
  directory, hook, or `.gitmodules`, a nested repo or submodule whose `.git`
  resolves to another work tree, or an unexpected crash — yields a `refuse`
  report, never a pass. A malformed `--request` (no `SLUG=PATH`, a slug
  outside `[A-Za-z0-9._-]+`, an empty path, or a glob pattern or comma list,
  meaning a value with `*?[` or a comma that names no existing path; an
  existing path such as `app/[locale]` is fine, and each path gets its own
  `--request`) is a usage error: exit 2 and no report. `ok` covers only these
  checks; the coordinator's other preflight steps (`baseRef`, the worktree
  ignore, no open main-checkout task, the recorded HEAD) still apply. The
  coordinator acts on `verdict` and on `refusals`, `excluded_requests`,
  `overlaps`, and `off_limits`, and reruns the script after adjusting a wave;
  `control_root.shape` is informational (it reads `non-git` with an empty
  reason when shape detection itself could not run). Every report key
  (`verdict`, `control_root`, `submodules`, `nested_repos`, `off_limits`,
  `post_checkout_hooks`, `dirty`, `scopes`, `overlaps`, `excluded_requests`,
  `refusals`) is always present, even on an early refusal or a crash, and
  `dirty` lists at most 20 status entries per repo alongside the full `count`.
  Hook detection reads the first 256 KiB of each post-checkout hook, matches
  `submodule` case-insensitively, and ignores the executable bit.
- No refusal advises deleting anything, with one exception: when git cannot
  open a nested repo or populated submodule because its `.git` is a gitfile
  naming a missing `.../worktrees/<name>` registration (a leftover worktree
  whose metadata was pruned), the refusal says to copy out anything still
  needed and then remove the directory. Every other failure, including an
  unreadable directory inside a nested repo that holds uncommitted work,
  gives no delete advice: it names the path and, where one applies, a
  non-destructive remedy (for example commit or stash, make it readable or
  move it out of the checkout, run from the main checkout, make the hook skip
  linked worktrees or run the requests one at a time as ordinary tasks). The
  first read failure stops further inspection, so `refusals` may name only
  that one and later report sections stay empty; fix it and rerun. When the
  control-root shape is not `ok`, `scopes` and `excluded_requests` are empty.
- Registered linked worktrees of the repository under the root (kept lead
  worktrees) are not nested repos: they are left out of `nested_repos` and
  `off_limits` and not status-checked, so a kept lead's uncommitted work does
  not refuse a new wave; a scope inside one is still `inside-ignored-nested-repo`.
- Each declared scope is classified on its symlink-resolved path:
  `outside-root` when it lies outside the root or under its `.git/`;
  `inside-submodule` when it equals or lies under a submodule path (populated
  or not); `inside-ignored-nested-repo` when an existing directory between the
  root (exclusive) and the scope (inclusive) holds its own `.git` entry, which
  also covers a scope inside a registered lead worktree under the root; and
  `tracked-area` for every other path inside the root. `tracked-area` is
  therefore broader than its name: it includes untracked, ignored (for
  example `build/`), and not-yet-existing paths, and a scope that contains a
  submodule or nested repo (`libs` around `libs/sub`); `off_limits` is what
  keeps a lead out of the repos inside such a scope. A separate class for
  ignored non-repo scopes is deferred: a lead's edits there are never
  committed, which is a task-planning problem rather than a repo-shape hazard.
  Only `tracked-area` may run in a lead. A request scoped inside a submodule or
  an ignored nested repo runs as an ordinary task in the main checkout,
  outside the wave; an `outside-root` scope cannot run in `harness:batch` at
  all. `excluded_requests` keeps every exclusion reason of a request.
- Two requests overlap when one of their symlink-resolved scopes equals or is
  a path-segment ancestor of one of the other's (`a/b` and `a/bc` do not
  overlap; `.` overlaps everything); a request's own paths are never paired,
  and neither is an excluded request, because it never runs in a wave.
  Overlapping requests move one of them to a later wave.
- The report's `off_limits` (every submodule, and every nested repo the scan
  found; a directory with its own `.git` among files the superproject tracks
  is not listed, though a scope under it is still excluded) goes into each
  lead prompt. A lead never runs `git submodule
  update/init/deinit/sync/set-url/absorbgitdirs` or any other subcommand but
  `status`, never passes `--recurse-submodules` or
  `-c submodule.recurse=true`, and never edits inside a submodule, an ignored
  nested repo, or an off-limits path; if the task needs that, it returns
  `blocked` with the reason.
- With no submodule ever initialized in a lead worktree, plain
  `git worktree remove` keeps working, so the batch rule "never `--force`"
  stays satisfiable. If a removal still refuses because of a submodule, the
  worktree is kept and reported.
- Residual risk: `git status` in a nested repo or submodule runs that repo's
  configured clean filters, as any status there does. Nested repos in the
  user's project are trusted like the main checkout; refusing filter configs
  would falsely refuse git-lfs repos.
- Known limit: the clean check is literally `git status --porcelain`, so
  `status.showUntrackedFiles=no` in the main checkout, a submodule, or a
  nested repo hides that repo's untracked files and the preflight does not
  refuse for them.
- Known limit: the preflight checks repository shape, scopes, and
  cleanliness, not HEAD state or earlier waves. A main checkout on a detached
  HEAD or in the middle of a rebase, merge, cherry-pick, revert, or bisect
  is not refused for that state (it gets `ok` when the tree is otherwise
  clean; unmerged entries still refuse as dirt), and kept blocked/failed lead
  worktrees are not compared with the new wave's scopes; both are follow-ups.

Verified hazards (git 2.43, reproduced in the 2026-09-27 investigation):

- Once a submodule was initialized in a worktree, plain `git worktree remove`
  refuses that worktree forever, clean or even after `deinit`, because the
  per-worktree module store (`.git/worktrees/<wt>/modules/`) exists and the
  index holds a populated gitlink.
- `git worktree remove --force` then deletes that module store together with
  any submodule commit that was never fetched or pushed elsewhere, and it
  skips the superproject's dirty and untracked check.
- `git submodule deinit` in a lead removes the `submodule.*` entries from the
  `.git/config` shared by the main checkout and every lead; afterwards
  `git submodule update` in main exits 0 and does nothing.
- Two leads that bump the same submodule to sibling commits always conflict
  on merge.
- `git merge` does not update the submodule checkout, and a later
  `git commit -a` records the stale checkout and silently reverts the bump.
- Git's own documentation (git-worktree, BUGS): "It is NOT recommended to make
  multiple checkouts of a superproject."

Full submodule support is a later task (Goal child G): lead init on a named
branch, coordinator local fetch → rebase and fast-forward → immediate
`submodule update`, and a
guarded single `--force` removal in `batch_harvest.py`. Until it lands, the
stop-gap above applies.

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
- `.claude/worktrees/` is gitignored in every harness project: manifest
  version 7 adds it to setup's managed operational ignores
  (`doc/harness/REQ__versioned-project-file-migrations.md`). The batch SKILL
  preflight step b.3 (`git check-ignore`, not `batch_preflight.py`) still
  checks it and, when the path is not ignored (for example in a project not
  yet migrated to v7), tells the user to add it; a later
  `--migrate-harness-version` moves that line into the managed block.
- Known limit: when `.claude` or `.claude/worktrees` is a symlink, step b.3's
  `git check-ignore .claude/worktrees/x` exits 128 ("beyond a symbolic link")
  even after the v7 migration has written the ignore entry, so batch stops at
  preflight in that layout although v7 accepts it. Follow-up: make b.3 check
  the path git actually sees, as `setup_finalize.py` does for the v7 entry.
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
- Cross-checkout protection: when a lead's Edit/Write target lies outside its
  worktree, the prewrite gate resolves the target's own harness root and
  applies the C-05 protected-artifact rules there, so the main checkout's or a
  sibling worktree's `TASK.json`/`PLAN.md`/`RECEIPTS.jsonl`/`REVIEWS.jsonl`,
  goal state, and focus markers are denied from a lead. Ordinary source files
  of another checkout are not gated (Claude Code's worktree isolation refuses
  such Write calls, observed above), and C-05 leaves Bash unguarded. Remaining
  limits are listed in `doc/harness/patterns/prewrite-gate.md`
  ("Cross-checkout protection").
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
- `tests/test_batch_harvest.py`: copy, append, idempotence; two locked leads
  rebased and fast-forwarded in order, harvest refused after the rebase and
  before the fast-forward, then accepted, unlock/remove/`branch -d`, and a
  history with no merge commit; a conflicting rebase aborted back to the
  lead's exact tip with main unchanged; a rebase stopped at a conflict
  refused as a detached HEAD, then resolved with
  `GIT_EDITOR=true rebase --continue`, fast-forwarded, harvested, and
  removed; refusal for an
  unregistered or unmerged worktree, links/FIFOs, and an archive collision; an
  ambient `GIT_DIR` cannot redirect the merged check; a non-canonical
  `--worktree` path is canonicalized and accepted.
- `tests/test_batch_preflight.py` (scratch repos): the five control-root
  shapes; submodules from gitlinks and `.gitmodules`, populated or not; deep,
  gitfile, and ignored nested repos, but not a registered lead worktree; the
  four scope classes including symlink escapes; dirt in the root, a nested
  repo, and a submodule hidden by `ignore=all`; broken nested `.git` metadata
  refuses, and the delete hint appears only for a gitfile naming a pruned
  worktree registration; an unreadable directory (scan and scope), an
  unreadable tracked directory, an unreadable directory inside a nested repo
  (no delete hint), an untraversable populated submodule, git's unreadable-path
  warning on the untracked listing, and an unreadable or non-regular
  `.gitmodules` refuse; every exclusion reason of a request is kept, and an
  excluded request is never paired in `overlaps`; overlaps and
  refuse-over-adjust precedence; post-checkout hooks in the default dir and
  `core.hooksPath`; byte-identical tree (index included) after a run; no
  `core.fsmonitor` launched (root, submodule, or nested repo); ambient
  `GIT_*` ignored; CLI exit codes and JSON, including usage errors for globs
  and comma lists that name nothing while existing paths with `,` or `[` are
  accepted; an unexpected crash still prints a `refuse` report.
- `tests/test_batch_skill_contract.py`: lead frontmatter and carve-outs, every
  coordinator step, the C-09 clause in both contract files, root CLAUDE.md
  clauses, and this repository's `baseRef`/ignore settings; the preflight
  script in intake/preflight and the off-limits spawn line; the lead's
  submodule and nested-repo prohibitions; this document's worktree-location
  and multi-repo sections; the batch SKILL's rebase and fast-forward
  integration commands, merge-commit precheck, and conflict test, and the
  absence of `--no-ff` and `git merge --abort` there.
- Live probe: a real worktree subagent starts a task with `workspace` and its
  nested reviewer's start/stop receipts appear in the worktree task.
