# 服内诊断与协议

[设计索引](README.md) · [安装与使用](../usage/probe.md)

## 采集与语义

共享代码负责 JSON、时间窗口、计数和聚合；Minecraft 1.19.2／1.20.1／1.21.1 适配接口差异，Forge／Fabric 适配生命周期事件。实现使用 Java、官方构建链及 MixinExtras，不依赖 Architectury 或 Kotlin。Forge 1.19.2、Forge 1.21.1 是单独目标；1.19.2 复用 1.20.1 的 Forge 生命周期入口。

主线程通过 tick 事件测量全服、维度 elapsed wall time，保留五分钟原始样本和秒级摘要。全服 TPS 为窗口内 tick 数除以实际经过时间；冷启动按实际时长计算，样本不足返回 null。MSPT给出平均、P95、最大及超过50ms的次数。维度耗时包含该维度tick内的工作；全服与维度差值不强行归因。1.21.1 另返回目标 tick rate、冻结、加速状态。100,000条tick上限触及时标记 partial。

玩家每秒采集一次，事件记录登录、离开和跨维度；内存最多五分钟／30,000条。游戏名与 UUID 支持查询，QQ 与游戏账户由线索对应。

对象普查访问已加载实体和 chunk holder，使用 `getChunkNow`，不请求区块加载。每tick所有普查合计约1ms、每批最多256个迭代步骤，同实例最多四个普查。扫描中同一对象去重；变化导致无法继续迭代时返回 partial 和原因。结果注明非原子快照、已访问数量、期间移除数量、分组总数和排行上限。对象／分组记录上限100,000，达到时标记 partial。

短时采样以 `WrapOperation` 包装实体 `tick`、骑乘实体 `rideTick` 及方块实体ticker；`finally`记录耗时并保留原异常传播。未采样时快速跳过。采样按墙钟到期，记录实际tick数；耗时排除已包裹子调用，避免嵌套重复累计。按对象、类型、区块、维度汇总累计／单次平均／单次最大／每服务端tick贡献。对象跨区块按观测位置分桶。

采样覆盖已观测实体和方块实体tick，不涵盖整个区块的计划刻、随机刻、流体、异步、网络或存盘。排序、聚合及文件序列化在独立单线程完成；世界对象只在服务端线程读取。

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

B沿用operation id作为后台编号和MOD请求编号。同编号／参数只创建一个采集，执行中重复通知忽略，已完成通知复用原文件；会话或参数冲突报错。B导入前核对协议、编号、参数哈希及会话，保留完整JSON和分页事件。

普通请求等15秒；采样等指定时长加15秒。超时返回 completion_unknown、最近快照和编号，并留下取消标记。MC重启检测会话变化，不自动重新采样。A断线不影响采集；续接查询原编号。B重启沿用既有“后台中断、保留结果、不自动重跑”机制。

取消写 `cancel/<id>.json`，MOD在tick边界／分批处检查；B最多等1秒确认，记录confirmed，不无限阻塞停止或修复。主线程卡死时取消只能在恢复后生效；详细计时还受原墙钟截止时间约束。

## 工具与批准

Probe 0.2.0可选接入spark公开API。五个目标仅编译依赖spark API，不打包spark/API类，也不要求安装spark。加载器报告spark存在后才访问独立适配类；不存在时不加载其API引用。能力文件的`integrations.spark`报告安装状态、版本、可用性及API错误，调用失败记录日志，不伪装成未安装。

metrics结果在原Probe数据之外添加独立`spark`字段，包含采集时间、平均TPS、MSPT、CPU及GC。直接使用API提供的窗口和值，注明单位；未支持和未取得有效值的情况显式标注。原Probe的维度耗时、历史、对象和热点协议保持不变，不把不同来源或不同窗口的统计混合计算。

`mc_players`、`mc_metrics`、`mc_objects`、`mc_profile`、`mc_inspect`为固定只读接口，不经过AI审核；后台用`mc_job_read`查询、`mc_job_wait`等待、`mc_job_cancel`取消。其他脚本、普通控制台及提案保持原审核规则，MOD不提供修改入口。

目标检查按已加载UUID或方块坐标寻找，不存在时明确说明。NBT仅在指定 `nbt_path` 时读取，保留SNBT类型、子项offset/limit；大字段由现有artifact引用续读。
