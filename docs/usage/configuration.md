# 配置说明

[使用索引](README.md) · [运行维护](operations.md)

## A：AstrBot 插件

推荐打开插件详情的 **设置视图**：连接测试、模型选择、能力测试、多人权限、B 的服务端和 CurseForge 密钥集中在这里。普通插件配置页同样支持 `_conf_schema.json` 中的字段。

模型的 API 地址、密钥和模型名称先在 **AstrBot 模型提供商页**配置。插件下拉选择该提供商，显示名称、ID、模型和接口类型。提供商 ID 不是模型名或 API Key。

| 字段 | 默认值 | 用途 |
|---|---|---|
| `host_url` | `https://127.0.0.1:18765` | B 最终控制地址，公网 IP 加映射端口即可 |
| `host_token` | 必填 | B 的共享令牌，设置视图留空保留原值 |
| `host_fingerprint` | 空 | B 证书的 SHA-256 指纹，自签名 HTTPS 直连时填写 |
| `provider_id` | 空 | 排障提供商；留空使用当前群配置，一键测试需明确选择 |
| `reasoning_effort` | 空 | 排障思考强度；留空继承，支持服务商接受的自定义值 |
| `review_provider_id` | 空，必须选择 | 独立审核模型，支持 OpenAI 兼容 Chat／Responses |
| `review_reasoning_effort` | 空 | 审核思考强度，留空继承审核提供商 |
| `model_max_attempts` | `3` | 同一模型步骤尝试次数，排障与审核分别计数 |
| `max_steps` | `40` | 每轮 Agent 最多模型步骤 |
| `forward_reasoning_summary` | `true` | 转发主模型明确提供的 Responses 摘要段落 |
| `enable_web_search` | `true` | Responses 托管搜索 |
| `web_search_tool_type` | `web_search` | 可选兼容格式 `web_search_preview` |
| `enable_alpha_search` | `false` | 独立 `alpha/search` 搜索，Chat／Responses 均可测试 |
| `admin_ids` | `[]` | 可管理任务的 QQ 号；AstrBot 自身管理员同样可操作 |
| `group_ids` | `[]` | 允许的群号；留空允许所有群 |

QQ 和群号建议填字符串。多位管理员权限相同，可以交叉创建、批准、暂停、续接和结束任务。玩家可补充线索、查看状态和列表；普通闲聊不进入任务。

### 模型、搜索与能力测试

主模型必须支持工具调用。主模型与审核模型可相同，审核使用独立无工具对话。思考强度可以填 `low/medium/high/xhigh` 等模型支持的值，只覆盖对应请求，不修改共享提供商配置。

两种搜索可分别开关、同时使用：

- 托管搜索：Responses 请求的 `tools` 加入 `web_search`，保留 MC 函数工具。服务商明确不支持时本轮关闭该功能，临时连接错误仍按有限重试处理。
- 独立搜索：`mc_search` 通过提供商基础地址追加 `alpha/search`，例如 `https://example.com/v1/alpha/search`。按 Codex 协议提供搜索、打开来源、页内查找，复用提供商鉴权、代理和请求头。任务内引用持久化。只有加密数据、没有可读 `output` 时明确返回不可用。

`mc_web` 继续用于直接获取已知 URL 的正文，网页内容属于外部资料。

“保存并测试、自动配置”执行短对话、流式响应、无副作用回显函数及续接、各一次搜索、来源打开／查找、摘要事件、审核 JSON。不会操作 MC 或发送群消息。结果区分验证通过、明确不支持、本次未观察到和请求失败。验证通过后开启对应功能；托管搜索明确不支持再尝试 preview；临时失败保留此前配置，未观察到摘要不直接判定不支持。修改提供商、模型或思考强度后需重测。测试会产生少量模型及搜索费用。

摘要只转发原始 API 的明确摘要事件，长段分开发送。普通推理字段和审核内容不转发；服务商没有摘要时仍发送必要提问、方案和结论。

保存 A 连接／模型配置时需等待当前轮结束或先暂停任务，避免替换执行中的连接。

### 运行时规则

首次启用将 `mcai/agent_rules.md` 复制到 `AstrBot/data/plugin_data/astrbot_plugin_mcai/AGENTS.md`。用户可编辑，升级保留修改。每轮及续接读取，同一规则用于排障和审核；源码根的开发规则不控制运行中的 Bot。旧规则迁移后建议补入 PowerShell 7 和循环 BAT 的说明。

## B：基础设置

从 `host.example.json` 复制为 `host.json`：

| 字段 | 默认值 | 用途 |
|---|---|---|
| `listen` | 缺省 `127.0.0.1`，示例 `0.0.0.0` | 监听地址 |
| `port` | `18765` | 本机端口，公网映射可用不同端口 |
| `tls` | `true` | 固定使用内置 HTTPS，不能关闭 |
| `token` | 必填 | 共享令牌，不能保留示例占位值 |
| `data_dir` | `runtime/host` | 状态、证书、输出、备份和下载 |
| `instances_file` | `instances.json` | 独立服务端文件，可热重载 |
| `powershell_path` | 空 | PowerShell 7 的完整路径，空时系统查找 |
| `world_tools.java_path` | 空 | 存档辅助程序 Java 21+，空时 PATH 查找 |
| `curseforge_api_key` | 空 | CurseForge API 与官方 CDN 凭据 |
| `download_max_bytes` | `2147483648` | 单个下载上限，默认 2 GiB |

基础相对路径以 `host.json` 所在目录解析。PowerShell 必须是 **7.3+ 的 7.x**；中间层、固定启动器、在线诊断和修复脚本共用，缺失或版本不符明确失败，不回退 Windows PowerShell 5.1。路径可包含中文与空格。

图形界面可更新 PowerShell 和存档 Java，保存后重启 B 生效。监听地址、端口、令牌和证书仍在 B 本地配置。数据目录不要放入将要整体备份的实例范围。

## B：服务端文件

从 `instances.example.json` 复制为 `instances.json`，或在设置视图增删：

```json
{
  "cti": {
    "description": "CTI 0.4.6，群里叫匠魂服",
    "command": "D:/MC/CTI_0.4.6/start.bat"
  },
  "zombie": {
    "description": "已故的工艺，群里叫僵尸服",
    "command": "D:/MC/DeceasedCraft_Server_CB_5.11.18/run.bat",
    "java_path": "D:/Java/jdk-17/bin/java.exe"
  }
}
```

`command` 只填写存在的 BAT 文件，工作目录取父目录，固定 PowerShell 7 启动器在其中执行 `./start.bat`。JSON 使用 `/` 或转义后的 `\\`；图形界面直接粘贴 Windows 路径。实例名使用字母、数字、下划线和短横线。

| 实例高级字段 | 默认值 | 用途 |
|---|---|---|
| `java_path` | 空 | 给实例和诊断设置 `JAVA_HOME`、PATH、`MCAI_JAVA`；空时继承 |
| `encoding` | `auto` | BAT 初始代码页，可填 `utf-8`、`gbk` 或 Windows `cp` 编号 |
| `stop_command` | `stop` | MC 正常停服命令 |
| `stop_timeout` | `120` | 等待正常停服的秒数，最多 3600 |
| `restart_prompt` | `Start server in 10 seconds. Press ctrl+c to stop right now.` | 退出后、自动重启前的完整提示 |

BAT 的自动重启循环保留。主动停服监听本次新输出，收到约定提示后只发一次 Ctrl+C，并处理批处理终止确认。正常退出、不循环的 BAT 同样可用。超时不会强杀，也不会继续文件修复。

自动编码按 BOM、有效 UTF-8、系统 ANSI 选择初始代码页，ConPTY 的 Unicode 输出直接保留。BAT 后续 `chcp` 由终端处理；日志查询编码独立设置。CMD 不支持的 UTF-16/32 BAT 明确拒绝，不改写原文件。

`java_path` 不覆盖 BAT 写死的绝对 Java 路径。希望配置生效可改用 `java` 或 `"%MCAI_JAVA%"`。存档辅助程序使用独立 Java 21，不改变服务端版本。

### 热重载

实例文件约每秒检查，也可 `mcai reload`。新增立即可见，不自动启动；说明立即更新。运行或执行操作中的启动配置延期，空闲后应用；删除先标记待移除，保留现有控制并阻止新绑定。错误配置保留上一份有效值，界面及日志显示错误。图形保存检查文件版本，发现其他修改时要求刷新。

规范化绝对目录用于实例身份与经验归档，统一 Windows 大小写和分隔符。目录变化后旧任务的新操作明确停止，已提交操作仍按原编号查询。启动 BAT 或已审核脚本变化后需重新提案。

## 下载、代理与 HTTPS

Modrinth 公开 API 无需令牌。CurseForge 在设置视图“下载与主机”填写，密钥保存在 B 的 `host.json`，仅返回已配置状态；支持替换、清空和官方只读接口测试，热更新。密钥不提供给模型。分发受限或无官方下载地址时明确失败。

A 网页获取、B 外部 API 与下载支持 `HTTP_PROXY`、`HTTPS_PROXY` 等环境变量；模型请求和独立搜索沿用 AstrBot 提供商代理。托管搜索的出站网络由服务商控制。

B 首次开启 TLS 在 `data_dir/tls` 生成证书并持续复用。指纹支持大小写、冒号和空格分隔。本机 CLI 自动读取配置和证书，连接本机 HTTPS。公网 IP 变化只更新 A 的地址，证书未变则指纹不变。更多见[运行维护](operations.md)。
