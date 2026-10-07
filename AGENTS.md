# Harness Codex routing

@CONTRACTS.md

## Harness routing
<!-- harness:routing-injected -->

- Repository mutation (implementation, fix, refactor, test/config/doc behavior change) → invoke `$harness:run` before editing. If a native Goal is active, the run skill synchronizes it and owns its child task.
- Harness bootstrap or repair → invoke `$harness:setup`.
- Read-only questions, explanations, reviews, and status reports → answer directly without starting a task.
- Hooks provide routing reminders and state only; `task_verify` and `task_close` are authoritative for fresh code-review, conditional security-review, and QA evidence.
- Changes to managed contracts, Harness skills, or `contract_lint.py` must keep the real-tree contract and skill-weight tests passing.

## Fork maintenance

- Before upstream synchronization or Codex execution/model-routing changes, read [the fork provenance and preservation rules](doc/harness/REQ__codex-followup-receipts.md#fork-provenance-and-preservation). Preserve the seven mapped receipt fixes and their tests/docs; reconcile upstream changes by behavior rather than overwriting these files.
