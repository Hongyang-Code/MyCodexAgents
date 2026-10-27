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
        write_new(protocol, {"synthetic": True, "scope": "trend diagnostic"})
        write_new(evidence, {"synthetic": True, "fund": "000051/A/CNY"})
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
            } for path in (protocol, evidence)],
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


if __name__ == "__main__":
    unittest.main()
