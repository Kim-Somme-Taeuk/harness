# Selected submodules in batch leads

S1 extends the durable batch pool to explicitly selected, populated direct
submodules. A request may add `submodules: ["libs/example"]` alongside its
literal `scopes`. A scope must name the module, an ancestor, or a descendant
inside it; selection never enlarges the permitted edit scope. Omitted
selection retains the existing exclusions and plain worktree cleanup.

## Selection and ownership

Selected paths must be canonical, non-symlink direct gitlinks with matching
`.gitmodules` entries and clean populated main checkouts at the recorded
gitlinks. Duplicate, missing, unpopulated, nested, escaping or unsupported
repository topology refuses before preparation. Recursive modules, shallow or
promisor repositories, alternates and replacement refs are not supported.
Ignored nested repositories continue as ordinary sequential tasks. Tracked entries
with `assume-unchanged` or `skip-worktree` flags refuse S1 cleanliness/disposal
proofs because Git can otherwise hide uncommitted bytes; the helper never clears
those flags or discards their content.

Each selected gitlink is one ownership boundary even when the requested edit
is a descendant path. Two leads changing sibling paths in the same module
serialize; different modules can run concurrently. Retained work keeps this
ownership across batches. Every unselected module remains off-limits.

## Durable preparation and continuation

Batches with any nonempty selection use state schema 2; ordinary batches retain
schema 1. An omitted or empty `submodules` list normalizes to the ordinary route. The new
reader accepts unchanged schema 1. Older readers refuse schema 2, preventing
silent execution without S1 guards. Selection participates in exact init
idempotence, and malformed or downgraded records refuse.

The existing batch record owns the module manifest and checkpoints. Bind
persists the exact worker/worktree/branch and preparation intent while still
reserved, then creates local independent module clones with private gitdirs
under that registered worktree's administration directory. Only the intended reachable objects transfer from validated local paths. No hardlinks,
alternates, network initialization or shared configuration edits are used.
Private clones use an empty Git template so disposable metadata does not inherit
custom hooks or template files.
Each prepared module has a deterministic named development branch at its
initial gitlink. Only complete preparation grants running permission. Successful
`bind` returns `status: "running"` and the bound `request`; its
`submodule_manifest.modules` entries must all have `phase: "prepared"`. Forward
that manifest to the same worker with permission to continue.

A failed or interrupted preparation retains the reservation and private data.
Retry initial preparation with `bind` using the same recorded worker, worktree
and branch; it accepts only positively owned complete effects. Unknown partial directories are never overwritten or deleted.
Resume uses the same worktree and module stores, preserving edits and task
generation. The lead commits module changes before recording their gitlinks
in the superproject. Its Harness lifecycle and evidence remain at the outer
worktree; no nested task is created.

For example, the coordinator can queue this request:

```json
[{"slug":"module-fix","request":"Fix the parser","scopes":["libs/example/src"],"submodules":["libs/example"]}]
```

After successful bind and continuation, the lead uses its prepared branch:

```bash
git -C "$W/libs/example" add -- src/parser.py
git -C "$W/libs/example" commit -m "Fix parser"
git -C "$W" add -- libs/example
```

The outer commit and task-close order follow the existing lead protocol. Never
run module initialization, remote fetching or cleanup from this example; those
remain coordinator operations. For a retained task, use batch `status`, then
`recover` for interrupted integration or `resume` for stopped development in the
same checkout. Preparation refusal must be resolved before continuation.

## Preservation and linear integration

Before integration, the coordinator inventories every private named reference
as its exact object, including annotated tags, reflog commit tips, and every
selected gitlink in the lead's superproject history. Intermediate commits
remain covered even if the final module branch no longer reaches them.
Topology changes, including temporary `.gitmodules` or gitlink add/delete/type
changes, refuse. A request selects at most 16 modules. Each module has at most
4096 inventory entries across refs, reflogs and gitlinks; the source-history scan
also allows at most 4096 commits. The complete module manifest, including pins
and witness, must fit 512 KiB within the existing 1 MiB batch-state limit.
Over-limit data refuses; inventories are never truncated. The owner persists the
complete inventory and deterministic pin intent within the full batch-state limit
before any fetch or pin write. Intent alone is not preservation proof: every
required reference and object closure must still be verified before use or removal.

Local fetches preserve the inventory under durable namespaced refs in the
validated main module repositories. Complete object closure and reference
identity must be verified before the private stores can be removed. These refs
survive garbage collection and remain after cleanup; S1 does not expire them.
New helper Git operations disable hooks, recursion and automatic remote fetch
per call, without modifying shared repository configuration.

The coordinator rebases the lead and fast-forwards the recorded destination;
it never creates a merge commit. Before fast-forward, it durably records the
destination ref, old superproject tip, intended landed tip, and exact old and
target module checkout commits. Immediately after landing, it updates selected
destination checkouts locally. Lead checkout reconciliation after rebase uses
the same exact-identity discipline.

Recovery consumes this witness before ordinary destination cleanliness checks.
Only the exact recorded destination and old-or-target clean module checkout
states qualify. Partial multi-module updates are idempotent. Unrelated dirt,
foreign checkout movement, missing objects, or a different destination tip
refuse and retain work; recovery never resets arbitrary source changes.

## Guarded disposal

Temporary worktree disposal follows successful integration, module object
preservation and durable task-evidence harvest. `batch_harvest.py` owns the
single guarded `git worktree remove --force` operation for state-managed S1.
Standalone finish and ordinary worktrees do not gain this permission.

Immediately before removal, recheck worktree/branch/module identity, topology,
reference inventory, preserved object closure, archive bytes, and tracked,
staged, untracked and ignored content. Only exact already-harvested task
evidence and matching learnings may be exempted. Unknown ignored content,
nested repositories, extra initialized modules, changed refs or unsafe metadata
retain the worktree. This includes unknown files inside private Git metadata or
its owned container, not only files visible to Git status. Only validated native
Git metadata may be discarded. Known reproducible outputs may be removed by their owner
before returning the lead; this helper does not delete unknown data.

On refusal, retain source and restore the original lock and bootstrap marker
where the worktree still exists. Branch deletion uses `-d`, never forced
deletion. Interrupted removal or branch cleanup uses the existing exact
archive/checkpoint recovery. A retained tree is unfinished work, not successful
completion.

## Verification

Real-Git tests exercise default compatibility, same-module serialization,
private preparation, exact retry/refusal, reference/tag/reflog/intermediate
object retention after GC, and byte-unchanged shared configuration. Process
and fault tests stop before/after clone, persistence, rebase, fast-forward,
module updates, harvest and deletion. Happy-path CLI verification must prove
linear history, current destination module checkouts, durable task evidence,
and absence of the owned temporary worktree and disposable branch.

Known ceiling: S1 supports explicitly selected populated direct modules only.
Recursive module graphs or unpopulated acquisition require a separately
specified ownership and recovery protocol; unsupported requests retain the
ordinary sequential route.
