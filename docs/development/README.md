# 开发指南

[返回文档索引](../README.md) · [设计约束](../design/README.md)

| 文档 | 内容 |
|---|---|
| [测试与复验](testing.md) | 验证入口、场景清单、测试编写与产物清理 |
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
| A 插件入口、群命令和只读问答 | `main.py`、`_conf_schema.json`、`readonly.py`、`attachments.py` |
| 原生 runner、模型请求、历史压缩和输入预算 | `astrbot_agent.py`、`agent_runtime.py`、`context_budget.py`、`model_budget.py` |
| 工具定义、参数、帮助和结果证据 | `tool_schemas.py`、`tool_arguments.py`、`tool_help.py`、`tool_results.py`、`evidence.py`、`playbooks.py` |
| 独立审核、计划与规则模板管理 | `review.py`、`review_parser.ps1`、`plans.py`、`runtime_rules.py` |
| A 任务、发件箱、SQLite 与经验文档 | `tasks.py`、`storage.py`、`knowledge.py` |
| 模型能力、用量、上游价格与 API 追踪 | `capabilities.py`、`model_usage.py`、`model_prices.py`、`tracing.py` |
| 两端 Dashboard 接口、设置面板与热重载 | `settings.py`、`host_web.py`、`configuration.py`、`views/settings/` |
| 搜索、网页、MOD 下载与 B 暂存 | `search.py`、`web.py`、`public_http.py`、`downloads.py`、`download_store.py` |
| B 主机入口、A 客户端、版本协议与 TLS | `__init__.py`、`__main__.py`、`host.py`、`client.py`、`protocol.py`、`tls.py`、`environment.py` |
| B 操作、备份、验收检查与定时维护 | `operation_context.py`、`backup.py`、`verification.py`、`scheduler.py` |
| 后台工作、辅助进程与共享内存 | `jobs.py`、`execution.py`、`worker.py`、`memory_job.py` |
| 托管窗口与控制台缓冲 | `terminal.py`、`remote_terminal.py`、`console.py`、`console_buffer.py` |
| A 源码工作区、路径约束与 B 隔离试服 | `workspace.py`、`workspace_worker.py`、`paths.py`、`test_environment.py` |
| B 故障留证、附件和告警 | `incidents.py`、`incident_files.py`、`incident_store.py`、`alerts.py` |
| 占用统计、数据清理和日志轮转 | `storage_usage.py`、`cleanup.py`、`monthly_logs.py` |
| 查询 CLI、文本编辑、组件清单和进程／JFR 诊断 | `query_cli.py`、`queries.py`、`text_files.py`、`inventory.py`、`diagnostics.py`、`chunk_jfr.py` |
| NBT、方块、区域与恢复 | `world.py`、`blocks.py`、`world_tools.py`、`region_recovery.py`、`java/` |
| 服内探针、文件协议、启动就绪与 spark 报告 | `mods/mcai-probe/`、`probe.py`、`probe_exchange.py`、`probe_readiness.py`、`spark_format.py`、`spark_report.py` |

表中只写文件名的模块均在 `mcai/`（根目录的 `main.py`、`_conf_schema.json` 除外）。运行时规则模板在该包中保留，不能移动成仅源码可读的文档。

## 修改与验证

先定义要改变的行为和验证标准，沿用既有操作编号、锁、后台任务和状态记录。生产写入、审核、断点恢复和任务状态变更通过真实runner／HTTPS集成验证；低影响文档变更不需要重写或复制实现细节的单元测试。

```powershell
# 一键静态检查（Ruff、Git 空白、Node 语法、配置与版本一致、文档链接、Probe CoreChecks）
.\.venv\Scripts\python.exe scripts/verify.py --mode static
# 快速冒烟；其余模式见测试说明
.\.venv\Scripts\python.exe scripts/verify.py --mode quick
```

测试模式、场景、夹具和 CI 分工见[测试说明](testing.md)。实际模型、QQ 和整合包的联调与模拟接口测试分开记录，不用行覆盖率推断 MC 版本兼容性。

B生命周期使用HostRunner：在aiohttp的pre_shutdown停止WebSocket输入之前等待已接受操作。嵌入或测试create_app时同样使用该runner，避免在on_shutdown内等待仍需终端响应的修复。

## 构建与发行

```powershell
# 完整构建（含 Java 辅助程序与 Probe 八目标）
.\.venv\Scripts\python.exe scripts/build_release.py
# 复用已有 Java／Probe 产物仅打包并校验（含 A/B 解包导入与 wheel 安装检查）
.\.venv\Scripts\python.exe scripts/verify.py --mode package
```

构建校验固定 MCA Selector 官方 JAR 的 SHA-256，用 JDK21 构建辅助程序，并构建八目标。首次构建按代理下载 Java17 和 Gradle 依赖；可用 `scripts/build_probe.py --java17 ... --java21 ...` 指定 JDK。产物在被忽略的 `dist/`：

从 Git 工作树构建时，源码清单取自 `git ls-files --cached`，内容取自工作树；新增、删除或改名的路径要先更新索引。完整源码 ZIP 内附 `SOURCE_MANIFEST.json`，解压到无 Git 的目录后可用同一命令构建。已有匹配版本的 Java 和八个 Probe 构建产物时，可加 `--package-only` 单独打包；清单错误会在构建前报告，三个 ZIP 都通过内部校验后才替换旧包。`verify.py --mode package` 与 `--mode release` 使用 `--package-only`，并自动完成解压链接检查、A 包隔离导入、B 包离线 wheel 构建安装和 `mcai --help` 冒烟。

- `astrbot_plugin_mcai.zip`：插件入口、配置 schema、A 所需模块、依赖清单、运行时规则模板、设置视图、README 和分层文档。
- `mcai_windows_host.zip`：Python 项目、基础与实例配置示例、模块、规则模板、JAR 与许可、README 和分层文档。
- `probe/`：八个目标的主 JAR、完整源码 ZIP 与许可（另在 `dist/probe/` 单独保留各目标 sources JAR）；B 包随 `probe/` 纳入白名单内的上述主 JAR、源码 ZIP 与许可。
- `mcai-<版本>-source.zip`：来自 Git 跟踪清单的源码、构建脚本、测试和许可；开发 `AGENTS.md`、未跟踪试验文件、运行数据和 Git 历史不打包。

A、B 包保留 README 引用的文档及目录层级，具体为 `docs/README.md`、使用／设计／开发三个目录的一级 Markdown 和 `docs/development/dependencies/` 的文件。重要实服、Probe 和历史归档记录位于完整源码的 `docs/development/records/`。源码测试、开发脚本、上游副本及开发 `AGENTS.md` 不进入 A、B 安装包；指南中的测试和构建命令在完整源码中运行。JAR 与相应许可随 B 包部署，运行时不下载。

常规版本发布统一使用 `scripts/release.py`，不再手工拼临时脚本、不再逐版新增 `records/release-<版本>.md` 流水账，也不在发布后回写二次提交：

```powershell
# 1. 同步版本号（pyproject.toml、metadata.yaml、mcai/protocol.py、README.md）
.\.venv\Scripts\python.exe scripts/release.py bump 0.20.4
# 2. 在 docs/usage/releases.md 顶部补充本次发布说明并提交 dev
# 3. 获授权发布时一键校验、归档 dist/<版本>/ + SHA256SUMS.txt、推 main 并创建 GitHub Release
.\.venv\Scripts\python.exe scripts/release.py publish
```

若功能提交已通过完整测试且发版准备提交只改版本号与发布说明，可在 `publish` 时追加 `--verify package`（约十秒完成静态与隔离安装校验）；需要重编 Probe 时追加 `--build-probe`。上传 GitHub Release 附件时直接核对 API 返回的 `state`、`size` 与 `sha256` digest，无需把全部附件重新下载回本地。

## Git与文档维护

- 上游（`.upstream/`）、运行数据（`runtime/`、`data/`）、私有配置、密钥、证书、下载、测试安装目录、构建输出（`dist/`）、虚拟环境、生成 JAR 与缓存由 `.gitignore` 排除，禁止提交。`git status --short` 检查本次改动，`git status --short --ignored` 检查本地工作产物。
- `host.example.json`、`instances.example.json`、Java 源码、`mcai/vendor/` 下的许可证、`tests/fixtures/worlds` 的许可与固定片段需要跟踪。不要用过宽的忽略规则隐藏它们。
- 根 README 只放项目介绍、部署与使用入口。使用文档说明当前操作（保持锚点稳定，不在小标题和正文中四处写死小版本号）；设计文档解释实际行为和约束；重要里程碑、实服联调与专项核验结果进入 `records/`，标注被测版本、环境、命令、结果与限制。历史报告引用的本地证据清理后，在对应记录注明。移动文档时同步核对链接与打包清单。
- 完成消融审查、适当验证后创建简短中文 commit。默认不推送或替用户部署。

## 发布仓库

本地 `dev` 保存完整源码与开发历史，只在本地维护。公开仓库 [astrbot_plugin_mcai](https://github.com/KNaiFen/astrbot_plugin_mcai) 的 `main` 与插件 ZIP 使用同一文件清单，供 AstrBot 通过链接安装和更新。B 程序、Probe 与完整源码以 Release 附件提供。

首次发布的 `main` 使用独立初始提交，不带入开发历史。后续发布由 `scripts/release.py publish` 在临时 worktree 以原 `main` 为父提交更新插件文件并仅显式推送 `main`；手动操作时同样禁止使用 `--all` 或 `--mirror`，也不推送 `dev`、开发历史或本地备份引用。
