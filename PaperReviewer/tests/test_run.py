import copy
import hashlib
import importlib.util
from pathlib import Path
import unittest
spec=importlib.util.spec_from_file_location('review_run',Path(__file__).resolve().parents[1]/'scripts/check_run.py')
review=importlib.util.module_from_spec(spec);spec.loader.exec_module(review)
FINAL='合成修订稿'.encode('utf-8')
H=hashlib.sha256(FINAL).hexdigest()
def fixture():
    return dict(schema_version=2,artifact_checks={'manuscript':'pass','responses':'pass','changes':'pass','proposal':'not_applicable'},requested_rounds=3,round_mode='max',original_sha256=H,rounds=[dict(number=1,input_sha256=H,output_sha256=H,no_progress=False,recheck='合成复查',submissions=[dict(role=role,agent_id='synthetic-'+role,status='completed',input_sha256=H,report_sha256=H,report_path=role+'.json') for role in ['reviewer_a','reviewer_b','editor']],issues=[dict(id='Q1',priority='major',location='第1段',question='合成问题',basis='合成证据',impact='测试影响',verdict='unsupported',state='resolved',action='保持正文',response='按原文澄清',recheck='合成位置支持驳回')])],completion_status='checked',stop_reason='resolved',unresolved_ids=[],text_readable_batches=[dict(revision_rounds=0,status='passed')],checks={k:'pass' for k in review.CHECKS},final_sha256=H)
class RunTests(unittest.TestCase):
    def test_valid_early_stop(self): self.assertEqual(review.validate(fixture(),FINAL)['status'],'pass')
    def test_positive_integer(self):
        for n in [0,-1,True,2.5,'3']:
            r=fixture();r['requested_rounds']=n
            with self.subTest(n=n):self.assertEqual(review.validate(r,FINAL)['status'],'fail')
    def test_over_budget(self):
        r=fixture();r['requested_rounds']=1;r['rounds']*=2;self.assertEqual(review.validate(r,FINAL)['status'],'fail')
    def test_exact_incomplete(self):
        r=fixture();r['round_mode']='exact';self.assertEqual(review.validate(r,FINAL)['status'],'fail')
    def test_exact_complete(self):
        r=fixture();r['round_mode']='exact';r['requested_rounds']=1;self.assertEqual(review.validate(r,FINAL)['status'],'pass')
    def test_pending_evidence_not_resolved(self):
        r=fixture();r['rounds'][0]['issues'][0]['verdict']='insufficient_evidence';self.assertEqual(review.validate(r,FINAL)['status'],'fail')
    def test_lost_issue_across_rounds(self):
        r=fixture();r['rounds'][0]['issues'][0].update(state='open',next_step='核查')
        second=copy.deepcopy(r['rounds'][0]);second.update(number=2,no_progress=True,issues=[])
        for item in second['submissions']:
            if item['role']!='editor':item['agent_id']+='-round2'
        r['rounds'].append(second)
        self.assertIn('unresolved issues silently lost or misreported',review.validate(r,FINAL)['errors'])
    def test_honest_partial(self):
        r=fixture();r['completion_status']='partial';r['stop_reason']='awaiting_evidence';r['unresolved_ids']=['Q1'];r['rounds'][0]['issues'][0].update(verdict='insufficient_evidence',state='awaiting_evidence',next_step='补充原始数据');r['text_readable_batches']=[]
        self.assertEqual(review.validate(r,FINAL)['status'],'pass')
    def test_three_language_batches(self):
        r=fixture();r['text_readable_batches']*=3;self.assertEqual(review.validate(r,FINAL)['status'],'fail')
    def test_four_language_revisions(self):
        r=fixture();r['text_readable_batches'][0]['revision_rounds']=4;self.assertEqual(review.validate(r,FINAL)['status'],'fail')
    def test_post_audit_change(self):self.assertEqual(review.validate(fixture(),b'changed')['status'],'fail')
    def test_broken_revision_chain(self):
        r=fixture();r['rounds'][0]['input_sha256']='0'*64;self.assertEqual(review.validate(r,FINAL)['status'],'fail')
    def test_no_fake_content_pass(self):
        r=fixture();r['checks']['content']='unknown';self.assertEqual(review.validate(r,FINAL)['status'],'fail')
    def test_record_cannot_prove_truth(self):
        r=fixture();r['rounds'][0]['issues'][0]['basis']='未经证实的论断';self.assertEqual(review.validate(r,FINAL)['status'],'pass')
        # Human source review must independently reject invented evidence.
    def test_missing_reviewer_submission(self):
        r=fixture();r['rounds'][0]['submissions'].pop(0);self.assertEqual(review.validate(r,FINAL)['status'],'fail')
    def test_same_agent_not_independent(self):
        r=fixture();r['rounds'][0]['submissions'][1]['agent_id']=r['rounds'][0]['submissions'][0]['agent_id'];self.assertEqual(review.validate(r,FINAL)['status'],'fail')
    def test_role_failed(self):
        r=fixture();r['rounds'][0]['submissions'][0]['status']='failed';self.assertEqual(review.validate(r,FINAL)['status'],'fail')
    def test_wrong_version_reviewed(self):
        r=fixture();r['rounds'][0]['submissions'][0]['input_sha256']='0'*64;self.assertEqual(review.validate(r,FINAL)['status'],'fail')
    def test_unreviewed_proposal(self):
        r=fixture();r['artifact_checks']['proposal']='unknown';self.assertEqual(review.validate(r,FINAL)['status'],'fail')
    def test_malformed_batch(self):
        r=fixture();r['text_readable_batches']=[None];self.assertEqual(review.validate(r,FINAL)['status'],'fail')
    def test_reviewer_context_must_be_fresh(self):
        r=fixture();second=copy.deepcopy(r['rounds'][0]);second['number']=2;r['rounds'].append(second)
        self.assertIn('reviewer context reused across roles or rounds',review.validate(r,FINAL)['errors'])
    def test_report_file_is_verified(self):
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            r=fixture()
            for role in r['rounds'][0]['submissions']:(Path(folder)/role['report_path']).write_bytes(FINAL)
            self.assertEqual(review.validate(r,FINAL,folder)['status'],'pass')
            (Path(folder)/'reviewer_a.json').write_bytes(b'changed')
            self.assertIn('role report changed after audit',review.validate(r,FINAL,folder)['errors'])
if __name__=='__main__':unittest.main()
