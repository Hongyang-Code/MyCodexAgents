import base64
import copy
import mimetypes
import xml.etree.ElementTree as ET
from pathlib import Path
from .layout import PORTS
from .storage import parse_xml, write_xml, digest, atomic

SHAPES={'process':'rectangle','data':'rectangle','tensor':'cube','decision':'rhombus',
        'state':'ellipse','storage':'cylinder','annotation':'text','image':'image'}
EDGE_STYLES={'data':'endArrow=block;endFill=1;', 'control':'dashed=1;endArrow=open;',
             'supervision':'dashed=1;dashPattern=2 3;endArrow=block;endFill=0;',
             'spatial':'endArrow=none;', 'grouping':'endArrow=none;dashed=1;'}


def style(values):
    return ';'.join(f'{k}={v}' for k,v in values.items())+';'


def styles(cell):
    return dict(v.split('=',1) for v in cell.get('style','').split(';') if '=' in v)


def cell(root, ident, value, parent, box, styling, **attrs):
    c=ET.SubElement(root,'mxCell',id=ident,value=value,parent=parent,style=styling,vertex='1',**attrs)
    ET.SubElement(c,'mxGeometry',x=str(box['x']),y=str(box['y']),width=str(box['w']),height=str(box['h']),attrib={'as':'geometry'})
    return c


def build(graph,plan,guide,assets,output,base_dir=None):
    nodes=graph['nodes'];boxes=plan['nodes'];base_dir=Path(base_dir or '.')
    xml=ET.Element('mxfile',host='PaperFigureAgent',compressed='false')
    d=ET.SubElement(xml,'diagram',id=graph.get('page_id','main'),name=graph.get('title','Figure'))
    model=ET.SubElement(d,'mxGraphModel',grid='0',page='0',math='0',background=guide.get('background','#FFFFFF'))
    root=ET.SubElement(model,'root');ET.SubElement(root,'mxCell',id='0');ET.SubElement(root,'mxCell',id='1',parent='0')
    width=max((b['x']+b['w'] for b in boxes.values()),default=500)+40
    width=max(width,max((p[0] for e in plan['edges'].values() for p in e['points']),default=0)+40)
    # Convert physical print size to editor units using effective bounding width.
    mm=guide.get('display_width_mm',180);factor=(width-20)/(mm/25.4*72)
    font=guide.get('font_pt',9)*factor
    base={'html':0,'whiteSpace':'wrap','fontFamily':guide.get('font','Arial'),'fontSize':round(font,2),
          'fontColor':guide.get('text','#202C38'),'strokeWidth':guide.get('line_width',1.5),'align':'center','verticalAlign':'middle','spacing':8}
    groups={}
    for group in graph.get('groups',[]):
        members=[boxes[n['id']] for n in nodes if n.get('parent')==group['id']]
        if not members:raise ValueError('Empty group')
        x=min(b['x'] for b in members)-22;y=min(b['y'] for b in members)-38
        w=max(b['x']+b['w'] for b in members)-x+22;h=max(b['y']+b['h'] for b in members)-y+22
        box={'x':x,'y':y,'w':w,'h':h};groups[group['id']]=box
        cell(root,group['id'],group['label'],'1',box,style({**base,'rounded':1,'arcSize':8,'fillColor':guide.get('group_fill','#F7F8FA'),
             'strokeColor':guide.get('group_stroke','#D5DAE0'),'verticalAlign':'top','fontSize':round(font*.87,2),'container':1,'collapsible':0,'connectable':0}))
    if graph.get('title'):
        cell(root,'pfa-title',graph['title'],'1',{'x':40,'y':12,'w':width-60,'h':44},style({**base,'shape':'text','strokeColor':'none','fillColor':'none','align':'left','fontStyle':1,'fontSize':round(font*1.3,2)}))
    asset_map={a['id']:a for a in assets}
    for n in nodes:
        box=dict(boxes[n['id']]);parent=n.get('parent','1')
        if parent!='1':box['x']-=groups[parent]['x'];box['y']-=groups[parent]['y']
        role=guide.get('roles',{}).get(n.get('role','default'),{})
        styling={**base,'shape':SHAPES[n.get('type','process')], 'rounded':0 if n.get('type')=='data' else 1,'arcSize':guide.get('arc_size',12),
                 'fillColor':role.get('fill','#FFFFFF'),'strokeColor':role.get('stroke','#637080'),
                 'fontColor':role.get('text',base['fontColor'])}
        if n.get('type')=='image':
            asset=asset_map[n['asset_id']];path=Path(asset['path'])
            if not path.is_absolute():path=base_dir/path
            if digest(path)!=asset['sha256']:raise ValueError('Asset changed: '+asset['id'])
            mime=mimetypes.guess_type(path)[0]
            if mime not in ('image/png','image/jpeg','image/gif','image/webp'):raise ValueError('Only traceable raster image assets supported')
            group=cell(root,n['id'],'',parent,box,'group;'+style({'container':1,'collapsible':0}))
            cell(root,n['id']+'-image','',n['id'],{'x':0,'y':0,'w':box['w'],'h':max(1,box['h']-24)},
                 style({'shape':'image','aspect':'fixed','imageAspect':1,'image':'data:'+mime+','+base64.b64encode(path.read_bytes()).decode()}))
            cell(root,n['id']+'-label',n['label'],n['id'],{'x':0,'y':box['h']-24,'w':box['w'],'h':24},style({**base,'shape':'text','strokeColor':'none','fillColor':'none'}))
        else:
            cell(root,n['id'],n['label'],parent,box,style(styling))
    for e in graph['edges']:
        r=plan['edges'][e['id']];sx,sy=PORTS[r['source_port']];tx,ty=PORTS[r['target_port']]
        attrs={**base,'rounded':0,'orthogonalLoop':1,'jettySize':'auto','endSize':guide.get('arrow_size',8),'strokeWidth':guide.get('edge_width',1.6),
               'strokeColor':guide.get('edge','#667484'),'fontSize':round(font*.78,2),'labelBackgroundColor':guide.get('background','#FFFFFF'),
               'exitX':sx,'exitY':sy,'entryX':tx,'entryY':ty,'exitPerimeter':1,'entryPerimeter':1,'jumpStyle':'arc','jumpSize':7,
               'whiteSpace':'nowrap','labelWidth':round(max(20,sum(1 if ord(ch)>127 else .6 for ch in e.get('label',''))*font*.78+10),2)}
        c=ET.SubElement(root,'mxCell',id=e['id'],value=e.get('label',''),parent='1',edge='1',source=e['source'],target=e['target'],
                        style=style(attrs)+EDGE_STYLES[e.get('kind','data')])
        geometry=ET.SubElement(c,'mxGeometry',relative='1',x='0',y=str(r.get('label_offset',-14)),attrib={'as':'geometry'})
        if len(r['points'])>2:
            points=ET.SubElement(geometry,'Array',attrib={'as':'points'})
            for x,y in r['points'][1:-1]:ET.SubElement(points,'mxPoint',x=str(x),y=str(y))
    write_xml(output,xml)
    return xml


def cells_by_page(root):
    pages={}
    for d in root.findall('diagram'):
        cells={}
        for c in d.iter('mxCell'):
            cells[c.get('id')]=ET.tostring(c,encoding='unicode')
        pages[d.get('id')]=cells
    return pages


def diff(before,after):
    a=cells_by_page(parse_xml(before));b=cells_by_page(parse_xml(after));result={}
    for page in sorted(a.keys()|b.keys()):
        x=a.get(page,{});y=b.get(page,{})
        result[page]={'added':sorted(y.keys()-x.keys()),'removed':sorted(x.keys()-y.keys()),
                      'changed':[i for i in x.keys()&y.keys() if x[i]!=y[i]]}
    return result


def patch(source,output,operations,expected_hash=None):
    """Targeted XML edits; preserve unrelated objects/pages; never regenerate layout."""
    if Path(source).resolve()==Path(output).resolve():raise ValueError('Output must be a new file; preserve original')
    if Path(output).exists():raise ValueError('Refusing to overwrite existing output')
    if expected_hash and digest(source)!=expected_hash:raise ValueError('Source changed; stale patch blocked')
    xml=parse_xml(source)
    for op in operations:
        d=next((d for d in xml.findall('diagram') if d.get('id')==op['page']),None)
        if d is None:raise ValueError('Unknown page')
        objects={c.get('id'):c for c in d.iter('mxCell')}
        c=objects[op['id']];action=op['action']
        if action=='label':c.set('value',op['value'])
        elif action=='move':
            g=c.find('mxGeometry')
            if g is None or c.get('edge')=='1':raise ValueError('Move requires a vertex or group')
            g.set('x',str(float(g.get('x',0))+op['dx']));g.set('y',str(float(g.get('y',0))+op['dy']))
        elif action=='reconnect':
            for key in ('source','target'):
                if key in op:
                    if op[key] not in objects:raise ValueError('Unknown connection endpoint')
                    c.set(key,op[key])
            g=c.find('mxGeometry')
            for arr in list(g.findall('Array')):g.remove(arr)
        elif action=='style':
            values=styles(c);values.update(op['values']);c.set('style',style(values))
        else:raise ValueError('Unsupported targeted operation: '+action)
    # Save an immutable original next to revision before writing edited XML.
    backup=Path(output).with_suffix('.before.drawio')
    if backup.exists():raise ValueError('Backup path already exists')
    atomic(backup,Path(source).read_bytes())
    write_xml(output,xml)
    return diff(source,output)
