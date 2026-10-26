"""Synthetic fixtures, manually interpreted by the host AI from natural requests.
No mock model responses, real experiments, or domain-specific core defaults.
"""

def node(ident,label,source,**kw):
    return {'id':ident,'label':label,'type':'process','evidence':source,**kw}


def edge(ident,source,target,evidence,**kw):
    return {'id':ident,'source':source,'target':target,'kind':'data','evidence':evidence,**kw}


CASES = [
    {'name':'branch-merge', 'request':'画一个算法图：观测序列分别进行局部滤波和频域描述，将两路结果融合，再输出异常评分。只画推理过程，不加训练步骤。',
     'graph':{'title':'双视角表征与异常评分', 'nodes':[
         node('obs','观测序列','request: 观测序列',type='data'),node('filter','局部滤波','request: 局部滤波'),
         node('spectrum','频域描述','request: 频域描述'),node('fusion','表征融合','request: 两路结果融合',role='contribution'),
         node('score','异常评分','request: 输出异常评分',type='data')],
         'edges':[edge('e1','obs','filter','request: 分别'),edge('e2','obs','spectrum','request: 分别'),
                  edge('e3','filter','fusion','request: 两路结果融合'),edge('e4','spectrum','fusion','request: 两路结果融合'),edge('e5','fusion','score','request: 再输出')], 'unresolved':[]}},
    {'name':'grouped-experiment', 'request':'同一批样本随机分组，一组常温培养，另一组加热培养；两组分别测量活性，再比较。把两个实验分支分组展示，不写未提供的样本数、温度和实验结果。',
     'graph':{'title':'分组对照实验设计', 'groups':[{'id':'control','label':'对照组'},{'id':'treatment','label':'处理组'}], 'nodes':[
         node('samples','同批样本','request: 同一批样本',type='data'),node('random','随机分组','request: 随机分组'),
         node('ambient','常温培养','request: 常温培养',parent='control'),node('heat','加热培养','request: 加热培养',parent='treatment',role='contribution'),
         node('measure_c','活性测量','request: 两组分别测量',parent='control'),node('measure_t','活性测量','request: 两组分别测量',parent='treatment'),
         node('compare','组间比较','request: 再比较',type='data')],
         'edges':[edge('b1','samples','random','request: 随机分组'),edge('b2','random','ambient','request: 一组'),edge('b3','random','heat','request: 另一组'),
                  edge('b4','ambient','measure_c','request: 分别测量'),edge('b5','heat','measure_t','request: 分别测量'),
                  edge('b6','measure_c','compare','request: 再比较'),edge('b7','measure_t','compare','request: 再比较')], 'unresolved':[]}},
    {'name':'iterative-feedback','request':'画迭代求解图。初值进入残差计算，然后更新状态并判断是否收敛。未收敛时用更新状态再次计算残差，收敛时输出。阈值没给，不要猜数值。',
     'graph':{'title':'带收敛判断的迭代求解', 'nodes':[
         node('initial','初始状态','request: 初值',type='state'),node('residual','计算残差','request: 残差计算'),
         node('update','更新状态','request: 更新状态',role='contribution'),node('stop','是否收敛？','request: 判断是否收敛',type='decision'),
         node('output','输出状态','request: 收敛时输出',type='state')],
         'edges':[edge('c1','initial','residual','request: 初值进入'),edge('c2','residual','update','request: 然后更新'),
                  edge('c3','update','stop','request: 并判断'),edge('c4','stop','output','request: 收敛时输出',kind='control',label='是'),
                  edge('c5','stop','residual','request: 未收敛用更新状态再次计算',kind='control',feedback=True,label='否：继续迭代')], 'unresolved':[]}}
]
