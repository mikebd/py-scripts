## Validation

Use the Makefile targets as the authoritative validation interface. For this
repository, run `make all`; do not treat direct `.venv/bin/pytest` or
`.venv/bin/pyright` invocations as equivalent unless that environment has been
verified to contain the project's development dependencies.
