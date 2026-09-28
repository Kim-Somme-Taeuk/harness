# Batch Wave 2 recovery

Initially recovered six interrupted implementations while preserving their source
worktrees without claiming their tasks closed. The combined change adds safe batch completion,
proof-based Claude integration-review carry, explicit AC ownership and parallel
test authoring, test-ledger isolation, and protected-write checks for large or
invalid-byte payloads and Codex child failures. It also aligns contracts, CI and
the Harness guide with current behavior. The complete recovered diff requires
fresh review and QA; original lead receipts are not carried.

The six originals were subsequently fully archived with byte verification under
`doc/harness/archive/worktree-recovery-wave2`, then removed along with their
six disposable branches. All original branches had zero unique commits and were
ancestors of the recovered destination. This was disposition of already-recovered
work, not a new rebase or a claim that the original lead tasks closed. The archives
remain local; original task status and receipts were not rewritten.

The completion helper also protects untracked files when Git is configured to
hide them, reconciles actual integration after a merge timeout, and attempts to
restore the worktree lock after exceptional removal failures. Preflight uses
the same explicit untracked-file check. Unknown integration and failed lock
restoration remain visible in the result instead of implying successful cleanup.
Integration evidence is tied to the original main branch, so detaching or
switching the checkout during integration cannot authorize lead deletion based
only on the new HEAD.

## Known ceiling

- Killing the entire hook, fallback failure, or memory exhaustion can still allow
  a write; the fallback protects C-05 targets only. Stronger host-enforced
  protection would be needed to remove these limits.
- AC sub-worker type, depth and ownership bounds are prompt-enforced. A
  disobedient worker can exceed them; stronger tool-level enforcement would be
  needed if that behavior is observed.
- The test ledger guard ignores its documented live-hook writers and cannot
  distinguish a test impersonating one of those writers.

See the gate [requirement](../harness/REQ__protected-artifact-denial-survives-payload-size-and-hook-timeout.md),
parallel-work [ADR](../harness/patterns/ADR__within-task-parallel-width.md),
and test-isolation [requirement](../harness/REQ__test-suite-determinism-under-xdist.md).
