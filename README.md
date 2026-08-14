# OpenCodePolicy

OpenCodePolicy is the machine-readable shared policy and compatibility contract for the OpenCode configurations implemented by [`upiscium/dotnix`](https://github.com/upiscium/dotnix) and [`upiscium/Templates`](https://github.com/upiscium/Templates).

> **OpenCodePolicy does not own the complete OpenCode configuration.**
>
> **It owns shared policy and compatibility contracts.**

`dotnix` and `Templates` remain implementation owners of their respective profiles. This repository is deliberately not a third OpenCode configuration implementation, a file-copy source, or an Agent Core consumer.

## Why this repository exists

The two consumers share role names, model identities, quota-family rules, fallback behavior, and durable safety constraints, while retaining materially different authority and lifecycle semantics. Keeping those contracts only in implementation files makes intentional differences hard to distinguish from drift. OpenCodePolicy provides one reviewable source of truth above both implementations without moving either implementation here.

```text
OpenCodePolicy
    | shared policy / compatibility contract
    +----------------------+----------------------+
    v                                             v
dotnix global profile                     Templates Agent-Core profile
    v                                             v
~/.config/opencode                        repository-local Agent Core
```

There is no dependency from OpenCodePolicy to Templates Agent Core generation or adoption. This repository must remain independently bootstrapped so that `OpenCodePolicy -> Templates -> OpenCodePolicy` cannot arise.

## Ownership boundary

### dotnix owns

- the global generic-repository baseline and safe fallback;
- user/provider credentials and provider configuration;
- Ollama endpoints and models;
- TUI and user or machine preferences;
- global permissions, commands, skills, and complete global agent prompts.

### Templates owns

- repository-local Agent Core implementation and distribution;
- `.automation/**`, `.opencode/**`, `AGENTS.md`, and the root `Justfile`;
- Task lifecycle, Work Units, Task Orchestrator, and guarded Git/GitHub APIs;
- repository policy, adoption, upgrade, `VERSION`, `UPSTREAM`, and Project Adapter;
- complete Agent-Core prompts, commands, and skills.

Neither complete prompt implementations nor command/skill implementations move in Phase 1. OpenCodePolicy does not generate, materialize, synchronize, or modify either consumer.

## Profiles

### Global Profile

`profiles/global.toml` describes the dotnix global user layer. It supports generic repositories without Agent Core. Global `build` can implement and orchestrate, global `plan` remains read-only, and repository-specific lifecycle is outside this profile. Repository-local rules may impose stronger boundaries.

### Agent-Core Profile

`profiles/agent-core.toml` describes the Templates repository-local layer. Repository-local configuration is authoritative; `build` is the Main Orchestrator rather than a direct implementation worker; one Task Orchestrator owns one Task's implementation; and raw Git/GitHub writes are constrained to guarded APIs.

The same role identity does not imply identical prompts, permissions, or authority. `build` and `general` are explicit profile variants. `task-orchestrator` is Agent-Core-only.

## Canonical contract

- `policy/models.toml`: model aliases, exact provider IDs, and quota families. Provider model literals appear only here.
- `policy/roles.toml`: canonical role taxonomy, profile applicability, and primary/subagent classification.
- `policy/fallback.toml`: fallback agents, model aliases, automatic/manual selection, one-retry limit, and failure classification.
- `policy/invariants.toml`: common invariants and value-free declarations of allowed profile differences. Compared values are derived from canonical role/profile data.
- `profiles/*.toml`: profile-specific primary assignments, authority semantics, and ownership.

The target policy defines `plan-fallback` as a **COMMON** capability. dotnix currently conforms. Templates currently lacks the fallback agent and binding; that is unexpected consumer drift, not an intentional profile difference. Phase 1 records but does not repair it.

## Intentionally not canonical

The contract does not canonicalize full permissions, full agent prompts, commands, skills, provider credentials, UI preferences, Task implementation mechanics, Just recipes, or Project Adapter details. Semantic authority can differ by profile even when a role name and model assignment are shared.

## Validate policy

Python 3.11 or newer is required for standard-library `tomllib`.

```sh
python tools/validate_policy.py
python -m unittest discover -s tests -v
```

The validator parses all TOML documents and checks semantic ID uniqueness, model/role/profile references, required fields, model ID syntax, applicability consistency, fallback self-reference, quota-family separation, and role/fallback contradictions.

## Audit consumers

Audit explicit local checkouts of current consumer implementations:

```sh
python tools/audit_consumers.py \
  --dotnix /path/to/dotnix \
  --templates /path/to/Templates
```

The audit is read-only and never repairs consumers. It checks role and fallback existence, model assignments, primary/subagent modes, and Agent-Core fallback bindings. It reports `PASS`, `INTENTIONAL_DIFFERENCE`, `DIFF`, and `MISSING`; unexpected mismatches are additionally labeled `UNEXPECTED_DRIFT`. Add `--strict` when unexpected drift should produce a non-zero exit status.

Consumer repositories are intentionally not cloned by CI. Policy CI therefore remains deterministic when either consumer's `main` branch changes.

## Current consumers

| Consumer | Profile | Implementation owner |
| --- | --- | --- |
| `upiscium/dotnix` | `global` | dotnix |
| `upiscium/Templates` | `agent-core` | Templates |

## Future integration direction

A later phase may add explicit, reviewable consumer alignment or compatibility workflows. Any future materialization must preserve implementation ownership, avoid runtime network dependencies, and prevent dependency cycles. Phase 1 only establishes and audits the contract.
