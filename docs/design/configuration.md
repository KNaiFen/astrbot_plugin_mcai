# 配置、终端与能力测试

[设计索引](README.md) · [用户配置](../usage/configuration.md)

## 终端与停服

所有 Windows shell 入口共用启动时验证的 PowerShell 7.3+ 路径。实例只配置 BAT 文件，父目录决定身份与 cwd；固定生成的 PS1 负责代码页、Ctrl+C 状态和调用边界，模型不提供终端启动字符串。

Console 的一次性停服状态记录实例、PID、启动监听时间和阶段。发出 stop 前落盘，收到新输出才累积匹配；VT 控制序列只在匹配视图去除，原文继续存储。完整重启提示匹配后落盘，再发一次 Ctrl+C；中文／英文批处理确认单次回复 Y。已退出、取消和超时撤销监听，网络重试由原 operation 去重。文件修复等待启动器与已有子进程退出后才备份。超时不强杀，不执行文件变更。

启动器同时清除继承的 Ctrl+C 忽略标志并启用 processed console input；本地验证表明只往未初始化的 ConPTY 写 `\x03` 可能被忽略。未启用停服监听时，不处理重启提示，BAT 正常循环。

## 配置生命周期

`host.json` 保存基础配置和密钥，`instances.json` 独立维护实例。加载边界校验 BAT、目录重复、Java、超时和编码；轮询比较内容哈希，校验成功才替换 desired 状态。活动实例维持旧启动配置，说明单独更新；空闲后切换或移除。operation 与 background_job 均纳入忙状态。目录变化由既有 expected_directory 检查拒绝旧任务的新操作。

`GET/PUT /configuration` 复用现有 HTTPS、令牌与指纹；只返回密钥是否配置，不回传原值。实例保存携带 revision 防止覆盖其他编辑。`POST /configuration/reload` 立即重载；CurseForge 只读测试使用独立接口。主机路径配置保存后重启生效。无额外端口和传输层。

## AstrBot 视图与模型测试

`views/settings` 通过 AstrBot v4.29.4 原生 bridge 的 apiGet/apiPost 调用插件注册接口，复用 Dashboard 管理员登录。A 的配置继续以 AstrBotConfig 保存，B 的配置经现有 HostClient 写入。主审模型分别覆盖请求配置，不改共享提供商。

能力测试使用无生产工具的独立对话；测试结果写本地，按 provider/model/config/settings 哈希识别过期。短对话、流式、回显调用续接、原生搜索、alpha/search、明确摘要和审核 JSON 分别记录。支持／未观察到／临时失败分开；只根据已验证事实自动配置，不因网络故障清空有效设置。

原生搜索以 [OpenAI 文档](https://developers.openai.com/api/docs/guides/tools-web-search) 为准。独立搜索固定参考 [Codex 553c764 的 SearchRequest](https://github.com/openai/codex/blob/553c764e8b99fa519e9c6eb9b657875ef0f5e1c1/codex-rs/codex-api/src/search.rs)，调用 provider-relative `alpha/search`，只实现排障使用的 search/open/find。保留任务搜索会话、可读 output 和结构化来源；不把 encrypted_output 放进主模型上下文。
