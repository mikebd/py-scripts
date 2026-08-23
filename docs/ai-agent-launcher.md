# AI agent launcher

`ai-agent-launcher` creates and runs local AI coding-agent workspaces. The
initial built-in adapter is `codex`; its runtime details remain adapter-owned.

## Install a tagged release

This tool is distributed from Git tags, not PyPI. Install the selected upstream
release with:

```bash
uv tool install "git+https://github.com/mikebd/py-scripts@v0.1.0"
```

For a fork, replace the repository URL and keep the selected tag:

```bash
uv tool install "git+https://github.com/OWNER/py-scripts@v0.1.0"
```

Ensure the UV tool binary directory is on `PATH` with `uv tool update-shell`,
or inspect it with `uv tool dir --bin`. Verify the installed executable with:

```bash
ai-agent-launcher --version
ai-agent-launcher --help
```

To move to a selected newer tag, rerun `uv tool install --reinstall` with that
tag. This replaces the installed tool with the requested source version.

## Test an untagged checkout

For a fast smoke test of the current checkout, run:

```bash
uv run ai-agent-launcher --version
uv run ai-agent-launcher --help
```

To also test an isolated tool installation without creating a Git tag or
replacing the normal installed launcher, use temporary UV directories:

```bash
test_root="$(mktemp -d)"
UV_TOOL_DIR="$test_root/tools" \
UV_TOOL_BIN_DIR="$test_root/bin" \
UV_CACHE_DIR="$test_root/cache" \
uv tool install --no-cache .
"$test_root/bin/ai-agent-launcher" --version
"$test_root/bin/ai-agent-launcher" --help
```

Remove the temporary directory when finished. `make release-check` performs
this installation check automatically from a temporary Git-tagged snapshot of
the current source.

## Configuration

The default configuration path is
`$XDG_CONFIG_HOME/ai-agent-launcher/config.toml`, falling back to
`$HOME/.config/ai-agent-launcher/config.toml`. Generic settings belong in
`[core]`; Codex settings belong in `[agents.codex]`.

Run `ai-agent-launcher --help` for the current launcher, worktree, and runtime
commands. Existing legacy Bash launcher artifacts are not imported; create
new launchers explicitly.

## Release procedure

For a new release version:

1. Update `project.version` in `pyproject.toml`.
2. Run `make release-check`.
3. Commit and push the reviewed product change.
4. Create and push an annotated matching Git tag, for example
   `git tag -a v0.1.0 -m "ai-agent-launcher v0.1.0"` followed by
   `git push origin v0.1.0`.
5. Repeat the install and `--version` smoke test against the public tag in an
   isolated UV tool directory.

No PyPI upload or GitHub Release object is part of this procedure.
