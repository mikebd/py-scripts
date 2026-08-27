# Changelog

This file records externally meaningful changes in tagged `mikebd-py-scripts`
distribution releases. Entries are newest first. Each entry identifies whether
it applies repository-wide, to one or more command-line entry points, or both.

Draft entries are updated as their release scope changes. Published entries
may be corrected when needed.

## [v0.1.2] - 2026-08-26

### Scope

- `ai-agent-launcher`

### Added

- `worktree new --source-worktree-dir` selects a Git repository without
  requiring the command to run from that checkout.
- Launcher-creating commands accept `--sandbox-mode`; `launcher fork` and
  `launcher adopt` can also add or remove inherited launcher-local writable
  directories. `launcher sandbox` updates those settings on an existing
  launcher.
- Generated launchers change to their selected worktree before delegating to
  the installed runtime, so terminal multiplexer panes inherit that directory.

### Removed

- Launcher creation no longer accepts `--marker`. Existing v1 launcher
  metadata that contains a marker remains supported but is ignored and removed
  when the launcher is rewritten.

### Fixed

- The Codex adapter omits a configured writable root when it would overlap
  automatic Git metadata for the launched worktree, avoiding a Codex sandbox
  conflict with that metadata while retaining configured roots for unrelated
  worktrees.

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
