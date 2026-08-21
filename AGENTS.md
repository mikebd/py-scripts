## Validation

Use the Makefile targets as the authoritative validation interface. For this
repository, run `make all`; do not treat direct `.venv/bin/pytest` or
`.venv/bin/pyright` invocations as equivalent unless that environment has been
verified to contain the project's development dependencies.

For Ruff work, prefer `make lint`, `make fix`, `make format`, or `make fmt`
over direct `uv run ruff ...` commands. These stable targets are the
repository's approval-friendly boundaries; use an ad-hoc Ruff invocation only
when no target expresses the needed operation.
