# 开发指南

[返回文档索引](../README.md) · [设计约束](../design/README.md)

| 文档 | 内容 |
|---|---|
| [测试与复验](testing.md) | 环境要求、按范围选择的测试命令、安装验证与证据边界 |
| [Probe 构建与复验](probe.md) | 八目标构建、隔离实服准备和测试脚本 |
| [固定验证环境](dependencies.md) | Windows／Python／AstrBot 环境的依赖锁与重建方式 |
| [第三方组件与来源](third-party.md) | 依赖许可、固定 JAR 和真实存档片段来源 |

在完整源码中打开 `docs/development/records/README.md`，可查发行核对、历史复盘和实测证据。用户安装从[项目首页](../../README.md)开始。

源码仓库根 `AGENTS.md` 定义开发协作规则，先阅读相关专题再修改。

## 环境与源码安装

开发环境使用Windows、Python3.12、PowerShell7.3+、JDK21+。JDK用于构建Java辅助程序；各MC服务端运行时Java独立配置。

在仓库根执行：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e '.[test]'
.\.venv\Scripts\python.exe scripts/setup_world_tools.py
```

辅助程序构建脚本读取 `HTTPS_PROXY` 或Git的 `http.proxy`，也可显式传 `--proxy`；`--java-home`指定JDK目录。上游源码和外部依赖下载走代理，参考项目放 `.upstream/`，不要提交上游副本。

完整Agent集成需要AstrBot **v4.29.4** 源码和依赖。`.upstream/AstrBot`可能是其他版本，先核对；既有测试环境示例为 `runtime/astrbot-4.29.4`，参见[测试命令](testing.md#运行)。

## 代码入口

| 范围 | 入口 |
|---|---|
| 插件命令、初始化与通知 | `main.py`、`_conf_schema.json` |
| Agent循环、上下文预算、工具schema与结果、模型重试与审核 | `mcai/astrbot_agent.py`、`context_budget.py`、`agent_runtime.py`、`tool_schemas.py`、`tool_results.py`、`review.py` |
| A 任务、发件箱、经验和网页 | `mcai/tasks.py`、`storage.py`、`knowledge.py`、`web.py` |
| MOD 工作区、试服与试玩发布 | `mcai/workspace.py`、`test_environment.py`、`operation_context.py` |
| B 故障留证和 A 通知 | `mcai/incidents.py`、`incident_store.py`、`main.py` |
| 任务私有API及交互记录、诊断导出 | `mcai/tracing.py`、`settings.py` |
| B接口、共用执行上下文、后台工作与下载 | `mcai/host.py`、`operation_context.py`、`client.py`、`jobs.py`、`downloads.py` |
| 独立托管窗口与控制台缓冲 | `mcai/terminal.py`、`console.py`、`console_buffer.py`、`remote_terminal.py` |
| 共享辅助进程与内存额度 | `mcai/execution.py`、`worker.py`、`memory_job.py` |
| 查询、NBT、区域与 JFR 辅助程序 | `mcai/queries.py`、`world_tools.py`、`chunk_jfr.py`、`java/` |
| Windows入口、Java与HTTPS | `mcai/__main__.py`、`environment.py`、`tls.py` |
| 配置热重载与设置页 | `mcai/configuration.py`、`settings.py`、`views/settings/` |
| 独立搜索与模型能力测试 | `mcai/search.py`、`capabilities.py` |
| 服内探针与桥接 | `mods/mcai-probe/`、`mcai/probe.py` |

表中同一行的简写模块均在 `mcai/`。运行时规则模板在该包中保留，不能移动成仅源码可读的文档。

## 修改与验证

先定义要改变的行为和验证标准，沿用既有操作编号、锁、后台任务和状态记录。生产写入、审核、断点恢复和任务状态变更通过真实runner／HTTPS集成验证；低影响文档变更不需要重写或复制实现细节的单元测试。

```powershell
.\.venv\Scripts\ruff.exe check main.py mcai tests scripts
.\.venv\Scripts\ruff.exe format --check main.py mcai tests scripts
git diff --check
```

测试场景与完整命令见[测试说明](testing.md)。实际模型、QQ和生产整合包的联调与模拟接口测试分开记录，不把行覆盖率当成所有MC版本兼容性证明。

HTTPS夹具为每个实例另开独立终端，B使用实际辅助工作进程；多窗口、B重启、资源限制及真实CLI交互见`test_terminal_isolation.py`。网站响应、备份失败和扫描时序等故障注入用例通过测试侧`local_execution`保留当前进程的替身，产品没有跳过内存额度的执行选项。

B生命周期使用HostRunner：在aiohttp的pre_shutdown停止WebSocket输入之前等待已接受操作。嵌入或测试create_app时同样使用该runner，避免在on_shutdown内等待仍需终端响应的修复。

## 构建与发行

```powershell
.\.venv\Scripts\python.exe scripts/build_release.py
```

构建校验固定MCA Selector官方JAR的SHA-256，用JDK21构建辅助程序，并构建八目标。首次构建按代理下载Java17和Gradle依赖；可用 `scripts/build_probe.py --java17 ... --java21 ...` 指定JDK。产物在被忽略的 `dist/`：

从 Git 工作树构建时使用 Git 跟踪文件清单。完整源码 ZIP 内附 `SOURCE_MANIFEST.json`，解压到无 Git 的目录后可用同一命令构建。已有匹配版本的 Java 和八个 Probe 构建产物时，可加 `--package-only` 单独打包；清单错误会在构建前报告，三个 ZIP 都通过内部校验后才替换旧包。

- `astrbot_plugin_mcai.zip`：插件入口、配置schema、A所需模块、依赖清单、运行时规则模板、设置视图、README和分层文档。
- `mcai_windows_host.zip`：Python项目、基础与实例配置示例、模块、规则模板、JAR与许可、README和分层文档。
- `probe/`：八目标、各目标sources JAR、完整源码ZIP与许可；B包中同样附带。
- `mcai-<版本>-source.zip`：来自 Git 跟踪清单的源码、构建脚本、测试和许可；开发 `AGENTS.md`、未跟踪试验文件、运行数据和 Git 历史不打包。

A、B 包携带当前使用、设计和开发指南及相关许可。发行验证、历史记录和证据位于完整源码的 `docs/development/records/`。源码测试、开发脚本、上游副本及开发 `AGENTS.md` 不进入 A、B 安装包；指南中的测试和构建命令在完整源码中运行。JAR 随 B 包部署，运行时不下载。

发行时同步 `metadata.yaml`、`pyproject.toml` 与 `mcai/protocol.py`，Probe 版本单独管理。检查 ZIP 完整性、模块、模板、许可与文档相对链接；影响安装或构建时，从解压 B 包构建 wheel 并独立安装，从解压 A 包验证导入与关键流程。对上传的附件生成 `SHA256SUMS.txt`。

## Git与文档维护

- 上游、运行数据、私有配置、环境和构建输出由 `.gitignore` 排除。`git status --short`检查本次改动，`git status --short --ignored`检查本地工作产物。
- `host.example.json`、Java源码、vendor许可证、`tests/fixtures/worlds`的许可与固定片段需要跟踪。不要用过宽的忽略规则隐藏它们。
- 使用文档说明当前操作；设计文档解释实际行为和约束；发行和验证结果进入 `records/`，标注被测版本、环境、命令、结果与限制。历史报告引用的本地证据清理后，在对应记录注明。
- 完成消融审查、适当验证后创建简短中文commit。默认不推送或替用户部署。

## 发布仓库

本地 `dev` 保存完整源码与开发历史，只在本地维护。公开仓库 [astrbot_plugin_mcai](https://github.com/KNaiFen/astrbot_plugin_mcai) 的 `main` 与插件ZIP使用同一文件清单，供AstrBot通过链接安装和更新。B程序、Probe与完整源码以Release附件提供。

首次发布的 `main` 使用独立初始提交，不带入开发历史。后续发布以原 `main` 为父提交更新插件文件，保持AstrBot正常拉取更新。只显式推送 `main`，不要使用 `--all` 或 `--mirror`，也不推送 `dev`。
