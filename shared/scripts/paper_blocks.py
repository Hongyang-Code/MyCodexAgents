"""Validate readable paper blocks; scientific meaning requires source review."""
import re
FIELDS = ['速览', '问题', '方法', '创新点', '结果与可靠性', '阅读建议']

def validate_blocks(text, extra_fields=(), minimum=0):
    text=text.replace('\r\n','\n').replace('\r','\n')
    errors=[]; ids=[]
    # Ignore comments/fenced examples: they cannot satisfy content requirements.
    clean=re.sub(r'<!--.*?-->', '', text, flags=re.S)
    clean=re.sub(r'^```.*?^```[^\n]*', '', clean, flags=re.M|re.S)
    lines=clean.splitlines()
    starts=[i for i,line in enumerate(lines) if re.match(r'^### \[P[0-9]+\] ', line)]
    for start in starts:
        end=next((i for i in range(start+1,len(lines)) if re.match(r'^#{1,3} ', lines[i])),len(lines))
        head=lines[start]; pid=re.match(r'^### \[(P[0-9]+)\]',head).group(1); ids.append(pid)
        if not re.search(r'\[[^\]]+\]\(https?://[^)]+\)', head): errors.append(pid+': missing paper link')
        body=lines[start+1:end]
        meta=[x for x in body if x.startswith('**基本信息：**')]
        if len(meta)!=1 or any(label not in meta[0] for label in ['作者：','发表：','等级：','日期：','已读：']): errors.append(pid+': incomplete metadata')
        if len(meta)==1:
            for label in ['作者','发表','等级','日期','已读']:
                value=re.search(re.escape(label)+r'：([^｜]+)',meta[0])
                if not value or not value[1].strip() or '{{' in value[1]: errors.append(pid+': empty metadata '+label)
        tokens=['- **'+f+'：**' for f in FIELDS+list(extra_fields)]
        found=[]
        for token in tokens:
            matches=[i for i,x in enumerate(body) if x.startswith(token)]
            if len(matches)!=1: errors.append(pid+': missing or repeated '+token); continue
            i=matches[0]; found.append(i); value=body[i][len(token):].strip()
            if not value.strip(' 。；') or '{{' in value: errors.append(pid+': empty field')
            if any(other in body[i][len(token):] for other in tokens): errors.append(pid+': fields squeezed onto same line')
            if i>0 and body[i-1].strip(): errors.append(pid+': blank line required before field')
        if found!=sorted(found): errors.append(pid+': unordered fields')
        advice=[x for x in body if x.startswith('- **阅读建议：**')]
        if advice and not any(w in advice[0] for w in ['建议精读','建议略读','暂缓判断']): errors.append(pid+': missing recommendation')
    if len(ids)!=len(set(ids)): errors.append('duplicate paper ids')
    if len(ids)<minimum: errors.append('fewer than '+str(minimum)+' papers')
    if '{{' in clean: errors.append('unresolved placeholders')
    if re.search(r'^- \*\*\[P[0-9]+\]',clean,re.M): errors.append('legacy compressed paper layout')
    return {'status':'fail' if errors else 'pass','papers':len(ids),'errors':errors}
