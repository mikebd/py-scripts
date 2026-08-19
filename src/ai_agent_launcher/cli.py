"""Command-line interface for ai-agent-launcher."""

from __future__ import annotations

import argparse
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Protocol

from ai_agent_launcher._adapters import RuntimeAgentAdapter
from ai_agent_launcher._config import default_config_path, load_config
from ai_agent_launcher._defaults import default_registry
from ai_agent_launcher._errors import LauncherError
from ai_agent_launcher._lifecycle import LauncherLifecycle
from ai_agent_launcher._migration import migrate_legacy_config, migrate_legacy_launcher
from ai_agent_launcher._models import AgentId
from ai_agent_launcher._registry import AgentRegistry
from ai_agent_launcher._runtime import RunContext, resolve_worktree

_DISTRIBUTION_NAME = "mikebd-py-scripts"


class _SubparserCommands(Protocol):
    def add_parser(
        self,
        name: str,
        *,
        help: str | None = None,
    ) -> argparse.ArgumentParser: ...


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
    commands = parser.add_subparsers(dest="command")
    _add_run_parser(commands, registry)
    _add_launcher_parser(commands, registry)
    _add_migration_parser(commands, registry)
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
    if namespace.command is None:
        parser.print_help()
        return 0
    try:
        return _dispatch(namespace, registry, parser, arguments)
    except LauncherError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


def _dispatch(
    namespace: argparse.Namespace,
    registry: AgentRegistry,
    parser: argparse.ArgumentParser,
    arguments: list[str],
) -> int:
    if namespace.command == "run":
        _require_separator(namespace.agent_arguments, arguments, parser)
        return _run(namespace, registry)
    if namespace.command == "launcher":
        return _launcher(namespace, registry, parser, arguments)
    if namespace.command == "migrate":
        return _migrate(namespace)
    parser.print_help()
    return 0


def _run(namespace: argparse.Namespace, registry: AgentRegistry) -> int:
    identifier = AgentId(namespace.agent)
    config = load_config(namespace.config, registry.identifiers)
    adapter = registry.get(identifier)
    if not isinstance(adapter, RuntimeAgentAdapter):
        raise LauncherError(f"agent does not support run: {identifier}")
    context = RunContext(
        worktree_dir=resolve_worktree(namespace.worktree_dir),
        configured_writable_dirs=config.core.writable_dirs,
        requested_writable_dirs=tuple(namespace.requested_writable_dirs),
        passthrough_args=_passthrough(namespace.agent_arguments),
    )
    return adapter.run(context, config.agent_settings.get(identifier, {}), namespace)


def _launcher(
    namespace: argparse.Namespace,
    registry: AgentRegistry,
    parser: argparse.ArgumentParser,
    arguments: list[str],
) -> int:
    config = load_config(namespace.config, registry.identifiers)
    lifecycle = LauncherLifecycle(registry, config)
    if namespace.launcher_command == "create":
        return _launcher_create(namespace, lifecycle)
    if namespace.launcher_command == "run":
        _require_separator(namespace.agent_arguments, arguments, parser)
        return lifecycle.run(namespace.launcher, _passthrough(namespace.agent_arguments))
    if namespace.launcher_command == "pin":
        lifecycle.pin(
            namespace.launcher,
            namespace.session_id,
            _optional_agent(namespace.agent),
            namespace.replace,
        )
        return 0
    if namespace.launcher_command == "fork":
        _require_separator(namespace.agent_arguments, arguments, parser)
        lifecycle.fork(
            namespace.launcher,
            namespace.target_launcher,
            _optional_agent(namespace.agent),
            tuple(namespace.requested_writable_dirs),
            _passthrough(namespace.agent_arguments),
        )
        return 0
    if namespace.launcher_command == "adopt":
        lifecycle.adopt(
            namespace.launcher,
            namespace.target_launcher,
            namespace.session_id,
            _optional_agent(namespace.agent),
            tuple(namespace.requested_writable_dirs),
        )
        return 0
    parser.error("launcher command is required")
    return 2


def _launcher_create(namespace: argparse.Namespace, lifecycle: LauncherLifecycle) -> int:
    lifecycle.create(
        AgentId(namespace.agent),
        namespace.launcher,
        namespace.worktree_dir,
        namespace.marker,
        namespace.preparation_path,
        tuple(namespace.requested_writable_dirs),
    )
    return 0


def _migrate(namespace: argparse.Namespace) -> int:
    if namespace.migration_command == "config":
        target = namespace.target if namespace.target is not None else default_config_path()
        ignored = migrate_legacy_config(
            namespace.source,
            target,
            trusted=namespace.trust_legacy_shell_config,
            replace=namespace.replace,
        )
        if ignored:
            print(
                f"warning: ignored legacy configuration variables: {', '.join(ignored)}",
                file=sys.stderr,
            )
        return 0
    if namespace.migration_command == "launcher":
        migrate_legacy_launcher(
            namespace.source,
            namespace.target,
            agent_id=AgentId(namespace.agent),
            marker=namespace.marker,
            preparation_path=namespace.preparation_path,
            replace=namespace.replace,
        )
        return 0
    raise LauncherError("migration command is required")


def _add_run_parser(commands: _SubparserCommands, registry: AgentRegistry) -> None:
    run_parser = commands.add_parser("run", help="run an agent in an existing Git worktree")
    run_parser.add_argument(
        "--agent", choices=[str(value) for value in registry.identifiers], required=True
    )
    run_parser.add_argument("--worktree-dir", metavar="PATH")
    _add_directories_argument(run_parser)
    for identifier in registry.identifiers:
        adapter = registry.get(identifier)
        if isinstance(adapter, RuntimeAgentAdapter):
            adapter.configure_run_parser(run_parser)
    run_parser.add_argument("agent_arguments", nargs=argparse.REMAINDER, metavar="AGENT_ARGUMENT")


def _add_launcher_parser(commands: _SubparserCommands, registry: AgentRegistry) -> None:
    launcher_parser = commands.add_parser("launcher", help="create and manage generated launchers")
    launcher_commands = launcher_parser.add_subparsers(dest="launcher_command")
    agent_choices = [str(value) for value in registry.identifiers]

    create = launcher_commands.add_parser(
        "create", help="create a launcher for an existing worktree"
    )
    create.add_argument("--agent", choices=agent_choices, required=True)
    create.add_argument("--launcher", type=Path, required=True)
    create.add_argument("--worktree-dir", type=Path, required=True)
    create.add_argument("--marker", required=True)
    create.add_argument("--prepare", dest="preparation_path", type=Path)
    _add_directories_argument(create)

    run = launcher_commands.add_parser("run", help="execute a generated launcher")
    run.add_argument("--launcher", type=Path, required=True)
    run.add_argument("agent_arguments", nargs=argparse.REMAINDER, metavar="AGENT_ARGUMENT")

    pin = launcher_commands.add_parser("pin", help="pin a launcher to a session")
    pin.add_argument("--launcher", type=Path, required=True)
    pin.add_argument("--session-id", required=True)
    pin.add_argument("--agent", choices=agent_choices)
    pin.add_argument("--replace", action="store_true")

    fork = launcher_commands.add_parser("fork", help="fork a pinned launcher session")
    _add_source_target_arguments(fork, agent_choices)
    _add_directories_argument(fork)
    fork.add_argument("agent_arguments", nargs=argparse.REMAINDER, metavar="AGENT_ARGUMENT")

    adopt = launcher_commands.add_parser("adopt", help="bind a launcher to an existing session")
    _add_source_target_arguments(adopt, agent_choices)
    adopt.add_argument("--session-id", required=True)
    _add_directories_argument(adopt)


def _add_migration_parser(commands: _SubparserCommands, registry: AgentRegistry) -> None:
    migration_parser = commands.add_parser(
        "migrate", help="explicitly migrate legacy Codex artifacts"
    )
    migrations = migration_parser.add_subparsers(dest="migration_command")
    config = migrations.add_parser("config", help="migrate trusted legacy Bash configuration")
    config.add_argument("--from", dest="source", type=Path, required=True)
    config.add_argument("--to", dest="target", type=Path)
    config.add_argument("--trust-legacy-shell-config", action="store_true")
    config.add_argument("--replace", action="store_true")

    launcher = migrations.add_parser("launcher", help="migrate one legacy generated launcher")
    launcher.add_argument(
        "--agent", choices=[str(value) for value in registry.identifiers], required=True
    )
    launcher.add_argument("--from", dest="source", type=Path, required=True)
    launcher.add_argument("--to", dest="target", type=Path, required=True)
    launcher.add_argument("--marker", required=True)
    launcher.add_argument("--prepare", dest="preparation_path", type=Path, required=True)
    launcher.add_argument("--replace", action="store_true")


def _add_directories_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--add-dir", dest="requested_writable_dirs", action="append", default=[])


def _add_source_target_arguments(parser: argparse.ArgumentParser, agent_choices: list[str]) -> None:
    parser.add_argument("--launcher", type=Path, required=True)
    parser.add_argument("--target-launcher", type=Path, required=True)
    parser.add_argument("--agent", choices=agent_choices)


def _optional_agent(value: str | None) -> AgentId | None:
    return AgentId(value) if value is not None else None


def _passthrough(values: list[str]) -> tuple[str, ...]:
    arguments = tuple(values)
    return arguments[1:] if arguments[:1] == ("--",) else arguments


def _require_separator(
    values: list[str], arguments: list[str], parser: argparse.ArgumentParser
) -> None:
    if values and "--" not in arguments:
        parser.error("agent arguments must follow --")
