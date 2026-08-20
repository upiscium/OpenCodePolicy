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

    def make_consumer(self, root: Path, profile: str, *, with_model_fallback: bool = False) -> Path:
        consumer = root / profile
        agent_dir = {
            "global": consumer / "config.d/opencode/agents",
            "agent-core": consumer / "components/agent-core/.opencode/agents",
        }[profile]
        agent_dir.mkdir(parents=True)
        models = self.documents["models"]["models"]
        roles = self.documents["roles"]["roles"]
        assignments = self.documents[profile]["assignments"]
        for role, assignment in assignments.items():
            mode = roles[role]["kind"]
            model = models[assignment["primary_model"]]["id"]
            (agent_dir / f"{role}.md").write_text(
                f"---\nmode: {mode}\nmodel: {model}\n---\n", encoding="utf-8"
            )

        if profile == "agent-core" and with_model_fallback:
            binding = consumer / "components/agent-core/.automation/model-fallback.toml"
            binding.parent.mkdir(parents=True)
            binding.write_text("version = 1\n", encoding="utf-8")

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
            self.assertIn("PASS profile=global fallback_agents=absent", lines)

    def test_conforming_agent_core_consumer_passes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            consumer = self.make_consumer(Path(temporary), "agent-core")
            lines, counts = audit_profile("agent-core", consumer, self.documents)
            self.assertEqual(0, counts["DIFF"])
            self.assertEqual(0, counts["MISSING"])
            self.assertIn("PASS profile=agent-core role=plan mode=primary", lines)
            self.assertIn("PASS profile=agent-core model_fallback_policy=absent", lines)

    def test_global_model_drift_is_diff(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            consumer = self.make_consumer(Path(temporary), "global")
            plan = consumer / "config.d/opencode/agents/plan.md"
            plan.write_text(plan.read_text().replace("openai/gpt-5.6-sol", "openai/wrong"), encoding="utf-8")
            lines, counts = audit_profile("global", consumer, self.documents)
            self.assertEqual(1, counts["DIFF"])
            self.assertTrue(any("role=plan primary_model" in line for line in lines))

    def test_global_mode_drift_is_diff(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            consumer = self.make_consumer(Path(temporary), "global")
            general = consumer / "config.d/opencode/agents/general.md"
            general.write_text(general.read_text().replace("mode: subagent", "mode: primary"), encoding="utf-8")
            lines, counts = audit_profile("global", consumer, self.documents)
            self.assertEqual(1, counts["DIFF"])
            self.assertTrue(any("role=general mode='primary' expected='subagent'" in line for line in lines))

    def test_global_fallback_agent_residue_is_diff(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            consumer = self.make_consumer(Path(temporary), "global")
            (consumer / "config.d/opencode/agents/plan-fallback.md").write_text(
                "---\nmode: subagent\nmodel: openai/gpt-5.6-sol\n---\n", encoding="utf-8"
            )
            lines, counts = audit_profile("global", consumer, self.documents)
            self.assertEqual(1, counts["DIFF"])
            self.assertTrue(any("fallback_residue=forbidden" in line for line in lines))

    def test_agent_core_fallback_residue_is_diff(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            consumer = self.make_consumer(Path(temporary), "agent-core")
            (consumer / "components/agent-core/.opencode/agents/verifier-fallback.md").write_text(
                "---\nmode: subagent\nmodel: openai/gpt-5.6-sol\n---\n", encoding="utf-8"
            )
            lines, counts = audit_profile("agent-core", consumer, self.documents)
            self.assertEqual(1, counts["DIFF"])
            self.assertTrue(any("fallback_residue=forbidden" in line for line in lines))

    def test_arbitrary_fallback_agent_residue_is_diff(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            consumer = self.make_consumer(Path(temporary), "global")
            (consumer / "config.d/opencode/agents/foo-fallback.md").write_text(
                "---\nmode: subagent\nmodel: openai/gpt-5.6-sol\n---\n", encoding="utf-8"
            )
            lines, counts = audit_profile("global", consumer, self.documents)
            self.assertEqual(1, counts["DIFF"])
            self.assertTrue(any("agent=foo-fallback" in line for line in lines))

    def test_agent_core_model_fallback_policy_residue_is_diff(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            consumer = self.make_consumer(Path(temporary), "agent-core", with_model_fallback=True)
            lines, counts = audit_profile("agent-core", consumer, self.documents)
            self.assertEqual(1, counts["DIFF"])
            self.assertTrue(any("model_fallback_policy=model-fallback.toml" in line for line in lines))

    def test_missing_primary_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            consumer = self.make_consumer(Path(temporary), "global")
            (consumer / "config.d/opencode/agents/plan.md").unlink()
            _, counts = audit_profile("global", consumer, self.documents)
            self.assertEqual(1, counts["MISSING"])

    def test_unknown_profile_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(ValueError, "unknown profile"):
                audit_profile("unknown", Path(temporary), self.documents)
            result = self.run_cli("audit-consumer", "--profile", "unknown", "--consumer", temporary)
            self.assertNotEqual(0, result.returncode)

    def test_validate_command(self) -> None:
        result = self.run_cli("validate")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("VALID policy contract", result.stdout)

    def test_audit_consumer_global_command(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            consumer = self.make_consumer(Path(temporary), "global")
            result = self.run_cli("audit-consumer", "--profile", "global", "--consumer", str(consumer), "--strict")
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

    def test_strict_failure_is_nonzero_for_fallback_residue(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            consumer = self.make_consumer(Path(temporary), "global")
            (consumer / "config.d/opencode/agents/foo-fallback.md").write_text(
                "---\nmode: subagent\nmodel: openai/gpt-5.6-sol\n---\n", encoding="utf-8"
            )
            result = self.run_cli("audit-consumer", "--profile", "global", "--consumer", str(consumer), "--strict")
            self.assertEqual(1, result.returncode)
            self.assertIn("DIFF=1", result.stdout)

    def test_malformed_arguments_fail(self) -> None:
        result = self.run_cli("audit-consumer", "--profile", "global")
        self.assertNotEqual(0, result.returncode)
        result = self.run_cli("audit-consumer", "--profile", "global", "--consumer", "/definitely/missing")
        self.assertNotEqual(0, result.returncode)

    def test_legacy_dual_cli_rejects_invalid_consumer_path(self) -> None:
        result = self.run_legacy_dual_cli("--dotnix", "/definitely/missing-dotnix", "--templates", "/definitely/missing-templates")
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

    def test_intentional_differences_are_unchanged(self) -> None:
        identifiers = {item["id"] for item in self.documents["invariants"]["intentional_differences"]}
        self.assertEqual({"build-authority", "general-authority"}, identifiers)

    def test_read_only_consumer_tree_is_supported(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            consumer = self.make_consumer(Path(temporary), "global")
            paths = sorted(consumer.rglob("*"), key=lambda p: len(p.parts), reverse=True)
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
