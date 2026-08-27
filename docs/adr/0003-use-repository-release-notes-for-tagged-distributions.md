# 0003: Use repository release notes for tagged distributions

## Status

Accepted

## Context

Tagged releases make source selection reproducible, but version identifiers
alone do not tell users which repository capabilities changed. A repository
may publish a distribution containing multiple command-line entry points, and
one release can affect the repository broadly, a subset of those entry points,
or both. Separate per-entry-point histories would fragment the account of one
tagged distribution release.

## Decision

Maintain one root release-note record in reverse chronological order. Each
tagged distribution release has one finalized entry that identifies its tag,
release date, affected repository scope, and externally meaningful changes.
Release scopes name repository-wide capabilities and affected command-line
entry points independently, so an entry need not imply that every entry point
changed.

Known future releases use an explicitly labeled draft entry. Draft entries may
change until release preparation. Before a release tag is created, its entry
must be finalized with the matching distribution version and date. Published
entries may be corrected when needed.

Release validation must reject a candidate distribution version that lacks a
finalized, structurally complete matching entry. This policy does not require a
package registry publication or a hosted release object.

## Alternatives considered

- Keep release information only in Git commit history and tag annotations.
- Maintain a separate release-note history for every command-line entry point.
- Use hosted release objects as the authoritative release record.
- Document release notes without validating their presence during release
  preparation.

## Consequences

- Users can find a single, complete, ordered account of tagged distribution
  changes without reconstructing commit history.
- A release can communicate a narrow affected scope without imposing
  independent versioning on every command-line entry point.
- Draft release notes provide a visible, mutable accumulation point during
  development; release preparation has an explicit documentation gate.
- Existing tags can be documented by backfilled entries without changing their
  immutable Git references.

## References

None.

## Related ADRs

- [0002: Use Git-tag distribution until PyPI is justified](0002-use-git-tag-distribution-until-pypi-is-justified.md)
