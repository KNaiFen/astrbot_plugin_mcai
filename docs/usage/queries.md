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

检索词以负号开头时，也可独立传入，例如 `["files","search","--glob","*.log","--query","-241,-318"]`。检索词若与当前子命令的选项同名，用等号传入，例如 `--query=--help`。

## 常见查询

| 目标 | 类别与用法 |
|---|---|
| 读取配置 | `files read --path server.properties --line-count 30` |
| 检索文本 | `files search --glob config/**/*.toml --query timeout` |
| 定向查询日志 | `logs search --query Exception --glob logs/**/*.log*` |
| 查看独立 NBT 结构 | `nbt read --path level.dat --nbt-path '["Data"]' --view children` |
| 跨玩家／独立 NBT 检索 | `nbt scan --scope playerdata`、`nbt scan --scope saved_data --query village` |
| 区域存档／方块查询 | `region-nbt`、`region-blocks` |
| 批量方块修改预览 | `region-blocks preview-batch`，参数见[批量方块预览](#批量方块预览) |
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

## 维度与坐标自动定位

先用 `mc_status` 查看实际世界路径。区域查询可提供明确的 `--path`，也可省略文件名，用 `--dimension` 和坐标解析已存在区域；多世界时用 `--world-path` 指定世界根目录或实际维度目录。自动定位的查询仍须提供 `--dimension`，不能仅凭 `--world-path`。单点方块用 `--block-x/y/z`，区域NBT用全局区块 `--x/--z`；点检查／导出可用区块坐标或 `--block-x/--block-z` 二选一。负坐标向下取整，例如方块 `(-1,64,-1)` 位于区块 `(-1,-1)`、区域 `r.-1.-1`。

```json
{"argv":["region-blocks","read","--dimension","minecraft:overworld","--block-x","-1","--block-y","64","--block-z","-1"]}
{"argv":["region-blocks","read","--world-path","world/DIM-1","--dimension","minecraft:the_nether","--block-x","1","--block-y","64","--block-z","1"]}
{"argv":["region-nbt","read","--dimension","-1","--dataset","region","--x","-1","--z","-1","--view","children"]}
{"argv":["region-nbt","read","--dimension","minecraft:overworld","--dataset","entities","--x","0","--z","0","--view","children"]}
```

标准维度为 `minecraft:overworld`、`minecraft:the_nether`、`minecraft:the_end`；旧版（含1.7.10）支持数字 `0/-1/1/其他整数` 或 `DIM<number>`，模组维度 `mod:dimension` 对应 `dimensions/mod/dimension`。发现范围包括Bukkit分离世界，例如下界实际目录可为 `world_nether/DIM-1`。世界与维度条件须唯一匹配；返回多个候选时，用返回的实际目录补充 `--world-path`，或以明确 `--path` 查询单文件。自动定位不创建未保存的区块或区域；物理 `--dataset` 为 `region/entities/poi`，默认 `region`，其中仅 `region` 在 `.mca` 不存在时回退 `.mcr`。`region-blocks`固定读取方块区域，不接受这个物理 `--dataset`。

区域扫描只传 `--world-path` 时，填写实际维度目录，例如下界是 `world/DIM-1`；也可用 `--world-path world --dimension minecraft:the_nether` 从世界根目录定位。扫描的 `--dataset` 表示逻辑数据类型，和单文件查询的物理目录选项不同：

```json
{"argv":["region-scan","--world-path","world/DIM-1","--dimension","minecraft:the_nether","--dataset","blocks","--name","minecraft:chest","--bounds","[-32,0,-32,31,255,31]","--result","by_chunk"]}
```

## 独立NBT扫描

`nbt scan` 启动 `nbt_scan` 后台工作。`--scope playerdata` 默认在唯一主世界的 `playerdata/*.dat` 查找，多世界时用 `--world-path` 指定主世界目录；`saved_data` 默认扫描发现维度下的 `data/*.dat`，可用 `--world-path/--dimension` 收窄到唯一目录；`glob` 必须带 `--glob` 指明实例内文件模式，可用于其他位置的NBT。它不会把文件当作普通文本检索。

```json
{"argv":["nbt","scan","--scope","playerdata","--world-path","world","--nbt-path","[\"Inventory\",\"*\"]","--contains-item","{\"id\":\"mod:gem\"}"]}
{"argv":["nbt","scan","--scope","saved_data","--query","village","--result","by_file"]}
{"argv":["nbt","scan","--scope","glob","--glob","world/playerdata/*.dat","--nbt-path","[\"EnderItems\",\"*\"]","--contains-item","{\"id\":\"minecraft:diamond\"}"]}
```

`--nbt-path` 先选择节点；`--query` 在其下按忽略大小写的字段名或字符串子串搜索，命中节点再接受 `--conditions/--contains-item` 过滤。`--contains-item` 递归查嵌套Compound和列表中的物品 `id`，包含容器内的容器、旧 `tag` 与现代 `components`；可附成对的 `nbt_path/value` 或 `conditions` 限定物品自身字段，递归超过32层报错。它筛选外层扫描对象；要以背包物品为冻结目标，应先用 `--nbt-path '["Inventory","*"]'` 选中物品。

`--result` 可为默认的 `list`、按文件计数 `by_file` 或按NBT标签类型计数 `by_type`，三者完成后均冻结目标。沿原 `job_id` 续读；读取期间文件变化会失败。`/mcaiask` 也跟踪本次问答启动的 `nbt_scan`，结束时取消尚未结算工作。

## 区域扫描与冻结清单

`region-scan --dataset` 支持 `entities/block_entities/chunks/poi/blocks`。`--bounds` 为全局方块 `[minX,minY,minZ,maxX,maxY,maxZ]`，边界包含端点。`blocks` 可用注册名 `--name` 或0–4095的旧数字 `--legacy-id` 筛选，按 `list/by_type/by_state/by_chunk/top_chunks` 返回坐标、类型、完整状态或区块计数；旧数字注册名检索依赖 `level.dat` 的FML映射。扫描只计已存储方块，不主动加载区块，也不代表实时耗时。

```json
{"argv":["region-scan","--dimension","minecraft:overworld","--dataset","blocks","--name","minecraft:chest","--bounds","[0,0,0,31,255,31]","--result","by_state"]}
{"argv":["region-scan","--world-path","world","--dataset","block_entities","--contains-item","{\"id\":\"mod:gem\"}","--result","list"]}
{"argv":["region-scan","--world-path","world","--dataset","block_entities","--conditions","[{\"path\":[\"Items\",\"*\",\"id\"],\"op\":\"eq\",\"value\":\"\\\"mod:gem\\\"\"}]","--capture-targets","--result","by_type"]}
```

实体／方块实体的 `--conditions` 支持 `exists/eq/ne/gt/ge/lt/le/contains`；`exists` 只需 `path`，其余需带类型SNBT字符串 `value`。路径里的 `*` 仅展开列表／数组，各条件有任一路径命中即可，多个条件全部满足。`contains` 对字符串检查子串、对列表／数组检查带类型元素、对Compound检查字符串键。`--contains-item` 用法与独立NBT扫描相同；这些NBT过滤不应用于 `dataset=blocks`，方块按名称、数字ID及范围筛选。实体类型、UUID和范围先在Java过滤；无NBT条件和容器检索的计数模式省去完整SNBT生成。

区域扫描对 `entities/block_entities/blocks` 的 `list` 自动冻结完整目标，计数模式加 `--capture-targets` 才冻结。原后台目录内的 `targets.json` 保存精确文件、坐标／NBT路径与标签SHA-256，`manifest.json` 保存数量、文件范围和样本。摘要的 `target_fingerprint` 是目标清单内容哈希，后续提案以原 `job_id` 作为 `scan_job_id`、该指纹作为 `manifest_sha256`；不要计算 `manifest.json` 文件哈希替代。分页只限制展示，实际清理消费完整清单。

只有同实例、同目录已完成且非 `partial` 的清单可用于 `region_prune/nbt_prune`。提案还须明确删除／设置完整对象或 `relative_path` 字段；执行会复核冻结对象旧值。`region_prune by_filter`另可在停服后按明确范围筛选，必须声明匹配上限；具体字段与备份边界见[扫描与冻结清理](../design/integrations.md#跨文件扫描与冻结清理)。

## 批量方块预览

`region-blocks preview-batch` 的 `--changes` 为1–1000项JSON数组，每项用全局 `block_x/block_y/block_z`、完整带类型SNBT `state`，以及 `expected` 或 `expected_sha256`。哈希来自方块扫描中的状态标签SHA-256，不是SNBT文本哈希；两个旧值条件同时提供时都须匹配。示例中的旧状态须换成实际查询结果：

```json
{"argv":["region-blocks","preview-batch","--dimension","minecraft:overworld","--changes","[{\"block_x\":1,\"block_y\":64,\"block_z\":1,\"expected\":\"{Name:\\\"minecraft:stone\\\"}\",\"state\":\"{Name:\\\"minecraft:air\\\"}\"}]"]}
```

也可用 `--path world/region/r.0.0.mca` 固定一份区域文件；自动定位时按实际区域与区块分组，重复坐标拒绝。预览不落盘，实际修改通过 `mc_propose` 的 `block_batch`。类型变化且存在方块实体时，每项须用 `remove_block_entity` 提交完整旧SNBT。标准Anvil `Blocks/Data/Add`支持0–4095数字ID与0–15元数据；未知扩展数组仍拒绝方块写入，MCR列式方块仍只读，详见[方块边界](../design/integrations.md#方块坐标与状态)。

## 结果与后续操作

返回沿用 `ok/data`、证据引用及 `next_call`。后台状态由 `data.status` 表示，`complete` 说明读取范围；发起查询后沿原 `job_id` 等待和续读，`mc_job_wait` 在有新增输出事件或任务结束时立即返回。长字段先看概览，用路径或文本定位取回必要部分。未知执行状态沿原 `operation_id` 查询，不换编号重跑。

控制台常用操作、Probe 常用诊断、提案、独立验证和多轮收尾可直接调用。网页、下载等专项工具通过 `mc_tools` 按名称加载，详细说明与示例同时返回；暂停和重启保留当前任务已加载集合。`mc_tools` 也可以查询默认工具的帮助。安装更新保留用户编辑的运行时规则文件。

## 在 B 的虚拟环境中运行

CLI 与 AI 入口使用相同参数解析和底层查询。无需全局安装或修改系统 PATH：

```powershell
& 'D:\MCAI\.venv\Scripts\python.exe' -m mcai --config 'D:\MCAI\host.json' query cti files read --path server.properties --line-count 30
& 'D:\MCAI\.venv\Scripts\python.exe' -m mcai query cti nbt select --help
```

子命令帮助无需连接 B。普通查询返回 JSON；耗时工作可能返回后台任务句柄，AI 任务通过现有后台与产物工具续读。

B 也会拒绝缺少非空 `--admin-feedback-id` 的堆转储请求；反馈身份核对和独立审核在 A 的群任务流程中进行。
