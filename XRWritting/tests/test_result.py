import copy
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location("check_result", Path(__file__).parents[1] / "scripts/check_result.py")
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)


def example():
    before = "We evaluate Model-A on 10 cases. It may improve Dice from 0.80 to 0.82 [1]."
    after = "On 10 cases, we evaluate Model-A. It may improve Dice from 0.80 to 0.82 [1]."
    source = {"schema_version": 1, "max_rounds": 3, "units": [{"id": "P01", "text": before, "protected_spans": ["Model-A", "[1]"]}]}
    result = {"schema_version": 1, "status": "passed", "judgment": "部分符合",
              "units": [{"id": "P01", "revised": after}], "original_sha256": checker.digest(before),
              "final_sha256": checker.digest(after), "style_revision_rounds": 1,
              "issues": [{"unit_id": "P01", "kind": "style", "rule_id": "XR03", "observation": "句序可调整"}],
              "changes": [{"unit_id": "P01", "before": before, "after": after, "reason": "明确测试范围，保留推测"}],
              "text_readable_batches": [{"status": "passed", "revision_rounds": 0, "final_sha256": checker.digest(after)}],
              "review": {k: {"status": "pass", "evidence": "合成测试中的记录字段，不代表真实语义审核"} for k in ["semantic_fidelity", "style", "readability", "requirements", "claim_strength"]}, "unresolved": []}
    return source, result


def update_text(result, after):
    result["units"][0]["revised"] = after
    result["changes"][0]["after"] = after
    result["final_sha256"] = checker.digest(after)
    result["text_readable_batches"][-1]["final_sha256"] = checker.digest(after)


class RecordTests(unittest.TestCase):
    def test_valid_record(self):
        self.assertEqual([], checker.validate(*example()))

    def test_changed_number_blocked(self):
        source, result = example()
        update_text(result, result["units"][0]["revised"].replace("0.82", "0.92"))
        self.assertTrue(any("numerical" in e for e in checker.validate(source, result)))

    def test_citation_and_name_blocked(self):
        for span in ["[1]", "Model-A"]:
            source, result = example()
            update_text(result, result["units"][0]["revised"].replace(span, "other"))
            self.assertTrue(any("protected" in e for e in checker.validate(source, result)))

    def test_missing_unit_blocked(self):
        source, result = example()
        result["units"].append(copy.deepcopy(result["units"][0]))
        self.assertTrue(checker.validate(source, result))

    def test_omitted_changes_blocked(self):
        source, result = example()
        result["changes"] = []
        self.assertTrue(any("manifest" in e for e in checker.validate(source, result)))

    def test_fake_change_blocked(self):
        source, result = example()
        update_text(result, source["units"][0]["text"])
        self.assertTrue(any("manifest" in e for e in checker.validate(source, result)))

    def test_actual_diff_blocked(self):
        source, result = example()
        result["changes"][0]["after"] = "fake"
        self.assertTrue(any("before/after" in e for e in checker.validate(source, result)))

    def test_iteration_limits(self):
        for rounds in [4, -1, True]:
            source, result = example()
            result["style_revision_rounds"] = rounds
            self.assertTrue(checker.validate(source, result))

    def test_zero_round_edit_blocked(self):
        source, result = example()
        result["style_revision_rounds"] = 0
        self.assertTrue(checker.validate(source, result))

    def test_language_limits(self):
        source, result = example()
        result["text_readable_batches"] *= 3
        self.assertTrue(checker.validate(source, result))
        source, result = example()
        result["text_readable_batches"][0]["revision_rounds"] = 4
        self.assertTrue(checker.validate(source, result))

    def test_stale_language_hash_blocked(self):
        source, result = example()
        result["text_readable_batches"][0]["final_sha256"] = "old"
        self.assertTrue(checker.validate(source, result))

    def test_source_issue_not_passed(self):
        source, result = example()
        result["issues"].append({"unit_id": "P01", "kind": "content", "observation": "证据不足", "state": "unresolved"})
        self.assertTrue(checker.validate(source, result))

    def test_semantic_drift_requires_actual_review(self):
        # Intentionally shows the checker cannot establish semantic fidelity.
        source, result = example()
        update_text(result, result["units"][0]["revised"].replace("may improve", "certainly improves"))
        self.assertEqual([], checker.validate(source, result))

    def test_unchanged_valid(self):
        source, result = example()
        update_text(result, source["units"][0]["text"])
        result["changes"] = []
        result["issues"] = []
        result["judgment"] = "基本符合"
        result["style_revision_rounds"] = 0
        self.assertEqual([], checker.validate(source, result))

    def test_cjk_numbers_are_protected(self):
        source, result = example()
        before = "在相同10例上，均值为0.80。"
        after = "在相同10例上，均值为0.90。"
        source["units"][0].update(text=before, protected_spans=[])
        result["original_sha256"] = checker.digest(before)
        result["changes"][0]["before"] = before
        update_text(result, after)
        self.assertTrue(any("numerical" in e for e in checker.validate(source, result)))

    def test_repeated_name_can_be_merged(self):
        source, result = example()
        before = "Model-A is evaluated. Model-A obtains 0.80."
        after = "Model-A is evaluated and obtains 0.80."
        source["units"][0].update(text=before, protected_spans=["Model-A"])
        result["original_sha256"] = checker.digest(before)
        result["changes"][0]["before"] = before
        update_text(result, after)
        self.assertEqual([], checker.validate(source, result))


if __name__ == "__main__":
    unittest.main()
