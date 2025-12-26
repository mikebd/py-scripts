# mikebd's Scripts

A personal collection of small Python command-line tools.

## Table of Contents

- [Requirements](#requirements)
- [Running scripts](#running-scripts)
- [Available Scripts](#available-scripts)
- [Development](#development)

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

### Brew Info New Formula (`bu`)

Identifies newly added Homebrew formulas after an update and displays their information.

## Development

A `Makefile` is provided for common development tasks. These commands use `uv` to run `ruff` and `pyright` within the
project environment.

| Command          | Description                                   |
|:-----------------|:----------------------------------------------|
| `make`           | Show the help menu (default)                  |
| `make lint`      | Run `ruff` linting checks                     |
| `make typecheck` | Run `pyright` static type analysis            |
| `make check`     | Run both linting and type checking            |
| `make fix`       | Automatically fix linting issues              |
| `make format`    | Format code with `ruff`                       |
| `make fmt`       | Fix, format, and run all checks (convenience) |
| `make all`       | Run all non-mutating checks                   |
