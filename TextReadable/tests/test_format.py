import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location("check_format", Path(__file__).resolve().parents[1] / "scripts/check_format.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
validate = module.validate

class FormatTests(unittest.TestCase):
    def setUp(self):
        self.requirements = {"format": {"document_headings": ["## 事件正文"], "unit_level": 3,
            "sections": [{"heading": "### " + name, "required_markers": ["**影响：**"]} for name in ("A", "B")]}}
        self.text = "## 事件正文\n### A\n**影响：** 原文已有影响。[来源](https://example.org)\n### B\n**影响：** 本次尚未核实影响。\n"

    def test_complete(self):
        self.assertEqual(validate(self.text, self.requirements)["status"], "pass")

    def test_absent_contract_preserves_behavior(self):
        for value in (None, {}, {"content": [{"id": "a", "scope": "all", "requirement": "内容要求"}]}):
            self.assertEqual(validate("普通文本", value)["status"], "not_applicable")

    def test_second_event_missing(self):
        self.assertEqual(validate(self.text.replace("**影响：** 本次尚未核实影响。", ""), self.requirements)["status"], "fail")

    def test_empty_or_placeholder(self):
        for replacement in ("", "{{影响}}", "TODO"):
            text = self.text.replace("本次尚未核实影响。", replacement)
            self.assertEqual(validate(text, self.requirements)["status"], "fail")

    def test_code_and_comment_cannot_supply_field(self):
        for replacement in ("```\n**影响：** 内容\n```", "<!-- **影响：** 内容 -->"):
            text = self.text.replace("**影响：** 本次尚未核实影响。", replacement)
            self.assertEqual(validate(text, self.requirements)["status"], "fail")

    def test_extra_or_missing_event(self):
        for text in (self.text + "### C\n**影响：** 内容", self.text.split("### B")[0]):
            self.assertEqual(validate(text, self.requirements)["status"], "fail")

    def test_duplicate_field_or_heading(self):
        for text in (self.text + "**影响：** 重复", self.text + "### A\n**影响：** 内容"):
            self.assertEqual(validate(text, self.requirements)["status"], "fail")

    def test_bad_contract_fails_closed(self):
        for value in ([], {"formt": {}}, {"format": {"sections": [{}]}}, {"content": [{}]}):
            self.assertEqual(validate(self.text, value)["status"], "fail")

    def test_prose_does_not_satisfy_label(self):
        text = self.text.replace("**影响：** 本次尚未核实影响。", "该事件已经结束。")
        self.assertEqual(validate(text, self.requirements)["status"], "fail")

    def test_empty_table_cell(self):
        contract = {"format": {"sections": [{"heading": "## 摘要", "required_markers": ["| 影响 |"]}]}}
        self.assertEqual(validate("## 摘要\n| 影响 | |", contract)["status"], "fail")

    def test_later_section_cannot_supply_missing_field(self):
        text = self.text.replace("**影响：** 本次尚未核实影响。", "") + "## 其他\n**影响：** 内容"
        self.assertEqual(validate(text, self.requirements)["status"], "fail")

    def test_structure_does_not_claim_semantic_coverage(self):
        text = self.text.replace("本次尚未核实影响。", "影响很大。")
        self.assertEqual(validate(text, self.requirements)["status"], "pass")
        # This result must still fail the separate content review.

if __name__ == "__main__":
    unittest.main()
