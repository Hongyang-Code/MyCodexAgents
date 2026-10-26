"""Reproducible host-authored acceptance actions; not an autonomous model simulation."""
import argparse
import copy
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from paperfigure import storage, drawio, layout, adapters
from paperfigure.cli import audit


def main():
    parser=argparse.ArgumentParser();parser.add_argument('runs');args=parser.parse_args()
    runs=storage.read_json(args.runs);base=Path(args.runs).parent
    # Rebuild the selected source with the repaired native data component; preserve older file.
    for run in runs:
        task=Path(run['task']);graph=storage.read_json(task/'semantic_graph.json');plan=storage.read_json(task/'layout_plan.json');guide=storage.read_json(task/'style_guide.json')
        storage.checkpoint(task,'visual-repair',True)
        drawio.build(graph,plan,guide,[],task/'figure-v2.drawio',task)
        for fmt in ('png','svg','pdf'):
            receipt=adapters.render(task/'figure-v2.drawio',task/('figure-v2.'+fmt),fmt=fmt)
            storage.write_json(task/('render-v2-'+fmt+'.json'),receipt)
        audit(task,task/'figure-v2.drawio')
    # Screenshot-only test: host observed the rendered pixels, then authored new IDs and structure.
    screenshot=Path(runs[0]['task'])/'figure.png'
    task=storage.start(base/'natural-inputs','只根据这张截图重建可编辑图，不要求额外论文或图注。',[screenshot])
    labels=[('sinput','观测序列','data'),('local','局部滤波','process'),('frequency','频域描述','process'),('join','表征融合','process'),('soutput','异常评分','data')]
    graph={'title':'双视角表征与异常评分','nodes':[{'id':i,'label':label,'type':kind,'evidence':'Screenshot: visible labeled shape; inspected by host'} for i,label,kind in labels],
           'edges':[{'id':f'se{i}','source':a,'target':b,'kind':'data','evidence':'Screenshot: visible directed connector'} for i,(a,b) in enumerate([('sinput','local'),('sinput','frequency'),('local','join'),('frequency','join'),('join','soutput')])],
           'unresolved':[]}
    guide=storage.read_json(Path(runs[0]['task'])/'style_guide.json');storage.write_json(task/'semantic_graph.json',graph);storage.write_json(task/'style_guide.json',guide)
    plan=layout.plan(graph);storage.write_json(task/'layout_plan.json',plan)
    drawio.build(graph,plan,guide,[],task/'reconstructed.drawio',task)
    receipt=adapters.render(task/'reconstructed.drawio',task/'reconstructed.png');storage.write_json(task/'render.json',receipt)
    audit(task,task/'reconstructed.drawio')
    screenshot_task=task
    # Fragmented input, later correction, local label edit without moving the graph.
    storage.add_requirement(task,'保持布局，只把“表征融合”改为“特征融合”。',['join'])
    before=task/'reconstructed.drawio';after=task/'edited.drawio'
    delta=drawio.patch(before,after,[{'page':'main','id':'join','action':'label','value':'特征融合'}],storage.digest(before))
    graph['nodes'][3]['label']='特征融合';graph['nodes'][3]['evidence']='User correction in synthetic acceptance case'
    storage.write_json(task/'semantic_graph.json',graph)
    storage.write_json(task/'changes.json',delta)
    storage.write_json(task/'edited-render.json',adapters.render(after,task/'edited.png'))
    edited_report=audit(task,after)
    # A true scientific gap stays unresolved; host's question is explicit, no fabricated answer.
    missing=storage.start(base/'natural-inputs','画个带反馈的方法图，反馈接到哪里我还没说明。')
    storage.write_json(missing/'clarification.json',{'question':'反馈使用哪个模块的输出，回到哪个模块？','reason':'这会改变科学依赖关系，无法从现有材料确定。',
        'independent_work':'已保存原话和待确认项；字号、配色、输出目录可以先确定。','status':'awaiting_scientific_fact'})
    unknown=storage.read_json(missing/'semantic_graph.json');unknown['unresolved']=['Feedback endpoints unknown'];storage.write_json(missing/'semantic_graph.json',unknown)
    record={'screenshot_task':str(screenshot_task),'screenshot_only':'host actually inspected synthetic screenshot; scientific reconstruction then native rendered',
            'local_edit':{'changed':delta,'checks':edited_report,'protected':'Only join value changed; all other cell XML preserved'},
            'missing_fact_task':str(missing),'model_execution':'Current host manually interpreted inputs; no external autonomous model or mock LLM API',
            'ui_edit':{'status':'not_run','reason':'Computer Use node kernel failed twice before window discovery: sandbox helper setup error'}}
    storage.write_json(base/'natural-input-acceptance.json',record)
    print(base/'natural-input-acceptance.json')


if __name__=='__main__':main()
