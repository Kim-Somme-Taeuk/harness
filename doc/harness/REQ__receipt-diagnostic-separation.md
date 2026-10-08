# Receipt diagnostics without authority changes

When a completion has a matching lifecycle identity but its event order cannot be established, diagnostics must identify ordering uncertainty instead of asserting that the start is missing or completion duplicated. Actual missing or duplicate completion identities retain pairing diagnostics. These messages never change the close verdict, authorize cross-coordinator PASS, or discard valid negative evidence.

A Codex MCP host without an owned session identity must keep session readiness unknown. It may expose a separate, bounded task/run worker snapshot derived only from its own manager state, filtered to the exact repository, task and run. Multiple coordinators must be visible rather than silently selecting one. A missing local worker does not prove global absence, and a running worker does not prove that every receipt is being captured. Error text must be bounded and flattened.

Binding conflicts between distinct open tasks in one coordinator remain fenced. Inspect other tasks through read-only files; task_context can change a session binding. Do not silently park another task, recover historical receipts, restart agents, or use diagnostic data as recording authority.

## Verification

Independent regressions cover mixed-origin ordering, true pairing defects, exact task/run/repository filtering, multiple workers, errors, missing session identity and unchanged close readiness. Existing watcher and worktree tests preserve binding fences and native evidence checks.

## Known ceiling

Worker snapshots describe only the reporting MCP manager process. Already-loaded Python processes do not automatically adopt newly installed modules. Historical missing records are not reconstructed by this change.
