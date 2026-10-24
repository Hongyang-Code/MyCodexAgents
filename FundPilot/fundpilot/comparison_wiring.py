"""Native upstream OFFLINE wiring probes. Synthetic transport, never model effects.

No live inference path is exposed. Source/tool boundaries are explicitly replaced
by a closed synthetic cache; native factories, graph/pipeline and validators run.
"""
import argparse
import asyncio
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import socket
import subprocess
from unittest.mock import patch
from .upstream_bridge import write_new, now, verify_upstream

FINROBOT_PIN='2717499b8e30f242640af08c4ad9afd1113c2d45'
FIXTURE={'funds':['SYNTHETIC_FUND_A','SYNTHETIC_FUND_B','SYNTHETIC_FUND_C'],
         'cutoff':'2020-01-01','evidence':'SYNTHETIC cached fund basket; NAV and rules unknown',
         'cash_return':None,'allocation':None,'holdings_confirmed':False}


def sha(raw):return hashlib.sha256(raw).hexdigest()


@contextmanager
def network_denied(attempts):
    def deny(*args,**kwargs):
        attempts.append('blocked_socket_attempt');raise RuntimeError('offline wiring forbids network')
    with patch.object(socket,'getaddrinfo',deny),patch.object(socket,'create_connection',deny),patch.object(socket.socket,'connect',deny),patch.object(socket.socket,'connect_ex',deny):
        yield


def tradingagents_native(root, analysts=('market','social','news','fundamentals'), synthetic_assets=3):
    verify_upstream(root)
    from langchain_core.runnables import Runnable
    from langchain_core.messages import AIMessage
    from tradingagents.graph.setup import GraphSetup
    from tradingagents.graph.propagation import Propagator
    from tradingagents.graph.conditional_logic import ConditionalLogic
    import tradingagents.agents.analysts.sentiment_analyst as sentiment
    calls=[];network=[];cache=[]
    class SyntheticTransport(Runnable):
        def bind_tools(self,tools,**kwargs):return self
        def with_structured_output(self,*args,**kwargs):raise NotImplementedError('synthetic text-only transport')
        def invoke(self,prompt,config=None,**kwargs):
            if len(calls)>=24:raise ValueError('synthetic probe call ceiling')
            text=str(prompt);calls.append({'prompt':text,'prompt_sha256':sha(text.encode())})
            return AIMessage(content='Hold\nSYNTHETIC ONLY; no forecast, no recommendation')
    def cached(*args,**kwargs):cache.append('synthetic_social_prefetch');return FIXTURE['evidence']
    from .ledger import Ledger
    from .portfolio import PortfolioManager
    if type(synthetic_assets) is not int or synthetic_assets<1:raise ValueError('positive synthetic asset count required')
    ledger=Ledger(':memory:');manager=PortfolioManager(ledger)
    manager.import_snapshot('synthetic-all',{'as_of':'2020-01-01T00:00:00Z','positions':[{'code':f'{900000+i:06d}','units':'1'} for i in range(synthetic_assets)]},
        {'source':'SYNTHETIC complete capacity fixture','confidence':{'as_of':'1','positions':'1'}})
    view=native_portfolio_view(manager,'900000',coverage='complete')
    model=SyntheticTransport()
    state=Propagator().create_initial_state('SYNTHETIC_FUND_BASKET',FIXTURE['cutoff'],asset_type='fund',instrument_context=json.dumps(FIXTURE),portfolio_context=view['context'])
    ledger.close()
    with network_denied(network),patch.object(sentiment.get_news,'func',cached),patch.object(sentiment,'fetch_stocktwits_messages',cached),patch.object(sentiment,'fetch_reddit_posts',cached),patch.object(sentiment,'jev_screen',lambda *a,**k:None):
        graph=GraphSetup(model,model,ConditionalLogic(1,1),max_tool_rounds=1).setup_graph(analysts).compile()
        result=graph.invoke(state,{'recursion_limit':40})
    return {'synthetic_asset_count':synthetic_assets,'native_portfolio_fingerprint':view['native_fingerprint'],'exact_book_sha256':view['exact_book_sha256'],'status':'native_graph_executed_synthetic','selected_analysts':list(analysts),
            'fixture_model_requests':len(calls),'research_debate_turns':result['investment_debate_state']['count'],
            'risk_debate_turns':result['risk_debate_state']['count'],'calls':calls,
            'cache_boundary_calls':cache,'network_attempts':network,
            'native_final_rating_is_not_a_fund_forecast':result.get('final_rating')}


def finrobot_native(root, pipeline_kind="equity"):
    root=Path(root).resolve()
    pin=subprocess.check_output(['git','-C',str(root),'rev-parse','HEAD'],text=True).strip()
    dirty=subprocess.check_output(['git','-C',str(root),'status','--porcelain','--untracked-files=no'],text=True)
    if pin!=FINROBOT_PIN or dirty:raise ValueError('clean pinned FinRobot V2 required')
    import finrobot
    if Path(finrobot.__file__).resolve().parents[2]!=root:raise ValueError('FinRobot import path differs from pinned checkout')
    from pydantic_ai.models.test import TestModel
    from pydantic_ai.messages import ModelMessagesTypeAdapter
    from finrobot.config import FinRobotSettings
    from finrobot.engine.agents.factory import create_sub_agents
    from finrobot.engine.deps import FinRobotDeps
    from finrobot.engine.pipelines.equity_research import create_equity_research_pipeline
    from finrobot.engine.pipelines.ic_memo import create_ic_memo_pipeline
    calls=[];fetches=[];network=[]
    class CountedTestModel(TestModel):
        async def request(self,messages,model_settings,model_request_parameters):
            raw=ModelMessagesTypeAdapter.dump_json(messages)
            calls.append({'prompt_sha256':sha(raw),'messages_json':raw.decode()})
            return await super().request(messages,model_settings,model_request_parameters)
    class ClosedFundCache:
        async def fetch_canonical(self,kind,ticker,**kwargs):
            fetches.append(str(kind));raise ValueError('CACHE_GAP: admitted fund NAV does not supply company revenue/EBITDA or canonical stock price')
        async def fetch(self,kind,ticker,**kwargs):
            fetches.append(str(kind));raise ValueError('CACHE_GAP: no admitted synthetic company dataset')
    settings=FinRobotSettings();model=CountedTestModel(call_tools=[],custom_output_text='SYNTHETIC revenue ebitda risk; cached fund basket facts unknown')
    with network_denied(network),patch.object(FinRobotSettings,'create_model',return_value=model):
        agents=create_sub_agents(settings);pipeline=(create_equity_research_pipeline(agents) if pipeline_kind=="equity" else create_ic_memo_pipeline(agents))
        pipeline.max_retries=0  # explicit probe: preserve first failure, no hidden retry.
        stages=[s.name for s in pipeline.steps]
        try:
            asyncio.run(pipeline.execute(FinRobotDeps(ClosedFundCache(),settings),'SYNTHETIC_FUND_BASKET'))
        except (ValueError,RuntimeError) as error:
            status='native_pipeline_blocked_by_fund_data_contract'
            failure={'type':type(error).__name__,'message':str(error)}
        else:
            raise AssertionError('closed fund cache unexpectedly produced a native equity report')
    return {'status':status,'pipeline_kind':pipeline_kind,'roles':list(agents),'native_steps':stages,'fixture_model_requests':len(calls),
            'calls':calls,'cache_fetches':fetches,'network_attempts':network,'failure':failure,
            'minimum_successful_total_requests':'unknown; pipeline aborts at company-financial prerequisite',
            'not_a_general_claim_finrobot_cannot_be_adapted':True}


def native_portfolio_view(manager, target, *, coverage, unresolved=(), currency=None):
    """Reuse upstream book rendering/fingerprint, retaining exact fund accounting.

    Native PortfolioContext requires known quantities and otherwise may say a
    target is not held. Refuse that projection for partial/unknown inventory.
    Native floats are display context only; the exact Decimal ledger stays intact.
    """
    from tradingagents.portfolio import PortfolioContext, Position
    book=manager.research_book(coverage=coverage,unresolved=unresolved)
    if coverage!='complete' or book['unresolved_positions']:
        raise ValueError('native book render requires complete confirmed inventory; keep unknown book separately')
    exact=json.dumps(book,sort_keys=True,ensure_ascii=False)
    class BoundFundBook(PortfolioContext):
        accounting_sha256: str
        def fingerprint(self):
            # Preserve native binding, adding pending/receivable/lot evidence.
            return sha((super().fingerprint()+self.accounting_sha256).encode())[:12]
        def render(self,ticker):
            return super().render(ticker)+'\nFund accounting (exact strings; no risk/weight inference):\n'+exact
    native=BoundFundBook(cash=None if book['available_cash'] is None else float(book['available_cash']),
        currency=currency,accounting_sha256=sha(exact.encode()),
        positions=[Position(ticker=k,quantity=float(v)) for k,v in book['confirmed_positions'].items()])
    return {'native':native,'book':book,'exact_book_sha256':sha(exact.encode()),
            'native_fingerprint':native.fingerprint(),'context':native.render(target)}


def run(arm,root):
    # Pinned dependency environments intentionally remain separate.
    if arm=='tradingagents-native':result=tradingagents_native(root)
    elif arm=='finrobot-native':result=finrobot_native(root)
    elif arm=='finrobot-ic-native':result=finrobot_native(root,'ic')
    else:raise ValueError('unsupported arm')
    return {'schema':1,'generated_at':now(),'arm':arm,'producer':'synthetic_fixture',
            'fixture_sha256':sha(json.dumps(FIXTURE,sort_keys=True).encode()),'fixture':FIXTURE,
            'actual_llm_requests':0,'effect_comparison_performed':False,'fusion_authorized':False,
            'trading_authorized':False,'project_complete':False,**result}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--arm',choices=('tradingagents-native','finrobot-native','finrobot-ic-native'),required=True)
    p.add_argument('--upstream',required=True);p.add_argument('--output',required=True)
    p.add_argument('--synthetic-fixture',action='store_true',required=True)
    args=p.parse_args();result=run(args.arm,args.upstream);write_new(args.output,result)
    print(json.dumps({k:result[k] for k in ('arm','status','fixture_model_requests','actual_llm_requests','effect_comparison_performed')}))


if __name__=='__main__':main()
