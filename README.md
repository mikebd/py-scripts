# mikebd's Python Scripts

A personal collection of small Python tools.

For simpler shell-first utilities, also check [`mikebd/bash-scripts`](https://github.com/mikebd/bash-scripts).
That repo is the lighter-weight Bash companion to this one and can act as a staging ground for utilities that may later be promoted into Python when they need more structure, tests, or packaging.

Currently tested only on Linux ([Pop!_OS](https://system76.com/pop/) 22.04).  `brew` commands currently assume formulas
only, cask support for `macOS` may be added in the future.

AI guidance is currently provided for [JetBrains Junie](https://www.jetbrains.com/junie/) only.

## Table of Contents

- [Requirements](#requirements)
- [Running scripts](#running-scripts)
- [Available Scripts](#available-scripts)
- [Development](#development)
  - [Architecture Decisions](#architecture-decisions)

## Requirements

- Python 3.13+
- [`uv`](https://github.com/astral-sh/uv)

## Running scripts

Scripts are run directly from the repository using `uv`, without installing anything globally.

From the repo root:

```bash
uv run bu
```

To make this convenient from anywhere, add an alias to your `.bashrc` or `.zshrc`:

```bash
alias bu='uv --project $HOME/src/mikebd/py/scripts run bu'
```

## Available Scripts

### AI Agent Launcher (`ai-agent-launcher`)

Creates and runs local AI coding-agent workspaces through an agent-neutral
core. The initial built-in adapter is `codex`. See the
[AI agent launcher guide](docs/ai-agent-launcher.md) for tagged installation,
configuration, and release guidance.

### Brew Diff (`brew_diff <remote_host>`)

Campares manually installed Homebrew formulas betweel the local and remote hosts.

### Brew Info New Formula (`bu`)

One way I keep track of the evolving developer ecosystem is by paying close
attention to new packages as they become available. This script simplifies that process by
automating the display of `brew info` output for newly added formulas.

Recommended environment variable to prevent implicit updates: `HOMEBREW_NO_AUTO_UPDATE=1`

#### bu Examples

Already up to date:

![bu - no new formulas.png](docs/images/bu-no-new-formulas.png)

New formula + outdated packages:

![bu - one new formula](docs/images/bu-one-new-formula.png)

#### bu Inspiration

```bash
#!/bin/bash

old_formulas=$(brew search --formula / | sort)
old_casks=$(brew search --cask / | sort)

brew update

new_formulas=$(brew search --formula / | sort)
new_casks=$(brew search --cask / | sort)

newly_added_formulas=$(comm -13 <(echo "$old_formulas") <(echo "$new_formulas"))
newly_added_casks=$(comm -13 <(echo "$old_casks") <(echo "$new_casks"))

echo "New Formulas:"
echo "$newly_added_formulas" | xargs brew info --formula
echo
echo "New Casks:"
echo "$newly_added_casks" | xargs brew info --cask
```

### JetBrains Codex Fix (`codex_fix`)

JetBrains IDEs bundle a Codex binary that can fail on Linux because of GLIBC incompatibilities. This script inspects cache folders (default `~/.cache/JetBrains`), extracts the latest `Codex CLI version mismatch` entry from each `idea.log`, downloads the matching musl Codex release from SourceForge, and installs it as `codex-x86_64-unknown-linux-gnu` inside the IDE cache so the IDE uses a compatible executable.

Run it via `uv run codex_fix`. Useful flags:
- `--cache-root` to point at a different JetBrains cache directory.
- `--ide-dir` (repeatable) to target specific IDE caches directly.
- `--all` to operate on every cache directory that matches any include/exclude filters instead of just one.
- `--include` / `--exclude` regexes to filter which IDE caches are touched.
- `--version` to override the parsed version and always install a specific Codex release.
- `--timeout-s` to control the download timeout.

Backups of existing binaries are created before replacement, and each install is verified by running the installed binary with `--version` so failures are reported per-IDE in the summary.

## Development

### Architecture Decisions

Durable repository decisions are recorded as [architecture decision
records](docs/adr/README.md). ADRs preserve the current rule, rationale,
alternatives, and consequences without turning routine implementation work
into permanent architecture policy. Accepted records retain their original
decision; later clarifications are dated amendments, while material changes
use a new superseding record.

### Branch Context

This repository's optional Branch Context is maintained on the [`py-scripts-context` branch](https://github.com/mikebd/public-branch-context/tree/py-scripts-context) of the public Branch Context repository. It provides branch-scoped working context for coding-agent workflows, including resumability, decision traceability, handoffs, and reproducible investigations.

See the [Branch Context guidance](https://github.com/mikebd/ai-agent-skills/tree/main/shared/references/branch-context) for the overall model and conventions.

### Setup

```bash
uv run pre-commit install
```

### Makefile

A `Makefile` is provided for common development tasks. These commands use `uv` to run `ruff`, `pyright` and `pytest`
within the project environment.

| Command              | Description                                   |
|:---------------------|:----------------------------------------------|
| `make`               | Show the help menu (default)                  |
| `make test`          | Run `pytest` tests with coverage              |
| `make test-parallel` | Run `pytest` tests with coverage, using xdist |
| `make lint`          | Run `ruff` linting checks                     |
| `make typecheck`     | Run `pyright` static type analysis            |
| `make check`         | Run both linting and type checking            |
| `make fix`           | Automatically fix linting issues              |
| `make format`        | Format code with `ruff`                       |
| `make fmt`           | Fix, format, and run all checks (convenience) |
| `make build`         | Build source and wheel distributions          |
| `make release-check` | Validate a clean Git-tagged tool installation |
| `make all`           | Run all non-mutating checks                   |
