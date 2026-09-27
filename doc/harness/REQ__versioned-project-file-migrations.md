---
tags: [harness, setup, migration, gitignore]
summary: Harness 관리 파일 변경은 manifest의 정수 top-level version 하나로 번호를 매기고 검증된 순차 마이그레이션으로 갱신한다.
updated: 2026-09-27
freshness: current
invalidated_by_paths:
  - plugin/scripts/setup_finalize.py
  - plugin/scripts/project_format_check.py
  - plugin/scripts/hook_session_start.py
  - plugin/hooks/hooks.json
freshness_updated: 2026-09-27T00:00:00Z
---

# REQ — Harness 버전 마이그레이션

`doc/harness/manifest.yaml`의 최상위 `version` 필드는 Harness가 프로젝트
안에 관리하는 파일 구성의 정수 버전 하나다. 관리 파일의 필드 추가·폐기,
운영 파일 ignore 규칙 변경처럼 기존 프로젝트에 적용해야 할 변경이 생길
때마다 `version`을 1씩 올리고 해당 번호의 마이그레이션을 정의한다. 버전을
올리는 일만으로는 기존 프로젝트를 갱신한 것으로 보지 않는다.

버전 1-5는 기존 manifest 스키마 마이그레이션(필드 구조 변경)이다. 버전 6은
Harness 운영 파일의 표준 `.gitignore` 목록(`doc/harness/.watcher-diagnostics.json`
포함)을 적용하고, 옛 `harness_version` 키와 `doc/harness/.version`,
`doc/harness/.format-version` 파일을 제거한다. 버전 7은 표준 목록에
`.claude/worktrees/`(`harness:batch` 리드와 Claude Code 격리 에이전트가 만드는
linked worktree 위치)를 추가한다. 런타임과 무관하게 모든 프로젝트에 적용한다
(사용자 결정 2026-09-27). 필드가 없는 프로젝트는 버전 0으로 읽는다.

버전 7의 검증 조건과 복구 경로는 다음과 같다. `.claude/worktrees/` 아래 경로가
`git check-ignore`로 ignore되고, 그 아래에 추적 중인 파일이나 gitlink가 없어야
`version: 7`을 기록하고 `HARNESS_MIGRATION_OK: version=7 updated=true`를
출력한다(재실행은 `updated=false`). 사용자가 이미 적어 둔
`.claude/worktrees/` 줄은 관리 블록으로 옮겨져 한 번만 남는다. 추적 중인
경로가 있으면 `operational artifact is already tracked: <path>`로 실패하고,
`.gitignore`를 되돌리며 버전을 올리지 않는다. 사용자가
`git rm --cached -r .claude/worktrees/<name>`로 추적을 해제한 뒤 명령을 다시
실행한다.

`.claude/worktrees/`는 Harness가 쓰지 않는 ignore 전용 항목이라 관리 경로
symlink 검사를 적용하지 않는다. 대신 ignore와 추적 검사를 Git이 실제로 보는
경로에서 한다. `.claude`처럼 상위 경로가 저장소 밖을 가리키는 symlink이면
Git은 그 너머를 추적하거나 나열하지 않으므로 이 항목은 자동으로 충족된다.
symlink가 저장소 안을 가리키면(예: `.claude -> config/claude`) Git이 보는
실제 경로(`config/claude/worktrees/`)가 ignore되고 추적되지 않아야 한다.
실패 메시지는 `(git sees config/claude/worktrees/__harness_probe__)`처럼 그
경로를 알려 주며, 사용자가 해당 경로를 `.gitignore`에 추가한 뒤 다시
실행한다. `.claude/worktrees` 자체가 symlink이면 끝에 `/`가 붙은 규칙은 그
symlink와 맞지 않아 `existing operational path is not effectively ignored:
.claude/worktrees`로 실패한다. 사용자가 `/.claude/worktrees` 규칙을
추가하거나(대상이 저장소 안이면 그 대상 경로도 함께) symlink를 실제
디렉터리로 바꾼 뒤 다시 실행한다.

`--migrate-harness-version` 명령은 기존 사용자 ignore 규칙을 보존하면서
표준 목록을 적용하고, 실제 ignore 동작을 검증한 뒤에만 manifest에 새 버전
번호를 기록한다. 이미 추적 중인 운영 파일은 ignore 규칙만으로 숨길 수
없으므로 마이그레이션을 실패로 보고한다. 에이전트는 사용자의 추적 상태를
임의로 변경하지 않는다. 명령은 정확한 Git 루트만 받는다. 하위 디렉터리에서
시작한 세션의 안내도 실제 루트의 절대 경로를 사용한다.

Codex와 Claude의 SessionStart 검사는 읽기 전용이다. manifest `version`이
지원 버전(현재 7)보다 낮거나, ignore 목록이 표준과 다르거나, 옛
`harness_version` 키나 `doc/harness/.version`/`.format-version` 파일이
남아 있으면 마이그레이션 명령을 안내한다. 현재 버전과 규칙이 모두 맞으면
메시지를 내지 않는다. 지원 범위를 넘는 미래 버전이나 잘못된 필드 값은
자동으로 덮어쓰지 않고 진단한다. 마이그레이션은 반복 실행해도 같은
결과여야 한다(idempotent).

향후 변경은 항상 버전을 1 올리고, 그 번호의 변경 내용·검증 조건·실패 시
복구 경로를 마이그레이션 코드와 테스트에 함께 추가한다. setup SKILL.md(두
런타임), bootstrap.md, verify-report.md, `plugin/scripts/README.md`에
하드코딩된 지원 버전 값은 `setup_finalize.py`의 `MANIFEST_VERSION`과 같아야
하며, `tests/test_manifest_version_drift.py`가 이를 보장한다.
