import copy,importlib.util,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('survey',ROOT/'ResearchFieldSurvey/scripts/check_survey.py');survey=importlib.util.module_from_spec(spec);spec.loader.exec_module(survey)
def fixture(n=20):
    papers=[];blocks=[]
    for i in range(1,n+1):
        pid=f'P{i:02d}'
        papers.append(dict(id=pid,canonical_id=f'doi:10.0000/synthetic{i}',identity_aliases=[f'doi:10.0000/synthetic{i}'],title='Synthetic '+str(i),type='method',selection_reason='合成样例',qualified=True,read_scope='合成方法结果',venue_abbreviation='Test',ccf_grade='不适用',ccf_edition='不适用',relations=[]))
        blocks.append(f'### [{pid}] [Synthetic {i}](https://example.org/{i})\n\n**基本信息：** 作者：Synthetic｜发表：Test｜等级：不适用｜日期：2026测试版｜已读：合成内容｜类型：方法\n\n'+'\n\n'.join('- **'+f+'：** '+('建议略读，仅测试。' if f=='阅读建议' else '合成内容，仅用于结构测试。') for f in survey.blocks.FIELDS+['领域位置','前后关系']))
    text='# 合成测试，不是真实文献\n\n'+'\n\n'.join('## '+h+'\n\n'+('\n\n'.join(blocks) if h=='主干论文' else '合成说明。') for h in survey.HEADINGS)
    return text,{'papers':papers}
class SurveyTests(unittest.TestCase):
    def test_windows_newlines(self):
        t,m=fixture();self.assertEqual(survey.validate(t.replace('\n','\r\n'),m)['status'],'pass')
    def test_valid(self): self.assertEqual(survey.validate(*fixture())['status'],'pass')
    def test_nineteen(self): self.assertEqual(survey.validate(*fixture(19))['status'],'fail')
    def test_no_upper_limit(self): self.assertEqual(survey.validate(*fixture(30))['status'],'pass')
    def test_duplicate_versions(self):
        t,m=fixture();m['papers'][0]['identity_aliases']=['arxiv:2601.12345v1'];m['papers'][1]['identity_aliases']=['https://arxiv.org/abs/2601.12345v2'];self.assertEqual(survey.validate(t,m)['status'],'fail')
    def test_paper_dropped(self):
        t,m=fixture();m['papers'].pop();self.assertEqual(survey.validate(t,m)['status'],'fail')
    def test_survey_needs_evidence(self):
        t,m=fixture();m['papers'][0]['type']='seminal_survey';self.assertEqual(survey.validate(t,m)['status'],'fail')
    def test_method_majority(self):
        t,m=fixture()
        for p in m['papers'][:10]:p['type']='theory'
        self.assertEqual(survey.validate(t,m)['status'],'fail')
    def test_unqualified(self):
        t,m=fixture();m['papers'][0]['qualified']=False;self.assertEqual(survey.validate(t,m)['status'],'fail')
    def test_collapsed(self):
        t,m=fixture();self.assertEqual(survey.validate(t.replace('\n\n- **',' - **'),m)['status'],'fail')
    def test_missing_field(self):
        t,m=fixture();self.assertEqual(survey.validate(t.replace('- **领域位置：**','Missing'),m)['status'],'fail')
    def test_missing_macro_section(self):
        t,m=fixture();self.assertEqual(survey.validate(t.replace('## 发展脉络','## Other'),m)['status'],'fail')
    def test_unknown_relationship(self):
        t,m=fixture();m['papers'][0]['relations']=[dict(target='P99',relation='extends',evidence='synthetic',status='test')];self.assertEqual(survey.validate(t,m)['status'],'fail')
if __name__=='__main__':unittest.main()
