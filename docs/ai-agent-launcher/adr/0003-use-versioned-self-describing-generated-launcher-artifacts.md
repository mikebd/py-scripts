# 0003: Use versioned self-describing generated launcher artifacts

## Status

Accepted

## Context

Generated launchers persist beyond a single command invocation. They must
retain enough information to run the selected integration in the intended
workspace, while remaining portable across local shell environments and safe
to update. An unversioned or executable-data format would make future changes
ambiguous and encourage unsafe interpretation of launcher contents.

## Decision

Generate a minimal POSIX-shell launcher that delegates to the installed tool
resolved through `PATH`. Store the launcher state as self-describing,
versioned metadata in the artifact. The metadata identifies the selected
integration, workspace, optional opaque session reference, and generic local
launcher settings without embedding integration-specific invocation logic in
the shell shim.

Only the tool reads and writes generated metadata. It validates metadata
without evaluating it as shell code, rejects unsupported format versions, and
writes replacements atomically while preserving the intended executable mode.

On a runtime upgrade, continue reading every previously supported launcher
metadata format until the release provides an explicit, documented recreation
or migration path. Do not silently reinterpret an older format. An older
runtime encountering a newer format must fail before execution rather than
guessing its meaning.

## Alternatives considered

- Generate full agent-specific shell scripts.
- Store unversioned ad-hoc launcher state in shell variables or comments.
- Keep launcher state only in a central local database.
- Parse or execute arbitrary existing shell launchers to infer their state.

## Consequences

- Generated launchers remain small, inspectable entrypoints while lifecycle
  logic stays in the installed tool.
- Versioned metadata makes compatibility boundaries explicit.
- Manual edits to generated metadata are unsupported and fail validation when
  they no longer describe a supported artifact.
- New metadata versions require deliberate compatibility handling.

## References

None.

## Related ADRs

- [0004: Use inspectable optional launcher metadata extensions](0004-use-inspectable-optional-launcher-metadata-extensions.md)
- [0005: Use adapter-owned persisted launcher sandbox overrides](0005-use-adapter-owned-persisted-launcher-sandbox-overrides.md)
