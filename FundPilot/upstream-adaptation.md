# 固定上游的基金研究适配

本入口实际调用 TradingAgents 原生研究节点，并通过 LangGraph 执行和恢复。它是历史诊断的局部适配，不是完整基金投资系统，也不证明研究有效。

## 保留 替换 简化

| 处理 | 实现与边界 |
| --- | --- |
| 保留 | 固定 TradingAgents e8f5503e9b86d5c2710b0c76b1f686703968c9df；直接导入 create_bull_researcher、create_bear_researcher、create_research_manager、AgentState、ConditionalLogic；使用原生 StateGraph、interrupt、Command 和 SqliteSaver。没有重写多空节点的状态更新和路由逻辑。 |
| 替换 | 股票行情、财报和新闻工具不装入图；调用方提供基金公开证据包。模型边界替换股票提示，保留原节点插入的证据与辩论历史，加入未知价、类别、渠道、费用、确认到账及历史污染限制。股票工具代码仍随依赖安装，但本图不暴露工具执行入口。 |
| 简化 | 一轮多空、一个研究经理，共三份响应；不运行 Trader、风险投票、Portfolio Manager、股票策略、自动记忆反思或交易接口。资金模拟独立复用已有 conditional_value。 |

这是对原生节点的有限图组合，不声称运行了完整 TradingAgentsGraph 或完成全部股票工具替换。经理沿用上游只接收辩论历史的设计；尚未验证证据压缩是否遗漏重要资料。

## 干净 Linux 安装

基础CLI支持Python 3.11+；本适配的版本约束和已验证上游依赖组合是Linux/Python 3.12。上游自身声明>=3.11，不等于本项目已验证3.11上的全部依赖组合。以下从仓库根目录执行；shell变量不填用户凭据。`FP_PRIVATE`必须是checkout外的新私有目录，`FP_UPSTREAM`和`FP_VENV`也在checkout外。示例先建立全新合成目录；实际项目应恢复已有私有账本，不能重新生成零种子。

```bash
# 首次从GitHub取得项目，已克隆者先fetch并使用获准分支。
git clone --single-branch --branch fundpilot/opensource-adaptation-20261024 \
  https://github.com/Hongyang-Code/MyCodexAgents.git MyCodexAgents
cd MyCodexAgents
FP_PRIVATE=$(mktemp -d /tmp/fundpilot-synthetic.XXXXXXXX)
FP_UPSTREAM=$(mktemp -d /tmp/fundpilot-upstream.XXXXXXXX)
FP_VENV=$(mktemp -d /tmp/fundpilot-venv.XXXXXXXX)
git -C "$FP_UPSTREAM" init
git -C "$FP_UPSTREAM" remote add origin https://github.com/TauricResearch/TradingAgents.git
git -C "$FP_UPSTREAM" fetch --depth=1 origin e8f5503e9b86d5c2710b0c76b1f686703968c9df
git -C "$FP_UPSTREAM" checkout --detach FETCH_HEAD
python3.12 -m venv "$FP_VENV"
"$FP_VENV/bin/python" -m pip install --no-input --timeout 30 --retries 0 \
  -c FundPilot/requirements/tradingagents-linux-py312.constraints.txt -e "$FP_UPSTREAM[dev]"
"$FP_VENV/bin/python" -m pip check
export PYTHONPATH="$PWD/FundPilot"
export FUND_PILOT_UPSTREAM="$FP_UPSTREAM"
```

可以复用已核对SHA、无已跟踪修改的上游checkout；仍需独立venv，导入路径必须指向该checkout。用本机包管理工具替代pip时也应保留同一约束和可编辑导入；约束文件不是wheel哈希锁。两上游的许可证/对照范围见下节，FinRobot不需要为运行本桥接而安装。

先运行已有合成方法，无需模型/API/来源请求：

```bash
"$FP_VENV/bin/python" -m unittest discover -s FundPilot/tests -p test_upstream_bridge.py -v
```

只针对上述全新合成目录准备已知零用量，再走可逐步观察的三次跨进程恢复。不要把这段合成种子或响应拿去初始化真实项目。

```bash
export FP_PRIVATE FP_VENV FP_UPSTREAM
"$FP_VENV/bin/python" - <<'PY_SYNTHETIC_INPUT'
import json, os
from pathlib import Path
p=Path(os.environ['FP_PRIVATE'])
files={
 'seed.json':{'run_id':'SYNTHETIC_NEW_RUN_ONLY','used':{'source':0,'retry':0,'llm':0,'prediction_batch':0},'candidate_history':[]},
 'evidence.json':{'fund':'SYNTHETIC:unknown','information_cutoff':'2020-01-01T00:00:00+08:00',
                  'market_report':'SYNTHETIC DATA ONLY; no public source fetched',
                  'fundamentals_report':'unknown','context':'synthetic transport; not a holding'}}
for name,value in files.items():
 f=p/name
 with f.open('x') as out:json.dump(value,out)
 f.chmod(0o600)
PY_SYNTHETIC_INPUT
"$FP_VENV/bin/python" -m fundpilot.upstream_bridge budget-init \
  --seed "$FP_PRIVATE/seed.json" --budget "$FP_PRIVATE/budget.sqlite"
"$FP_VENV/bin/python" -m fundpilot.upstream_bridge start \
  --evidence "$FP_PRIVATE/evidence.json" --output "$FP_PRIVATE/graph" \
  --budget "$FP_PRIVATE/budget.sqlite" --operation-id synthetic-new-graph --upstream "$FP_UPSTREAM"
for FP_SEQUENCE in 1 2 3; do
  export FP_SEQUENCE
  "$FP_VENV/bin/python" - <<'PY_SYNTHETIC_RESPONSE'
import json, os
from pathlib import Path
from datetime import datetime, timezone
p=Path(os.environ['FP_PRIVATE']);n=os.environ['FP_SEQUENCE']
q=json.loads((p/'graph'/f'request-{n}.json').read_bytes())
r={'producer':'synthetic_fixture','model_ref':'SYNTHETIC_NOT_LLM',
   'generated_at':datetime.now(timezone.utc).isoformat(),
   'prompt_sha256':q['prompt_sha256'],'content':'SYNTHETIC response only'}
f=p/f'response-{n}.json'
with f.open('x') as out:json.dump(r,out)
f.chmod(0o600)
PY_SYNTHETIC_RESPONSE
  "$FP_VENV/bin/python" -m fundpilot.upstream_bridge resume \
    --root "$FP_PRIVATE/graph" --response "$FP_PRIVATE/response-$FP_SEQUENCE.json" --upstream "$FP_UPSTREAM"
done
"$FP_VENV/bin/python" - <<'PY_SYNTHETIC_RESULT'
import json, os
from pathlib import Path
r=json.loads((Path(os.environ['FP_PRIVATE'])/'graph/result.json').read_bytes())
print({k:r[k] for k in ('bridge_responses','response_producers','trading_authorized','native_upstream_llm_api_called')})
assert r['bridge_responses']==3 and r['response_producers']==['synthetic_fixture']*3
assert r['trading_authorized'] is False and r['native_upstream_llm_api_called'] is False
PY_SYNTHETIC_RESULT
```

完成后再次resume必须失败，旧请求/响应/结果不覆盖；同一operation-id也不能重复start。`request-1/2/3.json`分别是bull/bear/manager请求；未完成时读取最新request即可了解等待角色。上述打印只显示传输状态，不签认模型身份或投资资格。既有测试还验证并发与崩溃，不需要为此生成真实模型响应。

## 实际当前 LLM 桥接

无API密钥时，图在真实节点的llm.invoke边界产生interrupt，保存提示及SHA256。当前会话LLM读取提示，实际生成响应并记录真实时间、模型标识和提示哈希，再由新进程resume。它不调用上游原生LLM API，不伪造SDK调用或usage。模型精确快照未知时明确unknown。

每个响应只接受actual_current_llm或synthetic_fixture；这些身份声明需要外部记录核验，程序不能证明文字究竟由谁产生。合成测试记录synthetic_fixture，不当真实模型。每图最多三份响应，失败保留，不自动修复重试；该限制不能替代调用方跨运行私有预算。没有完整旧候选历史时，禁止用新目录重置七天结构候选额度。

命令在仓库根目录执行，真实输入、输出、检查点、预算种子及响应全部放在checkout之外。先初始化同一份共享预算，详见下节；未知旧用量不能填写0：

```bash
PYTHONPATH=FundPilot /private/venv/bin/python -m fundpilot.upstream_bridge start \
  --evidence /private/evidence.json --output /private/new-graph \
  --upstream /private/pinned-tradingagents \
  --budget /private/project/budget.sqlite --operation-id reviewed-stable-batch-id
PYTHONPATH=FundPilot /private/venv/bin/python -m fundpilot.upstream_bridge resume \
  --root /private/new-graph --response /private/actual-response.json \
  --upstream /private/pinned-tradingagents
```

start的证据包含fund、information_cutoff、market_report、fundamentals_report字符串，可含context和news_report；该API仍按一个目标标的生成研究请求；该字段不限制完整组合资产数，不能把逐标的评级相加冒充全局组合优化。单批新增精读限制与全量组合/账本/风险评估分开。响应含producer、model_ref、generated_at、prompt_sha256、content。generated_at是实际带时区生成时间，不倒填到历史。生成完毕后保存result.json、输入原字节及receipt。所有请求、响应和SQLite检查点均属私有研究材料。检查点恢复已测同云主机不同进程，尚未验收跨机器或定时恢复。

调用前检查上游git SHA、已跟踪文件洁净状态与导入路径。设置LANGCHAIN_TRACING_V2和LANGSMITH_TRACING为false，不创建模型客户端、不读取认证文件、不启动服务器。目录和文件使用0700/0600；这些权限和哈希不等于远程不可篡改存储或完整安全沙箱。传入的私有父目录与存储权限须由调用方核实。

## 安装 许可证 与对照

TradingAgents和FinRobot指定版本均为Apache 2.0。此次使用独立checkout及venv实际安装，依赖快照在integrations中；两项目不混装，避免模型SDK版本冲突。上游安装脚本与广泛依赖不构成安全审计通过。本适配通过导入链接原项目，不复制上游源码；没有使用其名称或标识作为本项目品牌。若将来分发上游源码或制品，须保留其LICENSE、NOTICE和适用修改声明，并遵守商标政策。

FinRobot V2固定2717499b8e30f242640af08c4ad9afd1113c2d45。已安装finrobot_desktop并执行离线数值边界测试；其桌面壳、自动代码执行、股票估值工具和真实模型均未启动。这是有限工程对照，未运行FinRobot基金研究或复现其收益。

TradingAgents原生chatgpt_auth和README描述SIWC；OpenAI官方https://developers.openai.com/siwc亦说明合格开源应用可使用ChatGPT套餐。本轮没有登录、读取现有凭据或调用原生认证。若后续改用原生SIWC，需另由用户本人在官方流程授权；不得从Windows或其他工具复制令牌，也不以当前桥接等同完成认证。

## 真实历史诊断与固定验收

本轮私有运行使用一个公开基金研究对象、官网原始HTTP、三份真实当前LLM响应、实际生成/冻结时间、一个预冻结窗口和一次条件估值。之后才完成目标值诊断与净成本比较；抓取页面本身已经包含后续历史，当前会话及更大项目可能已见结果，故全程retrospective、reused_development、non-OOS。模型参数历史记忆污染不能靠裁剪材料消除。真实来源、预测、协议、结果、错误及状态不提交Git或公开CI。

现金、买持、固定trend20和LLM条件分配使用同本金、窗口、基金机会及费用假设。trend20在该窗口的冻结规则对应买持相同分配，复用同一估值路径，不另做参数搜索。暴露差异单列；较低暴露不能直接解释为预测优势。费用未核实、分红拆分未知、类别与渠道及完整估值日历缺证据，严格资格pending。未知确认与到账不计作可用现金，NAV内部费用不重复扣除。不把条件NAV估值当实际可执行净收益，不以观察对象代替真实初始持仓。

一次有据改动限定为工程字节保留：原实现对输入重新序列化，却用原字节生成receipt哈希；非规范JSON可导致保存件与receipt不符。修改为保留原始输入字节，固定合成负例和不同进程恢复测试通过。真实历史结果未因这项修复重调；研究结构候选因旧七天记录未知保持阻塞，不将工程修复称策略改善。

历史验收固定12个月扣费不亏概率目标95%、严格超同期中国全国CPI目标90%、单侧95%置信下限和单位化最大回撤5%。独立全胜样本的精确下限为0.05**(1/n)，分别至少59和29个；相关、重叠及调参后数据不能套独立二项公式。验收模块与精确统计由主任务独立维护，本适配不定义晋级算法。短窗口、LLM自报概率或工程测试通过均不能验收。

本轮未取得合格12个月独立样本、同期全国CPI或全部交易机制证据，项目未完成。没有创建前瞻、正式投资、真实交易或自动续跑任务。普通Work Linux容器不能声称已绑定已发布Codex Cloud环境。

## 合成复验

```bash
PYTHONPATH=FundPilot FUND_PILOT_UPSTREAM=/private/pinned-tradingagents \
  /private/venv/bin/python -m unittest discover -s FundPilot/tests -p test_upstream_bridge.py -v
```

实际导入固定上游节点，分别以新子进程开始和恢复三次，核对多空顺序、计数、原始输入哈希、错误响应拒绝、完成后拒绝再响应及合成身份。未安装可选依赖或未指定checkout时，该集成项明确skip，不用mock代替安装。验收统计与污染/重叠拦截的测试由主任务单独负责。手动结果与GitHub CI状态分开报告。


## 私有路径与恢复证据加固

v2桥接拒绝checkout内的真实或合成输入、响应和输出；路径逐组件通过O_NOFOLLOW及目录描述符打开，不跟随父路径或文件符号链接，拒绝父目录跳转。直接数据父目录必须当前用户所有且无任何组/其他权限；文件必须同属当前用户、普通文件、无组/其他权限且硬链接数为1。系统上层目录可为共享遍历目录，不能把它直接用作私有数据父目录。SQLite、WAL及SHM等已存在图目录内容同样检查，新建SQLite及侧文件使用私有权限。检查失败不会悄悄chmod补过门槛。

resume先核对input.json原字节与receipt哈希，再与SQLite检查点的输入/receipt元数据锚点和原始证据字段核对。逐份已保存请求须匹配其指定历史检查点的实际中断；当前请求还须对应最新检查点。历史响应亦核对提示哈希、捕获/生成时间及检查点中的辩论内容。修改输入和receipt两者仍会因检查点锚点不符而拒绝。不创建缺失的恢复数据库，不把新空图冒充恢复。

请求第一次进入真实节点中断时捕获带时区captured_at，并持久保存。LangGraph重放从原请求复用该时间；响应生成时间须不早于该原始捕获时间且不晚于实际检查时间。时间检查在保存响应前执行，拒绝旧响应而不误拒绝晚于原捕获、早于重放的合法响应。旧v1记录缺少这些证据时失败关闭，不自动迁移或改写旧真实研究。

新增实质回归覆盖checkout、父/叶符号链接、非私有目录/文件、硬链接、FIFO、原始输入/receipt单独和协同篡改、请求时间/提示/检查点ID篡改、历史请求/响应篡改、检查点原证据改变、过早响应，以及跨进程重放复用捕获时间。均使用合成输入和真实安装的上游图，无新增真实LLM/来源请求、历史收益计算或结构候选。私有权限和本地相互核对仍不能防同一文件所有者同时改写所有证据，不宣称远程WORM或完整抵御同uid攻击。


## 共享原子预算与实际入口

`start`现在必须提供`--budget`和稳定的`--operation-id`。预算文件由Python标准库SQLite保存，直接复用现有私有路径边界，没有新增依赖。每笔预留在`BEGIN IMMEDIATE`事务内检查并提交，先于对外发布请求或消费响应；失败不退还，重复ID不再授权执行，同ID换参数也拒绝。启动一批最多一基金、三份请求；本批模型请求上限12、主要来源含重试总上限12、瞬时重试至多1，均未扩额。

预算初始化使用已有`upstream_bridge`命令入口，种子必须是私有原始JSON：

```json
{"run_id":"reviewed-shared-run","used":{"source":null,"retry":null,"llm":null,"prediction_batch":null},"candidate_history":null}
```

```bash
PYTHONPATH=FundPilot /private/venv/bin/python -m fundpilot.upstream_bridge budget-init \
  --seed /private/project/reviewed-seed.json --budget /private/project/budget.sqlite
PYTHONPATH=FundPilot /private/venv/bin/python -m fundpilot.upstream_bridge budget-stop \
  --budget /private/project/budget.sqlite --reason platform_warning
```

这是安全的未知状态示例，会拒绝新动作。只有经独立核对的实际操作计数才可填非负整数；0须确实已知，不能从空预留推断。`candidate_history`须保留完整原记录，未知用null；旧`attempted_at`与`counts_toward_next_7_day_change_budget=true`原样保留。不得用新的目录、run_id、空历史或新账本绕过旧消耗。初始化拒绝覆盖已有文件；切换运行或恢复导入需要先审阅账本及完整历史，不自动创建/迁移/清零。程序不能替调用方证明导入历史完整。

`start`原子占用批次；真实上游图的每次中断，在写出可供宿主LLM读取的请求前占用`llm`操作；`resume`从受检查点锚定的receipt读取同一账本、run_id和操作ID，以独立响应ID原子占用一次再写入响应并推进图。resume不接受另一个预算参数；旧图没有绑定则拒绝自动迁移。并发重复start/resume只有一次获得执行权。纯冻结/校验入口不发模型或来源请求，仍仅进行形状和证据检查，不以其内存RunBudget充作共享执行授权。

已提交预留但未完成的动作保持占用，重启后不自动执行第二次。尤其崩溃在“预留完成、响应或检查点尚未写完”之间时，旧请求/检查点可保留，但恢复执行保守拒绝，须人工核对准确结果再另作受审恢复；没有自动的恰好一次外部副作用保证。stop持久化并禁止后续动作；调用者观察到平台额度警告必须先调用budget-stop，不能自动重试。账本/父目录权限、符号链接、硬链接、只读、缺失或SQLite/JSON/校验和损坏时失败关闭，不创建空账本冒充恢复。私有SQLite与校验和不防文件所有者恶意同步改写所有数据。

`DurableBudget.reserve`还提供来源/瞬时重试与候选/一次评价的原子占用。候选按持久原历史及所有已占用候选检查滚动七天，时间在程序内捕获，不接受调用方倒填；评价须关联本账本候选且只占用一次。当前没有实际外部来源抓取器或候选执行器接入这个模块，不声称通用工具、外部连接器或所有潜在调用已被拦截。旧register_candidate/review_candidate是纯声明校验，不是执行授权。SQLite要求支持可靠本地文件锁的同一权威文件；不同机器各自下载的快照不构成共享锁。跨机器并发、分布式租约/栅栏和自动跨机器图迁移未实现，须维持唯一执行者，不能宣称已经分布式互斥。共享账本不能计量不可见的账户token、当前会话上下文或平台隐藏请求；实际token及账户余量继续unknown。桥接预留约束的是请求发布与响应消费；宿主绕过入口手动重复调用同一提示不在CLI可见范围，真实LLM消耗仍需外部轨迹核对。

复验包括13进程同ID只成功一次、13个不同ID共12次上限、失败/重试总额、进程commit后强制退出再重放、持久stop、unknown/损坏/权限/链接拒绝、保留两条历史，以及真实安装上游的13并发start、并发resume和恢复占用中断。全部使用合成材料和synthetic_fixture，不产生真实模型/来源请求、收益评价或结构候选。工程验收独立于12个月历史策略验收；项目仍未完成。


## 真实历史证据与宿主响应模板

真实项目先恢复最新私有状态，核对阶段权限、旧预算、完整候选历史及唯一执行者。unknown用null，不复用合成零种子。`budget-init`不是重置/扩额命令；已有账本直接恢复，不重新初始化。证据JSON仍是单基金格式：

```json
{
  "fund": "<已核对的基金代码:份额类别；未知类别明确unknown>",
  "information_cutoff": "<带时区历史资料截点>",
  "market_report": "<公开来源ID/URL、对应版本发布时间、实际抓取与已知时间、原字节哈希、事实及反证>",
  "fundamentals_report": "<基金实际暴露、A/C逐批费用、申赎/确认/到账与分红等已核实事实；缺失unknown>",
  "context": "retrospective/reused_development/non-OOS；LLM历史记忆风险；观察基金不等于持仓；无现实指导"
}
```

尖括号是需要人工替换的模板，不是已核实资料。自由文本输入不会由程序自动验证来源事实或历史可得性；保留原始公开材料、哈希与独立审校。不要向LLM提供真实账户或凭据。用前述start命令冻结输入后，每次按以下步骤恢复，不能自动把合成响应改标为真实：

1. 宿主完整读取待处理request的prompt、prompt_sha256、role和captured_at，把prompt交给当前已获授权LLM；这是实际人工/Agent宿主步骤，CLI自身不调用SDK。
2. 保存该次实际生成的完整原文，并由实际执行生成的宿主记录真实generated_at和可知model_ref；未知模型快照明写unknown。generated_at不得用历史cutoff、旧响应时间或事后包装时间冒充。
3. 在私有response-N.json中填producer=actual_current_llm、对应prompt_sha256、model_ref、generated_at、content。文件0600、父目录0700；模型身份声明须由外部调用记录核对。然后单独新进程运行resume，得到下一角色请求；共三份，完成后读取result.json。失败及未知结果先保存，不自动重试。

可交给宿主LLM的执行指令：读取指定request.json的完整prompt，只依据其冻结证据回答；保留来源ID、反证、失效条件、未知和历史污染限制；不要自行抓取新来源、交易或改预算；返回实际生成原文和可审计的生成时间/模型标识，由宿主写入响应，不伪称上游原生API调用。原生SIWC仍需本人官方授权，本模板不登录或读取任何凭据。

## 冻结恢复和验收出口

start保存input.json原字节、receipt和图检查点；每份request、response及result是独立新文件，不覆盖旧件。执行进程完全关闭后，保存graph目录全部文件及其绑定的budget.sqlite、原证据/响应输入、文件SHA256清单与最新私有状态。上传到已授权私有持久存储并重新取回核对；本地/tmp或0700权限不能代替持久保存。恢复时保留唯一权威账本身份和原receipt引用，核对原路径/输入/检查点再resume；不能只复制graph、另建零预算。跨机器路径重定位/分布式唯一执行没有自动迁移，须审查恢复，不能把两份快照并发运行。退出进程后的同路径文件恢复由合成测试实际验证。

图result.json是带scope的研究状态，不是已核实估值日历的评分卡或投资验收报告。后续若获准评价，先按[llm-loop.md](llm-loop.md)独立映射来源、原生成时间、1/5/20估值日D0/Dh及日历；未知资格保留pending，不直接自动转换或回填旧卡。freeze保存cards/sources/calendar原字节；score读取后续NAV，仍不得冒称OOS。资金条件比较与[historical-acceptance.md](historical-acceptance.md)的12个月门槛另判，本批没有运行真实收益评价。完整执行机制、生产采集、跨机唯一执行、私有调度及真实模型身份审核仍需外部支持；本CLI不因工程跑通自动完成这些能力。

资料与权限齐备后，已有冻结和验收入口的最小命令如下；这些不是上面合成传输脚本的自动后续，不生成缺失证据，也不在本批运行真实评分：

```bash
"$FP_VENV/bin/python" -m fundpilot.llm_loop freeze \
  --cards "$FP_PRIVATE/cards.json" --sources "$FP_PRIVATE/sources.json" \
  --calendar "$FP_PRIVATE/calendar.json" --output "$FP_PRIVATE/new-frozen-cards"
"$FP_VENV/bin/python" -m fundpilot.acceptance \
  --input "$FP_PRIVATE/qualified-episodes.json" --output "$FP_PRIVATE/new-acceptance-run"
```

freeze的receipt与验收输出各自私有保存；验收工具不会从图结果推导净收益/CPI、签认独立性或自动准许现实指导。输入schema见对应文档，不将synthetic_fixture改名为真实证据。

## 原生单分析师九节点的宿主桥接

`upstream_bridge start --graph-mode native_news`复用固定上游GraphSetup及原生news、bull、bear、research manager、Trader、三风险节点与Portfolio Manager，共九次文本响应。原提示及其哈希单独保存；传输层加基金历史模拟边界，不用新角色提示冒充上游。保留原路由与SQLite检查点。结构化生成明确禁用，不隐藏重试；stock工具不执行，只使用冻结的共享证据，进程内网络连接被拒绝。这是闭合证据对照配置，不能冒称上游完整产品、实时工具或原生SDK推理。

真实材料仍由宿主实际读取request并生成响应；producer、model_ref、generated_at与prompt_sha256格式沿用前述模板。模型精确版本未知须明确unknown，不把合成响应改名。九次resume每次可在新进程执行；请求原捕获时间在重放时复用。input、receipt、各历史中断、当前中断及累计响应字节哈希与检查点元数据相互核对。输出的LangChain消息以其原生字典格式保存。全部路径、权限、重复执行和不确定崩溃的拒绝规则沿用稳定入口。

同一私有evidence.json除原字段外须有`portfolio_context`：完整非个性化观察组合及覆盖/日期、份额、现金、冻结、应收、批次和unknown。它必须原样包含在`context`中，使稳定三节点也看到相同组合；不截取前三只、不据名称推断暴露。观察例不等于用户持仓，固定观察池覆盖限制不得当作完整个人组合检验。

在**已经核对操作计数与本次授权**的同一账本中，先完成稳定三响应，然后启动唯一原生对照臂：

```bash
PYTHONPATH=FundPilot /private/ta-venv/bin/python -m fundpilot.upstream_bridge start \
  --evidence /private/research/evidence.json --output /private/research/new-native \
  --upstream /private/tradingagents --budget /private/research/budget.sqlite \
  --operation-id stable-comparison-native --graph-mode native_news \
  --comparison-root /private/research/completed-stable
PYTHONPATH=FundPilot /private/ta-venv/bin/python -m fundpilot.upstream_bridge resume \
  --root /private/research/new-native --response /private/research/actual-answer-1.json \
  --upstream /private/tradingagents
```

第二条依次用于九份实际回答。`--comparison-root`要求原稳定结果与已完成检查点、三份历史请求/响应、输入原字节和权威账本身份一致；不允许借另一个账本开始对照。新增`comparison_arm`操作是原批次的唯一伴随执行权，不增加prediction_batch、模型、来源或候选配额，仍逐次原子占用同一个12请求总额。要求至少留足九请求，失败或中断不退款、不自动重放；13进程竞争同一父批次最多一个伴随臂获准。它不是策略候选或收益评价授权。

诊断允许稳定3对原生9，报告各自成本及资源混杂，不要求同调用数，也不据此声称严格等资源的结构因果。若真实账本`llm`或`prediction_batch`为null，现有require_known会在创建图/发布请求前拒绝；账户token不可见与该操作检查分开。不能用新run_id、合成零种子或更换路径解除。需完整且有据的旧计数，或另经明确批准、保留旧unknown累计的一次受限批次迁移；当前没有自动额度迁移命令。FinRobot基金数据契约阻塞继续保留，不伪造财报凑第三臂。

## 明确批准的一次独立诊断额度

`python -m fundpilot.diagnostic_grant --legacy /private/authority/legacy.sqlite --approval /private/authority/approval.json`只用于有明确人类批准的单次诊断。approval须保存原问答、批准实际时点、出处、唯一approval_id、authority_legacy_path、旧账本SHA256及全部冻结文件路径/哈希；scope严格为llm=12、source=0、evaluations=1、candidate=0。真实批准与这些文件均私有，不复制示例当授权。

权威registry固定在原账本父目录，派生scope账本名由批准ID确定；同一批准只能创建一次。重复执行返回同一已消耗账本，pending/崩溃或缺失账本拒绝重发；复制至其他目录与原批准的canonical路径不一致而拒绝。保留原账本字节、完整候选历史和累计unknown，新scope已用0仅表示该次授权尚未用量，不代表旧用量或token=0。候选、来源和重试操作在此scope禁用；一次diagnostic_evaluation仅在12份请求与12次响应消费完成后允许，仍无融合或投资晋级。注册表/同一账本要求唯一云执行者和可靠本地锁，不提供跨机器多副本互斥、密码学身份签名或隐藏token计量。approval真实性由宿主核实，工具不能替人批准。

## 独立趋势诊断额度迁移

`python -m fundpilot.trend_diagnostic_grant --legacy <权威旧账本> --approval <私有批准记录>`只迁移已明确批准的固定趋势诊断。批准记录必须逐字绑定批准答复、唯一scope ID、三个固定公开样例、1／5／20期限、统一资料截点、权威旧账本路径及SHA256，并为协议和实际输入逐文件记录路径与哈希。它严格接受最多12次模型请求、12次来源尝试、一次固定评价、0结构候选和0交易；已发生的3次来源尝试作为新scope的初始消耗保存，只剩9次，不从空目录或空预留推断为0。

该入口复用权威旧账本旁的同一registry。批准ID决定唯一派生账本；并发领取返回同一账本，claimed状态、账本缺失、绑定变化或复制旧账本到其他目录都会关闭失败。旧累计和账户token仍为unknown，完整候选历史原样嵌入但候选操作禁用。来源及一次瞬时重试共享12次上限；模型请求仍在发布前逐笔预留，响应消费另行预留。只在至少一份响应完成、且每个已预留模型请求都已有对应响应消费时，允许一次固定评价；因此可保留部分样例的missing/pending，但不能遗漏已发请求后抢先评价。旧一次历史对照的12份响应门槛与来源禁用行为保持不变。

此迁移只提供同一主机、同一权威SQLite文件上的原子门禁。它不抓取来源、不生成模型回答、不运行评价、不计量平台token，也不提供跨机器锁。真实批准和权威旧账本不进入Git；缺其中任一项时只能完成合成工程验证，不能创建真实额度或宣称研究已经开始。
