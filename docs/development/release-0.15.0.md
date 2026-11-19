# 0.15.0发行验证

[开发索引](README.md) · [查询CLI实服验证](query-cli-lazy-tools-2026-11-18.md) · [上次发行](release-0.14.3.md)

## 发行范围与升级

本版相对公开0.14.3发布查询CLI、工具按需加载，以及检查点恢复顺序与结果阅读预算校准，功能源码提交25de510。九类查询合并为mc_query；34个模型工具中首轮提供15个基础工具，19个按需加载，加载集合及顺序持久化。原始argv、解析语义、证据和操作编号继续保存。metadata.yaml、pyproject.toml及请求头PRODUCT_VERSION同步为0.15.0。

A更新后可调用0.14.3 B原有远程操作；B的新功能是本机mcai query入口和相应jsonschema依赖。通信仍为mcai-5，终端与Probe未改，Probe继续0.4.1。只使用AI查询须更新A；本机CLI按需更新B和依赖并重启B，原托管窗口及MC继续运行。升级前完成或中止活动任务并等待操作结算，不迁移旧工具的未结算调用。已有数据及用户规则保留，人工合并执行模板的工具交互；审核和摘要模板未改。

本轮复用0.14.3已验证Java辅助工具和七目标Probe产物，逐字节核对，不重新构建未变更JAR。构建使用scripts/build_release.py的实际打包主体。公开main从插件ZIP生成，仅以上次main为父提交；dev保留完整源码和开发历史。

## 验证与边界

固定Windows／Python3.12.14／PowerShell7.3+／AstrBot v4.29.4，从解压B包通过`uv build --wheel --offline`构建wheel，`python -m pip install --no-deps --target`安装到独立site；A从解压插件加载。测试从仓库外的空目录运行，使用`--require-astrbot --import-mode=importlib`，要求零跳过。

- 独立安装定向集成66项全部通过、零跳过（220.54秒）。范围为test_query_cli.py、test_tool_contracts.py、test_review_resume.py、test_task_interactions.py、test_continuous_api_retry.py，以及自然目标下载／审核安装／归档、真实CLI、Chat／Responses多批方案。70个已加载模块逐一核对：A来自插件解压目录，B及worker来自独立site，源码字节一致。
- 请求头产品版本同步后重新打包、重建wheel并升级独立site，HTTPS及查询CLI补验9项全部通过、零跳过（39.66秒）；核对PRODUCT_VERSION=0.15.0、PROTOCOL=mcai-5。
- 新A连接原0.14.3 B完成查询类型／证据、按需加载及Chat／Responses一次批准多批执行5项，零跳过；最终版本重复验证5项全部通过（29.18秒）。B、worker、终端和操作上下文均从0.14.3原包导入，A来自新版插件。首次兼容测试因测试辅助解析器误从旧B导入而收集失败，修正为从A加载辅助模块后完成上述验证；B源码未改。
- 独立安装的`python -m mcai query test nbt select --help`正常返回类型、选择器与示例，无需连接B或全局安装。
- A／B／源码ZIP完整性、重复路径、逐文件源码一致、文档相对链接、新模块、规则及许可检查通过。B的Probe与vendor共41个文件与0.14.3逐字节一致；14个Probe运行／sources JAR未包含Fixture测试负载或spark打包类。公开main逐文件匹配A的ZIP，以原main为唯一父提交；12个发行附件附SHA-256并在上传时核对远端digest。

Ruff check全仓通过，变更的protocol.py格式与Git空白检查通过。全仓format --check仍报告scripts/test_probe_host.py一处既有格式差异，其Git blob与0.14.3源码相同；本次不修改。消融审查保留现有通信、任务和持久化机制，发布新增内容限版本标识与升级／验证说明。

历史实服190次真实请求及输入token对比见上方专题。本轮未重跑真实模型、真实QQ、全仓回归或四服矩阵；此前报告的6项既有断言失败及跨主机、长期并发边界继续保留，未计作本轮通过。

## 暂存与清理

发行暂存位于被忽略的runtime/release-0.15.0，用于安装包、原B兼容、JUnit与导入来源核对。发布附件确认后清理本轮解压目录、wheel、安装site、测试输入、缓存、日志及一次性脚本，仅留测试结果、校验和与发布回执的最小证据；dist保留本次交付附件。本轮没有启动真实MC服，没有修改用户存档、配置及现有测试服。
