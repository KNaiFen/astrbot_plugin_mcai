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
| 新图生成或区块存盘时卡顿 | `diagnostics chunk-jfr`，边重现边录 60 秒，沿后台结果读取 |
| 查已留证的故障 | `incidents list`；按返回的事件编号用 `incidents show`、`incidents console` 定向查看 |

群里只需描述问题，例如「生存服刚才崩了」或「一跑新图就卡」。Agent 会自己挑选查询。区块录制实际开始后，群里会收到一条复现提醒；按原操作跑一趟即可，Agent 会继续读取结果，无需回复才能继续。JFR 报告区分不支持、录制期间未观察到和录制不完整。区块生成有实测时长；区域读写只提供时间点、次数与字节数。

例如 AI 的读取参数为：

```json
{"argv":["files","read","--path","server.properties","--line-count","30"]}
```

NBT 的路径、选择器与相对路径配合示例：

```json
{"argv":["nbt","select","--path","playerdata/player.dat","--nbt-path","[\"Inventory\"]","--selector","{\"by\":\"slot\",\"slot\":0}","--relative-path","[\"id\"]"]}
```

先查看 `children` 得到真实结构，再按 UUID、方块实体位置、Slot 或字段匹配选中对象。相对路径从所选对象内开始。SNBT 的值保留类型，例如 `1b`、`2L` 和带引号字符串；修改预览中的 `expected=null` 仅表示已核实新字段不存在。

区域 NBT 的 `x/z` 使用全局区块坐标；单点方块读取的 `block-x/y/z` 使用全局方块坐标。存档查询反映已保存数据，活动现场通过 Probe 查询。

日志默认按完整多行异常归组，返回次数、时间范围和代表栈；需要核实具体细节时再选择原文。查询和预览不会执行生产修复；实际修改继续提交方案，经审核和批准后执行。

## 结果与后续操作

返回沿用 `ok/data`、证据引用及 `next_call`。后台状态由 `data.status` 表示，`complete` 说明读取范围；发起查询后沿原 `job_id` 等待和续读。长字段先看概览，用路径或文本定位取回必要部分。未知执行状态沿原 `operation_id` 查询，不换编号重跑。

控制台、Probe、验证、网页、下载和提案工具通过 `mc_tools` 按名称加载，详细说明与示例同时返回；暂停和重启保留当前任务已加载集合。安装更新保留用户编辑的运行时规则文件。

## 在 B 的虚拟环境中运行

CLI 与 AI 入口使用相同参数解析和底层查询。无需全局安装或修改系统 PATH：

```powershell
& 'D:\MCAI\.venv\Scripts\python.exe' -m mcai --config 'D:\MCAI\host.json' query cti files read --path server.properties --line-count 30
& 'D:\MCAI\.venv\Scripts\python.exe' -m mcai query cti nbt select --help
```

子命令帮助无需连接 B。普通查询返回 JSON；耗时工作可能返回后台任务句柄，AI 任务通过现有后台与产物工具续读。
