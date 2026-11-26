# 配置、终端与能力测试

[设计索引](README.md) · [用户配置](../usage/configuration.md)

## 终端与停服

所有Windows shell入口使用PowerShell 7.3+。实例配置目录，用户通过 `mcai tm` 创建独立交互终端，在其中运行固定的start.bat。B通过本机WebSocket连接，进程所有权和共享资源详见[托管终端与辅助资源](terminal-and-resources.md)。

一次性停服状态保存在窗口：发出stop前落盘，监听之后的新输出；收到重启提示后保存阶段并发一次Ctrl+C，中英文批处理确认单次回复Y。退出、取消及超时撤销监听。文件修复必须确认BAT链和Java退出，PowerShell窗口保留。断线不取消已接受的控制，原编号返回原结果。

固定初始化脚本设置初始代码页和Ctrl+C状态，提示符回报当前目录，ConPTY输出保留Unicode。B与窗口退出分开处理，不再由B清理所有服务端进程。

## 配置生命周期

`host.json` 保存基础配置和密钥，`instances.json` 独立维护实例。加载边界校验目录、重复身份、Java、超时和编码；轮询比较内容哈希，校验成功才替换 desired 状态。活动实例保留窗口的目录、Java 和编码；说明、复制清单及留证告警设置直接生效。空闲且在线时 B 通过 WebSocket `update_config` 同步停服命令、超时及重启提示。重连握手以窗口报告为实际配置，与 B 的期望值比较后继续同步；待生效字段单独返回。operation 与 background_job 均纳入忙状态。目录变化由既有 expected_directory 检查拒绝旧任务的新操作。

`GET/PUT /configuration` 复用现有 HTTPS、令牌与指纹；只返回密钥是否配置，不回传原值。实例保存携带 revision，主机配置支持可选 `host_revision`，并在写盘前复核版本防止并发或校验期间的外部修改互相覆盖。`POST /configuration/reload` 立即重读实例文件；CurseForge 只读测试使用独立接口。PowerShell 路径与辅助操作内存额度重启 B 后生效，清空 PowerShell 路径可恢复自动查找；下载上限、备份目录、存档 Java、留证设置及全局试服地址和端口可在线保存生效。修改试服端口须先释放全局名额；存在未关闭且未进入清理的隔离试服（或正在准备／清理）时不可切换 B 工作区，关闭试服窗口后释放该限制并保留原工作区记录供清理。无额外端口和传输层。

A设置的保存、生效与任务启动共用任务调度锁。保存期间新建、续接及归档等待生效后再使用运行对象；已有worker运行时拒绝保存。并发保存顺序提交，只安装已提交快照对应的client和agent，框架报告快照未提交时明确报错。

`workspace_java_path` 随 A 设置热重载，执行 `mc_workspace javap` 时解析和检查，允许指向同一 JDK 的 `java.exe` 或 `javap.exe`；留空按 `JAVA_HOME`、PATH 中的 `javap`、PATH 中的 `java` 顺序查找。`web_search_mode` 随 A 设置生效并参与能力结果的新旧判断；能力测试也会在接口拒绝该参数时改用裸搜索工具复测。

## AstrBot 视图与模型测试

Web 管理视图的 GET 查询参数走桥接第二个参数；所有浏览器修改走 POST，涉及 B 时由 A 转发。运行数据和 Probe 实时采样按实例按需加载。A 代理环境只提供脱敏概况；实例热重载保留当前操作快照。告警状态及历史筛选见[故障留证](storage-and-recovery.md#故障留证)。单项模型重测只更新该项，`alpha_open` 和 `alpha_find` 先建立搜索会话。

`views/settings` 通过 AstrBot v4.29.4 原生 bridge 的 apiGet/apiPost 调用插件注册接口，复用 Dashboard 管理员登录。A 的配置继续以 AstrBotConfig 保存，B 的配置经现有 HostClient 写入。主审模型分别覆盖请求配置，不改共享提供商。

能力测试使用无生产工具的独立对话；测试结果写本地，按 provider/model/config/settings 哈希识别过期。短对话、流式、回显调用续接、原生搜索、alpha/search、commentary执行进度汇报和审核 JSON 分别记录。支持／未观察到／临时失败分开；只根据已验证事实自动配置，不因网络故障清空有效设置，不自动开启进度转发。

图片能力项发送内置色块并核对实际颜色。只有接口明确拒绝图片输入时标为不支持，未识别和临时失败不作为禁用证据。单独的群截图识别请求沿用原生图片组件和提供商适配器，并计入该任务。

远程压缩默认关闭，由 `enable_remote_compaction` 和 `remote_compaction_mode` 控制。全量能力测试先通过流式 `compaction_trigger` 生成密文并做无状态回放；明确不支持（包括上游特性拦截的 403）才验证独立 `/responses/compact`。通过回放才自动启用对应模式，全部明确不支持或使用 Chat 提供商时关闭；未观察到结果或临时失败保留原配置。单项重测不改变配置。

原生搜索以 [OpenAI 文档](https://developers.openai.com/api/docs/guides/tools-web-search) 为准。独立搜索固定参考 [Codex 553c764 的 SearchRequest](https://github.com/openai/codex/blob/553c764e8b99fa519e9c6eb9b657875ef0f5e1c1/codex-rs/codex-api/src/search.rs)，调用 provider-relative `alpha/search`，只实现排障使用的 search/open/find。保留任务搜索会话、可读 output 和结构化来源；不把 encrypted_output 放进主模型上下文。
