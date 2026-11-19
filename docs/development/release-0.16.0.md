# 0.16.0 发行验证

[开发索引](README.md) · [MOD 工作区与实服验收](mod-repair-implementation-2026-11-19.md) · [升级说明](../../README.md#更新时保留什么)

0.16.0 使用 `mcai-6`，A、B 和全部托管窗口须配套更新。A 端新增 MOD 下载、任务工作区与可配置的 QQ 长消息合集，B 端新增任务内隔离测试副本。Probe 仍为 0.4.1，发行目标增至八个，新增 NeoForge 1.21.1。实际发送使用 OneBot v11 合并转发；原有 @ 放在卡片之后。

2026-11-19，从干净的 `dev` 快照在 Windows／Python 3.12 环境运行 `python scripts/build_release.py`。MCA Selector 固定 JAR 哈希、Java 辅助程序构建和八个 Probe Gradle 目标通过。三份 ZIP 核对了完整性、重复路径、与提交快照的字节一致性及 README／使用文档的相对链接；B 包的 16 个 Probe 运行与源码 JAR 不含测试负载或打包的 spark 类。公开 `main` 仅从 A 包生成，与其文件逐字节一致，父提交为上一版公开 `main`。

从 B 包用 `uv build --wheel --offline` 构建 wheel，再用 `python -m pip install --no-deps --target` 安装到独立目录。A 入口由解压后的插件加载；从空目录以 `python -m pytest --require-astrbot -p no:cacheprovider` 运行发布验收，AstrBot 固定为 v4.29.4。选择集：`test_mod_workspace.py`、`test_web_downloads.py`、`test_plan_continuation.py`、`test_task_interactions.py`、`test_query_cli.py`，以及设置保存、OneBot 合集和 @ 重试、方案完整性、完整 MOD 工作流用例。**44 项通过，零跳过（165.31 秒）**。独立安装核对了产品版本与协议，`mcai query test nbt select --help` 正常返回帮助。Ruff 与 Git 空白检查通过。

发布验证使用模拟模型回复和受控 OneBot 接入端；既有真实模型和隔离服结果见上方专题。本轮未在真实 QQ 群试发、未重跑全部 MC 实服矩阵。最终发行包保存在 `dist/release-0.16.0/`；暂存目录只保留 JUnit 结果、文件校验和与发布回执。
