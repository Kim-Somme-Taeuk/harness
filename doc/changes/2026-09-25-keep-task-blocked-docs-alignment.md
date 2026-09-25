---
date: 2026-09-25
task: TASK__remove-blocked-env-pause-path
tags: [contracts, lifecycle, task_blocked, docs]
---

# task_blocked stays as the park record

The plan to delete `task_blocked` and `BLOCKED.md` (2026-09-02, "only PASS may
end a turn") was withdrawn. That rule was enforced by the Claude Stop hook,
which was intentionally removed on 2026-09-23, so `task_blocked` no longer
lets a turn escape any gate. It only records why an open task stopped and what
unblocks it. C-17 in `CONTRACTS.md` and the setup template now carries a
**Parking clause**: parking is not completion, grants no PASS, does not bypass
C-04, and the task resumes with plain `task_start`. `plugin/CLAUDE.md` §4a
says the same. Five doc passages that still described the stop gate in the
present tense are now past tense. Runtime behavior is unchanged. Existing
projects receive the template clause the next time setup regenerates their
`CONTRACTS.md`. Background: `doc/harness/REQ__task-blocked-is-the-park-record.md`.
