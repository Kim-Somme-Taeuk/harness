# REQ — Codex failure-cost model routing

Codex task leads and implementation/test-author AC workers select a model
before native spawn. The executable authority is `plugin/scripts/model_routing.py`;
`plugin-codex/internal-skills/develop/model-routing.md` owns assessment and
handoff instructions used by develop and batch.

| Failure impact / recovery | Cost | Initial model |
| --- | --- | --- |
| Local, easy rollback | Low | gpt-6.1-sol |
| Shared component or costly repair | Medium | gpt-6.1-sol |
| Critical, irreversible, or unknown | High | gpt-6-astra |

One failed implementation attempt escalates a replacement to Astra. Three failed
attempts for the same issue stop; replacements retain the count. Model selection
never overrides dependency, ownership, capacity, batch binding or receipt gates.
Invalid input and unavailable models refuse dispatch. Models must be advertised
by the current host. Native creation remains the coordinator's responsibility;
this helper does not intercept arbitrary spawn calls.

The running coordinator and independent review/QA models are unchanged. Different
independent ACs can use different models concurrently. No canonical TASK schema,
Claude routing, CCC host configuration or live installation changes are needed.
The seven receipt fixes documented in REQ__codex-followup-receipts.md remain
preserved. Focused tests cover classification, escalation limits, unsupported
models and the CLI refusal path.
