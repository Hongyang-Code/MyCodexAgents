"""Inspect PPTX against explicit requirements; not a scientific or visual reviewer."""
import argparse
import hashlib
import json
import posixpath
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

NS = {'p': 'http://schemas.openxmlformats.org/presentationml/2006/main',
      'a': 'http://schemas.openxmlformats.org/drawingml/2006/main',
      'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships',
      'c': 'http://schemas.openxmlformats.org/drawingml/2006/chart',
      'm': 'http://schemas.openxmlformats.org/officeDocument/2006/math'}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def relations(z, part):
    path = posixpath.join(posixpath.dirname(part), '_rels', posixpath.basename(part) + '.rels')
    if path not in z.namelist():
        return {}
    out = {}
    for rel in ET.fromstring(z.read(path)):
        if rel.get('TargetMode') == 'External':
            continue
        target = rel.get('Target', '')
        resolved = posixpath.normpath(posixpath.join(posixpath.dirname(part), target)) if not target.startswith('/') else target[1:]
        if resolved.startswith('../') or resolved not in z.namelist():
            raise ValueError('unresolved internal relationship: ' + resolved)
        out[rel.get('Id')] = (resolved, rel.get('Type', '').rsplit('/', 1)[-1])
    return out


def text_of(node):
    return '\n'.join(''.join(p.itertext()) for p in node.findall('.//a:t', NS))


def normalized(value):
    return re.sub(r'\s+', '', value)


def inspect(path):
    with zipfile.ZipFile(path) as z:
        doc = ET.fromstring(z.read('ppt/presentation.xml'))
        rels = relations(z, 'ppt/presentation.xml')
        size = doc.find('p:sldSz', NS)
        width, height = int(size.get('cx')), int(size.get('cy'))
        slides = []
        for sid in doc.findall('p:sldIdLst/p:sldId', NS):
            part, kind = rels[sid.get('{'+NS['r']+'}id')]
            if kind != 'slide':
                raise ValueError('presentation order references a non-slide part')
            node = ET.fromstring(z.read(part))
            sr = relations(z, part)
            notes = '\n'.join(text_of(ET.fromstring(z.read(p))) for p, k in sr.values() if k == 'notesSlide')
            shapes = node.findall('.//p:sp', NS)
            names = [n.get('name', '') for n in node.findall('.//p:cNvPr', NS)]
            charts = []
            for cref in node.findall('.//c:chart', NS):
                cp, ck = sr[cref.get('{'+NS['r']+'}id')]
                if ck != 'chart':
                    raise ValueError('chart has wrong relationship type')
                cn = ET.fromstring(z.read(cp))
                values = [float(v.text) for v in cn.findall('.//c:ser/c:val//c:pt/c:v', NS)]
                axis = cn.find('.//c:valAx/c:scaling', NS)
                low = axis.find('c:min', NS) if axis is not None else None
                high = axis.find('c:max', NS) if axis is not None else None
                charts.append({'part': cp, 'values': values, 'text': '\n'.join(v.text or '' for v in cn.findall('.//c:v', NS)),
                               'y_range': [float(low.get('val')) if low is not None else None, float(high.get('val')) if high is not None else None],
                               'embedded_data': any(k == 'package' for _, k in relations(z, cp).values())})
            bounds = []
            # Top-level coordinates only: grouped transforms require visual/finalizer review.
            tree = node.find('p:cSld/p:spTree', NS)
            for obj in list(tree):
                if obj.tag not in ['{'+NS['p']+'}'+k for k in ('sp', 'pic', 'graphicFrame', 'cxnSp')]:
                    continue
                xf = obj.find('p:spPr/a:xfrm', NS)
                if xf is None:
                    xf = obj.find('p:xfrm', NS)
                if xf is None:
                    continue
                off, ext = xf.find('a:off', NS), xf.find('a:ext', NS)
                if off is None or ext is None:
                    continue
                x, y, w, h = (int(off.get('x')), int(off.get('y')), int(ext.get('cx')), int(ext.get('cy')))
                if x < 0 or y < 0 or x+w > width+9525 or y+h > height+9525:
                    name = obj.find('.//p:cNvPr', NS)
                    bounds.append(name.get('name', '') if name is not None else 'unnamed')
            slides.append({'text': text_of(node), 'notes': notes, 'names': names,
                           'text_shapes': sum(bool(s.findall('.//a:t', NS)) for s in shapes),
                           'tables': len(node.findall('.//a:tbl', NS)), 'charts': charts,
                           'connectors': len(node.findall('.//p:cxnSp', NS)),
                           'pictures': len(node.findall('.//p:pic', NS)),
                           'equations': len(node.findall('.//m:oMath', NS)), 'out_of_bounds': bounds})
        return {'size_emu': [width, height], 'slides': slides}


def validate(data, req):
    errors, warnings = [], []
    if not isinstance(req, dict) or req.get('schema_version') != 1:
        return {'status': 'fail', 'errors': ['requirements schema_version must be 1'], 'warnings': []}
    expected = req.get('slides')
    if not isinstance(expected, list) or not expected:
        return {'status': 'fail', 'errors': ['complete nonempty slide requirements required'], 'warnings': []}
    if req.get('slide_count') != len(expected) or len(data['slides']) != len(expected):
        errors.append('slide count or complete requirement list mismatch')
    if 'size_emu' in req and req['size_emu'] != data['size_emu']:
        errors.append('slide size mismatch')
    ids = [s.get('id') for s in expected]
    if any(not isinstance(i, str) or not re.fullmatch(r'S[0-9]+', i) for i in ids) or len(ids) != len(set(ids)):
        errors.append('missing/duplicate/invalid stable slide ids')
    for index, (actual, need) in enumerate(zip(data['slides'], expected), 1):
        prefix = str(index)+': '
        if not need.get('visible_contains'):
            errors.append(prefix+'visible content requirements required')
        for field, source in [('visible_contains', actual['text']), ('notes_contains', actual['notes'])]:
            values = need.get(field, [])
            if not isinstance(values, list) or any(not isinstance(v, str) or not v.strip() for v in values):
                errors.append(prefix+'invalid '+field)
                continue
            for value in values:
                if normalized(value) not in normalized(source):
                    errors.append(prefix+'missing '+field+': '+value)
        full = actual['text']+'\n'+actual['notes']+'\n'+'\n'.join(c['text'] for c in actual['charts'])
        for old in need.get('forbidden_text', []):
            if normalized(old) in normalized(full):
                errors.append(prefix+'forbidden old text: '+old)
        if re.search(r'\{\{.*?\}\}|\bTODO\b|Click to (?:add|edit)|待填写', full, re.I):
            errors.append(prefix+'unresolved placeholder')
        native = need.get('native_min', {})
        allowed = {'text_shapes', 'tables', 'charts', 'connectors', 'pictures', 'equations'}
        if set(native)-allowed or any(type(v) is not int or v < 0 for v in native.values()):
            errors.append(prefix+'invalid native object requirements')
        else:
            for kind, number in native.items():
                count = len(actual[kind]) if kind == 'charts' else actual[kind]
                if count < number:
                    errors.append(prefix+'missing native '+kind)
        for name in need.get('object_names', []):
            if name not in actual['names']:
                errors.append(prefix+'missing object '+name)
        for n, values in enumerate(need.get('chart_values', [])):
            if n >= len(actual['charts']) or actual['charts'][n]['values'] != values:
                errors.append(prefix+'chart data mismatch at chart '+str(n+1))
        for n, bounds in enumerate(need.get('chart_y_ranges', [])):
            if n >= len(actual['charts']) or actual['charts'][n].get('y_range') != bounds:
                errors.append(prefix+'chart axis range mismatch at chart '+str(n+1))
        if need.get('embedded_chart_data') and any(not c['embedded_data'] for c in actual['charts']):
            errors.append(prefix+'missing embedded chart data')
        if actual['out_of_bounds']:
            errors.append(prefix+'out of slide bounds: '+', '.join(actual['out_of_bounds']))
        if len(normalized(actual['text'])) > 450:
            warnings.append(prefix+'dense visible text; inspect and record disposition')
    return {'status': 'fail' if errors else 'pass', 'errors': errors, 'warnings': warnings}


def check(path, requirements):
    try:
        result = validate(inspect(path), requirements)
        result['pptx_sha256'] = digest(path)
        return result
    except (OSError, ValueError, KeyError, TypeError, AttributeError, ET.ParseError, zipfile.BadZipFile) as exc:
        return {'status': 'fail', 'errors': [str(exc)], 'warnings': []}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('pptx'); p.add_argument('--requirements', required=True)
    a = p.parse_args()
    try:
        result = check(a.pptx, json.loads(Path(a.requirements).read_text(encoding='utf-8-sig')))
        result['requirements_sha256'] = digest(a.requirements)
    except (OSError, ValueError) as exc:
        result = {'status': 'fail', 'errors': [str(exc)]}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return int(result['status'] != 'pass')


if __name__ == '__main__':
    raise SystemExit(main())
