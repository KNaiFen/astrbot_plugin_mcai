# MCAI 0.17.0 发行记录

0.17.0 使用 `mcai-7`，与 0.16.0 的 `mcai-6` 不混用。A、B 与所有已有托管窗口须配套更新；Probe 仍是 0.4.1，已安装同版无需替换。升级前完成或中止活动任务，保留任务历史、配置、证书、备份和自定义规则。

- MOD 源码修复只在需要时加载详细指引。试玩反馈绑定实际运行的试服和制品，管理员用原有 `/mcaisay` 自然回复。明确通过后，在原批准范围内先停试服，再备份、安装同一份制品并验证正式服；失败反馈会继续排查。
- B 支持预检测试端口和复制清单，保留失败的副本供定位。`/mcaidone` 验收后自动归档并清理任务临时文件，保留正式服备份。
- 正式实例可按需开启故障留证，默认关闭。B 在 A 离线时也能记录，只有明确配置通知群才发消息。

[真实端到端复验及原始判定摘要](mod-repair-implementation-2026-11-19.md#自然语言试玩确认发布与故障留证复验)记录了本版功能的真实 OneBot、AstrBot 4.29.4、主模型与独立审核、Windows HTTPS 和隔离 Fabric 1.21.1 实测。通过用例从试服进世界走到正式服进世界和清理；负反馈用例来自实际白名单拒绝，正式服无写入。测试使用本地 OneBot 与隔离服务端。

发行附件包括 A/B 安装包、完整项目源码、八个 Probe JAR、Probe 源码和 `SHA256SUMS.txt`。本版没有改动 Probe 和存档辅助工具的 Java 源码及构建输入；沿用 0.16.0 已发行的 Java 产物。

发布前从干净的 Git 快照生成三份 ZIP，核对完整性、文件清单、源文件字节、部署文档链接与附件 SHA-256。B 从解压目录以 `uv build --wheel --offline` 构建，使用 `python -m pip install --no-deps --target` 独立安装；A 从解压插件加载。Windows／Python 3.12.14 上使用 AstrBot 4.29.4，执行 `python -m pytest --require-astrbot -p no:cacheprovider`，覆盖 `test_mod_workspace.py`、`test_web_downloads.py`、`test_plan_continuation.py`、`test_task_interactions.py`、`test_query_cli.py` 和 `test_client_recovery.py`：**51 项通过，零跳过（168.40 秒）**。发行复验使用受控模型；真实模型与隔离服结果来自上方专题。公开 `main` 从 A ZIP 生成，逐文件核对内容，以上一版公开 `main` 为唯一父提交。
