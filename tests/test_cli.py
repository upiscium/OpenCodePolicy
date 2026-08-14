from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
sys.path.insert(0, str(TOOLS))

from audit_consumers import audit  # noqa: E402
from policy_audit import audit_profile, result_exit_code  # noqa: E402
from validate_policy import load_policy  # noqa: E402


class ConsumerAuditCliTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.documents, errors = load_policy(ROOT)
        if errors:
            raise AssertionError(errors)

    def make_consumer(self, root: Path, profile: str) -> Path:
        consumer = root / profile
        agent_dirs = {
            "global": consumer / "config.d/opencode/agents",
            "agent-core": consumer / "components/agent-core/.opencode/agents",
        }
        agent_dir = agent_dirs[profile]
        agent_dir.mkdir(parents=True)
        models = self.documents["models"]["models"]
        roles = self.documents["roles"]["roles"]
        fallbacks = self.documents["fallback"]["fallbacks"]
        for role, assignment in self.documents[profile]["assignments"].items():
            mode = roles[role]["kind"]
            model = models[assignment["primary_model"]]["id"]
            (agent_dir / f"{role}.md").write_text(
                f"---\nmode: {mode}\nmodel: {model}\n---\n", encoding="utf-8"
            )
            fallback = fallbacks[role]
            fallback_model = models[fallback["target_models"][profile]]["id"]
            (agent_dir / f"{fallback['fallback_agent']}.md").write_text(
                f"---\nmode: {mode}\nmodel: {fallback_model}\n---\n", encoding="utf-8"
            )

        if profile == "agent-core":
            binding = consumer / "components/agent-core/.automation/model-fallback.toml"
            binding.parent.mkdir(parents=True)
            sections = ["version = 1"]
            for role, assignment in self.documents[profile]["assignments"].items():
                fallback = fallbacks[role]
                primary_model = models[assignment["primary_model"]]["id"]
                fallback_model = models[fallback["target_models"][profile]]["id"]
                automatic = str(fallback["automatic"][profile]).lower()
                sections.append(
                    f'\n[roles."{role}"]\n'
                    f'primary_agent = "{role}"\n'
                    f'primary_model = "{primary_model}"\n'
                    f'fallback_agents = ["{fallback["fallback_agent"]}"]\n'
                    f'fallback_models = ["{fallback_model}"]\n'
                    f'automatic = {automatic}\n'
                )
            binding.write_text("".join(sections), encoding="utf-8")
        return consumer

    def run_cli(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(TOOLS / "opencode_policy.py"), *arguments],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

    def run_legacy_dual_cli(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(TOOLS / "audit_consumers.py"), *arguments],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_conforming_global_consumer_passes_without_second_checkout(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            consumer = self.make_consumer(root, "global")
            self.assertFalse((root / "agent-core").exists())
            lines, counts = audit_profile("global", consumer, self.documents)
            self.assertEqual(0, counts["DIFF"])
            self.assertEqual(0, counts["MISSING"])
            self.assertIn("PASS profile=global role=plan mode=primary", lines)
            self.assertTrue(any("id=general-primary-model" in line for line in lines))

    def test_conforming_agent_core_consumer_passes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            consumer = self.make_consumer(Path(temporary), "agent-core")
            lines, counts = audit_profile("agent-core", consumer, self.documents)
            self.assertEqual(0, counts["DIFF"])
            self.assertEqual(0, counts["MISSING"])
            self.assertIn("PASS profile=agent-core role=plan fallback_binding=model-fallback.toml", lines)
            self.assertTrue(any("id=general-primary-model" in line for line in lines))

    def test_global_model_drift_is_diff(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            consumer = self.make_consumer(Path(temporary), "global")
            plan = consumer / "config.d/opencode/agents/plan.md"
            plan.write_text(plan.read_text().replace("openai/gpt-5.6-sol", "openai/wrong"), encoding="utf-8")
            lines, counts = audit_profile("global", consumer, self.documents)
            self.assertEqual(1, counts["DIFF"])
            self.assertTrue(any("role=plan primary_model" in line for line in lines))

    def test_global_fallback_residue_is_diff(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            consumer = self.make_consumer(Path(temporary), "global")
            residue = consumer / "config.d/opencode/agents/task-orchestrator-fallback.md"
            residue.write_text("---\nmode: subagent\nmodel: openai/gpt-5.6-sol\n---\n", encoding="utf-8")
            lines, counts = audit_profile("global", consumer, self.documents)
            self.assertEqual(1, counts["DIFF"])
            self.assertTrue(any("agent=task-orchestrator-fallback expected=absent" in line for line in lines))

    def test_agent_core_binding_drift_is_diff(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            consumer = self.make_consumer(Path(temporary), "agent-core")
            binding = consumer / "components/agent-core/.automation/model-fallback.toml"
            text = binding.read_text(encoding="utf-8")
            start = text.index('[roles."plan"]')
            end = text.index("\n[roles.", start + 1)
            section = text[start:end].replace("automatic = false", "automatic = true")
            binding.write_text(text[:start] + section + text[end:], encoding="utf-8")
            lines, counts = audit_profile("agent-core", consumer, self.documents)
            self.assertEqual(1, counts["DIFF"])
            self.assertTrue(any("role=plan fallback_binding" in line for line in lines))

    def test_missing_fallback_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            consumer = self.make_consumer(Path(temporary), "global")
            (consumer / "config.d/opencode/agents/plan-fallback.md").unlink()
            _, counts = audit_profile("global", consumer, self.documents)
            self.assertEqual(1, counts["MISSING"])

    def test_unknown_profile_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(ValueError, "unknown profile"):
                audit_profile("unknown", Path(temporary), self.documents)
            result = self.run_cli(
                "audit-consumer", "--profile", "unknown", "--consumer", temporary
            )
            self.assertNotEqual(0, result.returncode)

    def test_validate_command(self) -> None:
        result = self.run_cli("validate")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("VALID policy contract", result.stdout)

    def test_audit_consumer_global_command(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            consumer = self.make_consumer(Path(temporary), "global")
            result = self.run_cli(
                "audit-consumer", "--profile", "global", "--consumer", str(consumer), "--strict"
            )
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertIn("DIFF=0 MISSING=0", result.stdout)

    def test_audit_consumer_agent_core_command(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            consumer = self.make_consumer(Path(temporary), "agent-core")
            result = self.run_cli(
                "audit-consumer", "--profile", "agent-core", "--consumer", str(consumer), "--strict"
            )
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertIn("DIFF=0 MISSING=0", result.stdout)

    def test_strict_failure_is_nonzero(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            consumer = self.make_consumer(Path(temporary), "global")
            (consumer / "config.d/opencode/agents/plan-fallback.md").unlink()
            result = self.run_cli(
                "audit-consumer", "--profile", "global", "--consumer", str(consumer), "--strict"
            )
            self.assertEqual(1, result.returncode)
            self.assertIn("MISSING=1", result.stdout)

    def test_malformed_arguments_fail(self) -> None:
        result = self.run_cli("audit-consumer", "--profile", "global")
        self.assertNotEqual(0, result.returncode)
        result = self.run_cli(
            "audit-consumer", "--profile", "global", "--consumer", "/definitely/missing"
        )
        self.assertNotEqual(0, result.returncode)

    def test_legacy_dual_cli_rejects_invalid_consumer_path(self) -> None:
        result = self.run_legacy_dual_cli(
            "--dotnix", "/definitely/missing-dotnix", "--templates", "/definitely/missing-templates"
        )
        self.assertEqual(2, result.returncode)

    def test_policy_invalid_result_is_unconditionally_nonzero(self) -> None:
        self.assertEqual(
            1,
            result_exit_code(["DIFF POLICY_INVALID malformed"], {"DIFF": 1, "MISSING": 0}, False),
        )

    def test_dual_audit_regression(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            global_consumer = self.make_consumer(root, "global")
            agent_core_consumer = self.make_consumer(root, "agent-core")
            _, counts = audit(global_consumer, agent_core_consumer, ROOT)
            self.assertEqual(0, counts["DIFF"])
            self.assertEqual(0, counts["MISSING"])

    def test_plan_fallback_remains_conforming(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for profile in ("global", "agent-core"):
                consumer = self.make_consumer(root, profile)
                lines, counts = audit_profile(profile, consumer, self.documents)
                self.assertEqual(0, counts["DIFF"])
                self.assertEqual(0, counts["MISSING"])
                self.assertTrue(any("role=plan fallback_agent=plan-fallback" in line for line in lines))

    def test_intentional_differences_are_unchanged(self) -> None:
        identifiers = {
            item["id"] for item in self.documents["invariants"]["intentional_differences"]
        }
        self.assertEqual(
            {
                "build-authority",
                "general-authority",
                "general-primary-model",
                "explore-primary-model",
            },
            identifiers,
        )
        task_orchestrator = self.documents["roles"]["roles"]["task-orchestrator"]
        self.assertEqual(["agent-core"], task_orchestrator["profiles"])

    def test_read_only_consumer_tree_is_supported(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            consumer = self.make_consumer(Path(temporary), "global")
            paths = sorted(consumer.rglob("*"), key=lambda path: len(path.parts), reverse=True)
            try:
                for path in paths:
                    path.chmod(0o555 if path.is_dir() else 0o444)
                consumer.chmod(0o555)
                _, counts = audit_profile("global", consumer, self.documents)
                self.assertEqual(0, counts["DIFF"])
                self.assertEqual(0, counts["MISSING"])
            finally:
                consumer.chmod(0o755)
                for path in reversed(paths):
                    if path.exists():
                        path.chmod(0o755 if path.is_dir() else 0o644)


if __name__ == "__main__":
    unittest.main()
