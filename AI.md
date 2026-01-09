# AI Coding Agent Instructions

This repository is optimized for AI-assisted development. Please follow these guidelines:

## Environment

- **Python:** 3.13+
- **Package Manager:** `uv` (use `uv run ...` for scripts and commands)
- **Workflow:** Use `make` commands for development tasks.

## Standards

- **Linter/Formatter:** `ruff` (configured in `pyproject.toml`)
- **Type Checker:** `pyright` in strict mode.
- **Testing:** `pytest` (place tests in `tests/` mirroring `src/`).

## Key Commands

- `make fmt`: Fix and format code.
- `make check`: Run linting and type checking.
- `make test`: Run tests with coverage.
- `make all`: Run all non-mutating checks and tests.

## Rules

- Always use type hints.
- Maintain minimum 70% test coverage.
- Prefer `uv` over `pip`.
- Follow the existing project structure in `src/`.
