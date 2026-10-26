"""Check survey structure and declared paper inventory, not scientific validity."""
import argparse, hashlib, importlib.util, json, re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('blocks',ROOT/'shared/scripts/paper_blocks.py')
blocks=importlib.util.module_from_spec(spec);spec.loader.exec_module(blocks)
HEADINGS=['领域全景','发展脉络','方法路线比较','主干论文','阅读路线','未决问题与覆盖限制']

def identity(value):
    value=value.strip().lower()
    value=re.sub(r'^https?://(?:dx\.)?doi.org/','doi:',value)
    value=re.sub(r'^https?://arxiv.org/(?:abs|pdf)/','arxiv:',value)
    if value.startswith('arxiv:'): value=re.sub(r'v[0-9]+(?:\.pdf)?$','',value)
    return value

def validate(text,manifest):
    text=text.replace('\r\n','\n').replace('\r','\n')
    result=blocks.validate_blocks(text,extra_fields=['领域位置','前后关系'],minimum=20)
    errors=result['errors']
    if re.findall(r'^## (.+)$',text,re.M)!=HEADINGS: errors.append('missing or unordered survey sections')
    ids=re.findall(r'^### \[(P[0-9]+)\]',text,re.M)
    core=re.search(r'^## 主干论文\n(.*?)(?=^## |\Z)',text,re.M|re.S)
    if not core or re.findall(r'^### \[(P[0-9]+)\]',core[1],re.M)!=ids: errors.append('paper blocks outside core section')
    papers=manifest.get('papers',[]) if isinstance(manifest,dict) else []
    if not isinstance(papers,list) or any(not isinstance(p,dict) for p in papers): papers=[];errors.append('invalid inventory')
    mids=[p.get('id') for p in papers]
    if mids!=ids: errors.append('inventory and report differ')
    seen=set();qualified=methods=0
    for p in papers:
        pid=str(p.get('id')); aliases=p.get('identity_aliases',[])
        if not isinstance(aliases,list) or not aliases or any(not isinstance(x,str) or not x.strip() for x in aliases): aliases=[];errors.append(pid+': missing stable aliases')
        keys={identity(x) for x in aliases+[str(p.get('canonical_id',''))] if x}
        if not p.get('canonical_id') or keys & seen: errors.append(pid+': missing or duplicate identity')
        seen.update(keys)
        for field in ['title','selection_reason','read_scope','venue_abbreviation','ccf_grade','ccf_edition']:
            if not isinstance(p.get(field),str) or not p[field].strip(): errors.append(pid+': missing '+field)
        if p.get('type') not in ['method','theory','benchmark','seminal_survey']: errors.append(pid+': invalid paper type')
        if p.get('type')=='seminal_survey' and not p.get('foundation_evidence'): errors.append(pid+': missing foundational evidence')
        if p.get('qualified') is True:
            qualified+=1;methods+=p.get('type')=='method'
        else: errors.append(pid+': unqualified paper belongs in pending sources, not core')
        relations=p.get('relations')
        if not isinstance(relations,list): errors.append(pid+': missing relations inventory');continue
        for rel in relations:
            if not isinstance(rel,dict) or rel.get('target') not in ids or not all(rel.get(k) for k in ['relation','evidence','status']): errors.append(pid+': invalid relationship evidence')
    if qualified<20: errors.append('fewer than 20 qualified unique core papers')
    if qualified and methods*2<=qualified: errors.append('methods must be the majority')
    refs=set(re.findall(r'\[(P[0-9]+)\]',text))
    if refs-set(ids): errors.append('unknown paper reference')
    result.update(status='fail' if errors else 'pass',qualified=qualified,methods=methods)
    return result

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('text');parser.add_argument('--papers',required=True);args=parser.parse_args()
    raw=Path(args.text).read_bytes();result=validate(raw.decode('utf-8-sig'),json.loads(Path(args.papers).read_text('utf-8-sig')))
    result['sha256']=hashlib.sha256(raw).hexdigest();print(json.dumps(result,ensure_ascii=True));raise SystemExit(result['status']=='fail')
