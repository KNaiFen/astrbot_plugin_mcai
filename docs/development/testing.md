# 测试与复验

[开发索引](README.md)

测试同时检查工具返回值、磁盘文件、备份内容、进程状态和持久化记录。普通 B 测试使用内存控制台和进程内执行；真实主机用例通过 BAT／ConPTY 启动可交互进程。存档测试使用固定来源的真实片段和生成样本；Agent 集成运行 AstrBot v4.29.4 的真实 runner，模型回复由测试控制。A/B 接口测试统一经 HTTPS。

当前版本的发行检查与真实场景记录在完整源码的 `docs/development/records/`。故障留证和卡顿复验使用真实模型、本地 OneBot、Fabric 与 ATM10 隔离服；区块录制的进世界证据同时核对协议客户端位置和服务端加入日志。安装复验和受控回归分别记账，不代表真实 QQ 或所有整合包均已联调。

## 运行

测试环境为 Windows、Python 3.12、PowerShell 7.3+、PATH 中可用的 JDK 21，静态检查还需 Node.js。集成基线固定为 AstrBot v4.29.4；不拿上游当前分支替代，其他版本的兼容验证单独记录。首次准备环境或依赖变化时，在源码目录执行：

```powershell
.\.venv\Scripts\python.exe -m pip install -e '.[test]'
.\.venv\Scripts\python.exe scripts/setup_world_tools.py
```

统一入口是 `scripts/verify.py`。它可自动识别仓库内的 `runtime/astrbot-4.29.4` 和 `runtime/astrbot-test`；也可传 `--astrbot-source` 和 `--astrbot-root` 指定目录：

```powershell
.\.venv\Scripts\python.exe scripts/verify.py --mode static
.\.venv\Scripts\python.exe scripts/verify.py --mode quick
.\.venv\Scripts\python.exe scripts/verify.py --mode full
.\.venv\Scripts\python.exe scripts/verify.py --mode compat
.\.venv\Scripts\python.exe scripts/verify.py --mode package
.\.venv\Scripts\python.exe scripts/verify.py --mode release
```

`static` 检查 Ruff、Git 空白、Node 语法、配置和版本、Markdown 相对链接与 Probe CoreChecks；`quick` 在静态检查后运行冒烟套件，排除 `real_host`；`full` 在静态检查后收集全部核心用例。`compat` 只核对配置与版本并运行两个兼容套件。`package` 运行静态检查并用已有 Java／Probe 产物打包，校验 ZIP、解包文档链接及 A/B 隔离导入安装与 CLI 帮助；`release` 在此基础上串行执行核心与兼容全量回归。

Windows CI（`.github/workflows/ci.yml`）将静态检查和核心／兼容矩阵分开。静态作业用 Node 20、JDK 21 和固定 Gson 运行 CoreChecks；测试作业安装锁定依赖、校验固定 AstrBot 源码并准备 WorldTools，运行 `full`／`compat` 时传 `--skip-java --skip-node`，由独立静态作业覆盖这两项。锁定依赖作业的 pip 缓存路径为 `~\AppData\Local\pip\Cache`。

若手动调用 `pytest` 跑全量核心回归：

```powershell
$env:ASTRBOT_ROOT = "$PWD/runtime/astrbot-test"
$env:PYTHONPATH = "$PWD/runtime/astrbot-4.29.4"
.\.venv\Scripts\python.exe -m pytest -q --require-astrbot --durations=15 --junitxml=runtime/pytest.xml
```

上述默认收集核心行为回归，覆盖真实 runner、HTTPS、托管窗口、审核批准、备份修改、失败恢复及原编号去重。日常修改按受影响行为选择文件或节点；同一轮涉及多个范围时合并成一条去重后的 pytest 命令，核心回归已覆盖的节点不再作为额外关卡。文档整理检查相关链接、示例、忽略规则和受影响的发行包。

详细兼容矩阵按变更范围显式追加，不再让每次任务重复启动全部环境：

| 触发变更 | 追加文件 | 内容 |
|---|---|---|
| 存档读写、NBT／区域／方块、Java、备份恢复或共用操作上下文 | `tests/world_compatibility.py` | 数据类型、版本打包、MCR／MCC、第三方编解码器及恢复边界 |
| 模型适配、搜索、进度流、能力检测、OpenAI SDK或相关依赖 | `tests/api_compatibility.py` | Chat／Responses详细协议、流式错误、SDK重试及搜索能力矩阵 |

例如修改两类共用代码时，核心回归按上方命令执行一次，再合并运行两个专项。不要同时把父目录和专项文件传给pytest：当前版本会将目录中未匹配默认文件名的专项去重掉。

```powershell
.\.venv\Scripts\python.exe -m pytest tests/world_compatibility.py tests/api_compatibility.py -q --require-astrbot
```

两个专项文件刻意不使用 `test_` 前缀，默认不收集；它们保留有用的格式和适配器差异，按受影响范围运行。

`--require-astrbot`强制核对v4.29.4，并在出现任何跳过时返回失败。未提供AstrBot时可以执行不依赖runner的专项；含跳过的结果不能作为完整回归或发行通过的证据。需要分析覆盖率时，再给上述命令追加`--cov=mcai --cov-branch --cov-report=html:runtime/coverage-html`；覆盖率采集不作为每轮默认步骤。

`verify.py --mode package` 与 `--mode release` 已自带解压链接校验、A 导入、B 离线构建安装 wheel 与 `mcai --help` 冒烟。仅当改动涉及打包结构、导入边界或安装运行时，再用解压 A 插件和独立安装的 B 执行以下代表性集成节点（多轮用例包含 Chat／Responses 两种适配器，共 4 项）：

```text
tests/test_mcai_workflow.py::test_natural_target_web_mod_review_install_verify_and_archive_real_runner
tests/test_https.py::TestHttpsTransport::test_local_cli_uses_relative_data_dir_for_all_operations_and_attach
tests/test_plan_continuation.py::test_one_approval_runs_three_observed_batches_with_actual_adapters
```

这些节点须在准备好的解压验证目录运行，测试解释器使用现有依赖，PYTHONPATH 指向独立 B 安装目录、AstrBot 和复制的测试目录；核对 A 模块来自解压插件、B 及 worker 来自独立安装目录。不能从源码根运行后当作安装验证。Probe／Java 产物未变化时由脚本自动核对关键入口；涉及相关实现或依赖变更时，再执行对应的真实 MC 组合。保存被测版本、实际命令、结果和限制，常规发版不再逐版补写校验和转录表。

真实方块修复验证另行运行，使用本地原版MC **1.21.1 bundler JAR**和JDK21。脚本创建独立的`runtime/maintenance-real/<随机编号>/`，仅监听127.0.0.1，不使用生产世界；通过实际HTTPS／ConPTY执行停服、备份、修改、重启和MC命令确认，保留日志与`result.json`。它不随普通pytest自动启动：

```powershell
.\.venv\Scripts\python.exe scripts/test_maintenance_server.py --server-jar 'D:/MC-Test/server-1.21.1.jar' --java 'C:/Program Files/Java/jdk-21/bin/java.exe'
```

若已按[探针验证](probe.md)准备隔离Fabric 1.21.1安装目录，可省略参数，使用其中的原版bundler。

## 编写与维护测试

- **先找已有场景。** 优先补现有测试的必要断言，按故障留证、主机维护、存档、查询 CLI、修复或终端隔离等职责合并小用例。不要复制启动和清理流程，也不为一两个用例另建零散文件。移动测试或共用夹具时，同步检查兼容矩阵的导入，尤其是 `tests/world_compatibility.py`，并更新下方场景清单。
- **复用夹具。** `tests/conftest.py` 的 `host` 默认使用 `SimConsole`／`SimTerminal` 和进程内 `local_execution`。只有确实依赖 ConPTY、窗口标题、共享 Job Object 内存额度、进程树隔离或 BAT 自动重启的测试才标为 `@pytest.mark.real_host`。保留 `cache_powershell_version` 对默认 `pwsh.exe` 的版本探测缓存（其他路径仍执行真实校验），以及 `fast_test_polling` 的模块级轮询替换；`plugin_session` 复用 `_load_plugin_module()` 的模块缓存和通过 `host` 使用的会话级 `test_tls_bundle`。
- **控制参数化规模。** 使用 `host` 或 `plugin_session` 时，各参数组合都会重建对应的函数级夹具。纯数据校验在同一测试内循环；多维协议、流式错误或分隔符取代表组合覆盖边界，避免笛卡尔积。需要穷举的存档编解码、模型接口兼容矩阵放入 `world_compatibility.py` 或 `api_compatibility.py`。
- **分清工具结算和重试。** 假 `Provider` 的回调先显式判断 `provider.last.get("next_call")`，工具同步返回或后台工作已结算时可能没有该字段。直接索引的 `KeyError` 可能被模型失败路径捕获并消耗下一条模拟动作；`mcai/agent_runtime.py` 的有限重试间隔为 `RETRY_DELAYS = (2, 5)`，持续 API 失败用 `API_RETRY_DELAYS`。失败重试测试使用 `fast_model_retries`；专测退避中取消时可局部设置 `API_RETRY_DELAYS`，用事件提前中止。
- **保留后台首等窗口。** `mcai/jobs.py` 的 `Jobs.start` 等待至多 2 秒后返回当前状态，不终止后台工作。不要统一压短，避免将正常的 PowerShell 启动或短结果误测成仍在执行。专门验证 `running` 后再 `mc_job_wait` 的脚本需超过 2 秒，例如 2.4 秒；测取消时及时提交取消，不等自然超时。
- **及时确认取消并控制载荷。** Probe 取消测试的假终端监听 `cancel/<key>.json`，以匹配原编号和会话的结果回写 `status="cancelled"`；除专测未确认外，不空等协议的 1 秒或部分扫描的 3 秒，监听任务在 `finally` 取消并回收。文件分块、gzip 和上下文超限取刚超过各自阈值的输入；例如覆盖 256 KiB 文件分块时用约 270 KB 的有效载荷。
- **同步入口。** 不新增一次性的 `scripts/test_*.py` 或基准脚本，通用验证维护在 `scripts/verify.py` 与 CI。增删或改名测试文件且需验证发行包时，先按[构建与发行](README.md#构建与发行)更新 Git 索引，再跑静态检查和受影响套件，或用 `--mode release` 完成全检；完整回归须零跳过。

开始前检查已有临时案例、目录和产物，优先复用有用资料。每个案例结束后立即评估并清理本次生成的无用环境、输入副本、日志、缓存和构建产物，结束任务前再核对磁盘占用。清理前把条件、命令、结果和关键数值写进既有验证记录，默认只保留记录和最小必要证据。确需暂留的大体积资料注明位置、用途和清理时机，用完即清理。保留项目内的回归测试及用户的数据、配置和存档。

## 场景清单

| 范围 | 主要覆盖内容 | 测试文件 |
|---|---|---|
| 自然语言识别与目标绑定 | 无实例创建、先追问再由反馈识别、未绑定拒绝实例工具、绑定冲突、取消原目标后台工作、方案失效、提交修复后固定目标、暂停重载、规范目录重复、目录变化拒绝新操作与旧编号查询 | `test_mcai_workflow.py` |
| API 托管搜索 | 核心检查搜索续接与持久会话；专项检查流式／非流式、preview、降级、有限重试、来源及上下文隔离 | `test_settings_search.py`、`api_compatibility.py` |
| 网页阅读 | HTML正文和链接、JSON分页、GB18030文本、持久引用、页内查找、跨任务引用拒绝、无正文/二进制/登录/404/超限错误 | `test_web_downloads.py` |
| MOD与下载 | 两站项目/说明/版本/依赖/变更说明、版本和加载器筛选、CurseForge API/CDN凭据、无关重定向不带凭据、分发受限、哈希失败、大小限制、临时错误重试、网络等待取消、HTTPS响应丢失及工具检查点去重 | `test_web_downloads.py`、`test_mcai_workflow.py` |
| MOD 源码修复、试服与发布 | A 工作区、B 测试端口和复制预检、试玩反馈、同制品发布、验收清理及恢复 | `test_mod_workspace.py`、`test_plan_continuation.py`、`test_client_recovery.py` |
| 批准安装与经验 | 拒绝不安装、审核后暂存变化、旧文件备份/新增文件恢复、真实runner贯穿验收归档、归档失败重载重试、文档/索引中断去重、人工编辑保留、多案例并发、相关片段与不同目录隔离 | `test_mcai_workflow.py`、`test_web_downloads.py` |
| 日志和文件查询 | 字面量/正则、大小写、空查询、无匹配、普通/gzip、损坏 gzip、UTF-8/UTF-16/GB18030、中文路径、重叠上下文去重、调用栈归属、跨日日期、时区转换、追加/轮转、空文件和缺失文件 | `test_diagnostics.py`、`test_query_cli.py` |
| 维护工具与存档修复 | 哈希补丁／编码保留、后台等待／检索、JVM身份与卡死恢复、就绪观察、组件清单差异、身份批量NBT、坏邻居点恢复、维度坐标解析与`block_batch`预览／执行、冻结清单`region_prune/nbt_prune`审核批准、停服过滤上限与方块实体移除 | `test_host_maintenance.py`、`test_host_world.py` |
| 大结果 | 行数和字符预算、全局事件序号不连续、重复读同一页、末页/空页、中文和 emoji 的长字段引用、按字符续读、首次大结果创建持久目录 | `test_diagnostics.py`、`test_job_interactions.py`、`test_tool_contracts.py` |
| 在线诊断 | 开服期间执行、工作子目录、中文和空格路径、stdout/stderr、跨输出分块的多字节字符、非零退出码、脚本错误后停止后续语句、无效超时、正常超时、父子进程取消 | `test_diagnostics.py`、`test_job_interactions.py` |
| 后台协作 | 多请求复用同一操作、并发重复取消、取消已完成/失败任务、同实例扫描串行和排队取消、其他实例并行、扫描期间读控制台、修复前结束所属诊断和扫描、保留其他任务工作 | `test_diagnostics.py`、`test_job_interactions.py` |
| 存档查询 | 核心检查真实片段、扫描及原生工具流程；专项检查旧／新实体区域、UUID表示、维度与负坐标解析、歧义拒绝、`nbt_scan`通配条件／递归容器搜物、方块扫描与轻量计数、冻结清单指纹 | `test_diagnostics.py`、`test_agent_edges.py`、`world_compatibility.py` |
| 存档修改和恢复 | 核心保留原生runner批准后的批量NBT、方块与区域恢复；专项保留冻结`region_prune/nbt_prune`、字段级清理与哈希旧值、`block_batch`及标准`Add`扩展ID写入／FML映射／高度图、未知扩展数组拒绝、数据类型、编解码、MCR／MCC及损坏邻居矩阵 | `test_host_world.py`、`world_compatibility.py` |
| 修复故障 | 同一目标多次修改只备份原始内容、重叠目录/文件备份、恢复目录时移除新文件、备份失败、替换失败、修复脚本异常/超时保留现场、跳过后续步骤、失败后保持停服、显式停服不被自动重启覆盖、跨实例备份拒绝、有效步骤绑定与纯停服无依赖 | `test_repair_edges.py` |
| 群任务状态 | 新反馈与来源、修复期间反馈、停止／暂停和重载、完整分段发送及失败续发；设置与实例占用边界保留独立故障场景 | `test_task_interactions.py`、`test_audit_agent.py`、`test_review_contract.py` |
| 真实 Agent 工具链 | 基础与按需加载工具的契约及原生 runner 流程，含Chat／Responses实际请求、错参后正确调用、五个探针入口、暂停续接、后台等待／分页／长字段／取消、操作记录与上下文历史、单回复多工具、未知工具后继续、步数上限、配置错误后恢复、中止和原编号检查点恢复 | `test_tool_contracts.py`、`test_agent_edges.py`、`test_review_contract.py`、`test_plan_continuation.py` |
| 服内探针桥接 | HTTPS断线去重、结果身份核对、会话变化、超时状态不确定、晚到结果、已有结果导入、范围schema、分页及长字段、取消确认、修复协作、多实例隔离 | `test_probe.py` |
| 工具参数 | 实际 Chat／Responses 请求中的工具 schema 及非法参数，一次验证完整定义，再验证错参纠正后的真实读取 | `test_tool_contracts.py` |
| 网络和持久化 | 502/503/504 重试、保留请求和操作编号、非 JSON/损坏 JSON、永久错误快速失败、POST/GET 响应丢失时中止、修复/诊断不重复执行、插件重载、B 的任务重建中断状态、PID 身份不匹配时保留新进程 | `test_repair_edges.py`、`test_diagnostics.py`、`test_client_recovery.py`、`test_job_interactions.py` |
| HTTPS 直连 | 首次生成/重启复用证书、中文和空格路径、IP 地址直连、指纹格式和匹配、错误令牌、损坏或缺失的证书、本机 CLI、TLS 响应丢失/暂时断网、操作去重、后台任务续读与取消、插件重载 | `test_https.py` |
| 独立审核和续接 | 三个入口分别放行/拒绝、配置与协议错误、审核重试、材料缺失/超限、脚本变更、主上下文隔离、规则重载、检查点中断恢复、修复部分失败后再次审批 | `test_review_contract.py`、`test_model_recovery_summary.py` |
| 原生模型适配与 API 摘要 | 核心保留实际适配器工具调用、多轮执行、重试和上下文压缩；专项保留思考程度、流式／非流式、进度、摘要与失败矩阵 | `test_tool_contracts.py`、`test_plan_continuation.py`、`test_model_recovery_summary.py`、`api_compatibility.py` |
| 完整交互与诊断导出 | 拒绝命令原文、任务私有API请求／响应／摘要、独立审核、批量工具结果、消息发送成功／失败、关闭群摘要和ZIP回放 | `test_tracing.py`、`test_settings_search.py` |
| Web 管理控制台 | AstrBot 请求上下文和真实 A→B HTTPS：计划、配置与环境、备用模型配置校验与独立能力测试、启停以及试服关窗、Probe 局部查询、任务批准及归档、故障筛选和附件、经验增删改查与目录索引、上游价格与用量、备份及后台取消 | `test_web_management.py`、`test_settings_search.py` |
| 配置生命周期与主机退出 | 实例热重载、待生效字段、拒绝活动改名、配置版本、留证容量、BAT 重启和停服监听、B 退出时已接受操作结算、断线保留窗口配置 | `test_configuration_lifecycle.py`、`test_terminal_isolation.py` |
| 留证、主动告警与附件 | 故障控制台、旧事件导入、附件身份与 gzip 分块、容量淘汰、B 失联、通知游标、窗口／磁盘／性能告警、另卷备份和过期活跃状态清理 | `test_incidents.py`、`test_alerts.py` |
| 定时维护与数据管理 | 计划审核、时段恢复、在线备份恢复保存、保留份数、任务清理保护、数据库压缩和按月日志清理 | `test_schedules.py`、`test_data_maintenance.py` |
| 只读群命令与群附件 | 实例和 Probe 状态、问答权限及独立后台任务、`/mcaiask` 主备切换与冷却共享、`nbt_scan`后台跟踪与结束取消、附件来源和大小限制、引用身份、图片识别主备切换与仅传文字 | `test_readonly_commands.py`、`test_group_attachments.py` |
| 模型恢复、用量及结果完整性 | 启动恢复、长输入预算与归档主备切换重试、持续重试与主备自动切换／冷却探测／双挂告警／超时暂停续接／异构协议兼容、审核主备切换与协议错隔离、主请求和审核拒绝未完成输出、任务与每日用量、费用估算和上限续期 | `test_continuous_api_retry.py`、`test_model_request_integrity.py`、`test_model_usage.py`、`test_model_recovery_summary.py` |
| 审核材料与历史证据 | 原始记录续读、容量收缩、反馈使旧提案失效、脚本依赖与恢复材料、范围去重及归档原文回填 | `test_review_contract.py`、`test_review_material_contract.py` |
| 复合排障与回放 | 交错函数项、崩溃日志、错抄证据和审核降级贯穿批准与流式归档；输出截断后从 SQLite 修复工具配对；远程检查点预算与跨模型去密文；续批的审核流超时、并行工具和缓存用量；只读问答从限流与进度输出续接；WAL 写入期间导出诊断 | `test_mcai_workflow.py`、`test_model_request_integrity.py`、`test_model_recovery_summary.py`、`api_compatibility.py`、`test_plan_continuation.py`、`test_readonly_commands.py`、`test_tracing.py` |
| Probe 就绪、spark 与 JVM 内存 | 当前 JVM 的新鲜响应和会话超时、spark 报告身份及采样权重、真实 JFR 和 HPROF、内存预算降级、产物路径约束 | `test_probe.py`、`test_memory_diagnostics.py` |
| Windows 运维入口 | CLI列表／状态／启停／恢复与相对目录、attach半行／长行／新会话、输入拒绝、每实例Java及托管窗口交互 | `test_https.py`、`test_configuration_lifecycle.py`、`test_terminal_isolation.py` |
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

日常仅调整版本号与发布说明的常规发版不另写 `records/release-<版本>.md` 或逐版追记本节；以下保留重要基准、Web 控制台与专项实测记录。

2026-11-23 的 **0.20.3／mcai-9 发行验证**（完整源码 `docs/development/records/release-0.20.3.md`）使用 Windows、Python 3.12.14、PowerShell 7.6.5、Node v24.11.0、JDK 21.0.7 和 AstrBot v4.29.4。`verify.py --mode release` 完成静态、494 项核心、66 项兼容和发行 ZIP 检查，零失败、零跳过，用时 616.73 秒。另在独立目录验证 A 解包导入、B wheel 离线安装、版本／协议及 CLI 帮助；沿用已验收的八个 Probe 0.5.0 产物。这是发行记录的结果。

2026-11-23 的 **0.20.2／mcai-9 发行验证**（完整源码 `docs/development/records/release-0.20.2.md`）使用 Windows、Python 3.12.14、PowerShell 7.6.5、Node 24.11.0、JDK 21.0.7 和 AstrBot v4.29.4。`verify.py --mode release` 完成静态、493 项核心、66 项兼容和发行 ZIP 检查，零失败、零跳过，用时 621.58 秒。另在独立目录验证 A 解包导入、B wheel 离线安装、版本／协议及 CLI 帮助；沿用已验收的八个 Probe 0.5.0 产物。这是发行记录的结果。

2026-11-21 的 **0.19.1 开发阶段 Web 控制台验证**：以 AstrBot v4.29.4 的实际桥接脚本置于受限 iframe，父页模拟管理 API。Playwright 核对计划创建、编辑、暂停、恢复、删除、局部 Probe 刷新、任务短码弹窗、群输入及亮暗切换；1280px 桌面和 390px 下九个面板没有横向溢出。独立临时源码目录执行 `python scripts/build_release.py --package-only`，插件、B 和源码包的 ZIP CRC 通过，包含对应页面资源与 B 管理模块；使用了已有 Java／Probe 产物。A 机通过 `Downloads.request` 对真实 Modrinth 搜索 API 发出只读请求，收到 1 条结果。未使用真实 QQ、生产服务器或 CurseForge 私有凭据。

同轮使用 Windows、Python 3.12、`PYTHONPATH=runtime/astrbot-4.29.4` 和隔离 `ASTRBOT_ROOT=runtime/astrbot-test`。`python -m pytest -q --require-astrbot --durations=15 --junitxml=runtime/mcai-web-pytest-final.xml` 结算为 514 通过、零跳过、98 条依赖弃用提示（22 分 38 秒）；最后补充的原编号防迟到断言和索引目录校验随 Web 相关节点复测，8 通过。`ruff check main.py mcai tests scripts`、`ruff format --check main.py mcai tests scripts`、`git diff --check` 和三个 JavaScript 模块的 `node --check` 均通过。

Python 行/分支覆盖率衡量执行过的 Python 代码。Java 辅助程序通过真实 JVM 的读写、压缩、外部文件和恢复结果验证；没有把 Python 覆盖率数字用于表示 Java 的覆盖率。

内存诊断复验见完整源码的 `docs/development/records/probe-memory-2026-11-22.md`。`tests/test_memory_diagnostics.py` 启动隔离 JVM 生成真实 JFR 和 HPROF；验证停顿重合、分配首样本、支配路径、小堆降级及 B 端路径限制。

真实模型与隔离服务端的专项记录仅涵盖所列模型和服务端组合。真实 QQ、用户的模型与 CurseForge 凭据以及生产整合包仍需在各自部署中验证。Python回归主要以BAT运行受控交互进程，另有上述真实Minecraft服验收。没有耗尽整机内存、模拟整机断电或真实磁盘损坏；共享额度用小Job限制验证，不能证明MC自身耗尽系统内存时Windows会如何处置其他进程。真实存档来源与许可见[第三方说明](third-party.md)。
