"""Contract guards for the harness:task-lead agent and harness:batch skill.

Covers TASK__parallel-tasks-in-one-session AC-004: the batch-lead agent
definition, the batch coordinator skill, and the develop skill's batch-lead
carve-outs.
"""
from __future__ import annotations

from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
TASK_LEAD = REPO / "plugin" / "agents" / "task-lead.md"
BATCH_SKILL = REPO / "plugin" / "skills" / "batch" / "SKILL.md"
DEVELOP_SKILL = REPO / "plugin" / "skills" / "develop" / "SKILL.md"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _frontmatter(path: Path) -> dict[str, str]:
    lines = _text(path).splitlines()
    assert lines and lines[0] == "---", f"{path} must start with frontmatter"
    data: dict[str, str] = {}
    for line in lines[1:]:
        if line == "---":
            return data
        if ":" not in line or line.startswith((" ", "\t")):
            continue
        key, value = line.split(":", 1)
        data[key.strip()] = value.strip()
    raise AssertionError(f"{path} frontmatter is not closed")


def _normalized(body: str) -> str:
    return " ".join(body.lower().split())


def _assert_all(body: str, fragments: tuple[str, ...], path: Path) -> None:
    lowered = _normalized(body)
    for fragment in fragments:
        assert _normalized(fragment) in lowered, f"{path}: missing {fragment!r}"


def test_task_lead_frontmatter_declares_worktree_isolation_and_inherits_tools():
    meta = _frontmatter(TASK_LEAD)
    assert meta.get("isolation") == "worktree", TASK_LEAD
    # A lead runs the whole lifecycle: it needs Agent, Skill and the harness MCP
    # task tools under whatever server name the host exposes (plugin-scoped
    # `mcp__plugin_harness_harness__*` or a user-level `mcp__harness__*`). A
    # `tools:` allowlist naming one form strips the tools under the other.
    assert "tools" not in meta, f"{TASK_LEAD}: must inherit the session's tools"


def test_task_lead_body_states_batch_carveouts():
    body = _text(TASK_LEAD)
    _assert_all(
        body,
        (
            "workspace",
            "AskUserQuestion",
            "install_verified.py",
            "git rev-parse HEAD",
            "coordinator",
            "never `cd`",
            "plain",
            "installed plugin",
        ),
        TASK_LEAD,
    )
    # Never call AskUserQuestion is a prohibition, not a step it performs.
    assert "never call `askuserquestion`" in _normalized(body)


def test_batch_skill_frontmatter_and_weight():
    meta = _frontmatter(BATCH_SKILL)
    assert meta.get("name") == "batch", BATCH_SKILL
    assert "parallel" in meta.get("description", "").lower(), BATCH_SKILL
    assert "one session" in meta.get("description", "").lower(), BATCH_SKILL

    line_count = len(_text(BATCH_SKILL).splitlines())
    assert line_count <= 500, f"{BATCH_SKILL} has {line_count} lines, budget is 500"


def test_batch_skill_names_every_coordinator_step():
    body = _text(BATCH_SKILL)
    _assert_all(
        body,
        (
            "one assistant message",
            "3 concurrent leads",
            "git merge --ff-only",
            "rebase --no-autostash",
            "batch_harvest.py",
            "git worktree remove",
            "never",
            "--force",
            "TASK__batch-integrate",
            "install_verified.py",
            "baseRef",
            "\"head\"",
            "branches and commits only",
        ),
        BATCH_SKILL,
    )


def test_batch_skill_covers_conflict_and_blocked_lead_handling():
    body = _text(BATCH_SKILL)
    _assert_all(
        body,
        (
            "rebase --abort",
            "GIT_EDITOR=true",
            "rebase --continue",
            "carry",
            "integration task",
            "blocked",
            "failed",
            "kept",
        ),
        BATCH_SKILL,
    )


def test_batch_skill_integrates_leads_without_merge_commits():
    body = _text(BATCH_SKILL)
    assert "--no-ff" not in body, BATCH_SKILL
    assert "git merge --abort" not in body, BATCH_SKILL
    assert "never by a merge commit" in body, BATCH_SKILL
    assert "fall back to a merge commit" in body, BATCH_SKILL
    _assert_all(
        body,
        (
            # The branch is checked out in the lead worktree: rebase runs there.
            'git -C <W> rebase --no-autostash "$(git rev-parse HEAD)"',
            # A rebase drops a merge commit's own change; refuse such a lead.
            'git rev-list --merges "$(git rev-parse HEAD)..<branch>"',
            # A conflict and a dirty refusal share exit 1; paths tell them apart.
            "git -C <W> diff --name-only --diff-filter=U",
            "git -C <W> rebase --abort",
            "go on to the next closed lead",
        ),
        BATCH_SKILL,
    )


def test_develop_skill_points_to_task_lead_carveouts():
    body = _text(DEVELOP_SKILL)
    assert "plugin/agents/task-lead.md" in body, DEVELOP_SKILL
    # Referenced once near the write-focus pre-flight and once near auto-install.
    assert body.count("plugin/agents/task-lead.md") >= 2, DEVELOP_SKILL
    _assert_all(
        body,
        (
            "never calls `AskUserQuestion`",
            "skips this step",
        ),
        DEVELOP_SKILL,
    )


def test_root_claude_md_states_batch_focus_and_install_clauses():
    body = _normalized(_text(REPO / "CLAUDE.md"))
    assert _normalized(
        "In `harness:batch` mode, batch leads skip this verified install; it runs "
        "once from the post-merge integration task in the main checkout."
    ) in body
    assert _normalized(
        "Each linked git worktree is its own checkout with its own write focus"
    ) in body


def test_batch_skill_runs_harvest_from_plugin_root_unlocks_and_integrates_every_closed_lead():
    body = _text(BATCH_SKILL)
    norm = _normalized(body)
    # User projects have no plugin/scripts/; the installed payload does.
    assert "${claude_plugin_root}/scripts/batch_harvest.py" in norm
    assert "python3 plugin/scripts/batch_harvest.py" not in norm
    # Claude Code keeps its agent lock after the lead returns.
    assert "git worktree unlock" in norm
    assert _normalized("never unlock a worktree whose lead is still running") in norm
    # A conflict never strands later closed leads.
    assert _normalized("continue steps d.1–d.4 in order for every remaining closed lead") in norm


def test_c09_batch_clause_is_in_root_and_template_contracts():
    clause = _normalized(
        "Each linked git worktree is a separate checkout with its own write focus; "
        "a coordinator may run one task per worktree via `harness:batch`"
    )
    for path in (REPO / "CONTRACTS.md", REPO / "plugin/skills/setup/templates/CONTRACTS.md"):
        body = _text(path)
        c09 = body[body.index("### C-09"):body.index("### C-10")]
        assert clause in _normalized(c09), path


def test_this_repo_branches_leads_from_head_and_ignores_worktrees():
    import json
    import subprocess

    settings = json.loads((REPO / ".claude/settings.json").read_text(encoding="utf-8"))
    assert settings["worktree"]["baseRef"] == "head"
    ignored = subprocess.run(
        ["git", "check-ignore", "-q", ".claude/worktrees/probe"], cwd=REPO,
    )
    assert ignored.returncode == 0


def test_batch_skill_rejects_reused_slugs_before_integrating():
    norm = _normalized(_text(BATCH_SKILL))
    assert _normalized("Slugs must be distinct within the batch") in norm
    assert "doc/harness/archive/batch/task__<slug>" in norm
    assert _normalized("integration stopped at a conflict carried from step d.2") in norm


def test_batch_skill_gates_spawning_on_the_repo_shape_preflight():
    body = _text(BATCH_SKILL)
    norm = _normalized(body)
    # Installed payload path, like batch_harvest; a user project has no plugin/.
    assert "${claude_plugin_root}/scripts/batch_preflight.py" in norm
    assert "python3 plugin/scripts/batch_preflight.py" not in norm
    assert _normalized("Spawn only when it exits 0") in norm
    for shape in ("`submodule-checkout`", "`linked-worktree`", "`non-git`", "`separate-git-dir`"):
        assert shape in norm, shape
    _assert_all(
        body,
        (
            "in every populated submodule, and in every ignored nested repo",
            "`inside-submodule` or `inside-ignored-nested-repo` is not batched",
            "ordinary harness task in the main checkout",
            "`outside-root` scope cannot run in a batch lead",
            "excluded_requests",
            "overlaps",
            "off-limits: <preflight off_limits",
            "keep it and report it like a blocked lead",
            # One path per flag; `ok` is necessary, not sufficient.
            "--request <slug>=<path> --request <slug>=<path2>",
            "a comma list is refused",
            "exits 0 (`verdict: \"ok\"`) and steps b.2–b.5 hold",
            # Step g accounts for every request kept out of the wave.
            "excluded (ordinary task, done or pending)",
            "deferred to a later wave",
            "outside the root, not batchable",
        ),
        BATCH_SKILL,
    )
    # The plain root-only status check is gone; the script owns cleanliness.
    assert _normalized("`git status --porcelain` in the main checkout must be empty") not in norm


def test_task_lead_forbids_submodule_commands_and_nested_repo_edits():
    body = _text(TASK_LEAD)
    norm = _normalized(body)
    for subcommand in ("update", "init", "deinit", "sync", "set-url", "absorbgitdirs"):
        assert f"`{subcommand}`" in norm or f"git submodule {subcommand}" in norm, subcommand
    _assert_all(
        body,
        (
            "Never run `git submodule update`",
            "any other `git submodule` subcommand except `status`",
            "`--recurse-submodules`",
            "`-c submodule.recurse=true`",
            "Never edit a path inside a submodule, inside an ignored nested repo",
            "`off-limits`",
            "return `verdict: \"blocked\"` with that reason",
        ),
        TASK_LEAD,
    )


def test_req_documents_worktree_location_and_multi_repo_shapes():
    path = REPO / "doc/harness/REQ__parallel-tasks-via-worktree-leads.md"
    body = _text(path)
    frontmatter = body.split("\n---", 1)[0]
    assert "plugin/scripts/batch_preflight.py" in frontmatter
    assert "\n## Worktree location\n" in body
    assert "\n## Multi-repo and submodules\n" in body
    _assert_all(
        body,
        (
            "validates registration, not path",
            "$CODEX_HOME/worktrees",
            "WorktreeCreate hook",
            "read-only",
            "same 9p mount",
            "It is NOT recommended to make multiple checkouts of a superproject.",
            "refuses that worktree forever",
            "Goal child G",
        ),
        path,
    )


def test_task_lead_never_touches_the_coordinator_goal_and_defines_verdicts():
    norm = _normalized(_text(TASK_LEAD))
    assert _normalized("Never call the `goal_*` tools") in norm
    for verdict in ("`closed`", "`blocked`", "`failed`"):
        assert verdict in norm
    assert _normalized("`failed` when the lifecycle could not reach PASS") in norm
