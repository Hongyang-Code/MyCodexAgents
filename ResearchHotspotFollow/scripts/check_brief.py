"""Check four source groups and separate paper fields."""
import argparse, hashlib, importlib.util, json, re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('paper_blocks',ROOT/'shared/scripts/paper_blocks.py')
blocks=importlib.util.module_from_spec(spec); spec.loader.exec_module(blocks)
GROUPS=['CCF及其他重要期刊会议','arXiv','Hugging Face','其他相关论文']
FIELDS=blocks.FIELDS+['与核心领域的联系']
RELATION_PARTS=['联系类型','具体关联','证据状态','适用条件']

def validate(text):
    text=text.replace('\r\n','\n').replace('\r','\n')
    # Hidden examples cannot satisfy required scope or relation fields.
    visible=[]; fence=None
    for line in re.sub(r'<!--.*?-->', '', text, flags=re.S).splitlines():
        marker=re.match(r'^ {0,3}(`{3,}|~{3,})',line)
        if marker:
            token=marker[1]
            if fence is None: fence=token
            elif token[0]==fence[0] and len(token)>=len(fence): fence=None
            continue
        if fence is None: visible.append(line)
    text='\n'.join(visible)
    result=blocks.validate_blocks(text, extra_fields=['与核心领域的联系'])
    for paper in re.finditer(r'^### \[(P[0-9]+)\] [^\n]*\n(.*?)(?=^#{1,3} |\Z)',text,re.M|re.S):
        pid,body=paper[1],paper[2]
        meta=re.search(r'^\*\*基本信息：\*\* (.+)$',body,re.M)
        categories=re.findall(r'(?:^|｜)追踪：([^｜\n]+)',meta[1]) if meta else []
        if len(categories)!=1 or categories[0].strip() not in ('核心领域','相关领域'):
            result['errors'].append(pid+': missing or invalid tracking category')
            continue
        if categories[0].strip()=='相关领域':
            relation=re.search(r'^- \*\*与核心领域的联系：\*\* (.+)$',body,re.M)
            value=relation[1] if relation else ''
            for part in RELATION_PARTS:
                found=re.findall(re.escape(part)+r'：([^；\n]+)',value)
                if len(found)!=1 or not found[0].strip(' 。') or found[0].strip() in ('待填写','TODO'):
                    result['errors'].append(pid+': missing or empty relation part '+part)
            status=re.search(r'证据状态：([^；\n]+)',value)
            if not status or not any(label in status[1] for label in ('已有验证','待验证设想')):
                result['errors'].append(pid+': missing relation evidence status')
    headings=re.findall(r'^## (.+)$',text,re.M)
    if headings!=GROUPS+['覆盖与限制']: result['errors'].append('missing, repeated or unordered source headings')
    for group in GROUPS:
        m=re.search(r'^## '+re.escape(group)+r'\n(.*?)(?=^## |\Z)',text,re.M|re.S)
        if m and not re.search(r'^### \[P[0-9]+\]',m.group(1),re.M) and '未检出' not in m.group(1): result['errors'].append('group needs papers or coverage: '+group)
    result['status']='fail' if result['errors'] else 'pass'
    return result

def main():
    parser=argparse.ArgumentParser(description=__doc__); parser.add_argument('text'); args=parser.parse_args()
    raw=Path(args.text).read_bytes(); result=validate(raw.decode('utf-8-sig')); result['sha256']=hashlib.sha256(raw).hexdigest()
    print(json.dumps(result,ensure_ascii=True)); return int(result['status']=='fail')
if __name__=='__main__': raise SystemExit(main())
