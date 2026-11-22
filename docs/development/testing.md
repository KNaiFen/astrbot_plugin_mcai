# 测试与复验

[开发索引](README.md)

测试同时检查工具返回值、磁盘文件、备份内容、进程状态和持久化记录。测试服务器通过真实 BAT/ConPTY 启动可交互进程；存档测试使用固定来源的真实片段和生成样本；Agent 集成运行 AstrBot v4.29.4 的真实 runner，模型回复由测试控制。A/B 接口测试统一经 HTTPS。

当前版本的发行检查与真实场景记录在完整源码的 `docs/development/records/`。故障留证和卡顿复验使用真实模型、本地 OneBot、Fabric 与 ATM10 隔离服；区块录制的进世界证据同时核对协议客户端位置和服务端加入日志。安装复验和受控回归分别记账，不代表真实 QQ 或所有整合包均已联调。

## 运行

测试环境为 Windows、Python 3.12、PowerShell 7.3+、PATH 中可用的 JDK 21。首次准备环境或依赖变化时，在源码目录执行：

```powershell
.\.venv\Scripts\python.exe -m pip install -e '.[test]'
.\.venv\Scripts\python.exe scripts/setup_world_tools.py
```

完整 Agent/群命令测试还需要安装 AstrBot v4.29.4 的依赖，并指定其源码路径。例如源码位于 `runtime/astrbot-4.29.4`：

```powershell
$env:ASTRBOT_ROOT = "$PWD/runtime/astrbot-test"
$env:PYTHONPATH = "$PWD/runtime/astrbot-4.29.4"
.\.venv\Scripts\python.exe -m pytest -q --require-astrbot --durations=15 --junitxml=runtime/pytest.xml
```

上述默认收集核心行为回归，保留真实runner、HTTPS、托管窗口、审核批准、备份修改、失败恢复及原编号去重。日常修改按受影响行为选择文件或节点；同一轮涉及多个范围时，合并成一条去重后的pytest命令。核心回归只跑一次，已包含的节点不再作为重复关卡。文档整理检查相关链接、示例与打包。

详细兼容矩阵按变更范围显式追加，不再让每次任务重复启动全部环境：

| 触发变更 | 追加文件 | 内容 |
|---|---|---|
| 存档读写、NBT／区域／方块、Java、备份恢复或共用操作上下文 | `tests/world_compatibility.py` | 数据类型、版本打包、MCR／MCC、第三方编解码器及恢复边界 |
| 模型适配、搜索、进度流、能力检测、OpenAI SDK或相关依赖 | `tests/api_compatibility.py` | Chat／Responses详细协议、流式错误、SDK重试及搜索能力矩阵 |

例如修改两类共用代码时，核心回归按上方命令执行一次，再合并运行两个专项。不要同时把父目录和专项文件传给pytest：当前版本会将目录中未匹配默认文件名的专项去重掉。

```powershell
.\.venv\Scripts\python.exe -m pytest tests/world_compatibility.py tests/api_compatibility.py -q --require-astrbot
```

两个专项文件刻意不使用`test_`前缀，默认不收集；它们保留有用的格式和适配器差异，不按普通功能改动反复执行。新测试先确认现有流程是否已覆盖；能在已有完整场景中增加必要断言，就不再复制一套启动／关闭流程。

`--require-astrbot`强制核对v4.29.4，并在出现任何跳过时返回失败。未提供AstrBot时可以执行不依赖runner的专项；含跳过的结果不能作为完整回归或发行通过的证据。需要分析覆盖率时，再给上述命令追加`--cov=mcai --cov-branch --cov-report=html:runtime/coverage-html`；覆盖率采集不作为每轮默认步骤。

构建后用解压A插件和独立安装的B执行代表性安装验证，重点核对导入路径、原生runner、HTTPS、CLI、备份修改、下载归档及多轮方案。可选择以下节点（多轮用例包含Chat／Responses两种适配器，共4项）：

```text
tests/test_mcai_workflow.py::test_natural_target_web_mod_review_install_verify_and_archive_real_runner
tests/test_https.py::TestHttpsTransport::test_local_cli_uses_relative_data_dir_for_all_operations_and_attach
tests/test_plan_continuation.py::test_one_approval_runs_three_observed_batches_with_actual_adapters
```

这些节点须在准备好的解压验证目录运行，测试解释器使用现有依赖，PYTHONPATH指向独立B安装目录、AstrBot和复制的测试目录；核对A模块来自解压插件、B及worker来自独立安装目录。不能从源码根运行后当作安装验证。Probe／Java产物未变化时核对受测产物的内部文件内容；涉及相关实现或依赖变更时，再执行对应的真实MC组合。保存被测版本、实际命令、结果和限制，历史数字以各批记录为准。

真实方块修复验证另行运行，使用本地原版MC **1.21.1 bundler JAR**和JDK21。脚本创建独立的`runtime/maintenance-real/<随机编号>/`，仅监听127.0.0.1，不使用生产世界；通过实际HTTPS／ConPTY执行停服、备份、修改、重启和MC命令确认，保留日志与`result.json`。它不随普通pytest自动启动：

```powershell
.\.venv\Scripts\python.exe scripts/test_maintenance_server.py --server-jar 'D:/MC-Test/server-1.21.1.jar' --java 'C:/Program Files/Java/jdk-21/bin/java.exe'
```

若已按[探针验证](probe.md)准备隔离Fabric 1.21.1安装目录，可省略参数，使用其中的原版bundler。

## 场景清单

| 范围 | 主要覆盖内容 | 测试文件 |
|---|---|---|
| 自然语言识别与目标绑定 | 无实例创建、先追问再由反馈识别、未绑定拒绝实例工具、绑定冲突、取消原目标后台工作、方案失效、提交修复后固定目标、暂停重载、规范目录重复、目录变化拒绝新操作与旧编号查询 | `test_mcai_workflow.py` |
| API 托管搜索 | 核心检查搜索续接与持久会话；专项检查流式／非流式、preview、降级、有限重试、来源及上下文隔离 | `test_settings_search.py`、`api_compatibility.py` |
| 网页阅读 | HTML正文和链接、JSON分页、GB18030文本、持久引用、页内查找、跨任务引用拒绝、无正文/二进制/登录/404/超限错误 | `test_web_downloads.py` |
| MOD与下载 | 两站项目/说明/版本/依赖/变更说明、版本和加载器筛选、CurseForge API/CDN凭据、无关重定向不带凭据、分发受限、哈希失败、大小限制、临时错误重试、网络等待取消、HTTPS响应丢失及工具检查点去重 | `test_web_downloads.py`、`test_mcai_workflow.py` |
| MOD 源码修复、试服与发布 | A 工作区、B 测试端口和复制预检、试玩反馈、同制品发布、验收清理及恢复 | `test_mod_workspace.py`、`test_plan_continuation.py`、`test_client_recovery.py`、`scripts/e2e_mod_repair.py` |
| 批准安装与经验 | 拒绝不安装、审核后暂存变化、旧文件备份/新增文件恢复、真实runner贯穿验收归档、归档失败重载重试、文档/索引中断去重、人工编辑保留、多案例并发、相关片段与不同目录隔离 | `test_mcai_workflow.py`、`test_web_downloads.py` |
| 日志和文件查询 | 字面量/正则、大小写、空查询、无匹配、普通/gzip、损坏 gzip、UTF-8/UTF-16/GB18030、中文路径、重叠上下文去重、调用栈归属、跨日日期、时区转换、追加/轮转、空文件和缺失文件 | `test_diagnostics.py`、`test_query_edges.py` |
| 维护工具与存档修复 | 哈希补丁／编码保留、后台等待／检索、JVM身份与卡死恢复、就绪观察、组件清单差异、身份批量NBT、坏邻居点恢复、方块打包／高度图与原生批准流程 | `test_host_maintenance.py`、`test_host_recovery.py`、`test_host_verification.py`、`test_host_inventory.py`、`test_host_nbt_batch.py`、`test_host_region_recovery.py`、`test_host_blocks.py` |
| 大结果 | 行数和字符预算、全局事件序号不连续、重复读同一页、末页/空页、中文和 emoji 的长字段引用、按字符续读、首次大结果创建持久目录 | `test_audit_data.py`、`test_job_interactions.py`、`test_tool_contracts.py` |
| 在线诊断 | 开服期间执行、工作子目录、中文和空格路径、stdout/stderr、跨输出分块的多字节字符、非零退出码、脚本错误后停止后续语句、无效超时、正常超时、父子进程取消 | `test_diagnostics.py`、`test_job_interactions.py` |
| 后台协作 | 多请求复用同一操作、并发重复取消、取消已完成/失败任务、同实例扫描串行和排队取消、其他实例并行、扫描期间读控制台、修复前结束所属诊断和扫描、保留其他任务工作 | `test_diagnostics.py`、`test_job_interactions.py` |
| 存档查询 | 核心检查真实片段、扫描及原生工具流程；专项检查旧／新实体区域、UUID表示、负坐标、过滤范围、条件和排名 | `test_diagnostics.py`、`test_agent_edges.py`、`world_compatibility.py` |
| 存档修改和恢复 | 核心保留原生runner批准后的批量NBT、方块与区域恢复；专项保留数据类型、编解码、MCR／MCC及损坏邻居矩阵 | `test_host_nbt_batch.py`、`test_host_blocks.py`、`test_host_region_recovery.py`、`world_compatibility.py` |
| 修复故障 | 同一目标多次修改只备份原始内容、重叠目录/文件备份、恢复目录时移除新文件、备份失败、替换失败、修复脚本异常/超时保留现场、跳过后续步骤、失败后保持停服、显式停服不被自动重启覆盖、跨实例备份拒绝 | `test_workflows.py`、`test_repair_edges.py` |
| 群任务状态 | 新反馈与来源、修复期间反馈、停止／暂停和重载、完整分段发送及失败续发；设置与实例占用边界保留独立故障场景 | `test_task_interactions.py`、`test_say_mode.py`、`test_audit_agent.py`、`test_review_resume.py` |
| 真实 Agent 工具链 | 基础与按需加载工具的契约及原生 runner 流程，含Chat／Responses实际请求、错参后正确调用、五个探针入口、暂停续接、后台等待／分页／长字段／取消、操作记录与上下文历史、单回复多工具、未知工具后继续、步数上限、配置错误后恢复、中止和原编号检查点恢复 | `test_tool_contracts.py`、`test_agent_edges.py`、`test_review_resume.py`、`test_plan_continuation.py` |
| 服内探针桥接 | HTTPS断线去重、结果身份核对、会话变化、超时状态不确定、晚到结果、已有结果导入、范围schema、分页及长字段、取消确认、修复协作、多实例隔离 | `test_probe.py` |
| 工具参数 | 实际 Chat／Responses 请求中的工具 schema 及非法参数，一次验证完整定义，再验证错参纠正后的真实读取 | `test_tool_contracts.py` |
| 网络和持久化 | 502/503/504 重试、保留请求和操作编号、非 JSON/损坏 JSON、永久错误快速失败、POST/GET 响应丢失时中止、修复/诊断不重复执行、插件重载、B 的任务重建中断状态、PID 身份不匹配时保留新进程 | `test_workflows.py`、`test_diagnostics.py`、`test_client_recovery.py`、`test_job_interactions.py` |
| HTTPS 直连 | 首次生成/重启复用证书、中文和空格路径、IP 地址直连、指纹格式和匹配、错误令牌、损坏或缺失的证书、本机 CLI、TLS 响应丢失/暂时断网、操作去重、后台任务续读与取消、插件重载 | `test_https.py` |
| 独立审核和续接 | 三个入口分别放行/拒绝、配置与协议错误、审核重试、材料缺失/超限、脚本变更、主上下文隔离、规则重载、检查点中断恢复、修复部分失败后再次审批 | `test_review_resume.py`、`test_model_recovery_summary.py` |
| 原生模型适配与 API 摘要 | 核心保留实际适配器工具调用、多轮执行、重试和上下文压缩；专项保留思考程度、流式／非流式、进度、摘要与失败矩阵 | `test_tool_contracts.py`、`test_plan_continuation.py`、`test_model_recovery_summary.py`、`api_compatibility.py` |
| 完整交互与诊断导出 | 拒绝命令原文、任务私有API请求／响应／摘要、独立审核、批量工具结果、消息发送成功／失败、关闭群摘要和ZIP回放 | `test_tracing.py`、`test_settings_search.py` |
| Web 管理控制台 | AstrBot 请求上下文和真实 A→B HTTPS：定时计划校验和替换、配置保存和环境回显、正常启停与占用冲突、Probe 局部读取、任务短码和归档、故障与 gzip 附件、经验索引、备份清单及后台取消 | `test_web_management.py`、`test_settings_search.py` |
| Windows 运维入口 | CLI列表／状态／启停／恢复与相对目录、attach半行／长行／新会话、输入拒绝、每实例Java及托管窗口交互 | `test_https.py`、`test_audit_host.py`、`test_console_cli.py`、`test_terminal_isolation.py` |
| 独立终端与共享额度 | tm/terminal、当前目录与-C、命名互斥、目录登记、真实补全/历史/中文/Ctrl+C、两个窗口与B强杀重连、会话和控制编号去重、9999行与字节上限、Job配置失败、共享额度耗尽和恢复、修复备份保留 | `test_terminal_isolation.py` |

## 单独复现

测试中的两端网络波动通过本地 HTTPS 服务实际返回临时错误或丢失响应，在真实 TLS 握手与证书指纹校验后调用操作接口。网页与模型模拟接口可使用本地 HTTP。并发扫描通过可控制的等待点稳定复现排队与取消时序。备份和替换失败通过注入文件操作错误复现。所有测试数据、脚本和进程都由用例在临时目录创建。

例如单独检查并发取消和扫描排队：

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_job_interactions.py -k 'double_cancel or scan_queue' -v
```

单独检查工具链和提交后恢复：

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_agent_edges.py::test_native_queries_diagnostic_cancel_repair_and_archive tests/test_mcai_workflow.py::test_submitted_tool_keeps_original_payload_when_resuming -v
```

## 验证范围

2026-11-21 Web 控制台验证：以 AstrBot v4.29.4 的实际桥接脚本置于受限 iframe，父页模拟管理 API。Playwright 核对计划创建、编辑、暂停、恢复、删除、局部 Probe 刷新、任务短码弹窗、群输入及亮暗切换；1280px 桌面和 390px 下九个面板没有横向溢出。独立临时源码目录执行 `python scripts/build_release.py --package-only`，插件、B 和源码包的 ZIP CRC 通过，包含对应页面资源与 B 管理模块；使用了已有 Java／Probe 产物。A 机通过 `Downloads.request` 对真实 Modrinth 搜索 API 发出只读请求，收到 1 条结果。未使用真实 QQ、生产服务器或 CurseForge 私有凭据。

同轮使用 Windows、Python 3.12、`PYTHONPATH=runtime/astrbot-4.29.4` 和隔离 `ASTRBOT_ROOT=runtime/astrbot-test`。`python -m pytest -q --require-astrbot --durations=15 --junitxml=runtime/mcai-web-pytest-final.xml` 结算为 514 通过、零跳过、98 条依赖弃用提示（22 分 38 秒）；最后补充的原编号防迟到断言和索引目录校验随 Web 相关节点复测，8 通过。`ruff check main.py mcai tests scripts`、`ruff format --check main.py mcai tests scripts`、`git diff --check` 和三个 JavaScript 模块的 `node --check` 均通过。

Python 行/分支覆盖率衡量执行过的 Python 代码。Java 辅助程序通过真实 JVM 的读写、压缩、外部文件和恢复结果验证；没有把 Python 覆盖率数字用于表示 Java 的覆盖率。

内存诊断复验见完整源码的 `docs/development/records/probe-memory-2026-11-22.md`。`tests/test_memory_diagnostics.py` 启动隔离 JVM 生成真实 JFR 和 HPROF；验证停顿重合、分配首样本、支配路径、小堆降级及 B 端路径限制。

真实模型与隔离服务端的专项记录仅涵盖所列模型和服务端组合。真实 QQ、用户的模型与 CurseForge 凭据以及生产整合包仍需在各自部署中验证。Python回归主要以BAT运行受控交互进程，另有上述真实Minecraft服验收。没有耗尽整机内存、模拟整机断电或真实磁盘损坏；共享额度用小Job限制验证，不能证明MC自身耗尽系统内存时Windows会如何处置其他进程。真实存档来源与许可见[第三方说明](third-party.md)。
