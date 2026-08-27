# 0004: Use inspectable optional launcher metadata extensions

## Status

Accepted

## Context

Generated artifacts sometimes need optional persisted settings in addition to
their required execution state. Adding every optional setting to the required
metadata envelope creates unnecessary format-version pressure, while an
unstructured or hidden escape hatch makes persisted behavior difficult to
inspect and safely maintain.

## Decision

Use a strict required metadata envelope with an optional, namespaced extension
object for persisted settings that an older runtime can safely ignore. The
tool validates the required envelope, validates the extension container as
data rather than executable content, and reports every persisted extension
through artifact inspection.

Same-format lifecycle updates preserve well-formed extensions they do not
interpret. Extensions are only for optional settings: a change to required
structure, parsing, compatibility, or safety behavior requires a new metadata
format and follows the versioned-artifact policy.

## Alternatives considered

- Add every optional setting to the required top-level envelope.
- Keep optional persisted settings only in external configuration.
- Permit unstructured metadata with no inspection requirement.
- Store executable or shell-interpreted extension data.

## Consequences

- Additive optional settings can be persisted without weakening validation of
  required state.
- Artifact inspection remains a complete view of persisted launcher settings.
- Lifecycle operations do not silently discard compatible extension data.
- Incompatible metadata changes remain deliberate versioned-artifact changes.

## References

None.

## Related ADRs

- [0002: Use XDG TOML configuration with core and agent namespaces](0002-use-xdg-toml-configuration-with-core-and-agent-namespaces.md)
- [0003: Use versioned self-describing generated launcher artifacts](0003-use-versioned-self-describing-generated-launcher-artifacts.md)
- [0005: Use adapter-owned persisted launcher sandbox overrides](0005-use-adapter-owned-persisted-launcher-sandbox-overrides.md)
