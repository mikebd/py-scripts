"""Command-line interface for ai-agent-launcher."""

from __future__ import annotations

import argparse
import os
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Protocol

import shtab

from ai_agent_launcher._adapters import RuntimeAgentAdapter, WritableDirectoryAdapter
from ai_agent_launcher._config import load_config
from ai_agent_launcher._defaults import default_registry
from ai_agent_launcher._errors import LauncherError
from ai_agent_launcher._launchers import (
    describe_launcher,
    launcher_git_metadata_access,
    read_launcher_artifact,
)
from ai_agent_launcher._lifecycle import LauncherLifecycle
from ai_agent_launcher._models import AgentId, GitMetadataAccess
from ai_agent_launcher._registry import AgentRegistry, UnknownAgentError
from ai_agent_launcher._runtime import RunContext, resolve_worktree
from ai_agent_launcher._worktrees import CreatedWorktree, WorktreeLifecycle

_DISTRIBUTION_NAME = "mikebd-py-scripts"
_COMPLETION_SHELLS = tuple(sorted(shtab.SUPPORTED_SHELLS))


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
    _add_worktree_parser(commands, registry)
    _add_completion_parser(commands)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the root command, showing help when no operation was requested."""
    arguments = sys.argv[1:] if argv is None else argv
    registry = default_registry()
    parser = build_parser(registry)
    if not arguments:
        parser.print_help()
        return 0
    namespace = parser.parse_args(_normalize_worktree_suffix(arguments))
    if namespace.command is None:
        parser.print_help()
        return 0
    try:
        return _dispatch(namespace, registry, parser, arguments)
    except (LauncherError, UnknownAgentError) as error:
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
    if namespace.command == "worktree":
        return _worktree(namespace, registry)
    if namespace.command == "completion":
        return _completion(namespace, parser)
    parser.print_help()
    return 0


def _completion(namespace: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    shell = namespace.shell or _detect_completion_shell(parser)
    sys.stdout.write(shtab.complete(parser, shell=shell))
    return 0


def _detect_completion_shell(parser: argparse.ArgumentParser) -> str:
    shell = Path(os.environ.get("SHELL", "")).name
    if shell not in _COMPLETION_SHELLS:
        parser.error(
            "could not detect a supported shell from $SHELL; "
            f"use completion --shell {{{','.join(_COMPLETION_SHELLS)}}}"
        )
    return shell


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
        git_metadata_access=config.core.default_git_metadata_access,
    )
    return adapter.run(context, config.agent_settings.get(identifier, {}), namespace)


def _launcher(
    namespace: argparse.Namespace,
    registry: AgentRegistry,
    parser: argparse.ArgumentParser,
    arguments: list[str],
) -> int:
    if namespace.launcher_command == "describe":
        return _launcher_describe(namespace, registry)
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
            _optional_git_metadata_access(namespace.git_metadata_access),
        )
        return 0
    if namespace.launcher_command == "adopt":
        lifecycle.adopt(
            namespace.launcher,
            namespace.target_launcher,
            namespace.session_id,
            _optional_agent(namespace.agent),
            tuple(namespace.requested_writable_dirs),
            _optional_git_metadata_access(namespace.git_metadata_access),
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
        _optional_git_metadata_access(namespace.git_metadata_access),
    )
    return 0


def _launcher_describe(namespace: argparse.Namespace, registry: AgentRegistry) -> int:
    metadata = read_launcher_artifact(namespace.launcher)
    description = describe_launcher(namespace.launcher, metadata)
    try:
        config = load_config(namespace.config, registry.identifiers)
        adapter = registry.get(metadata.agent_id)
        if not isinstance(adapter, WritableDirectoryAdapter):
            raise LauncherError(
                f"agent does not report effective writable directories: {metadata.agent_id}"
            )
        report = adapter.resolve_writable_dirs(
            RunContext(
                worktree_dir=metadata.worktree_dir,
                configured_writable_dirs=config.core.writable_dirs,
                requested_writable_dirs=tuple(
                    str(directory) for directory in metadata.local_writable_dirs
                ),
                passthrough_args=(),
                git_metadata_access=launcher_git_metadata_access(metadata),
            ),
            config.agent_settings.get(metadata.agent_id, {}),
        )
    except (LauncherError, LookupError) as error:
        sys.stdout.write(_format_writable_directory_report(description, (), (str(error),)))
        return 0
    sys.stdout.write(
        _format_writable_directory_report(description, report.directories, report.notes)
    )
    return 0


def _format_writable_directory_report(
    description: str, directories: tuple[Path, ...], notes: tuple[str, ...]
) -> str:
    lines = [description.rstrip("\n")]
    if directories:
        lines.append("effective writable directories:")
        lines.extend(f"  - {directory}" for directory in sorted(directories))
    else:
        lines.append("effective writable directories: none")
    if notes:
        lines.append("effective writable directory notes:")
        lines.extend(f"  - {note}" for note in notes)
    return "\n".join(lines) + "\n"


def _worktree(namespace: argparse.Namespace, registry: AgentRegistry) -> int:
    """Create a Git worktree and its unpinned generated launcher."""
    config = load_config(namespace.config, registry.identifiers)
    lifecycle = LauncherLifecycle(registry, config)
    worktrees = WorktreeLifecycle(config, lifecycle)
    agent_id = AgentId(namespace.agent)
    if namespace.worktree_command == "new":
        result = worktrees.new(
            agent_id,
            namespace.worktree_dir,
            namespace.branch,
            namespace.from_ref,
            namespace.launcher,
            namespace.marker,
            namespace.preparation_path,
            tuple(namespace.requested_writable_dirs),
            _optional_git_metadata_access(namespace.git_metadata_access),
        )
    elif namespace.worktree_command == "stack":
        result = worktrees.stack(
            agent_id,
            namespace.suffix,
            namespace.marker,
            namespace.preparation_path,
            tuple(namespace.requested_writable_dirs),
            _optional_git_metadata_access(namespace.git_metadata_access),
        )
    else:
        raise LauncherError("worktree command is required")
    _print_created_worktree(result)
    return 0


def _print_created_worktree(result: CreatedWorktree) -> None:
    print(f"created worktree: {result.worktree_dir}")
    print(f"created branch: {result.branch}")
    print(f"created launcher: {result.launcher}")
    print(
        "default session: none; run the launcher once, then use "
        f"ai-agent-launcher launcher pin --launcher {result.launcher} --session-id ID"
    )


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
    _add_git_metadata_access_argument(create)

    run = launcher_commands.add_parser("run", help="execute a generated launcher")
    run.add_argument("--launcher", type=Path, required=True)
    run.add_argument("agent_arguments", nargs=argparse.REMAINDER, metavar="AGENT_ARGUMENT")

    describe = launcher_commands.add_parser(
        "describe", help="describe a generated launcher artifact"
    )
    describe.add_argument("--launcher", type=Path, required=True)

    pin = launcher_commands.add_parser("pin", help="pin a launcher to a session")
    pin.add_argument("--launcher", type=Path, required=True)
    pin.add_argument("--session-id", required=True)
    pin.add_argument("--agent", choices=agent_choices)
    pin.add_argument("--replace", action="store_true")

    fork = launcher_commands.add_parser("fork", help="fork a pinned launcher session")
    _add_source_target_arguments(fork, agent_choices)
    _add_directories_argument(fork)
    _add_git_metadata_access_argument(fork)
    fork.add_argument("agent_arguments", nargs=argparse.REMAINDER, metavar="AGENT_ARGUMENT")

    adopt = launcher_commands.add_parser("adopt", help="bind a launcher to an existing session")
    _add_source_target_arguments(adopt, agent_choices)
    adopt.add_argument("--session-id", required=True)
    _add_directories_argument(adopt)
    _add_git_metadata_access_argument(adopt)


def _add_worktree_parser(commands: _SubparserCommands, registry: AgentRegistry) -> None:
    worktree_parser = commands.add_parser("worktree", help="create Git worktrees and launchers")
    worktree_commands = worktree_parser.add_subparsers(dest="worktree_command", required=True)
    agent_choices = [str(value) for value in registry.identifiers]

    new = worktree_commands.add_parser(
        "new", help="create an explicit worktree and unpinned launcher"
    )
    new.add_argument("--agent", choices=agent_choices, required=True)
    new.add_argument("--worktree-dir", type=Path, required=True)
    new.add_argument("--branch")
    new.add_argument("--from", dest="from_ref")
    new.add_argument("--launcher", type=Path)
    _add_worktree_launcher_options(new)

    stack = worktree_commands.add_parser(
        "stack", help="create strict sibling targets from the current worktree"
    )
    stack.add_argument("--agent", choices=agent_choices, required=True)
    stack.add_argument("--suffix", required=True)
    _add_worktree_launcher_options(stack)


def _add_completion_parser(commands: _SubparserCommands) -> None:
    completion = commands.add_parser("completion", help="print shell completion code")
    completion.add_argument("--shell", choices=_COMPLETION_SHELLS)


def _add_directories_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--add-dir", dest="requested_writable_dirs", action="append", default=[])


def _add_worktree_launcher_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--marker", required=True)
    parser.add_argument("--prepare", dest="preparation_path", type=Path)
    _add_directories_argument(parser)
    _add_git_metadata_access_argument(parser)


def _add_git_metadata_access_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--git-metadata-access",
        choices=[access.value for access in GitMetadataAccess],
        help="persist Git metadata access for the generated launcher",
    )


def _add_source_target_arguments(parser: argparse.ArgumentParser, agent_choices: list[str]) -> None:
    parser.add_argument("--launcher", type=Path, required=True)
    parser.add_argument("--target-launcher", type=Path, required=True)
    parser.add_argument("--agent", choices=agent_choices)


def _optional_agent(value: str | None) -> AgentId | None:
    return AgentId(value) if value is not None else None


def _optional_git_metadata_access(value: str | None) -> GitMetadataAccess | None:
    return GitMetadataAccess(value) if value is not None else None


def _passthrough(values: list[str]) -> tuple[str, ...]:
    arguments = tuple(values)
    return arguments[1:] if arguments[:1] == ("--",) else arguments


def _require_separator(
    values: list[str], arguments: list[str], parser: argparse.ArgumentParser
) -> None:
    if values and "--" not in arguments:
        parser.error("agent arguments must follow --")


def _normalize_worktree_suffix(arguments: list[str]) -> list[str]:
    """Preserve legacy `--suffix -child` parsing without changing other options."""
    try:
        worktree_index = arguments.index("worktree")
    except ValueError:
        return arguments
    stack_index = worktree_index + 1
    if stack_index >= len(arguments) or arguments[stack_index] != "stack":
        return arguments

    normalized: list[str] = []
    index = 0
    while index < len(arguments):
        current = arguments[index]
        if current == "--":
            normalized.extend(arguments[index:])
            break
        if (
            index > stack_index
            and current == "--suffix"
            and index + 1 < len(arguments)
            and arguments[index + 1].startswith("-")
            and not arguments[index + 1].startswith("--")
        ):
            normalized.append(f"--suffix={arguments[index + 1]}")
            index += 2
            continue
        normalized.append(current)
        index += 1
    return normalized
