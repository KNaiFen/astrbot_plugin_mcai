# 排障流程测试说明

[开发索引](README.md)

测试同时检查工具返回值、磁盘文件、备份内容、进程状态和持久化记录。测试服务器通过真实 BAT/ConPTY 启动可交互进程；存档测试使用固定来源的真实片段和生成样本；Agent 集成运行 AstrBot v4.29.4 的真实 runner，模型回复由测试控制。A/B 接口测试统一经 HTTPS。

## 当前验证

0.7.1 清理旧插件迁移、内联配置转换、旧读取接口和旧任务字段补齐。当前工具恢复仍使用原操作编号；配置、审核、诊断、修复与暂停续接继续回归。公开插件与完整源码分开发行，检查解压安装、文件清单及许可。

2026-11-13，Windows／Python3.12.14／AstrBot v4.29.4：全量310项通过，无跳过，耗时约475秒。此轮已移除迁移场景；测试统一使用HTTPS，原HTTP／HTTPS重复参数随后合并。两项警告来自AstrBot的audioop和工具schema弃用提示。

最终补充边界15项通过，覆盖旧读取动作拒绝、HTTP地址拒绝、内联配置拒绝、原编号恢复和方案复核；Ruff及Git空白检查通过。

精简插件解压后经真实runner验证12个关键场景，包括识别、下载、审核与修复、归档、检查点恢复、多人管理员和设置接口。设置用例首次因测试副本的schema路径指向错误失败，修正测试路径后通过；产品文件未改动。B包从解压目录在全新Python环境安装，导入来自site-packages，HTTPS CLI的list/start/status/reload/stop通过，路径含中文与空格。

Probe 功能保持 0.1.0；四目标服内功能与开销数据见[探针验证](probe.md)。本轮不重复宣称已重新运行四个 Minecraft 目标或真实模型、QQ与CurseForge凭据联调。

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
| 真实 Agent 工具链 | 二十二个工具经实际 runner 调用，含五个探针入口、暂停续接、后台查询/长字段/取消/修复记录、单次模型回复内多个工具、未知工具后继续、错参拒绝、步数上限、模型配置错误后恢复、中止、已提交工具检查点恢复 | `test_astrbot_integration.py`、`test_agent_edges.py`、`test_review_resume.py` |
| 服内探针桥接 | HTTPS断线去重、结果身份核对、会话变化、超时状态不确定、晚到结果、已有结果导入、范围schema、分页及长字段、取消确认、修复协作、多实例隔离 | `test_probe.py` |
| 工具参数 | 必填项、动作与字段不匹配、额外参数、错误类型、页大小/超时边界、负 NBT 索引、缺失的修复字段、空步骤与空脚本备份列表 | `test_agent_edges.py` |
| 网络和持久化 | 502/503/504 重试、保留请求和操作编号、非 JSON/损坏 JSON、永久错误快速失败、POST/GET 响应丢失时中止、修复/诊断不重复执行、插件重载、B 的任务重建中断状态、PID 身份不匹配时保留新进程 | `test_workflows.py`、`test_diagnostics.py`、`test_client_recovery.py`、`test_job_interactions.py` |
| HTTPS 直连 | 首次生成/重启复用证书、中文和空格路径、IP 地址直连、指纹格式和匹配、错误令牌、损坏或缺失的证书、本机 CLI、TLS 响应丢失/暂时断网、操作去重、后台任务续读与取消、插件重载 | `test_https.py` |
| 独立审核和续接 | 三个入口分别放行/拒绝、配置与协议错误、审核重试、材料缺失/超限、脚本变更、主上下文隔离、规则重载、检查点中断恢复、修复部分失败后再次审批 | `test_review_resume.py`、`test_model_recovery_summary.py` |
| 原生模型适配与 API 摘要 | 真实 Chat／Responses 适配器与模拟 HTTP API、独立思考程度、原始摘要事件、分片完成后发送、原始推理不转发、不支持摘要/流式时的兼容行为、原文分段、去重和停止后丢弃 | `test_provider_runtime.py`、`test_model_recovery_summary.py` |
| Windows 运维入口 | CLI 列表/状态/启停/重启/恢复、attach 输入和 EOF/detach、断开不停止服务端、多行控制台命令拒绝、原进程仍存活时拒绝重复接管、相对配置路径、每实例独立 Java | `test_console_cli.py`、`test_diagnostics.py` |

## 单独复现

测试中的两端网络波动通过本地 HTTPS 服务实际返回临时错误或丢失响应，在真实 TLS 握手与证书指纹校验后调用操作接口。网页与模型模拟接口可使用本地 HTTP。并发扫描通过可控制的等待点稳定复现排队与取消时序。备份和替换失败通过注入文件操作错误复现。所有测试数据、脚本和进程都由用例在临时目录创建。

例如单独检查并发取消和扫描排队：

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_job_interactions.py -k 'double_cancel or scan_queue' -v
```

单独检查工具链和提交后恢复：

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_agent_edges.py tests/test_mcai_workflow.py -k 'all_ten or submitted_tool' -v
```

## 验证范围

Python 行/分支覆盖率衡量执行过的 Python 代码。Java 辅助程序通过真实 JVM 的读写、压缩、外部文件和恢复结果验证；没有把 Python 覆盖率数字用于表示 Java 的覆盖率。

真实QQ、模型服务及生产整合包仍需部署联调。0.6.0已运行四目标Minecraft服务端，详见探针验证；原Python测试中的终端夹具仍为可交互Python进程。没有模拟整机断电和真实磁盘损坏；进程身份、中断重建、备份失败和替换失败有独立用例。真实存档来源与许可见[第三方说明](third-party.md)。
