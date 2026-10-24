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

上游源码[LICENSE](https://github.com/TauricResearch/TradingAgents/blob/e8f5503e9b86d5c2710b0c76b1f686703968c9df/LICENSE)为Apache-2.0。首次CI提交仅增加云端安装与相关测试。后续已接入原生研究节点与真实当前会话LLM桥接，调用范围及限制见[upstream-adaptation.md](upstream-adaptation.md)；不将桥接称原生API调用。全部传递依赖的许可证/供应链审计尚未完成。

GitHub公开仓库标准Linux runner在当前官方计费说明中免费；未启用较大runner、付费模型或收费数据源，没有上传artifact。本CI不带账户密钥，不读取私有档案，不运行真实基金研究。

## 仍未通过的验收

已完成一个真实当前会话LLM桥接历史诊断，并有独立新云任务恢复和只读算术核对。原生SDK推理/认证、完整基金渠道/费用/日历、严格历史净收益与独立12个月验收、受控研究改进及定时首次触发仍需分别验收。短期方向/Brier不能证明12个月不亏或抗通胀，LLM自报概率不能作为通过依据。达到历史门槛之前保持研发与模拟，现实指导禁用。


## 适配后的CI

[固定11a72c45的云端运行](https://github.com/Hongyang-Code/MyCodexAgents/actions/runs/40077787113)完成292项基础回归（3项可选集成skip）、23项和12项跨模块回归；上游环境另外实际执行10项基金桥接/恢复测试与65项上游离线测试，均通过。工作流以editable方式加载已验证的干净上游checkout，核对实际Git提交和导入路径；版本约束安装也已实际通过。不读取私有研究档案或模型凭据。
