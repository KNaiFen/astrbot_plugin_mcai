# 首次部署与上手指南

[返回使用文档](README.md) · [项目首页](../../README.md) · [配置说明](configuration.md) · [运行维护](operations.md)

本文按第一次部署的顺序说明。示例路径请按本机实际情况替换：

| 示例 | 含义 |
|---|---|
| `D:\MCAI` | B 主机程序解压目录，包含 `pyproject.toml` 和 `host.example.json` |
| `D:\MC\CTI` | 已经可以正常启动的 MC 服务端目录，包含 `start.bat`、配置和存档 |
| `cti` | 给这个服务端起的配置 ID，用于本机命令；群内创建任务时由 AI 自动选择服务端 |
| `主城卡顿` | 群内排障任务名，与配置 ID 分开 |

下文 PowerShell 命令默认在 **B 机器**的 PowerShell 7 执行，输入时不带提示符；QQ 群指令发在 Bot 所在的允许群。

---

## 一、安装前准备

A 与 B 当前使用 `mcai-9` 协议（Probe 协议 1）；B 使用 `mcai_windows_host-<版本>.zip`（附带可选 Probe 0.6.0），A 使用 `astrbot_plugin_mcai.zip`。从源码构建见[开发指南](../development/README.md#构建与发行)。

### 软件与版本

| 位置 | 需要准备的环境 | 如何确认 |
|---|---|---|
| A | Windows 本机运行的 AstrBot，**最低 v4.29.4**；Python **3.12+** | 在 AstrBot 管理界面或启动日志查看版本；插件依赖安装到 AstrBot 自己使用的 Python 环境 |
| A | 已连接 QQ 的消息适配器，支持引用消息和主动发消息 | 先确认 Bot 能收到群消息并能在该群回复；创建任务需能取得被引用消息文字 |
| A | 支持 OpenAI 兼容 Chat／Responses 的排障模型与审核模型 API，排障模型须支持工具调用 | 在 AstrBot 模型页配置，之后用插件设置页测试；两者可使用同一提供商，审核独立请求 |
| A | PowerShell **7.3+ 的 7.x** | 插件启动时检查 A 本机 PowerShell；需能自动找到，或在 A 配置填写完整路径 |
| A（仅 MOD 源码修复） | 构建该 MOD 所需的 JDK | [试玩与发布](operations.md#mod-试服试玩与正式发布)使用 A 构建制品 |
| B | Windows **10 1809 或更新版本／Windows 11**，建议 x64；Python **3.12+** | 在 Windows“设置 → 系统 → 关于”查看版本和系统类型，再执行下方 Python 检查 |
| B | PowerShell **7.3+ 的 7.x** | 执行 `$PSVersionTable.PSVersion`；程序是 `pwsh.exe`，Windows 自带 PowerShell 5.1 不符合要求 |
| B | 存档辅助工具使用的 Java **21+** 运行环境 | 执行所选 `java.exe -version`；安装发行包只需运行 JAR，无需自行编译 |
| 各 MC 服务端 | 原来能够正常启动的 **Minecraft Java 版服务端**、对应 Java 和 `start.bat` | Java 版本按该 MC／整合包要求，先人工启动并确认玩家可以进入 |

AstrBot 的安装版本声明为 `>=4.29.4`，不设最高版本（当前集成验证基线为 v4.29.4；使用更新版时先完成连接与模型能力测试）。

A、B 可以共用一台 Windows 电脑，也可以分开部署。B 的托管窗口依赖 Windows ConPTY，Linux、WSL 或 Linux Docker 容器不能运行该托管流程。A 的基础排障不需要 B 的 PowerShell、存档 Java 或服务端环境；B 不需要安装 AstrBot。

**两套 Java 要分开理解：** `host.json` 的 `world_tools.java_path` 指向 Java 21+，供存档辅助工具使用；MC 仍使用原 `start.bat` 或实例配置指定的 Java（例如原整合包要求 Java 17，就保留它，同时另装 Java 21 给存档工具）。配置时分别写完整路径，多套 Java 可以共存。

### 内存、磁盘与运行账号

- **内存：** 按“MC 最大堆内存 + Windows／AstrBot 等程序 + 辅助操作余量”安排。B 默认让全部辅助操作共享最多 **8 GiB**（按需上限，非预占），MC 服务端不计入该额度；整机余量不足时可下调 `operations_memory_limit_mib`。
- **磁盘：** B 数据目录需容纳下载暂存、操作记录及每次修复的完整备份；涉及整个存档目录时预留至少一份存档副本的空间，维护方式见[数据与备份](operations.md#数据与备份)。
- **账号与权限：** 运行 B 的 Windows 账号需能读写服务端目录、B 配置与数据目录并启动 Java／PowerShell；B 与各托管窗口使用同一 Windows 用户。A 运行账号需能写 AstrBot 插件数据目录。
- **模型算力：** 使用远程模型 API 时无需本地显卡；若本地部署模型，显存和内存按模型服务要求另行准备。

### 网络条件

| 从哪里访问 | 必须能访问什么 | 什么时候使用 |
|---|---|---|
| A → QQ 适配器／平台、模型服务 | 正常的消息连接和已配置的模型 API | 收发群消息、排障和独立审核 |
| A → B | B 的 HTTPS 地址和 TCP 端口，默认 `18765` | 控制程序和查询结果；跨网络时配置可达地址与端口映射 |
| A、B → Python 包源 | 安装所需依赖的包源或可用镜像 | 首次安装和更新依赖 |
| A → 网页／独立搜索 API | 所查询的网页或已配置的搜索服务 | 启用相应查询功能时 |
| A → Modrinth／CurseForge 及下载站 | 对应 API 和下载地址 | 搜索或下载 MOD 时；CurseForge API Key 填在 A 插件设置 |

同机部署时 A 使用本机地址即可，不需要为 A→B 连接配置公网入口。需要代理时分别按[代理说明](configuration.md#下载代理与-https)配置。

### 检查基础软件

可从 [Python Windows 下载页](https://www.python.org/downloads/windows/)、[PowerShell Windows 安装说明](https://learn.microsoft.com/powershell/scripting/install/installing-powershell-on-windows)、[Temurin Java 下载页](https://adoptium.net/temurin/releases/?version=21)准备环境。在开始菜单打开 **PowerShell 7** 执行：

```powershell
$PSVersionTable.PSVersion
py -3.12 --version
& 'C:\Program Files\Java\jdk-21\bin\java.exe' -version
```

应分别看到 PowerShell 7.3+ 的 7.x、Python 3.12+ 和 Java 21+（如已装更高版 Python 3.x 可对应替换 `py -3.12` 或使用完整 `python.exe` 路径）。A 的 Python 与 B 的 `.venv` 各自独立，先确认基础软件到位再继续。

---

## 二、在 B 机器安装并连接服务端

### 1. 解压并安装主机程序

将 `mcai_windows_host-<版本>.zip` 解压到例如 `D:\MCAI`，确认目录内直接存在 `pyproject.toml`。在 PowerShell 7 中执行：

```powershell
Set-Location -LiteralPath 'D:\MCAI'
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
Copy-Item -LiteralPath '.\host.example.json' -Destination '.\host.json'
Copy-Item -LiteralPath '.\instances.example.json' -Destination '.\instances.json'
```

安装成功后 `D:\MCAI\.venv\Scripts\` 中应有 `python.exe` 和 `mcai.exe`。后两条复制命令仅在**首次安装**时执行，升级时保留原有配置。后续命令均使用 `.venv` 内完整路径，不需要激活环境或加入 PATH。

### 2. 填写 B 的基础配置

打开 `D:\MCAI\host.json`（如 `notepad .\host.json`）按实际情况修改：

```json
{
  "listen": "0.0.0.0",
  "port": 18765,
  "tls": true,
  "token": "这里换成你自己生成的一串令牌",
  "data_dir": "runtime/host",
  "instances_file": "instances.json",
  "powershell_path": "C:/Program Files/PowerShell/7/pwsh.exe",
  "world_tools": {
    "java_path": "C:/Program Files/Java/jdk-21/bin/java.exe"
  },
  "operations_memory_limit_mib": 8192
}
```

| 字段 | 第一次应该怎样填 |
|---|---|
| `listen` | 使用 `0.0.0.0`，让 B 接受本机及其他机器连接 |
| `port` | 默认 `18765`，是 A 连接 B 的端口，与 MC 游戏端口分开 |
| `token` | 自己生成的一串共享令牌，稍后原样填到 A，与模型 API Key 分开 |
| `powershell_path` | PowerShell 7 的 `pwsh.exe` 完整路径；留空时自动查找 |
| `world_tools.java_path` | Java 21+ 的 `java.exe` 完整路径，供存档辅助工具使用 |
| `data_dir` | 保存备份、证书与操作记录，不要放进 MC 存档目录 |
| `operations_memory_limit_mib` | 默认 `8192` MiB，全部辅助操作共享，MC 服务端不计入 |

生成随机令牌可执行：

```powershell
.\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(32))"
```

JSON 路径建议写 `/`（写反斜杠需转义为 `\\`），不加注释，注意记事本不要保存成 `host.json.txt`。

### 3. 登记 MC 服务端

打开 `D:\MCAI\instances.json`，将示例目录改为真实服务端目录：

```json
{
  "cti": {
    "directory": "D:/MC/CTI",
    "description": "CTI整合包服，群里也叫CTI服、匠魂服，主城在主世界"
  }
}
```

- `cti`：配置 ID（字母、数字、下划线或短横线），供本机命令使用。
- `directory`：包含 `start.bat` 的服务端根目录（不是 `world`、`mods` 或 B 目录）。
- `description`：给 AI 识别目标用，填整合包名、群内简称等真实区分信息。

多服务端在同一个 JSON 对象里继续加项即可，详见[B 服务端文件](configuration.md#b服务端文件)，后续也可在 A 设置页添加。

### 4. 核对原来的 start.bat

保留原有启动参数、对应 Java、整合包脚本和自动重启循环。若 BAT 有自动重启循环，在 **Java 退出之后、下一次启动之前**输出退出提示并保留倒计时：

```bat
echo Start server in 10 seconds. Press ctrl+c to stop right now.
timeout /t 10 /nobreak
```

这行提示让托管窗口确认“本次 Java 已退出、可以中断自动重启”。Java 须在 BAT 中前台运行，不要用 `start` 另开脱离当前窗口的进程；原本无循环的 BAT 可直接使用。主动停服参数详见[停服与启动参数](configuration.md#b服务端文件)。

### 5. 启动 B，保存连接信息

在 B 的 PowerShell 7 窗口执行：

```powershell
Set-Location -LiteralPath 'D:\MCAI'
.\.venv\Scripts\python.exe -m mcai host
```

窗口标题会变为 `MCAI-HOST`，首次启动自动生成证书并输出 `HTTPS 监听` 与 64 位十六进制 `证书 SHA-256 指纹`。**保持此窗口运行**并保存证书指纹。B 的管理界面在 A 插件设置页内，无需在浏览器打开这个 HTTPS 地址。

| 部署方式 | A 的“B 地址”示例 | 网络上需要做什么 |
|---|---|---|
| 同一台 Windows 机器 | `https://127.0.0.1:18765` | 使用本机地址，仍填写指纹 |
| 同一个局域网 | `https://192.168.1.20:18765` | 换成 B 局域网 IP，防火墙放行该 TCP 端口 |
| 跨公网连接 | `https://你的公网IP:28765` | 将外部 TCP 映射到 B 的 `18765`，A 填外部端口；云主机同步放行入站规则 |

只开放 MC 游戏端口 `25565` 不能让 A 连上 B，详见[下载、代理与 HTTPS](configuration.md#下载代理与-https)。

### 6. 为每个服务端打开独立托管窗口

在 B 机器**另开一个 PowerShell 7 窗口**（同一 Windows 用户），执行：

```powershell
& 'D:\MCAI\.venv\Scripts\mcai.exe' tm -C 'D:\MC\CTI'
```

窗口标题会变为 `MCAI - cti`，看到托管提示符 `PS D:\MC\CTI>` 后，在**该窗口内**执行：

```powershell
.\start.bat
```

确认服务端正常启动且玩家可进服。若 MC 原来跑在普通窗口中，需先正常停服再从托管窗口启动（`tm` 不会接管其他窗口里已运行的进程）。第二个服务端另开一个 `tm` 窗口即可。

**窗口关系：** B 退出或重启时，托管窗口和 MC 照常运行并自动重连；关闭托管窗口会影响对应服务端，不要用直接关窗代替停服。

### 7. 本机检查一次

另开一个 PowerShell 7 窗口检查状态：

```powershell
Set-Location -LiteralPath 'D:\MCAI'
.\.venv\Scripts\mcai.exe list
.\.venv\Scripts\mcai.exe status cti
```

确认 `list` 包含 `cti`，且 `status` 中 `window_online: true`、`running: true`、`state_unknown: false`（尚未运行 `start.bat` 时 `running: false` 属正常）。若 `window_online: false`，先核对 B 和 `tm` 窗口再配 A。

---

## 三、在 A 机器安装并配置插件

### 1. 安装插件并打开设置页

在 AstrBot **插件管理页**上传同版本 `astrbot_plugin_mcai.zip`（或通过[插件仓库](https://github.com/KNaiFen/astrbot_plugin_mcai)安装），等待安装依赖并启用插件，打开 **“MC 排障助手”（`astrbot_plugin_mcai`）** 的设置视图（标题“MCAI 设置”）。

若安装依赖出现 `WinError 5` 并指向 `charset_normalizer` 或 `__mypyc*.pyd`，按[安装依赖时拒绝访问](operations.md#安装依赖时拒绝访问)完全退出 AstrBot 后预装依赖再重试。

### 2. 填写并测试 B 连接

在“**主机连接**”区填写：

| 界面字段 | 对应内容 |
|---|---|
| B 地址 | 完整 `https://IP或域名:端口`（如 `https://127.0.0.1:18765`，避免需跳转的地址） |
| 共享令牌 | `host.json` 中 `token` 的值（不含引号） |
| 证书 SHA-256 指纹 | B 启动时显示的指纹（可含冒号或空格，不含提示文字） |

点击“**测试连接**”看到成功提示后，点击“**保存 A 设置**”。

### 3. 选择排障模型与审核模型

先在 AstrBot 模型提供商页配置好 API 地址、Key 与模型，再回到“MCAI 设置 → **模型与能力**”：

1. **排障模型**：选择 OpenAI 兼容 Chat／Responses 提供商（AstrBot 原生 Gemini 等其他适配器不支持完整工具结构会被拒绝）。
2. **审核模型**：必填，选择 OpenAI 兼容 Chat／Responses 提供商（可与排障模型共用提供商，审核仍独立发起请求）。
3. **思考强度**：不确定时留空以继承提供商设置，仅填该模型支持的档位。
4. **上下文容量**：在 AstrBot 提供商中按实际容量填写 `max_context_tokens`（未填或为 0 时默认按 272000 估算，详见[上下文与群消息范围](configuration.md#上下文与群消息范围)）。
5. 点击“**保存并测试、自动配置**”，确认普通对话、工具调用与续接、图片识别、审核模型与 JSON 均通过（会产生少量 API 费用，不操作 MC 也不发群消息）。搜索和执行进度汇报为可选项，见[模型、搜索与能力测试](configuration.md#模型搜索与能力测试)。

### 4. 配置管理员、允许群与服务端同步

在“**群与通知**”区填写“管理员 QQ”（每行一个，AstrBot 管理员同样具备权限）与“允许群号”（留空允许所有群），点击“**保存 A 设置**”。

再到“**服务端配置**”页点击“**刷新 B 配置**”，确认能看到 `cti`。若以后在此新增或修改目录／Java／编码，对应实例需停服并重开托管窗口；修改 B 的 PowerShell 路径或辅助内存额度需重启 B，详见[热重载](configuration.md#热重载)。

最后在允许群发送 `/mcaihelp`（若修改过 AstrBot 唤醒前缀请换用对应前缀，或 @Bot 后发 `mcaihelp`），确认收到帮助回复。

---

## 四、在群里走通第一次排障

1. **只读查询（不建任务、不占用实例）**：发 `/mcaiserver` 或 `/mcaiserver cti` 查实时状态；或发 `/mcaiask cti服为什么 TPS 降低了？` 做一次只读 AI 问答（默认仅管理员可用，敏感信息自动脱敏）。
2. **创建任务（管理员）**：发 `/mcainew 主城卡顿 是CTI服，昨天更新模组后开始卡，玩家Steve在主城附近复现`，或直接引用玩家的问题消息后发 `/mcainew 主城卡顿`。日常运维（如发维护公告、改配置）同样走 `/mcainew`。任务名不带空格，最多 40 字；一任务绑定一台服。
3. **补充线索（群成员皆可）**：发 `/mcaisay 主城卡顿 我的游戏名是 Steve，主世界坐标 120 65 -300`；也可附带或引用日志、压缩包、截图，详见[群文件和图片](operations.md#群文件和图片)。普通群聊不会进入任务；如需屏蔽普通成员补充，管理员可用 `/mcaisaymode 主城卡顿 false`（详见[任务、批准与停止](operations.md#任务批准与停止)）。
4. **查看方案与短码批准（管理员）**：涉及修改、启停或维护命令时，AI 会先过独立审核并把简洁待批卡片发到群里（随时可用 `/mcaiplan 主城卡顿` 重看）。核对无误后发送卡片给出的短码批准命令，例如 `/mcaiapply 主城卡顿 9F2A7C`。不同意时不要批准，直接用 `/mcaisay` 提出调整意见。
5. **复核与验收（管理员）**：修复完成后先补充实际复现结果（涉及 MOD 源码修复的按[试服试玩与发布](operations.md#mod-试服试玩与正式发布)验证），确认没问题再发 `/mcaidone 主城卡顿` 结案，释放实例占用并在后台归档经验文档。
6. **暂停、续接或中止**：临时等待复现用 `/mcaipause 主城卡顿`，恢复用 `/mcairesume 主城卡顿`，放弃任务用 `/mcaistop 主城卡顿`。重试策略、断线恢复与发件箱排障见[断线和修复失败](operations.md#断线和修复失败)。

---

## 五、可选探针、日常开机与常见安装问题

- **可选服内诊断 Probe**：提供玩家现场、维度 TPS/MSPT、已加载对象普查与短时热点，无需客户端安装。停服后从 B 包 `probe/` 选对应版本与加载器的**一个 JAR** 放进 `mods/`，重启看到 `MCAI Probe 0.6.0 ready` 即可，详见[Probe 安装与使用](probe.md#安装)。
- **下次开机顺序**：先启动 B（`.\.venv\Scripts\python.exe -m mcai host`），再为每台服开托管窗口（`mcai.exe tm -C ...`）并运行 `.\start.bat`，A 端照常启动 AstrBot。详见[多窗口管理服务端](operations.md#多窗口管理服务端)。
- **自定义运行时规则与备份**：自定义规则在「MCAI 设置 → 运行时规则」维护，升级不会覆盖原规则（见[运行时规则](configuration.md#运行时规则)）；修复备份默认保存在 `data_dir/backups/操作编号/`（见[数据与备份](operations.md#数据与备份)）；版本升级见[升级步骤](operations.md#升级步骤)。

### 常见部署问题

| 现象 | 按什么顺序检查 |
|---|---|
| 找不到 `mcai` 命令 | 使用 `.venv\Scripts\mcai.exe` 完整路径，确认 `pip install -e .` 已成功 |
| 提示 PowerShell 版本不对 | 打开 PowerShell 7，核对 `$PSVersionTable.PSVersion` 及 `host.json` 的 `powershell_path` |
| 启动时目录／配置文件不存在 | 核对解压层级、当前目录、文件扩展名及 JSON 路径；B 从安装目录启动 |
| 提示找不到 B 配置位置 | 先在同一 Windows 用户下成功启动一次 B，再打开托管窗口 |
| A 测试连接失败 | 确认 B 正在运行；核对实际地址、端口、令牌和证书指纹 |
| 有服务端配置但显示无托管连接 | 确认 `tm -C` 目录正确；普通窗口中已运行的 MC 不会被自动接管 |
| AI 没看到刚发的解释 | 用 `/mcaisay 任务名 内容` 补充；暂停状态下需管理员 `/mcairesume` 续接 |

模型、下载、停服与依赖权限等其他问题见[运行维护常见问题](operations.md#其他常见问题)。
