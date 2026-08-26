# Changelog

This file records externally meaningful changes in tagged `mikebd-py-scripts`
distribution releases. Entries are newest first. Each entry identifies whether
it applies repository-wide, to one or more command-line entry points, or both.

Draft entries are updated as their release scope changes. Published entries
may be corrected when needed.

## [v0.1.2] - Draft

### Scope

- `ai-agent-launcher`

### Added

- `worktree new --source-worktree-dir` selects a Git repository without
  requiring the command to run from that checkout.
- `launcher sandbox` persists a Codex sandbox-mode override and can add or
  remove launcher-local writable directories on an existing launcher.

## [v0.1.1] - 2026-08-26

### Scope

- `ai-agent-launcher`

### Added

- Root command help and installation documentation link to the AI-agent
  runtime activation guide.

## [v0.1.0] - 2026-08-25

### Scope

- `ai-agent-launcher`

### Added

- Initial Codex-backed workspace launcher, with generated-launcher lifecycle,
  Git-worktree creation, XDG configuration, static shell completion, and
  Git-tagged installation support.
