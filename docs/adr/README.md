# Architecture decision records

Architecture decision records (ADRs) preserve consequential repository
decisions and their rationale. They make future changes reviewable without
recovering the original planning conversation. This repository uses the
[Architecture Decision Records](https://adr.github.io/) approach.

## Lifecycle

Each ADR begins with one of these statuses:

- **Proposed**: under review and not yet the repository direction.
- **Provisional**: selected for a bounded initial evaluation; it must be
  reconsidered against explicit triggers before becoming a general standard.
- **Accepted**: the current repository direction.
- **Superseded**: replaced by a later ADR, which this record links to.
- **Rejected**: considered and intentionally not adopted.

Accepted and provisional ADRs describe the current posture. Either may receive
a dated amendment that corrects facts or clarifies wording without changing the
decision outcome. Amendments must identify what changed and must not silently
replace the original rationale. Editorial revisions that do not change the
decision outcome or material rationale may be made directly. A new, reversed,
or materially changed decision creates a new sequential record and updates the
earlier record's status or related links. Record numbers are never reused or
renumbered.

## Record structure

Each record includes its status, context, decision, alternatives,
consequences, references, and related ADRs. A provisional record also names
its reconsideration triggers. ADRs record durable architectural choices, not
implementation task checklists or mutable operational runbooks.

## Generic framing

Frame every ADR as a reusable rule, independent of the feature, package,
endpoint, or implementation that first prompted it. Do not use Branch Context,
WBS, plans, or other delivery artifacts to define an ADR's purpose or
rationale.

A specific reference is exceptional. Include one only when it is material to
the decision itself, or when a clearly labeled example is necessary because
generic wording cannot express the rule. A convenient example from the first
implementation is not sufficient reason to make it part of an ADR.

## Further reading

These sources provide general background and alternative formats; they do not
replace this repository's ADR conventions.

- [Documenting Architecture Decisions](https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions.html)
  — Michael Nygard's foundational ADR article.
- [MADR](https://adr.github.io/madr/) — a Markdown ADR template and tooling
  reference.

## Index

| ADR | Status | Decision |
| --- | --- | --- |
| [0001](0001-use-static-parser-derived-shell-completion.md) | Accepted | Use static parser-derived shell completion. |
| [0002](0002-use-git-tag-distribution-until-pypi-is-justified.md) | Accepted | Use Git-tag distribution until PyPI is justified. |
