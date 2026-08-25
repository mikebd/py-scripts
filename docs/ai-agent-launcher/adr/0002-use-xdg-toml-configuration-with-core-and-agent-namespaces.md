# 0002: Use XDG TOML configuration with core and agent namespaces

## Status

Accepted

## Context

An AI-agent workspace tool has settings shared by all integrations and
settings that only one integration can interpret. A single flat configuration
schema would either expose agent details as core concepts or make future
extensions collide. Configuration also needs a predictable local location and
clear behavior when users explicitly select a file.

## Decision

Use one TOML configuration document. Its default location is
`$XDG_CONFIG_HOME/ai-agent-launcher/config.toml`, falling back to
`$HOME/.config/ai-agent-launcher/config.toml`; an explicit configuration-path
option selects a different document.

Place settings shared by every integration in `[core]` and settings owned by
one integration in `[agents.<identifier>]`. The core validates its own schema
and recognized agent namespaces; each adapter validates the values in its own
namespace. Unknown configuration tables and keys are errors rather than
silently ignored.

Absence of the default configuration document means empty configuration. An
explicitly selected missing or invalid document is an error. Invocation options
may override adapter configuration only where that adapter declares the
option.

## Alternatives considered

- Use only command-line options and environment variables.
- Use a flat configuration document shared by every integration.
- Use JSON or YAML configuration.
- Ignore unknown keys to permit unchecked configuration evolution.

## Consequences

- Shared policy remains distinct from integration-specific settings.
- Adding an integration does not require expanding the core configuration
  schema with its private options.
- Strict validation detects misspellings and unsupported integrations early.
- Incompatible configuration changes require an explicit compatibility or
  migration decision rather than silent reinterpretation.

## References

- [XDG Base Directory Specification](https://specifications.freedesktop.org/basedir-spec/latest/)
- [TOML](https://toml.io/)

## Related ADRs

None.
