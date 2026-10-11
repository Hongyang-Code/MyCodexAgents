import importlib.util
from pathlib import Path
import unittest
ROOT=Path(__file__).resolve().parents[2]
def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
brief=load('brief',ROOT/'ResearchHotspotFollow/scripts/check_brief.py')
shared=load('shared',ROOT/'TextReadable/scripts/check_format.py')
ENTRY="### [P01] [Synthetic Paper](https://example.org/paper)\n\n**基本信息：** 作者：Synthetic｜发表：测试｜等级：不适用｜日期：2026-09-01，测试版｜已读：合成摘要｜追踪：核心领域\n\n"+"\n\n".join('- **'+f+'：** '+('建议略读，合成测试。' if f=='阅读建议' else '合成内容，仅供结构测试。') for f in brief.FIELDS)
RELATED=ENTRY.replace('追踪：核心领域','追踪：相关领域').replace('- **与核心领域的联系：** 合成内容，仅供结构测试。','- **与核心领域的联系：** 联系类型：方法借鉴；具体关联：合成匹配机制可供核心任务对应点搜索研究；证据状态：待验证设想，仅为合成分析；适用条件：须匹配数据维度，障碍是监督差异，先作小规模对照。')
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
    def test_related(self): self.assertEqual(brief.validate(document(RELATED))['status'],'pass')
    def test_validated_relation(self): self.assertEqual(brief.validate(document(RELATED.replace('待验证设想','已有验证')))['status'],'pass')
    def test_missing_category(self): self.assertEqual(brief.validate(document(ENTRY.replace('｜追踪：核心领域','')))['status'],'fail')
    def test_unknown_category(self): self.assertEqual(brief.validate(document(ENTRY.replace('追踪：核心领域','追踪：热门领域')))['status'],'fail')
    def test_duplicate_category(self): self.assertEqual(brief.validate(document(ENTRY.replace('追踪：核心领域','追踪：核心领域｜追踪：相关领域')))['status'],'fail')
    def test_missing_relation_parts(self):
        for part in brief.RELATION_PARTS:
            with self.subTest(part=part): self.assertEqual(brief.validate(document(RELATED.replace(part+'：','missing：')))['status'],'fail')
    def test_empty_relation_conditions(self):
        value=RELATED.split('适用条件：')[1]
        self.assertEqual(brief.validate(document(RELATED.replace(value,'')))['status'],'fail')
    def test_missing_evidence_status(self): self.assertEqual(brief.validate(document(RELATED.replace('待验证设想','潜力巨大')))['status'],'fail')
    def test_hidden_relation(self):
        line=RELATED.splitlines()[-1]
        for wrapped in ['<!--'+line+'-->','```markdown\n'+line+'\n```','~~~markdown\n'+line+'\n~~~']:
            with self.subTest(wrapped=wrapped): self.assertEqual(brief.validate(document(RELATED.replace(line,wrapped)))['status'],'fail')
    def test_mixed_core_related(self): self.assertEqual(brief.validate(document(ENTRY+'\n\n'+RELATED.replace('[P01]','[P02]')))['status'],'pass')
    def test_contract_requires_relation(self):
        requirements={'format':{'unit_level':3,'sections':[{'heading':ENTRY.splitlines()[0],'required_markers':['- **'+f+'：**' for f in brief.FIELDS]}]}}
        self.assertEqual(shared.validate(document(RELATED),requirements)['status'],'pass')
        self.assertEqual(shared.validate(document(RELATED.replace('- **与核心领域的联系：**','- removed')),requirements)['status'],'fail')
    def test_structure_does_not_verify_claim(self):
        self.assertEqual(brief.validate(document(ENTRY.replace('合成内容，仅供结构测试。','未经证实的首次突破。')))['status'],'pass')
if __name__=='__main__':unittest.main()
