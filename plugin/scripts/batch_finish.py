#!/usr/bin/env python3
"""Integrate one closed `harness:batch` lead: batch SKILL step d.

Run from the main checkout once per lead that returned `verdict: "closed"`,
in order. It rebases the lead branch onto the main checkout's HEAD inside the
lead's worktree, fast-forwards the main checkout, harvests the lead's
gitignored task evidence (`batch_harvest.py`), and removes the worktree and
branch. See `doc/harness/REQ__parallel-tasks-via-worktree-leads.md`.

Usage:
  python3 plugin/scripts/batch_finish.py --repo <main checkout> \
      --worktree <abs lead worktree> --branch <lead branch> \
      --task-id <TASK__x> --commit <sha the lead returned> [--resume]

Before it changes anything it checks, and on a failed check leaves every
repository as it found it: the worktree is a registered linked worktree of
`--repo` with no rebase in progress and `<branch>` checked out; `--commit` is
the branch tip (with `--resume`: it still resolves); the branch holds no merge
commit after the main HEAD (a rebase would drop that merge's own change); the
lead worktree is clean; the main checkout is clean and on a branch.

`--resume` is for integration-task step e.1: the coordinator reran the rebase,
resolved each stopped commit, and finished it with
`GIT_EDITOR=true git -C <W> rebase --continue`, so the branch tip is no longer
the commit the lead returned. It also finishes a lead after an `ff-refused`
or a `kept` whose cause was fixed, as long as the worktree still exists (after
a `git branch -d` refusal it is already removed: delete the branch by hand).

Prints one JSON object and exits with its status:
  integrated  0  fast-forwarded, harvested, worktree and branch removed.
  kept        3  this lead stays (a failed check, a rebase failure without
                 conflicted paths, or a harvest or removal refusal). Go on to
                 the next closed lead.
  conflict    4  the rebase stopped on `conflicted_paths` and was aborted.
                 Stop integrating; resolve it in the integration task.
  ff-refused  5  the main checkout is not clean, not on a branch, or
                 `git merge --ff-only` refused. Stop integrating.
  error       1  unexpected failure. Stop integrating and report it.
Whatever the status, a non-null `integrated_tip` means the lead's commits are
on the main branch. Usage errors exit 2 without a JSON object.

Never passes `--force`, never stashes, never creates a merge commit. It
releases Claude Code's agent lock on the worktree, so never run it for a lead
that is still running. Git runs the repositories' own hooks as usual. Stdlib
only.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _lib import (  # type: ignore  # noqa: E402
    GitBindingError,
    _trusted_git_env,
    find_repo_root,
    resolve_registered_worktree,
)
import batch_harvest  # type: ignore  # noqa: E402

TASK_ID_RE = batch_harvest.TASK_ID_RE
COMMIT_RE = re.compile(r"[0-9a-fA-F]{7,64}")
BRANCH_RE = re.compile(r"[^\s~^:?*\[\\]+")
TRAILER_KEY = "Harness-Task"
GIT_TIMEOUT_SECONDS = 600
# The rebase writes commits; an identity that comes only from the
# environment must survive the trusted (GIT_*-free) environment.
IDENTITY_ENV = (
    "GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL",
)
EXIT_CODES = {"integrated": 0, "error": 1, "kept": 3, "conflict": 4, "ff-refused": 5}


class FinishError(RuntimeError):
    """A git call could not run or failed where failure was not expected."""


class Outcome(Exception):
    """Stop with ``status`` and ``reason``; the result dict carries the rest."""

    def __init__(self, status: str, reason: str):
        super().__init__(reason)
        self.status = status
        self.reason = reason


def _git(cwd: str, *args: str) -> subprocess.CompletedProcess:
    env = _trusted_git_env()
    env.update({key: os.environ[key] for key in IDENTITY_ENV if key in os.environ})
    env["LC_ALL"] = "C"
    command = ["git", "-c", "core.fsmonitor=false", *args]
    try:
        return subprocess.run(
            command, cwd=cwd, capture_output=True, text=True, encoding="utf-8",
            errors="replace", check=False, env=env, stdin=subprocess.DEVNULL,
            timeout=GIT_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise FinishError(
            f"git {' '.join(args)} timed out after {GIT_TIMEOUT_SECONDS}s in {cwd}; "
            "that checkout may be mid-update"
        ) from exc
    except OSError as exc:
        raise FinishError(f"git {' '.join(args)} could not run in {cwd}: {exc}") from exc


def _detail(result: subprocess.CompletedProcess) -> str:
    return (result.stderr or result.stdout).strip() or f"exit {result.returncode}"


def _git_out(cwd: str, *args: str) -> str:
    result = _git(cwd, *args)
    if result.returncode != 0:
        raise FinishError(f"git {' '.join(args)} failed in {cwd}: {_detail(result)}")
    return result.stdout


def _resolve_commit(repo: str, rev: str) -> str:
    result = _git(repo, "rev-parse", "--verify", "--quiet", f"{rev}^{{commit}}")
    return result.stdout.strip() if result.returncode == 0 else ""


def _rebase_in_progress(worktree: str) -> bool:
    for name in ("rebase-merge", "rebase-apply"):
        path = _git_out(worktree, "rev-parse", "--git-path", name).strip()
        if os.path.exists(path if os.path.isabs(path) else os.path.join(worktree, path)):
            return True
    return False


def _status_lines(checkout: str) -> list:
    listing = _git_out(
        checkout, "--no-optional-locks", "status", "--porcelain", "--ignore-submodules=none",
    )
    return [line for line in listing.splitlines() if line]


def _trailer_present(repo: str, base: str, tip: str, task_id: str):
    """Whether every commit in ``base..tip`` carries ``Harness-Task: <task_id>``.

    None when the range holds no commit, so there is nothing to trace.
    """
    listing = _git_out(
        repo, "log", f"--format=%(trailers:key={TRAILER_KEY},valueonly,separator=%x1f)%x1e",
        f"{base}..{tip}",
    )
    records = [record.strip("\n") for record in listing.split("\x1e")][:-1]
    if not records:
        return None
    return all(
        task_id in [value.strip() for value in record.split("\x1f")] for record in records
    )


def _worktree_lock(repo: str, worktree: str):
    """The lock reason of ``worktree`` ("" when locked without one), or None."""
    listing = _git_out(repo, "worktree", "list", "--porcelain", "-z")
    current = None
    for field in listing.split("\0"):
        if field.startswith("worktree "):
            current = os.path.realpath(field[len("worktree "):])
        elif current == worktree and (field == "locked" or field.startswith("locked ")):
            return field[len("locked "):] if field != "locked" else ""
    return None


def _result(args, worktree: str) -> dict:
    return {
        "status": "error",
        "reason": "",
        "task_id": args.task_id,
        "branch": args.branch,
        "worktree": worktree,
        "returned_commit": args.commit,
        "branch_tip": None,
        "integrated_tip": None,
        "conflicted_paths": [],
        "trailer_present": None,
        "harvest": None,
        "cleanup": {"unlocked": False, "relocked": False, "removed": False, "branch_deleted": False},
    }


def _check(repo: str, worktree: str, args, result: dict) -> str:
    """Run every pre-rebase check; return the main HEAD they were made against."""
    try:
        resolved = resolve_registered_worktree(repo, worktree)
    except GitBindingError as exc:
        raise Outcome("kept", f"{worktree} is not a registered linked worktree of {repo}: {exc}")
    if not resolved:
        raise Outcome("kept", "--worktree names the main checkout, not a lead worktree")
    if _rebase_in_progress(worktree):
        raise Outcome(
            "kept",
            "a rebase is already in progress in the lead worktree and was left alone; "
            f"finish it with `GIT_EDITOR=true git -C {worktree} rebase --continue` and "
            "rerun with --resume",
        )
    ref = f"refs/heads/{args.branch}"
    head_ref = _git(worktree, "symbolic-ref", "-q", "HEAD").stdout.strip()
    if head_ref != ref:
        raise Outcome(
            "kept", f"the lead worktree has {head_ref or 'a detached HEAD'} checked out, not {ref}",
        )
    tip = _resolve_commit(repo, ref)
    result["branch_tip"] = tip
    returned = _resolve_commit(repo, args.commit)
    if not returned:
        raise Outcome("kept", f"the returned commit {args.commit} does not exist")
    result["returned_commit"] = returned
    if not args.resume and returned != tip:
        raise Outcome(
            "kept",
            f"the returned commit {returned} is not the tip of {args.branch} ({tip}); "
            "rerun with --resume once that tip is the lead's resolved work",
        )
    main_head = _git_out(repo, "rev-parse", "--verify", "HEAD").strip()
    result["trailer_present"] = _trailer_present(repo, main_head, ref, args.task_id)
    merges = _git_out(repo, "rev-list", "--merges", f"{main_head}..{ref}").split()
    if merges:
        raise Outcome(
            "kept",
            f"{args.branch} holds merge commit(s) {', '.join(merges)}; a rebase would drop "
            "what a merge commit itself changed",
        )
    dirty = _status_lines(worktree)
    if dirty:
        raise Outcome("kept", f"the lead worktree is not clean ({len(dirty)} status entries)")
    if _git(repo, "symbolic-ref", "-q", "HEAD").returncode != 0:
        # A fast-forward would move only the detached HEAD, and `branch -d`
        # would then delete the one branch that holds the lead's work.
        raise Outcome("ff-refused", "the main checkout is on a detached HEAD; nothing was changed")
    dirty = _status_lines(repo)
    if dirty:
        raise Outcome(
            "ff-refused",
            f"the main checkout is not clean ({len(dirty)} status entries); nothing was changed",
        )
    return main_head


def _abort_note(worktree: str) -> str:
    """Abort a rebase in progress; "" on success or when none is in progress."""
    if not _rebase_in_progress(worktree):
        return ""
    aborted = _git(worktree, "rebase", "--abort")
    if aborted.returncode == 0:
        return ""
    return f"; `git rebase --abort` failed, the worktree is mid-rebase: {_detail(aborted)}"


def _rebase(repo: str, worktree: str, main_head: str, result: dict) -> None:
    try:
        rebased = _git(
            worktree, "-c", "rebase.updateRefs=false", "rebase", "--no-autostash", main_head,
        )
        if rebased.returncode == 0:
            return
        conflicted = _git(worktree, "diff", "--name-only", "--diff-filter=U")
        result["conflicted_paths"] = [p for p in conflicted.stdout.splitlines() if p]
    except BaseException:
        try:  # it may have started; never leave it stopped midway
            _abort_note(worktree)
        except Exception:
            pass
        raise
    note = _abort_note(worktree) or " and was aborted"
    result["branch_tip"] = _resolve_commit(repo, f"refs/heads/{result['branch']}")
    if result["conflicted_paths"]:
        raise Outcome("conflict", f"the rebase onto {main_head} stopped on conflicts{note}")
    raise Outcome("kept", f"the rebase onto {main_head} failed: {_detail(rebased)}{note}")


def _cleanup(repo: str, worktree: str, branch: str, result: dict) -> None:
    cleanup = result["cleanup"]
    lock = _worktree_lock(repo, worktree)
    if lock is not None:
        unlocked = _git(repo, "worktree", "unlock", worktree)
        if unlocked.returncode != 0:
            raise Outcome("kept", f"`git worktree unlock` failed: {_detail(unlocked)}")
        cleanup["unlocked"] = True
    removed = _git(repo, "worktree", "remove", worktree)
    if removed.returncode != 0:
        reason = f"`git worktree remove` refused, worktree kept: {_detail(removed)}"
        if cleanup["unlocked"]:
            relock = ["worktree", "lock"] + (["--reason", lock] if lock else []) + [worktree]
            cleanup["relocked"] = _git(repo, *relock).returncode == 0
            if not cleanup["relocked"]:
                reason += "; it could not be locked again and is now unlocked"
        raise Outcome("kept", reason)
    cleanup["removed"] = True
    deleted = _git(repo, "branch", "-d", branch)
    if deleted.returncode != 0:
        raise Outcome(
            "kept",
            "`git branch -d` refused, branch kept; the worktree is already removed, so once "
            f"the cause is fixed run `git branch -d {branch}` (a rerun cannot): "
            f"{_detail(deleted)}",
        )
    cleanup["branch_deleted"] = True


def finish(repo_root: str, args) -> dict:
    """Run step d for one lead; never raises, the result carries the status."""
    repo = os.path.realpath(repo_root)
    worktree = os.path.realpath(args.worktree)
    result = _result(args, worktree)
    ref = f"refs/heads/{args.branch}"
    try:
        main_head = _check(repo, worktree, args, result)
        _rebase(repo, worktree, main_head, result)
        result["branch_tip"] = _resolve_commit(repo, ref)
        merged = _git(repo, "merge", "--ff-only", ref)
        if merged.returncode != 0:
            raise Outcome("ff-refused", f"`git merge --ff-only {ref}` refused: {_detail(merged)}")
        head = _git_out(repo, "rev-parse", "--verify", "HEAD").strip()
        result["integrated_tip"] = head
        if head != result["branch_tip"]:
            raise FinishError(f"main HEAD {head} is not the branch tip after the fast-forward")
        try:
            result["harvest"] = batch_harvest.harvest(repo, worktree, args.task_id)
        except Exception as exc:  # any harvest failure is local to this lead
            raise Outcome("kept", f"harvest refused, worktree kept: {type(exc).__name__}: {exc}")
        _cleanup(repo, worktree, args.branch, result)
        result["status"] = "integrated"
    except Outcome as outcome:
        result["status"], result["reason"] = outcome.status, outcome.reason
    except Exception as exc:  # a crash must never read as integrated
        result["status"] = "error"
        result["reason"] = f"batch_finish failed: {type(exc).__name__}: {exc}"
    return result


def _arg(pattern, what: str):
    def check(value: str) -> str:
        if value.startswith("-") or not pattern.fullmatch(value):
            raise argparse.ArgumentTypeError(f"invalid {what}: {value!r}")
        return value
    return check


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--repo", default=None, help="main checkout (default: discover from cwd)")
    parser.add_argument("--worktree", required=True, help="absolute path of the lead worktree")
    parser.add_argument("--branch", required=True, type=_arg(BRANCH_RE, "branch name"))
    parser.add_argument("--task-id", required=True, type=_arg(TASK_ID_RE, "task id"))
    parser.add_argument("--commit", required=True, type=_arg(COMMIT_RE, "commit (hex sha)"))
    parser.add_argument(
        "--resume", action="store_true",
        help="integration-task step e.1: accept a branch tip other than --commit",
    )
    args = parser.parse_args(argv)
    if not os.path.isabs(args.worktree):
        parser.error(f"--worktree must be an absolute path: {args.worktree}")
    try:
        result = finish(args.repo or find_repo_root(), args)
    except Exception as exc:  # a crash must never read as integrated
        result = _result(args, os.path.realpath(args.worktree))
        result["reason"] = f"batch_finish failed: {type(exc).__name__}: {exc}"
    print(json.dumps(result, indent=2))
    return EXIT_CODES[result["status"]]


if __name__ == "__main__":
    raise SystemExit(main())
