# AI agent launcher

`ai-agent-launcher` creates and runs local AI coding-agent workspaces. The
current supported adapter is `codex`; its runtime details remain adapter-owned.

Its component-specific durable choices are recorded in the
[AI agent launcher decision records](adr/README.md).
Repository-wide completion and distribution policy remains in
[the repository ADR index](../adr/README.md).

## Agent runtime activation

When configuring an AI coding agent to discover and select this command, use the
[AI agent runtime activation guide](https://github.com/mikebd/ai-agent-skills/blob/main/shared/references/agent-runtime/AI_AGENT_LAUNCHER.md).
It governs source selection, when an agent should prefer this command, and how
it uses runtime `--version` and `--help`. It is the canonical activation
policy; this guide remains the command's installation and usage reference.

## Install the tagged distribution for persistent launchers

`ai-agent-launcher` is a command-line entry point of the `mikebd-py-scripts`
distribution. That distribution follows the repository's [Git-tag distribution
default](../adr/0002-use-git-tag-distribution-until-pypi-is-justified.md), not
PyPI. A generated launcher is a persistent shell shim: direct execution
requires `ai-agent-launcher` to be available on that process's `PATH`. Install
the selected upstream distribution release with:

```bash
uv tool install "git+https://github.com/mikebd/py-scripts@v0.1.1"
```

For a fork, replace the repository URL and keep the selected tag:

```bash
uv tool install "git+https://github.com/OWNER/py-scripts@v0.1.1"
```

Ensure the UV tool binary directory is on `PATH`. You may run
`uv tool update-shell` to update shell startup configuration, or inspect the
directory with `uv tool dir --bin` and add it through your own shell setup.
Verify the installed executable with:

```bash
ai-agent-launcher --version
ai-agent-launcher --help
```

To move to a selected newer tag, rerun `uv tool install --reinstall` with that
tag. This replaces the installed distribution with the requested source
version.

## Direct CLI smoke test from an untagged checkout

Use `uv run` for direct, one-shot commands from the current checkout:

```bash
uv run ai-agent-launcher --version
uv run ai-agent-launcher --help
```

Running `uv run ai-agent-launcher launcher create ...` does not install the
command into the later generated launcher's `PATH`. Use the temporary
installation below to test persistent-launcher behavior without replacing the
normal installed distribution.

## Temporarily install an untagged checkout

To test an installation candidate without creating a Git tag or replacing the
normal installed launcher, use isolated UV directories:

```bash
test_root="$(mktemp -d)"
UV_TOOL_DIR="$test_root/tools" \
UV_TOOL_BIN_DIR="$test_root/bin" \
UV_CACHE_DIR="$test_root/cache" \
uv tool install --no-cache .
export PATH="$test_root/bin:$PATH"
ai-agent-launcher --version
ai-agent-launcher --help
```

Keep the temporary directory and its `PATH` entry for any generated-launcher
smoke test. Remove the directory after restoring `PATH`. `make release-check`
validates the current release-note entry and performs the corresponding
temporary Git-tagged distribution installation plus `--version` and `--help`
checks automatically; it does not create or execute a generated launcher.

## Inspect a generated launcher

Generated launchers contain encoded metadata so their shell shims remain small
and do not interpret state as shell code. Inspect a launcher through the tool:

```bash
ai-agent-launcher launcher describe --launcher /path/to/launcher
```

The command reports the artifact's format, selected agent, workspace, session
state, preparation helper, persisted metadata extensions, local
writable directories, and the best-effort effective writable-directory set for
the current machine. It does not execute the launcher, invoke an agent, run
preparation, or create cache directories. It reads the current configuration
and asks the selected adapter to resolve workspace support paths such as
`.context`, Git metadata, and available tool caches. If a configuration,
worktree, Git, or tool lookup is unavailable, it still reports stored metadata
and prints a note for the unavailable effective-directory source. Newly
generated launchers include this command as a comment beside their encoded
metadata.

For one-shot diagnosis from an untagged checkout, use the same command through
`uv run`:

```bash
uv run ai-agent-launcher launcher describe --launcher /path/to/launcher
```

This diagnoses a launcher artifact but does not make that launcher executable;
persistent launchers still require an installed `ai-agent-launcher` on `PATH`.
When a generated launcher runs, it changes to its stored worktree before
delegating to the installed runtime. This keeps the launched agent and terminal
multiplexer panes created from it in the selected worktree.

## Create a worktree from another checkout

`worktree new` normally selects the repository containing the current working
directory. Use `--source-worktree-dir` to select a different existing Git
worktree instead:

```bash
ai-agent-launcher worktree new \
  --agent codex \
  --source-worktree-dir /path/to/source-checkout \
  --worktree-dir /path/to/new-worktree \
  --branch feature/example
```

The selected path chooses the repository only. The new worktree starts at that
repository's primary-worktree `HEAD`, just as it does without the option. Use
`--from REF` when a different start commit is required; the selected linked
worktree's branch is never used implicitly.

## Configuration

The default configuration path is
`$XDG_CONFIG_HOME/ai-agent-launcher/config.toml`, falling back to
`$HOME/.config/ai-agent-launcher/config.toml`. Generic settings belong in
`[core]`; Codex settings belong in `[agents.codex]`.

Run `ai-agent-launcher --help` for the current launcher, worktree, and runtime
commands. Existing legacy Bash launcher artifacts are not imported; create
new launchers explicitly.

### Git metadata access

The core default is conservative:

```toml
[core]
default_git_metadata_access = "worktree"
```

`worktree` lets the Codex adapter add the selected worktree's Git directory,
but does not automatically grant access to its shared Git common directory.
Use `shared` only when the launched agent needs to write shared metadata such
as refs or other data shared by linked worktrees:

```toml
[core]
default_git_metadata_access = "shared"
```

The configuration default applies to direct `run` invocations and newly
created launchers. New launchers persist their effective selection explicitly.
Override it for one launcher without changing the default:

```bash
ai-agent-launcher launcher create ... --git-metadata-access shared
ai-agent-launcher worktree new ... --git-metadata-access worktree
```

`launcher fork` and `launcher adopt` inherit the source launcher's policy
unless given the same explicit option. Older launchers without this persisted
setting continue with implicit `worktree` access and are not rewritten merely
by inspection, execution, or pinning. Use `launcher describe` to verify the
stored and effective policy.

The conservative default follows the safety rationale in the
[AI-agent runtime Git-permissions guidance](https://github.com/mikebd/ai-agent-skills/blob/main/shared/references/agent-runtime/DEVELOPER_INSTRUCTIONS.md#git-permissions).
That guidance is a reference for this default, not a restriction on users who
choose the less strict `shared` policy for an individual launcher or their
configuration.

### Persisted sandbox settings

Set an initial persisted sandbox mode while creating a launcher with
`--sandbox-mode`. `launcher create`, `launcher fork`, `launcher adopt`,
`worktree new`, and `worktree stack` support this option. It accepts the
sandbox modes supported by the selected agent adapter; the current Codex
adapter supports `read-only`, `workspace-write`, and `danger-full-access`.

`launcher fork` and `launcher adopt` copy the source launcher's local writable
directories and persisted sandbox mode unless explicitly overridden. Their
repeatable `--remove-dir` option removes inherited launcher-local directories;
an unmatched path warns but does not block creation. It cannot remove
directories configured under `[core].writable_dirs` or directories added
automatically by the selected adapter.

Use `launcher sandbox` to update an existing launcher's Codex sandbox mode,
add or remove launcher-local writable directories, or combine those updates
atomically. Its shorter `--mode` option is local to that sandbox subcommand:

```bash
ai-agent-launcher launcher sandbox \
  --launcher /path/to/launcher \
  --mode workspace-write \
  --add-dir /path/to/writable-directory \
  --remove-dir /path/to/no-longer-needed-directory
```

`--add-dir` and `--remove-dir` are repeatable. Added directories must already
exist and are stored as canonical absolute paths. Removal accepts an absolute
path even when the stored directory has since been deleted, so it can repair
stale launcher metadata.

At least one update is required: use `--mode`, one or more `--add-dir` or
`--remove-dir` values, or a combination. `--mode` is optional when only
changing directories. A directory requested for removal but not stored in
launcher-local metadata produces a warning and does not prevent other updates.
The command preserves the launcher's session and other persisted settings, does
not start an agent, and affects only future launcher invocations. Without a
persisted sandbox-mode override, a launcher continues to use its current
`[agents.codex].sandbox` configuration value. Use `launcher describe` to
inspect a persisted override under `codex.sandbox` and launcher-local
directories.

## Codex-specific behavior

The Codex adapter adds writable directories that are needed by its
local sandbox and the tools it may run. They are in addition to the generic
`[core].writable_dirs` and launcher-local `--add-dir` inputs.

| Source | Inclusion condition | Runtime behavior |
| --- | --- | --- |
| `[core].writable_dirs` | Each configured path, except one that strictly contains automatic Git metadata for the launched worktree | Must already be an existing directory. The Codex adapter omits that overlapping configured root to avoid a Codex sandbox conflict with the launched worktree's automatic Git metadata. Other configured roots remain available for unrelated worktrees. |
| Launcher-local `--add-dir` entries | Each path stored in launcher metadata | Must already be an existing directory. |
| `<worktree>/.context` | The directory exists | Added when present. |
| Git directory | The launcher worktree has resolvable Git metadata | Adds the worktree-specific directory from `git rev-parse --git-dir`. |
| Git common directory | The launcher's persisted Git metadata access is `shared` | Adds the shared directory from `git rev-parse --git-common-dir`. |
| Go build cache | `go` is on `PATH` and `go env GOCACHE` is not `off` | The reported cache directory is created when needed. |
| Go module cache | `go` is on `PATH`; path from `go env GOMODCACHE` | The reported cache directory is created when needed. |
| GolangCI-Lint cache | `golangci-lint` is on `PATH` | Uses `$GOLANGCI_LINT_CACHE`, then `$XDG_CACHE_HOME/golangci-lint`, then `$HOME/.cache/golangci-lint`; the directory is created when needed. |

Duplicates are removed. The Codex adapter also omits a configured root that
would strictly contain automatic Git metadata for the launched worktree; this
avoids a Codex sandbox conflict with the launched worktree's automatic Git
metadata while retaining configured roots for unrelated worktrees. Runtime
ordering remains adapter-owned: configured directories, launcher-local
directories, optional `.context`, Git metadata, then available tool caches.
`ai-agent-launcher launcher describe` presents a sorted, best-effort view for
diagnosis; it does not create caches, start an agent, or run launcher
preparation. Unavailable or omitted configuration, worktree, Git, or tool
sources appear as notes beside the stored launcher metadata.

Only the configured and launcher-local inputs are agent-neutral. The automatic
additions above are current Codex behavior and are not a contract for future
agent adapters.

## Shell completion

Generate static completion code for the shell named by `$SHELL`:

```bash
ai-agent-launcher completion
```

Select a shell explicitly when saving a generated script or when `$SHELL` does
not name the current shell:

```bash
ai-agent-launcher completion --shell zsh
```

The command supports the shells exposed by its installed Shtab version; run
`ai-agent-launcher completion --help` for the current list. It writes only to
standard output; it does not modify shell configuration. Use the explicit form
for persistent setup. The patterns below cover the currently available shells:

| Shell | Activation pattern |
| --- | --- |
| Bash | Use `source <(ai-agent-launcher completion --shell bash)` for the current session. Add that line to `$HOME/.bashrc` for persistent setup. |
| Fish | Write `ai-agent-launcher completion --shell fish` to `$HOME/.config/fish/completions/ai-agent-launcher.fish`; Fish loads that directory automatically. |
| Tcsh | Use `ai-agent-launcher completion --shell tcsh \| source /dev/stdin` for the current session. Add that line to `$HOME/.cshrc` for persistent setup. |
| Zsh | Write `ai-agent-launcher completion --shell zsh` to `$HOME/.zsh/completions/_ai-agent-launcher`, add `$HOME/.zsh/completions` to `fpath` before `compinit`, then run `autoload -Uz compinit && compinit`. |

Create a destination directory before writing a generated file. Zsh completion
files must retain the underscore-prefixed executable name.

### Zsh with Oh My Zsh

[Oh My Zsh](https://ohmyz.sh/) already adds `$ZSH_CUSTOM/completions` to `fpath`
before running `compinit`. In an Oh My Zsh shell, install the generated file
there, remove the existing completion cache, then reload:

```zsh
mkdir -p "$ZSH_CUSTOM/completions"
ai-agent-launcher completion --shell zsh > "$ZSH_CUSTOM/completions/_ai-agent-launcher"
rm -f -- "$ZSH_COMPDUMP"
omz reload
```

`$ZSH_CUSTOM` defaults to `$ZSH/custom`. Removing `$ZSH_COMPDUMP` ensures that
the reloaded completion index includes the newly generated file.

## Release procedure

For a new distribution release:

1. Maintain the matching Draft entry in the root [changelog](../../CHANGELOG.md)
   while the release scope changes.
2. Finalize that entry with the release date, affected command-line entry
   points, and externally meaningful changes.
3. Update `project.version` in `pyproject.toml`.
4. Run `make release-check`.
5. Commit and push the reviewed product change.
6. Create and push an annotated matching Git tag, for example
   `git tag -a v0.1.2 -m "mikebd-py-scripts v0.1.2"` followed by
   `git push origin v0.1.2`.
7. Repeat the install and `--version` smoke test against the public tag in an
   isolated UV tool directory.

No PyPI upload or GitHub Release object is part of this procedure.
