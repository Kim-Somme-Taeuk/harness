---
date: 2026-09-25
task: TASK__claude-stop-binds-to-hook-owned-start
tags: [receipts, subagent, lifecycle, claude]
---

# Completion receipts no longer depend on another plugin's start banner

On an install with only the harness plugin, subagent transcripts contain no
`SubagentStart` attachment, because those attachments come from other plugins'
start hooks. The harness start hook still recorded a `started` receipt, but
every `SubagentStop` was declined at `no-canonical-start-attachment`. No
completion receipt was written, and `task_verify` could not reach PASS. A stop
whose transcript has no start attachment now binds to the agent type in the
single hook-owned `started` receipt for the same runtime and run. All other
provenance checks are unchanged. A present attachment still wins. A stop
payload that names a different lens is rejected as
`hook-start-agent-type-mismatch`. Stop-only runtimes still need the transcript
attachment. Details: `doc/harness/REQ__subagent-completion-receipt-transcript-shape.md`.
