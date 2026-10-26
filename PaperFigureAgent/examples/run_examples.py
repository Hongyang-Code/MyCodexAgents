import argparse
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from paperfigure import storage, layout, drawio, adapters
from paperfigure.cli import candidate, audit
from cases import CASES


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',required=True);p.add_argument('--render',action='store_true');args=p.parse_args()
    root=Path(args.output);root.mkdir(parents=True,exist_ok=True);results=[]
    for case in CASES:
        task=storage.start(root,case['request']);graph=case['graph']
        storage.write_json(task/'semantic_graph.json',graph)
        guide={'background':'#FFFFFF','text':'#243746','edge':'#6C7D89','group_fill':'#F7F9FB','group_stroke':'#D7E0E6',
               'font':'Microsoft YaHei','font_pt':9,'display_width_mm':180,
               'roles':{'default':{'fill':'#F3F6F8','stroke':'#A7B8C3'},'contribution':{'fill':'#DCEDEA','stroke':'#43877C','text':'#1D5A52'}}}
        storage.write_json(task/'style_guide.json',guide)
        candidate(task)
        # Both are full native candidates. The host views them, not just their scalar scores.
        for i in (1,2):
            plan=storage.read_json(task/f'candidate-{i}.json')
            drawio.build(graph,plan,guide,[],task/f'candidate-{i}.drawio',task)
        # Host compared both rendered candidates in the initial acceptance run:
        # these three short scientific flows read more compactly from left to right.
        chosen=storage.read_json(task/'candidate-1.json')
        storage.write_json(task/'layout_plan.json',chosen)
        storage.write_json(task/'selection.json',{'selection':'LR','by':'host visual review of preceding acceptance candidates',
                            'reason':'Horizontal main path is compact; vertical variants waste space and make group headers cross routing. This is fixture-specific, not a global preference.'})
        drawio.build(graph,chosen,guide,[],task/'figure.drawio',task)
        report=audit(task,task/'figure.drawio')
        entry={'name':case['name'],'task':str(task.resolve()),'direction':chosen['direction'],'checks':report}
        if args.render:
            entry['renders']=[]
            for name in ('candidate-1','candidate-2','figure'):
                receipt=adapters.render(task/(name+'.drawio'),task/(name+'.png'))
                storage.write_json(task/(name+'-render.json'),receipt);entry['renders'].append(receipt)
        storage.checkpoint(task,'examples-rendered');results.append(entry)
    storage.write_json(root/'examples-run.json',results)
    print(root/'examples-run.json')


if __name__=='__main__':main()
