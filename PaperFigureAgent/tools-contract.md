# 工具契约

核心仅依赖Python标准库；在本目录运行`python run.py --help`。所有路径由任务调用传入或相对本包确定，无本机项目路径、论文名或固定领域结构。CLI报错输出JSON并返回非零；不静默省略失败对象。

| 入口 | 输入 → 实际输出 |
|---|---|
| capabilities | 无 → 本机读取/渲染能力，宿主能力待实际检测 |
| start "自然要求" --material 文件 --root 输出目录 | 原文和材料 → task_id、隔离状态目录、初始快照 |
| read 文件 | 文本/PDF/图像/drawio → 内容/元数据/页/对象；图像语义交宿主 |
| resume 任务目录 | 当前状态 → brief/requirements/state/qa，不自动回滚 |
| plan 任务目录 | 宿主生成图谱 → LR/TB候选布局、几何分数和初选；不证明美观 |
| build 任务目录 --name 新文件.drawio | 图谱/布局/样式/素材 → 未压缩原生图，拒绝覆盖 |
| check 任务目录 图文件 | 源图和语义/需求 → XML/拓扑/几何/素材/历史检查 |
| render 图文件 输出.png --receipt 收据.json | draw.io Desktop CLI → 原生PNG/SVG/PDF与同版哈希；无工具not_run |
| patch 原图 新图 操作.json --expected-hash 哈希 | 精确操作 → 备份+新图+对象差异；过期基准拒绝 |
| diff 原图 新图 | 两版 → 各页添加/删除/修改对象，不代替科学判断 |
| require 任务 "反馈" --objects ID --supersedes R001 | 用户反馈 → 保留原文的有效要求历史 |
| checkpoint 任务 阶段 --optimization | 当前文件 → 不可变版本与轮次，上限3 |
| deliver 任务 图文件 审校.json --preview 原生.png | 重核检查和哈希 → delivery/figure.drawio与预览；失败不假称通过 |
| deliver … --problem | 明确未完成任务 → problem-version与缺口说明 |

Python API：layout.plan支持自定义boxes；drawio.build支持图像组/原生组件；drawio.patch保留无关对象/页。特殊图、嵌套组、同端点并行边、相对端口、旋转和复杂曲线由宿主针对性处理，当前保守检查会报不支持或需要目视，不保证任意第三方图完整自动布局。

## 原生适配

检测顺序：显式--drawio、DRAWIO_BIN、PATH、隔离runtime收据、常见安装位置。tools/setup_drawio.py --download明确请求后下载官方Windows x64便携版，校验官方SHA256，仅写.cache，不安装系统。其他平台手动提供本机路径；未实测。官方版本27.0.2以后CLI页码从1开始；工具对外--page从0开始，旧版可设DRAWIO_PAGE_BASE=0。

使用独立Electron临时配置；Windows后台调用隐藏窗口。不删除用户文件，不覆盖既有预览。超时55秒返回fail；检查文件签名，不能把旧图片判成新渲染成功。PDF为原生裁切导出；投稿精确页面尺寸需另外核验，不默认声称180mm的PDF物理页面。

官方接口依据：[draw.io XML](https://www.drawio.com/docs/manual/advanced/diagram-source-edit/)、[导出](https://www.drawio.com/docs/manual/export/export-diagram/)、[Desktop源码与版本](https://github.com/jgraph/drawio-desktop)。能力事实以实际运行收据为准。
