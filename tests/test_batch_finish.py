"""Scratch-repo tests for plugin/scripts/batch_finish.py (harness:batch step d).

Every test builds a main checkout under ``tmp_path`` whose lead worktrees sit
where Claude Code puts them (``<main>/.claude/worktrees/<name>``), with the
operational ignores a harness project has, and points HOME at an empty
directory so a developer's global git config cannot change the outcome.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "plugin/scripts/batch_finish.py"
SPEC = importlib.util.spec_from_file_location("batch_finish", SCRIPT)
assert SPEC and SPEC.loader
mod = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = mod
SPEC.loader.exec_module(mod)

IGNORES = (
    "doc/harness/tasks/\ndoc/harness/learnings.jsonl\ndoc/harness/archive/\n"
    ".claude/worktrees/\n"
)
LOCK_REASON = "claude agent agent-x (pid 12345)"


def _isolate(monkeypatch, tmp_path: Path) -> None:
    """Point HOME at an empty directory and drop ambient GIT_* variables."""
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))
    for key in list(os.environ):
        if key.upper().startswith("GIT_"):
            monkeypatch.delenv(key, raising=False)


def _git(*args, cwd, env=None, check=True) -> str:
    result = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=False,
        env={**os.environ, **(env or {})},
    )
    if check:
        assert result.returncode == 0, f"git {args} failed: {result.stderr}"
    return result.stdout.strip()


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _main(tmp_path: Path, monkeypatch, name: str = "main") -> Path:
    _isolate(monkeypatch, tmp_path)
    main = Path(os.path.realpath(tmp_path)) / name
    main.mkdir()
    _git("init", "-q", "-b", "main", cwd=main)
    _git("config", "user.email", "test@example.com", cwd=main)
    _git("config", "user.name", "Test", cwd=main)
    _write(main / "README.md", "root\n")
    _write(main / "shared.txt", "base\n")
    _write(main / "doc/harness/manifest.yaml", "version: 7\n")
    _write(main / ".gitignore", IGNORES)
    _git("add", "-A", cwd=main)
    _git("commit", "-q", "-m", "init", cwd=main)
    return main


class Lead:
    def __init__(self, main: Path, name: str, *, lock: bool = True):
        self.main = main
        self.name = name
        self.branch = f"worktree-{name}"
        self.task_id = f"TASK__{name}"
        self.worktree = main / ".claude/worktrees" / name
        _git("worktree", "add", "-q", "-b", self.branch, str(self.worktree), cwd=main)
        if lock:
            _git("worktree", "lock", "--reason", LOCK_REASON, str(self.worktree), cwd=main)
        _write(self.worktree / "doc/harness/tasks" / self.task_id / "PLAN.md", f"{name} plan\n")
        _write(
            self.worktree / "doc/harness/learnings.jsonl",
            json.dumps({"key": name, "insight": f"{name} learned"}) + "\n",
        )
        self.commit = _git("rev-parse", "HEAD", cwd=self.worktree)

    def commit_files(self, files: dict, *, trailer: str | None = "own") -> str:
        for rel, text in files.items():
            _write(self.worktree / rel, text)
        _git("add", "-A", cwd=self.worktree)
        args = ["commit", "-q", "-m", f"{self.name} work"]
        if trailer is not None:
            value = self.task_id if trailer == "own" else trailer
            args += ["--trailer", f"Harness-Task: {value}"]
        _git(*args, cwd=self.worktree)
        self.commit = _git("rev-parse", "HEAD", cwd=self.worktree)
        return self.commit

    def finish(self, *, commit: str | None = None, resume: bool = False) -> dict:
        args = argparse.Namespace(
            worktree=str(self.worktree), branch=self.branch, task_id=self.task_id,
            commit=commit or self.commit, resume=resume,
        )
        return mod.finish(str(self.main), args)

    def cli(self, *extra: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [
                sys.executable, str(SCRIPT), "--repo", str(self.main),
                "--worktree", str(self.worktree), "--branch", self.branch,
                "--task-id", self.task_id, "--commit", self.commit, *extra,
            ],
            capture_output=True, text=True, check=False,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )


def _head(repo: Path) -> str:
    return _git("rev-parse", "HEAD", cwd=repo)


def _tip(main: Path, branch: str) -> str:
    return _git("rev-parse", f"refs/heads/{branch}", cwd=main)


def _lock_reason(main: Path, worktree: Path):
    return mod._worktree_lock(str(main), str(worktree))


def _assert_untouched(lead: Lead, main_head: str) -> None:
    assert _head(lead.main) == main_head
    assert _tip(lead.main, lead.branch) == lead.commit
    assert lead.worktree.is_dir()
    assert not mod._rebase_in_progress(str(lead.worktree))
    assert not (lead.main / "doc/harness/archive/batch" / lead.task_id).exists()


def _commit_on_main(main: Path, rel: str, text: str) -> str:
    _write(main / rel, text)
    _git("add", rel, cwd=main)
    _git("commit", "-q", "-m", f"main {rel}", cwd=main)
    return _head(main)


# ── Integration ──────────────────────────────────────────────────────────


def test_two_leads_integrate_in_order_on_a_linear_history(tmp_path, monkeypatch):
    main = _main(tmp_path, monkeypatch)
    first, second = Lead(main, "a"), Lead(main, "b")
    first.commit_files({"a.txt": "a\n"})
    second.commit_files({"b.txt": "b\n"})

    one = first.finish()
    assert one["status"] == "integrated", one
    # The first lead of a wave already sits on the main HEAD: no new id.
    assert one["returned_commit"] == one["integrated_tip"] == first.commit == _head(main)
    assert one["trailer_present"] is True
    assert one["cleanup"] == {
        "unlocked": True, "relocked": False, "removed": True, "branch_deleted": True,
    }
    assert not first.worktree.exists()
    assert _git("branch", "--list", first.branch, cwd=main) == ""
    assert (main / "doc/harness/archive/batch/TASK__a/PLAN.md").read_text() == "a plan\n"

    two = second.finish()
    assert two["status"] == "integrated", two
    assert two["returned_commit"] == second.commit
    # Rebased onto the first lead: a new id, whose parent is that lead's tip.
    assert two["integrated_tip"] == _head(main) != second.commit
    assert _git("rev-parse", "HEAD^", cwd=main) == first.commit
    assert _git("rev-list", "--merges", "HEAD", cwd=main) == ""
    assert (main / "a.txt").exists() and (main / "b.txt").exists()
    learnings = (main / "doc/harness/learnings.jsonl").read_text()
    assert "a learned" in learnings and "b learned" in learnings
    assert _git("status", "--porcelain", cwd=main) == ""


def test_trailer_is_reported_not_enforced(tmp_path, monkeypatch):
    main = _main(tmp_path, monkeypatch)
    bare, foreign = Lead(main, "bare"), Lead(main, "foreign")
    bare.commit_files({"bare.txt": "x\n"}, trailer=None)
    foreign.commit_files({"foreign.txt": "y\n"}, trailer="TASK__someone-else")
    for lead in (bare, foreign):
        result = lead.finish()
        assert result["status"] == "integrated", result
        assert result["trailer_present"] is False
    # Every commit in the lead range must carry it, not just one.
    mixed = Lead(main, "mixed")
    mixed.commit_files({"m1.txt": "1\n"}, trailer=None)
    mixed.commit_files({"m2.txt": "2\n"})
    assert mixed.finish()["trailer_present"] is False
    ok = Lead(main, "ok")
    ok.commit_files({"o.txt": "o\n"})
    assert ok.finish()["trailer_present"] is True
    # A lead that committed nothing has nothing to trace.
    empty = Lead(main, "empty")
    result = empty.finish()
    assert result["status"] == "integrated", result
    assert result["trailer_present"] is None


# ── Checks before the rebase: nothing changes ────────────────────────────


def test_a_lead_with_a_merge_commit_is_kept(tmp_path, monkeypatch):
    main = _main(tmp_path, monkeypatch)
    lead = Lead(main, "merger")
    lead.commit_files({"l.txt": "l\n"})
    _git("checkout", "-q", "-b", "side", cwd=lead.worktree)
    _write(lead.worktree / "side.txt", "side\n")
    _git("add", "side.txt", cwd=lead.worktree)
    _git("commit", "-q", "-m", "side", cwd=lead.worktree)
    _git("checkout", "-q", lead.branch, cwd=lead.worktree)
    _git("merge", "-q", "--no-ff", "-m", "merge side", "side", cwd=lead.worktree)
    lead.commit = _git("rev-parse", "HEAD", cwd=lead.worktree)
    main_head = _commit_on_main(main, "other.txt", "o\n")

    result = lead.finish()
    assert result["status"] == "kept", result
    assert "merge commit" in result["reason"]
    _assert_untouched(lead, main_head)
    assert _lock_reason(main, lead.worktree) == LOCK_REASON


def test_a_dirty_lead_is_kept(tmp_path, monkeypatch):
    main = _main(tmp_path, monkeypatch)
    lead = Lead(main, "dirty")
    lead.commit_files({"d.txt": "d\n"})
    main_head = _commit_on_main(main, "other.txt", "o\n")
    for dirt in ("d.txt", "untracked.txt"):
        _write(lead.worktree / dirt, "uncommitted\n")
        result = lead.finish()
        assert result["status"] == "kept", result
        assert "not clean" in result["reason"]
        _assert_untouched(lead, main_head)
        _git("checkout", "-q", "--", "d.txt", cwd=lead.worktree)
    assert (lead.worktree / "untracked.txt").exists()  # never cleaned or stashed


def test_returned_commit_must_be_the_branch_tip(tmp_path, monkeypatch):
    main = _main(tmp_path, monkeypatch)
    lead = Lead(main, "moved")
    returned = lead.commit_files({"m.txt": "1\n"})
    lead.commit_files({"m.txt": "2\n"})
    result = lead.finish(commit=returned)
    assert result["status"] == "kept", result
    assert "--resume" in result["reason"]
    missing = lead.finish(commit="0" * 40)
    assert missing["status"] == "kept" and "does not exist" in missing["reason"]
    assert lead.worktree.is_dir() and _tip(main, lead.branch) == lead.commit


def test_unregistered_or_wrong_branch_worktree_is_kept(tmp_path, monkeypatch):
    main = _main(tmp_path, monkeypatch)
    lead = Lead(main, "lost")
    lead.commit_files({"x.txt": "x\n"})
    plain = tmp_path / "plain"
    plain.mkdir()
    args = argparse.Namespace(
        worktree=str(plain), branch=lead.branch, task_id=lead.task_id,
        commit=lead.commit, resume=False,
    )
    result = mod.finish(str(main), args)
    assert result["status"] == "kept" and "registered" in result["reason"]
    args.worktree, args.branch = str(lead.worktree), "some-other-branch"
    result = mod.finish(str(main), args)
    assert result["status"] == "kept" and "checked out" in result["reason"]


def test_dirty_main_checkout_is_ff_refused_before_any_change(tmp_path, monkeypatch):
    main = _main(tmp_path, monkeypatch)
    lead = Lead(main, "waiting")
    lead.commit_files({"w.txt": "w\n"})
    main_head = _commit_on_main(main, "other.txt", "o\n")
    _write(main / "stray.txt", "stray\n")
    result = lead.finish()
    assert result["status"] == "ff-refused", result
    assert "main checkout is not clean" in result["reason"]
    _assert_untouched(lead, main_head)


def test_detached_main_head_is_ff_refused_before_any_change(tmp_path, monkeypatch):
    # A fast-forward would move only the detached HEAD, and `branch -d` would
    # then delete the one branch holding the lead's work.
    main = _main(tmp_path, monkeypatch)
    lead = Lead(main, "orphaned")
    lead.commit_files({"o.txt": "o\n"})
    main_head = _commit_on_main(main, "other.txt", "o\n")
    _git("checkout", "-q", "--detach", cwd=main)
    result = lead.finish()
    assert result["status"] == "ff-refused", result
    assert "detached HEAD" in result["reason"]
    _assert_untouched(lead, main_head)
    assert _git("branch", "--list", lead.branch, cwd=main) != ""


# ── Rebase failures ──────────────────────────────────────────────────────


def test_conflict_is_aborted_back_to_the_exact_tip(tmp_path, monkeypatch):
    for backend in ("merge", "apply"):  # rebase-merge / rebase-apply
        main = _main(tmp_path, monkeypatch, name=f"main-{backend}")
        _git("config", "rebase.backend", backend, cwd=main)
        lead = Lead(main, "clash")
        lead.commit_files({"shared.txt": "lead\n"})
        main_head = _commit_on_main(main, "shared.txt", "main\n")

        result = lead.finish()
        assert result["status"] == "conflict", (backend, result)
        assert result["conflicted_paths"] == ["shared.txt"]
        assert result["integrated_tip"] is None
        _assert_untouched(lead, main_head)
        assert _git("symbolic-ref", "HEAD", cwd=lead.worktree) == f"refs/heads/{lead.branch}"
        assert _git("status", "--porcelain", cwd=lead.worktree) == ""
        assert _lock_reason(main, lead.worktree) == LOCK_REASON


def test_a_failed_abort_is_reported(tmp_path, monkeypatch):
    main = _main(tmp_path, monkeypatch)
    lead = Lead(main, "stuck")
    lead.commit_files({"shared.txt": "lead\n"})
    _commit_on_main(main, "shared.txt", "main\n")
    real_git = mod._git

    def abort_fails(cwd, *args):
        if args[-2:] == ("rebase", "--abort"):
            return subprocess.CompletedProcess(args, 1, "", "error: simulated abort failure")
        return real_git(cwd, *args)

    monkeypatch.setattr(mod, "_git", abort_fails)
    result = lead.finish()
    assert result["status"] == "conflict", result
    assert "mid-rebase" in result["reason"] and "simulated abort failure" in result["reason"]
    assert "was aborted" not in result["reason"]
    monkeypatch.setattr(mod, "_git", real_git)
    assert mod._rebase_in_progress(str(lead.worktree))


def test_a_failure_while_diagnosing_a_failed_rebase_still_aborts_it(tmp_path, monkeypatch):
    main = _main(tmp_path, monkeypatch)
    lead = Lead(main, "diagnosed")
    lead.commit_files({"shared.txt": "lead\n"})
    main_head = _commit_on_main(main, "shared.txt", "main\n")
    real_git = mod._git

    def diff_cannot_run(cwd, *args):
        if args[:1] == ("diff",):
            raise mod.FinishError("simulated: git diff could not run")
        return real_git(cwd, *args)

    monkeypatch.setattr(mod, "_git", diff_cannot_run)
    result = lead.finish()
    assert result["status"] == "error", result
    monkeypatch.setattr(mod, "_git", real_git)
    _assert_untouched(lead, main_head)  # aborted back to the lead's tip


def test_rebase_failure_without_conflicts_is_kept(tmp_path, monkeypatch):
    main = _main(tmp_path, monkeypatch)
    lead = Lead(main, "hooked")
    lead.commit_files({"h.txt": "h\n"})
    main_head = _commit_on_main(main, "other.txt", "o\n")
    hook = main / ".git/hooks/pre-rebase"
    _write(hook, "#!/bin/sh\necho refusing rebase >&2\nexit 1\n")
    hook.chmod(0o755)

    result = lead.finish()
    assert result["status"] == "kept", result
    assert result["conflicted_paths"] == []
    assert "rebase" in result["reason"]
    _assert_untouched(lead, main_head)


def test_a_rebase_already_in_progress_is_never_aborted(tmp_path, monkeypatch):
    main = _main(tmp_path, monkeypatch)
    lead = Lead(main, "midway")
    lead.commit_files({"shared.txt": "lead\n"})
    main_head = _commit_on_main(main, "shared.txt", "main\n")
    _git("rebase", "--no-autostash", main_head, cwd=lead.worktree, check=False)
    assert mod._rebase_in_progress(str(lead.worktree))

    for resume in (False, True):
        result = lead.finish(resume=resume)
        assert result["status"] == "kept", result
        assert "already in progress" in result["reason"]
        assert mod._rebase_in_progress(str(lead.worktree))
    assert _head(main) == main_head


def test_ff_only_refusal_keeps_the_rebased_lead(tmp_path, monkeypatch):
    main = _main(tmp_path, monkeypatch)
    lead = Lead(main, "late")
    lead.commit_files({"l.txt": "l\n"})
    _commit_on_main(main, "other.txt", "o\n")
    real_git = mod._git

    def main_moves_before_the_fast_forward(cwd, *args):
        if args[:2] == ("merge", "--ff-only"):
            _commit_on_main(main, "racing.txt", "r\n")
        return real_git(cwd, *args)

    monkeypatch.setattr(mod, "_git", main_moves_before_the_fast_forward)
    result = lead.finish()
    assert result["status"] == "ff-refused", result
    assert result["integrated_tip"] is None
    assert result["branch_tip"] == _tip(main, lead.branch) != lead.commit
    assert lead.worktree.is_dir()
    assert not (main / "l.txt").exists()
    assert _lock_reason(main, lead.worktree) == LOCK_REASON

    # The branch was rebased, so only --resume accepts it; it then lands.
    monkeypatch.setattr(mod, "_git", real_git)
    assert lead.finish()["status"] == "kept"
    resumed = lead.finish(resume=True)
    assert resumed["status"] == "integrated", resumed
    assert (main / "l.txt").exists() and (main / "racing.txt").exists()


# ── After the fast-forward ───────────────────────────────────────────────


def test_harvest_refusal_keeps_the_worktree_with_the_integrated_tip(tmp_path, monkeypatch):
    main = _main(tmp_path, monkeypatch)
    lead = Lead(main, "reused")
    lead.commit_files({"r.txt": "r\n"})
    _write(main / "doc/harness/archive/batch/TASK__reused/PLAN.md", "an older batch\n")

    result = lead.finish()
    assert result["status"] == "kept", result
    assert "harvest refused" in result["reason"]
    assert result["integrated_tip"] == _head(main) == lead.commit
    assert lead.worktree.is_dir()
    assert _tip(main, lead.branch) == lead.commit
    assert _lock_reason(main, lead.worktree) == LOCK_REASON  # never unlocked

    # Once the cause is fixed, a rerun finishes the already integrated lead.
    (main / "doc/harness/archive/batch/TASK__reused/PLAN.md").unlink()
    (main / "doc/harness/archive/batch/TASK__reused").rmdir()
    rerun = lead.finish(resume=True)
    assert rerun["status"] == "integrated", rerun
    assert rerun["integrated_tip"] == lead.commit
    assert not lead.worktree.exists()


def test_any_harvest_failure_is_local_to_the_lead(tmp_path, monkeypatch):
    # batch_harvest decodes learnings outside its own error handling.
    main = _main(tmp_path, monkeypatch)
    lead = Lead(main, "binary")
    lead.commit_files({"b.txt": "b\n"})
    (lead.worktree / "doc/harness/learnings.jsonl").write_bytes(b"\xff\xfe not utf-8\n")
    result = lead.finish()
    assert result["status"] == "kept", result
    assert "UnicodeDecodeError" in result["reason"]
    assert result["integrated_tip"] == _head(main) == lead.commit
    assert lead.worktree.is_dir()


def test_a_failure_after_the_fast_forward_keeps_the_integrated_tip(tmp_path, monkeypatch):
    main = _main(tmp_path, monkeypatch)
    lead = Lead(main, "crash")
    lead.commit_files({"c.txt": "c\n"})

    def boom(*_args, **_kwargs):
        raise ValueError("cleanup exploded")

    monkeypatch.setattr(mod, "_cleanup", boom)
    result = lead.finish()
    assert result["status"] == "error", result
    assert result["integrated_tip"] == _head(main) == lead.commit


def test_unlock_only_when_locked(tmp_path, monkeypatch):
    main = _main(tmp_path, monkeypatch)
    unlocked, locked = Lead(main, "free", lock=False), Lead(main, "held")
    unlocked.commit_files({"f.txt": "f\n"})
    locked.commit_files({"h.txt": "h\n"})
    free = unlocked.finish()
    assert free["status"] == "integrated", free
    assert free["cleanup"]["unlocked"] is False
    held = locked.finish()
    assert held["status"] == "integrated", held
    assert held["cleanup"]["unlocked"] is True


def test_removal_refusal_relocks_with_the_original_reason(tmp_path, monkeypatch):
    main = _main(tmp_path, monkeypatch)
    lead = Lead(main, "sticky")
    lead.commit_files({"s.txt": "s\n"})
    real_harvest = mod.batch_harvest.harvest

    def harvest_then_leave_a_file(repo, worktree, task_id):
        summary = real_harvest(repo, worktree, task_id)
        _write(Path(worktree) / "late-untracked.txt", "x\n")
        return summary

    monkeypatch.setattr(mod.batch_harvest, "harvest", harvest_then_leave_a_file)
    result = lead.finish()
    assert result["status"] == "kept", result
    assert "git worktree remove" in result["reason"]
    assert result["integrated_tip"] == _head(main)
    assert result["cleanup"] == {
        "unlocked": True, "relocked": True, "removed": False, "branch_deleted": False,
    }
    assert lead.worktree.is_dir()
    assert _lock_reason(main, lead.worktree) == LOCK_REASON


def test_a_failed_relock_says_the_worktree_is_unlocked(tmp_path, monkeypatch):
    main = _main(tmp_path, monkeypatch)
    lead = Lead(main, "bare")
    lead.commit_files({"s.txt": "s\n"})
    real_git, real_harvest = mod._git, mod.batch_harvest.harvest

    def harvest_then_leave_a_file(repo, worktree, task_id):
        summary = real_harvest(repo, worktree, task_id)
        _write(Path(worktree) / "late-untracked.txt", "x\n")
        return summary

    def lock_fails(cwd, *args):
        if args[:2] == ("worktree", "lock"):
            return subprocess.CompletedProcess(args, 128, "", "fatal: simulated")
        return real_git(cwd, *args)

    monkeypatch.setattr(mod.batch_harvest, "harvest", harvest_then_leave_a_file)
    monkeypatch.setattr(mod, "_git", lock_fails)
    result = lead.finish()
    assert result["status"] == "kept", result
    assert result["cleanup"]["relocked"] is False
    assert "now unlocked" in result["reason"]


def test_a_branch_deletion_refusal_is_kept_after_removal(tmp_path, monkeypatch):
    main = _main(tmp_path, monkeypatch)
    lead = Lead(main, "branchy")
    lead.commit_files({"b.txt": "b\n"})
    real_git = mod._git

    def branch_delete_fails(cwd, *args):
        if args[:2] == ("branch", "-d"):
            return subprocess.CompletedProcess(args, 1, "", "error: simulated")
        return real_git(cwd, *args)

    monkeypatch.setattr(mod, "_git", branch_delete_fails)
    result = lead.finish()
    assert result["status"] == "kept", result
    # The worktree is gone, so a rerun cannot finish it: the reason says so.
    assert f"run `git branch -d {lead.branch}`" in result["reason"]
    assert result["cleanup"]["removed"] is True and result["cleanup"]["branch_deleted"] is False
    assert result["integrated_tip"] == _head(main)
    assert not lead.worktree.exists()


# ── Resume (integration-task step e.1) ───────────────────────────────────


def test_resume_after_manual_conflict_resolution(tmp_path, monkeypatch):
    main = _main(tmp_path, monkeypatch)
    lead = Lead(main, "resolved")
    lead.commit_files({"shared.txt": "lead\n", "extra.txt": "e\n"})
    main_head = _commit_on_main(main, "shared.txt", "main\n")
    assert lead.finish()["status"] == "conflict"

    # The coordinator reruns the rebase, resolves, and continues.
    _git("rebase", "--no-autostash", main_head, cwd=lead.worktree, check=False)
    _write(lead.worktree / "shared.txt", "main\nlead\n")
    _git("add", "shared.txt", cwd=lead.worktree)
    _git("rebase", "--continue", cwd=lead.worktree, env={"GIT_EDITOR": "true"})
    rebased = _git("rev-parse", "HEAD", cwd=lead.worktree)
    assert rebased != lead.commit

    plain = lead.finish()
    assert plain["status"] == "kept" and "--resume" in plain["reason"]
    result = lead.finish(resume=True)
    assert result["status"] == "integrated", result
    assert result["returned_commit"] == lead.commit
    assert result["integrated_tip"] == rebased == _head(main)
    assert result["trailer_present"] is True
    assert (main / "shared.txt").read_text() == "main\nlead\n"
    assert not lead.worktree.exists()


# ── CLI ──────────────────────────────────────────────────────────────────


def test_cli_prints_one_json_result_with_distinct_exit_codes(tmp_path, monkeypatch):
    main = _main(tmp_path, monkeypatch)
    clash = Lead(main, "clash")
    clash.commit_files({"shared.txt": "lead\n"})
    good = Lead(main, "good")
    good.commit_files({"g.txt": "g\n"})
    _commit_on_main(main, "shared.txt", "main\n")

    integrated = good.cli()
    assert integrated.returncode == 0, integrated.stderr
    body = json.loads(integrated.stdout)
    assert body["status"] == "integrated"
    assert set(body) == set(mod._result(argparse.Namespace(
        task_id="", branch="", commit="", resume=False), ""))

    conflict = clash.cli()
    assert conflict.returncode == 4
    assert json.loads(conflict.stdout)["conflicted_paths"] == ["shared.txt"]

    _write(clash.worktree / "wip.txt", "wip\n")
    kept = clash.cli()
    assert kept.returncode == 3 and json.loads(kept.stdout)["status"] == "kept"
    (clash.worktree / "wip.txt").unlink()

    _write(main / "stray.txt", "x\n")
    refused = clash.cli()
    assert refused.returncode == 5 and json.loads(refused.stdout)["status"] == "ff-refused"


def test_cli_usage_errors_exit_2_without_json(tmp_path, monkeypatch):
    main = _main(tmp_path, monkeypatch)
    lead = Lead(main, "usage")
    lead.commit_files({"u.txt": "u\n"})
    valid = {
        "--repo": str(main), "--worktree": str(lead.worktree), "--branch": lead.branch,
        "--task-id": lead.task_id, "--commit": lead.commit,
    }
    for flag, value in (
        ("--commit", "HEAD"),
        ("--commit", "--all"),
        ("--branch", "-D"),
        ("--task-id", "not-a-task"),
        ("--worktree", "relative/path"),
    ):
        argv = [item for key, val in {**valid, flag: value}.items() for item in (key, val)]
        result = subprocess.run(
            [sys.executable, str(SCRIPT), *argv], capture_output=True, text=True, check=False,
        )
        assert result.returncode == 2, (flag, value, result.stdout)
        assert result.stdout == ""
    assert lead.worktree.is_dir() and _tip(main, lead.branch) == lead.commit


def test_unexpected_failure_reports_error_and_exit_1(tmp_path, monkeypatch, capsys):
    main = _main(tmp_path, monkeypatch)
    lead = Lead(main, "boom")
    lead.commit_files({"b.txt": "b\n"})

    def boom(*_args, **_kwargs):
        raise ValueError("unexpected")

    monkeypatch.setattr(mod, "_check", boom)
    code = mod.main([
        "--repo", str(main), "--worktree", str(lead.worktree), "--branch", lead.branch,
        "--task-id", lead.task_id, "--commit", lead.commit,
    ])
    assert code == 1
    body = json.loads(capsys.readouterr().out)
    assert body["status"] == "error"
    assert "ValueError: unexpected" in body["reason"]


def test_an_identity_from_the_environment_reaches_the_rebase(tmp_path, monkeypatch):
    # Every GIT_* variable is dropped except the four identity ones: a
    # container or CI identity often comes only from the environment.
    main = _main(tmp_path, monkeypatch)
    _git("config", "--unset", "user.name", cwd=main)
    _git("config", "--unset", "user.email", cwd=main)
    _git("config", "user.useConfigOnly", "true", cwd=main)
    for key, value in (
        ("GIT_AUTHOR_NAME", "Env Author"), ("GIT_AUTHOR_EMAIL", "author@example.com"),
        ("GIT_COMMITTER_NAME", "Env Committer"), ("GIT_COMMITTER_EMAIL", "committer@example.com"),
    ):
        monkeypatch.setenv(key, value)
    first, second = Lead(main, "one"), Lead(main, "two")
    first.commit_files({"1.txt": "1\n"})
    second.commit_files({"2.txt": "2\n"})
    assert first.finish()["status"] == "integrated"
    result = second.finish()  # rebased: writes a new commit
    assert result["status"] == "integrated", result
    assert _git("log", "-1", "--format=%cn", cwd=main) == "Env Committer"


def test_ambient_git_environment_cannot_redirect_it(tmp_path, monkeypatch):
    main = _main(tmp_path, monkeypatch)
    lead = Lead(main, "env")
    lead.commit_files({"e.txt": "e\n"})
    decoy = tmp_path / "decoy"
    decoy.mkdir()
    _git("init", "-q", cwd=decoy)
    monkeypatch.setenv("GIT_DIR", str(decoy / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(decoy))
    result = lead.finish()
    assert result["status"] == "integrated", result


@pytest.mark.parametrize("location", ["lead", "main"])
def test_hidden_untracked_files_refuse_before_integration(tmp_path, monkeypatch, location):
    main = _main(tmp_path, monkeypatch)
    lead = Lead(main, "hidden")
    lead.commit_files({"change.txt": "committed\n"})
    original = _head(main)
    _git("config", "status.showUntrackedFiles", "no", cwd=main)
    target = (lead.worktree if location == "lead" else main) / "untracked.txt"
    _write(target, "irreplaceable\n")
    assert _git("status", "--porcelain", cwd=target.parent) == ""

    result = lead.finish()

    assert result["status"] == ("kept" if location == "lead" else "ff-refused"), result
    _assert_untouched(lead, original)
    assert target.read_text() == "irreplaceable\n"
    assert _lock_reason(main, lead.worktree) == LOCK_REASON


def test_hidden_untracked_file_created_after_harvest_survives_removal(tmp_path, monkeypatch):
    main = _main(tmp_path, monkeypatch)
    lead = Lead(main, "late-hidden")
    lead.commit_files({"change.txt": "committed\n"})
    _git("config", "status.showUntrackedFiles", "no", cwd=main)
    real_harvest = mod.batch_harvest.harvest
    target = lead.worktree / "late-untracked.txt"

    def harvest_then_write(*args):
        result = real_harvest(*args)
        _write(target, "irreplaceable\n")
        return result

    monkeypatch.setattr(mod.batch_harvest, "harvest", harvest_then_write)
    result = lead.finish()
    assert result["status"] == "kept", result
    assert result["integrated_tip"] == _head(main) == lead.commit
    assert target.read_text() == "irreplaceable\n"
    assert not result["cleanup"]["removed"]
    assert _lock_reason(main, lead.worktree) == LOCK_REASON
    assert _tip(main, lead.branch) == lead.commit


def test_real_post_merge_hook_timeout_reports_integrated_tip_without_cleanup(tmp_path, monkeypatch):
    main = _main(tmp_path, monkeypatch)
    lead = Lead(main, "hook-timeout")
    lead.commit_files({"change.txt": "committed\n"})
    hook = main / ".git/hooks/post-merge"
    _write(hook, "#!/bin/sh\nexec sleep 0.5\n")
    hook.chmod(0o755)
    real_run = subprocess.run

    def shorten_merge_timeout(command, *args, **kwargs):
        if "merge" in command and "--ff-only" in command:
            kwargs["timeout"] = 0.2
        return real_run(command, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", shorten_merge_timeout)
    result = lead.finish()
    assert _head(main) == lead.commit  # real Git advanced HEAD before the timeout
    assert result["status"] != "integrated", result
    assert result["integrated_tip"] == lead.commit, result
    assert "tim" in result["reason"].lower()
    assert not (main / "doc/harness/archive/batch" / lead.task_id).exists()
    assert not any(result["cleanup"].values())
    assert _lock_reason(main, lead.worktree) == LOCK_REASON


def test_failed_merge_reconciliation_reports_unknown_and_preserves_evidence(tmp_path, monkeypatch):
    main = _main(tmp_path, monkeypatch)
    lead = Lead(main, "unknown")
    lead.commit_files({"change.txt": "committed\n"})
    real_run = subprocess.run
    interrupted = False

    def lose_git_after_merge(command, *args, **kwargs):
        nonlocal interrupted
        if "merge" in command and "--ff-only" in command:
            completed = real_run(command, *args, **kwargs)
            assert completed.returncode == 0
            interrupted = True
            raise subprocess.TimeoutExpired(command, 1)
        if interrupted:
            raise OSError("reconciliation unavailable")
        return real_run(command, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", lose_git_after_merge)
    result = lead.finish()
    monkeypatch.setattr(subprocess, "run", real_run)
    assert _head(main) == lead.commit
    assert result["integrated_tip"] is None
    assert "unknown" in result["reason"].lower(), result
    assert "reconciliation unavailable" in result["reason"]
    assert not any(result["cleanup"].values())
    assert not (main / "doc/harness/archive/batch" / lead.task_id).exists()
    assert _lock_reason(main, lead.worktree) == LOCK_REASON


@pytest.mark.parametrize("failure", ["timeout", "oserror"])
@pytest.mark.parametrize("relock_fails", [False, True])
def test_exceptional_removal_restores_lock_and_preserves_failure(
    tmp_path, monkeypatch, failure, relock_fails,
):
    main = _main(tmp_path, monkeypatch)
    lead = Lead(main, "remove-error")
    lead.commit_files({"change.txt": "committed\n"})
    real_run = subprocess.run

    def remove_raises(command, *args, **kwargs):
        if "worktree" in command and "remove" in command:
            if failure == "timeout":
                raise subprocess.TimeoutExpired(command, 1)
            raise OSError("removal unavailable")
        if relock_fails and "worktree" in command and "lock" in command:
            raise OSError("relock unavailable")
        return real_run(command, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", remove_raises)
    result = lead.finish()
    assert result["status"] != "integrated", result
    assert result["integrated_tip"] == _head(main) == lead.commit
    assert ("tim" in result["reason"].lower() if failure == "timeout"
            else "removal unavailable" in result["reason"]), result
    assert result["cleanup"]["unlocked"]
    assert result["cleanup"]["relocked"] is not relock_fails
    assert not result["cleanup"]["removed"]
    assert not result["cleanup"]["branch_deleted"]
    assert lead.worktree.is_dir()
    assert _tip(main, lead.branch) == lead.commit
    if relock_fails:
        assert "relock unavailable" in result["reason"]
        assert "could not" in result["reason"] and "lock" in result["reason"]
        assert _lock_reason(main, lead.worktree) is None
    else:
        assert _lock_reason(main, lead.worktree) == LOCK_REASON


def test_removal_completed_before_exception_is_reported_without_deleting_branch(tmp_path, monkeypatch):
    main = _main(tmp_path, monkeypatch)
    lead = Lead(main, "removed-error")
    lead.commit_files({"change.txt": "committed\n"})
    real_run = subprocess.run

    def remove_then_timeout(command, *args, **kwargs):
        completed = real_run(command, *args, **kwargs)
        if "worktree" in command and "remove" in command:
            assert completed.returncode == 0
            raise subprocess.TimeoutExpired(command, 1)
        return completed

    monkeypatch.setattr(subprocess, "run", remove_then_timeout)
    result = lead.finish()
    assert result["status"] != "integrated", result
    assert result["integrated_tip"] == _head(main) == lead.commit
    assert not lead.worktree.exists()
    assert result["cleanup"]["removed"]
    assert not result["cleanup"]["relocked"]
    assert not result["cleanup"]["branch_deleted"]
    assert _tip(main, lead.branch) == lead.commit
