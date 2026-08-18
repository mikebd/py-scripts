"""Command-line interface for ai-agent-launcher."""

import argparse
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from ai_agent_launcher._adapters import RuntimeAgentAdapter
from ai_agent_launcher._config import load_config
from ai_agent_launcher._defaults import default_registry
from ai_agent_launcher._errors import LauncherError
from ai_agent_launcher._models import AgentId
from ai_agent_launcher._registry import AgentRegistry
from ai_agent_launcher._runtime import RunContext, resolve_worktree

_DISTRIBUTION_NAME = "mikebd-py-scripts"


def distribution_version() -> str:
    """Return the installed package version without duplicating project metadata."""
    try:
        return version(_DISTRIBUTION_NAME)
    except PackageNotFoundError:
        return "0+unknown"


def build_parser(registry: AgentRegistry) -> argparse.ArgumentParser:
    """Build the root parser and delegate agent-owned options to adapters."""
    parser = argparse.ArgumentParser(
        prog="ai-agent-launcher",
        description="Launch and manage local AI coding-agent workspaces.",
    )
    parser.add_argument("--config", type=Path, metavar="PATH")
    parser.add_argument("--version", action="version", version=distribution_version())
    subparsers = parser.add_subparsers(dest="command")
    run_parser = subparsers.add_parser("run", help="run an agent in an existing Git worktree")
    run_parser.add_argument(
        "--agent", choices=[str(value) for value in registry.identifiers], required=True
    )
    run_parser.add_argument("--worktree-dir", metavar="PATH")
    run_parser.add_argument(
        "--add-dir", dest="requested_writable_dirs", action="append", default=[]
    )
    for identifier in registry.identifiers:
        adapter = registry.get(identifier)
        if isinstance(adapter, RuntimeAgentAdapter):
            adapter.configure_run_parser(run_parser)
    run_parser.add_argument("codex_arguments", nargs=argparse.REMAINDER, metavar="CODEX_ARGUMENT")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the root command, showing help when no operation was requested."""
    arguments = sys.argv[1:] if argv is None else argv
    registry = default_registry()
    parser = build_parser(registry)
    if not arguments:
        parser.print_help()
        return 0
    namespace = parser.parse_args(arguments)
    if namespace.command != "run":
        parser.print_help()
        return 0
    if namespace.codex_arguments and not _has_passthrough_separator(arguments):
        parser.error("Codex arguments must follow --")

    try:
        identifier = AgentId(namespace.agent)
        config = load_config(namespace.config, registry.identifiers)
        adapter = registry.get(identifier)
        if not isinstance(adapter, RuntimeAgentAdapter):
            raise LauncherError(f"agent does not support run: {identifier}")
        passthrough_args = tuple(namespace.codex_arguments)
        if passthrough_args[:1] == ("--",):
            passthrough_args = passthrough_args[1:]
        context = RunContext(
            worktree_dir=resolve_worktree(namespace.worktree_dir),
            configured_writable_dirs=config.core.writable_dirs,
            requested_writable_dirs=tuple(namespace.requested_writable_dirs),
            passthrough_args=passthrough_args,
        )
        return adapter.run(context, config.agent_settings.get(identifier, {}), namespace)
    except LauncherError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


def _has_passthrough_separator(arguments: list[str]) -> bool:
    """Report whether run's arbitrary Codex arguments were introduced by `--`."""
    try:
        run_index = arguments.index("run")
    except ValueError:
        return False
    return "--" in arguments[run_index + 1 :]
