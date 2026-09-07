"""Check four source groups and separate paper fields."""
import argparse, hashlib, importlib.util, json, re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('paper_blocks',ROOT/'shared/scripts/paper_blocks.py')
blocks=importlib.util.module_from_spec(spec); spec.loader.exec_module(blocks)
GROUPS=['CCF及其他重要期刊会议','arXiv','Hugging Face','其他相关论文']
FIELDS=blocks.FIELDS

def validate(text):
    text=text.replace('\r\n','\n').replace('\r','\n')
    result=blocks.validate_blocks(text)
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
