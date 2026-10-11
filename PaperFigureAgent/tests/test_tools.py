import base64
import copy
import json
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zlib
from pathlib import Path
from urllib.parse import quote
from unittest.mock import patch as mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'examples'))
from paperfigure import storage, layout, drawio, qa, adapters
from paperfigure.cli import audit, deliver
from cases import CASES


class FigureTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.graph=copy.deepcopy(CASES[0]['graph']);self.path=self.root/'test.drawio'
        self.guide={'display_width_mm':180,'font_pt':9}
        self.make()

    def make(self):drawio.build(self.graph,layout.plan(self.graph),self.guide,[],self.path,self.root)
    def result(self):return qa.check(self.path,self.graph)
    def change(self,fn):
        xml=storage.parse_xml(self.path);fn(xml);storage.write_xml(self.path,xml)
    def c(self,root,ident):return next(c for c in root.iter('mxCell') if c.get('id')==ident)
    def test_three_topologies(self):
        for case in CASES:
            self.graph=copy.deepcopy(case['graph']);self.make()
            self.assertEqual(self.result()['status'],'pass',self.result())
    def test_duplicate_id(self):
        self.change(lambda r:self.c(r,'score').set('id','obs'));self.assertEqual(self.result()['status'],'fail')
    def test_invalid_reference(self):
        self.change(lambda r:self.c(r,'e1').set('target','missing'));self.assertEqual(self.result()['status'],'fail')
    def test_invalid_port(self):
        self.change(lambda r:self.c(r,'e1').set('style',self.c(r,'e1').get('style')+'entryX=2;'));self.assertEqual(self.result()['status'],'fail')
    def test_parent_cycle(self):
        self.change(lambda r:self.c(r,'obs').set('parent','obs'));self.assertEqual(self.result()['status'],'fail')
    def test_missing_scientific_edge(self):
        self.change(lambda r:r.find('diagram/mxGraphModel/root').remove(self.c(r,'e3')))
        self.assertEqual(self.result()['scientific_consistency']['status'],'fail')
    def test_reversed_scientific_edge(self):
        self.change(lambda r:(self.c(r,'e3').set('source','fusion'),self.c(r,'e3').set('target','filter')))
        self.assertEqual(self.result()['scientific_consistency']['status'],'fail')
    def test_extra_scientific_node(self):
        self.change(lambda r:drawio.cell(r.find('diagram/mxGraphModel/root'),'invented','Unfounded','1',{'x':10,'y':600,'w':100,'h':80},'fontSize=20;'))
        self.assertEqual(self.result()['scientific_consistency']['status'],'fail')
    def test_bitmap_disguise(self):
        self.change(lambda r:self.c(r,'fusion').set('style','shape=image;image=data:image/png;base64,FAKE;'))
        self.assertEqual(self.result()['scientific_consistency']['status'],'fail')
    def test_small_font(self):
        self.change(lambda r:self.c(r,'fusion').set('style',self.c(r,'fusion').get('style')+'fontSize=2;'))
        self.assertTrue(any('font too small' in f for f in self.result()['geometry']['findings']))
    def test_alignment_constraint(self):
        self.graph['alignment_groups']=[{'axis':'y','ids':['obs','fusion','score']}]
        self.assertEqual(self.result()['geometry']['status'],'pass')
        self.change(lambda r:self.c(r,'score').find('mxGeometry').set('y','180'))
        self.assertTrue(any('misaligned centers' in f for f in self.result()['geometry']['findings']))
    def test_line_through_node(self):
        def corrupt(root):
            edge=self.c(root,'e5');g=edge.find('mxGeometry');arr=ET.SubElement(g,'Array',attrib={'as':'points'})
            ET.SubElement(arr,'mxPoint',x='400',y='120');ET.SubElement(arr,'mxPoint',x='400',y='300')
        self.change(corrupt);self.assertEqual(self.result()['geometry']['status'],'fail')
    def test_overlapping_vertices(self):
        self.change(lambda r:self.c(r,'filter').find('mxGeometry').set('y','250'))
        self.assertEqual(self.result()['geometry']['status'],'fail')
    def test_unresolved_science(self):
        self.graph['unresolved']=['unknown input'];self.assertTrue(qa.graph_errors(self.graph))
    def test_unmarked_cycle(self):
        self.graph['edges'].append({'id':'back','source':'score','target':'obs','kind':'data','evidence':'fixture'})
        with self.assertRaises(ValueError):layout.plan(self.graph)
    def test_route_avoids_obstacle(self):
        box={'x':40,'y':-10,'w':20,'h':20};route=layout.route((0,0),(100,0),[box])
        self.assertFalse(any(layout.hits(a,b,box) for a,b in zip(route,route[1:])))
        self.assertGreater(len(route),2)
    def test_direct_route_minimal(self):self.assertEqual(layout.route((0,0),(100,0),[]),[(0,0),(100,0)])
    def test_active_requirement_regression(self):
        req=[{'id':'R2','status':'active','checks':[{'id':'fusion','kind':'label','value':'Corrected'}]}]
        self.assertEqual(qa.check(self.path,self.graph,req)['history']['status'],'fail')
    def test_superseded_requirement_ignored(self):
        req=[{'id':'R1','status':'superseded','checks':[{'id':'fusion','kind':'label','value':'old'}]}]
        self.assertEqual(qa.check(self.path,self.graph,req)['history']['status'],'pass')
    def test_targeted_label_other_page_preserved(self):
        self.change(lambda r:r.append(copy.deepcopy(r.find('diagram'))))
        xml=storage.parse_xml(self.path);xml.findall('diagram')[1].set('id','other');storage.write_xml(self.path,xml)
        before=ET.tostring(xml.findall('diagram')[1]);out=self.root/'edited.drawio'
        diff=drawio.patch(self.path,out,[{'page':'main','id':'fusion','action':'label','value':'融合处理'}],storage.digest(self.path))
        self.assertEqual(diff['main']['changed'],['fusion']);self.assertEqual(diff['other']['changed'],[])
        self.assertEqual(before,ET.tostring(storage.parse_xml(out).findall('diagram')[1]))
    def test_move_group_only(self):
        self.graph=copy.deepcopy(CASES[1]['graph']);self.make();out=self.root/'moved.drawio'
        result=drawio.patch(self.path,out,[{'page':'main','id':'control','action':'move','dx':0,'dy':-30}],storage.digest(self.path))
        self.assertEqual(result['main']['changed'],['control'])
        self.assertEqual(self.c(storage.parse_xml(out),'b4').get('source'),'ambient')
    def test_reconnect_minimal(self):
        out=self.root/'rewire.drawio';d=drawio.patch(self.path,out,[{'page':'main','id':'e5','action':'reconnect','source':'filter'}],storage.digest(self.path))
        self.assertEqual(d['main']['changed'],['e5'])
    def test_stale_patch(self):
        with self.assertRaises(ValueError):drawio.patch(self.path,self.root/'edit.drawio',[],'stale')
    def test_no_overwrite_source(self):
        with self.assertRaises(ValueError):drawio.patch(self.path,self.path,[])
    def test_compressed_import(self):
        root=storage.parse_xml(self.path);d=root.find('diagram');model=d.find('mxGraphModel')
        enc=zlib.compressobj(wbits=-15);raw=quote(ET.tostring(model,encoding='unicode')).encode()
        encoded=base64.b64encode(enc.compress(raw)+enc.flush()).decode();d.remove(model);d.text=encoded
        storage.atomic(self.path,ET.tostring(root));self.assertIsNotNone(storage.parse_xml(self.path).find('diagram/mxGraphModel'))
    def test_entity_rejected(self):
        storage.atomic(self.path,'<!DOCTYPE mxfile [<!ENTITY x "bad">]><mxfile/>')
        with self.assertRaises(ValueError):storage.parse_xml(self.path)
    def test_tasks_isolated_and_natural_start(self):
        a=storage.start(self.root,'Draw an enzyme loop');b=storage.start(self.root,'A telescope pipeline')
        self.assertNotEqual(a,b);self.assertNotIn('enzyme',(b/'brief.json').read_text())
        self.assertEqual(storage.read_json(b/'brief.json')['display_width_mm'],180)
    def test_requirement_supersedes(self):
        task=storage.start(self.root,'Use old label');storage.add_requirement(task,'Use corrected label',['fusion'],['R001'])
        reqs=storage.read_json(task/'requirements.json');self.assertEqual(reqs[0]['status'],'superseded');self.assertEqual(reqs[1]['status'],'active')
    def test_round_limit_and_resume(self):
        task=storage.start(self.root,'Draw a graph')
        for i in range(3):storage.checkpoint(task,'repair',True)
        with self.assertRaises(ValueError):storage.checkpoint(task,'repair',True)
        self.assertEqual(storage.read_json(task/'state.json')['optimization_rounds'],3)
    def test_native_missing_is_not_run(self):
        with mock.object(adapters,'discover_drawio',return_value=None):self.assertEqual(adapters.render(self.path,self.root/'no.png')['status'],'not_run')
    def test_changed_asset_blocked(self):
        graph=copy.deepcopy(self.graph);graph['nodes'][0].update(type='image',asset_id='a')
        img=self.root/'source.png';img.write_bytes(b'changed')
        with self.assertRaises(ValueError):drawio.build(graph,layout.plan(graph),self.guide,[{'id':'a','path':str(img),'sha256':'old'}],self.root/'bad.drawio')
    def test_malformed_xml_reported(self):
        storage.atomic(self.path,'<mxfile>');self.assertEqual(self.result()['structure']['status'],'fail')
    def test_group_bounds(self):
        self.graph=copy.deepcopy(CASES[1]['graph']);self.make()
        self.change(lambda r:self.c(r,'ambient').find('mxGeometry').set('x','-100'))
        self.assertEqual(self.result()['geometry']['status'],'fail')
    def test_edge_label_native_and_no_wrap(self):
        self.graph=copy.deepcopy(CASES[2]['graph']);self.make();c=self.c(storage.parse_xml(self.path),'c5')
        self.assertEqual(c.get('value'),'否：继续迭代');self.assertEqual(drawio.styles(c)['whiteSpace'],'nowrap')
        self.assertGreater(float(drawio.styles(c)['labelWidth']),20)
    def test_label_collision_flagged(self):
        self.graph=copy.deepcopy(CASES[2]['graph']);self.make()
        self.change(lambda r:self.c(r,'c5').find('mxGeometry').set('y','-50'))
        self.assertTrue(any('label collides' in f for f in self.result()['geometry']['findings']))
    def test_redundant_bend_flagged(self):
        def corrupt(root):
            c=self.c(root,'e5');g=c.find('mxGeometry')
            arr=ET.SubElement(g,'Array',attrib={'as':'points'})
            ET.SubElement(arr,'mxPoint',x='1030',y='212');ET.SubElement(arr,'mxPoint',x='1040',y='212')
        self.change(corrupt)
        self.assertTrue(any('collinear' in f for f in self.result()['geometry']['findings']))
    def test_ambiguous_crossing(self):
        self.graph={'nodes':[{'id':i,'label':i,'type':'process','evidence':'synthetic'} for i in 'abcd'],
                    'edges':[{'id':'x','source':'a','target':'b','kind':'data','evidence':'synthetic'},
                             {'id':'y','source':'c','target':'d','kind':'data','evidence':'synthetic'}]}
        boxes={'a':{'x':0,'y':100,'w':60,'h':60},'b':{'x':340,'y':100,'w':60,'h':60},
               'c':{'x':170,'y':0,'w':60,'h':60},'d':{'x':170,'y':220,'w':60,'h':60}}
        plan={'nodes':boxes,'edges':{'x':{'source_port':'right','target_port':'left','points':[(60,130),(340,130)]},
                                    'y':{'source_port':'bottom','target_port':'top','points':[(200,60),(200,220)]}}}
        drawio.build(self.graph,plan,self.guide,[],self.path)
        self.change(lambda r:[c.set('style',c.get('style','').replace('jumpStyle=arc;','')) for c in r.iter('mxCell') if c.get('edge')=='1'])
        self.assertTrue(any('ambiguous crossing' in f for f in self.result()['geometry']['findings']))
    def test_image_group_children_and_connection_preserved(self):
        img=self.root/'pixel.png';img.write_bytes(base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aY1kAAAAASUVORK5CYII='))
        self.graph['nodes'][0].update(type='image',asset_id='image1')
        drawio.build(self.graph,layout.plan(self.graph),self.guide,[{'id':'image1','path':str(img),'sha256':storage.digest(img)}],self.path)
        out=self.root/'image-moved.drawio'
        result=drawio.patch(self.path,out,[{'page':'main','id':'obs','action':'move','dx':-10,'dy':0}],storage.digest(self.path))
        self.assertEqual(result['main']['changed'],['obs'])
        root=storage.parse_xml(out);self.assertEqual(self.c(root,'obs-image').get('parent'),'obs');self.assertEqual(self.c(root,'e1').get('source'),'obs')


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.task=storage.start(self.root,'synthetic gate fixture');self.graph=copy.deepcopy(CASES[0]['graph'])
        storage.write_json(self.task/'semantic_graph.json',self.graph);storage.write_json(self.task/'style_guide.json',{'font_pt':9})
        self.figure=self.task/'figure.drawio';drawio.build(self.graph,layout.plan(self.graph),{'font_pt':9},[],self.figure)
        self.report=audit(self.task,self.figure);self.preview=self.task/'test.png';self.preview.write_bytes(b'SYNTHETIC_GATE_TEST_NOT_A_RENDER')
        self.review={'figure_sha256':storage.digest(self.figure),'baseline_hashes':self.report['baseline_hashes'],
                     **{k:{'status':'pass','evidence':'Synthetic record for gate unit test only'} for k in ('scientific','visual_full','visual_print','history')},
                     'requirements':[{'id':'R001','status':'pass','evidence':'synthetic fixture'}],
                     'edit':{'status':'not_run','evidence':'unit test, no interactive renderer'},'unresolved':[],
                     'native_render':{'status':'pass','figure_sha256':storage.digest(self.figure),'output_sha256':storage.digest(self.preview)}}
        self.review_path=self.task/'review.json'
    def result(self):
        storage.write_json(self.review_path,self.review)
        return deliver(self.task,self.figure,self.preview,self.review_path)
    def test_record_valid_not_evidence_of_reality(self):self.assertEqual(self.result()['status'],'pass')
    def test_missing_visual_review(self):
        self.review.pop('visual_print');self.assertEqual(self.result()['status'],'fail')
    def test_missing_active_requirement(self):
        self.review['requirements']=[];self.assertEqual(self.result()['status'],'fail')
    def test_old_figure(self):
        self.review['figure_sha256']='old';self.assertEqual(self.result()['status'],'fail')
    def test_old_preview(self):
        self.preview.write_bytes(b'changed');self.assertEqual(self.result()['status'],'fail')
    def test_changed_baseline(self):
        storage.add_requirement(self.task,'new required content');self.assertEqual(self.result()['status'],'fail')
    def test_wrong_asset(self):
        p=self.task/'data.csv';p.write_text('wrong');storage.write_json(self.task/'assets.json',[{'id':'a','path':str(p),'sha256':'wrong'}])
        self.assertEqual(audit(self.task,self.figure)['assets']['status'],'fail')
    def test_native_missing(self):
        self.review['native_render']['status']='not_run';self.assertEqual(self.result()['status'],'fail')
    def test_unresolved_blocked(self):
        self.review['unresolved']=['unknown science'];self.assertEqual(self.result()['status'],'fail')


if __name__=='__main__':unittest.main()
