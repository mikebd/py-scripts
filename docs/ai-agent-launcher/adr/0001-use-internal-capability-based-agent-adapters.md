# 0001: Use internal capability-based agent adapters

## Status

Accepted

## Context

An AI-agent workspace tool coordinates worktree handling, generated launcher
artifacts, configuration, and safety checks while different agent CLIs use
different invocation arguments, writable-directory mechanisms, and session
semantics. Treating those differences as generic core behavior would either
couple the core to a particular agent or require a lowest-common-denominator
contract that does not describe real integrations.

The tool needs a boundary that allows additional built-in integrations without
promising an external extension ABI before one is justified.

## Decision

Keep agent-neutral orchestration in the core and represent agent-specific
behavior through internal, capability-based adapters. The core owns workspace
and generated-launcher lifecycle, shared configuration loading, validation,
and safety checks. Adapters own agent command construction, environment,
writable-directory mechanics, and agent session discovery and lifecycle.

The core treats an agent-associated session reference as opaque. An adapter
advertises only the capabilities it implements, so a caller cannot assume that
all integrations expose the same session operations.

The adapter registry is built into and controlled by this tool. It does not
perform runtime discovery or define a public third-party plugin interface.
Adding an adapter is a repository-owned change with contract coverage for its
declared capabilities.

## Alternatives considered

- Put each agent CLI's behavior directly in the core.
- Define one universal command, writable-directory, and session contract for
  every agent.
- Publish a dynamic third-party plugin ABI and discover integrations at
  runtime.

## Consequences

- Agent-specific behavior remains isolated from shared lifecycle and safety
  logic.
- A future integration can add only the capabilities it supports without
  weakening the core model.
- External plugins are intentionally unsupported until a separate decision
  establishes their compatibility, discovery, and security model.
- Adapter implementations need focused contract tests in addition to shared
  lifecycle coverage.

## References

None.

## Related ADRs

None.
