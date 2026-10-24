# 云端工程验证与开源安装

本文件记录通用工程验证，不保存真实基金数据、预测、资产或运行状态。投资门槛尚未通过，项目未完成。

## 实际首轮验证

2026-10-24，在GitHub标准Linux云端runner、Python 3.12.15执行。提交57cac368f4ad2fc2a575e4b3cbb492e0f8705be5的[运行记录](https://github.com/Hongyang-Code/MyCodexAgents/actions/runs/40076242381)显示：FundPilot263项、ResearchHotspotFollow23项、TextReadable12项均通过；编译、发布检查和diff检查通过。

TradingAgents固定提交e8f5503e9b86d5c2710b0c76b1f686703968c9df已在新虚拟环境安装，pip check通过；上游认证、provider和检查点四个测试文件合计65项通过。测试包含替身，不能写成真实订阅登录、真实LLM或收益验证。没有安装或运行FinRobot，不将静态比较升级为实跑结论。

## 可直接运行的Linux命令

在本仓库根目录，用Python 3.12执行：

```bash
PYTHONPATH=FundPilot python -m unittest discover -s FundPilot/tests -q
python -m unittest discover -s ResearchHotspotFollow/tests -q
python -m unittest discover -s TextReadable/tests -q
python -m compileall -q FundPilot/fundpilot
python FundPilot/scripts/check_release.py
```

在全新临时目录安装上游，不挂载私有资料或凭据：

```bash
UPSTREAM_WORK=$(mktemp -d)
git init "$UPSTREAM_WORK/source"
git -C "$UPSTREAM_WORK/source" remote add origin https://github.com/TauricResearch/TradingAgents.git
git -C "$UPSTREAM_WORK/source" fetch --depth=1 origin e8f5503e9b86d5c2710b0c76b1f686703968c9df
git -C "$UPSTREAM_WORK/source" checkout --detach FETCH_HEAD
python -m venv "$UPSTREAM_WORK/venv"
"$UPSTREAM_WORK/venv/bin/python" -m pip install --no-input --disable-pip-version-check --timeout 30 --retries 0 -c FundPilot/requirements/tradingagents-linux-py312.constraints.txt "$UPSTREAM_WORK/source[dev]"
"$UPSTREAM_WORK/venv/bin/python" -m pip check
(cd "$UPSTREAM_WORK/source" && "$UPSTREAM_WORK/venv/bin/python" -m pytest tests/test_chatgpt_auth.py tests/test_chatgpt_provider.py tests/test_checkpoint_resume.py tests/test_checkpoint_lifecycle.py -q)
```

首次安装解析出92个带版本包；约束文件保存这次实际版本，源包另外按Git提交固定。约束针对上述Linux/Python范围，没有wheel哈希，也未声称跨平台完全复现。后续约束安装结果以对应CI提交记录为准，不能提前写通过。Python补丁版本由setup-python解析，实际值保留在日志。

## 复用边界与许可

上游源码[LICENSE](https://github.com/TauricResearch/TradingAgents/blob/e8f5503e9b86d5c2710b0c76b1f686703968c9df/LICENSE)为Apache-2.0。当前提交仅增加云端安装与相关测试，尚未把它的研究节点接入基金真实LLM流程；后续必须给出实际调用轨迹。全部传递依赖的许可证/供应链审计尚未完成。

GitHub公开仓库标准Linux runner在当前官方计费说明中免费；未启用较大runner、付费模型或收费数据源，没有上传artifact。本CI不带账户密钥，不读取私有档案，不运行真实基金研究。

## 仍未通过的验收

真实LLM调用、基金数据/渠道规则适配、完整历史净成本比较、受控研究改进、私有跨任务恢复和云端调度均须另验。短期方向/Brier不能证明12个月不亏或抗通胀，LLM自报概率不能作为通过依据。达到历史门槛之前保持研发与模拟，现实指导禁用。
