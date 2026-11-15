# MCAI Probe 服务端诊断

[使用索引](README.md) · [指标与协议](../design/probe.md)

MCAI Probe 只安装在服务端，让 AI 获取当前玩家位置、全服与维度指标、已加载对象数量和短时实体热点。客户端不需要安装，也不新增端口或密钥。

## 安装

正常停服后，从 B 发行包的 `probe/` 目录选择**一个**匹配文件放入该服务端 `mods/`，再正常启动：

| Minecraft | 加载器 | 文件 | Java |
|---|---|---|---|
| 1.19.2 | Forge 43.x | `mcai-probe-1.19.2-forge-0.2.1.jar` | 17 |
| 1.20.1 | Forge 47.x | `mcai-probe-1.20.1-forge-0.2.1.jar` | 17 |
| 1.20.1 | Fabric | `mcai-probe-1.20.1-fabric-0.2.1.jar` | 17 |
| 1.21.1 | Forge 52.x | `mcai-probe-1.21.1-forge-0.2.1.jar` | 21 |
| 1.21.1 | Fabric | `mcai-probe-1.21.1-fabric-0.2.1.jar` | 21 |

从[0.12.0发行页](https://github.com/KNaiFen/astrbot_plugin_mcai/releases/tag/v0.12.0)下载对应的Probe 0.2.1 JAR，也可从[源码构建](../development/probe.md#构建)。更新时正常停服，移走旧Probe后放入对应的新JAR，再启动；单独更新Probe无需升级A、B或协议。Forge版不依赖Fabric API；Fabric版需要对应版本的 Fabric API 和 Loader 0.16.14+。Forge 包内包含 MixinExtras；不要安装 `sources` 源码包。1.21.1 Forge JAR 不能用于 NeoForge。本轮未提供 1.16.5、1.7.10 或插件端版本。

B 配置的实例目录应与 BAT 启动 Java 时的工作目录一致。MOD 在工作目录生成 `.mcai-probe/`，B 自动发现，无额外配置。启动日志显示 `MCAI Probe 0.2.1 ready` 后即可使用。

## 使用

安装spark后，Probe通过其公开API读取平均TPS、MSPT、进程／系统CPU及GC信息，`mc_metrics`结果中的独立`spark`字段保留原生统计窗口和单位。CPU是0到1的比例，GC时间为毫秒。spark是可选集成，未安装时Probe仍可正常使用；`mc_status.probe.integrations.spark`区分未安装、可用和API错误。缺少Probe但已有spark时，AI也可通过控制台运行`spark tps`、`spark health`取得诊断信息，不必为此安装Probe。

群指令保持原样。反馈可写：

```text
/mcaisay 主城卡顿 我的游戏名是Steve，刚进基地就卡
```

AI 可依次查询玩家位置、比较维度耗时、普查附近实体，再进行短时采样。采样默认10秒、上限30秒，每个实例同时一个；中途反馈仍进入原任务。完整结果保存在 B 后台记录，群里只发关键问题和结论。

- 全服 TPS 代表实际 tick 频率；各维度展示耗时，不单独计算 TPS。
- 实体多只说明数量集中；热点计时提供实体／方块实体耗时证据，其他工作仍需 spark、线程栈等工具定位。
- 普查只看已加载内容，不生成区块。分批结果包含采集起止时间和覆盖说明；对象移动、卸载或数量上限可能导致部分结果。
- 在线实时数据、磁盘存档、历史经验分别解释。MOD 只诊断，修复仍等待原有审核与管理员批准。

## 故障与维护

`mc_status` 返回探针版本、加载器、会话和最近更新时间。没有安装时原有诊断仍可使用；AI 不会自动安装探针或重启。

若提示结果未取得，检查服务端是否卡住、控制台是否可用、工作目录是否一致，以及服务端日志。B 会发送取消标记并保存请求编号，不默认重跑。主线程停顿时最后快照可能过时，此时使用已有外部线程栈工具。

旧Probe 0.2.0 Forge版将MixinExtras限制为`[0.4.1,0.5)`，与需要0.5.x的模组共同安装时会触发`VERSION_RESOLUTION_FAILED`。嵌套依赖解析失败后，可能连带显示多项前置缺失；使用Connector的整合包也可能提示`fabric_permissions_api_v0`缺少`fabric-api-base`。先替换为0.2.1再检查启动日志，不按连带报错盲目添加依赖。0.2.1保留内嵌0.4.1，允许Forge在同服依赖中选择兼容的新版本。

两端断线时采样继续，重连查询原任务。MC重启产生新会话，未完成采样中断。B重启后托管窗口按目录／session重连，原辅助工作标记中断，不自动重新执行。任务停止与修复前清理会请求取消；MOD由后台线程读取取消标记，主线程恢复tick后处理取消事实。

`.mcai-probe/` 含玩家现场及诊断结果；B 的任务目录保存导入副本。五分钟现场保存在内存，重启清空。磁盘请求、结果保留用于追查，停服且没有活动任务时可按需清理旧记录。
