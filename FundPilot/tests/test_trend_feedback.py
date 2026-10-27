"""Synthetic bridge -> unchanged scorer -> correct/incorrect case feedback."""
import csv
from datetime import date, timedelta
import json
from pathlib import Path
import tempfile
import unittest

from fundpilot import llm_loop
from fundpilot.trend_feedback import freeze_bridge_cards, feedback_from_scores
from fundpilot.upstream_bridge import digest, write_new
from test_frozen_topdown import _fixture


class TrendFeedbackTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.graph, cutoff = _fixture(self.root)
        response_path = self.graph / "response-3.json"
        response = json.loads(response_path.read_bytes())
        content = json.loads(response["content"])
        content["forecasts"][0]["direction"] = "up"
        content["forecasts"][0]["p_up"] = .8
        content["forecasts"][1]["direction"] = "down"
        response["content"] = json.dumps(content)
        response_path.write_text(json.dumps(response))
        result_path = self.graph / "result.json"
        result = json.loads(result_path.read_bytes())
        result["research_state"]["investment_plan"] = response["content"]
        result_path.write_text(json.dumps(result))
        self.claims = content["forecasts"]
        self.fund = "SYNTHETIC:001"
        self.days = [(date(2020, 1, 1) + timedelta(days=i)).isoformat() for i in range(45)]
        binding = {
            "reviewed": True, "review_ref": "SYNTHETIC mapping, no real evidence",
            "bridge_input_sha256": digest((self.graph / "input.json").read_bytes()),
            "manager_response_sha256": digest(response_path.read_bytes()),
            "cutoff": cutoff.isoformat(), "fund": self.fund, "origin": "2020-01-03",
            "mode": "synthetic", "source_ids_by_horizon": {str(h): ["S1"] for h in (1, 5, 20)},
        }
        write_new(self.root / "binding.json", binding)
        write_new(self.root / "sources.json", [{
            "id": "S1", "url": "https://example.org/synthetic-only",
            "raw_sha256": "0" * 64, "reviewed": True,
            "published_at": "2020-01-01T00:00:00Z",
            "retrieved_at": "2020-01-01T01:00:00Z",
            "known_available_at": "2020-01-01T01:00:00Z",
        }])
        write_new(self.root / "calendar.json", {
            "reviewed": True, "evidence_ref": "SYNTHETIC daily dates, not market sessions",
            "dates": {self.fund: self.days}})
        self.nav = self.root / "nav.csv"
        with self.nav.open("w") as f:
            writer = csv.writer(f)
            writer.writerow(["fund", "date", "nav", "retrieved_at",
                             "known_available_at", "assumed_available_at"])
            for i, day in enumerate(self.days):
                at = day + "T18:00:00Z"
                writer.writerow([self.fund, day, 100 + i, at, at, at])
        self.nav.chmod(0o600)
        self.manifest()

    def manifest(self):
        path = self.root / "nav-manifest.json"
        data = {"sha256": digest(self.nav.read_bytes()), "reviewed": True,
                "reviewed_by": "SYNTHETIC fixture", "evidence_refs": ["synthetic"]}
        if path.exists():
            path.write_text(json.dumps(data))
        else:
            write_new(path, data)

    def freeze(self):
        return freeze_bridge_cards(
            research_root=self.graph, binding_path=self.root / "binding.json",
            sources_path=self.root / "sources.json", calendar_path=self.root / "calendar.json",
            output=self.root / "frozen")

    def score(self, name="scored"):
        return llm_loop.score(self.root / "frozen", self.nav,
                              self.root / "nav-manifest.json", llm_loop.now(),
                              self.root / name)

    def feedback(self, name="feedback", scored="scored"):
        return feedback_from_scores(frozen_root=self.root / "frozen",
                                    scored_root=self.root / scored, output=self.root / name)

    def test_original_trends_score_and_both_outcomes_become_zero_weight_candidates(self):
        original = {p.name: p.read_bytes() for p in self.graph.iterdir()}
        self.freeze()
        mapped = json.loads((self.root / "frozen/cards.json").read_bytes())
        self.assertEqual([r["bridge_forecast"] for r in mapped["cards"]], self.claims)
        self.assertEqual(mapped["generated_at"], "2026-10-27T00:00:01+00:00")
        self.assertNotIn("numeric_schema", mapped)
        self.assertNotIn("numeric_forecast", mapped["cards"][0])
        self.assertEqual(mapped["cards"][0]["bridge_forecast"]["p_up"], .8)
        self.score()
        result = self.feedback()
        self.assertEqual(result["counts"],
                         {"correct": 1, "incorrect": 1, "abstained": 1, "pending": 0, "missing": 0})
        self.assertEqual({r["outcome"] for r in result["experience_candidates"]},
                         {"correct", "incorrect"})
        for row in result["experience_candidates"]:
            self.assertEqual(row["experience"]["state"], "candidate")
            self.assertEqual(row["experience"]["weight"], 0)
            self.assertTrue(row["counterevidence"])
        self.assertTrue(all(c["attribution"]["cause"] == "unknown" for c in result["cases"]))
        self.assertFalse(result["automatic_promotion"])
        self.assertFalse(result["forecasting_skill_proven"])
        self.assertEqual(original, {p.name: p.read_bytes() for p in self.graph.iterdir()})

    def test_missing_truth_is_not_a_wrong_prediction_or_success(self):
        self.freeze()
        body = self.nav.read_text().splitlines()
        self.nav.write_text("\n".join(l for l in body if ",2020-01-04," not in l) + "\n")
        self.manifest()
        self.score()
        result = self.feedback()
        self.assertEqual(result["counts"]["missing"], 1)
        self.assertEqual(result["counts"]["correct"], 0)
        self.assertEqual(len(result["experience_candidates"]), 1)
        self.assertEqual(result["experience_candidates"][0]["outcome"], "incorrect")

    def test_immature_and_uncovered_targets_remain_pending(self):
        path = self.root / "calendar.json"
        calendar = json.loads(path.read_bytes())
        calendar["dates"][self.fund] = self.days[:3] + ["2099-01-01"]
        path.write_text(json.dumps(calendar))
        self.freeze()
        self.score()
        result = self.feedback()
        self.assertEqual(result["counts"]["pending"], 3)
        self.assertEqual(result["experience_candidates"], [])
        self.assertTrue(all(c["actual_direction"] is None for c in result["cases"]))

    def test_future_source_and_wrong_origin_fail_before_new_frozen_directory(self):
        path = self.root / "sources.json"
        sources = json.loads(path.read_bytes())
        sources[0]["known_available_at"] = "2020-02-01T00:00:00Z"
        path.write_text(json.dumps(sources))
        with self.assertRaisesRegex(ValueError, "future evidence"):
            self.freeze()
        self.assertFalse((self.root / "frozen").exists())

    def test_identity_or_original_hash_cannot_be_substituted(self):
        path = self.root / "binding.json"
        initial = json.loads(path.read_bytes())
        for updates in ({"fund": "ANOTHER"}, {"manager_response_sha256": "0" * 64},
                        {"bridge_input_sha256": "0" * 64}, {"reviewed": False},
                        {"origin": "2020-01-04"}):
            path.write_text(json.dumps({**initial, **updates}))
            with self.assertRaises(ValueError):
                self.freeze()
            self.assertFalse((self.root / "frozen").exists())

    def test_forecast_citation_mapping_required_for_every_horizon(self):
        path = self.root / "binding.json"
        binding = json.loads(path.read_bytes())
        binding["source_ids_by_horizon"].pop("20")
        path.write_text(json.dumps(binding))
        with self.assertRaisesRegex(ValueError, "every horizon"):
            self.freeze()

    def test_synthetic_source_cannot_be_relabelled_actual_or_prospective(self):
        path = self.root / "binding.json"
        binding = json.loads(path.read_bytes())
        for mode in ("prospective", "retrospective"):
            binding["mode"] = mode
            path.write_text(json.dumps(binding))
            with self.assertRaisesRegex(ValueError, "same-producer"):
                self.freeze()

    def test_score_manifest_cannot_refer_to_other_frozen_input(self):
        self.freeze()
        self.score()
        path = self.root / "scored/manifest.json"
        manifest = json.loads(path.read_bytes())
        manifest["frozen_receipt_sha256"] = "0" * 64
        path.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, "exact frozen"):
            self.feedback()

    def test_omitted_case_or_changed_direction_is_rejected_even_with_result_hash(self):
        self.freeze()
        self.score()
        path = self.root / "scored/results.json"
        manifest_path = self.root / "scored/manifest.json"
        original = json.loads(path.read_bytes())
        for mutation in ("omit", "direction", "hit"):
            result = json.loads(json.dumps(original))
            if mutation == "omit":
                result["tape"].pop()
            elif mutation == "direction":
                result["tape"][0]["llm_direction"] = "down"
            else:
                result["tape"][0]["llm_hit"] = False
            path.write_text(json.dumps(result))
            manifest = json.loads(manifest_path.read_bytes())
            manifest["results_sha256"] = digest(path.read_bytes())
            manifest_path.write_text(json.dumps(manifest))
            with self.assertRaises(ValueError):
                self.feedback()

    def test_bridge_copy_tamper_rejected_and_old_outputs_not_overwritten(self):
        self.freeze()
        self.score()
        self.feedback()
        before = (self.root / "feedback/feedback.json").read_bytes()
        with self.assertRaises(FileExistsError):
            self.feedback()
        self.assertEqual(before, (self.root / "feedback/feedback.json").read_bytes())
        path = self.root / "frozen/bridge-manager.json"
        path.write_text(path.read_text() + " ")
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            self.feedback("new-feedback")


if __name__ == "__main__":
    unittest.main()
