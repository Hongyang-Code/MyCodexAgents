# PaperFigureAgent

接收自然语言、截图、论文材料或已有.drawio，制作原生可编辑科研图。已提供实际Python工具与Codex入口；语义理解、视觉设计和来源判断由宿主AI完成。没有独立自动调用模型的后台服务，也不要求API密钥。

## 直接使用

在当前仓库的Codex对话里说：

> 请读取 `E:\MyCodexAgents\PaperFigureAgent\AGENTS.md`。把这段方法画成论文图：【直接粘贴内容或给文件】。自行整理结构，完成科学、布局、视觉及可编辑性检查后，交付draw.io和同版预览。

也可以只说：

- “按这张截图重建，文字和箭头要能编辑。”
- “只把图里的两个模块改名，其他页面和布局保留。”
- “输入先编码，再经三个不同分支，最后融合输出。画清楚这个过程。”
- “接着刚才的任务，反馈来自更新后的状态，回到残差计算。”

不用填表，不用列节点、坐标或JSON。没有尺寸默认180mm。关键科学关系缺失时才具体补问；常规排版自主决定。审查未完成或证据缺失的版本会明确标记。

## 本地工具入口

Windows：在本目录执行 `./bootstrap.ps1 -Python <可用Python路径>` 创建独立.venv。随后：

```powershell
./.venv/Scripts/python.exe run.py capabilities
./.venv/Scripts/python.exe run.py start "画出输入、处理、输出的流程"
./.venv/Scripts/python.exe run.py resume <返回的任务目录>
./.venv/Scripts/python.exe -m unittest discover -s tests -v
```

macOS/Linux：`python3 -m venv .venv`，之后`.venv/bin/python run.py ...`。这两个平台未在本次实测。可选`pip install -e .`获得paperfigure命令；不安装也能run.py直接运行。核心零第三方Python依赖；PDF/图片扩展按需在.venv安装`.[materials]`，也可调用宿主已有读取工具。

start保存原话并建立状态，不伪装成独立模型。宿主继续填写内部数据并调用工具，流程见[agent.md](agent.md)及[工具契约](tools-contract.md)。

原生渲染优先检测现有draw.io，或设置DRAWIO_BIN。Windows x64可显式运行`python tools/setup_drawio.py --download`下载官方便携版到隔离缓存；实际运行本机已准备完成。安装脚本需要联网，绘图核心与已备好的原生渲染可以离线。

## 示例与验证

`python examples/run_examples.py --output outputs/新的验收批次 --render`重做三种示例（分支合并、分组对照、循环反馈）及完整候选，不包含真实科研结果。

交付通常为任务目录下delivery/figure.drawio、同版preview.png；原生SVG/PDF按能力提供。状态、素材清单、审查、修改历史保存本地，不提交Git。具体实际运行结果和限制见[VALIDATION.md](VALIDATION.md)。

局部编辑保留原图及无关页面，只修改指定对象；最终未压缩XML，标题、模块、连接、标签均可编辑。照片内部像素仍是位图，外部标注及图像组可以独立编辑。

## 能力边界

首版自动布局面向小中型有向图、显式反馈和一级分组，提供自定义布局接口。复杂嵌套、旋转、曲线、同端点多条语义线、第三方自定义图元需宿主针对性处理。不能把有限测试推广为任意论文图均可自动完成。

结构检查、科学理解、实际看图、交互编辑分别记录。本次已原生导出PNG/SVG/PDF；交互工具启动失败，UI拖动/改字/保存重开标为not_run。XML局部编辑与连接引用测试实际通过，不能替代UI验证。
