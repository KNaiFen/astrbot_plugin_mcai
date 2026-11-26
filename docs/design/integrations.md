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
| 检索统计 | 实体类型、不同UUID表示、方块坐标范围、NBT字段条件与容器搜物；按类型／状态／区块计数与排行 |

每条结果携带世界／维度、区域文件、全局区块坐标、NBT路径和 `DataVersion`。负坐标按向下取整处理。未知模组字段保留，不自动转换世界版本。

区域查询与修改可显式指定实例内 `path`，也可用 `dimension` 和坐标自动定位，多世界时用 `world_path` 限定实例内实际维度目录。标准维度 `minecraft:overworld`、`minecraft:the_nether`、`minecraft:the_end` 分别对应主世界、`DIM-1`、`DIM1`；模组资源名 `mod:dimension` 对应 `dimensions/mod/dimension`，1.7.10 等旧世界可用数字维度 `0/-1/1/其他整数` 或 `DIM<number>`。发现范围包括 Bukkit 分离世界目录，例如 `world_nether/DIM-1`；世界与维度条件必须唯一匹配，多个候选或未找到时返回候选路径，不猜测目标。具体用法见[自动定位](../usage/queries.md#维度与坐标自动定位)。

`block_x/block_z` 先向下取整到区块，再由全局区块 `x/z` 向下取整到区域坐标。自动定位的物理 `dataset` 为 `region/entities/poi`，默认 `region`；先找 `.mca`，仅 `region` 在 `.mca` 不存在时回退同坐标 `.mcr`。显式 `path` 直接指定文件，不再按维度推断。自动定位要求目标文件已存在，不创建区域或区块。

独立NBT和区域读取支持`selector`：按UUID（字符串、四整数及Most/Least表示）、方块实体`x/y/z`、物品`Slot`或带类型字段匹配；`relative_path`指向选中对象内字段。`mode: select`返回匹配数量、实际路径和SNBT，`preview_batch`验证并预览批量修改，不写文件。查询可返回多个匹配，实际修改要求每项唯一。

批量修改用`nbt_batch`或`region_batch`，每项`changes`包含`op: set/delete`、`nbt_path`、可选`selector/relative_path`，并提供带类型SNBT的`expected`或64位十六进制`expected_sha256`；`set`另有带类型SNBT的`value`。哈希针对目标标签的二进制NBT载荷，不是SNBT文本或整份文件；两者同时提供时都须匹配。`expected: null`只表示新字段原先不存在，不能与哈希并用，也不能跳过旧值检查。区域每项另带全局区块`x/z`；自动定位可按实际区域文件分组。一次最多1000项，同一文件内先按原状态解析全部目标并校验旧值／重叠，之后应用修改；同列表多项删除按原下标处理，不因前一次删除漂移。数组保留Byte/Int/Long类型重建，未修改字段保留。

同一区域批量操作只采集一次副本，按目标区块读取，统一修改后一次保存、重新读取校验，再进入原文件替换与MCC备份路径；正常编辑仍拒绝丢弃损坏的邻居。一个批量步骤失败不会写入候选内容；多个文件步骤仍按既有逐步执行和失败保留现场语义运行，不承诺跨文件事务。

区域写入保留全部原有扇区，只追加编辑过的压缩记录并更新目标头项；旁邻记录和时间戳原字节保留。目标区块通过二进制NBT与Python交换，Float／Double保留原始IEEE位（含负零和NaN载荷），不经整块SNBT往返。单独NBT使用同样的浮点保真读取；旧值比较区分浮点位。旧HeightMap只取固定上游算法的计算结果，不将算法解码的其他字段写回。候选重新解压后按二进制字节核对；外置MCC仍进入原备份与替换范围。

## 跨文件扫描与冻结清理

`mc_region_scan` 通过查询CLI的 `region-scan` 启动后台扫描，逻辑 `dataset` 为 `entities/block_entities/chunks/poi/blocks`。实体与方块实体支持 `entity_type`、UUID、三维方块 `bounds`、NBT `conditions` 和 `contains_item`；现代独立实体文件存在时优先读取，避免旧区块实体副本重复计数。`dataset=blocks` 按注册名 `name`、旧数字 `legacy_id` 和三维范围筛选已存储方块，支持列表、`by_type/by_state/by_chunk/top_chunks` 计数；Java 先按范围与调色板注册名排除无关区块，Python 解码命中区块并计数。方块扫描不应用实体NBT条件或容器搜物条件。

实体类型、UUID与范围过滤下推到Java。无 `conditions/contains_item` 的 `by_type/by_chunk/top_chunks` 使用轻量行，不生成完整对象SNBT；冻结目标时由Java直接计算目标标签原始二进制载荷的SHA-256。NBT条件与容器递归仍在Python执行。条件 `path` 中的 `*` 只展开列表／数组元素；每个条件任一实际路径满足即可，多个条件全部满足。`contains` 对字符串做子串匹配、对列表／数组做带类型元素匹配、对Compound检查字符串键是否存在。

`contains_item: {id, nbt_path?, value?, conditions?}` 递归搜索Compound和列表中的物品 `id`，覆盖嵌套容器、旧 `tag` 与现代 `components` 结构；可用成对 `nbt_path/value` 或 `conditions` 限定该物品标签，递归超过32层明确报错。它筛选包含物品的扫描对象，不自动将匹配物品改成修改目标。

`mc_nbt` 的 `scan`（CLI：`nbt scan`）作为 `nbt_scan` 后台任务扫描独立NBT。`scope=playerdata` 默认唯一主世界的 `playerdata/*.dat`，多世界可用 `world_path` 指定主世界；`saved_data` 默认扫描发现维度的 `data/*.dat`，可用 `world_path/dimension` 收窄；`glob` 使用实例内显式文件模式。`nbt_path` 可含列表／数组通配符；`query` 在选中节点下按忽略大小写的字段名／字符串子串检索，另支持相同的 `conditions/contains_item`。结果可为 `list/by_file/by_type`；读取期间文件大小或修改时间变化会失败，不发布可用清单。

独立NBT扫描完成后始终冻结目标；区域扫描对 `entities/block_entities/blocks` 的列表结果自动冻结，计数模式需显式 `capture_targets=true`。完整目标保存在原后台目录的 `targets.json`，`manifest.json` 记录实例目录、数据集、文件范围、数量、前5个样本及 `partial`；结果摘要返回 `target_count/target_files_count/target_fingerprint`。`target_fingerprint` 是 `targets.json` 内容的SHA-256，后续作为 `manifest_sha256`，并非 `manifest.json` 文件哈希。显示分页或缩略不会缩小冻结目标范围。

批准方案的清理步骤沿用停服、备份、候选校验与失败留现场流程：

| 步骤 | 输入与边界 |
|---|---|
| `region_prune`，`mode=from_scan` | 必填 `scan_job_id/manifest_sha256/op`，只接受本实例同目录已完成、非partial的实体／方块实体／方块冻结清单；执行按原文件、坐标／路径及目标哈希核对，不重新筛选扩大范围 |
| `region_prune`，`mode=by_filter` | 必填 `dataset/bounds/max_matches/op`、`world_path`或`dimension`，且按数据集强制约束筛选与操作字段：实体／方块实体必填非空 `entity_type`（禁用 `name/legacy_id/state/clear_block_entity`），方块必填 `name` 或 `legacy_id` 且仅限 `op=set` 与 `state`（禁用 `entity_type/conditions/contains_item/value/relative_path/expected`）；`max_matches` 为1–100000。审核先列候选区域及MCC文件，精确目标停服后筛选，超过上限整步不写入 |
| `nbt_prune` | 必填 `scan_job_id/manifest_sha256/op`，消费已完成的独立NBT冻结清单；根目标删除会删除整份文件，根目标设置须为Compound |

实体／方块实体和独立NBT清理的 `op=delete/set` 默认作用于完整匹配对象：`set` 须提供带类型 `value`（不能同时提交 `state`），`delete` 不接受 `value` 或 `state`；可用 `relative_path` 只改对象内字段，可选 `expected` 再核对字段旧值，执行前仍核对完整冻结对象哈希。方块清理只接受 `op=set` 与完整 `state`（不能同时提交 `value`），删除方块须设为目标版本的空气状态；`clear_block_entity=true` 才自动移除对应唯一方块实体，歧义则拒绝。所有区域候选准备完成后才开始替换；跨文件安装失败仍按既有逐文件记录保留现场，不承诺跨文件事务。

## 方块坐标与状态

`mc_region_blocks`的`read`按`block_x/block_y/block_z`查询一个已存储方块及对应方块实体；`search`按全局区块`x/z`查询该区块的已存储section，可按注册名`name`或旧数字`legacy_id`过滤，分页列表或`by_state`计数。支持现代`sections.block_states`、旧`Level.Sections.Palette/BlockStates`、旧Anvil数字`Blocks/Data/Add`，以及只读MCR列式数组；缺少section明确返回未存储，不当作空气或在线状态。

方案`block_set`提供文件或维度、方块坐标、完整带类型SNBT的`expected/state`；`block_batch`用1–1000项`changes`，每项提供方块坐标、`state`与`expected`或`expected_sha256`，按实际区域和区块分组，重复坐标拒绝。`mc_region_blocks preview_batch`使用相同批量参数只预览，不写盘。调色板修改重编码索引，按DataVersion区分连续与padded布局，保留其他方块和未知字段。

旧Anvil支持标准`Blocks/Data/Add`的12-bit数字ID写入，状态格式为`{Id:整数,Data:元数据b}`，ID范围0–4095、Data范围0–15；按需建立或更新`Add`半字节数组。读取`level.dat`中FML `ItemData`或`Registries.minecraft:blocks.ids`映射，辅助显示和按注册名查询；写入仍明确使用数字`Id/Data`。包含`Blocks16/Add2/Data16/BlocksB2/BlockIDs`等未知扩展数组的区块明确拒绝方块语义写入；GTNH等自定义节格式须按实际数组判断，读取成功不能推定可写。MCR列式方块仍只读。

方块类型变化且有方块实体时，`block_set/block_batch`必须用`remove_block_entity`明确提交其完整旧SNBT；只删方块实体不重编码方块缓存。通过原编解码器校验候选，再停服备份替换，MCC沿用原机制。

变更方块会失效光照缓存；现代Heightmaps交服务端重建，旧Anvil HeightMap使用固定MCA Selector算法重算。没有足够版本信息确定布局、过渡快照HeightMap与调色板混用、MCR语义写入或缺少section时明确拒绝，不升级世界、不创建未知section。此工具不运行游戏逻辑，也不会同步推断模组自有缓存、结构、计划刻或POI；涉及这些数据需按目标版本和模组进一步验证。活动区块优先使用服务端命令；离线恢复后需重启并核对实际效果。

## 区块检查、导出与点恢复

`mc_region_check`检查扇区头、负载长度、MCC存在性、重叠和可解码NBT；带全局区块`x/z`时只检查指定位置，并返回`fingerprint`。默认同时纳入同维度`region/entities/poi`的同一坐标，`include_related: false`可明确缩小到当前文件。文件存在但缺少完整8192字节区域头时只说明当前无法验证，返回文件体积、修改时间和采集变化，点修复拒绝继续；显式传入 `path` 且目标文件不存在时仍可完成点检查并返回对应空缺关联指纹，供 `region_restore` 恢复重建。在线新世界可能尚未落盘，应结合服务端状态／Probe或正常停服后复查；离线持续异常再对照完整备份。

`mc_region_export`把指定位置的原始压缩记录、外部MCC和来源清单保存到B的`jobs/<job_id>/chunk.zip`，不会安装或修改存档。可带`backup`从同规范目录的原备份提取，备份须实际覆盖所选关联文件；目录备份覆盖其子项。清单记录源目录、维度路径、坐标、DataVersion、来源备份和采集时间，归档计算SHA-256。损坏／采集中变化的导出仍留现场但`usable: false`，不能用于恢复；二进制ZIP供B本地保存或后续操作，`mc_artifact_read/find`用于文本产物。

方案`region_restore`需提供`path/x/z/export_id/expected`，`expected`为当前点检查得到的关联指纹，且检查与导出使用相同关联范围。审核读取导出来源清单；执行前复核归档哈希、规范目录、维度路径和坐标，停服并备份全部实际区域／MCC目标（显式 `path` 目标缺失时备份清单记录不存在状态，并在恢复时新建写入）。恢复优先复用可确认未被其他区块占用的目标原扇区，其次使用确认空闲的连续扇区；占用边界不可靠时跳过复用，追加时也避开其他头项声明的范围。除目标头项和写入范围外，其他字节保持不变，包括不可解码的邻居记录。候选先由原Java后端重新读取验证，之后才替换生产文件。源压缩方式和NBT结构保留，不迁移世界版本。

确需删除损坏区块、等待服务端按其正常机制重新生成时，使用批准方案`region_remove`，同样声明坐标和当前关联指纹，默认处理关联数据并保留备份。它不主动加载／生成区块。恢复和删除均不跨路径搬迁区块；已无差异的内容不重复重写。多关联文件逐个替换，失败时原操作记录`writing/written_files`，保留已完成部分与备份，不自动重跑或回滚。

在线扫描逐区域复制区域及关联外部文件到任务临时目录，记录采集时间和源文件是否变化。每实例同时一个扫描，不同实例可并行；一次批量扫描复用一个JVM。损坏区块和不支持格式返回位置及部分完成状态，不静默跳过。

磁盘只代表已保存内容。活动区块优先用服务端命令、jcmd和已有spark；强制保存经批准，不默认停服或 `save-all flush`。区域修改在停服备份后编辑副本，重新读取验证再替换；外部MCC新增、修改、移除进入修改与恢复清单。

只读NBT／方块查询和扫描按目标记录校验偏移、分配扇区及实际负载边界，完整头下的可读记录不因文件尾尚未补齐扇区而被拒绝；截断负载仍失败。整区检查仍报告文件尾异常，写入仍要求完整扇区及可解码邻居。读取不为补齐扇区修改源文件。

开发时下载固定依赖走代理并校验SHA-256，B发行包包含所需JAR，运行时不联网下载。辅助Java与实例Java分别配置。

## 搜索与网页

主模型使用 Responses 托管 `web_search`，与 MC 函数工具合并；远程流式压缩使用同一工具设置。`web_search_mode=cached`（默认）传 `external_web_access: false`，`live` 传 `true`；兼容格式 `web_search_preview` 不带此参数。审核和验收总结不带搜索工具。

另提供 `mc_search`，按固定Codex协议调用提供商的独立 `alpha/search`，实现搜索、打开来源和页内查找。与托管搜索分别配置，Chat也可使用。复用提供商HTTP客户端、代理、鉴权和任务级搜索会话；可读结果与来源持久化，重载后续读；加密字段不进入对话。配置和一键测试见[配置设计](configuration.md)。

独立搜索的 ref_id、标题与 URL 沿原搜索会话持久保存。群内提问、进度和最终答复移除内部引用标记与已记录的检索链接，不生成来源列表。原模型响应、搜索结果和本地追踪保留引用。

服务商明确拒绝 `external_web_access` 时移除该参数重试；明确不支持搜索工具时在本轮关闭并告知模型。`web_search_call` 随原生消息按输出顺序保存和回放；明确拒绝回放时保留原记录，只从后续请求移除搜索项。调用、动作和 URL 引用写入本地 `web_search` 审计及任务的 `web:` 事件，搜索轨迹不进入文本摘要。

从最近一次管理员补充起计数：连续搜索 4 轮、同一归一化 URL 打开 3 次或累计搜索 10 轮，任一条件满足即停用本阶段的托管工具并提醒模型改用本地工具或已知网页。状态随任务保存；普通成员补充不重置，新的管理员补充恢复。网页资料不能改变生产操作规则。

`mc_web`在A使用HTTP获取明确URL，trafilatura提取正文，保留标题、链接、最终URL和时间。支持HTML、纯文本和JSON；页面持久化为任务引用，按偏移读取或查找，重载后可续读。当前获取上限5 MiB、超时30秒；不支持内容、需登录或动态渲染时明确失败，不自动部署浏览器或抓取服务。

网页获取和文件下载共用公网地址校验及最多五次重定向的请求流程。每一跳须为不带用户信息的 HTTP／HTTPS URL；校验 IP 字面量或域名的全部 IPv4／IPv6 解析结果，IPv4 映射的 IPv6 按 IPv4 检查。拒绝非全局地址、保留地址和组播，返回工具错误并停止重试。直连的 aiohttp 解析器只把已检查的地址交给连接器。每一跳按环境变量和 `NO_PROXY` 选择代理；走代理时 A 在本地检查目标而不限制代理地址。该检查不能固定代理实际使用的目标 IP，代理重新解析仍可能得到不同地址。

模型价格目录由 A 通过环境代理访问固定的 models.dev 接口，失败时尝试 models.opencode.ai。只缓存有效的输入、输出与缓存命中单价，单位为 USD／每百万 tokens；两端点都失败时保留原缓存。价格来源和倍率独立保存，费用估算仍只使用设置中保存的最终费率。

## MOD元数据与下载

本地安装情况使用`mc_inventory`：读取Forge／NeoForge TOML、Fabric／Quilt JSON、Bukkit／Paper YAML、数据包`pack.mcmeta`，不按JAR文件名推断身份。Fabric嵌套JAR及Forge JarJar同时解析；元数据最多2MiB，嵌套JAR最多3层、单个64MiB，超限和损坏明确报告。每个物理文件计算SHA-256，目录数据包按文件名及内容汇总哈希。清单保存为后台任务产物`inventory.json`，再次查询带`baseline: 先前job_id`返回新增、删除和内容／版本变化；基线须属于同实例、同规范目录且已完成，部分基线会标明；损坏或未知归档会使清单标记partial。

清单列出重复ID、仅客户端声明、未找到的必需依赖和数值版本范围不匹配。常见精确、比较、通配和Maven区间可检查；不支持的版本语法明确`version_unverified`，不能据此判定兼容。可从实际JVM参数、所选JDK的release及实际主JAR的version.json确认部分运行版本，其他MC／加载器要求返回`runtime_requirement_unverified`。清单是磁盘声明与取证线索，不证明某个MOD已成功加载，也不自动安装、卸载或解决依赖。

Quilt按`quilt_loader`读取字符串／对象依赖、optional、带独立版本及组名的provides和嵌套JAR，环境来自`minecraft.environment`。组合依赖与unless条件保留原声明并返回`dependency_unverified`，不据此生成确定缺失结论；Fabric继续按自身结构读取。

A通过Modrinth v2及CurseForge官方API查询项目、说明、版本、加载器、依赖和文件。固定 API 不跟随重定向，返回的下载地址仍按公网地址规则检查。Modrinth设置项目User-Agent；CurseForge API及官方CDN使用A插件设置中的 `x-api-key`，密钥不进入模型与审核材料，无关重定向不转发源站凭据。B不访问MCAI外网。

先核对MC版本、加载器和服务端适用性，再明确选择文件。返回必需、可选等依赖关系供模型判断，不默认最新版、不自动安装可选依赖。分发受限、无官方下载链接或凭据错误明确失败，不猜测CDN地址。

下载复用A后台任务和原工具编号，完成前写临时文件，校验网站哈希并计算本地SHA-256后才发布可用记录。默认每次下载尝试（含重定向）最长600秒、文件2 GiB，网络临时错误最多3次；重试重新写临时文件。取消可打断网络等待，A重启不自动重新下载。方案审核时A经现有HTTPS传输将文件和任务元数据送入B暂存区；B核对大小和SHA-256后才接受，断线重试保持同一编号和内容身份。

`mc_download`提供通用HTTP／HTTPS直链暂存，可传期望SHA-256。完成记录关联实例、任务、来源、大小、哈希和项目版本；未完成、跨任务或被更改的文件不能用于安装。`mc_workspace`也可把A工作区生成的文件登记为同类暂存下载。

## A工作区与测试副本

`mc_workspace`把任务文件放在A插件数据目录的`workspaces/<task_id>/`，可按名称翻页列目录、按指定编码读取文本、对工作区或经`Downloads.verify`核验的`download_id`制品只读检查JAR条目（`jar_entries`）、对比两条目哈希差异（`jar_diff`）或调用同目录有`javap.exe`的JDK执行有界字节码只读检查（`javap`）、执行PowerShell 7.3+构建命令，并从B正式实例内拉取文件。列表把 `next_cursor` 传给 `after`，文本把 `next_cursor` 传给 `cursor`；文件有变化后需重新读取；三种JAR只读检查无需多轮方案或独立AI审核。构建子进程加入A端共享Job Object资源组，默认8GiB，取消结束进程树；重载后依据原后台任务与进程身份判定中断，不重新执行。工作区脚本以AstrBot Windows账号运行，不提供操作系统沙箱。

主模型与独立审核共用的任务提示词规定：MOD源码修改、编译和重新打包必须在A工作区完成，B的隔离副本也适用。主模型在制定方案和调用工具时遵守这项分工，独立审核核对实际执行位置。`stage`在A登记制品，提交`install_download`时才经HTTPS发送给B。B负责现场诊断、备份、接收和安装制品、启停与验证。

从B拉取文件中途遇到连接中断或响应未传完时，A沿同一调用从文件头重传一次，完整接收后才替换工作区目标文件；再次失败会返回错误并移除未完成文件。

管理员在 B 的 `host.json` 全局配置 `test_address` 和专用 `test_port`。`prepare_test` 在 B 任务工作区复制 `start.bat` 与显式 `paths` 或实例 `test_copy_paths` 指定的路径，并改写测试端口。列全实际存在的启动和运行依赖；源路径不存在时在审核材料阶段明确返回缺失路径，执行时也会复核。`copy_test_world`通过正式服停服、快照、恢复运行后复制所选世界路径。`mc_test_server` 支持查询测试副本状态（未创建时返回 `not_created`，已创建后区分对外配置地址与 `server.properties` 的 `listen_ip`/`listen_port`）、打开 B 独立托管窗口或关闭已停服窗口释放全局名额。接受打开及启停操作时，B 以原操作编号保留试服名额，启动前再次检查。可保留多份停止的磁盘副本，但一次只有一个试服窗口或运行中的试服；状态、查询、控制台和提案用`environment=test`访问测试副本。试服发布证据通过绑定安装记录、启动前目标JAR实际SHA-256及安装后最近一次`ready`记录验证有效性，普通配置或诊断命令不再误废未变动制品，目标JAR变化时要求重测；管理书面豁免客户端进服测试（`client_login_waived=true`）且试服已干净停止时仍需核验同SHA-256及`ready`证据。仅试服结案可通过`mc_plan_finish`记录管理员反馈豁免而不修改正式服。测试服是原任务的子环境，生产实例仍是唯一任务目标。地址和端口无效或被占用时明确失败，不自动更换目标或端口。操作步骤见[试服试玩与正式发布](../usage/operations.md#mod-试服试玩与正式发布)。

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
