---
date: 2026-09-26
task: TASK__install-refreshes-claude-plugin-cache
tags: [install, claude, plugin-cache]
---

# install.py now delivers to the plugin cache Claude actually runs

Claude Code runs harness hooks from its plugin cache
(`~/.claude/plugins/cache/harness/harness/<version>`), not from
`~/.claude/harness-dev`. Because the plugin version stayed `2.3.0`,
`claude plugin update` never refreshed that cache. An install synced the
mirror while the runtime kept running the old code. On 2026-09-25 a receipt fix
reached the hooks only after a manual uninstall and reinstall. The installed
mirror's `plugin.json` version now carries a payload hash (`2.3.0+h<sha8>`),
so any payload change is a new version. Every Claude install path, including
the `--if-stale` "synchronized" skip, ends with
`claude plugin update harness@harness`. That installs the new code into a
fresh cache directory without a window where the plugin is missing, and it is a
no-op when the cache is already current. The source manifest keeps its plain
version. Old cache directories are marked orphaned by the Claude CLI.
