"""Command-line interface for ai-agent-launcher."""

import argparse
import sys
from importlib.metadata import PackageNotFoundError, version

_DISTRIBUTION_NAME = "mikebd-py-scripts"


def distribution_version() -> str:
    """Return the installed package version without duplicating project metadata."""
    try:
        return version(_DISTRIBUTION_NAME)
    except PackageNotFoundError:
        return "0+unknown"


def build_parser() -> argparse.ArgumentParser:
    """Build the intentionally minimal root command parser."""
    parser = argparse.ArgumentParser(
        prog="ai-agent-launcher",
        description="Launch and manage local AI coding-agent workspaces.",
    )
    parser.add_argument("--version", action="version", version=distribution_version())
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the root command, showing help when no operation was requested."""
    arguments = sys.argv[1:] if argv is None else argv
    parser = build_parser()
    if not arguments:
        parser.print_help()
        return 0
    parser.parse_args(arguments)
    return 0
