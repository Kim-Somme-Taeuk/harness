from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path



ROOT = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location(
    "batch_harvest", ROOT / "plugin/scripts/batch_harvest.py"
)
assert SPEC and SPEC.loader
mod = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = mod
SPEC.loader.exec_module(mod)


def _git(*args, cwd):
    result = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, f"git {args} failed: {result.stderr}"
    return result.stdout.strip()


def _init_repo(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    _git("init", "-q", cwd=repo)
    _git("config", "user.email", "test@example.com", cwd=repo)
    _git("config", "user.name", "Test", cwd=repo)
    (repo / "README.md").write_text("root\n", encoding="utf-8")
    (repo / "doc/harness").mkdir(parents=True, exist_ok=True)
    (repo / "doc/harness/manifest.yaml").write_text("version: 5\n", encoding="utf-8")
    _git("add", "README.md", "doc/harness/manifest.yaml", cwd=repo)
    _git("commit", "-q", "-m", "init", cwd=repo)


def _add_worktree(repo: Path, worktree: Path, branch: str) -> None:
    worktree.parent.mkdir(parents=True, exist_ok=True)
    _git("worktree", "add", "-b", branch, str(worktree), cwd=repo)


def _write_task(root: Path, task_id: str, content: str = "plan\n") -> Path:
    """Write task evidence directly in the worktree's filesystem, the way a
    lead's gitignored doc/harness/tasks/ actually behaves: never git-added."""
    task_dir = root / "doc/harness/tasks" / task_id
    task_dir.mkdir(parents=True, exist_ok=True)
    (task_dir / "PLAN.md").write_text(content, encoding="utf-8")
    return task_dir


def _write_learnings(root: Path, rows: list) -> None:
    (root / "doc/harness/learnings.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8",
    )


def _rebase_and_fast_forward(repo: Path, worktree: Path, branch: str) -> None:
    """The batch skill's step d.1: rebase the lead branch onto the main
    checkout's HEAD inside the lead worktree, then fast-forward main."""
    base = _git("rev-parse", "HEAD", cwd=repo)
    _git("rebase", "-q", "--no-autostash", base, cwd=worktree)
    _git("merge", "-q", "--ff-only", branch, cwd=repo)


def _commit_and_merge(repo: Path, worktree: Path, branch: str) -> None:
    """Commit a real, git-tracked source change on `branch` in the worktree
    and integrate it into the main checkout's HEAD. Mirrors how a lead's actual
    code change is what gets integrated, while its gitignored task evidence and
    learnings stay worktree-local (never git-added, never touched by git)."""
    (worktree / "src.txt").write_text(f"change from {branch}\n", encoding="utf-8")
    _git("add", "src.txt", cwd=worktree)
    _git("commit", "-q", "-m", f"{branch} work", cwd=worktree)
    _rebase_and_fast_forward(repo, worktree, branch)


def _raises(exc, match=None):
    import pytest

    return pytest.raises(exc, match=match)


def _main_repo(tmp_path: Path) -> Path:
    r = tmp_path / "main"
    _init_repo(r)
    return r


def test_happy_path_copy_and_append(tmp_path: Path):
    repo = _main_repo(tmp_path)
    worktree = tmp_path / "wt"
    _add_worktree(repo, worktree, "lead-1")

    task_id = "TASK__demo"
    _write_task(worktree, task_id, "plan body\n")
    _write_learnings(worktree, [
        {"key": "a", "insight": "one"},
        {"key": "b", "insight": "two"},
    ])
    _commit_and_merge(repo, worktree, "lead-1")

    summary = mod.harvest(str(repo), str(worktree), task_id)

    dest = repo / "doc/harness/archive/batch" / task_id
    assert dest.is_dir()
    assert (dest / "PLAN.md").read_text(encoding="utf-8") == "plan body\n"
    assert summary["archived"] == str(dest)
    assert summary["learnings_appended"] == 2

    learnings = (repo / "doc/harness/learnings.jsonl").read_text(encoding="utf-8")
    assert '"insight": "one"' in learnings
    assert '"insight": "two"' in learnings


def test_idempotent_second_run_appends_zero(tmp_path: Path):
    repo = _main_repo(tmp_path)
    worktree = tmp_path / "wt"
    _add_worktree(repo, worktree, "lead-1")
    task_id = "TASK__demo"
    _write_task(worktree, task_id)
    _write_learnings(worktree, [{"key": "a"}])
    _commit_and_merge(repo, worktree, "lead-1")

    first = mod.harvest(str(repo), str(worktree), task_id)
    assert first["learnings_appended"] == 1

    second = mod.harvest(str(repo), str(worktree), task_id)
    assert second["learnings_appended"] == 0
    assert second["archived"] == first["archived"]

    dest = Path(second["archived"])
    assert (dest / "PLAN.md").exists()


def test_refuses_plain_directory(tmp_path: Path):
    repo = _main_repo(tmp_path)
    plain = tmp_path / "not_a_worktree"
    plain.mkdir()
    _write_task(plain, "TASK__demo")

    with _raises(mod.HarvestError):
        mod.harvest(str(repo), str(plain), "TASK__demo")

    assert not (repo / "doc/harness/archive/batch").exists()


def test_refuses_worktree_of_different_repo(tmp_path: Path):
    repo = _main_repo(tmp_path)
    other_repo = tmp_path / "other"
    _init_repo(other_repo)
    other_worktree = tmp_path / "other_wt"
    _add_worktree(other_repo, other_worktree, "lead-x")
    _write_task(other_worktree, "TASK__demo")

    with _raises(mod.HarvestError):
        mod.harvest(str(repo), str(other_worktree), "TASK__demo")

    assert not (repo / "doc/harness/archive/batch").exists()


def test_refuses_forged_back_pointer(tmp_path: Path):
    repo = _main_repo(tmp_path)
    worktree = tmp_path / "wt"
    _add_worktree(repo, worktree, "lead-1")
    _write_task(worktree, "TASK__demo")
    _commit_and_merge(repo, worktree, "lead-1")

    # Forge the back-pointer inside .git/worktrees/<name>/gitdir so it no
    # longer names this worktree's .git file.
    gitfile_text = (worktree / ".git").read_text(encoding="utf-8")
    assert gitfile_text.startswith("gitdir: ")
    metadata_dir = Path(gitfile_text[len("gitdir: "):].strip())
    back_pointer = metadata_dir / "gitdir"
    back_pointer.write_text(str(tmp_path / "somewhere-else" / ".git") + "\n", encoding="utf-8")

    with _raises(mod.HarvestError, match="back-pointer"):
        mod.harvest(str(repo), str(worktree), "TASK__demo")

    assert not (repo / "doc/harness/archive/batch").exists()


def test_refuses_unmerged_branch(tmp_path: Path):
    repo = _main_repo(tmp_path)
    worktree = tmp_path / "wt"
    _add_worktree(repo, worktree, "lead-1")
    _write_task(worktree, "TASK__demo")
    (worktree / "src.txt").write_text("unmerged change\n", encoding="utf-8")
    subprocess.run(["git", "add", "src.txt"], cwd=worktree, check=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "unmerged lead work"], cwd=worktree, check=True,
    )
    # Deliberately do not merge lead-1 into the main checkout's HEAD.

    with _raises(mod.HarvestError, match="not merged"):
        mod.harvest(str(repo), str(worktree), "TASK__demo")

    assert not (repo / "doc/harness/archive/batch").exists()


def _ignore_task_evidence(repo: Path) -> None:
    """Commit the ignores a real project has, so task evidence stays out of git
    and `git worktree remove` sees a clean lead worktree."""
    (repo / ".gitignore").write_text(
        "doc/harness/tasks/\ndoc/harness/learnings.jsonl\ndoc/harness/archive/\n",
        encoding="utf-8",
    )
    _git("add", ".gitignore", cwd=repo)
    _git("commit", "-q", "-m", "ignore task evidence", cwd=repo)


def _lead_commit(worktree: Path, name: str, body: str, message: str) -> None:
    (worktree / name).write_text(body, encoding="utf-8")
    _git("add", name, cwd=worktree)
    _git("commit", "-q", "-m", message, cwd=worktree)


def test_two_leads_rebased_and_fast_forwarded_are_harvested_and_removed(tmp_path: Path):
    repo = _main_repo(tmp_path)
    _ignore_task_evidence(repo)
    base = _git("rev-parse", "HEAD", cwd=repo)
    leads = []
    for n in (1, 2):
        worktree = tmp_path / f"wt{n}"
        branch = f"lead-{n}"
        _add_worktree(repo, worktree, branch)
        _git("worktree", "lock", str(worktree), cwd=repo)  # Claude's agent lock
        task_id = f"TASK__lead{n}"
        _write_task(worktree, task_id, f"plan {n}\n")
        _write_learnings(worktree, [{"key": f"k{n}", "insight": f"lead {n}"}])
        _lead_commit(worktree, f"file{n}.txt", f"lead {n}\n", f"lead {n} work")
        leads.append((worktree, branch, task_id))

    tip_before = _git("rev-parse", "HEAD", cwd=leads[1][0])
    for index, (worktree, branch, task_id) in enumerate(leads):
        if index == 1:
            # Rebased but not yet fast-forwarded: harvest must refuse.
            base_now = _git("rev-parse", "HEAD", cwd=repo)
            _git("rebase", "-q", "--no-autostash", base_now, cwd=worktree)
            with _raises(mod.HarvestError, match="not merged"):
                mod.harvest(str(repo), str(worktree), task_id)
        _rebase_and_fast_forward(repo, worktree, branch)
        assert _git("rev-parse", "HEAD", cwd=worktree) == _git("rev-parse", "HEAD", cwd=repo)
        summary = mod.harvest(str(repo), str(worktree), task_id)
        assert summary["learnings_appended"] == 1
        _git("worktree", "unlock", str(worktree), cwd=repo)
        _git("worktree", "remove", str(worktree), cwd=repo)
        _git("branch", "-d", branch, cwd=repo)

    # The second lead was rewritten onto the first; history is linear.
    assert _git("rev-parse", "HEAD", cwd=repo) != tip_before
    assert _git("rev-list", "--merges", f"{base}..HEAD", cwd=repo) == ""
    assert _git("log", "--format=%s", f"{base}..HEAD", cwd=repo).splitlines() == [
        "lead 2 work", "lead 1 work",
    ]
    for _, _, task_id in leads:
        assert (repo / "doc/harness/archive/batch" / task_id / "PLAN.md").is_file()
    assert _git("worktree", "list", "--porcelain", cwd=repo).count("worktree ") == 1


def test_rebase_conflict_abort_restores_the_lead_and_leaves_main(tmp_path: Path):
    repo = _main_repo(tmp_path)
    _ignore_task_evidence(repo)
    first, second = tmp_path / "wt1", tmp_path / "wt2"
    _add_worktree(repo, first, "lead-1")
    _add_worktree(repo, second, "lead-2")
    _lead_commit(first, "shared.txt", "from lead 1\n", "lead 1 work")
    _lead_commit(second, "shared.txt", "from lead 2\n", "lead 2 work")
    _rebase_and_fast_forward(repo, first, "lead-1")
    main_head = _git("rev-parse", "HEAD", cwd=repo)
    lead_tip = _git("rev-parse", "HEAD", cwd=second)

    conflict = subprocess.run(
        ["git", "rebase", "-q", "--no-autostash", main_head],
        cwd=second, capture_output=True, text=True, check=False,
    )
    assert conflict.returncode != 0
    _git("rebase", "--abort", cwd=second)

    assert _git("rev-parse", "HEAD", cwd=second) == lead_tip
    assert _git("status", "--porcelain", cwd=second) == ""
    assert _git("rev-parse", "HEAD", cwd=repo) == main_head
    with _raises(mod.HarvestError, match="not merged"):
        mod.harvest(str(repo), str(second), "TASK__lead2")


def test_rebase_stopped_at_a_conflict_is_refused_then_continued_and_integrated(tmp_path: Path):
    """A stopped rebase detaches the worktree HEAD at the main HEAD, which
    passes the ancestor check; harvest must refuse it. The integration task
    then resolves, continues, fast-forwards, harvests, and removes."""
    repo = _main_repo(tmp_path)
    _ignore_task_evidence(repo)
    first, second = tmp_path / "wt1", tmp_path / "wt2"
    _add_worktree(repo, first, "lead-1")
    _add_worktree(repo, second, "lead-2")
    _write_task(second, "TASK__lead2")
    _lead_commit(first, "shared.txt", "from lead 1\n", "lead 1 work")
    _lead_commit(second, "shared.txt", "from lead 2\n", "lead 2 work")
    _rebase_and_fast_forward(repo, first, "lead-1")
    main_head = _git("rev-parse", "HEAD", cwd=repo)

    stopped = subprocess.run(
        ["git", "rebase", "-q", "--no-autostash", main_head],
        cwd=second, capture_output=True, text=True, check=False,
    )
    assert stopped.returncode != 0
    assert _git("diff", "--name-only", "--diff-filter=U", cwd=second) == "shared.txt"
    assert _git("rev-parse", "HEAD", cwd=second) == main_head  # detached at main
    with _raises(mod.HarvestError, match="detached"):
        mod.harvest(str(repo), str(second), "TASK__lead2")
    assert not (repo / "doc/harness/archive/batch/TASK__lead2").exists()

    (second / "shared.txt").write_text("from lead 1\nfrom lead 2\n", encoding="utf-8")
    _git("add", "shared.txt", cwd=second)
    env = {**os.environ, "GIT_EDITOR": "true"}
    subprocess.run(["git", "rebase", "--continue"], cwd=second, env=env,
                   capture_output=True, check=True)
    _git("merge", "-q", "--ff-only", "lead-2", cwd=repo)
    mod.harvest(str(repo), str(second), "TASK__lead2")
    _git("worktree", "remove", str(second), cwd=repo)
    _git("branch", "-d", "lead-2", cwd=repo)

    assert (repo / "shared.txt").read_text(encoding="utf-8") == "from lead 1\nfrom lead 2\n"
    assert _git("rev-list", "--merges", "HEAD", cwd=repo) == ""
    assert (repo / "doc/harness/archive/batch/TASK__lead2/PLAN.md").is_file()


def test_refuses_invalid_task_id(tmp_path: Path):
    repo = _main_repo(tmp_path)
    worktree = tmp_path / "wt"
    _add_worktree(repo, worktree, "lead-1")
    _commit_and_merge(repo, worktree, "lead-1")

    with _raises(mod.HarvestError, match="invalid task_id"):
        mod.harvest(str(repo), str(worktree), "../escape")

    assert not (repo / "doc/harness/archive/batch").exists()


def _merged_lead(repo: Path, tmp_path: Path, branch: str = "lead-x") -> Path:
    worktree = tmp_path / branch
    _add_worktree(repo, worktree, branch)
    _commit_and_merge(repo, worktree, branch)
    return worktree


def test_refuses_symlink_inside_task_evidence(tmp_path: Path):
    repo = _main_repo(tmp_path)
    worktree = _merged_lead(repo, tmp_path)
    task_dir = _write_task(worktree, "TASK__demo")
    secret = tmp_path / "secret.txt"
    secret.write_text("secret\n", encoding="utf-8")
    (task_dir / "leak").symlink_to(secret)
    with _raises(mod.HarvestError, match="non-regular entry"):
        mod.harvest(str(repo), str(worktree), "TASK__demo")
    assert not (repo / "doc/harness/archive/batch/TASK__demo").exists()


def test_refuses_symlinked_evidence_parent_and_fifo(tmp_path: Path):
    repo = _main_repo(tmp_path)
    worktree = _merged_lead(repo, tmp_path)
    outside = tmp_path / "outside-tasks"
    _write_task(outside, "TASK__demo")
    (worktree / "doc/harness/tasks").symlink_to(outside / "doc/harness/tasks")
    with _raises(mod.HarvestError, match="symlink"):
        mod.harvest(str(repo), str(worktree), "TASK__demo")

    worktree2 = _merged_lead(repo, tmp_path, "lead-y")
    task_dir = _write_task(worktree2, "TASK__demo")
    os.mkfifo(task_dir / "pipe")
    with _raises(mod.HarvestError, match="non-regular entry"):
        mod.harvest(str(repo), str(worktree2), "TASK__demo")


def test_learnings_links_refused_and_non_json_rows_skipped(tmp_path: Path):
    repo = _main_repo(tmp_path)
    worktree = _merged_lead(repo, tmp_path)
    _write_task(worktree, "TASK__demo")
    real = tmp_path / "rows.jsonl"
    real.write_text('{"k": 1}\n', encoding="utf-8")
    (worktree / "doc/harness/learnings.jsonl").symlink_to(real)
    with _raises(mod.HarvestError, match="symlink"):
        mod.harvest(str(repo), str(worktree), "TASK__demo")
    assert not (repo / "doc/harness/archive/batch/TASK__demo").exists()

    (worktree / "doc/harness/learnings.jsonl").unlink()
    (worktree / "doc/harness/learnings.jsonl").write_text(
        '{"k": 1}\nnot json\n["array"]\n{"k": 2}\n', encoding="utf-8",
    )
    summary = mod.harvest(str(repo), str(worktree), "TASK__demo")
    assert summary["learnings_appended"] == 2
    assert (repo / "doc/harness/learnings.jsonl").read_text(encoding="utf-8") == '{"k": 1}\n{"k": 2}\n'


def test_refuses_to_replace_a_different_archive_for_the_same_task_id(tmp_path: Path):
    repo = _main_repo(tmp_path)
    first = _merged_lead(repo, tmp_path, "lead-a")
    _write_task(first, "TASK__fix", "evidence from batch 1\n")
    mod.harvest(str(repo), str(first), "TASK__fix")
    archived = repo / "doc/harness/archive/batch/TASK__fix/PLAN.md"
    assert archived.read_text(encoding="utf-8") == "evidence from batch 1\n"

    second = _merged_lead(repo, tmp_path, "lead-b")
    _write_task(second, "TASK__fix", "evidence from batch 2\n")
    with _raises(mod.HarvestError, match="refusing to overwrite"):
        mod.harvest(str(repo), str(second), "TASK__fix")
    assert archived.read_text(encoding="utf-8") == "evidence from batch 1\n"


def test_ambient_git_env_cannot_redirect_the_merged_check(tmp_path: Path, monkeypatch):
    repo = _main_repo(tmp_path)
    decoy = tmp_path / "decoy"
    _init_repo(decoy)
    worktree = tmp_path / "wt"
    _add_worktree(repo, worktree, "lead-env")
    (worktree / "src.txt").write_text("unmerged\n", encoding="utf-8")
    _git("add", "src.txt", cwd=worktree)
    _git("commit", "-q", "-m", "unmerged", cwd=worktree)
    _write_task(worktree, "TASK__demo")
    # Pointing git at a decoy repository must not make an unmerged lead look merged.
    monkeypatch.setenv("GIT_DIR", str(decoy / ".git"))
    with _raises(mod.HarvestError):
        mod.harvest(str(repo), str(worktree), "TASK__demo")
    assert not (repo / "doc/harness/archive/batch/TASK__demo").exists()


def test_non_canonical_worktree_path_is_canonicalized_before_use(tmp_path: Path):
    repo = _main_repo(tmp_path)
    worktree = _merged_lead(repo, tmp_path, "lead-c")
    _write_task(worktree, "TASK__demo")
    alias = str(tmp_path / "lead-c" / ".." / "lead-c")
    summary = mod.harvest(str(repo), alias, "TASK__demo")
    assert summary["archived"] == str(repo.resolve() / "doc/harness/archive/batch/TASK__demo")
    with _raises(mod.HarvestError, match="absolute"):
        mod.harvest(str(repo), "lead-c", "TASK__demo")
