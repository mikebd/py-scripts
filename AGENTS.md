## Current guidance

Read `README.md` and documentation relevant to the change before making a
durable decision. Discover and apply every `AGENTS.md` from the repository
root through the target directory; deeper guidance adds to this file and wins
when instructions conflict.

When an agent changes an `AGENTS.md`, README, or file under `docs/`, reread
that document during the same session before continuing. The changed guidance
takes effect immediately; do not wait for a restart or manual reminder.

## Architecture decisions

Before changing a durable public CLI contract, completion policy, adapter/core
boundary, configuration model, or distribution policy, read
`docs/adr/README.md` and the relevant ADRs. Add the next sequential ADR when
a change establishes, reverses, or materially changes such a decision; do not
create ADRs for routine implementation details or temporary tracking.

## Validation

Use the Makefile targets as the authoritative validation interface. For this
repository, run `make all`; do not treat direct `.venv/bin/pytest` or
`.venv/bin/pyright` invocations as equivalent unless that environment has been
verified to contain the project's development dependencies.

For Ruff work, prefer `make lint`, `make fix`, `make format`, or `make fmt`
over direct `uv run ruff ...` commands. These stable targets are the
repository's approval-friendly boundaries; use an ad-hoc Ruff invocation only
when no target expresses the needed operation.
