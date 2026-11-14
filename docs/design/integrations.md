# 存档、联网与下载

[设计索引](README.md) · [配置说明](../usage/configuration.md) · [第三方来源](../development/third-party.md)

## Java版存档

单独NBT使用 `nbtlib`，区域容器使用独立Java21+辅助程序和固定MCA Selector 2.9官方JAR，复用配套Querz NBT接口。辅助程序通过标准输入／输出交换JSON请求和结果行，日志走标准错误与本地文件，不启动GUI。

| 范围 | 当前处理 |
|---|---|
| 单独 `.dat/.nbt` | 保留gzip形式与NBT类型，用带类型SNBT读写 |
| `.mca` | gzip、zlib、未压缩、LZ4及外部 `.mcc` |
| 旧 `.mcr` | 在任务副本中使用兼容文件名交给后端，保留原始NBT结构 |
| 多版本实体 | 旧 `Level.Entities/TileEntities` 与新版独立实体区域 |
| 世界发现 | 原版、Bukkit分离世界、模组维度中的 `region/entities/poi` |
| 检索统计 | 实体类型、不同UUID表示、方块坐标范围、NBT字段条件；按类型／区块计数与排行 |

每条结果携带世界／维度、区域文件、全局区块坐标、NBT路径和 `DataVersion`。负坐标按向下取整处理。未知模组字段保留，不自动转换世界版本。

独立NBT和区域读取支持`selector`：按UUID（字符串、四整数及Most/Least表示）、方块实体`x/y/z`、物品`Slot`或带类型字段匹配；`relative_path`指向选中对象内字段。`mode: select`返回匹配数量、实际路径和SNBT，`preview_batch`验证并预览批量修改，不写文件。查询可返回多个匹配，实际修改要求每项唯一。

批量修改用`nbt_batch`或同一个区域文件的`region_batch`，每项`changes`包含`op: set/delete`、`nbt_path`、可选`selector/relative_path`和必填`expected`；`set`另有带类型SNBT的`value`。`expected: null`只表示新字段原先不存在，不能用来跳过旧值检查。区域每项另带全局区块`x/z`。一次最多1000项，先按原状态解析全部目标并校验旧值／重叠，之后应用修改；同列表多项删除按原下标处理，不因前一次删除漂移。数组保留Byte/Int/Long类型重建，未修改字段保留。

同一区域批量操作只采集一次副本，按目标区块读取，统一修改后一次保存、重新读取校验，再进入原文件替换与MCC备份路径；正常编辑仍拒绝丢弃损坏的邻居。一个批量步骤失败不会写入候选内容；多个文件步骤仍按既有逐步执行和失败保留现场语义运行，不承诺跨文件事务。

## 方块坐标与状态

`mc_region_blocks`的`get`按`block_x/block_y/block_z`查询一个已存储方块及对应方块实体；`search`按全局区块`x/z`查询该区块的已存储section，可按注册名`name`或旧数字`legacy_id`过滤，分页列表或`by_state`计数。支持现代`sections.block_states`、旧`Level.Sections.Palette/BlockStates`、旧Anvil数字`Blocks/Data/Add`，以及只读MCR列式数组；缺少section明确返回未存储，不当作空气或在线状态。

方案`block_set`提供文件、方块坐标、完整带类型SNBT的`expected/state`。调色板修改重编码索引，按DataVersion区分连续与padded布局，保留其他方块和未知字段；旧数字写入限定ID 0至255和Data 0至15，含扩展ID的区块拒绝推测。方块类型变化且有方块实体时，必须用`remove_block_entity`明确提交其完整旧SNBT；只删方块实体不重编码方块缓存。通过原编解码器校验候选，再停服备份替换，MCC沿用原机制。

变更方块会失效光照缓存；现代Heightmaps交服务端重建，旧Anvil HeightMap使用固定MCA Selector算法重算。没有足够版本信息确定布局、过渡快照HeightMap与调色板混用、MCR语义写入或缺少section时明确拒绝，不升级世界、不创建未知section。此工具不运行游戏逻辑，也不会同步推断模组自有缓存、结构、计划刻或POI；涉及这些数据需按目标版本和模组进一步验证。活动区块优先使用服务端命令；离线恢复后需重启并核对实际效果。

## 区块检查、导出与点恢复

`mc_region_check`检查扇区头、负载长度、MCC存在性、重叠和可解码NBT；带全局区块`x/z`时只检查指定位置，并返回`fingerprint`。默认同时纳入同维度`region/entities/poi`的同一坐标，`include_related: false`可明确缩小到当前文件。缺少完整8192字节区域头时不能保证其他区块，点修复拒绝继续；可考虑已有完整备份恢复。

`mc_region_export`把指定位置的原始压缩记录、外部MCC和来源清单保存到B的`jobs/<job_id>/chunk.zip`，不会安装或修改存档。可带`backup`从同规范目录的原备份提取，备份须实际覆盖所选关联文件；目录备份覆盖其子项。清单记录源目录、维度路径、坐标、DataVersion、来源备份和采集时间，归档计算SHA-256。损坏／采集中变化的导出仍留现场但`usable: false`，不能用于恢复；二进制ZIP供B本地保存或后续操作，`mc_artifact_read/find`用于文本产物。

方案`region_restore`需提供`path/x/z/export_id/expected`，`expected`为当前点检查得到的关联指纹，且检查与导出使用相同关联范围。审核读取导出来源清单；执行前复核归档哈希、规范目录、维度路径和坐标，停服并备份全部实际区域／MCC目标。只追加导出记录并更新目标头项，保留未选择扇区的原始字节，能保留不可解码的邻居；候选先由原Java后端重新读取验证，之后才替换生产文件。源压缩方式和NBT结构保留，不迁移世界版本。

确需删除损坏区块、等待服务端按其正常机制重新生成时，使用批准方案`region_remove`，同样声明坐标和当前关联指纹，默认处理关联数据并保留备份。它不主动加载／生成区块。恢复和删除均不跨路径搬迁区块；已无差异的内容不重复重写。多关联文件逐个替换，失败时原操作记录`writing/written_files`，保留已完成部分与备份，不自动重跑或回滚。

在线扫描逐区域复制区域及关联外部文件到任务临时目录，记录采集时间和源文件是否变化。每实例同时一个扫描，不同实例可并行；一次批量扫描复用一个JVM。损坏区块和不支持格式返回位置及部分完成状态，不静默跳过。

磁盘只代表已保存内容。活动区块优先用服务端命令、jcmd和已有spark；强制保存经批准，不默认停服或 `save-all flush`。区域修改在停服备份后编辑副本，重新读取验证再替换；外部MCC新增、修改、移除进入修改与恢复清单。

开发时下载固定依赖走代理并校验SHA-256，B发行包包含所需JAR，运行时不联网下载。辅助Java与实例Java分别配置。

## 搜索与网页

主模型使用公开Responses托管 `web_search`，按配置可选 `web_search_preview`。与MC函数工具合并，不能覆盖原工具列表。只在主排障请求启用，审核和验收总结不带搜索工具。

另提供 `mc_search`，按固定Codex协议调用提供商的独立 `alpha/search`，实现搜索、打开来源和页内查找。与托管搜索分别配置，Chat也可使用。复用提供商HTTP客户端、代理、鉴权和任务级搜索会话；可读结果与来源持久化，重载后续读；加密字段不进入对话。配置和一键测试见[配置设计](configuration.md)。

服务商明确不支持时在本轮关闭并告知模型，网络临时失败继续有限重试。搜索调用、动作、来源和引用落本地记录；结论保留必要URL，避免模型响应转换时丢失引用。网页资料不能改变生产操作规则。

`mc_web`在A使用HTTP获取明确URL，trafilatura提取正文，保留标题、链接、最终URL和时间。支持HTML、纯文本和JSON；页面持久化为任务引用，按偏移读取或查找，重载后可续读。当前获取上限5 MiB、超时30秒；不支持内容、需登录或动态渲染时明确失败，不自动部署浏览器或抓取服务。

## MOD元数据与下载

本地安装情况使用`mc_inventory`：读取Forge／NeoForge TOML、Fabric／Quilt JSON、Bukkit／Paper YAML、数据包`pack.mcmeta`，不按JAR文件名推断身份。Fabric嵌套JAR及Forge JarJar同时解析；元数据最多2MiB，嵌套JAR最多3层、单个64MiB，超限和损坏明确报告。每个物理文件计算SHA-256，目录数据包按文件名及内容汇总哈希。清单保存为后台任务产物`inventory.json`，再次查询带`baseline: 先前job_id`返回新增、删除和内容／版本变化；基线须属于同实例、同规范目录且已完成，部分基线会标明；损坏或未知归档会使清单标记partial。

清单列出重复ID、仅客户端声明、未找到的必需依赖和数值版本范围不匹配。常见精确、比较、通配和Maven区间可检查；不支持的版本语法明确`version_unverified`，不能据此判定兼容。可从实际JVM参数、所选JDK的release及实际主JAR的version.json确认部分运行版本，其他MC／加载器要求返回`runtime_requirement_unverified`。清单是磁盘声明与取证线索，不证明某个MOD已成功加载，也不自动安装、卸载或解决依赖。

B通过Modrinth v2及CurseForge官方API查询项目、说明、版本、加载器、依赖和文件。Modrinth设置项目User-Agent；CurseForge API及官方CDN携带B配置的 `x-api-key`，密钥不进入模型与审核材料，无关重定向不转发源站凭据。

先核对MC版本、加载器和服务端适用性，再明确选择文件。返回必需、可选等依赖关系供模型判断，不默认最新版、不自动安装可选依赖。分发受限、无官方下载链接或凭据错误明确失败，不猜测CDN地址。

下载复用B后台任务和原操作编号，完成前写临时文件，校验网站哈希并计算本地SHA-256后才发布可用记录。默认每次请求最长600秒、文件2 GiB，网络临时错误最多3次；重试重新写临时文件。取消可打断网络等待，B重启不自动重新下载。

`mc_download`提供通用HTTP／HTTPS直链暂存，可传期望SHA-256。完成记录关联实例、任务、来源、大小、哈希和项目版本；未完成、跨任务或被更改的文件不能用于安装。

## 批准安装

```json
{
  "action": "install_download",
  "download_id": "已完成下载的操作编号",
  "path": "mods/new-version.jar",
  "remove_paths": ["mods/old-version.jar"]
}
```

该步骤必须放入 `mc_propose`。审核读取下载元数据、目标和替换范围，管理员批准后B再次校验，进入停服、备份、安装和验证流程。新增目标的原先不存在状态与旧文件内容都写入备份，支持恢复时撤销新增文件。

暂存不自动安装或执行。下载BAT／PS1／Python后要运行时，仍需提交实际脚本正文接受审核，正式修改经批准。通用脚本的范围约束见[审核设计](agent.md)。
