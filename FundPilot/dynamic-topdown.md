# 总—分—总动态回测接线

本增量复用现有 `EventSimulator`，把一次静态配置扩展为按截止时点循环的工程流程：

**统一趋势 → 共享该趋势的多方法方案 → 最终选择／融合 → 显式交易计划 → 基金事件模拟。**

入口为 `fundpilot.dynamic_topdown.run_dynamic`，目前只接受 `synthetic_fixture`。它没有调用真实大模型、运行数学优化器或训练神经网络；不能作为完整 Agent、盈利验证或投资资格证明。

## 已接通的部分

- `predict(view)` 返回一份带截点、依据和失效条件的 `Trend`。程序计算指纹，所有候选必须引用相同指纹。
- `generators` 中的各方法共享该趋势与同一时点账户状态，返回不同的目标权重；不在中间层重新预测趋势投票。
- `select(view, trend, candidates)` 返回选择或融合比例及理由。生成方法与最终选择是不同接口。
- 融合先合并目标权重，再调用一次 `plan` 形成显式订单；不平均历史收益，不分别执行子方案。
- 保持当前组合为必备候选。它不等于清仓或全现金，也不强制产生交易。没有明确估值目标时，不支持把“保持当前状态”混入目标权重融合。
- `plan` 返回 `ExecutionPlan`，即订单与执行／等待理由。申请批次先在现有模拟器副本上核对资金和份额，失败不部分提交。
- 完成选择和决策记录的内存指纹后，才调用 `settle` 取得后续确认、到账事件；这些未来事件不传给研究回调。
- 截点之后的资料与净值不传给回调。每个回调获得独立账户副本，修改自己的副本不能改真实模拟状态。
- 保留逐次趋势、候选、选择、融合目标、订单、等待理由、已知信息和账户状态。记录带连续哈希；返回结果仍只是内存工程记录，不能冒称已完成私有持久冻结。

## 冻结上游的离线适配边界

`fundpilot.frozen_topdown` 可以在不重放图、不调用模型、不改变预算的前提下，读取一份已经完成的 stable v2 上游桥接目录。它逐项核对输入哈希、固定上游提交、scope、三组连续请求／响应、prompt 哈希、生成时间、producer 列表以及 `result.json` 中的最终研究文本。只有研究经理返回了完整的 1／5／20 结构化 JSON 时，才会确定性地生成一份 `Trend`；普通文本会关闭失败。

该结果明确标记为 `replayed_frozen_output`。其生成时间可以晚于历史信息截点，因此只是历史开发材料，不是该截点真实可用的独立预测。当前 `run_dynamic` 仍只接受合成回调，这个离线适配器不会绕过该入口限制。

研究经理给出的条件配置讨论不等于最终候选裁决。`load_frozen_research` 因而始终返回 `choice=None`。现有 `fundpilot.final-choice-*.v1` 只绑定 Trend 指纹、candidate IDs、prompt 哈希、producer、模型标识与实际生成时间；它尚未绑定同 ID 候选的权重／费用风险表和当时账户状态。因此它只能验证既有响应信封，不能证明候选内容或状态没有被替换。该缺口不得用改名掩盖。

`run_frozen_synthetic` 进一步把两种冻结信封接到一次 `run_dynamic` 决策，供复制恢复和端到端回归使用。它只接受一个截点，并要求研究与最终选择的 producer 都是 `synthetic_fixture`；`actual_current_llm` 会关闭失败，不能借该入口绕过真实运行资格。返回值保留两段响应的 prompt/response 哈希、模型标识、生成时间和源文件，并固定 `new_model_inference=false`、`temporal_oos_qualified=false`。测试把完整信封复制到新私密目录后，在独立 Python 进程恢复并核对同一决策摘要。

## 合成动态案例

测试在明确标记的两个合成资产间执行：

1. 第一个截点依据合成趋势买入 A。
2. 第二个截点趋势改变，决定赎回 A、配置 B。
3. 赎回确认后、资金到账前，继续等待，不使用应收款买 B。
4. 到账同一时刻仍按原内核约束保持不可用；之后才申购 B。
5. 使用后续确认事件更新份额，并分别保留期末账面估值、可用现金、冻结现金和应收。

合成费用和价格只用于精确算术回归。该路径没有证明策略能预测市场或获得收益。

## 验证命令

在仓库根目录的 Linux / Python 3.12 环境执行：

```bash
PYTHONPATH=FundPilot python -m unittest discover -s FundPilot/tests -p test_dynamic_topdown.py -v
PYTHONPATH=FundPilot python -m unittest discover -s FundPilot/tests -p test_frozen_topdown.py -v
PYTHONPATH=FundPilot python -m unittest discover -s FundPilot/tests -p test_conditional_dynamic.py -v
PYTHONPATH=FundPilot python -m unittest discover -s FundPilot/tests -q
```

云端实际结果以该提交的 CI 回执为准，不能提前签认。

## 条件历史冻结输入入口

`python -m fundpilot.conditional_dynamic --input INPUT.json --output RESULT.json` 接受已经在外部冻结的多截点决策和事件，直接交给现有 `EventSimulator`。它不调用 `run_dynamic`，也不改变 `run_dynamic`／`run_frozen_synthetic` 的 `synthetic_fixture` 门禁；真实响应不能改名为 synthetic。输入必须明确声明 `mode=conditional_historical`、`real_execution_verified=false`，逐截点提供不可变 `decision_ref`、既定 choice 和事件。hold 必须没有事件，adapter 不会为到账后执行偷偷生成 Order。

新输入应使用 `fundpilot.conditional-dynamic-replay.v2`。严格 v2 不接受调用方自填的 64 位哈希，也不允许用旧 choice v1 原件升级：每个决策必须指向 checkout 外私有目录中的原三研究 request/response/result 和独立 choice v2 request/response，由现有 `load_frozen_research`／`load_frozen_choice` 重新读取并核哈希。choice v2 的 prompt 同时绑定真实 replay state、完整合法候选内容（非 hold 权重非负、有限、唯一且合计为1；真正 hold 的 `target_weights=null`）以及 cutoff、decision_ref、当前 Order 意图。未来 Confirmation／Receipt 的价格和时间不属于当时选择输入，完整结算 tape 由 replay `input_sha256` 独立留痕。缺原件、同 ID 改权重、改截点或改 Order 均拒绝，不能输出 bound=true。旧 v1 文件仍可复现原数值，但输出明确标记 `legacy_unbound_decision_context=true`，不签认研究、状态、候选和选择已经连接。

`event_kernel_attested=true` 只表示调用方愿意让现有 typed kernel 检查这组条件研究事件，不证明真实成交。未知确认／到账历史只能写成预先冻结的情景时间，并在 limitations 保留；不得把情景改写成已核实交易。每个截点前只推进队列中不晚于该截点的结算，当前冻结决策只能提交自己的 Order，未来非 Order 事件入队；到明确 `end_at` 后仍未发生的事件保留 pending。输出同时分开期末账面估值、可用现金／冻结资金／应收和 `conditional_liquidation_value`，后者固定标记为非已到账现金。条件清算规则必须与资产一致，并在明确 `liquidation_at` 仍生效、已可用。

CLI 的输入和输出必须位于 checkout 外、由当前用户拥有且组／其他用户无权限的私有目录。输入按私有普通文件读取；输出使用 `0600` exclusive create，既有路径和符号链接均拒绝，不先检查再覆盖。

合成回归覆盖两个截点、hold 不生成交易、赎回确认后未到账资金不能申购、条件清算不等于现金，以及 CLI 子进程写出结果。该入口没有重新选择策略、评分或晋级。

进程内的单请求来源回调应逐次通过 `DurableBudget.run_source_attempt`：先持久预扣，再调用一次 callback；callback 抛错时费用仍已占用，达到上限或重复 operation ID 时 callback 不执行。调用者必须保证一个 callback 最多执行一次 HTTP／来源动作；该方法无法拦截 callback 内的多次 HTTP，也无法拦截绕过本进程的宿主 web 工具，因此并非所有来源路径的全局机械硬保护。它不恢复已经超额的预算，也不授权新的来源请求。

## 仍未接通

- 前瞻或真实成交动态运行仍未接通。当前已有条件历史冻结输入入口，但固定为 `real_execution_verified=false`，不把历史生成内容包装成当时可用预测；原桥接和预算入口未改动。
- 可运行的不同数学／机器学习／神经网络策略适配器及其训练、输入资格和效果比较。测试中的权重来自明示的合成回调。
- 通用目标权重到场外基金订单的规划器、逐批费率／取整／限购／QDII 日历和统一硬风险检查。本入口不把现有简化 Rule 的固定费率升级为完整真实执行器。
- 成熟预测评分、错误归因、经验审查、跨任务恢复、重复运行幂等与私有不可变冻结的端到端连接。
- 同条件动态基线、真实历史比较与年度投资验收。

回调本身可能访问外部资料或通过闭包／模型记忆知道未来；本模块不能证明外部回调清白。宿主必须维持纯合成回调，真实接入须另行通过来源、预算、权限和评价协议审查。没有新依赖、网络抓取、模型服务、凭据或真实交易接口。项目保持未完成。
