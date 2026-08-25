# ADR authoring guide

## Durable decision records

- Write ADRs as reusable repository-level decisions. State the enduring rule,
  rationale, alternatives, and consequences rather than the current task or
  implementation slice.
- Frame every ADR independently of the feature, package, endpoint, or
  implementation that first prompted it. Do not use Branch Context, WBS,
  plans, or other delivery artifacts to define its purpose or rationale.
- Include a specific reference only when it is material to the decision, or
  when a clearly labeled example is necessary because generic wording cannot
  express the rule. A convenient first implementation is not enough.
- Use terminology that applies across future uses of the repository. Do not
  make the concrete component, interface, or implementation that first
  prompted a decision the basis of its framing.
- Keep a concrete present-day case out of an ADR unless it is essential to
  define the decision's scope. When essential, describe the category of case
  rather than its current implementation details.
- Put mutable implementation status, acceptance steps, workarounds, and
  follow-up tasks in separate operational documentation, not an ADR. An ADR
  must never name or link to an external working-context root, lane, or plan,
  and must remain self-contained without that context.
- Named technologies, versions, protocols, products, and supporting links may
  remain when they materially explain alternatives, constraints, or rationale.
  Make their role explicit: a reference or candidate does not imply selection
  or rejection. Keep the ADR self-contained; do not create a separate
  evaluation or reference document solely to avoid naming them.

## Record maintenance

- Follow the repository-level ADR lifecycle, numbering, index, and reciprocal
  related-record requirements.
- Before issuing a new ADR number, run `git worktree list --porcelain` from
  the repository root and inspect `docs/adr/[0-9][0-9][0-9][0-9]-*.md` in
  every non-bare worktree of this repository. Treat every discovered number as
  claimed, whether or not its branch has merged, and allocate the integer
  immediately after the highest claim. Stop and resolve an unreadable worktree
  rather than guessing a number.
- When touching an existing ADR, generalize incidental implementation detail
  that no longer helps explain the durable decision.
- Either an accepted or provisional ADR may receive a dated amendment for a
  factual correction or clarification that preserves its decision outcome.
  Place an amendment after the complete section it amends. Do not insert it
  mid-section when later paragraphs remain part of the original decision. Name
  the exact rule or paragraph amended. Editorial revisions that do not change
  the decision outcome or material rationale may be made directly. Create a
  new record for a reversed or materially changed decision.
