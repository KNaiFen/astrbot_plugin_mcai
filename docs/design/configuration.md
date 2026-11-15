# 配置、终端与能力测试

[设计索引](README.md) · [用户配置](../usage/configuration.md)

## 终端与停服

所有Windows shell入口使用PowerShell 7.3+。实例配置目录，用户通过 `mcai tm` 创建独立交互终端，在其中运行固定的start.bat。B通过本机WebSocket连接，进程所有权和共享资源详见[托管终端与辅助资源](terminal-and-resources.md)。

一次性停服状态保存在窗口：发出stop前落盘，监听之后的新输出；收到重启提示后保存阶段并发一次Ctrl+C，中英文批处理确认单次回复Y。退出、取消及超时撤销监听。文件修复必须确认BAT链和Java退出，PowerShell窗口保留。断线不取消已接受的控制，原编号返回原结果。

固定初始化脚本设置初始代码页和Ctrl+C状态，提示符回报当前目录，ConPTY输出保留Unicode。B与窗口退出分开处理，不再由B清理所有服务端进程。

## 配置生命周期

`host.json` 保存基础配置和密钥，`instances.json` 独立维护实例。加载边界校验目录、重复身份、Java、超时和编码；轮询比较内容哈希，校验成功才替换 desired 状态。活动实例维持旧启动配置，说明单独更新；托管窗口关闭且操作结束后切换或移除。operation 与 background_job 均纳入忙状态。目录变化由既有 expected_directory 检查拒绝旧任务的新操作。

`GET/PUT /configuration` 复用现有 HTTPS、令牌与指纹；只返回密钥是否配置，不回传原值。实例保存携带 revision 防止覆盖其他编辑。`POST /configuration/reload` 立即重载；CurseForge 只读测试使用独立接口。主机路径配置保存后重启生效。无额外端口和传输层。

A设置的保存、生效与任务启动共用任务调度锁。保存期间新建、续接及归档等待生效后再使用运行对象；已有worker运行时拒绝保存。并发保存顺序提交，只安装已提交快照对应的client和agent，框架报告快照未提交时明确报错。

## AstrBot 视图与模型测试

`views/settings` 通过 AstrBot v4.29.4 原生 bridge 的 apiGet/apiPost 调用插件注册接口，复用 Dashboard 管理员登录。A 的配置继续以 AstrBotConfig 保存，B 的配置经现有 HostClient 写入。主审模型分别覆盖请求配置，不改共享提供商。

能力测试使用无生产工具的独立对话；测试结果写本地，按 provider/model/config/settings 哈希识别过期。短对话、流式、回显调用续接、原生搜索、alpha/search、commentary执行进度汇报和审核 JSON 分别记录。支持／未观察到／临时失败分开；只根据已验证事实自动配置，不因网络故障清空有效设置，不自动开启进度转发。

原生搜索以 [OpenAI 文档](https://developers.openai.com/api/docs/guides/tools-web-search) 为准。独立搜索固定参考 [Codex 553c764 的 SearchRequest](https://github.com/openai/codex/blob/553c764e8b99fa519e9c6eb9b657875ef0f5e1c1/codex-rs/codex-api/src/search.rs)，调用 provider-relative `alpha/search`，只实现排障使用的 search/open/find。保留任务搜索会话、可读 output 和结构化来源；不把 encrypted_output 放进主模型上下文。
