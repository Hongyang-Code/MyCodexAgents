import argparse
import base64
import hashlib
import json
import shutil
import sys
from pathlib import Path
from . import storage, layout, drawio, qa, adapters


def candidate(task):
    task=Path(task);graph=storage.read_json(task/'semantic_graph.json')
    errors=qa.graph_errors(graph)
    if errors:raise ValueError('; '.join(errors))
    plans=[layout.plan(graph,direction) for direction in ('LR','TB')]
    for i,p in enumerate(plans,1):storage.write_json(task/f'candidate-{i}.json',p)
    best=min(plans,key=lambda p:p['score'])
    storage.write_json(task/'layout_plan.json',best)
    storage.checkpoint(task,'planned')
    return {'selected':best['direction'],'scores':[p['score'] for p in plans], 'note':'Geometry score only; host must compare full candidates visually before final selection.'}


def build_task(task,name='figure.drawio'):
    task=Path(task);output=task/name
    if output.exists():raise ValueError('Existing figure preserved; use a new --name for revisions')
    graph=storage.read_json(task/'semantic_graph.json');errors=qa.graph_errors(graph)
    if errors:raise ValueError('; '.join(errors))
    drawio.build(graph,storage.read_json(task/'layout_plan.json'),storage.read_json(task/'style_guide.json'),storage.read_json(task/'assets.json'),output,task)
    storage.checkpoint(task,'built')
    return {'output':str(output), 'sha256':storage.digest(output)}


def audit(task,figure):
    task=Path(task);figure=Path(figure)
    guide=storage.read_json(task/'style_guide.json')
    result=qa.check(figure,storage.read_json(task/'semantic_graph.json'),storage.read_json(task/'requirements.json'),guide.get('display_width_mm',180))
    result['baseline_hashes']={n:storage.digest(task/n) for n in ('semantic_graph.json','requirements.json','assets.json','style_guide.json')}
    result['assets']={'status':'pass','findings':[]}
    for asset in storage.read_json(task/'assets.json'):
        p=Path(asset.get('path',asset.get('source','')))
        if not p.is_absolute():p=task/p
        if not p.is_file() or storage.digest(p)!=asset['sha256']:
            result['assets']['status']='fail';result['assets']['findings'].append('Missing/changed asset: '+asset['id']);result['status']='fail'
    graph=storage.read_json(task/'semantic_graph.json');asset_map={a['id']:a for a in storage.read_json(task/'assets.json')}
    xml=storage.parse_xml(figure);cells={c.get('id'):c for d in xml.findall('diagram') if d.get('id')==graph.get('page_id','main') for c in d.iter('mxCell')}
    for n in graph['nodes']:
        if n.get('type')!='image':continue
        c=cells.get(n['id']+'-image');image_style=c.get('style','') if c is not None else ''
        match=__import__('re').search(r'image=data:image/[^;,]+(?:;base64)?,([^;]+)',image_style)
        actual=hashlib.sha256(base64.b64decode(match.group(1))).hexdigest() if match else None
        if actual!=asset_map.get(n.get('asset_id'),{}).get('sha256') or actual is None:
            result['assets']['status']='fail';result['assets']['findings'].append('Embedded asset mismatch: '+n['id']);result['status']='fail'
    storage.write_json(task/'qa_report.json',result)
    return result


def deliver(task,figure,preview,review_file,problem=False):
    task=Path(task);figure=Path(figure);preview=Path(preview) if preview else None
    report=audit(task,figure);review=storage.read_json(review_file);sha=storage.digest(figure)
    errors=[]
    if report['status']!='pass':errors.append('deterministic checks failed')
    if review.get('figure_sha256')!=sha:errors.append('review refers to old figure')
    if review.get('baseline_hashes')!=report['baseline_hashes']:errors.append('review refers to old scientific/requirement baseline')
    for key in ('scientific','visual_full','visual_print','history'):
        item=review.get(key,{})
        if item.get('status')!='pass' or not item.get('evidence'):errors.append('missing or failed host review: '+key)
    active={r['id'] for r in storage.read_json(task/'requirements.json') if r['status']=='active'}
    reviewed=review.get('requirements',[])
    if {r.get('id') for r in reviewed}!=active or len(reviewed)!=len(active) or any(r.get('status')!='pass' or not r.get('evidence') for r in reviewed):
        errors.append('active requirements not individually reviewed')
    native=review.get('native_render',{})
    if native.get('status')!='pass' or native.get('figure_sha256')!=sha or not preview or not preview.exists() or native.get('output_sha256')!=storage.digest(preview):
        errors.append('native preview unavailable, failed or stale')
    if review.get('edit',{}).get('status') not in ('pass','not_run') or not review.get('edit',{}).get('evidence'):
        errors.append('editing evidence or honest not_run required')
    if review.get('unresolved'):errors.append('unresolved host review findings')
    state=storage.read_json(task/'state.json')
    if state['optimization_rounds']>3:errors.append('optimization budget exceeded')
    if errors and not problem:return {'status':'fail','errors':errors,'action':'Fix within budget or explicitly deliver a marked problem version.'}
    dest=task/('problem-version' if errors else 'delivery')
    if dest.exists():raise ValueError('Delivery exists; preserve it and make a separate revision task')
    dest.mkdir()
    storage.atomic(dest/'figure.drawio',figure.read_bytes())
    if preview and preview.exists():storage.atomic(dest/('preview'+preview.suffix),preview.read_bytes())
    result={'status':'problem_version' if errors else 'pass','errors':errors,'figure_sha256':sha,
            'limitation':'Interactive editor checks not run' if review.get('edit',{}).get('status')!='pass' else '', 'folder':str(dest.resolve())}
    storage.write_json(dest/'delivery.json',result);storage.write_json(dest/'review.json',review)
    storage.checkpoint(task,'delivered' if not errors else 'problem')
    return result


def main(argv=None):
    # Stable machine-readable Chinese output even under Windows legacy codepages.
    for stream in (sys.stdout,sys.stderr):
        if hasattr(stream,'reconfigure'):stream.reconfigure(encoding='utf-8')
    p=argparse.ArgumentParser(description='PaperFigureAgent native tools. Host AI handles natural input and scientific/visual judgment.')
    sub=p.add_subparsers(dest='cmd',required=True)
    sub.add_parser('capabilities')
    s=sub.add_parser('start');s.add_argument('text');s.add_argument('--root',default=str(Path(__file__).resolve().parents[1]/'outputs'));s.add_argument('--material',action='append',default=[])
    s=sub.add_parser('read');s.add_argument('path')
    s=sub.add_parser('resume');s.add_argument('task')
    s=sub.add_parser('plan');s.add_argument('task')
    s=sub.add_parser('build');s.add_argument('task');s.add_argument('--name',default='figure.drawio')
    s=sub.add_parser('check');s.add_argument('task');s.add_argument('figure')
    s=sub.add_parser('render');s.add_argument('figure');s.add_argument('output');s.add_argument('--format',choices=['png','svg','pdf'],default='png');s.add_argument('--page',type=int,default=0);s.add_argument('--drawio');s.add_argument('--receipt')
    s=sub.add_parser('patch');s.add_argument('source');s.add_argument('output');s.add_argument('operations');s.add_argument('--expected-hash',required=True)
    s=sub.add_parser('diff');s.add_argument('before');s.add_argument('after')
    s=sub.add_parser('require');s.add_argument('task');s.add_argument('text');s.add_argument('--objects',nargs='*',default=[]);s.add_argument('--supersedes',nargs='*',default=[])
    s=sub.add_parser('checkpoint');s.add_argument('task');s.add_argument('stage');s.add_argument('--optimization',action='store_true')
    s=sub.add_parser('deliver');s.add_argument('task');s.add_argument('figure');s.add_argument('review');s.add_argument('--preview');s.add_argument('--problem',action='store_true')
    args=p.parse_args(argv)
    try:
        if args.cmd=='capabilities':result=adapters.capabilities()
        elif args.cmd=='start':
            task=storage.start(args.root,args.text,args.material)
            result={'task':str(task),'next':'Host reads agent.md and prompts/01-understand.md; do not ask user for JSON.'}
        elif args.cmd=='read':result=storage.material(args.path)
        elif args.cmd=='resume':
            task=Path(args.task);result={n:storage.read_json(task/(n+'.json')) for n in ('brief','state','requirements','qa_report')}
        elif args.cmd=='plan':result=candidate(args.task)
        elif args.cmd=='build':result=build_task(args.task,args.name)
        elif args.cmd=='check':result=audit(args.task,args.figure)
        elif args.cmd=='render':
            result=adapters.render(args.figure,args.output,args.drawio,args.page,args.format)
            if args.receipt:storage.write_json(args.receipt,result)
        elif args.cmd=='patch':result=drawio.patch(args.source,args.output,storage.read_json(args.operations),args.expected_hash)
        elif args.cmd=='diff':result=drawio.diff(args.before,args.after)
        elif args.cmd=='require':result=storage.add_requirement(args.task,args.text,args.objects,args.supersedes)
        elif args.cmd=='checkpoint':result={'snapshot':str(storage.checkpoint(args.task,args.stage,args.optimization))}
        elif args.cmd=='deliver':result=deliver(args.task,args.figure,args.preview,args.review,args.problem)
        print(json.dumps(result,ensure_ascii=False,indent=2))
        return 1 if isinstance(result,dict) and result.get('status')=='fail' else 0
    except Exception as exc:
        print(json.dumps({'status':'fail','error':str(exc),'type':type(exc).__name__},ensure_ascii=False),file=sys.stderr)
        return 1
