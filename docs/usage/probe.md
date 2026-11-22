# MCAI Probe 服务端诊断

[使用索引](README.md) · [指标与协议](../design/probe.md)

MCAI Probe 只安装在服务端，让 AI 获取当前玩家位置、全服与维度指标、已加载对象数量和短时实体热点。客户端不需要安装，也不新增端口或密钥。

Probe 0.5.0 提供在线玩家、区块加载／tick 状态、对象计时、慢 tick 筛选及直接强加载汇总。直接 ticket 与传播后的有效加载等级分别解释。NeoForge 能核对控制器、所有者及实际注册模组时才显示对应字段。旧 JAR 保留原有能力；新选项以 Probe 的实际能力声明为准。

安装兼容 Probe 后，`mc_verify`的启动就绪检查会自动确认服务端主线程能够处理本次请求；即使Java仍在、日志曾出现Done，主线程未响应也不会通过。未安装Probe时只报告日志就绪。已安装旧Probe但缺少响应能力时需配套更新，不能把旧日志或上次进程的能力文件当成本次响应。检查不设置TPS／MSPT性能基线。

## 安装

正常停服后，从 B 发行包的 `probe/` 目录选择**一个**匹配文件放入该服务端 `mods/`，再正常启动：

| Minecraft | 加载器 | 文件 | Java |
|---|---|---|---|
| 1.7.10 | Forge 10.13.4.1614 + lwjgl3ify 3.1.0 + UniMixins 0.3.2 | `mcai-probe-1.7.10-forge-0.5.0.jar` | 17／21 |
| 1.16.5 | Forge 36.2.39+（36.x） | `mcai-probe-1.16.5-forge-0.5.0.jar` | 8 |
| 1.19.2 | Forge 43.x | `mcai-probe-1.19.2-forge-0.5.0.jar` | 17 |
| 1.20.1 | Forge 47.x | `mcai-probe-1.20.1-forge-0.5.0.jar` | 17 |
| 1.20.1 | Fabric | `mcai-probe-1.20.1-fabric-0.5.0.jar` | 17 |
| 1.21.1 | Forge 52.x | `mcai-probe-1.21.1-forge-0.5.0.jar` | 21 |
| 1.21.1 | Fabric | `mcai-probe-1.21.1-fabric-0.5.0.jar` | 21 |
| 1.21.1 | NeoForge 21.1.247+（21.1.x） | `mcai-probe-1.21.1-neoforge-0.5.0.jar` | 21 |

0.20.1 随 B 包提供 Probe 0.5.0 的八个目标，包含区块诊断、模拟玩家控制和 Mixin 兼容修复。更新时正常停服，移走旧 Probe 后放入同名的新 JAR，再启动；A、B 须配套更新，Probe 协议 1 按能力声明扩展。Forge 版不依赖 Fabric API；Fabric 版需要对应版本的 Fabric API 和 Loader 0.16.14+。Forge 包含 MixinExtras，NeoForge 使用加载器自带的 MixinExtras；不要安装 `sources` 源码包。Forge、NeoForge 和 Fabric 版本按表中加载器分别选择。NeoForge 按 21.1.247 基线构建并验证，其他 NeoForge 21.1.x 仅声明兼容范围。1.7.10 当前基线是标准 Forge + lwjgl3ify + UniMixins；GTNH 2.6.1 有隔离服验证记录，其他组合须按实际环境验证。

1.16.5 目标要求 Forge 36.2.39 或更高的 36.x，已验证标准 Forge 36.2.39 与 CatServer `1.16.5-1d8d6313`（Forge 36.2.39／Java 11.0.21）。混合端验证仅覆盖上述版本的隔离Probe／spark环境，其他插件及整合包组合需另测。

B 配置的实例目录应与 BAT 启动 Java 时的工作目录一致。MOD 在工作目录生成 `.mcai-probe/`，B 自动发现，无额外配置。启动日志显示 `MCAI Probe 0.5.0 ready` 后即可使用。

## 使用

### 临时模拟玩家

具有 `player_simulation` 能力的目标可从服务端控制台创建一个临时模拟玩家：

```text
mcai_probe player ProbeBot spawn at 0 65 0 in minecraft:overworld
mcai_probe player Scout spawn at 1024.5 100 1024.5 in minecraft:overworld mode spectator invulnerable true ephemeral true
mcai_probe player Scout status
mcai_probe player Scout move to 1280.5 100 1024.5 speed 20
mcai_probe player Scout stop
mcai_probe player Scout tp 1024.5 100 1024.5 in minecraft:overworld
mcai_probe player ProbeBot remove
mcai_probe player list
```

模拟玩家通过内部伪连接加入正常玩家列表并参与玩家 tick 和区块跟踪。`mc_players` 会返回其 UUID、位置及 `simulated: true`；`mc_objects` 和 `mc_inspect` 也能按普通玩家实体观察它。下列命令仅接受服务端控制台，沿用现有控制台审核流程。

- `spawn at <x> <y> <z> in <dimension> [mode <mode>] [invulnerable <true|false>] [ephemeral <true|false>]`：三个选项可任意排序，每项最多一次。默认使用服务端游戏模式和原版存档流程，不额外开启无敌。`mode` 接受 `survival`、`creative`、`adventure`、`spectator`；1.7.10 明确拒绝 `spectator`。旁观玩家能否触发区块加载取决于原版 `spectatorsGenerateChunks` 规则。无敌保护免受一般伤害，可用 `remove` 确定清理。
- `ephemeral true` 跳过原版玩家 `.dat` 保存。若同名离线 UUID 已有 `.dat` 或 `.dat_old`，命令拒绝创建并保留文件。原版统计、进度和模组各自保存的数据可能仍会写入。
- `move to <x> <y> <z> [speed <blocks_per_sec>]` 以每 20 个服务端 tick 为一秒直线移动，速度默认 5，范围 0.5 至 50，到达后驻留。移动不寻路；建议选择畅通路线或使用无敌保护。`tp <x> <y> <z> [in <dimension>]` 立即传送并结束当前移动。`stop` 取消移动、定期右键和正在使用的物品。
- `status` 返回小数位置、区块坐标及 `simulation` 字段；`mc_players` 也提供该字段，其中包括模式、无敌、潜行、朝向、`idle`／`moving`／`using` 以及当前位置区块的 `loaded` 和 `entity_ticking`。跟踪立即刷新，区块完成加载仍需要时间。开始采样前可等 `entity_ticking: true`；1.7.10 该字段为 `null`，只能检查 `loaded`。`list` 仍返回名称、UUID、维度、小数坐标和连接状态。
- `look <yaw> <pitch>` 或 `look at <x> <y> <z>` 设置朝向；瞄准方块请用方块内的小数坐标。`sneak <true|false>` 切换潜行。`use [once|interval <ticks>]` 在主手执行一次右键或每隔 1 至 1200 tick 执行一次。优先对 4.5 格内命中的已加载方块交互；未命中时尝试主手物品。游戏模式、保护规则和方块交互语义仍生效。启动定期右键会停止移动，开始移动会取消定期右键。

名称为 1 至 16 位字母、数字或下划线；同名在线玩家会被拒绝。坐标必须有限，`|x|、|z|≤29999984`、`|y|≤20000000`。1.7.10 使用数字维度 ID，例如 `0` 或 `-1`。模拟会话只在当前进程内存在；`remove`、死亡、断开和停服沿用原生离服清理，重启不会自动恢复。采用默认存档时，同名模拟玩家重新创建若读取到零生命值会恢复满血。

`mc_metrics` 无需 spark 即可读取堆占用、内存池、直接缓冲区、窗口 GC 增量和近期回收前后堆大小。卡顿先对照 `wall_ms`、`server_cpu_ms` 和 `gc_pause_ms`，再看 `phase_wall_ms_total` 中的计划刻、区块/刷怪、存盘及网络等阶段。阶段和对象墙钟可能包含暂停，不宜直接当作 CPU 热点。安装 spark 后，其原生 TPS、MSPT、CPU 与 GC 窗口仍在独立 `spark` 字段。

群指令保持原样。反馈可写：

```text
/mcaisay 主城卡顿 我的游戏名是Steve，刚进基地就卡
```

AI可依次查询玩家位置、比较维度耗时、普查附近实体，再进行短时采样。默认Probe对象计时10秒、上限30秒；`mc_profile engine=spark`默认30秒、允许15—60秒，可选全部线程或仅慢tick，不能按区块范围过滤调用栈。两种采样每实例共用一个占用；中途反馈仍进入原任务。完整结果保存在B后台记录，群里只发关键问题和结论。

启用区块阶段后，`mc_profile engine=probe group_by=chunk` 的 `category_wall_ms` 区分实体、掉落物、方块实体与区块阶段，`chunk_phase_wall_ms` 列出观测到的方块／流体计划刻、随机与区块 tick、刷怪耗时。再用 `group_by=type` 比较阶段或对象类型；要只看某阶段，可把阶段名作为对象类型筛选。支持这项能力时，`chunk`、`type`、`dimension` 默认开启，`object` 默认关闭；用 `include_chunk_phases` 显式切换。结果的 `covered` 列出启用的计时入口，耗时不代表整个区块或整拍。1.7.10 只有混合计划刻及部分随机与区块 tick 计时，无独立流体或刷怪计时。

支持慢拍采样的 Probe 可用 `only_ticks_over_ms`：只把整拍耗时严格超过阈值的计时计入榜单，返回命中拍数和每命中拍平均值。没有命中时榜单为空。对象榜达到 100,000 个分组时可用更慢的观测替换冷条目；`partial` 及 `omitted_calls`、`omitted_wall_ms`、`evicted_entries` 描述被省略的计时与淘汰次数。

`mc_chunks view=forced_summary` 按维度和可核实的模组汇总扫描到的直接强加载，分别列出原版与未知归属。直接记录数可大于区块数；同一区块可出现在多个分组，不能把分组相加当作全局总数。扫描不会加载新区块。

`mc_chunks view=scheduled_backlog` 按积压量列出范围内已加载、待执行计划刻非零的区块，另附范围及各命中维度的总量和区块数（不受 `top` 限制）。这些是检查时的排队数量，与实际执行量或耗时分开看。Forge 1.7.10 只返回混合队列总数；其余目标分别给出方块和流体。旧 Probe 未声明能力时需更新后才能使用。

spark模式先用`profiler info`确认空闲，再使用已安装spark的限时本地保存功能，B保留原始`.sparkprofile`及线程、热点方法和主要调用路径摘要。已有前台或后台采样时返回占用并保留原采样，可使用既有结果或Probe计时；15秒内未确认空闲则明确失败，不启动采样。采样权重与Probe实测对象耗时分别解释；未知方法来源保持未知。取消后立即停止等待，已开始的spark按原时限自然结束，期间仍占用采样位置；不会发送全局stop／cancel。内部取证的轮询、取消及可自行处理的失败留本地；用户明确要求的诊断会返回必要结果或中断原因。

隔离Forge1.19.2使用的spark1.10.37存在Java引擎慢tick导出缺陷：能确认采样结束，却可能没有本地报告。此时任务明确失败并保留回执，后续诊断可使用默认采样及≥100ms事件线索；不会把缺少报告解释为没有热点。各版本的实际验证边界见[开发记录](../development/probe.md)。

NBT保持单对象、按指定路径读取。大对象同步保存耗时单独展示；每请求SNBT最多1MiB，超限字段整项省略并标记部分结果，可沿更具体路径继续查询。

- 全服 TPS 代表实际 tick 频率；各维度展示耗时，不单独计算 TPS。
- 实体多只说明数量集中；热点计时提供实体／方块实体耗时证据，其他工作仍需 spark、线程栈等工具定位。
- 普查只看已加载内容，不生成区块。分批结果包含采集起止时间和覆盖说明；对象移动、卸载或数量上限可能导致部分结果。
- 在线实时数据、磁盘存档、历史经验分别解释。诊断工具保持只读，修复仍等待原有审核与管理员批准。
- `mc_metrics history=true`可读取五分钟内最多256条≥100ms的tick事件及维度耗时；容量淘汰数量会单独报告，事件只作为关联玩家反馈和采样窗口的线索。
- 历史默认每5秒保留一个代表样本，并省略无人且无区块的维度；`history_step_seconds=1` 恢复逐秒，`include_idle_dimensions=true` 恢复空闲维度。独立的慢拍和 `state_events` 不抽样；后者可对照玩家进出、加载数与已识别强加载变化，少于5秒的强加载集合变化可能错过。
- 小矩形优先使用 `scope=chunks/player`。`mc_objects category=blocks` 只读最多16个已加载区块，`block_id` 精确筛选，`group_by=object` 看坐标和状态（1.7.10 为数字元数据），`group_by=type` 看计数。超时或取消时已取得的数据可作为部分结果续读。
- `mc_profile group_by=object` 可直接查看首次记下的下落方块、实体自定义名和版本支持的所有者 UUID。同一实体在同一维度按 UUID 合并，坐标取最后一次观测；`moved_chunks: true` 表示窗口内观测到跨区块。按类型查询运行中版本用 `mc_runtime section=mods query=名字`。
- Spark `mode=allocation` 依赖其 async-profiler，官方 Windows 安装使用 [`diagnostics memory-jfr`](queries.md)。分配字节权重、老对象样本和 HPROF 保留大小用于回答不同问题。

## 故障与维护

`mc_status` 返回探针版本、加载器、会话和最近更新时间。没有安装时原有诊断仍可使用；AI 不会自动安装探针或重启。

若提示结果未取得，检查服务端是否卡住、控制台是否可用、工作目录是否一致，以及服务端日志。B 会发送取消标记并保存请求编号，不默认重跑。主线程停顿时最后快照可能过时，此时使用已有外部线程栈工具。

两端断线时采样继续，重连查询原任务。MC重启产生新会话，未完成采样中断。B重启后托管窗口按目录／session重连，原辅助工作标记中断，不自动重新执行。任务停止与修复前清理会请求取消；MOD由后台线程读取取消标记，主线程恢复tick后处理取消事实。

`.mcai-probe/` 含玩家现场及诊断结果；B 的任务目录保存导入副本。五分钟现场保存在内存，重启清空。磁盘请求、结果保留用于追查，停服且没有活动任务时可按需清理旧记录。
