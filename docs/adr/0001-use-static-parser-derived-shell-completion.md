# 0001: Use static parser-derived shell completion

## Status

Accepted

## Context

Command-line completion should reflect the public command parser without
requiring a separately maintained implementation for each shell. It must not
run application code on every tab press or modify a user's shell configuration
or privileged completion directories.

An `argparse` parser already describes commands, nested subcommands, options,
and choices. It can serve as the single source for static completion
generation.

## Decision

When a repository CLI supports shell completion, generate static scripts from
its authoritative parser with Shtab. Support the shells exposed by the
installed Shtab version rather than maintaining a separate shell list.

Expose completion through a top-level `completion` subcommand with an optional
`--shell` selector. Omitting it derives the shell from `$SHELL`; an explicit
value takes precedence. An absent or unsupported value produces an actionable
error directing the user to `--shell`.

Completion generation writes only to standard output. Users and package
managers choose whether and where to install or source the generated script;
the CLI does not edit shell startup files, alter completion search paths, or
write privileged directories.

Generated completion covers the CLI's parser-defined interface. Inputs outside
that parser's contract are outside the completion surface.

Shtab can embed shell commands in generated scripts, but that capability is not
part of this decision. It introduces run-time behavior beyond the parser
contract. A CLI that needs it must document the intentional exception and its
justification with that CLI.

## Alternatives considered

- Use dynamic Argcomplete-style completion that starts application Python on
  each tab press.
- Hand-maintain shell scripts for each supported shell.
- Add a command that installs completion by changing user shell configuration
  or system completion directories.
- Support only zsh.

## Consequences

- Shtab is a runtime dependency for CLIs that expose this capability.
- Parser commands, options, and choices remain the source of completion
  behavior, reducing drift from the documented interface.
- Completion installation remains explicit and user-owned, avoiding hidden
  configuration writes and system-specific path policy.
- By selecting completion generation rather than a parser-definition
  framework, this ADR preserves the option to use docopt via argopt where
  justified; it neither adopts nor rejects that approach.
- Static parser-derived generation is the default. An individual CLI may use
  an Argcomplete-style dynamic model only when a demonstrated need for live,
  application-defined completion makes it necessary; document that intentional
  exception and its justification with the CLI.

## References

- [Shtab](https://pypi.org/project/shtab/)
- [Shtab usage documentation](https://tqdm.github.io/shtab/use/)
- [Python `argparse`](https://docs.python.org/3/library/argparse.html)

## Related ADRs

None.
