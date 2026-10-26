import copy
import hashlib
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
import check_deck
import check_delivery


def slide():
    return {'text':'标题\n0.82\n仅本测试集\n未做显著性检验', 'notes':'来源：合成材料，样本10例',
            'names':['title','input','output'], 'text_shapes':4, 'tables':1,
            'charts':[{'part':'chart.xml','values':[0.8,0.82],'text':'平均 Dice','embedded_data':True,'y_range':[0,1]}],
            'connectors':1,'pictures':1,'equations':0,'out_of_bounds':[]}


def requirements():
    return {'schema_version':1,'slide_count':1,'size_emu':[12192000,6858000],
            'slides':[{'id':'S01','visible_contains':['标题','0.82','仅本测试集','未做显著性检验'],
                       'notes_contains':['来源：合成材料','样本10例'], 'native_min':{'text_shapes':3,'tables':1,'charts':1,'connectors':1,'pictures':1},
                       'object_names':['input','output'], 'chart_values':[[0.8,0.82]],'embedded_chart_data':True,
                       'forbidden_text':['旧项目']} ]}


class DeckTests(unittest.TestCase):
    def setUp(self):
        self.data={'size_emu':[12192000,6858000],'slides':[slide()]}
        self.req=requirements()

    def result(self): return check_deck.validate(self.data,self.req)['status']
    def test_valid(self): self.assertEqual(self.result(),'pass')
    def test_missing_slide(self):
        self.data['slides']=[]; self.assertEqual(self.result(),'fail')
    def test_wrong_count(self):
        self.req['slide_count']=2; self.assertEqual(self.result(),'fail')
    def test_duplicate_ids(self):
        self.req['slides']*=2; self.req['slide_count']=2; self.data['slides']*=2
        self.assertEqual(self.result(),'fail')
    def test_missing_condition(self):
        self.data['slides'][0]['text']='标题\n0.82'; self.assertEqual(self.result(),'fail')
    def test_condition_only_in_notes(self):
        self.data['slides'][0]['text']='标题\n0.82'
        self.data['slides'][0]['notes']+='仅本测试集 未做显著性检验'
        self.assertEqual(self.result(),'fail')
    def test_missing_source(self):
        self.data['slides'][0]['notes']='样本10例'; self.assertEqual(self.result(),'fail')
    def test_old_notes(self):
        self.data['slides'][0]['notes']+='旧项目'; self.assertEqual(self.result(),'fail')
    def test_placeholder(self):
        self.data['slides'][0]['text']+='{{标题}}'; self.assertEqual(self.result(),'fail')
    def test_chart_mismatch(self):
        self.data['slides'][0]['charts'][0]['values']=[0.8,0.92]; self.assertEqual(self.result(),'fail')
    def test_chart_axis_mismatch(self):
        self.req['slides'][0]['chart_y_ranges']=[[0,1]]
        self.data['slides'][0]['charts'][0]['y_range']=[0.79,0.83]
        self.assertEqual(self.result(),'fail')
    def test_bitmap_table_rejected(self):
        self.data['slides'][0]['tables']=0; self.assertEqual(self.result(),'fail')
    def test_missing_connector(self):
        self.data['slides'][0]['connectors']=0; self.assertEqual(self.result(),'fail')
    def test_missing_embedded_data(self):
        self.data['slides'][0]['charts'][0]['embedded_data']=False; self.assertEqual(self.result(),'fail')
    def test_finished_image_allowed(self):
        self.req['slides'][0]['native_min']={'text_shapes':2,'pictures':1}
        self.req['slides'][0].pop('chart_values'); self.req['slides'][0].pop('embedded_chart_data')
        self.data['slides'][0]['charts']=[]; self.data['slides'][0]['tables']=0
        self.assertEqual(self.result(),'pass')
    def test_geometry(self):
        self.data['slides'][0]['out_of_bounds']=['title']; self.assertEqual(self.result(),'fail')
    def test_dense_is_warning_not_deletion(self):
        self.data['slides'][0]['text']+='很长文字'*160
        r=check_deck.validate(self.data,self.req)
        self.assertEqual(r['status'],'pass'); self.assertTrue(r['warnings'])
    def test_semantic_overclaim_needs_review(self):
        self.data['slides'][0]['text']+='已证明所有场景显著改善'
        self.assertEqual(self.result(),'pass') # Explicitly demonstrates checker limitation.
    def test_invalid_schema(self):
        self.req['schema_version']=99; self.assertEqual(self.result(),'fail')
    def test_real_zip_read_in_presentation_order(self):
        pns=check_deck.NS['p']; ans=check_deck.NS['a']; rns=check_deck.NS['r']
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'order.pptx'
            with zipfile.ZipFile(path,'w') as z:
                z.writestr('ppt/presentation.xml',f'<p:presentation xmlns:p="{pns}" xmlns:r="{rns}"><p:sldIdLst><p:sldId id="257" r:id="r2"/><p:sldId id="256" r:id="r1"/></p:sldIdLst><p:sldSz cx="12192000" cy="6858000"/></p:presentation>')
                z.writestr('ppt/_rels/presentation.xml.rels','<Relationships><Relationship Id="r1" Type="x/slide" Target="slides/slide1.xml"/><Relationship Id="r2" Type="x/slide" Target="slides/slide2.xml"/></Relationships>')
                for i in (1,2):
                    z.writestr(f'ppt/slides/slide{i}.xml',f'<p:sld xmlns:p="{pns}" xmlns:a="{ans}"><p:cSld><p:spTree><p:sp><p:txBody><a:p><a:r><a:t>页{i}</a:t></a:r></a:p></p:txBody></p:sp></p:spTree></p:cSld></p:sld>')
            self.assertEqual([s['text'] for s in check_deck.inspect(path)['slides']],['页2','页1'])


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.base=Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        def save(name,value):
            b=value.encode() if isinstance(value,str) else json.dumps(value,ensure_ascii=False).encode()
            (self.base/name).write_bytes(b)
            return {'path':name,'sha256':hashlib.sha256(b).hexdigest()}
        self.save=save
        copy_text='### [S01] 标题\n\n**页面文字：** 仅本测试集\n\n**来源：** 合成\n'
        original=save('original.md',copy_text); final=save('final.md',copy_text)
        contract=save('contract.json',{'content':[{'id':'c1','scope':'S01','requirement':'保留条件'}],
                                      'format':{'unit_level':3,'sections':[{'heading':'### [S01] 标题','required_markers':['**页面文字：**','**来源：**']}]}})
        tr={'status':'passed','revision_rounds':0,'validated_text_sha256':final['sha256'],'original_sha256':original['sha256'],
            'checks':{k:'pass' for k in ('readability','wording_rigor','semantic_fidelity','coverage','content_requirements','format_requirements')},
            'requirement_results':[{'id':'c1','status':'pass','evidence':'合成记录'}]}
        pptx=save('deck.pptx','fixture, actual PPTX tested separately')
        self.record={'schema_version':1,'mode':'materials','interaction':'direct','approval':{'state':'direct_authorized','evidence':'合成测试授权'},
                     'pptx':pptx,'requirements':save('requirements.json',requirements()),'copy_sha256':final['sha256'],'visual_revision_rounds':0,
                     'text_batches':[{'revision_rounds':0,'original':original,'final':final,'requirements':contract,'result':save('tr.json',tr)}],
                     'checks':{k:{'status':'pass','evidence':'合成测试记录'} for k in ('facts','coverage','narrative','copy_to_deck','editability','visual','design')},
                     'slides_reviewed':[{'id':'S01','image':save('s1.png','fixture'),'status':'pass','evidence':'合成记录','pptx_sha256':pptx['sha256']}],
                     'unresolved':[]}
        self.record['finalizer']=save('receipt.json',{'finalSha256':pptx['sha256'],'packageIntegrity':{'status':'pass'},'presentationLayout':{'exitCode':0},'firstPartyImport':{'passed':True}})
        self.record['design_review']={
            'status':'pass', 'pptx_sha256':pptx['sha256'],
            'references':[{'kind':'reference','source':'synthetic fixture','pages':'1','viewed':True,'adopt':'合成测试层级','avoid':'合成测试不适用元素'}],
            'slides':[{'id':'S01','status':'pass','image':self.record['slides_reviewed'][0]['image'],
                       'dimensions':{k:{'status':'pass','evidence':'合成记录，仅验证门槛'} for k in check_delivery.DESIGN_PAGE_DIMENSIONS}}],
            'whole_deck':{k:{'status':'pass','evidence':'合成记录，仅验证门槛'} for k in check_delivery.DESIGN_DECK_DIMENSIONS},
            'issues':[], 'user_style_feedback':{'state':'pending','evidence':'直接制作，用户尚未查看'}}
        self.record['audience_review']={'status':'pass','target_audience':'科研组会','reviewer_profile':'该领域资深教授','basis':'合成验收场景',
            'pptx_sha256':pptx['sha256'],'copy_sha256':final['sha256'],'revision_rounds':0,
            'dimensions':{k:{'status':'pass','evidence':'合成审查记录'} for k in ('evidence','reasoning','comparisons','communication','purpose')},
            'slides':[{'id':'S01','status':'pass','question':'是否夸大测试范围？','evidence':'页面保留仅本测试集和未做显著性检验。'}], 'issues':[]}
        self.addCleanup(patch.stopall)
        patch.object(check_deck,'check',return_value={'status':'pass','errors':[],'warnings':[]}).start()

    def result(self): return check_delivery.validate(self.record,self.base)['status']
    def test_valid_record(self): self.assertEqual(self.result(),'pass')
    def test_design_review_not_replaced_by_visual_check(self):
        del self.record['checks']['design']; self.assertEqual(self.result(),'fail')
    def test_design_details_required(self):
        del self.record['design_review']; self.assertEqual(self.result(),'fail')
    def test_design_missing_stale_or_failed(self):
        original=copy.deepcopy(self.record['design_review'])
        for change in ({'status':'unknown'}, {'pptx_sha256':'old'}, {'references':[]}, {'slides':[]}, {'whole_deck':{}}, {'issues':None}):
            with self.subTest(change=change):
                self.record['design_review']={**copy.deepcopy(original),**change}
                self.assertEqual(self.result(),'fail')
    def test_design_every_dimension_required(self):
        design=self.record['design_review']
        for dimensions in (design['slides'][0]['dimensions'], design['whole_deck']):
            for key in list(dimensions):
                with self.subTest(key=key):
                    item=dimensions.pop(key)
                    self.assertEqual(self.result(),'fail')
                    dimensions[key]=item
    def test_design_reference_and_preview(self):
        design=self.record['design_review']
        design['references'][0]['viewed']=False
        self.assertEqual(self.result(),'fail')
        design['references'][0]['viewed']=True
        design['slides'][0]['image']={'path':'old.png','sha256':'old'}
        self.assertEqual(self.result(),'fail')
    def test_design_issue_closure(self):
        issue={'id':'D01','scope':'S01','finding':'箭头偏移','impact':'阅读路径受干扰','action':'修正端点','recheck':'新渲染对齐','status':'resolved'}
        self.record['design_review']['issues']=[issue]
        self.assertEqual(self.result(),'pass')
        for key,value in [('status','open'),('recheck',''),('scope','S99')]:
            with self.subTest(key=key):
                self.record['design_review']['issues']=[{**issue,key:value}]
                self.assertEqual(self.result(),'fail')
    def test_design_user_feedback(self):
        self.record['design_review']['user_style_feedback']={'state':'rejected','evidence':'用户拒绝当前版本'}
        self.assertEqual(self.result(),'fail')
        self.record['design_review']['user_style_feedback']={'state':'accepted','evidence':''}
        self.assertEqual(self.result(),'fail')
    def test_missing_audience_review(self):
        del self.record['audience_review']; self.assertEqual(self.result(),'fail')
    def test_audience_review_failures(self):
        base=copy.deepcopy(self.record['audience_review'])
        cases=[{'status':'unknown'},{'pptx_sha256':'old'},{'copy_sha256':'old'},
               {'revision_rounds':4},{'revision_rounds':True},{'slides':[]},{'dimensions':{}},
               {'reviewer_profile':''},{'issues':None}]
        for change in cases:
            with self.subTest(change=change):
                self.record['audience_review']={**copy.deepcopy(base),**change}
                self.assertEqual(self.result(),'fail')
    def test_audience_issue_closure(self):
        issue={'id':'A01','scope':'S01','question':'可否声称显著提升？','evidence':'没有统计检验',
               'impact':'结论强度失实','severity':'major','decision':'成立','action':'收紧标题',
               'recheck':'新标题不再声称显著，测试条件保留','status':'resolved'}
        self.record['audience_review']['issues']=[issue]
        self.assertEqual(self.result(),'pass')
        for field,value in [('status','open'),('recheck',''),('action',''),('scope','S99')]:
            with self.subTest(field=field):
                self.record['audience_review']['issues']=[{**issue,field:value}]
                self.assertEqual(self.result(),'fail')
        self.record['audience_review']['issues']=[issue,issue]
        self.assertEqual(self.result(),'fail')
    def test_evidenced_rejected_question_allowed(self):
        self.record['audience_review']['issues']=[{'id':'A02','scope':'S01','question':'是否漏写测试范围？',
            'evidence':'页面已有仅本测试集','impact':'若遗漏将扩大结论范围','severity':'major','decision':'不成立',
            'action':'保留原文，无需修改','recheck':'在最终页面确认限定可见','status':'rejected'}]
        self.assertEqual(self.result(),'pass')
    def test_stale_ppt(self):
        (self.base/'deck.pptx').write_text('changed'); self.assertEqual(self.result(),'fail')
    def test_stale_finalizer(self):
        self.record['finalizer']=self.save('old-receipt.json',{'finalSha256':'old'})
        self.assertEqual(self.result(),'fail')
    def test_stale_preview(self):
        (self.base/'s1.png').write_text('changed'); self.assertEqual(self.result(),'fail')
    def test_missing_slide_review(self):
        self.record['slides_reviewed']=[]; self.assertEqual(self.result(),'fail')
    def test_last_batch_omits_slide(self):
        req=requirements();req['slide_count']=2
        extra=copy.deepcopy(req['slides'][0]);extra['id']='S02';req['slides'].append(extra)
        self.record['requirements']=self.save('requirements2.json',req)
        preview=copy.deepcopy(self.record['slides_reviewed'][0]);preview['id']='S02'
        self.record['slides_reviewed'].append(preview)
        self.assertEqual(self.result(),'fail')
    def test_review_for_old_ppt(self):
        self.record['slides_reviewed'][0]['pptx_sha256']='old'; self.assertEqual(self.result(),'fail')
    def test_visual_budget(self):
        self.record['visual_revision_rounds']=4; self.assertEqual(self.result(),'fail')
    def test_text_batch_budget(self):
        self.record['text_batches']*=3; self.assertEqual(self.result(),'fail')
    def test_text_round_budget(self):
        self.record['text_batches'][0]['revision_rounds']=4; self.assertEqual(self.result(),'fail')
    def test_unknown_content_review(self):
        self.record['checks']['facts']['status']='unknown'; self.assertEqual(self.result(),'fail')
    def test_unresolved(self):
        self.record['unresolved']=['S01超出边界']; self.assertEqual(self.result(),'fail')
    def test_unconfirmed_sample(self):
        self.record['interaction']='collaborative'; self.assertEqual(self.result(),'fail')
    def test_no_semantic_review(self):
        tr=json.loads((self.base/'tr.json').read_text(encoding='utf-8')); tr['checks']['semantic_fidelity']='fail'
        self.record['text_batches'][0]['result']=self.save('tr2.json',tr)
        self.assertEqual(self.result(),'fail')
    def test_missing_substantive_results(self):
        tr=json.loads((self.base/'tr.json').read_text(encoding='utf-8')); tr['requirement_results']=[]
        self.record['text_batches'][0]['result']=self.save('tr2.json',tr)
        self.assertEqual(self.result(),'fail')
    def test_template_needs_change_log(self):
        self.record['mode']='template'; self.assertEqual(self.result(),'fail')
    def test_topic_needs_sources(self):
        self.record['mode']='topic'; self.assertEqual(self.result(),'fail')
    def test_updated_copy_not_bound(self):
        self.record['copy_sha256']='other'; self.assertEqual(self.result(),'fail')
    def test_paths_cannot_escape(self):
        self.record['pptx']['path']='../secret'; self.assertEqual(self.result(),'fail')


if __name__ == '__main__': unittest.main()
