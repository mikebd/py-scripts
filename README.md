# mikebd's Scripts

A personal collection of small Python command-line tools.

## Requirements

- Python 3.13+
- [`uv`](https://github.com/astral-sh/uv)

## Running scripts (recommended)

Scripts are run directly from the repository using `uv`, without installing anything globally.

From the repo root:

```bash
uv run bu
```

To make this convenient from anywhere, add an alias to your `.bashrc` or `.zshrc`:

```bash
alias bu='uv --project /home/mikebd/src/mikebd/py/scripts run bu'
```

## Available Scripts

### Brew Info New Formula (`bu`)

Identifies newly added Homebrew formulas after an update and displays their information.

```bash
bu
```

## Optional: install as a CLI (advanced)

If you want `bu` installed into your environment as a normal CLI tool:

```bash
pip install -e .
```

This is mainly useful for development or if you prefer traditional Python packaging workflows.
