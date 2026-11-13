# 排障流程测试说明

[开发索引](README.md)

测试同时检查工具返回值、磁盘文件、备份内容、进程状态和持久化记录。测试服务器通过真实 BAT/ConPTY 启动可交互进程；存档测试使用固定来源的真实片段和生成样本；Agent 集成运行 AstrBot v4.29.4 的真实 runner，模型回复由测试控制。A/B 接口测试统一经 HTTPS。

## 当前验证

0.8.0架构整改后的结果见[整改与验证](architecture-remediation-0.8.0.md)。下列326项数字及原性能记录保留为整改前基线。

2026-11-13，0.8.0正式发行验证：Windows x64／Python3.12.14／PowerShell7／官方AstrBot v4.29.4，固定环境执行`pytest -q --require-astrbot`，350项通过、零跳过，947.96秒；保留audioop、pkg_resources和工具schema共3条上游弃用警告。首次命令误设PYTHONUTF8导致BAT系统中文编码文件的测试读取失败，修正验证环境后完整重跑得到上述结果，未修改产品代码。两发行包及四目标Probe重新构建，解压B包后构建wheel并在新环境安装，site-packages运行HTTPS CLI、独立托管、循环停服、辅助执行、备份修改及原窗口重启通过；Ruff、格式、设置页JS语法、113个本地链接及锚点通过。正式手册、安装版本声明和关联文档同步到发行附件，main按插件ZIP生成并保留原发布提交为父提交。未重新联调生产QQ、外部模型或生产整合包，Probe真实服验证沿用同日整改记录。

2026-11-13用户手册细化：README按B部署、独立窗口、A设置和完整群内流程重写，补齐两端软件版本、Java用途、资源、账号和网络要求，使用固定示例目录并解释各步骤的成功现象。核对11个群命令与当前入口、设置页按钮、CLI和窗口提示；2个JSON示例解析及实例规范化通过，11段PowerShell示例由PowerShell7.6.5解析通过，112个本地文档链接及锚点有效。AstrBot安装版本声明改为>=4.29.4，检查排除4.29.3并接收4.29.4、4.30.0和5.0.0；集成验证基线仍为v4.29.4，未实测高版本runner。两发行包和源码包更新后校验README、版本声明、关联文档及许可；本轮修改文档与安装版本声明，未新增测试或重跑功能回归，未重新部署真实A/B。消融审查将字段细节、维护和开发验证继续留在分层文档中。

2026-11-13创建任务补充说明：`/mcainew 任务名 [补充说明]`将引用原文和可选补充一起保存，首次模型输入可见；复用report及初始pending，不增加状态或后续补充调用。真实AstrBot v4.29.4的完整插件流程（带补充／不带补充）、缺少引用、权限和群隔离共11项通过，零跳过，44.02秒；模型由测试控制，未联调生产QQ或外部模型。同步帮助、使用与设计说明；消融审查保留原有任务创建和持久化路径。

2026-11-13运行时预设补充：扩展`mcai/agent_rules.md`的工作场景、消息可见范围、证据与恢复约定，补充上下文和群消息范围说明。真实AstrBot v4.29.4的插件命令、独立审核／规则重读、用户规则保留、全部工具链以及300轮历史压缩／续读／验收归档共31项通过，零跳过，146.04秒；未新增单元测试。模型由测试控制，未联调生产QQ或外部模型。两包构建及模板、文档链接一致性检查通过；较早完整回归仍沿用上方整改记录，本轮未重跑整套。

2026-11-13，0.8.0，Windows／Python3.12.14／PowerShell 7／AstrBot v4.29.4：完整回归322项通过，无跳过，耗时859秒；收尾新增4项边界场景后，终端与后台交互28项通过，耗时75秒。当前共326项场景。两项上游弃用警告来自audioop和工具schema。

重点实测：两个独立窗口运行时强杀B，两服保持运行，辅助诊断进程树结束；重启B后原会话自动重连，原任务标记中断。512 MiB共享测试额度下，一个180 MB诊断仍运行，另一个400 MB申请失败；修复脚本申请失败保留备份和原文件，取消后新诊断成功。Job配置失败阻止辅助执行；没有窗口时仍能查看主机指标，拒绝文件修改。

真实CLI通过嵌套ConPTY验证Tab补全、上键历史、中文输入与Ctrl+C；终端缓冲验证行数、字节、长行、未换行内容、淘汰游标和会话变更。HTTPS场景验证同编号不重放、窗口断线时已接受停服继续完成、停服后保留PowerShell及再次启动。回归发现排队扫描取消等待锁的问题，已统一由B持有扫描锁并在等待期间响应取消，相关交互重新通过。

真实Fabric 1.20.1服务端和Probe通过`test_probe_host.py`验证：手动托管启动、HTTPS查询、采样重连去重、修复前取消、循环BAT停服、备份修改、原窗口重启，以及B正常退出后服务端继续运行。Probe仍为0.1.0；四个目标重新构建，其他目标的服内功能与开销数据沿用[探针验证](probe.md)中的已标注版本结果。

两发行包解压后检查ZIP、文件清单、源码一致性与许可；B在全新环境由wheel安装，从site-packages运行HTTPS CLI、独立终端、诊断、循环停服和备份修复。精简插件与已安装B经真实runner验证23项，包括识别、下载、审核、再次批准、归档、检查点恢复、多人管理员、设置接口和终端交互。设置页经浏览器验证目录字段、共享额度保存和窄屏布局。

消融审查移除了B持有ConPTY和连续控制台落盘的旧实现，删除了工作进程中重复的扫描锁及未使用接口。复用原操作、后台任务和数据库，关键步骤经B保存确认后再执行。Ruff、格式和Git空白检查通过。

## 运行

测试环境为 Windows、Python 3.12、PowerShell 7.3+、PATH 中可用的 JDK 21。使用源码目录执行：

```powershell
.\.venv\Scripts\python.exe -m pip install -e '.[test]'
.\.venv\Scripts\python.exe scripts/setup_world_tools.py
.\.venv\Scripts\python.exe -m pytest -q
```

完整 Agent/群命令测试还需要安装 AstrBot v4.29.4 的依赖，并指定其源码路径。例如源码位于 `runtime/astrbot-4.29.4`：

```powershell
$env:ASTRBOT_ROOT = "$PWD/runtime/astrbot-test"
$env:PYTHONPATH = "$PWD/runtime/astrbot-4.29.4"
.\.venv\Scripts\python.exe -m pytest --cov=mcai --cov-branch --cov-report=term-missing --cov-report=html:runtime/coverage-html -q
```

未提供 AstrBot 时，需要真实 runner 的用例会显示 `skipped`。仅靠通过数量不足以判断是否跑过这部分，应同时查看跳过项和运行参数。HTML 覆盖率报告位于 `runtime/coverage-html/index.html`。

发行验证追加`--require-astrbot`，入口强制核对v4.29.4并在出现任何跳过时返回失败。整改后验证见[0.8.0整改记录](architecture-remediation-0.8.0.md)，上方数量保留为整改前基线。

## 场景清单

| 范围 | 主要覆盖内容 | 测试文件 |
|---|---|---|
| 自然语言识别与目标绑定 | 无实例创建、先追问再由反馈识别、未绑定拒绝实例工具、绑定冲突、取消原目标后台工作、方案失效、提交修复后固定目标、暂停重载、规范目录重复、目录变化拒绝新操作与旧编号查询 | `test_mcai_workflow.py` |
| API 托管搜索 | MC函数与搜索并存、流式/非流式、preview类型、显式不支持降级、503有限重试、摘要与来源保留、主配置不变、审核和验收总结不注入搜索 | `test_hosted_search.py` |
| 网页阅读 | HTML正文和链接、JSON分页、GB18030文本、持久引用、页内查找、跨任务引用拒绝、无正文/二进制/登录/404/超限错误 | `test_web_downloads.py` |
| MOD与下载 | 两站项目/说明/版本/依赖/变更说明、版本和加载器筛选、CurseForge API/CDN凭据、无关重定向不带凭据、分发受限、哈希失败、大小限制、临时错误重试、网络等待取消、HTTPS响应丢失及工具检查点去重 | `test_web_downloads.py`、`test_mcai_workflow.py` |
| 批准安装与经验 | 拒绝不安装、审核后暂存变化、旧文件备份/新增文件恢复、真实runner贯穿验收归档、归档失败重载重试、文档/索引中断去重、人工编辑保留、多案例并发、相关片段与不同目录隔离 | `test_mcai_workflow.py`、`test_web_downloads.py` |
| 日志和文件查询 | 字面量/正则、大小写、空查询、无匹配、普通/gzip、损坏 gzip、UTF-8/UTF-16/GB18030、中文路径、重叠上下文去重、调用栈归属、跨日日期、时区转换、追加/轮转、空文件和缺失文件 | `test_diagnostics.py`、`test_query_edges.py` |
| 大结果 | 行数和字符预算、全局事件序号不连续、重复读同一页、末页/空页、中文和 emoji 的长字段引用、按字符续读、首次大结果创建持久目录 | `test_diagnostics.py`、`test_query_edges.py`、`test_job_interactions.py` |
| 在线诊断 | 开服期间执行、工作子目录、中文和空格路径、stdout/stderr、跨输出分块的多字节字符、非零退出码、脚本错误后停止后续语句、无效超时、正常超时、父子进程取消 | `test_diagnostics.py`、`test_job_interactions.py` |
| 后台协作 | 多请求复用同一操作、并发重复取消、取消已完成/失败任务、同实例扫描串行和排队取消、其他实例并行、扫描期间读控制台、修复前结束所属诊断和扫描、保留其他任务工作 | `test_diagnostics.py`、`test_job_interactions.py` |
| 存档查询 | 旧 Level.Entities、新独立实体区域、UUID 字符串/四整数/双 Long、异常 UUID 后继续扫描、负坐标、世界过滤、独立实体覆盖旧残留数据、三维实体范围/水平区块相交、NBT 比较条件、按类型/区块计数和排行、未知模组字段 | `test_diagnostics.py`、`test_query_edges.py` |
| 存档修改和恢复 | 单独 NBT 的数组类型、子项分页、列表删除、gzip 保留、expected 不符、错误路径和 SNBT、四种区域压缩、MCR、真实存档、超大外部 MCC 保持与缩小、相邻 MCC、缺失 MCC、损坏邻居和错误坐标 | `test_workflows.py`、`test_diagnostics.py`、`test_query_edges.py`、`test_repair_edges.py` |
| 修复故障 | 同一目标多次修改只备份原始内容、重叠目录/文件备份、恢复目录时移除新文件、备份失败、替换失败、修复脚本异常/超时保留现场、跳过后续步骤、失败后保持停服、显式停服不被自动重启覆盖、跨实例备份拒绝 | `test_workflows.py`、`test_repair_edges.py` |
| 群任务状态 | 新反馈使旧方案失效、重复批准、执行修复期间保留反馈、后台等待时改变方向并取消工作、停止/验收后拒绝反馈、修复中止完成当前步骤、失败后补充消息继续、待取消状态重载续接、短群消息和完整本地记录 | `test_workflows.py`、`test_task_interactions.py` |
| 真实 Agent 工具链 | 二十三个工具经实际 runner 调用，含五个探针入口、暂停续接、后台查询/长字段/取消/修复记录、单次模型回复内多个工具、未知工具后继续、错参拒绝、步数上限、模型配置错误后恢复、中止、已提交工具检查点恢复 | `test_astrbot_integration.py`、`test_agent_edges.py`、`test_review_resume.py` |
| 服内探针桥接 | HTTPS断线去重、结果身份核对、会话变化、超时状态不确定、晚到结果、已有结果导入、范围schema、分页及长字段、取消确认、修复协作、多实例隔离 | `test_probe.py` |
| 工具参数 | 必填项、动作与字段不匹配、额外参数、错误类型、页大小/超时边界、负 NBT 索引、缺失的修复字段、空步骤与空脚本备份列表 | `test_agent_edges.py` |
| 网络和持久化 | 502/503/504 重试、保留请求和操作编号、非 JSON/损坏 JSON、永久错误快速失败、POST/GET 响应丢失时中止、修复/诊断不重复执行、插件重载、B 的任务重建中断状态、PID 身份不匹配时保留新进程 | `test_workflows.py`、`test_diagnostics.py`、`test_client_recovery.py`、`test_job_interactions.py` |
| HTTPS 直连 | 首次生成/重启复用证书、中文和空格路径、IP 地址直连、指纹格式和匹配、错误令牌、损坏或缺失的证书、本机 CLI、TLS 响应丢失/暂时断网、操作去重、后台任务续读与取消、插件重载 | `test_https.py` |
| 独立审核和续接 | 三个入口分别放行/拒绝、配置与协议错误、审核重试、材料缺失/超限、脚本变更、主上下文隔离、规则重载、检查点中断恢复、修复部分失败后再次审批 | `test_review_resume.py`、`test_model_recovery_summary.py` |
| 原生模型适配与 API 摘要 | 真实 Chat／Responses 适配器与模拟 HTTP API、独立思考程度、原始摘要事件、分片完成后发送、原始推理不转发、不支持摘要/流式时的兼容行为、原文分段、去重和停止后丢弃 | `test_provider_runtime.py`、`test_model_recovery_summary.py` |
| Windows 运维入口 | CLI 列表/状态/启停/重启/恢复、attach 输入和 EOF/detach、断开不停止服务端、多行控制台命令拒绝、原进程仍存活时拒绝重复接管、相对配置路径、每实例独立 Java | `test_console_cli.py`、`test_diagnostics.py` |
| 独立终端与共享额度 | tm/terminal、当前目录与-C、命名互斥、目录登记、真实补全/历史/中文/Ctrl+C、两个窗口与B强杀重连、会话和控制编号去重、9999行与字节上限、Job配置失败、共享额度耗尽和恢复、修复备份保留 | `test_terminal_isolation.py` |

## 单独复现

测试中的两端网络波动通过本地 HTTPS 服务实际返回临时错误或丢失响应，在真实 TLS 握手与证书指纹校验后调用操作接口。网页与模型模拟接口可使用本地 HTTP。并发扫描通过可控制的等待点稳定复现排队与取消时序。备份和替换失败通过注入文件操作错误复现。所有测试数据、脚本和进程都由用例在临时目录创建。

例如单独检查并发取消和扫描排队：

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_job_interactions.py -k 'double_cancel or scan_queue' -v
```

单独检查工具链和提交后恢复：

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_agent_edges.py tests/test_mcai_workflow.py -k 'all_tools or submitted_tool' -v
```

## 验证范围

Python 行/分支覆盖率衡量执行过的 Python 代码。Java 辅助程序通过真实 JVM 的读写、压缩、外部文件和恢复结果验证；没有把 Python 覆盖率数字用于表示 Java 的覆盖率。

真实QQ、模型服务、CurseForge凭据及生产整合包仍需部署联调。Python回归主要以BAT运行受控交互进程，另有上述真实Minecraft服验收。没有耗尽整机内存、模拟整机断电或真实磁盘损坏；共享额度用小Job限制验证，不能证明MC自身耗尽系统内存时Windows会如何处置其他进程。真实存档来源与许可见[第三方说明](third-party.md)。
