#!/usr/bin/env python3
"""Read-only parity audit for dotnix and Templates OpenCode consumers."""

from __future__ import annotations

import argparse
import sys
import tomllib
from collections import Counter
from pathlib import Path
from typing import Any

from validate_policy import ROOT, load_policy, validate_policy

CONSUMERS = {
    "global": Path("config.d/opencode/agents"),
    "agent-core": Path("components/agent-core/.opencode/agents"),
}


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


def audit(dotnix: Path, templates: Path, policy_root: Path = ROOT) -> tuple[list[str], Counter[str]]:
    validation_errors = validate_policy(policy_root)
    if validation_errors:
        return [f"DIFF POLICY_INVALID {error}" for error in validation_errors], Counter(DIFF=len(validation_errors))
    docs, _ = load_policy(policy_root)
    models = docs["models"]["models"]
    roles = docs["roles"]["roles"]
    fallbacks = docs["fallback"]["fallbacks"]
    profiles = {"global": dotnix, "agent-core": templates}
    lines: list[str] = []
    counts: Counter[str] = Counter()
    templates_bindings: dict[str, Any] | None = None
    templates_fallback_path = templates / "components/agent-core/.automation/model-fallback.toml"
    try:
        with templates_fallback_path.open("rb") as handle:
            parsed_fallback = tomllib.load(handle)
        parsed_roles = parsed_fallback.get("roles", {})
        templates_bindings = parsed_roles if isinstance(parsed_roles, dict) else {}
    except (OSError, tomllib.TOMLDecodeError):
        lines.append(
            f"MISSING UNEXPECTED_DRIFT profile=agent-core fallback_policy={templates_fallback_path}"
        )
        counts["MISSING"] += 1

    for profile_id, consumer_root in profiles.items():
        agent_dir = consumer_root / CONSUMERS[profile_id]
        if not agent_dir.is_dir():
            lines.append(f"MISSING UNEXPECTED_DRIFT profile={profile_id} agent_directory={agent_dir}")
            counts["MISSING"] += 1
            continue
        expected_roles = {role_id for role_id, role in roles.items() if profile_id in role["profiles"]}
        for role_id in sorted(expected_roles):
            assignment = docs[profile_id]["assignments"][role_id]
            expected_model = models[assignment["primary_model"]]["id"]
            primary_path = agent_dir / f"{role_id}.md"
            primary = parse_frontmatter(primary_path)
            if not primary_path.is_file():
                lines.append(f"MISSING UNEXPECTED_DRIFT profile={profile_id} role={role_id} agent={role_id}")
                counts["MISSING"] += 1
            elif primary.get("model") != expected_model:
                lines.append(
                    f"DIFF UNEXPECTED_DRIFT profile={profile_id} role={role_id} primary_model="
                    f"{primary.get('model')!r} expected={expected_model!r}"
                )
                counts["DIFF"] += 1
            else:
                lines.append(f"PASS profile={profile_id} role={role_id} primary_model={expected_model}")
                counts["PASS"] += 1

            fallback = fallbacks[role_id]
            fallback_agent = fallback["fallback_agent"]
            expected_fallback_model = models[fallback["target_models"][profile_id]]["id"]
            fallback_path = agent_dir / f"{fallback_agent}.md"
            fallback_data = parse_frontmatter(fallback_path)
            if not fallback_path.is_file():
                lines.append(
                    f"MISSING UNEXPECTED_DRIFT profile={profile_id} role={role_id} "
                    f"fallback_agent={fallback_agent} expected_model={expected_fallback_model}"
                )
                counts["MISSING"] += 1
            elif fallback_data.get("model") != expected_fallback_model:
                lines.append(
                    f"DIFF UNEXPECTED_DRIFT profile={profile_id} role={role_id} fallback_agent={fallback_agent} "
                    f"model={fallback_data.get('model')!r} expected={expected_fallback_model!r}"
                )
                counts["DIFF"] += 1
            else:
                lines.append(
                    f"PASS profile={profile_id} role={role_id} fallback_agent={fallback_agent} "
                    f"model={expected_fallback_model}"
                )
                counts["PASS"] += 1

            if profile_id == "agent-core" and templates_bindings is not None:
                binding = templates_bindings.get(role_id)
                if not isinstance(binding, dict):
                    lines.append(
                        f"MISSING UNEXPECTED_DRIFT profile=agent-core role={role_id} "
                        "fallback_binding=model-fallback.toml"
                    )
                    counts["MISSING"] += 1
                else:
                    expected_automatic = fallback["automatic"][profile_id]
                    expected_binding = {
                        "primary_agent": role_id,
                        "primary_model": expected_model,
                        "fallback_agents": [fallback_agent],
                        "fallback_models": [expected_fallback_model],
                        "automatic": expected_automatic,
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

        forbidden_roles = set(roles) - expected_roles
        for role_id in sorted(forbidden_roles):
            if (agent_dir / f"{role_id}.md").exists():
                lines.append(f"DIFF UNEXPECTED_DRIFT profile={profile_id} role={role_id} expected=absent")
                counts["DIFF"] += 1
            else:
                lines.append(f"INTENTIONAL_DIFFERENCE profile={profile_id} role={role_id} expected=absent")
                counts["INTENTIONAL_DIFFERENCE"] += 1

    for variant in docs["invariants"].get("profile_variants", []):
        lines.append(
            f"INTENTIONAL_DIFFERENCE id={variant['id']} field={variant['field']} "
            f"global={variant['global']} agent-core={variant['agent-core']}"
        )
        counts["INTENTIONAL_DIFFERENCE"] += 1
    return lines, counts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dotnix", type=Path, required=True)
    parser.add_argument("--templates", type=Path, required=True)
    parser.add_argument("--strict", action="store_true", help="return non-zero for unexpected drift")
    args = parser.parse_args()
    lines, counts = audit(args.dotnix.resolve(), args.templates.resolve())
    for line in lines:
        print(line)
    print("SUMMARY " + " ".join(f"{key}={counts[key]}" for key in ("PASS", "INTENTIONAL_DIFFERENCE", "DIFF", "MISSING")))
    if args.strict and (counts["DIFF"] or counts["MISSING"]):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
