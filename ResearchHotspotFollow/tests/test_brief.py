import importlib.util
from pathlib import Path
import unittest
ROOT=Path(__file__).resolve().parents[2]
def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
brief=load('brief',ROOT/'ResearchHotspotFollow/scripts/check_brief.py')
shared=load('shared',ROOT/'TextReadable/scripts/check_format.py')
ENTRY="### [P01] [Synthetic Paper](https://example.org/paper)\n\n**基本信息：** 作者：Synthetic｜发表：测试｜等级：不适用｜日期：2026-09-01，测试版｜已读：合成摘要\n\n"+"\n\n".join('- **'+f+'：** '+('建议略读，合成测试。' if f=='阅读建议' else '合成内容，仅供结构测试。') for f in brief.FIELDS)
def document(entry=ENTRY):
    return '# 合成测试\n\n'+'\n\n'.join('## '+g+'\n\n'+(entry if i==0 else '本次未检出符合条件的论文，范围为合成测试。') for i,g in enumerate(brief.GROUPS))+'\n\n## 覆盖与限制\n\n非真实报告。\n'
class BriefTests(unittest.TestCase):
    def test_windows_newlines(self): self.assertEqual(brief.validate(document().replace('\n','\r\n'))['status'],'pass')
    def test_valid(self): self.assertEqual(brief.validate(document())['status'],'pass')
    def test_missing_each_field(self):
        for field in brief.FIELDS:
            with self.subTest(field=field): self.assertEqual(brief.validate(document(ENTRY.replace('- **'+field+'：**','- missing')))['status'],'fail')
    def test_collapsed(self): self.assertEqual(brief.validate(document(ENTRY.replace('\n\n- **',' - **')))['status'],'fail')
    def test_missing_venue_grade_scope(self):
        for field in ['发表：','等级：','已读：']:
            with self.subTest(field=field): self.assertEqual(brief.validate(document(ENTRY.replace(field,'')))['status'],'fail')
    def test_empty_grade(self): self.assertEqual(brief.validate(document(ENTRY.replace('等级：不适用','等级：')))['status'],'fail')
    def test_duplicate(self): self.assertEqual(brief.validate(document(ENTRY+'\n\n'+ENTRY))['status'],'fail')
    def test_missing_group(self): self.assertEqual(brief.validate(document().replace('## Hugging Face','## Missing'))['status'],'fail')
    def test_empty(self): self.assertEqual(brief.validate(document(ENTRY.replace('- **问题：** 合成内容，仅供结构测试。','- **问题：**')))['status'],'fail')
    def test_no_results(self): self.assertEqual(brief.validate(document('本次未检出符合条件的论文，合成测试。'))['status'],'pass')
    def test_contract_detects_dropped_paper(self):
        requirements={'format':{'document_headings':['## '+g for g in brief.GROUPS+['覆盖与限制']],'unit_level':3,'sections':[{'heading':ENTRY.splitlines()[0],'required_markers':['**基本信息：**']+['- **'+f+'：**' for f in brief.FIELDS]}]}}
        self.assertEqual(shared.validate(document(),requirements)['status'],'pass')
        self.assertEqual(shared.validate(document('本次未检出符合条件的论文。'),requirements)['status'],'fail')
    def test_structure_does_not_verify_claim(self):
        self.assertEqual(brief.validate(document(ENTRY.replace('合成内容，仅供结构测试。','未经证实的首次突破。')))['status'],'pass')
if __name__=='__main__':unittest.main()
