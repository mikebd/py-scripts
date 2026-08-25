# Scoped ADR authoring guide

These records apply only to `ai-agent-launcher`. Read this file, `README.md`,
and the relevant root ADR guidance in `../../adr/` before creating or changing
a scoped record.

- Follow the root ADR lifecycle, immutable-baseline and amendment practice,
  record structure, generic framing, and reciprocal related-record rules.
- Keep each record within this tool's declared scope. Do not place a
  repository-wide policy here; create or update a root ADR when the rule must
  govern multiple independent tools.
- Before issuing a new number, run `git worktree list --porcelain` from the
  repository root and inspect
  `docs/ai-agent-launcher/adr/[0-9][0-9][0-9][0-9]-*.md` in every non-bare
  worktree. Treat every discovered number as claimed and stop on an unreadable
  worktree rather than guessing.
- Keep concrete branches, work packages, delivery plans, and first
  implementation details out of records unless they are material to the
  decision's scope. The tool may be named to establish scope; frame the rule
  itself in reusable terms.
- Reread changed guidance and records before continuing; they apply
  immediately in the current session.
