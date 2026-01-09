# GitHub Copilot Instructions

## Project Context

This is a collection of Python command-line tools managed with `uv`.

## Coding Guidelines

- **Python Version:** 3.13+
- **Style:** Use `ruff` for formatting and linting.
- **Types:** Strict type checking with `pyright`. Always provide type hints for function signatures and public APIs.
- **Management:** Use `uv` for all dependency and environment management.

## Development Workflow

- Use the `Makefile` for standard tasks:
    - `make lint` for linting.
    - `make typecheck` for type analysis.
    - `make test` for running tests with coverage.
    - `make fmt` to format and fix common issues.

## Testing

- Use `pytest` for all tests.
- Place tests in the `tests/` directory mirroring the `src/` structure.
- Aim for high test coverage (minimum 70%).
