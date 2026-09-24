# Fix-First Pattern

A pre-review self-check over your own diff, plus the escalation rule for every
fix loop in develop.

## Pre-review self-check

After each AC and once over the whole diff before Phase 6.6 review, reread
your change against the minimum-sufficient ladder in
`${CLAUDE_PLUGIN_ROOT}/agents/developer.md` and fix what you find in the lines you changed:

- `delete`: dead code, unused flexibility, or a speculative feature you added.
- `reuse`: something you wrote that already exists in the codebase.
- `stdlib` / `native`: hand-rolled logic the standard library or platform ships.
- `yagni`: an abstraction with one implementation, a config nobody sets, or a
  defense against a state the code already rules out.

Stay inside the AC: do not rename, retype, or restructure adjacent code that
you did not change. Decisions that change an API, architecture, data model,
error strategy, concurrency model, or security posture go to the user or the
final response instead of being made here.

## 3-Attempt Escalation Rule

Applies to any fix loop in develop: per-AC fix, Phase 7 verification fix, Phase 7
browser debug (browser-verification.md). If the SAME issue fails to resolve after
3 consecutive fix attempts, STOP. Do not try a 4th attempt.

Track attempts per issue in working context and include the current count and
last failure in an auto-checkpoint note when a session boundary is possible.
Do not add an `attempts` key to canonical PROGRESS.md.
An "issue" is identified by {test_name | symptom | file:line} — different
failures in the same cycle don't share a counter.

On the 3rd failure, invoke `AskUserQuestion` with this structured format:

```
AskUserQuestion:
  Question: "3 fix attempts exhausted for <issue>. How should we proceed?"
  Context:
    REASON: <why the current approach keeps failing — one sentence>
    ATTEMPTED:
      1. <attempt 1 summary + failure mode>
      2. <attempt 2 summary + failure mode>
      3. <attempt 3 summary + failure mode>
    RECOMMENDATION: <best next step — root-cause analysis, defer to human,
                    widen scope, re-examine the test, etc.>
  Options:
    - A) Run structured root-cause analysis with `hypothesis-driven-debugging.md`
    - B) Defer — mark AC/test as deferred with details
    - C) Extend budget (allow 2 more attempts — user must explicitly approve)
    - D) Revert the changes and re-plan
```

Log the escalation:
```bash
echo '{"ts":"'"$(date -u +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || echo unknown)"'","type":"escalation","source":"fix-first","key":"3-attempt-exhausted","issue":"<issue>","task":"'"<task_id>"'"}' >> doc/harness/learnings.jsonl 2>/dev/null || true
```

Never silently keep trying past 3. Thrashing is a signal to stop, not to try harder.
