"""Shared read-only consumer audit implementation."""

from __future__ import annotations

import tomllib
from collections import Counter
from pathlib import Path
from typing import Any, Mapping

PROFILE_AGENT_DIRS = {
    "global": Path("config.d/opencode/agents"),
    "agent-core": Path("components/agent-core/.opencode/agents"),
}
SUMMARY_KEYS = ("PASS", "INTENTIONAL_DIFFERENCE", "DIFF", "MISSING")


def parse_frontmatter(path: Path) -> dict[str, Any]:
    """Parse the scalar fields needed by the audit without a YAML dependency."""
    result: dict[str, Any] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return result
    if not lines or lines[0].strip() != "---":
        return result
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if line.startswith((" ", "\t")) or ":" not in line:
            continue
        key, value = line.split(":", 1)
        value = value.strip().strip('"').strip("'")
        if value in {"true", "false"}:
            result[key] = value == "true"
        else:
            result[key] = value
    return result


def _load_agent_core_bindings(consumer_root: Path) -> tuple[dict[str, Any] | None, str | None]:
    fallback_path = consumer_root / "components/agent-core/.automation/model-fallback.toml"
    try:
        with fallback_path.open("rb") as handle:
            parsed = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError):
        return None, f"MISSING UNEXPECTED_DRIFT profile=agent-core fallback_policy={fallback_path}"
    roles = parsed.get("roles", {})
    if not isinstance(roles, dict):
        return {}, None
    return roles, None


def _audit_profile_contract(
    profile: str,
    consumer_root: Path,
    documents: Mapping[str, Mapping[str, Any]],
) -> tuple[list[str], Counter[str]]:
    if profile not in PROFILE_AGENT_DIRS:
        raise ValueError(f"unknown profile: {profile}")

    models = documents["models"]["models"]
    roles = documents["roles"]["roles"]
    fallbacks = documents["fallback"]["fallbacks"]
    lines: list[str] = []
    counts: Counter[str] = Counter()
    bindings: dict[str, Any] | None = None
    if profile == "agent-core":
        bindings, binding_error = _load_agent_core_bindings(consumer_root)
        if binding_error:
            lines.append(binding_error)
            counts["MISSING"] += 1

    agent_dir = consumer_root / PROFILE_AGENT_DIRS[profile]
    if not agent_dir.is_dir():
        lines.append(f"MISSING UNEXPECTED_DRIFT profile={profile} agent_directory={agent_dir}")
        counts["MISSING"] += 1
        return lines, counts

    expected_roles = {role_id for role_id, role in roles.items() if profile in role["profiles"]}
    for role_id in sorted(expected_roles):
        assignment = documents[profile]["assignments"][role_id]
        expected_model = models[assignment["primary_model"]]["id"]
        expected_mode = roles[role_id]["kind"]
        primary_path = agent_dir / f"{role_id}.md"
        primary = parse_frontmatter(primary_path)
        if not primary_path.is_file():
            lines.append(f"MISSING UNEXPECTED_DRIFT profile={profile} role={role_id} agent={role_id}")
            counts["MISSING"] += 1
        else:
            if primary.get("model") != expected_model:
                lines.append(
                    f"DIFF UNEXPECTED_DRIFT profile={profile} role={role_id} primary_model="
                    f"{primary.get('model')!r} expected={expected_model!r}"
                )
                counts["DIFF"] += 1
            else:
                lines.append(f"PASS profile={profile} role={role_id} primary_model={expected_model}")
                counts["PASS"] += 1
            if primary.get("mode") != expected_mode:
                lines.append(
                    f"DIFF UNEXPECTED_DRIFT profile={profile} role={role_id} "
                    f"mode={primary.get('mode')!r} expected={expected_mode!r}"
                )
                counts["DIFF"] += 1
            else:
                lines.append(f"PASS profile={profile} role={role_id} mode={expected_mode}")
                counts["PASS"] += 1

        fallback = fallbacks[role_id]
        fallback_agent = fallback["fallback_agent"]
        expected_fallback_model = models[fallback["target_models"][profile]]["id"]
        fallback_path = agent_dir / f"{fallback_agent}.md"
        fallback_data = parse_frontmatter(fallback_path)
        if not fallback_path.is_file():
            lines.append(
                f"MISSING UNEXPECTED_DRIFT profile={profile} role={role_id} "
                f"fallback_agent={fallback_agent} expected_model={expected_fallback_model}"
            )
            counts["MISSING"] += 1
        else:
            if fallback_data.get("model") != expected_fallback_model:
                lines.append(
                    f"DIFF UNEXPECTED_DRIFT profile={profile} role={role_id} "
                    f"fallback_agent={fallback_agent} model={fallback_data.get('model')!r} "
                    f"expected={expected_fallback_model!r}"
                )
                counts["DIFF"] += 1
            else:
                lines.append(
                    f"PASS profile={profile} role={role_id} fallback_agent={fallback_agent} "
                    f"model={expected_fallback_model}"
                )
                counts["PASS"] += 1
            if fallback_data.get("mode") != expected_mode:
                lines.append(
                    f"DIFF UNEXPECTED_DRIFT profile={profile} role={role_id} "
                    f"fallback_agent={fallback_agent} mode={fallback_data.get('mode')!r} "
                    f"expected={expected_mode!r}"
                )
                counts["DIFF"] += 1
            else:
                lines.append(
                    f"PASS profile={profile} role={role_id} fallback_agent={fallback_agent} "
                    f"mode={expected_mode}"
                )
                counts["PASS"] += 1

        if profile == "agent-core" and bindings is not None:
            binding = bindings.get(role_id)
            if not isinstance(binding, dict):
                lines.append(
                    f"MISSING UNEXPECTED_DRIFT profile=agent-core role={role_id} "
                    "fallback_binding=model-fallback.toml"
                )
                counts["MISSING"] += 1
            else:
                expected_binding = {
                    "primary_agent": role_id,
                    "primary_model": expected_model,
                    "fallback_agents": [fallback_agent],
                    "fallback_models": [expected_fallback_model],
                    "automatic": fallback["automatic"][profile],
                }
                differences = {
                    key: (binding.get(key), value)
                    for key, value in expected_binding.items()
                    if binding.get(key) != value
                }
                if differences:
                    lines.append(
                        f"DIFF UNEXPECTED_DRIFT profile=agent-core role={role_id} "
                        f"fallback_binding={differences!r}"
                    )
                    counts["DIFF"] += 1
                else:
                    lines.append(f"PASS profile=agent-core role={role_id} fallback_binding=model-fallback.toml")
                    counts["PASS"] += 1

    for role_id in sorted(set(roles) - expected_roles):
        forbidden_agents = (role_id, fallbacks[role_id]["fallback_agent"])
        present_agents = [agent for agent in forbidden_agents if (agent_dir / f"{agent}.md").exists()]
        if present_agents:
            for agent in present_agents:
                lines.append(
                    f"DIFF UNEXPECTED_DRIFT profile={profile} role={role_id} "
                    f"agent={agent} expected=absent"
                )
                counts["DIFF"] += 1
        else:
            lines.append(f"INTENTIONAL_DIFFERENCE profile={profile} role={role_id} expected=absent")
            counts["INTENTIONAL_DIFFERENCE"] += 1
    return lines, counts


def _policy_difference_lines(
    documents: Mapping[str, Mapping[str, Any]],
) -> tuple[list[str], Counter[str]]:
    lines: list[str] = []
    counts: Counter[str] = Counter()
    for difference in documents["invariants"].get("intentional_differences", []):
        role_id = difference["role"]
        field = difference["field"]
        global_value = documents["global"]["assignments"][role_id][field]
        agent_core_value = documents["agent-core"]["assignments"][role_id][field]
        lines.append(
            f"INTENTIONAL_DIFFERENCE id={difference['id']} role={role_id} field={field} "
            f"global={global_value} agent-core={agent_core_value}"
        )
        counts["INTENTIONAL_DIFFERENCE"] += 1
    return lines, counts


def audit_profiles(
    consumers: Mapping[str, Path],
    documents: Mapping[str, Mapping[str, Any]],
) -> tuple[list[str], Counter[str]]:
    """Audit one or more explicitly bound profiles with shared accounting."""
    lines: list[str] = []
    counts: Counter[str] = Counter()
    for profile, consumer_root in consumers.items():
        profile_lines, profile_counts = _audit_profile_contract(profile, consumer_root, documents)
        lines.extend(profile_lines)
        counts.update(profile_counts)
    difference_lines, difference_counts = _policy_difference_lines(documents)
    lines.extend(difference_lines)
    counts.update(difference_counts)
    return lines, counts


def audit_profile(
    profile: str,
    consumer_root: Path,
    policy_documents: Mapping[str, Mapping[str, Any]],
) -> tuple[list[str], Counter[str]]:
    """Audit one consumer using an explicit profile; never infer from its path."""
    return audit_profiles({profile: consumer_root}, policy_documents)


def format_summary(counts: Counter[str]) -> str:
    return "SUMMARY " + " ".join(f"{key}={counts[key]}" for key in SUMMARY_KEYS)


def invalid_consumer_roots(consumers: Mapping[str, Path]) -> list[Path]:
    """Return explicitly supplied consumer roots that are not directories."""
    return [path for path in consumers.values() if not path.is_dir()]


def result_exit_code(lines: list[str], counts: Counter[str], strict: bool) -> int:
    """Apply common policy-invalid and strict conformity exit semantics."""
    if any(line.startswith("DIFF POLICY_INVALID ") for line in lines):
        return 1
    if strict and (counts["DIFF"] or counts["MISSING"]):
        return 1
    return 0
