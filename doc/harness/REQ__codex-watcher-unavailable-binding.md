---
status: active
freshness: current
---

# Codex watcher recovery after unavailable binding reads

## User outcome

A temporary inability to read the exact active task binding must not silently
disable receipt collection for the rest of a valid registration. Unknown binding
grants no receipt authority. A validated change to a different task/run retires
the previous worker normally.

## Required behavior

- Outer watch checks and spawn/start/completion publication checks distinguish
  unavailable binding from a positively established different generation.
- During uncertainty, no lifecycle is observed or receipt appended. Bounded
  rechecks may recover the same binding; otherwise the worker fails retryably.
  The manager must independently validate the persisted registration before
  restarting from its immutable offset. Idle limits, stop requests and leases
  still bound work.
- Exact lifecycle correlation, protected receipt ownership, deduplication and
  duplicate-terminal rejection remain unchanged. Conflict fencing invalidates
  the old registration; authorized rebinding starts at a new current offset.
- An older recorded review/QA FAIL stays FAIL when a remedial retry lacks
  receipts. Guidance first requires remediation. Only subsequently delivered
  required review PASS followed by QA PASS, with no actual outstanding failure
  or environment blocker, permits the canonical missing-attestation endgame
  after one fresh verification. Direct finals cannot close a task.
- The fixed parking text remains owned by `_lib.py`; no additional copy lives
  in this requirement. No manual receipt repair or historical scan is allowed.

## Incident evidence and limits

Dogfooding on 2026-09-28 observed missing latest QA start/completion receipts,
while prior review receipts existed. The live MCP process had its manager but
no root watcher thread or rollout descriptor. A new task registration naturally
created a worker. Code inspection found that an empty binding made the worker
return success and permanently suppressed its registration within that manager.
This mechanism is reproducible; the exact event that triggered the live worker
exit was not captured and remains unknown.

## Verification

Deterministic tests cover unavailable reads at each lifecycle boundary,
same-generation recovery, sustained uncertainty, validated task/run changes,
conflict fencing, trusted-file replacement rejection and exact receipt
deduplication. Gate tests retain FAIL and close refusal while exposing conditional
canonical parking guidance. Independent security review and full QA precede
verified installation.

## Known ceiling

Fresh-process projection tests verify the changed Python implementation.
Installing updated files does not prove that an existing MCP process reloaded
already-imported modules. Native Claude is unavailable in this environment;
Claude projection checks do not constitute native Claude execution.
