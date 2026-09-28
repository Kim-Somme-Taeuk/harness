# Batch Wave 2 recovery

Recovered six interrupted implementations without modifying their source worktrees
or claiming their tasks closed. The combined change adds safe batch completion,
proof-based Claude integration-review carry, explicit AC ownership and parallel
test authoring, test-ledger isolation, and protected-write checks for large or
invalid-byte payloads and Codex child failures. It also aligns contracts, CI and
the Harness guide with current behavior. The complete recovered diff requires
fresh review and QA; original lead receipts are not carried.

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
