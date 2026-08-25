# AI agent launcher decision records

These scoped architecture decision records preserve consequential choices that
apply only to `ai-agent-launcher`. They do not establish policy for other
tools in this repository.

## Relationship to repository ADRs

The repository ADR directory, [`../../adr/README.md`](../../adr/README.md),
is reserved for reusable repository-wide policy. Use this directory when a
decision is durable for this tool but does not govern other independent tools.
If a later decision becomes repository-wide, record that policy in the root
ADR directory and add reciprocal related-record links where the relationship
is material.

This directory adopts the root ADR [lifecycle](../../adr/README.md#lifecycle),
[record structure](../../adr/README.md#record-structure), and
[generic-framing](../../adr/README.md#generic-framing) rules. The root
authoring guide, [`../../adr/AGENTS.md`](../../adr/AGENTS.md), governs durable
wording and maintenance unless this scoped guide states otherwise.

## Numbering and index

Numbers are local to this directory and are never reused or renumbered. Before
allocating a number, inspect this directory's numbered records in every
non-bare Git worktree and use the integer immediately after the highest
claimed number. Keep the index current in the same change as any scoped
record.

## Index

| Record | Status | Decision |
| --- | --- | --- |
| [0001](0001-use-internal-capability-based-agent-adapters.md) | Accepted | Use internal capability-based agent adapters. |
| [0002](0002-use-xdg-toml-configuration-with-core-and-agent-namespaces.md) | Accepted | Use XDG TOML configuration with core and agent namespaces. |
| [0003](0003-use-versioned-self-describing-generated-launcher-artifacts.md) | Accepted | Use versioned self-describing generated launcher artifacts. |
| [0004](0004-use-inspectable-optional-launcher-metadata-extensions.md) | Accepted | Use inspectable optional launcher metadata extensions. |
