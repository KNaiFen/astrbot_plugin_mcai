# 查询命令与按需帮助

[使用索引](README.md) · [运行维护](operations.md)

AI 通过 `mc_query` 查询当前绑定实例的文件、日志、存档和进程。其他工具按需要加载，群内仍用自然语言提出目标，无须手写这些内部命令。

## 查看帮助

`mc_query` 的 `argv` 是参数数组，从查询类别开始；不填写 `mcai`、`query`、实例 ID 或安装路径。路径中的中文、空格、反斜杠均放在同一个字符串中。

```json
{"argv":["--help"]}
{"argv":["files","read","--help"]}
{"argv":["nbt","select","--help"]}
```

顶层帮助列出类别，类别及子命令帮助说明用途、必填参数、单位和示例。布尔开关采用 `--regex`／`--no-regex` 等形式；数组和对象作为 JSON 字符串传入。输入错误时沿返回的具体用法修正，不重新收集已有效证据。

## 常见查询

| 目标 | 类别与用法 |
|---|---|
| 读取配置 | `files read --path server.properties --line-count 30` |
| 检索文本 | `files search --glob config/**/*.toml --query timeout` |
| 定向查询日志 | `logs search --query Exception --glob logs/**/*.log*` |
| 查看独立 NBT 结构 | `nbt read --path level.dat --nbt-path '["Data"]' --view children` |
| 区域存档／方块查询 | `region-nbt`、`region-blocks` |
| 区域检查、导出或扫描 | `region-check`、`region-export`、`region-scan` |
| 实例进程与 JVM 采样 | `diagnostics process`、`diagnostics jvm --samples 1` |
| 新图生成或区块存盘时卡顿 | `diagnostics chunk-jfr` 默认静默录制 60 秒，沿后台结果读取 |
| GC 停顿、分配热点与老对象 | `diagnostics memory-jfr --duration-seconds 25`，允许 10–60 秒，需 JDK 11+，与当前 Probe 慢拍对齐 |
| 持续观察内存与 GC | `diagnostics memory-trend --duration-seconds 300 --interval-seconds 60`，静默采样 |
| 实时类实例和字节排行 | `diagnostics class-histogram --top 30`，可能暂停 JVM，按需执行 |
| 采集在线堆转储 | `diagnostics heap-dump --pid 1234 --admin-feedback-id 实际反馈编号`，群内任务须管理员明确同意并通过独立审核 |
| 已有堆转储的持有链 | `diagnostics hprof-summary --path dumps/capture.hprof.gz`，流式读取已有 `.hprof` 或 `.hprof.gz` |
| 查已留证的故障 | `incidents list`；按返回的事件编号用 `incidents show`、`incidents console` 定向查看 |

群里只需描述问题，例如「生存服刚才崩了」或「一跑新图就卡」。Agent 会自己挑选查询。只有需要玩家或管理员当场进服复现时，任务内的 `diagnostics chunk-jfr` 才传 `--notify-user`；A 观察到录制已开始且尚未结束时在任务群提醒一次，然后继续读取结果。直接在 B CLI 运行没有任务群可通知；内存 JFR 始终没有复现提醒，结果直接附带 GC 次数、Full GC、GC 后堆趋势、Top 分配热点和老对象样本数等紧凑摘要，完整分析仍可按引用分页读取。JFR 报告区分不支持、录制期间未观察到和录制不完整；`hprof-summary` 严格校验 HPROF 文件头、记录帧与分段结束标记完整性。区块生成有实测时长；区域读写只提供时间点、次数与字节数。

内存趋势允许采样 120–1200 秒、间隔 30–120 秒，默认分别为 300、60 秒。优先用 Probe 读取堆、GC 和服内指标；Probe 不可用时保留进程采样，有可用 `jcmd` 则补采堆概要。结束后默认附加 30 秒内存 JFR（允许 10–60 秒），可用 `--no-include-jfr` 关闭。堆转储可用 `--compress` 直接生成 `.hprof.gz`；通过群内任务执行时，顶层 `evidence_ids` 引用已结算的 `process` 或 `jvm` 结果供审核。

`/mcaiask` 的 JVM 诊断只开放 `process` 和 `jvm`；内存趋势、JFR、堆转储和离线分析通过排障任务使用。

例如 AI 的读取参数为：

```json
{"argv":["files","read","--path","server.properties","--line-count","30"]}
```

NBT 的路径、选择器与相对路径配合示例：

```json
{"argv":["nbt","select","--path","playerdata/player.dat","--nbt-path","[\"Inventory\"]","--selector","{\"by\":\"slot\",\"slot\":0}","--relative-path","[\"id\"]"]}
```

先查看 `children` 得到真实结构，再按 UUID、方块实体位置、Slot 或字段匹配选中对象。相对路径从所选对象内开始。SNBT 的值保留类型，例如 `1b`、`2L` 和带引号字符串；修改预览中的 `expected=null` 仅表示已核实新字段不存在。

NBT 节点太大时，查询返回原路径、字节数及可展开的子节点概览。沿原路径用 `children` 逐层查找，再按需读取具体字段；多条结果按返回的续页偏移继续。

区域 NBT 的 `x/z` 使用全局区块坐标；单点方块读取的 `block-x/y/z` 使用全局方块坐标。存档查询反映已保存数据，活动现场通过 Probe 查询。

日志默认按完整多行异常归组，返回次数、时间范围和首条原文。tick、耗时、UUID 和实体坐标等抖动不会单独开组，端口和普通错误码仍区分。时间仅从行首日志头解析；正文与续行继承本条事件时间，损坏的时间头标为时间未知。返回 `partial: true` 时，计数只覆盖已扫部分；缩小文件名或时间范围再查。查询和预览不会执行生产修复；实际修改继续提交方案，经审核和批准后执行。

## 结果与后续操作

返回沿用 `ok/data`、证据引用及 `next_call`。后台状态由 `data.status` 表示，`complete` 说明读取范围；发起查询后沿原 `job_id` 等待和续读，`mc_job_wait` 在有新增输出事件或任务结束时立即返回。长字段先看概览，用路径或文本定位取回必要部分。未知执行状态沿原 `operation_id` 查询，不换编号重跑。

控制台、Probe、验证、网页、下载和提案工具通过 `mc_tools` 按名称加载，详细说明与示例同时返回；暂停和重启保留当前任务已加载集合。安装更新保留用户编辑的运行时规则文件。

## 在 B 的虚拟环境中运行

CLI 与 AI 入口使用相同参数解析和底层查询。无需全局安装或修改系统 PATH：

```powershell
& 'D:\MCAI\.venv\Scripts\python.exe' -m mcai --config 'D:\MCAI\host.json' query cti files read --path server.properties --line-count 30
& 'D:\MCAI\.venv\Scripts\python.exe' -m mcai query cti nbt select --help
```

子命令帮助无需连接 B。普通查询返回 JSON；耗时工作可能返回后台任务句柄，AI 任务通过现有后台与产物工具续读。

B 也会拒绝缺少非空 `--admin-feedback-id` 的堆转储请求；反馈身份核对和独立审核在 A 的群任务流程中进行。
