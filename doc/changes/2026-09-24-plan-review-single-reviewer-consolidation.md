---
date: 2026-09-24
task: TASK__plan-review-single-reviewer-consolidation
tags: [plan, develop, review, codex]
---

# Full planning now runs one reviewer, and develop has no haiku completion audit

A full plan used to run up to four reviewers one after another: CEO, then
Design if the task had UI scope, then Eng, then DX if the task had DX scope. It
now runs one Phase 1 Plan Review. A single independent reviewer first checks
premises, problem framing, scope, and alternatives (the plan-ceo-review
method), then architecture, the test diagram, breaking tests, error paths,
deployment, performance, and security (the plan-eng-review method). The
timeout is 900s because that one reviewer now covers both. When `ui_scope` is
true, the review also requires an interaction-state table, a user journey, and
accessibility requirements in PLAN.md. There is no 0-10 scoring loop, mockup,
or visual-style pass; ux-browser/qa-browser still judge rendered quality.
`dx_scope` detection and its "developer tool / AI agent is primary user"
override are gone, so harness-repo tasks no longer always trigger a DX pass.
plan-design-review and plan-devex-review stay installed for direct use.

Develop Phase 4 Plan Completion Audit (a haiku agent comparing ACs with
`git diff --stat`) is removed from both runtimes. The formal code reviewer
already proves every AC against code, tests, and docs; a forgotten AC now
surfaces as a review FAIL instead of an earlier self-fix.

Evidence: in the session that prompted this, the Eng reviewer caught
implementation-blocking problems. About half of the CEO reviewer's findings
overlapped Eng, DX produced mostly polish, and the haiku audit returned
nothing usable. Design review had run 0 times across 38 PLANs in this repo
(evidence limited to this repo).
