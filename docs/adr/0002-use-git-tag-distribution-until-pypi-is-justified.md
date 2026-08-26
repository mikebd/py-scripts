# 0002: Use Git-tag distribution until PyPI is justified

## Status

Accepted

## Context

Releasable Python distributions that expose command-line entry points need a
distribution path that identifies the exact source selected by an installer,
supports a maintained fork, and avoids creating a public package-registry
commitment before it is useful. Git-tagged source installation provides that
path.

Publishing to PyPI creates a public package identity and an ongoing release
operation. It is justified only when a distribution has a demonstrated need
that Git-tag installation cannot reasonably meet and its maintainers are
prepared to operate that public release channel.

## Decision

Git-tagged source installation is the default external distribution method for
every releasable Python distribution in this repository. Release documentation
must identify the selected tag and include version-verification guidance.

An individual distribution may use PyPI as a documented exception to this
default. It does not require a dedicated ADR or amendment when its
documentation records the demonstrated consumer need and all of the following
release controls:

- an available package name and accountable project owner;
- package-specific versioning and release notes;
- clean installation validation of the built distribution artifacts;
- a dedicated GitHub Actions release workflow using scoped PyPI Trusted
  Publishing and a protected release environment; and
- maintained installation, support, and security-reporting guidance.

The exception documentation chooses the package topology. A PyPI distribution
may be a dedicated project in this repository or live in a separate repository;
this decision imposes neither layout.

A change to the repository-wide default requires a new or superseding ADR.

## Alternatives considered

- Publish every releasable distribution to PyPI by default.
- Prohibit PyPI publication permanently.
- Publish from a developer workstation with a long-lived credential.
- Require every PyPI distribution to use a dedicated repository.

## Consequences

- Git tags remain the normal release and installation contract, including for
  maintained forks.
- A PyPI exception carries explicit public-package and release-operation
  responsibilities; it is not a convenience-only distribution change.
- The default does not require a PyPI project, publication workflow, or package
  split for components that do not qualify for an exception.
- A repository-wide move to PyPI is a material policy change and requires a
  later ADR.

## References

- [PyPI Trusted Publishing](https://docs.pypi.org/trusted-publishers/using-a-publisher/)
- [PyPI Trusted Publishing security considerations](https://docs.pypi.org/trusted-publishers/security-model/)
- [uv workspaces](https://docs.astral.sh/uv/concepts/projects/workspaces/)

## Related ADRs

- [0003: Use repository release notes for tagged distributions](0003-use-repository-release-notes-for-tagged-distributions.md)
