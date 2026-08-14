from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from audit_consumers import audit  # noqa: E402
from validate_policy import load_policy, validate_policy  # noqa: E402


class PolicyContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.docs, cls.parse_errors = load_policy(ROOT)

    def make_consumer_fixture(self, root: Path) -> tuple[Path, Path, Path, Path, Path]:
        dotnix_root = root / "dotnix"
        templates_root = root / "Templates"
        dotnix_agents = dotnix_root / "config.d/opencode/agents"
        templates_agents = templates_root / "components/agent-core/.opencode/agents"
        dotnix_agents.mkdir(parents=True)
        templates_agents.mkdir(parents=True)
        models = self.docs["models"]["models"]
        roles = self.docs["roles"]["roles"]
        fallbacks = self.docs["fallback"]["fallbacks"]
        for profile, directory in (("global", dotnix_agents), ("agent-core", templates_agents)):
            for role, assignment in self.docs[profile]["assignments"].items():
                mode = roles[role]["kind"]
                model = models[assignment["primary_model"]]["id"]
                (directory / f"{role}.md").write_text(
                    f"---\nmode: {mode}\nmodel: {model}\n---\n", encoding="utf-8"
                )
                fallback = fallbacks[role]
                fallback_model = models[fallback["target_models"][profile]]["id"]
                (directory / f"{fallback['fallback_agent']}.md").write_text(
                    f"---\nmode: {mode}\nmodel: {fallback_model}\n---\n", encoding="utf-8"
                )
        binding_path = templates_root / "components/agent-core/.automation/model-fallback.toml"
        binding_path.parent.mkdir(parents=True)
        binding_sections = ["version = 1"]
        for role, assignment in self.docs["agent-core"]["assignments"].items():
            fallback = fallbacks[role]
            primary_model = models[assignment["primary_model"]]["id"]
            fallback_model = models[fallback["target_models"]["agent-core"]]["id"]
            automatic = str(fallback["automatic"]["agent-core"]).lower()
            binding_sections.append(
                f'\n[roles."{role}"]\n'
                f'primary_agent = "{role}"\n'
                f'primary_model = "{primary_model}"\n'
                f'fallback_agents = ["{fallback["fallback_agent"]}"]\n'
                f'fallback_models = ["{fallback_model}"]\n'
                f'automatic = {automatic}\n'
            )
        binding_path.write_text("".join(binding_sections), encoding="utf-8")
        return dotnix_root, templates_root, dotnix_agents, templates_agents, binding_path

    @staticmethod
    def remove_fallback_binding(binding_path: Path, role: str) -> None:
        binding_text = binding_path.read_text(encoding="utf-8")
        start = binding_text.index(f'\n[roles."{role}"]')
        end = binding_text.find("\n[roles.", start + 1)
        if end == -1:
            end = len(binding_text)
        binding_path.write_text(binding_text[:start] + binding_text[end:], encoding="utf-8")

    def test_policy_is_valid(self) -> None:
        self.assertEqual([], validate_policy(ROOT))

    def test_malformed_table_is_reported_without_crashing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            shutil.copytree(ROOT / "policy", root / "policy")
            shutil.copytree(ROOT / "profiles", root / "profiles")
            (root / "policy/roles.toml").write_text('schema_version = 1\nroles = "invalid"\n', encoding="utf-8")
            errors = validate_policy(root)
            self.assertIn("policy/roles.toml: roles must be a table", errors)

    def test_validator_rejects_duplicated_intentional_difference_values(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            shutil.copytree(ROOT / "policy", root / "policy")
            shutil.copytree(ROOT / "profiles", root / "profiles")
            invariants_path = root / "policy/invariants.toml"
            contents = invariants_path.read_text(encoding="utf-8").replace(
                'role = "build"\nfield = "authority"',
                'role = "build"\nfield = "authority"\nglobal = "duplicated-value"',
                1,
            )
            invariants_path.write_text(contents, encoding="utf-8")
            errors = validate_policy(root)
            self.assertTrue(any("canonical values must not be duplicated" in error for error in errors))

    def test_all_model_references_resolve(self) -> None:
        self.assertEqual([], self.parse_errors)
        models = self.docs["models"]["models"]
        for profile in ("global", "agent-core"):
            for assignment in self.docs[profile]["assignments"].values():
                self.assertIn(assignment["primary_model"], models)

    def test_all_fallback_references_resolve(self) -> None:
        models = self.docs["models"]["models"]
        roles = self.docs["roles"]["roles"]
        for fallback in self.docs["fallback"]["fallbacks"].values():
            self.assertIn(fallback["role"], roles)
            for model in fallback["target_models"].values():
                self.assertIn(model, models)

    def test_profile_only_roles_are_not_common(self) -> None:
        task_orchestrator = self.docs["roles"]["roles"]["task-orchestrator"]
        self.assertEqual("AGENT_CORE_ONLY", task_orchestrator["classification"])
        self.assertEqual(["agent-core"], task_orchestrator["profiles"])
        self.assertNotIn("task-orchestrator", self.docs["global"]["assignments"])

    def test_profile_scoping_does_not_force_roles(self) -> None:
        for role_id, role in self.docs["roles"]["roles"].items():
            if role["classification"] == "GLOBAL_ONLY":
                self.assertNotIn(role_id, self.docs["agent-core"]["assignments"])
            if role["classification"] == "AGENT_CORE_ONLY":
                self.assertNotIn(role_id, self.docs["global"]["assignments"])

    def test_plan_fallback_is_common_target_policy(self) -> None:
        plan = self.docs["fallback"]["fallbacks"]["plan"]
        self.assertEqual({"global", "agent-core"}, set(plan["profiles"]))
        self.assertEqual("plan-fallback", plan["fallback_agent"])
        self.assertEqual({"global": "spark", "agent-core": "spark"}, plan["target_models"])

    def test_quota_family_is_defined_once_per_model(self) -> None:
        families = self.docs["models"]["quota_families"]
        for model in self.docs["models"]["models"].values():
            self.assertIsInstance(model["quota_family"], str)
            self.assertIn(model["quota_family"], families)

    def test_current_common_primary_assignments(self) -> None:
        expected = {
            "build": ("sol", "sol"),
            "plan": ("sol", "sol"),
            "architect": ("sol", "sol"),
            "general": ("spark", "luna"),
            "explore": ("spark", "luna"),
            "verifier": ("spark", "spark"),
            "reviewer": ("terra", "terra"),
            "investigator": ("terra", "terra"),
            "security-reviewer": ("terra", "terra"),
            "scout": ("spark", "spark"),
        }
        for role, (global_model, agent_core_model) in expected.items():
            self.assertEqual(global_model, self.docs["global"]["assignments"][role]["primary_model"])
            self.assertEqual(agent_core_model, self.docs["agent-core"]["assignments"][role]["primary_model"])

    def test_intentional_differences_derive_canonical_values(self) -> None:
        declarations = self.docs["invariants"]["intentional_differences"]
        self.assertTrue(all(not ({"global", "agent-core", "classification"} & set(item)) for item in declarations))
        with tempfile.TemporaryDirectory() as temporary:
            dotnix, templates, _, _, _ = self.make_consumer_fixture(Path(temporary))
            lines, counts = audit(dotnix, templates, ROOT)
            self.assertEqual(0, counts["DIFF"])
            self.assertIn(
                "INTENTIONAL_DIFFERENCE id=general-primary-model role=general field=primary_model "
                "global=spark agent-core=luna",
                lines,
            )

    def test_task_orchestrator_global_absence_is_counted_once(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            dotnix, templates, _, _, _ = self.make_consumer_fixture(Path(temporary))
            lines, _ = audit(dotnix, templates, ROOT)
            differences = [
                line
                for line in lines
                if line.startswith("INTENTIONAL_DIFFERENCE") and "role=task-orchestrator" in line
            ]
            self.assertEqual(
                ["INTENTIONAL_DIFFERENCE profile=global role=task-orchestrator expected=absent"],
                differences,
            )

    def test_matching_primary_and_fallback_modes_pass(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            dotnix, templates, _, _, _ = self.make_consumer_fixture(Path(temporary))
            lines, counts = audit(dotnix, templates, ROOT)
            self.assertEqual(0, counts["DIFF"])
            self.assertIn("PASS profile=global role=build mode=primary", lines)
            self.assertIn("PASS profile=global role=general fallback_agent=general-fallback mode=subagent", lines)

    def test_role_mode_mismatch_is_unexpected_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            dotnix, templates, dotnix_agents, _, _ = self.make_consumer_fixture(Path(temporary))
            general_path = dotnix_agents / "general.md"
            general_path.write_text(
                general_path.read_text(encoding="utf-8").replace("mode: subagent", "mode: primary"),
                encoding="utf-8",
            )
            lines, counts = audit(dotnix, templates, ROOT)
            self.assertEqual(1, counts["DIFF"])
            self.assertTrue(
                any(
                    "DIFF UNEXPECTED_DRIFT profile=global role=general mode='primary' expected='subagent'" in line
                    for line in lines
                )
            )

    def test_fallback_mode_mismatch_is_unexpected_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            dotnix, templates, dotnix_agents, _, _ = self.make_consumer_fixture(Path(temporary))
            fallback_path = dotnix_agents / "general-fallback.md"
            fallback_path.write_text(
                fallback_path.read_text(encoding="utf-8").replace("mode: subagent", "mode: primary"),
                encoding="utf-8",
            )
            lines, counts = audit(dotnix, templates, ROOT)
            self.assertEqual(1, counts["DIFF"])
            self.assertTrue(
                any(
                    "DIFF UNEXPECTED_DRIFT profile=global role=general fallback_agent=general-fallback "
                    "mode='primary' expected='subagent'" in line
                    for line in lines
                )
            )

    def test_agent_core_only_fallback_in_global_is_unexpected_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            dotnix, templates, dotnix_agents, _, _ = self.make_consumer_fixture(Path(temporary))
            (dotnix_agents / "task-orchestrator-fallback.md").write_text(
                "---\nmode: subagent\nmodel: openai/gpt-5.6-sol\n---\n", encoding="utf-8"
            )
            lines, counts = audit(dotnix, templates, ROOT)
            self.assertEqual(1, counts["DIFF"])
            self.assertIn(
                "DIFF UNEXPECTED_DRIFT profile=global role=task-orchestrator "
                "agent=task-orchestrator-fallback expected=absent",
                lines,
            )

    def test_agent_core_only_primary_in_global_is_unexpected_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            dotnix, templates, dotnix_agents, _, _ = self.make_consumer_fixture(Path(temporary))
            (dotnix_agents / "task-orchestrator.md").write_text(
                "---\nmode: subagent\nmodel: openai/gpt-5.3-codex-spark\n---\n", encoding="utf-8"
            )
            lines, counts = audit(dotnix, templates, ROOT)
            self.assertEqual(1, counts["DIFF"])
            self.assertIn(
                "DIFF UNEXPECTED_DRIFT profile=global role=task-orchestrator "
                "agent=task-orchestrator expected=absent",
                lines,
            )

    def test_audit_reports_missing_common_plan_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            dotnix, templates, _, templates_agents, binding_path = self.make_consumer_fixture(Path(temporary))
            (templates_agents / "plan-fallback.md").unlink()
            self.remove_fallback_binding(binding_path, "plan")
            lines, counts = audit(dotnix, templates, ROOT)
            self.assertEqual(2, counts["MISSING"])
            self.assertEqual(0, counts["DIFF"])
            self.assertIn(
                "PASS profile=global role=plan fallback_agent=plan-fallback model=openai/gpt-5.3-codex-spark",
                lines,
            )
            self.assertTrue(
                any("MISSING UNEXPECTED_DRIFT" in line and "fallback_agent=plan-fallback" in line for line in lines)
            )
            self.assertTrue(
                any("MISSING UNEXPECTED_DRIFT" in line and "fallback_binding=model-fallback.toml" in line for line in lines)
            )


if __name__ == "__main__":
    unittest.main()
