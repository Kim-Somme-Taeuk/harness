#!/usr/bin/env python3
"""Harvest one lead's task evidence from a linked worktree before removal.

`doc/harness/tasks/` and `doc/harness/learnings.jsonl` are gitignored, so a
batch lead's task evidence and learnings only exist inside its own linked
worktree. Before the coordinator runs `git worktree remove` it must copy that
evidence into the main checkout, or it is lost.

Usage:
  python3 plugin/scripts/batch_harvest.py --worktree <abs path> \
      --task-id <TASK__x> [--repo <main checkout>]

Refuses (non-zero exit, nothing written) unless:
  - `<worktree>` is a registered linked worktree of `--repo` (a regular,
    non-symlink `.git` gitfile whose `gitdir:` target sits directly under
    `<repo>/.git/worktrees/`, with a matching `gitdir` back-pointer); and
  - the worktree's current HEAD commit is an ancestor of the main checkout's
    HEAD (i.e. already merged).

Idempotent: re-running after a successful harvest is a no-op for the archive
copy (byte-identical tree) and appends zero learnings rows. An existing archive
with different content for the same task id is refused, never replaced. Never removes the
worktree, branch, or any git state — that stays the coordinator's job with
plain `git worktree remove` / `git branch -d`.

Stdlib only.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _lib import (  # type: ignore  # noqa: E402
    GitBindingError,
    _trusted_git_env,
    resolve_registered_worktree,
    find_repo_root,
)

TASK_ID_RE = re.compile(r"^TASK__[A-Za-z0-9._-]+$")


class HarvestError(RuntimeError):
    """Refusal to harvest — nothing has been written when this is raised."""


def _verify_registered_worktree(repo_root: str, worktree: str) -> None:
    """Refuse unless `worktree` is a registered linked worktree of `repo_root`."""
    if not os.path.isabs(worktree):
        raise HarvestError(f"--worktree must be an absolute path: {worktree}")
    try:
        resolved = resolve_registered_worktree(repo_root, worktree)
    except GitBindingError as exc:
        raise HarvestError(f"worktree is not a registered git worktree: {exc}") from exc
    if not resolved:
        raise HarvestError("--worktree names the main checkout, not a linked worktree")


def _worktree_head_sha(worktree: str) -> str:
    result = subprocess.run(
        ["git", "-C", worktree, "rev-parse", "HEAD"],
        capture_output=True, text=True, check=False, env=_trusted_git_env(),
    )
    if result.returncode != 0:
        raise HarvestError(f"cannot resolve worktree HEAD: {result.stderr.strip()}")
    sha = result.stdout.strip()
    if not sha:
        raise HarvestError("worktree HEAD is empty")
    return sha


def _verify_merged(repo_root: str, worktree: str) -> None:
    sha = _worktree_head_sha(worktree)
    result = subprocess.run(
        ["git", "merge-base", "--is-ancestor", sha, "HEAD"],
        cwd=repo_root, capture_output=True, text=True, check=False,
        env=_trusted_git_env(),
    )
    if result.returncode != 0:
        raise HarvestError(
            f"worktree HEAD {sha} is not merged into the main checkout's HEAD"
        )


def _refuse_links_below(worktree: str, *parts: str) -> str:
    """Return ``<worktree>/<parts...>`` after refusing a symlink at any level."""
    path = worktree
    for part in parts:
        path = os.path.join(path, part)
        try:
            info = os.lstat(path)
        except FileNotFoundError:
            return path
        if stat.S_ISLNK(info.st_mode):
            raise HarvestError(f"refusing symlink in worktree evidence path: {path}")
    return path


def _refuse_non_regular_tree(root: str) -> None:
    """Refuse symlinks, FIFOs, sockets, and devices anywhere under ``root``."""
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        for name in dirnames + filenames:
            full = os.path.join(dirpath, name)
            mode = os.lstat(full).st_mode
            if not (stat.S_ISDIR(mode) or stat.S_ISREG(mode)):
                raise HarvestError(
                    f"refusing non-regular entry in task evidence: {full}"
                )


def _hash_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _tree_entries(root: str) -> dict:
    """Map every relative path under `root` to a file hash, or None for a dir."""
    entries: dict = {}
    for dirpath, dirnames, filenames in os.walk(root):
        for name in dirnames:
            rel = os.path.relpath(os.path.join(dirpath, name), root)
            entries[rel] = None
        for name in filenames:
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, root)
            entries[rel] = _hash_file(full)
    return entries


def _archive_task(repo_root: str, worktree: str, task_id: str) -> str:
    if not TASK_ID_RE.match(task_id):
        raise HarvestError(f"invalid task_id: {task_id}")
    source_dir = _refuse_links_below(worktree, "doc", "harness", "tasks", task_id)
    if not os.path.isdir(source_dir):
        raise HarvestError(f"task directory not found in worktree: {source_dir}")
    # A lead's worktree is untrusted input: copy only plain files and dirs so a
    # planted link or FIFO can neither pull outside files in nor hang the copy.
    _refuse_non_regular_tree(source_dir)

    dest_root = os.path.join(repo_root, "doc", "harness", "archive", "batch")
    dest_dir = os.path.join(dest_root, task_id)
    os.makedirs(dest_root, exist_ok=True)

    if os.path.lexists(dest_dir):
        if os.path.islink(dest_dir) or not os.path.isdir(dest_dir):
            raise HarvestError(
                f"archive destination exists and is not a plain directory: {dest_dir}"
            )
        if _tree_entries(source_dir) == _tree_entries(dest_dir):
            return dest_dir  # already archived, identical content: no-op
        # A different tree under the same id is an earlier batch's evidence
        # (e.g. a reused slug); never replace it.
        raise HarvestError(
            f"archive already holds different evidence for {task_id}: {dest_dir}; "
            "refusing to overwrite it"
        )

    tmp_dir = tempfile.mkdtemp(dir=dest_root, prefix=f".{task_id}.tmp-")
    try:
        # mkdtemp already created tmp_dir; copytree requires the destination to
        # not exist, so drop the empty placeholder before copying into it.
        os.rmdir(tmp_dir)
        shutil.copytree(source_dir, tmp_dir, symlinks=True)
        os.rename(tmp_dir, dest_dir)
    except Exception:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise
    return dest_dir


def _read_learnings_rows(src: str) -> list:
    """Return the JSON-object rows of a worktree learnings file, no links followed."""
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        fd = os.open(src, flags)
    except FileNotFoundError:
        return []
    except OSError as exc:
        raise HarvestError(f"refusing unreadable or symlinked learnings file: {src}") from exc
    with os.fdopen(fd, "r", encoding="utf-8") as handle:
        if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
            raise HarvestError(f"refusing non-regular learnings file: {src}")
        rows = []
        for line in handle:
            stripped = line.rstrip("\n")
            try:
                if isinstance(json.loads(stripped), dict):
                    rows.append(stripped)
            except ValueError:
                continue
        return rows


def _append_learnings(repo_root: str, rows: list) -> int:
    if not rows:
        return 0
    dest = os.path.join(repo_root, "doc", "harness", "learnings.jsonl")
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest, "a+", encoding="utf-8") as handle:
        # Read-dedupe-append under one exclusive lock so a retried harvest
        # cannot interleave with a still-running one.
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        handle.seek(0)
        existing = {line.rstrip("\n") for line in handle if line.strip()}
        new_rows = []
        for row in rows:
            if row not in existing:
                new_rows.append(row)
                existing.add(row)
        for row in new_rows:
            handle.write(row + "\n")
    return len(new_rows)


def harvest(repo_root: str, worktree: str, task_id: str) -> dict:
    repo_root = os.path.realpath(repo_root)
    if not os.path.isabs(worktree):
        raise HarvestError(f"--worktree must be an absolute path: {worktree}")
    # Validate and operate on one canonical path, never the raw argument.
    worktree = os.path.realpath(worktree)
    _verify_registered_worktree(repo_root, worktree)
    _verify_merged(repo_root, worktree)
    # Read and validate every input before the first write, so a refusal
    # leaves the main checkout untouched.
    rows = _read_learnings_rows(
        _refuse_links_below(worktree, "doc", "harness", "learnings.jsonl")
    )
    dest_dir = _archive_task(repo_root, worktree, task_id)
    appended = _append_learnings(repo_root, rows)
    return {"archived": dest_dir, "learnings_appended": appended}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worktree", required=True, help="absolute path to the linked worktree")
    parser.add_argument("--task-id", required=True, help="TASK__... id to harvest")
    parser.add_argument(
        "--repo", default=None,
        help="main checkout root (default: discover from cwd)",
    )
    args = parser.parse_args()

    repo_root = args.repo or find_repo_root()
    try:
        summary = harvest(repo_root, args.worktree, args.task_id)
    except HarvestError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
