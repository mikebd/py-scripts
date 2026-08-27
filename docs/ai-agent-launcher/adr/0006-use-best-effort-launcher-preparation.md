# 0006: Use best-effort launcher preparation

## Status

Accepted

## Context

Generated launchers may retain an optional preparation helper that performs
workspace setup before an agent action. Helper files and their dependencies
can change after launcher creation. Treating a later availability or execution
failure as invalid launcher metadata makes an otherwise usable workspace and
session unavailable, while automatically discarding the helper loses an
opportunity to recover when it is repaired.

## Decision

Treat preparation helpers as optional, best-effort workspace plumbing. Store a
canonical absolute helper path in launcher metadata. Resolve a relative helper
path from the selected workspace, including normal path traversal, before
persisting it.

Validate an explicitly configured helper when its workspace is already
available. When an operation creates a workspace, create the workspace before
checking and running its helper. At later launcher execution or session
operations, a missing, non-executable, or unsuccessful helper emits a visible
warning and does not prevent the primary operation from continuing. Preserve
the helper's output, retain its configured path, and retry it on later
operations. Interruptions remain interruptible.

Helper availability is runtime state, not required metadata structure. Do not
change the launcher metadata version, remove a failed helper automatically, or
add a strict-preparation mode for this policy.

## Alternatives considered

- Treat any helper failure as a hard lifecycle failure and roll back a newly
  created workspace.
- Resolve relative helper paths from the invoking process directory.
- Remove a helper automatically after its first failure.
- Add a persisted strict-preparation setting.

## Consequences

- A launcher remains runnable and maintainable when its optional helper later
  becomes unavailable.
- A helper tracked in a newly created workspace can be selected by a relative
  path.
- Warnings provide immediate diagnostics while allowing the agent to proceed.
- Existing absolute helper paths and launcher metadata formats remain
  compatible.

## References

None.

## Related ADRs

- [0003: Use versioned self-describing generated launcher artifacts](0003-use-versioned-self-describing-generated-launcher-artifacts.md)
