"""Create intentionally incorrect PPTX copies for acceptance review; never deliver them."""
import argparse
import json
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import check_deck


def make_faults(source, destination):
    destination = Path(destination)
    if destination.exists() or destination.resolve() == Path(source).resolve():
        raise ValueError('Use a new fault-copy path')
    ns=check_deck.NS
    for key,value in ns.items(): ET.register_namespace(key,value)
    with zipfile.ZipFile(source) as src, zipfile.ZipFile(destination,'x',zipfile.ZIP_DEFLATED) as dst:
        for info in src.infolist():
            raw=src.read(info.filename)
            if info.filename=='ppt/slides/slide1.xml':
                node=ET.fromstring(raw)
                for shape in node.findall('.//p:sp',ns):
                    name=shape.find('p:nvSpPr/p:cNvPr',ns)
                    if name is not None and name.get('name')=='body-158':
                        t=shape.find('.//a:t',ns)
                        t.text='本方法已在所有场景证明有效。'+('由于该方法能够通过多阶段过程对数据进行处理从而实现更好的表现，'*12)
                        shape.find('p:spPr/a:xfrm/a:off',ns).set('x','11500000')
                connector=node.find('.//p:cxnSp/p:nvCxnSpPr/p:cNvCxnSpPr',ns)
                a,b=connector.find('a:stCxn',ns),connector.find('a:endCxn',ns)
                ai,bi=dict(a.attrib),dict(b.attrib);a.attrib.clear();a.attrib.update(bi);b.attrib.clear();b.attrib.update(ai)
                raw=ET.tostring(node,encoding='utf-8',xml_declaration=True)
            elif info.filename=='ppt/slides/slide2.xml':
                node=ET.fromstring(raw)
                for t in node.findall('.//a:t',ns):
                    if t.text=='差值为 0.02；未做显著性检验':t.text='差值为20%，已证明显著改善'
                raw=ET.tostring(node,encoding='utf-8',xml_declaration=True)
            elif info.filename.endswith('/chart1.xml'):
                node=ET.fromstring(raw)
                values=node.findall('.//c:ser/c:val//c:pt/c:v',ns)
                if len(values)>1:values[1].text='0.92'
                raw=ET.tostring(node,encoding='utf-8',xml_declaration=True)
            dst.writestr(info,raw)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source');parser.add_argument('destination');parser.add_argument('--requirements',required=True)
    args=parser.parse_args();make_faults(args.source,args.destination)
    result=check_deck.check(args.destination,json.loads(Path(args.requirements).read_text(encoding='utf-8')))
    print(json.dumps(result,ensure_ascii=False,indent=2))
    if result['status']!='fail':raise SystemExit('Fault injection was not caught')
