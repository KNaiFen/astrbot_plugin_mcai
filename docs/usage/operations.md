# 运行维护

[使用索引](README.md) · [配置说明](configuration.md)

## 多窗口管理服务端

B先在独立窗口运行 `mcai host`。每个服务端再打开一个独立托管窗口：

```powershell
mcai tm -C "D:/MC/CTI_0.4.6"
./start.bat
```

`terminal` 与 `tm` 等效；在服务端目录运行时可省略 `-C`。B首次启动记住本机配置绝对位置，之后不必向各窗口重复填写连接信息。未知目录先输入项目ID和说明，B在线登记；已有目录在B离线时照常运行并持续重连。

每个窗口独立持有PowerShell／ConPTY和BAT。关闭窗口会影响该实例，其他实例继续；B退出、升级或崩溃不关闭它们。没有托管窗口时，远程start要求人工打开，不自动创建窗口。

`mcai attach cti` 可额外查看控制台并发送MC命令，`/detach` 仅结束这次查看。人工输入不走AI审核；生产操作请自行核对。

其他命令：

```powershell
.\.venv\Scripts\python.exe -m mcai status cti
.\.venv\Scripts\python.exe -m mcai stop cti
.\.venv\Scripts\python.exe -m mcai restart cti
.\.venv\Scripts\python.exe -m mcai reload
.\.venv\Scripts\python.exe -m mcai --config D:/mcai/host.json list
```

`--config` 等全局选项放在子命令前。可通过 Windows 任务计划程序启动控制程序，运行目录与配置路径应固定。

## 任务、批准与停止

新任务 `/mcainew 任务名 [补充说明]` 必须引用玩家的问题。任务名后的文本可直接补充实例、时间和复现条件，与引用问题一起保存并进入首次排查；补充说明可省略，任务名不带空格。任务未识别目标时，AI可联网、看历史、提问；实例工具需先绑定目标。多个未识别任务可以并存，绑定时才占用实例。已绑定任务暂停后仍保留占用。

| 场景 | 行为 |
|---|---|
| 玩家补充 `/mcaisay` | 新反馈进入任务；未执行方案失效，AI重新判断 |
| 修复执行中补充 | 先保留反馈，执行结果返回后再处理 |
| 暂停时补充 | 只保存，不自动唤醒；管理员 `/mcairesume` 继续 |
| 管理员 `/mcaiapply` | 只批准当前已通过 AI 审核的方案；新方案需再次批准 |
| `/mcailist [页码]`、`/mcaiplan 任务名` | 查看当前群活动任务或重发待批准方案 |
| 管理员 `/mcaipause` | 保存进度暂停；已提交修复完成后再暂停模型 |
| 管理员 `/mcaistop` | 停止接收反馈，取消所属诊断、下载与扫描；当前文件步骤结束后停止后续步骤 |
| 管理员 `/mcaidone` | 验收结束、释放占用；后台生成已验收经验 |

已提交修复的任务保持目标固定，其他服务端另建任务。停止不自动撤销已发生修改，也不生成已解决案例。修复执行中要中止使用 `/mcaistop`，不能直接验收。

群指令统一使用 `/mcai…`，创建时填写任务名和可选补充，不需要填写实例 ID；AI根据线索选择目标。多位管理员权限相同。

## 断线和修复失败

两端网络波动自动重连，使用原操作编号查询，不重复启动诊断或修复。MC 服务端、B 上的后台诊断、扫描和下载继续运行。模型服务连接错误默认最多尝试 3 次，2、5 秒退避；耗尽或永久配置错误会保存并暂停。

修复确定失败后停止原方案后续步骤，保留备份、已发生修改及服务端状态。AI 检查记录、状态和控制台继续分析；新方案重新审核、批准，无可行方向则暂停。不会自动回滚或重启失败的修复。

插件重载恢复已保存操作和上下文，已暂停任务保持暂停。B 程序重启会把未完成工作标记为中断或状态不确定，保留输出，不自动重放。托管窗口继续运行并自动重连B；原控制请求绑定会话，不会重放到新窗口。

正常退出B会结束辅助工作、等待当前修复操作并断开托管连接，不主动停服。强制结束B会终止辅助进程树，托管窗口继续运行；未完成修改保留现场。

## 控制台与内存额度

控制台每窗口保留9999行，且最多16 MiB UTF-8内容；单行超过64 KiB保留末尾并标注截断。不连续写入B数据库。游标包含会话，内容淘汰会返回缺口；更早数据查询服务端logs。窗口关闭后缓冲消失，B重启不会清除仍在窗口里的缓冲。任务实际读取的片段和操作审计仍持久化。

辅助扫描、下载、NBT、备份、修复及脚本由独立进程执行，所有实例共用 `operations_memory_limit_mib`，默认8192 MiB。上限按Windows提交内存计算，包含辅助Python进程及子进程的开销，不是Java的Xmx或文件大小。B和服务端不计入额度。额度不足使当前操作失败，保留输出与备份，AI可缩小范围继续；新修复重新批准。此额度不限制MC，也不防止MC占满整机内存。

## 数据与备份

| 位置 | 内容 |
|---|---|
| A：`AstrBot/data/plugin_data/astrbot_plugin_mcai/` | 任务、消息、审核与工具记录、规则、网页缓存、经验 |
| A：`knowledge/index.md`、`knowledge/servers/*.md` | 按 B 的规范目录关联的经验索引和文档 |
| B：配置的 `data_dir` | `state.sqlite3`、`audit.jsonl`、证书和任务数据 |
| B：`jobs/操作编号/` | 后台结果、诊断脚本、输出及存档采样副本 |
| B：`downloads/操作编号/` | 完成校验的暂存文件和未完成临时文件 |
| B：`backups/操作编号/` | 原文件、`manifest.json`、修复脚本与输出 |

完整命令、上下文和错误在本地记录中；群里只发关键交流及可选 API 摘要。当前不自动清理备份、下载与历史，维护时先确定是否还被待执行方案或恢复流程引用。

文件修复先停服备份，成功后原先运行的服务端默认启动；方案中显式启停步骤优先。在线控制台修复可能没有可恢复备份，批准消息会说明。人工恢复某次备份会先备份当前目标：

```powershell
.\.venv\Scripts\python.exe -m mcai restore cti 备份目录名
```

恢复使用备份清单：恢复原文件、移除该次修复新增的目标。恢复操作也可能失败，应保留原备份并检查执行记录。

### 容量与人工维护

容量取决于实例文件、备份次数、下载大小和诊断输出，不预设统一保留期限。预留“全部待备份文件＋暂存下载＋现有历史”的空间，定期查看磁盘可用量。在完整源码包中运行只读清单；可重复传入已安装Probe的实例目录：

```powershell
.\.venv\Scripts\python.exe scripts/data_inventory.py --a-dir "D:/AstrBot/data/plugin_data/astrbot_plugin_mcai" --b-dir "D:/MCAI/runtime/host" --instance "D:/MC/NCraft"
```

清单统计字节、文件数、数据库记录类型和quick_check，列出活动／暂停任务、待批准方案、未结算工具、运行操作、待取消、待归档和待核对控制的引用来源。两端应在同一维护窗口导出；未列出活动引用的历史仍可能用于人工恢复和经验追溯，清单不生成删除候选。

维护顺序：暂停A接收任务并退出插件，正常退出B等待修复完成；维护Probe数据还需停对应MC服。先完整备份A/B数据、实例Probe目录和托管窗口数据，保存配置及证书。SQLite使用Python的sqlite3.Connection.backup做一致副本，对副本执行PRAGMA integrity_check；运行中不能只复制主数据库而遗漏WAL。先归档已完成且无活动引用的下载、诊断输出和Probe请求／结果，再按人工恢复需求归档整套备份及manifest。数据库records/events、审核与上下文证据不手工逐行删除；证书、规则、knowledge、待核对控制和活动引用文件保留。归档后启动两端，核对原操作、历史查询、备份读取和暂停任务续接，再决定离线归档的保留期限。

备份按源规范目录核对身份；同目录改配置名仍可恢复，同名换目录会拒绝。缺少来源目录的旧清单需人工核对。修复日志每次读取最多12000字符，mc_job repair的next_offset用于继续读取。

## 经验维护

管理员验收后才归档，不把 AI 自称修好直接记为成功。归档在后台进行，失败不会重新占用实例；待归档状态在插件重载或该实例下次绑定时重试。

经验文档允许人工补充。索引的 `mcai-server` 注释记录规范目录和相对文档路径，`mcai-case` 标记用于案例去重，编辑时保留这些标记。实例配置改名或公网 IP 改变不影响目录关联；搬迁服务端目录默认视为新实例，需要继承经验时人工调整索引中的目录关联。当前按一台 B 设计，换到另一台主机应分开维护经验。

## 升级与常见问题

升级前保留 A 插件数据和 B 的 `data_dir`，尤其是任务状态、备份和 TLS 证书。替换插件文件并安装新 `requirements.txt`；替换 B 文件后重新安装 Python 依赖。AstrBot 最低版本为 v4.29.4，不设版本上限；当前集成验证基线为 v4.29.4。升级 AstrBot 后先执行插件的连接与模型能力测试，再创建一次任务确认 runner 与工具调用正常；新版本的验证结果另行记录。

升级保留当前插件数据目录，规则文件和经验文档持续沿用。安装仅使用 `astrbot_plugin_mcai`，实例配置单独保存在 `instances.json`。

### 安装依赖时拒绝访问

Windows 上，AstrBot 插件页安装依赖时，pip 可能需要升级 AstrBot 已加载的 Python 扩展。例如 `trafilatura 2.3.1` 要求 `charset-normalizer>=3.5.2`，若环境中仍是 3.4.7，替换其 `__mypyc*.pyd` 时可能出现 `WinError 5：拒绝访问`，使插件安装中止。

1. 完全退出 AstrBot，确认其 Python 进程已结束；仅禁用或重载插件无法保证释放扩展文件。若使用自动重启脚本，先停止该脚本。
2. 将同次发行的 `astrbot_plugin_mcai.zip` 解压到临时目录，找到其中的 `requirements.txt`。
3. 在 PowerShell 7 中，用 **AstrBot 实际使用的 Python** 安装这份依赖清单。以下示例中 AstrBot 位于 `D:\AstrBot`，插件解压到 `D:\MCAI-A`；按自己的目录替换：

```powershell
& 'D:\AstrBot\venv\Scripts\python.exe' -m pip install -r 'D:\MCAI-A\requirements.txt'
& 'D:\AstrBot\venv\Scripts\python.exe' -c 'import trafilatura, charset_normalizer; print(trafilatura.__version__, charset_normalizer.__version__)'
```

使用镜像时，在安装命令末尾加 `-i 'https://mirrors.aliyun.com/pypi/simple/'`。不要换用 B 的 `.venv` 或系统 Python。若进程全部退出后仍拒绝访问，检查运行账号对日志所示文件的读写权限与文件占用。

安装命令成功、导入检查打印版本号后，重新启动 AstrBot，在插件页重试安装 ZIP 或仓库。若上次 pip 卸载失败导致 `charset_normalizer` 导入损坏，在 AstrBot 仍退出时，用同一个 Python 执行 `-m pip install --force-reinstall 'charset-normalizer>=3.5.2,<4'`，然后重新安装插件依赖并检查导入。

### 其他常见问题

| 现象 | 处理 |
|---|---|
| 无法连接 B | 检查 B 是否运行、端口映射、防火墙和 A 的最终 `https://` 地址；详细错误看本地日志 |
| 指纹或令牌错误 | 核对 B 启动输出与 A 配置，修改后重载插件 |
| 证书文件缺失或损坏 | 检查 `server.crt` 和 `server.key`；不会覆盖现有半套证书 |
| 模型或审核配置错误 | 修正提供商、参数或凭据后，管理员 `/mcairesume` 继续 |
| 查不到目标服务端 | 检查 B 的目录与 `description`；在群里补充常用名称、版本或位置 |
| Java 版本不符 | 分别检查实例 `java_path`、BAT 写死路径和 `world_tools.java_path` |
| PowerShell 版本错误 | 安装 PowerShell 7.3+ 的 7.x，或在 B 的 `powershell_path` 指定正确 `pwsh.exe` |
| 主动停服超时 | 检查本次退出提示是否匹配、倒计时是否存在；原循环不需要删除。未确认退出时不会进行文件修复 |
| 不能搜索或网页提取失败 | 核对模型服务能力；动态或需登录页面不支持完整浏览器渲染 |
| MOD 下载受限 | 检查 CurseForge key、分发权限及实际官方文件地址 |

人工换证书时先停止 B，将旧 `server.crt`、`server.key` 一起移走，再启动生成新证书并更新 A 的指纹。公网 IP 变化而证书未变时，只改 `host_url`。更多持久化与失败语义见[状态与恢复设计](../design/storage-and-recovery.md)。
