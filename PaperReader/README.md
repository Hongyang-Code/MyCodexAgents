# PaperReader

以简体中文完成论文概括、阅读价值判断、证据评估、详细报告和结构导图。保留必要原题、引用和术语。不接入 Zotero，Markdown 可直接复制。

## 开始使用

在 Codex 中将本目录作为工作目录启动任务，发送 PDF、链接、DOI 或明确题目即可：

> 请按 PaperReader 流程完整阅读这篇论文，完成证据核查、质量检测、报告和结构导图。

从根目录使用时，明确说“先读取 PaperReader/AGENTS.md，并按该智能体工作”。已有任务不会因新增文件而自动重新加载指令；可主动要求重新读取。

CLI 可用时运行：

```powershell
codex -C E:\MyCodexAgents\PaperReader
```

新会话指令加载验收提示：

> 不阅读论文、不修改文件。概括你加载的角色、输出语言、四项交付、质量检测流程、本地命名和 Git 同步范围。

预期：简体中文主体；摘要、可靠性、详细报告、PNG；检查→修改→复查；年份—venue-短标题；产物仅本地。这验证指令加载，不保证所有未来报告正确。

## 工作文件与产物

AGENTS.md 定义角色，workflow.md 定义工作流，quality-check.md 是独立交付门槛，templates/ 包含报告/来源/导图模板，scripts/ 提供目录与绘图工具，tests/ 提供工具测试及语义审校挑战。

每篇论文目录为 outputs/年份—会议或期刊名字-短标题/，包含 report.md、sources.md、mindmap.png、身份文件 .paper.json 和内部缓存 .cache/。

原文与全部阅读产物被 Git 忽略，不得强制加入版本库。年份和 venue 信息对应读取版本；预印本用实际平台；未知项不猜。同一身份可复用目录，但写入前须先读取旧报告，保留用户修改。不同论文同名追加身份哈希；paper-id 应含阅读版本。目录工具不会覆盖已有报告。

## 辅助工具

需要 Python 3.10+；目录工具仅使用标准库，绘图需要 Pillow 与中文字体。优先用 Codex 已有运行时。没有现成依赖时，在本目录运行：

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
```

以下命令从本目录运行；python 可替换为实际运行时路径：

```powershell
python scripts/prepare_output.py --year 2016 --venue CVPR --title 'Deep Residual Learning' --paper-id 'https://openaccess.thecvf.com/content_cvpr_2016/papers/He_Deep_Residual_Learning_CVPR_2016_paper.pdf'
python scripts/render_mindmap.py 'outputs/2016—CVPR-Deep Residual Learning/.cache/mindmap.json' 'outputs/2016—CVPR-Deep Residual Learning/mindmap.png'
python -m unittest discover -s tests -v
```

图 JSON 以 templates/mindmap.json 为结构参考；采用真实章节和中文要点，不能直接交付占位文案。图片已存在时换新文件名重绘，看图通过后再替换。工具不验证论文事实，仍须完整质量检测。

字体依次检查 --font、PAPERREADER_FONT、Windows 微软雅黑/黑体、Linux Noto CJK、macOS PingFang。自定义字体须支持中文；实际检查生成字形。缺少字体明确失败。

## 验证与同步边界

自动测试覆盖目录与图片生成，不能替代语义审校。用 tests/quality-challenge.md 检查纠错和表达，再用完整开放论文核对证据与图表。

默认不运行论文实验，全文不可得时只交付受证据支持的部分。图片未生成或未检查须披露。常规阅读在对话展示完整报告与 PNG；配置实施试读可只提供本地报告链接。

仅按用户要求同步配置。同步前 git fetch origin，检查分支与 diff，明确选择配置文件提交。不强推，不定时同步，不提交 outputs/。
