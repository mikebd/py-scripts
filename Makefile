.PHONY: help lint format typecheck fix check all fmt

# Default target: show help
help:
	@echo "Available commands:"
	@echo "  make test      - Run tests and coverage with pytest"
	@echo "  make lint      - Run ruff linting checks"
	@echo "  make typecheck - Run pyright type analysis"
	@echo "  make check     - Run linting and type checking"
	@echo "  make fix       - Automatically fix linting issues"
	@echo "  make format    - Format code with ruff"
	@echo "  make fmt       - Fix, format, and run all checks"
	@echo "  make all       - Run all non-mutating checks"

# Default: non-mutating checks (CI-safe)
all: check test

check: lint typecheck

test:
	uv run pytest

lint:
	uv run ruff check .

typecheck:
	uv run pyright

# Mutating actions
fix:
	uv run ruff check . --fix

format:
	uv run ruff format .

# Convenience: fix + format + recheck
fmt: fix format check
