UV := $(or \
  $(shell command -v uv), \
  $(shell command -v ~/.cargo/bin/uv), \
  $(shell command -v /home/linuxbrew/.linuxbrew/bin/uv) \
)

ifndef UV
$(error "uv not found in PATH. Please install uv: https://astral.sh/uv/")
endif

.PHONY: help lint format typecheck fix check all fmt build release-check

# Default target: show help
help:
	@echo "Available commands:"
	@echo "  make test          - Run tests and coverage with pytest"
	@echo "  make lint          - Run ruff linting checks"
	@echo "  make typecheck     - Run pyright type analysis"
	@echo "  make check         - Run linting and type checking"
	@echo "  make fix           - Automatically fix linting issues"
	@echo "  make format        - Format code with ruff"
	@echo "  make fmt           - Fix, format, and run all checks"
	@echo "  make build         - Build source and wheel distributions"
	@echo "  make release-check - Validate a clean Git-tagged tool installation"
	@echo "  make all           - Run all non-mutating checks"

# Default: non-mutating checks (CI-safe)
all: check test

check: lint typecheck

test:
	$(UV) run pytest

build:
	$(UV) build --no-sources

release-check: all build
	$(UV) run python scripts/check_release.py --uv "$(UV)"

test-parallel:
	$(UV) run pytest -n auto

lint:
	$(UV) run ruff check .

typecheck:
	$(UV) run pyright

# Mutating actions
fix:
	$(UV) run ruff check . --fix

format:
	$(UV) run ruff format .

# Convenience: fix + format + recheck
fmt: fix format check
