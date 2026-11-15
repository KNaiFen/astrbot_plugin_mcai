# 开发指南

[返回文档索引](../README.md) · [设计约束](../design/README.md)

| 文档 | 内容 |
|---|---|
| [测试说明](testing.md) | 测试环境、命令、场景、当前基线和验证边界 |
| [0.11.0 正确性审查](code-audit-2026-11-14.md) | 已确认缺陷、最小复现、验证证据、38工具契约矩阵与覆盖边界 |
| [正确性审查整改](code-audit-fixes-2026-11-15.md) | R01—R11与U01的核实、最小修改、回归入口与验证边界 |
| [B端运维能力与验证](maintenance-capabilities.md) | 精确编辑、取证恢复、修复验证、组件清单与存档工具的分批实现和测试 |
| [0.8.0 架构与行为审查](architecture-review-0.8.0.md) | 已复现问题、性能风险、测试债务与分批改进及验收条件 |
| [0.8.0 整改与验证](architecture-remediation-0.8.0.md) | 对应R01—R21的当前行为、验收证据与保留边界 |
| [固定验证环境](dependencies.md) | Windows/Python/AstrBot依赖版本、包哈希及空环境重建 |
| [第三方组件与来源](third-party.md) | 设计参考、依赖许可、固定JAR和真实存档片段来源 |
| [探针构建与验证](probe.md) | 五目标构建、真实服务端、测试负载、共存及性能结果 |

源码仓库根 `AGENTS.md` 定义开发协作规则，先阅读相关专题再修改。用户部署从[README](../../README.md)开始。

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
| A任务、发件箱、经验和网页 | `mcai/tasks.py`、`storage.py`、`knowledge.py`、`web.py` |
| 任务私有API及交互记录、诊断导出 | `mcai/tracing.py`、`settings.py` |
| B接口、共用执行上下文、后台工作与下载 | `mcai/host.py`、`operation_context.py`、`client.py`、`jobs.py`、`downloads.py` |
| 独立托管窗口与控制台缓冲 | `mcai/terminal.py`、`console.py`、`console_buffer.py`、`remote_terminal.py` |
| 共享辅助进程与内存额度 | `mcai/execution.py`、`worker.py`、`memory_job.py` |
| 查询、NBT与区域辅助程序 | `mcai/queries.py`、`world.py`、`world_tools.py`、`java/WorldTool.java` |
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

构建校验固定MCA Selector官方JAR的SHA-256，用JDK21构建辅助程序，并构建五个探针目标。首次构建按代理下载Java17和Gradle依赖；可用 `scripts/build_probe.py --java17 ... --java21 ...` 指定JDK。产物在被忽略的 `dist/`：

- `astrbot_plugin_mcai.zip`：插件入口、配置schema、A所需模块、依赖清单、运行时规则模板、设置视图、README和分层文档。
- `mcai_windows_host.zip`：Python项目、基础与实例配置示例、模块、规则模板、JAR与许可、README和分层文档。
- `probe/`：五个MOD、各目标sources JAR、完整源码ZIP与许可；B包中同样附带。
- `mcai-<版本>-source.zip`：完整源码、构建脚本、测试和许可，不含Git历史及被忽略的本地文件。

发行包面向部署，不包含源码测试、开发脚本、上游或开发 `AGENTS.md`。开发文档中的测试、构建命令应在源码仓库执行。JAR随B包部署，运行时不下载。

涉及版本发布时同步 `metadata.yaml` 与 `pyproject.toml`。文档整理不必改变功能版本。检查ZIP完整性、模块、模板、许可与文档相对链接；影响安装或构建时，从解压B包构建wheel，在独立环境安装，并从解压插件验证导入与关键流程。

## Git与文档维护

- 上游、运行数据、私有配置、环境和构建输出由 `.gitignore` 排除。`git status --short`检查本次改动，`git status --short --ignored`检查本地工作产物。
- `host.example.json`、Java源码、vendor许可证、`tests/fixtures/worlds`的许可与固定片段需要跟踪。不要用过宽的忽略规则隐藏它们。
- 用户文档维护当前行为；设计文档保留最终方案及明确边界；测试基线标记版本与日期。不要把每次临时失败或开发对话抄进README。
- 完成消融审查、适当验证后创建简短中文commit。默认不推送或替用户部署。

## 发布仓库

本地 `dev` 保存完整源码与开发历史，只在本地维护。公开仓库 [astrbot_plugin_mcai](https://github.com/KNaiFen/astrbot_plugin_mcai) 的 `main` 与插件ZIP使用同一文件清单，供AstrBot通过链接安装和更新。B程序、Probe与完整源码以Release附件提供。

首次发布的 `main` 使用独立初始提交，不带入开发历史。后续发布以原 `main` 为父提交更新插件文件，保持AstrBot正常拉取更新。只显式推送 `main`，不要使用 `--all` 或 `--mirror`，也不推送 `dev`。
