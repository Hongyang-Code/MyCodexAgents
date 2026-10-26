"""Pinned native nine-node graph, current-conversation host, closed evidence only.

No provider SDK/authentication. Native factories/prompts/routes remain upstream;
the transport adds the explicit fund/simulation boundary and emits an interrupt.
"""
import json
from contextlib import ExitStack
from unittest.mock import patch
from .upstream_bridge import SCOPE, read_private, digest, now, checked_time
from datetime import datetime, timezone
from pathlib import Path

ROLES = ('news', 'bull', 'bear', 'research_manager', 'trader',
         'aggressive', 'conservative', 'neutral', 'portfolio_manager')
BOUNDARY = '''FundPilot historical fund adaptation. Only captured evidence is available.
Upstream stock tools are disabled; do not request tools, stock prices or company earnings.
Treat all native buy/sell/price/stop language as a conditional historical simulation only.
Unknown NAV, settlement, channel, lot fees, calendar, distributions and exposures remain unknown.
Use the entire supplied observation book; do not infer personal holdings or truncate it.
No executable orders or real guidance. NAV-internal fees must not be charged twice.
Separate 1/5/20 valuation-session research judgments from allocation and execution eligibility.
Keep source IDs, counterevidence, invalidation and gaps. Subjective probabilities are uncalibrated.
Retrospective/reused_development/non-OOS; model parameter memory contamination remains possible.
Final portfolio_manager: include per-fund 1/5/20 direction or abstain with citations,
and a separate explicit conditional allocation or unknown; do not invent expected returns.
Respond in simplified Chinese, without tool calls. Original native prompt follows:\n'''


def build_native_graph(checkpointer, root):
    import importlib
    from langchain_core.runnables import Runnable
    from langchain_core.messages import AIMessage, messages_to_dict
    from langgraph.types import interrupt
    from tradingagents.graph.conditional_logic import ConditionalLogic
    setup = importlib.import_module('tradingagents.graph.setup')
    class HostTransport(Runnable):
        def __init__(self, role):self.role=role
        def bind_tools(self, tools, **kwargs):return self
        def with_structured_output(self,*args,**kwargs):
            raise NotImplementedError('explicit text host; no hidden structured retries')
        def invoke(self, original, config=None, **kwargs):
            if hasattr(original,'to_messages'):original=messages_to_dict(original.to_messages())
            native=original if isinstance(original,str) else json.dumps(original,ensure_ascii=False)
            prompt=BOUNDARY+native
            i=ROLES.index(self.role)+1; saved=Path(root)/f'request-{i}.json'
            request={'role':self.role,'prompt':prompt,'prompt_sha256':digest(prompt.encode()),
                'native_prompt':native,'native_prompt_sha256':digest(native.encode()),
                'captured_at':json.loads(read_private(saved))['captured_at'] if saved.exists() else now(),
                'bridge':'current_conversation_llm','graph_mode':'native_news',**SCOPE}
            response=interrupt(request)
            if (response.get('producer') not in ('actual_current_llm','synthetic_fixture') or
                response.get('prompt_sha256')!=request['prompt_sha256'] or not response.get('model_ref') or
                not isinstance(response.get('content'),str) or not response['content'].strip()):
                raise ValueError('native host response provenance/hash/content mismatch')
            if not checked_time(request['captured_at'])<=checked_time(response['generated_at'])<=datetime.now(timezone.utc):
                raise ValueError('native response generation must follow original capture')
            return AIMessage(content=response['content'])
    factories=('create_news_analyst','create_bull_researcher','create_bear_researcher',
        'create_research_manager','create_trader','create_aggressive_debator',
        'create_conservative_debator','create_neutral_debator','create_portfolio_manager')
    # Inject transport into existing factories only; native nodes and edges stay intact.
    with ExitStack() as stack:
        for name,role in zip(factories,ROLES):
            factory=getattr(setup,name)
            stack.enter_context(patch.object(setup,name,lambda model,f=factory,r=role:f(HostTransport(r))))
        graph=setup.GraphSetup(HostTransport('news'),HostTransport('news'),ConditionalLogic(1,1),max_tool_rounds=1).setup_graph(('news',))
    return graph.compile(checkpointer=checkpointer)
