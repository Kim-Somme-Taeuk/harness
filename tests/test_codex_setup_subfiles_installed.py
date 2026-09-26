"""Every sub-file the Codex setup skill tells the agent to read ships beside it.

2026-09-26: `plugin-codex/skills/setup/SKILL.md` names `project-interview.md`
and three other adjacent files, none of which exist under `plugin-codex/`. That
looked like a dead reference; it is not, because `_build_codex_payload` copies
them from `plugin/skills/setup/`. This test pins that pairing so dropping a name
from the copy list, or adding a row the installer never ships, fails here.
"""
from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SUBFILE_ROW = re.compile(r"^\|\s*`([\w.-]+\.md)`\s*\|", re.MULTILINE)


def _load_install_module():
    spec = importlib.util.spec_from_file_location("harness_install_setup_subfiles", REPO_ROOT / "install.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_the_built_codex_payload_contains_every_named_setup_subfile(tmp_path):
    install = _load_install_module()
    skill = (REPO_ROOT / "plugin-codex" / "skills" / "setup" / "SKILL.md").read_text(encoding="utf-8")
    named = SUBFILE_ROW.findall(skill)
    assert "project-interview.md" in named, named

    target = tmp_path / "harness"
    install._build_codex_payload(target, target)
    setup_dir = target / "skills" / "setup"
    missing = [name for name in named if not (setup_dir / name).is_file()]
    assert missing == [], f"Codex setup SKILL.md names sub-files the payload lacks: {missing}"
