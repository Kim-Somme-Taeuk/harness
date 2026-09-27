---
title: prewrite_gate — plan-first + protected artifacts + scope lock
freshness: suspect
invalidated_by_paths:
  - plugin/scripts/prewrite_gate.py
  - plugin/scripts/_lib.py
  - plugin/hooks/hooks.json
tier: 2
freshness_updated: 2026-04-26T14:50:21Z
---

# prewrite_gate

PreToolUse hook on `Write` / `Edit` / `MultiEdit`. Blocks writes that would
violate harness invariants. The hook wrapper preserves C-12 fail-safe (`|| true`)
by signalling decisions via stdout JSON rather than exit code.

## Rules (in order)

| # | Rule id | When | Deny owner (`owner=`) |
|---|---------|------|-----------------------|
| 1 | (escape) | `HARNESS_SKIP_PREWRITE=1` | — (silent allow, logs `gate-bypass`) |
| 2 | `C-05-protected-artifact` | Write to any `PROTECTED_ARTIFACTS` basename *inside* a task dir | the owning skill / CLI |
| 2a | `C-05-protected-artifact` | Target outside the cwd's Harness root that is a protected artifact of *its own* valid Harness root (see [Cross-checkout protection](#cross-checkout-protection)); any other out-of-root target is a silent allow | same as rule 2 |
| 3 | (allow) | Other writes *inside* any task dir | — |
| 4 | (allow) | Paths under `EXEMPT_PREFIXES` | — |
| 5 | `workflow-control-surface` | Write to any `WORKFLOW_CONTROL_SURFACE` entry without a MAINTENANCE marker on the active task | `maintain-skill` |
| 6 | `no-active-task` | Source write without `.active` pointer | `plan-skill` |
| 7 | `invalid-active` | `.active` unreadable / missing / out of tree | `plan-skill` |
| 8 | `C-02-plan-first` | Source write but active task lacks `PLAN.md` (and no MAINTENANCE marker) | `plan-skill` |
| 9 | `scope-lock-forbidden` | Path matches `forbidden_paths` in the active task's `PROGRESS.md` | `developer` |

A write that hits no block rule is a silent allow (silence is the trust signal).

## Deny-reason structure

Every deny emits a structured tail followed by a human sentence and an escape hint:

```
[gate=prewrite rule=<id> path=<repo-relpath> owner=<role> docs=<pattern-doc>] <human text>
escape: HARNESS_SKIP_PREWRITE=1 <retry>
```

Agents can parse the tail to route actions without scanning prose. Humans read
the sentence to understand what to do next.

## Protected artifacts

The `PROTECTED_ARTIFACTS` dict maps basename → owner-role. Owners are space-free
so the structured tail remains grep-stable; the deny sentence names the human
tool to route through (for example `write_plan` for `PLAN.md`). Claude
`projects/*/<session>/subagents/agent-*.jsonl` leaves are also protected outside
the repository because stop-only receipt provenance depends on them.

## Cross-checkout protection

A `harness:batch` lead runs with its cwd in a linked worktree
(`<main>/.claude/worktrees/<name>`). The gate's control root is then the
worktree, so the main checkout and sibling worktrees lie outside it. Without
this rule, writes to those checkouts' protected artifacts were allowed. The same
applies to a main-checkout session writing into an out-of-tree worktree.

How the gate handles a target outside the cwd's Harness root:

1. It skips targets whose name cannot be a protected artifact: the basename is
   not a `PROTECTED_ARTIFACTS` key, the path is not goal JSON, and it is not
   `.active` or under `.active_sessions/`.
2. For the remaining targets it resolves the target's own root with
   `harness_root_resolution(dirname(target))`. That call does file checks only
   and runs no Git subprocess. It tries the realpath first, then the requested
   path.
3. If that root is valid (a regular manifest and no resolution error) and the
   target is one of its protected artifacts (`TASK.json`, `PLAN.md`,
   `RECEIPTS.jsonl`, task-local `REVIEWS.jsonl`, `doc/harness/goals/*.json`,
   `doc/harness/tasks/.active`, `doc/harness/tasks/.active_sessions/*`), the
   gate denies the write:
   - rule id: `C-05-protected-artifact`;
   - owner and sentence: the same as an in-root deny;
   - extra sentence: `The target belongs to another Harness checkout: <root>.`;
   - tail `path=`: relative to that other root.

Only C-05 crosses checkouts. Plan-first, workflow-control-surface, REQ and
scope-lock rules belong to the checkout that holds the active task. An ordinary
source file of another checkout therefore stays a silent allow from a worktree
cwd. So does that checkout's `plugin/scripts/prewrite_gate.py`.

Behavior that does not change:
- A cwd outside any Harness root keeps its early return.
- A target outside every Harness root is still a silent allow.
- An exception in this branch is logged to the cwd's root through
  `_log_gate_error`, and the write is allowed (C-12). It never ends the loop
  over the remaining paths of the same tool call.

Known limits:
- From the main checkout, an in-tree worktree is inside the main root, so the
  in-root rules apply to it. The task-local `REVIEWS.jsonl` test is then
  relative to the main checkout's task dir, so an in-tree worktree's
  `REVIEWS.jsonl` is not denied from main.
- A directory symlink inside a foreign root that points out of every Harness
  root is allowed.
- A foreign root with an invalid manifest is not treated as a valid root, so
  writes into it are allowed.

## Workflow-control-surface

Files that define harness runtime behaviour. Writes require a task with a
`MAINTENANCE` marker. The set currently includes `plugin/CLAUDE.md`,
`plugin/hooks/hooks.json`, `plugin/scripts/{prewrite_gate,_lib}.py`,
`plugin/mcp/harness_server.py`, `doc/harness/manifest.yaml`.

Touch `doc/harness/tasks/<task>/MAINTENANCE` to enable writes, and record the
reason in close-time Self-Healing Candidates. The prewrite gate itself does not
create this marker.

## Scope lock

If `PROGRESS.md` exists in the active task's directory, the gate enforces:

- `forbidden_paths` — deny with rule `scope-lock-forbidden`
- `allowed_paths` / `test_paths` — advisory; unlisted paths log a warning but do not block (gate philosophy: block only when explicit)

One-shot bypass: `HARNESS_DISABLE_SCOPE_LOCK=1` (audit flag is dropped in
`audit/scope-lock-bypass.flag` for post-hoc review).

## Escape hatches

| Env var | Effect | Audit |
|---------|--------|-------|
| `HARNESS_SKIP_PREWRITE=1` | one-shot silent allow | `gate-bypass` in `doc/harness/learnings.jsonl` |
| `HARNESS_DISABLE_SCOPE_LOCK=1` | skip scope lock for one write | `scope-lock-bypass.flag` in task `audit/` dir |

Activations are logged. If your `learnings.jsonl` shows recurring `gate-bypass`
entries against the same path, that is a signal to either move the path into
the task's `allowed_paths` or to run the work under a maintain task.

## Fail-safe behaviour

- Top-level `_lib` import failure → module-level `sys.exit(0)` (fail-open).
- Exception inside `main()` → `_log_gate_error` writes a `gate-error` entry to
  `learnings.jsonl` and the hook exits 0.
- Malformed / empty stdin → silent allow.

The hook wrapper is `python3 ... || true`, so a process-level crash is also
allowed through. The JSON decision mechanism is what gives the gate teeth —
exit-code blocking is not used.

## Related

- Bash/shell file mutation is outside this direct-write enforcement surface.
- Tier 2: [`scope-lock.md`](./scope-lock.md) — PROGRESS.md scope lock details
- Contract: C-02 (plan-first), C-05 (protected artifact), C-12 (hooks fail-safe)
