"""Deterministic checks are evidence of consistency, not scientific truth or beauty."""
import math
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from .storage import parse_xml, digest
from .drawio import styles
from .layout import port, hits, crosses, inside


def graph_errors(graph):
    errors=[];nodes=graph.get('nodes',[]);edges=graph.get('edges',[]);groups=graph.get('groups',[])
    ids=[n.get('id') for n in nodes+edges+groups]
    if not nodes:errors.append('semantic graph has no nodes')
    if any(not isinstance(i,str) or not i or i in ('0','1','pfa-title') for i in ids) or len(ids)!=len(set(ids)):
        errors.append('invalid or duplicate stable ID')
    node_ids={n.get('id') for n in nodes};group_ids={g.get('id') for g in groups}
    for n in nodes:
        if not n.get('label'):errors.append('missing node label: '+str(n.get('id')))
        if n.get('parent','1') not in group_ids|{'1'}:errors.append('unknown group')
        if not n.get('evidence'):errors.append('missing node evidence: '+n['id'])
    for e in edges:
        if e.get('source') not in node_ids or e.get('target') not in node_ids:errors.append('unknown semantic endpoint')
        if e.get('kind') not in ('data','control','supervision','spatial','grouping'):errors.append('unknown relation kind')
        if not e.get('evidence'):errors.append('missing edge evidence: '+e['id'])
    if graph.get('unresolved'):errors.append('unresolved scientific facts')
    return errors


def check(path,graph=None,requirements=(),display_width_mm=180):
    findings={'structure':[],'scientific_consistency':[],'geometry':[],'history':[]}
    metrics=[]
    def err(category,text):findings[category].append(text)
    try:
        root=parse_xml(path);pages=root.findall('diagram')
        if not pages:err('structure','no pages')
        if len({d.get('id') for d in pages})!=len(pages):err('structure','duplicate page IDs')
        for page in pages:
            objects=list(page.iter('mxCell'));ids=[c.get('id') for c in objects];cells={c.get('id'):c for c in objects}
            if len(ids)!=len(set(ids)) or any(i is None for i in ids):err('structure','duplicate/missing cell ID')
            if not {'0','1'}<=set(ids):err('structure','missing root cells')
            for c in objects:
                for ref in ('parent','source','target'):
                    if c.get(ref) and c.get(ref) not in cells:err('structure','invalid '+ref+': '+str(c.get('id')))
                seen=set();cur=c
                while cur.get('parent') in cells:
                    if cur.get('id') in seen:err('structure','cyclic parent');break
                    seen.add(cur.get('id'));cur=cells[cur.get('parent')]
            boxes={}
            def box(ident,stack=()):
                if ident in boxes:return boxes[ident]
                if ident in stack:raise ValueError('parent cycle')
                c=cells[ident];g=c.find('mxGeometry')
                if g is None:raise ValueError('missing geometry: '+ident)
                values=[float(g.get(k,0)) for k in ('x','y','width','height')]
                if not all(math.isfinite(v) for v in values):raise ValueError('non-finite geometry')
                x,y,w,h=values
                if w<=0 or h<=0:err('structure','nonpositive size: '+ident)
                if g.get('relative')=='1':err('structure','relative vertex geometry requires host import adapter: '+ident)
                parent=c.get('parent')
                if parent in cells and cells[parent].get('vertex')=='1':
                    p=box(parent,stack+(ident,));x+=p['x'];y+=p['y']
                    if values[0]<0 or values[1]<0 or values[0]+w>p['w']+.1 or values[1]+h>p['h']+.1:
                        err('geometry','child outside group: '+ident)
                boxes[ident]={'x':x,'y':y,'w':w,'h':h}
                return boxes[ident]
            for c in objects:
                if c.get('vertex')=='1':box(c.get('id'))
            if graph and page.get('id')==graph.get('page_id','main'):
                findings['scientific_consistency']+=graph_errors(graph)
                expected_edges={e['id']:e for e in graph['edges']}
                actual_edges={c.get('id'):c for c in objects if c.get('edge')=='1'}
                if set(expected_edges)!=set(actual_edges):err('scientific_consistency','missing or extra scientific edges')
                expected_nodes={n['id'] for n in graph['nodes']}
                expected_aux={'pfa-title'}|{g['id'] for g in graph.get('groups',[])}
                for n in graph['nodes']:
                    c=cells.get(n['id'])
                    if c is None or c.get('vertex')!='1':err('scientific_consistency','missing node: '+n['id']);continue
                    if n.get('type')!='image' and c.get('value')!=n['label']:err('scientific_consistency','node label differs: '+n['id'])
                    if n.get('type')!='image' and ('image=' in c.get('style','') or styles(c).get('shape')=='image'):
                        err('scientific_consistency','native scientific object replaced by image: '+n['id'])
                    if n.get('type')=='image':expected_aux.update([n['id']+'-image',n['id']+'-label'])
                actual_nodes={c.get('id') for c in objects if c.get('vertex')=='1'}
                if actual_nodes-expected_nodes-expected_aux:err('scientific_consistency','unexpected scientific/visual nodes; record them in graph')
                for eid,e in expected_edges.items():
                    c=actual_edges.get(eid)
                    if c is not None:
                        if (c.get('source'),c.get('target'))!=(e['source'],e['target']):err('scientific_consistency','reversed or altered edge: '+eid)
                        s=styles(c)
                        dashed=s.get('dashed')=='1'
                        if (e['kind'] in ('control','supervision','grouping'))!=dashed:err('scientific_consistency','relation style mismatch: '+eid)
            # Ancestors are containers, not obstacles to their children.
            def ancestors(ident):
                seen=set()
                while ident in cells and ident not in seen:
                    seen.add(ident);ident=cells[ident].get('parent')
                return seen
            paths=[];all_points=[];label_boxes=[]
            for c in objects:
                if c.get('edge')!='1':continue
                s=styles(c);source=c.get('source');target=c.get('target')
                if source not in boxes or target not in boxes:err('structure','edge endpoint is not a vertex');continue
                ports=[]
                for key,b in (('exit',boxes[source]),('entry',boxes[target])):
                    u,v=float(s.get(key+'X',.5)),float(s.get(key+'Y',.5))
                    if not 0<=u<=1 or not 0<=v<=1 or (u not in (0,1) and v not in (0,1)):err('structure','invalid boundary port: '+c.get('id'))
                    ports.append((b['x']+u*b['w'],b['y']+v*b['h']))
                g=c.find('mxGeometry')
                if g is None:err('structure','edge geometry missing');continue
                mids=[(float(p.get('x',0)),float(p.get('y',0))) for p in g.findall("Array[@as='points']/mxPoint")]
                pts=[ports[0],*mids,ports[1]];all_points+=pts
                for a,b,d in zip(pts,pts[1:],pts[2:]):
                    if (a[0]==b[0]==d[0]) or (a[1]==b[1]==d[1]):
                        err('geometry','redundant collinear waypoint: '+c.get('id'))
                excluded=ancestors(source)|ancestors(target)
                for a,b in zip(pts,pts[1:]):
                    for ident,ob in boxes.items():
                        if ident not in excluded and not (ancestors(ident)&{source,target}) and hits(a,b,ob,2):
                            err('geometry','line crosses node/text/image: '+c.get('id')+'/'+ident)
                if len(pts)>3 and not (graph and any(e['id']==c.get('id') and e.get('feedback') for e in graph['edges'])):
                    # Detours are allowed if obstacle avoidance needed; exposed metric for host review.
                    pass
                if c.get('value'):
                    # mxGeometry x=0 labels at half path; y displaces normal to segment.
                    total=sum(abs(b[0]-a[0])+abs(b[1]-a[1]) for a,b in zip(pts,pts[1:]));walk=0
                    for a,b in zip(pts,pts[1:]):
                        length=abs(b[0]-a[0])+abs(b[1]-a[1])
                        if walk+length>=total/2 and length:
                            t=(total/2-walk)/length;offset=float(g.get('y',0));dx=b[0]-a[0];dy=b[1]-a[1]
                            cx=a[0]+t*dx+dy/length*offset;cy=a[1]+t*dy-dx/length*offset
                            font=float(s.get('fontSize',12));w=float(s.get('labelWidth',sum(1 if ord(ch)>127 else .6 for ch in c.get('value'))*font))
                            lb={'x':cx-w/2,'y':cy-font*.6,'w':w,'h':font*1.2};label_boxes.append((c.get('id'),lb));break
                        walk+=length
                paths.append((c.get('id'),pts,s))
            def overlap(a,b):return max(a['x'],b['x'])<min(a['x']+a['w'],b['x']+b['w']) and max(a['y'],b['y'])<min(a['y']+a['h'],b['y']+b['h'])
            for i,(ident,b) in enumerate(boxes.items()):
                for other,o in list(boxes.items())[i+1:]:
                    if ident not in ancestors(other) and other not in ancestors(ident) and overlap(b,o):err('geometry','overlapping vertices: '+ident+'/'+other)
            for i,(eid,b) in enumerate(label_boxes):
                for ident,o in boxes.items():
                    if styles(cells[ident]).get('container')!='1' and overlap(b,o):err('geometry','edge label collides: '+eid+'/'+ident)
                for other,o in label_boxes[i+1:]:
                    if overlap(b,o):err('geometry','edge label collision: '+eid+'/'+other)
            for i,(eid,pts,s) in enumerate(paths):
                for other,q,t in paths[i+1:]:
                    if any(crosses(a,b,c,d) for a,b in zip(pts,pts[1:]) for c,d in zip(q,q[1:])) and s.get('jumpStyle')!='arc' and t.get('jumpStyle')!='arc':
                        err('geometry','ambiguous crossing: '+eid+'/'+other)
                    ec,oc=cells[eid],cells[other]
                    if not {ec.get('source'),ec.get('target')}&{oc.get('source'),oc.get('target')}:
                        for a,b in zip(pts,pts[1:]):
                            for c,d in zip(q,q[1:]):
                                shared=(a[0]==b[0]==c[0]==d[0] and max(min(a[1],b[1]),min(c[1],d[1]))<min(max(a[1],b[1]),max(c[1],d[1]))) or (a[1]==b[1]==c[1]==d[1] and max(min(a[0],b[0]),min(c[0],d[0]))<min(max(a[0],b[0]),max(c[0],d[0])))
                                if shared:err('geometry','unrelated flows share segment: '+eid+'/'+other)
            if boxes:
                left=min([b['x'] for b in boxes.values()]+[p[0] for p in all_points]);right=max([b['x']+b['w'] for b in boxes.values()]+[p[0] for p in all_points])
                factor=display_width_mm/25.4*72/max(1,right-left)
                top=min([b['y'] for b in boxes.values()]+[p[1] for p in all_points]);bottom=max([b['y']+b['h'] for b in boxes.values()]+[p[1] for p in all_points])
                leaf_area=sum(b['w']*b['h'] for ident,b in boxes.items() if not any(c.get('parent')==ident for c in objects))
                fonts=[]
                for ident,c in cells.items():
                    if c.get('value') and (c.get('vertex')=='1' or c.get('edge')=='1'):
                        pt=float(styles(c).get('fontSize',12))*factor
                        fonts.append({'id':ident,'print_pt':round(pt,2)})
                        if pt<6.5:err('geometry',f'print font too small: {ident} {pt:.2f}pt')
                metrics.append({'page':page.get('id'),'bounding_box':[left,top,right,bottom], 'display_width_mm':display_width_mm,
                                'approximate_unoccupied_ratio':round(max(0,1-leaf_area/max(1,(right-left)*(bottom-top))),3),
                                'fonts':fonts,'note':'Whitespace and group sizes are review evidence, not universal aesthetic thresholds.'})
                if graph:
                    for aligned in graph.get('alignment_groups',[]):
                        axis=aligned['axis'];size='w' if axis=='x' else 'h'
                        values=[boxes[i][axis]+boxes[i][size]/2 for i in aligned['ids']]
                        if max(values)-min(values)>aligned.get('tolerance',1):err('geometry','misaligned centers: '+','.join(aligned['ids']))
            for r in requirements:
                if r.get('status')!='active':continue
                for constraint in r.get('checks',[]):
                    c=cells.get(constraint['id'])
                    if constraint['kind']=='label' and (c is None or c.get('value')!=constraint['value']):err('history','active label requirement violated: '+r['id'])
                    if constraint['kind']=='edge' and (c is None or c.get('source')!=constraint['source'] or c.get('target')!=constraint['target']):err('history','active edge requirement violated: '+r['id'])
        if graph and not any(p.get('id')==graph.get('page_id','main') for p in pages):err('scientific_consistency','semantic page missing')
    except (ValueError, KeyError, TypeError, OSError, AttributeError, ET.ParseError) as exc:
        err('structure',str(exc))
    report={k:{'status':'fail' if v else 'pass','findings':sorted(set(v))} for k,v in findings.items()}
    if graph is None:report['scientific_consistency']={'status':'not_run','findings':['No semantic baseline supplied']}
    report.update(figure_sha256=digest(path), metrics=metrics, status='fail' if any(v for v in findings.values()) else 'pass',
                  limitation='Checks establish internal consistency and conservative geometry; scientific interpretation and rendered typography require host review.')
    return report
