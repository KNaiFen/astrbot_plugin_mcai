# 服内诊断与协议

[设计索引](README.md) · [安装与使用](../usage/probe.md)

## 采集与语义

`common`是独立Java 8核心，按Gson 2.2.4 API编译，负责协议文件、请求去重与取消、互斥、历史、普查预算、分页和统计聚合。`ProbePlatform`提供游戏快照、扫描游标、已复制的NBT及spark命令边界；读取世界和推进游标均在服务端tick处理，后台只处理脱离世界的数据。核心class合并进各目标JAR，不增加独立运行依赖。Minecraft 1.19.2／1.20.1／1.21.1共用现代游戏适配器，Forge／NeoForge／Fabric各自适配生命周期事件；1.16.5和1.7.10使用各自旧版适配器。实现使用Java、官方构建链及MixinExtras，不依赖Architectury或Kotlin。

主线程通过 tick 事件测量全服、维度 elapsed wall time，保留五分钟原始样本和秒级摘要。全服 TPS 为窗口内 tick 数除以实际经过时间；冷启动按实际时长计算，样本不足返回 null。MSPT给出平均、P95、最大及超过50ms的次数。维度耗时包含该维度tick内的工作；全服与维度差值不强行归因。1.21.1 另返回目标 tick rate、冻结、加速状态。100,000条tick上限触及时标记 partial。

玩家每秒采集一次，事件记录登录、离开和跨维度；内存最多五分钟／30,000条。游戏名与 UUID 支持查询，QQ 与游戏账户由线索对应。

对象普查访问已加载实体和 chunk holder，使用 `getChunkNow`，不请求区块加载。每tick所有普查合计约1ms、每批最多256个迭代步骤，同实例最多四个普查。扫描中同一对象去重；变化导致无法继续迭代时返回 partial 和原因。结果注明非原子快照、已访问数量、期间移除数量、分组总数和排行上限。对象／分组记录上限100,000，达到时标记 partial。

短时采样以 `WrapOperation` 包装实体 `tick`、骑乘实体 `rideTick` 及方块实体ticker；`finally`记录耗时并保留原异常传播。未采样时快速跳过。采样按墙钟到期，记录实际tick数；耗时排除已包裹子调用，避免嵌套重复累计。按对象、类型、区块、维度汇总累计／单次平均／单次最大／每服务端tick贡献。对象跨区块按观测位置分桶。

采样覆盖已观测实体和方块实体tick，不涵盖整个区块的计划刻、随机刻、流体、异步、网络或存盘。排序、聚合及文件序列化在独立单线程完成；世界对象只在服务端线程读取。

可选 `only_ticks_over_ms` 仅累计整拍耗时严格大于阈值的完整 tick。每拍先暂存排他计时，判定后合并或丢弃；归并不计入本拍判断。结果分别报告全窗口 tick 数和命中数、每全窗口 tick 与每命中 tick 的贡献，零命中返回空榜。旧 Probe 缺少 `profile_slow_ticks` 时明确拒绝。

## 请求与恢复

```text
Agent → 现有 HTTPS operation → B background job
      → .mcai-probe/requests/<id>.json
      → 控制台 mcai_probe request <id>
      → MOD 主线程采集 → results/<id>.json
      → B 持久化结果 → mc_job_read/wait 分页／mc_artifact_read 长字段
```

MOD不监听网络。`mcai_probe`仅接受服务端控制台来源。请求文件异步读取，再交主线程；结果、能力文件通过临时文件原子替换。

协议1请求含 `protocol/id/session/kind/arguments_hash/arguments`；结果回传同一身份，附 `status/items`、采集信息及错误。每次MC启动生成新session，能力文件每秒更新。模型使用具名工具，不能指定协议文件路径。

性能告警读取能力文件可选的 `mspt_mean`，来自已有的一秒 tick 摘要；心跳只读取最近一秒采样。长窗口统计从服务端线程取得固定样本和世界状态，使用独立后台线程排序和写入结果，同时最多处理一个统计请求。B 校验 PID、JVM 启动时间、Probe 会话和心跳时效，无需发控制台命令。缺失、过期或未采到值的心跳不参与告警。

B沿用operation id作为后台编号和MOD请求编号。同编号／参数只创建一个采集，执行中重复通知忽略，已完成通知复用原文件；会话或参数冲突报错。B导入前核对协议、编号、参数哈希及会话，保留完整JSON和分页事件。

普通请求等15秒；采样等指定时长加15秒。超时返回 completion_unknown、最近快照和编号，并留下取消标记。新 JVM 已出现但 Probe 能力仍指向旧 PID 时，B 短暂等待新能力再发出原请求；已发出后发现会话变化即中断，不自动重新采样。A 断线不影响采集；续接查询原编号。B 重启沿用既有“后台中断、保留结果、不自动重跑”机制。分页元信息提供实际结果条数，零行也是可读结果。

取消写 `cancel/<id>.json`，MOD在tick边界／分批处检查；B最多等1秒确认，记录confirmed，不无限阻塞停止或修复。主线程卡死时取消只能在恢复后生效；详细计时还受原墙钟截止时间约束。

## 工具与批准

Probe 可选接入 spark 公开 API，不打包 spark/API 类，也不要求安装 spark。加载器报告 spark 存在后才访问适配类；能力文件的 `integrations.spark` 报告安装状态、版本、可用性及 API 错误，调用失败记录日志。

metrics结果在原Probe数据之外添加独立`spark`字段，包含采集时间、平均TPS、MSPT、CPU及GC。直接使用API提供的窗口和值，注明单位；未支持和未取得有效值的情况显式标注。原Probe的维度耗时、历史、对象和热点协议保持不变，不把不同来源或不同窗口的统计混合计算。

`mc_players`、`mc_metrics`、`mc_objects`、`mc_chunks`、`mc_runtime`、`mc_profile`、`mc_inspect`为固定只读接口，不经过AI审核；后台用`mc_job_read`查询、`mc_job_wait`等待、`mc_job_cancel`取消。其他脚本、普通控制台及提案保持原审核规则，MOD不提供修改入口。

## 临时模拟玩家

`player_simulation`是能力文件中的增量能力。控制台命令为`mcai_probe player <name> spawn at <x> <y> <z> in <dimension>`、`remove`和`list`。创建路径参考 Carpet 的 fake player：版本层构造真实 `ServerPlayer`/`ServerPlayerEntity`/`EntityPlayerMP`，使用只在进程内存在的伪连接调用正常玩家列表加入流程，再将位置设回请求坐标。伪连接丢弃所有出站包，不监听端口，也不等待外部 FML 握手。

版本层通过现有`GameVersion`按编译期接口构造玩家、完成登录及离服；不按映射前的方法名反射调用游戏API。伪连接不加入外部网络轮询，因此适配器在服务端tick补充`doTick`／`onUpdateEntity`，恢复固定位置并清零速度，每20tick刷新正常玩家区块跟踪。每个版本维护活动模拟玩家表，但查询只读取真实玩家列表，不用该表补造在线结果。创建和删除只依赖一次原生登录／离服事件，移除时关闭内部channel，停服清理所有活动实体。Probe不保存模拟会话或自动恢复配置；原生玩家数据仍可能由正常登录／离服流程保存，重启不会自动登录。

目标检查按已加载UUID或方块坐标寻找，不存在时明确说明。NBT仅在指定 `nbt_path` 时读取，保留SNBT类型、子项offset/limit；大字段由现有artifact引用续读。

NBT仅对单对象按需保存并复制脱离世界；保存、复制在主线程分别记录耗时，模组同步save不能被约1ms普查预算抢占。路径遍历、排序及SNBT生成在IO线程执行；单请求SNBT总量上限1MiB，超限整项省略，明确partial／原因和next_offset，建议缩小路径，不返回损坏的截断SNBT。异步计算或结果写入失败在`failures/<id>.json`记录阶段、会话、参数哈希及错误；B验证身份后明确失败。已受理的内存记录在finally清理，磁盘完全不可写时日志保留具体阶段与写入错误。

## 现场查询

`mc_chunks` 复用分批普查，读取现有 chunk holder、非阻塞区块引用及直接 ticket。每行区分实际加载、方块／实体 tick 就绪、有效 ticket 等级、原版强加载与直接 ticket；不会创建 ticket 或请求加载区块。Forge 返回可核实的 mod ID、方块位置或实体 UUID；NeoForge 读取标准强加载 ticket 的控制器和所有者，仅在能核实实际注册模组时返回 `mod_id`，不从命名空间猜测。`forced_summary` 只统计已扫描、已加载区块中的直接强加载，原版／模组／未知分列，分别给出分组与整体的去重区块数。未完整扫描或触及上限时标注 `partial`。

`mc_inspect`读取普通方块状态及方块实体，区分越界、区块未加载和没有方块实体。实体检查补充名称、生命值、骑乘关系及玩家游戏模式；普查和热点的高频路径不额外收集这些字段。UUID未找到仅表示当前已加载集合未找到，不断言删除。结果附采集时间及Probe会话。

`mc_runtime`按summary／mods／datapacks／dimensions／settings读取实际版本、加载器、已加载组件、已启用数据包、维度及当前设置。mods可引用本实例同规范目录已完成的`mc_inventory`任务；B按ID及声明版本关联，保留全部候选、版本差异与单边记录。版本匹配不证明二进制或来源文件匹配。新能力通过协议1的capabilities增量声明，未安装Probe时原磁盘工具仍可使用。

## 主线程响应与ready

能力文件增加实际JVM PID，`ping`在服务端主线程处理后返回同请求身份、PID、tick序号和tick控制状态。B的Probe后台任务与ready检查共用持久化请求／结果交换，编号、参数哈希和会话校验不分叉。

`ready`从实例mods归档元数据识别Probe；Forge 1.7.10使用`mcmod.info`，Forge 1.16.5及更新目标使用`mods.toml`，NeoForge使用`neoforge.mods.toml`，三者都保留版本和来源声明；已安装时，在匹配本次就绪日志后取得新ping回执，观察期间每秒检查，并在满足观察时长后取得最终新回执、重新检查日志和进程身份后通过。每次响应最多等待15秒且不超过原总超时。子编号由原操作、方案步骤、检查位置和请求序号组成，请求文件先落盘再发送；JVM或Probe会话变化、能力不兼容、无响应均明确失败。tick冻结和主动调速不通过固定TPS门槛判错。未安装时结果为`logs_only`并明确主线程未验证，旧能力残留不作为安装依据。该检查只说明观察期间能够响应，不代替玩家登录或性能复现。

## spark限时采样

`mc_profile engine=probe`保持对象实测计时；`engine=spark`默认30秒，允许15—60秒，默认服务端线程，可选全部线程或慢tick阈值，不接受区块范围。Probe通过固定Minecraft命令参数启动并要求本地保存，以注释`mcai:<操作编号>:<Probe会话>`关联报告。请求专属接收实体从不加入世界，解决Forge spark忽略CommandSourceStack.source、改取entity或server的行为；它只接收该命令的异步回执，不读取游戏世界。可选的`SparkSenderMixin`仅在spark创建本请求的命令发送者时保留其包装器，防止spark的弱引用在GC后丢失回执；取得报告或明确结束并达到保存期限后释放。没有链接spark实现类或调用其私有采样方法。

两种引擎共享同实例互斥；人工前台spark已在采样时明确返回占用。取消只停止B等待，不发送全局stop／cancel，未确认结束时保留占用及`sampling_end_confirmed=false`。结束与报告保存分别记录；结束回执及时更新原文件，保存期间保留接收器和占用，最迟在采样时长加15秒的保存期限释放已确认结束的采样。迟到回执更新原文件，原cancelled／failed状态不复活；无法确认结束时保留占用到JVM退出，断线或B重启不重新采样。

B在原辅助进程和共享Job Object内，用标准Protobuf运行时解析本地报告，导入前核实实例内来源路径、编号、会话及时间。保存原始bytes、SHA-256与结构化摘要；解析失败也保留已取得的原报告。摘要的调用路径区分包含子调用与自身采样权重，方法排行只累计自身权重，递归不会重复累计；组件归属只来自报告的method／line／class映射，未知保留未知。权重不是Probe实测耗时或整机CPU比例。解析上限64MiB／100万节点，展示路径最多64帧，明确被省略外层帧数。

五分钟内存历史另保留最多256条≥100ms的单 tick 事件和维度耗时；`mc_metrics history=true` 按需返回，记录容量淘汰数量。JFR 只在同 JVM、同 Probe 会话时用这份历史按时间对齐；区块生成按持续区间，区域文件读写按活动点对齐。重合是线索，不能把异步耗时加到主线程 tick 上。运行边界见[区块取证说明](../usage/operations.md#文件存档与故障取证)。
