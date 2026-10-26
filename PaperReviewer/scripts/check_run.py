"""Validate declared review records; never verify scientific truth or run a model."""
import importlib.util
import argparse
import hashlib
import json
import re
from pathlib import Path

CHECKS = ['content', 'coverage', 'readability', 'semantic_audit', 'format']
VERDICTS = ['supported', 'partly_supported', 'unsupported', 'insufficient_evidence']

def validate(run, final_bytes=None, base_path=None):
    errors = []
    def require(ok, message):
        if not ok: errors.append(message)
    if not isinstance(run, dict): return {'status':'fail','errors':['run must be an object']}
    require(run.get('schema_version')==2, 'current runs require schema_version=2; preserve v1 as historical records')
    n=run.get('requested_rounds'); mode=run.get('round_mode'); rounds=run.get('rounds')
    require(type(n) is int and n>0, 'N must be a positive integer')
    require(mode in ['max','exact'], 'invalid round_mode')
    if not isinstance(rounds,list): return {'status':'fail','errors':errors+['rounds must be a list']}
    if type(n) is int and n>0: require(len(rounds)<=n,'review round limit exceeded')
    status=run.get('completion_status'); stop=run.get('stop_reason')
    require(status in ['checked','partial','needs_input'],'invalid completion_status')
    require(stop in ['resolved','max_rounds','stagnation','awaiting_evidence','needs_input','user_stopped','role_failed'],'invalid stop_reason')
    if mode=='exact' and type(n) is int and len(rounds)<n:
        require(stop in ['awaiting_evidence','needs_input','user_stopped','role_failed'],'exact mode ended early without blocking reason')
    if stop=='max_rounds': require(len(rounds)==n,'max_rounds recorded before N')
    if stop=='stagnation': require(len(rounds)>=2 and all(x.get('no_progress') is True for x in rounds[-2:] if isinstance(x,dict)), 'stagnation needs two rounds without progress')
    def valid_hash(value): return isinstance(value,str) and re.fullmatch(r'[a-f0-9]{64}',value) is not None
    previous=run.get('original_sha256'); require(valid_hash(previous),'invalid original hash')
    latest={}
    reviewer_ids=set()
    for number, record in enumerate(rounds,1):
        if not isinstance(record,dict): errors.append('invalid round record');continue
        require(record.get('number')==number,'nonsequential round number')
        require(record.get('input_sha256')==previous,'broken revision chain')
        require(valid_hash(record.get('output_sha256')),'invalid revision hash')
        submissions=record.get('submissions',[])
        if not isinstance(submissions,list): submissions=[];errors.append('invalid submissions')
        require([s.get('role') for s in submissions if isinstance(s,dict)]==['reviewer_a','reviewer_b','editor'], 'missing, repeated or unordered role submissions')
        actors=[]
        for submission in submissions:
            if not isinstance(submission,dict): errors.append('invalid role submission');continue
            actor=submission.get('agent_id');role=submission.get('role')
            require(isinstance(actor,str) and bool(actor.strip()),'missing actual agent id')
            if isinstance(actor,str):
                actors.append(actor)
                if role in ['reviewer_a','reviewer_b']:
                    require(actor not in reviewer_ids,'reviewer context reused across roles or rounds')
                    reviewer_ids.add(actor)
            require(submission.get('status')=='completed','incomplete role submitted as completed round')
            require(submission.get('input_sha256')==record.get('input_sha256'),'role read wrong frozen manuscript')
            require(valid_hash(submission.get('report_sha256')),'invalid role report hash')
            path=submission.get('report_path')
            require(isinstance(path,str) and bool(path.strip()),'missing role report path')
            if base_path is not None and isinstance(path,str):
                root=Path(base_path).resolve();report=(root/path).resolve()
                if report==root or not report.is_relative_to(root):errors.append('role report outside run directory')
                elif not report.is_file():errors.append('role report missing')
                else: require(hashlib.sha256(report.read_bytes()).hexdigest()==submission.get('report_sha256'),'role report changed after audit')
        require(len(actors)==3 and len(set(actors))==3,'roles require distinct actual agents')
        previous=record.get('output_sha256')
        require(type(record.get('no_progress')) is bool,'no_progress must be boolean')
        require(isinstance(record.get('recheck'),str) and bool(record['recheck'].strip()),'missing recheck evidence')
        issues=record.get('issues')
        if not isinstance(issues,list): errors.append('issues must be a list');continue
        ids=[]
        for issue in issues:
            if not isinstance(issue,dict): errors.append('invalid issue');continue
            pid=issue.get('id'); require(isinstance(pid,str) and bool(pid.strip()),'invalid issue id')
            if not isinstance(pid,str): continue
            ids.append(pid)
            require(issue.get('verdict') in VERDICTS,'invalid verdict')
            require(issue.get('priority') in ['critical','major','minor'],'invalid priority')
            require(issue.get('state') in ['resolved','open','awaiting_evidence'],'invalid issue state')
            for key in ['location','question','basis','impact','action','response','recheck']:
                require(isinstance(issue.get(key),str) and bool(issue[key].strip()),'missing issue '+key)
            if issue.get('verdict')=='insufficient_evidence': require(issue.get('state')!='resolved','unverified concern cannot be resolved')
            if issue.get('state')!='resolved': require(isinstance(issue.get('next_step'),str) and bool(issue['next_step'].strip()),'unresolved issue needs next_step')
            latest[pid]=issue
        require(len(ids)==len(set(ids)),'duplicate issue id within round')
    unresolved=sorted(pid for pid,issue in latest.items() if issue.get('state')!='resolved')
    require(run.get('unresolved_ids')==unresolved,'unresolved issues silently lost or misreported')
    batches=run.get('text_readable_batches')
    if not isinstance(batches,list): batches=[];errors.append('text_readable_batches must be a list')
    require(len(batches)<=2,'TextReadable batch limit exceeded')
    for batch in batches:
        if not isinstance(batch,dict): errors.append('invalid TextReadable batch');continue
        count=batch.get('revision_rounds')
        require(type(count) is int and 0<=count<=3,'TextReadable revision limit exceeded')
        require(batch.get('status') in ['passed','not_passed','needs_clarification'],'invalid TextReadable status')
    require(valid_hash(run.get('final_sha256')),'invalid final hash')
    if final_bytes is not None: require(hashlib.sha256(final_bytes).hexdigest()==run.get('final_sha256'),'final file changed after audit')
    if status=='checked':
        require(bool(rounds),'checked without review')
        require(not unresolved,'checked with unresolved issues')
        require(stop in ['resolved','max_rounds'],'checked despite incomplete stop reason')
        require(isinstance(run.get('checks'),dict) and all(run['checks'].get(k)=='pass' for k in CHECKS),'checked without all final checks')
        require(bool(batches) and isinstance(batches[-1],dict) and batches[-1].get('status')=='passed','checked without final TextReadable pass')
    artifact_checks=run.get('artifact_checks',{})
    if not isinstance(artifact_checks,dict):artifact_checks={};errors.append('invalid artifact_checks')
    for name in ['manuscript','responses','changes','proposal']:
        value=artifact_checks.get(name)
        require(value in ['pass','fail','unknown','not_applicable'],'missing artifact audit: '+name)
        if name!='proposal':require(value!='not_applicable','required artifact cannot be not_applicable')
        if status=='checked':require(value=='pass' or (name=='proposal' and value=='not_applicable'),'checked with incomplete artifact audit')
    return {'status':'fail' if errors else 'pass','errors':errors,'executed_rounds':len(rounds),'unresolved_ids':unresolved}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('record');parser.add_argument('--final',required=True)
    parser.add_argument('--original',required=True);parser.add_argument('--changes',required=True);parser.add_argument('--change-report',required=True)
    args=parser.parse_args()
    try:
        record_path=Path(args.record);run=json.loads(record_path.read_text('utf-8-sig'))
        original=Path(args.original).read_bytes();final=Path(args.final).read_bytes()
        result=validate(run,final,record_path.parent)
        if hashlib.sha256(original).hexdigest()!=run.get('original_sha256'):result['errors'].append('original file differs from frozen source')
        spec=importlib.util.spec_from_file_location('change_manifest',Path(__file__).with_name('change_manifest.py'))
        manifest_module=importlib.util.module_from_spec(spec);spec.loader.exec_module(manifest_module)
        manifest=json.loads(Path(args.changes).read_text('utf-8-sig'))
        known={issue['id'] for row in run['rounds'] for issue in row['issues']}
        change_result=manifest_module.validate(original,final,manifest,known_issue_ids=known)
        result['errors'].extend(change_result['errors'])
        if Path(args.change_report).read_bytes()!=manifest_module.render(manifest).encode('utf-8'):result['errors'].append('human change report differs from checked manifest')
        result['status']='fail' if result['errors'] else 'pass'
    except (OSError,ValueError,TypeError,KeyError) as exc: result={'status':'fail','errors':[str(exc)]}
    print(json.dumps(result,ensure_ascii=False));return int(result['status']=='fail')
if __name__=='__main__': raise SystemExit(main())
