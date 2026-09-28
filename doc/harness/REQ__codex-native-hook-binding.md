# Native Codex hook binding

After publishing the Codex payload, configuration, hook trust and marketplace
registration, Harness must refresh the installed hooks in running local Codex
sessions. An enabled, trusted hook listing establishes configuration, not actual
event delivery: a loaded session can still hold an earlier hook snapshot.

The installer discovers the daemon with `codex app-server daemon version` and
uses its native `config/batchWrite` API with empty edits and
`reloadUserConfig: true`. It does not restart the daemon or change user settings.
The local socket and connected peer must belong to the current user. The native
symlink from the private control directory to the private runtime socket is
supported; connection time, message size and notification count are bounded.

A failed discovery with an existing control endpoint, malformed daemon metadata,
or failed reload makes installation report failure after payload publication.
When no local endpoint exists, hooks load in the next session. Installing to a
config path different from the runtime's `CODEX_HOME/config.toml` (default
`~/.codex/config.toml`) reports that a new session must use that config and never
refreshes an unrelated daemon. An explicit path matching the runtime home does
reload that daemon.
Publication is retained after a reload failure; rollback is not automatic.
After fixing the daemon, retry with `python3 install.py --codex-only --force`.
Retain the original `CODEX_HOME` and any explicit `--config-path`; the installer
includes the shell-quoted configuration path in its retry command.
The ordinary synchronized-payload fast path does not repeat installation or
repair configuration and must not be used as evidence that a failed reload
has recovered.

Successful native task-start/context completion binds the exact hook session to
the returned open task generation. The validation, conflict fencing and
future-only watcher rules remain defined in
[the receipt protocol](patterns/ADR__single-direct-codex-receipt-protocol.md).
Outer JavaScript, printed tool results and compatibility markers are not
substitutes for native identity. Existing unregistered work is never replayed
into receipts.

Verification must cover installed routing and a real native task-result event,
then fresh required review and QA started/completed receipts. Missing event
delivery must remain distinguishable from rejected task binding; configuration
or unit-test success alone cannot establish working receipt acquisition.
