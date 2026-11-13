# MC 群内排障助手

在 QQ 群里排查 Minecraft Java 服务端问题：管理员引用玩家的反馈创建任务，AI 识别服务端、查看日志和存档、联网查资料并提出修复方案。管理员批准后执行，文件修改前备份；验收后自动记录经验，供下次排查使用。

两端分别运行：**A：AstrBot 插件 → HTTPS → B：MC 控制程序 → 多个服务端**。A 无需公网入口，B 映射一个 TCP 端口。两端也可以放在同一台 Windows 机器上。

## 安装

准备以下环境：

| 位置 | 要求 |
|---|---|
| A：QQ Bot | Windows、AstrBot v4.29.4、支持工具调用的模型 API；QQ 适配器支持引用消息和主动发消息 |
| B：MC 主机 | Windows 10 1809+、Python 3.12+、PowerShell 7.3+；存档工具使用 Java 21+ |

各 MC 实例可使用不同 Java 版本。中间层、启动器和 Agent 脚本统一使用 PowerShell 7；模型能力可在插件设置页测试。

### 1. 配置 B

从 [Releases](https://github.com/KNaiFen/astrbot_plugin_mcai/releases/latest) 下载并解压 `mcai_windows_host.zip`，在其目录打开 PowerShell：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
Copy-Item -LiteralPath host.example.json -Destination host.json
Copy-Item -LiteralPath instances.example.json -Destination instances.json
```

编辑 `host.json`，设置自己的共享令牌和存档工具 Java 路径：

```json
{
  "listen": "0.0.0.0",
  "port": 18765,
  "tls": true,
  "token": "替换成你自己的共享令牌",
  "data_dir": "runtime/host",
  "instances_file": "instances.json",
  "powershell_path": "",
  "world_tools": {"java_path": "D:/Java/jdk-21/bin/java.exe"},
  "curseforge_api_key": ""
}
```

服务端单独填在 `instances.json`，只需要 BAT 完整路径和说明：

```json
{
  "ncraft": {
    "description": "NCraft，也叫自制服、奶粉自制服",
    "command": "D:/MC/NCraft/start.bat"
  }
}
```

程序自动在 BAT 父目录执行 `./start.bat`。服务端列表可在运行时修改，也可稍后在 A 的图形界面增删。

**保留 BAT 自动重启循环。** Java 应前台运行；每次退出后、重新启动前输出下面这行，并保留倒计时：

```bat
echo Start server in 10 seconds. Press ctrl+c to stop right now.
timeout /t 10 /nobreak
```

主动停服先发送 MC 的 `stop`，收到本次退出提示后只发送一次 Ctrl+C，必要时确认终止批处理。之后重新启动仍保留自动重启。已有手动窗口需先正常停服，再用本程序启动。

启动控制程序：

```powershell
.\.venv\Scripts\python.exe -m mcai host
```

首次启动生成并保存 HTTPS 证书，复制界面显示的 **SHA-256 指纹**。将 B 的 TCP `18765` 放行并映射到公网端口，控制程序窗口保持运行。

### 2. 配置 A

在 AstrBot 的插件管理页选择通过链接安装，填写：

```text
https://github.com/KNaiFen/astrbot_plugin_mcai
```

安装并启用后，打开插件的 **设置视图**。后续在插件管理页更新；也可从 [Releases](https://github.com/KNaiFen/astrbot_plugin_mcai/releases/latest) 下载插件 ZIP 手动安装。

- 填写 B 的 `https://公网IP:映射端口`、共享令牌和证书指纹，点击测试连接。
- 先在 AstrBot 模型页配置 API，再选择排障模型与审核模型，可分别设置思考强度。
- 填写管理员 QQ（支持多人）及允许群号，保存。
- 点击“保存并测试、自动配置”，验证对话、工具、两种搜索和摘要；也可手动切换功能。
- 服务端列表、CurseForge 密钥及主机路径同样在此管理。

审核模型必须选择，支持 OpenAI 兼容 Chat／Responses，可与主模型相同。同机地址填 `https://127.0.0.1:18765`，仍填写指纹。详细选项见[配置说明](docs/usage/configuration.md)。

## 群内使用

可选安装 **MCAI Probe**：从 B 包 `probe/` 选取对应 MC 版本和加载器的 JAR 放入服务端 `mods/`，正常重启。支持 1.20.1、1.21.1 的 Forge／Fabric，提供玩家位置、维度耗时和实体热点；客户端无需安装。详见[探针使用](docs/usage/probe.md)。

管理员**回复一条玩家的问题消息**，输入 `/mcainew 主城卡顿`。AI 根据引用、服务端目录和反馈识别目标，不确定时会追问。之后使用：

| 指令 | 用途 |
|---|---|
| `/mcaisay 主城卡顿 是CTI服，靠近基地就卡` | 补充线索，玩家也可使用 |
| `/mcaistatus 主城卡顿` | 查看任务状态 |
| `/mcailist` | 查看本群活动任务，支持页码 |
| `/mcaiplan 主城卡顿` | 查看当前待批准方案 |
| `/mcaiapply 主城卡顿` | 管理员批准当前修复方案 |
| `/mcairesume 主城卡顿` | 管理员续接已暂停任务 |
| `/mcaipause 主城卡顿` | 管理员保存进度并暂停 |
| `/mcaistop 主城卡顿` | 管理员中止任务 |
| `/mcaidone 主城卡顿` | 管理员验收并结束，后台归档经验 |
| `/mcaihelp` | 查看帮助 |

任务名不带空格；一个任务处理一个服务端，同一服务端只允许一个活动任务。普通闲聊不会进入上下文。

- 诊断命令、诊断脚本和修复方案先经独立 AI 审核；修复方案还需要管理员批准。文件修改先停服和备份，在线控制台修复无法备份时会在确认消息里说明。
- MOD 和其他文件先下载到 B 的暂存目录，安装再批准。CurseForge 需在 B 配置 `curseforge_api_key`，Modrinth 公开下载无需令牌。
- 模型服务连续失败会保存并暂停，`/mcaisay` 仍能补充信息，使用 `/mcairesume` 继续。修复失败后 AI 检查现场，有新方案就再次请求批准，无方向则暂停。
- 两端断网时 B 上的服务端和后台工作继续运行。停止任务会取消所属诊断与下载，文件修复在当前安全步骤结束后停止。

首次启用会在 `AstrBot/data/plugin_data/astrbot_plugin_mcai/AGENTS.md` 生成可编辑的生产操作规则。通用脚本以 B 的运行账号权限执行，AI 审核不能代替系统文件权限。

## 本机管理与资料

在 B 另开 PWSH 窗口：

```powershell
.\.venv\Scripts\python.exe -m mcai list
.\.venv\Scripts\python.exe -m mcai start ncraft
.\.venv\Scripts\python.exe -m mcai attach ncraft
```

`attach` 后可直接输入 MC 命令，`/detach` 只断开控制台。其他实例分别开窗口管理。启停、备份恢复、故障处理和升级方法见[运行维护](docs/usage/operations.md)。

[文档总索引](docs/README.md) · [配置](docs/usage/configuration.md) · [运行维护](docs/usage/operations.md) · [开发](docs/development/README.md)

本仓库为 AstrBot 插件安装与更新入口；B 程序、Probe 和完整源码见 Releases。插件与主机代码采用 [MIT](LICENSE)，Probe 及第三方组件保留各自许可，见[来源说明](docs/development/third-party.md)。
