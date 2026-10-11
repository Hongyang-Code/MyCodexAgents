# PaperFigureAgent · Codex 入口

读取本目录 agent.md，按当前阶段读取 prompts/，执行 tools-contract.md 与 state-spec.md。这是 Codex 宿主适配入口；平台无关行为位于 agent.md。

接收自然语言与已有材料，由当前任务中的宿主 AI 进行真实语义理解、视觉观察和设计评审，调用 run.py 完成确定性工具工作。不得要求用户整理 JSON、节点、端口或坐标。不要把示例图的内容作为默认科学结构。不默认启动子智能体，不自动提交或推送。

优先使用本目录 .venv 中的 Python；不存在时检测实际可用解释器并运行 bootstrap.ps1，或 python -m venv .venv。核心标准库即可运行；PDF/图片可使用宿主已有读取能力，不需污染研究项目。capabilities 只是本地探测；实际调用宿主看图、读取、联网及交互工具后才记录其可用性。

如果遇到环境阻碍，先完成不受阻的工作，再明确 not_run；不将预览构造、结构测试或模拟接口写成真实模型/原生编辑验收通过。
