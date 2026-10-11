"""Additional synthetic input and component checks; host-authored expected semantics."""
import argparse
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from paperfigure import storage,layout,drawio,adapters
from paperfigure.cli import audit


def run():
    parser=argparse.ArgumentParser();parser.add_argument('runs');args=parser.parse_args();base=Path(args.runs).parent
    task=storage.start(base/'natural-inputs','输入是传感器读数。')
    storage.add_requirement(task,'先去噪。')
    storage.add_requirement(task,'之后阈值判别，无回归输出。')
    graph={'title':'去噪与阈值判别','nodes':[{'id':i,'label':l,'type':t,'evidence':e} for i,l,t,e in [
        ('reading','传感器读数','data','initial request'),('denoise','去噪','process','feedback 1'),('threshold','阈值判别','decision','feedback 2')]],
        'edges':[{'id':'f1','source':'reading','target':'denoise','kind':'data','evidence':'feedback 1: 先'},
                 {'id':'f2','source':'denoise','target':'threshold','kind':'data','evidence':'feedback 2: 之后'}],'unresolved':[]}
    guide={'font':'Microsoft YaHei','font_pt':9,'display_width_mm':180}
    storage.write_json(task/'semantic_graph.json',graph);storage.write_json(task/'style_guide.json',guide)
    plan=layout.plan(graph);storage.write_json(task/'layout_plan.json',plan);drawio.build(graph,plan,guide,[],task/'figure.drawio')
    result={'fragmented':{'task':str(task),'checks':audit(task,task/'figure.drawio'),'render':adapters.render(task/'figure.drawio',task/'figure.png')}}
    # An already finished synthetic image remains a bitmap; tensor and annotation remain native.
    source=Path(storage.read_json(args.runs)[0]['task'])/'figure-v2.png'
    task=storage.start(base/'components','组件验收：嵌入已有示意图，连接到张量对象，再存入存储对象。不是实验结果。',[source])
    asset={'id':'A1','path':str(source),'sha256':storage.digest(source),'role':'finished_synthetic_image'}
    graph={'title':'原生成组素材与数据对象','nodes':[
        {'id':'picture','label':'已有示意图','type':'image','asset_id':'A1','evidence':'synthetic component request'},
        {'id':'tensor','label':'张量对象','type':'tensor','evidence':'synthetic component request'},
        {'id':'archive','label':'存储对象','type':'storage','evidence':'synthetic component request'}],
        'edges':[{'id':'i1','source':'picture','target':'tensor','kind':'data','evidence':'synthetic relation'},
                 {'id':'i2','source':'tensor','target':'archive','kind':'data','evidence':'synthetic relation'}],'unresolved':[]}
    storage.write_json(task/'semantic_graph.json',graph);storage.write_json(task/'assets.json',[asset]);storage.write_json(task/'style_guide.json',guide)
    boxes={'picture':{'x':50,'y':100,'w':320,'h':170},'tensor':{'x':440,'y':145,'w':150,'h':80},'archive':{'x':665,'y':145,'w':150,'h':80}}
    plan=layout.plan(graph,boxes=boxes);storage.write_json(task/'layout_plan.json',plan);drawio.build(graph,plan,guide,[asset],task/'figure.drawio')
    result['components']={'task':str(task),'checks':audit(task,task/'figure.drawio'),'render':adapters.render(task/'figure.drawio',task/'figure.png')}
    diff=drawio.patch(task/'figure.drawio',task/'moved.drawio',[{'page':'main','id':'picture','action':'move','dx':0,'dy':20}],storage.digest(task/'figure.drawio'))
    result['components']['move_delta']=diff;result['components']['moved_render']=adapters.render(task/'moved.drawio',task/'moved.png')
    storage.write_json(base/'extra-acceptance.json',result);print(base/'extra-acceptance.json')


if __name__=='__main__':run()
