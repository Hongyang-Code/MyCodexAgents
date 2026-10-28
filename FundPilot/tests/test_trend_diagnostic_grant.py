"""Synthetic authorization fixtures only; no model, source, or evaluation calls."""
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from fundpilot.durable_budget import DurableBudget
from fundpilot.trend_diagnostic_grant import grant
from fundpilot.trend_scope_audit import audit
from fundpilot.trend_scope_evidence import register
from fundpilot.diagnostic_grant import verify_bindings
from fundpilot.upstream_bridge import now, write_new


class TrendDiagnosticGrantTests(unittest.TestCase):
    def fixture(self, root):
        legacy = root / "legacy.sqlite"
        history = [{
            "attempted_at": now(),
            "counts_toward_next_7_day_change_budget": True,
        }] * 2
        DurableBudget.create(
            legacy,
            run_id="SYNTHETIC_LEGACY",
            used=dict(source=None, retry=None, llm=None, prediction_batch=None),
            candidate_history=history,
        )
        protocol = root / "protocol.json"
        evidence = root / "000051.json"
        manifest = root / "input.json"
        write_new(protocol, {"synthetic": True, "scope": "trend diagnostic"})
        write_new(manifest, {
            "synthetic": True,
            "used": {"source": 3},
            "reservations": [
                {"id": f"trend-source-{index:02d}", "kind": "source"}
                for index in range(1, 4)
            ],
        })
        write_new(evidence, {
            "synthetic": True,
            "fund": "000051/A/CNY",
            "information_cutoff": "2026-07-31T21:30:00+08:00",
            "market_report": "SYNTHETIC qualified transport input",
            "fundamentals_report": "SYNTHETIC qualified transport input",
        })
        approval = root / "approval.json"
        write_new(approval, {
            "approval_id": "SYNTHETIC_TREND_DIAGNOSTIC",
            "authority_legacy_path": str(legacy),
            "answer": "批准这一批趋势诊断",
            "question": "SYNTHETIC exact bounded scope",
            "source": "SYNTHETIC fixture, not user authorization",
            "approved_at": now(),
            "legacy_sha256": hashlib.sha256(legacy.read_bytes()).hexdigest(),
            "bindings": [{
                "path": str(path),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            } for path in (protocol, manifest, evidence)],
            "funds": ["000051/A/CNY", "004042/A/CNY", "000071/A/CNY"],
            "horizons": [1, 5, 20],
            "information_cutoff": "2026-07-31T21:30:00+08:00",
            "scope": {
                "funds": 3, "llm": 12, "source": 12,
                "evaluations": 1, "candidate": 0, "trades": 0,
            },
            "used": {
                "source": 3, "retry": 0, "llm": 0,
                "prediction_batch": 0, "evaluations": 0,
            },
        })
        return legacy, approval, evidence

    def test_concurrent_claims_share_one_scope_without_touching_legacy(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            legacy, approval, _ = self.fixture(root)
            original = legacy.read_bytes()
            command = [sys.executable, "-m", "fundpilot.trend_diagnostic_grant",
                       "--legacy", str(legacy), "--approval", str(approval)]
            processes = [subprocess.Popen(command, stdout=subprocess.PIPE,
                                          stderr=subprocess.PIPE, text=True)
                         for _ in range(13)]
            results = [(p.communicate(timeout=30), p.returncode) for p in processes]
            paths = [json.loads(out[0])["budget"] for out, code in results if code == 0]
            self.assertGreaterEqual(len(paths), 1)
            self.assertEqual(len(set(paths)), 1)
            self.assertEqual(legacy.read_bytes(), original)
            self.assertEqual(grant(legacy, approval).path, Path(paths[0]))

    def test_used_sources_are_preserved_and_only_remaining_nine_can_reserve(self):
        with tempfile.TemporaryDirectory() as td:
            legacy, approval, _ = self.fixture(Path(td))
            budget = grant(legacy, approval)
            for index in range(9):
                budget.require(f"source-{index}", "source")
            self.assertEqual(budget.reserve("source-10", "source"), "skip_partial")
            seed = budget.snapshot()["seed"]
            self.assertEqual(seed["used"]["source"], 3)
            self.assertIsNone(seed["diagnostic_grant"]["legacy_cumulative_used"]["source"])

    def test_partial_completed_responses_allow_one_fixed_evaluation(self):
        with tempfile.TemporaryDirectory() as td:
            legacy, approval, _ = self.fixture(Path(td))
            budget = grant(legacy, approval)
            budget.require("batch", "prediction_batch")
            for index in range(3):
                request = f"request-{index}"
                budget.require(request, "llm")
                budget.require(f"response-{index}", "checkpoint_resume", parent=request)
            budget.require("evaluation", "diagnostic_evaluation", parent="batch")
            self.assertEqual(
                budget.reserve("evaluation-2", "diagnostic_evaluation", parent="batch"),
                "skip_partial",
            )
            for kind in ("candidate", "comparison_arm", "evaluation"):
                self.assertEqual(budget.reserve("blocked-" + kind, kind), "skip_partial")

    def test_evaluation_waits_for_each_reserved_response_and_llm_cap_is_twelve(self):
        with tempfile.TemporaryDirectory() as td:
            legacy, approval, _ = self.fixture(Path(td))
            budget = grant(legacy, approval)
            budget.require("batch", "prediction_batch")
            budget.require("request-0", "llm")
            self.assertEqual(
                budget.reserve("early-evaluation", "diagnostic_evaluation", parent="batch"),
                "skip_partial",
            )
            budget.require("response-0", "checkpoint_resume", parent="request-0")
            for index in range(1, 12):
                budget.require(f"request-{index}", "llm")
                budget.require(f"response-{index}", "checkpoint_resume",
                               parent=f"request-{index}")
            self.assertEqual(budget.reserve("request-12", "llm"), "skip_partial")

    def test_copy_or_changed_binding_cannot_issue_fresh_quota(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            legacy, approval, evidence = self.fixture(root)
            grant(legacy, approval)
            evidence.write_text("changed")
            with self.assertRaisesRegex(ValueError, "binding"):
                grant(legacy, approval)
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            legacy, approval, _ = self.fixture(root)
            copied = root / "copied"
            copied.mkdir(mode=0o700)
            shutil.copy2(legacy, copied / legacy.name)
            with self.assertRaisesRegex(ValueError, "canonical"):
                grant(copied / legacy.name, approval)

    def test_non_executable_bound_input_is_rejected_before_claim(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            legacy, approval, evidence = self.fixture(root)
            write_new(root / "batch-manifest.json", {
                "schema": "fundpilot.trend-diagnostic-input.v1",
                "funds": ["000051/A/CNY", "004042/A/CNY", "000071/A/CNY"],
            })
            data = json.loads(approval.read_text())
            data["bindings"] = [{
                "path": str(root / "batch-manifest.json"),
                "sha256": hashlib.sha256(
                    (root / "batch-manifest.json").read_bytes()
                ).hexdigest(),
            }]
            approval.unlink()
            write_new(approval, data)
            with self.assertRaisesRegex(ValueError, "executable"):
                grant(legacy, approval)
            self.assertFalse((root / "diagnostic-grants.sqlite").exists())

    def test_ready_scope_audit_is_read_only(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            legacy, approval, _ = self.fixture(root)
            budget = grant(legacy, approval)
            before = {
                path: path.read_bytes()
                for path in (legacy, approval, budget.path,
                             root / "diagnostic-grants.sqlite")
            }
            result = audit(legacy, approval)
            self.assertEqual(result["status"], "ready")
            self.assertTrue(result["bridge_start_allowed"])
            self.assertEqual(result["operations"], 0)
            self.assertEqual(result["audit_mutations"], 0)
            self.assertEqual(
                before,
                {path: path.read_bytes() for path in before},
            )

    def test_append_only_derived_evidence_uses_existing_sources(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            legacy, approval, _ = self.fixture(root)
            budget = grant(legacy, approval)
            derived = root / "004042-derived.json"
            write_new(derived, {"fund": "004042/A/CNY",
                "information_cutoff": "2026-07-31T21:30:00+08:00",
                "market_report": "SYNTHETIC derived evidence",
                "fundamentals_report": "SYNTHETIC derived evidence"})
            result = register(legacy, approval, derived,
                ["trend-source-01", "trend-source-02", "trend-source-03"])
            self.assertEqual(result["new_source_attempts"], 0)
            self.assertEqual(budget.snapshot()["operations"], [])
            verify_bindings(budget.snapshot()["seed"], evidence_path=derived,
                input_sha256=hashlib.sha256(derived.read_bytes()).hexdigest())
            self.assertEqual(audit(legacy, approval)["derived_evidence_count"], 1)

    def test_derived_evidence_rejects_unpaid_source_and_conflict(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            legacy, approval, _ = self.fixture(root)
            grant(legacy, approval)
            derived = root / "004042-derived.json"
            payload = {"fund": "004042/A/CNY",
                "information_cutoff": "2026-07-31T21:30:00+08:00",
                "market_report": "SYNTHETIC derived evidence",
                "fundamentals_report": "SYNTHETIC derived evidence"}
            write_new(derived, payload)
            with self.assertRaisesRegex(ValueError, "charged"):
                register(legacy, approval, derived, ["unpaid-source"])
            register(legacy, approval, derived, ["trend-source-01"])
            derived.unlink(); payload["market_report"] = "CHANGED"; write_new(derived, payload)
            with self.assertRaisesRegex(ValueError, "registered|conflicting"):
                register(legacy, approval, derived, ["trend-source-01"])

    def test_derived_evidence_rejects_out_of_scope_fund(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            legacy, approval, _ = self.fixture(root)
            grant(legacy, approval)
            derived = root / "outside.json"
            write_new(derived, {"fund": "999999/A/CNY",
                "information_cutoff": "2026-07-31T21:30:00+08:00",
                "market_report": "SYNTHETIC", "fundamentals_report": "SYNTHETIC"})
            with self.assertRaisesRegex(ValueError, "outside approved"):
                register(legacy, approval, derived, ["trend-source-01"])


if __name__ == "__main__":
    unittest.main()
