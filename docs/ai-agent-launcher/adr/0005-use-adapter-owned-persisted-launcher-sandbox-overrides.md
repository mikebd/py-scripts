# 0005: Use adapter-owned persisted launcher sandbox overrides

## Status

Accepted

## Context

Generated launchers may need a sandbox policy that differs from the current
agent configuration while retaining the same workspace and session. Sandbox
mode names and their runtime meanings belong to each agent integration, but
the launcher lifecycle must be able to update persisted sandbox-related
settings safely and inspectably.

## Decision

Persist an optional launcher sandbox-mode override in the selected agent's
metadata-extension namespace. The agent adapter owns the supported modes,
validates an override before it is written, and applies it during generated
launcher execution. A missing override continues to use the agent's current
configuration default.

The neutral lifecycle may atomically update a launcher in place, including
generic launcher-local writable directories, but it does not define or
interpret agent sandbox modes. It preserves unrelated extensions and the
existing launcher artifact format.

## Alternatives considered

- Make sandbox mode a required, agent-neutral metadata field.
- Keep sandbox mode only in mutable agent configuration.
- Define a core-wide sandbox-mode vocabulary before another adapter requires
  one.
- Require a replacement launcher for each sandbox-policy change.

## Consequences

- A launcher can retain an explicit agent-specific sandbox policy without
  changing its configured default or creating a new session.
- The core can support additional adapters without encoding their sandbox-mode
  vocabularies or runtime semantics.
- Artifact inspection exposes the persisted override through the extension
  data.
- Removing or resetting an override remains a later lifecycle capability if a
  demonstrated need arises.

## References

None.

## Related ADRs

- [0001: Use internal capability-based agent adapters](0001-use-internal-capability-based-agent-adapters.md)
- [0003: Use versioned self-describing generated launcher artifacts](0003-use-versioned-self-describing-generated-launcher-artifacts.md)
- [0004: Use inspectable optional launcher metadata extensions](0004-use-inspectable-optional-launcher-metadata-extensions.md)
