# GTNH与亡者世界第二轮真实端到端测试

[开发索引](README.md) · [上一轮整改](four-servers-fixes-2026-11-17.md) · [本轮改进建议](two-servers-improvement-plan-2026-11-17.md)

本轮基线为本地dev `5d3c553`。用户授权GTNH与DeceasedCraft同时测试，各分配10GiB Java最大堆，允许在隔离副本中构造崩服、启动加载坏区块、卡顿及疑难运维场景。只记录产品问题，不在测试过程中修复产品；测试夹具问题另记。

最终统计：2026-11-17 13:06—16:12（北京时间，首末模型请求），741次持久工具调用，41／41注册工具均被真实模型调用；746次API请求包含重试与中断。两个主任务及后续经验复用任务均验收归档。主要修复链能走通，区域数据保真、审核容量恢复、模拟玩家和大结果转换仍有明确问题；41工具被调用不表示所有动作、格式和异常分支都通过。

## 成功标准与证据

本地真实OneBot测试消息组件→AstrBot v4.29.4原生runner→实际模型API→独立审核请求→测试管理员批准→HTTPS B→独立托管终端→真实nogui Minecraft。消息从测试组件注入，未连接真实QQ账号／群。观察工具是否可用、结果是否可信、模型能否合理调用与推进；实际修改核对停服、备份、目标范围、磁盘结果与新启动证据。失败、拒绝、部分效果、恢复和未覆盖项均保留，不把成功发出命令当作修复成功。

两服重新从用户ZIP解压，原ZIP不修改。本轮数据在被忽略的`runtime/two-servers-e2e-20261117/`，与此前测试状态分开。测试专用Probe负载及持久实体故障注入仅存在该目录的夹具JAR和隔离测试服，禁止进入dist；故障触发实际服务端崩溃，报告区分受控故障注入与原始游戏数据故障。

## 场景与实际结果

| 场景 | 实际结果与边界 |
|---|---|
| 双服启动及基线巡检 | 两服均实际运行，jcmd确认各10GiB；自然语言绑定、磁盘／运行组件、日志、TCP和JVM取证完成。GTNH首次就绪误报另列R01 |
| 持久实体故障 | GTNH出生区牛实体在启动tick崩溃；亡者需玩家进入原区块才触发盔甲架tick崩溃。模型停服、备份、修改单个故障字段并重启，磁盘独立验证正常哨兵保留 |
| 区域移除及恢复 | 仅GTNH隔离拷贝(-4,38)：点检查、原始导出、移除、缺失核验、原坐标恢复、完整解压NBT哈希及邻块指纹核验完成。未伪称原游戏区域自然损坏 |
| 实体热点与卡顿 | 亡者80架受控慢tick盔甲架分2／20／30／28清理，最终完整60秒1200tick、20TPS、平均9.3158ms、p95 12.55ms、慢tick0；正常两架保留。GTNH夹具负载未形成持续卡顿，模型如实报告，没有据数量误清理 |
| 多格式维护及并发变化 | 两服JSON／TOML／YAML、GB18030＋CRLF、独立NBT和拷贝区块维护完成；审核后并发改动触发旧hash失败，新提案重新批准后保留并发字段。区域保存另暴露R05 |
| 联网与安装 | 搜索／网页／本地手册、Modrinth项目／版本／文件查询完成；错误SHA失败、正确校验、慢下载取消、停服安装和备份恢复均完成，生产mods未更改 |
| 长上下文与服务恢复 | 10次真实压缩请求、8次成功压缩；压缩中A重启、反馈保存、原文哈希核验和续接通过。B重启时两服Java存活，重连PID／会话不变；三个实例任务验收归档并在新任务读取经验 |
| 卡死与强制恢复 | 亡者崩溃后Java卡住，正常停服120秒超时，模型核对PID／创建时间／会话后强停、备份、修复和重启完成；未把超时当作已停服 |
| JVM启动即退出 | GTNH受控-Xms12G大于-Xmx10G，模型定位、独立新提案修复、新启动及实际InitialHeapSize=2GiB／MaxHeapSize=10GiB核验完成；注入时序的测试编排错误单列 |
| 消息和任务生命周期 | 澄清、占用拒绝、普通成员反馈限制、停止、一次批准多批、API失败暂停／原任务续接、主动mc_pause、暂停中反馈保存及最终验收完成 |
| 长行与现代存档 | 3条约2万字符控制台行分别续读完；现代方块read/search、实体扫描、关联记录检查和原始导出完成，读取操作未加载新块 |

41个模型工具及主要分支按实际持久调用逐项统计，详见末表；版本不支持或外部服务不可用单列。

## 问题与观察分类

| 编号 | 场景与实际行为 | 结论与证据 |
|---|---|---|
| R01 | GTNH第一次Done后，ready等待当前JVM Probe能力15秒即失败；服务端继续运行，后续Probe可用 | `cf4414985a1143f29325f4a9e7731d70`：13:09:50 Done，13:10:05失败，配置总timeout实际300秒。内部另设15秒上限，未用完总时限。后续启动旁路观测见专节；首次capabilities精确发布时间未保留，不能断言具体哪个MOD阻塞 |
| R02 | 两服故障位置验证的临时玩家死亡后，Probe remove找不到/跳过对象；kick报告成功而在线列表仍残留，模型需要另提重启清理 | GTNH `McaiGTCheck`、亡者`VerifyLoader`均出现，旁观模式第二个玩家可正常移除；疑似模拟连接死亡／断开清理生命周期缺陷，需核对玩家注册表、服务端列表和终端事实 |
| R04 | NBT／区域批改多传sha256，却提示合法op=set不在delete枚举中 | 真实调用`c8c3c48b512c4cc0ad3c6b07d4f7041a`；只删除steps[6].sha256、steps[7].sha256，其他参数原样即通过完整schema。嵌套oneOf错误选择误报未匹配分支，allowed_fields也为空；见schema-branch-error-minimal.json |
| R05 | 单区块新增标签后，同文件非目标区块Double负零被改为正零 | GTNH样本实测37个非目标区块63处；独立复制原备份，只做一次根字符串新增，逐类型／浮点位比较同样复现。证据negative-zero-evidence/independent-reproduction.json及原始MCA；固定库DoubleTag.valueOf把负零归入ZERO，saveRegion重编码所有邻块 |
| R06 | 执行模型大量读取原始NBT／日志，再累计送审；当前审核证据超预算后暂停 | 执行侧已有分页与历史压缩，但缺少源头的语义归组、定向视图及跨调用去重。审核侧三次本地容量预检暂停，引用结果分别163428、878509和129711字符；两侧需共用有界证据机制，详见改进建议 |
| R08 | 大操作记录外置后mc_operation_read结果转换抛KeyError | 14:19:12和14:19:35两次读取同一原操作bb66ed9a…；B已返回16024字符产物，A仍访问data.operation.id，两份真实回包均能独立复现 |
| R03（场景） | 亡者崩溃后正常停服超时，文件修改尚未发生 | `f6f273e05d7d4bbb81a2522e079ff3ae`保存PID832，超时后仍为同一Java，说明崩溃退出卡住；后续`2c66adfce77649438a8c857982af5c90`以实际pid/process_created/session_id首步force_stop，再备份并单字段修复成功。当前证据支持正常超时边界及强停恢复，不直接列为产品缺陷 |
| O02／R06 | 两服把多格式和拷贝区块维护整组送审，补读完整区块后都超过审核容量而暂停 | 测试要求“查看完整旧值”被解释为整块NBT全文，GTNH根产物719298字符、亡者145575字符；多页证据累计送审。本轮人工say／resume拆批后继续，但正常使用应自动收敛，不能把人工拆批当作问题已解决 |
| O01 | 模型把ready超时填600秒，被300秒上限拒绝；Java取证读取参数文件不完整遭审核拒绝 | 真实纠错成本，原参数、错误路径及补证保留，模型继续处理 |
| O03 | 多格式方案曾提交snapshot、空backup_paths、组合分支错参；诊断脚本曾出现PowerShell变量后冒号语法错误 | 所有记录保留为未执行或明确失败，不归因为管理员输入；后续核对错误提示是否准确定位匹配分支、模型纠正所需步数 |
| O04 | 修正一个参数后，重提时漏掉原evidence_ids，造成第二次审核拒绝 | GTNH JVM提案`e53ab8`因timeout600被拒，`25b74a`改300却漏证据；亡者安装提案`2b5ae7`使用job_id被拒，`edd968`改download_id又漏证据。后续补齐通过。审核拒绝正确，模型的局部纠错未保留其余有效材料 |
| R07（体验改进） | 手段取代目标、非关键差异被当作阻塞，导致反复核验和迟迟不收尾 | 用户的TPS例子说明通用决策僵硬，不构成固定指标需求。本轮有全文分页、纠错漏证据和总结重复回读等额外轮次；方案围绕任务目标、关键事实和足够证据设计，不新增某个数值的特殊处理 |

## 主要证据

- 双服真实消息基线分别40、49次工具调用，完成实例绑定、启动、清单／运行组件／Probe／JVM等巡检。GTNH首次ready失败后通过独立只读补验继续，未因旧元数据告警直接停止整个巡检。
- 澄清任务只发一次mc_say；普通成员反馈开关关闭后标记内容未保存；实例占用拒绝保持原任务，最终停止新任务。
- 亡者受控存档盔甲架在玩家进入出生区后触发真实Ticking entity崩溃。整合包优化空服出生区加载，故空服Done不构成原触发条件的修复证明。GTNH修正夹具后在启动时触发牛实体真实崩溃。
- 首轮夹具未触发分别因旧版Mixin列表没有包含新增类、亡者缺少玩家加载；均为测试夹具问题，未计产品缺陷。旧版已改用原有测试FixtureEntityMixin入口；注入代码只在runtime生成JAR中，dist逐包检查不含故障类。
- 真实压缩请求期间补充约束并强制重启A，任务ID不变，反馈持久化，重启前216条消息逐条哈希核对无缺失（恢复历史加归档217条）。证据`compression-restart-before.json`、`compression-restart-recovered.json`；后续压缩完成性和修复续接继续观察。
- 两服存档故障实际修复：只修改指定实体持久标记，磁盘核对故障被解除且同区块正常哨兵实体保留。模型在原触发区用模拟玩家和主线程／热点观察验证；因死亡模拟玩家残留，又分别正常重启清理，未直接将能Done视为完成。
- B单独中断／重启期间两服Java继续存活，重连后的PID与终端session均未变；证据`b-restart-before.json`和`b-restart-validation.json`。两服实际`jcmd VM.flags`核实MaxHeapSize=10737418240。
- A重启后亡者压缩完成从258590降至56682估算tokens；GTNH另一次真实阈值压缩从260416降至63626，后续维护继续。统计以audit的context_compacted为准，job预算内batches不是整个任务历史总数。

### R01的场景、技术分析与解决建议

第一次GTNH开服，原操作`cf4414985a1143f29325f4a9e7731d70`要求300秒内完成Done、Probe主线程和60秒稳定观察。游戏日志13:09:50出现Done，操作13:10:05.954失败，Java PID14852没有退出，随后只读巡检能使用Probe。另一轮维护后也出现同类启动验证失败，模型没有重新运行已执行的文件修改，而是补验同一次启动。

`mcai/verification.py`在见到Done后直接调用`main_thread_response`；`mcai/probe_readiness.py:48`把能力发布等待和主线程应答共同限制为`min(总deadline, 当前时间＋15秒)`。Forge1.7.10探针到`FMLServerStartedEvent`才创建，其他启动收尾仍可能在Done之后执行。首轮日志13:10:09才出现默认任务数据库加载完成，说明Done后仍有收尾，但没有保留首轮capabilities的精确首次写入时间，不能将具体阻塞MOD定为已证实根因。

在本轮后续JVM修复启动时增加独立只读轮询：15:44:18 Done，15:44:28.728发布新Probe会话和PID64492，间隔约10.7秒。该次在15秒内成功，证明能力发布与Done并非同步；不能据此倒推首轮的准确延迟。证据`ready-timing-evidence.json`和`gtnh-capability-timing-observed.json`。

建议把“等待当前JVM发布能力”纳入已有总就绪deadline，能力出现后再使用明确的单次ping超时。继续校验PID、创建时间／会话和稳定窗口，实际Java退出、会话变化或总deadline耗尽应明确失败。回归至少包括Done后20秒发布、旧PID残留能力、新会话迟到、真正主线程卡死与总超时。当前未修改实现。

### R02的技术定位与后续建议

现代Probe的`tickStart`遇`player.isRemoved()`只删除simulatedPlayers映射，1.7.10遇`player.isDead`也只删除映射；两者的remove入口又拒绝已移除／死亡对象。模拟连接没有真实客户端发起正常重生及后续断开，映射被清除后服务端PlayerList中的对象可能继续残留，后续remove已无法找到它。实测两服的`mc_players/list`与`mcai_probe player list`不一致，kick回执也不能替代实际离线。

建议后续修复统一死亡／移除／断开的清理路径：清理服务端玩家列表、区块跟踪和连接后再移除自有映射，remove应能完成对死亡对象的幂等收尾；测试覆盖存活移除、死亡后移除、kick、停服及再用同名加入。本轮保持产品代码，使用正常重启完成测试现场清理。

### R04的技术定位与后续建议

工具正确拒绝了多余参数，拒绝原因的选取错误。外层步骤分支已匹配region_batch，但深入嵌套oneOf时优先选了更深的delete分支枚举错误，掩盖真正的额外sha256字段。其实际影响是模型可能按照错误建议修改操作语义，增加重试或停滞；本次未发生错误写入。

建议在每层组合分支先依据当前对象的action/mode/kind/op/by等声明判别匹配分支，再报告该分支的required/additionalProperties等错误，不能仅按错误路径深度选择。验证应包含“合法set加多余字段”“缺value”“未知op”和嵌套selector错参的原生调用，确保返回真实字段和当前分支允许项。本轮只保存复现，未改产品。

### R05的技术定位与后续建议

测试目标为`mcai-e2e/region/r.-1.1.mca`的全局区块(-4,38)，仅新增字符串标签。模型的后验与备份逐字段比对发现63处Double的IEEE 754符号位改变；数值常规相等判断会把两者当作相同，因此普通NBT equals检查未阻止保存。进一步独立复制原始备份，用实际world-helper仅新增另一测试字符串，再通过nbtlib读取全部记录并按浮点位比较，得到相同37区块／63处变化。

固定MCA Selector内`DoubleTag.valueOf(double)`使用与0比较命中单例ZERO，`-0.0 == 0.0`成立，读取时已丢失符号；WorldTool.saveRegion解码再保存所有邻块，把这种变化写回。即使只限制单区块NBT路径，当前保存策略仍可能改变未选中的记录。实测只确认负零符号变化，不据此臆称地形损坏。

建议后续保存采用未编辑区块原始记录透传，逐记录校验未选中记录的原压缩字节；目标区块采用保留数值类型与原始浮点位的NBT读写，覆盖Double／Float负零、NaN载荷和带控制字符字符串。只修邻块透传还不能保证目标区块其他字段无损，需要同时验证目标未修改字段。产品修复前不要把一般数值相等当作完整保留证明。本轮让模型在隔离样本中按新方案恢复受影响原压缩记录，原始现场单独保留。

### R08的场景、技术分析与解决建议

亡者多格式维护后，模型查询原操作`bb66ed9acd1a4d28a27110519b52f9fc`。B把16024字符的大记录外置，返回正常的后台产物信封：id、status、items内reference／characters／preview。14:19:12和14:19:35，A的`tool_results.model_result`都在第124行读取`data["operation"]["id"]`而抛KeyError，AstrBot向模型返回`error: 'operation'`。两个tool_call已持久化raw result，但没有model_result，不能算成功映射。

根因是大结果分支已决定下一步读取产物，却仍掉入mc_operation_read对内嵌记录的专用处理；外置信封没有operation字段。这与“B尚未执行完”无关。两个调用ID为`f1c26e95b4cf4c8f8f73b32eeed853c9`、`8c51bda4ff68466a866fcae824592604`；`operation-result-mapping-reproduction.json`对实际回包调用原产品函数，两次均重现。

建议按回包类型分流：外置记录保留产物job_id与reference，目标操作编号取原调用参数或独立元数据，直接返回mc_artifact_read；仅内嵌记录读取operation.id。核对小记录、大记录、失败操作、产物分页和检查点恢复，保证都保存完整model_result且沿原操作编号查询，不新建编号执行修复。本轮未改产品。

## 故障处置过程与工具体验

### 启动／进区块即崩溃

两服故障均通过隔离夹具向真实持久实体写入异常标记。测试JAR在读到该标记并tick实体时抛出真实异常；不是给模型一份虚构日志。GTNH为牛实体的`ForgeData.mcai_crash_on_tick`，亡者为盔甲架Tags中的`mcai_crash_on_tick`。同一区块另放一个正常哨兵，防止“删整块／清空全部实体”被误算作精确修复。

GTNH在启动加载出生区时实际崩溃。亡者整合包优化了无人时的出生区加载，第一次空服启动能Done；加入临时玩家到原位置后才触发真实Ticking entity异常。因此模型后续必须回到原触发位置验证，不能只看开服日志。

模型通过崩溃报告、异常上下文、区域／实体NBT查询识别目标，提出停服、备份和单字段修复方案，经独立审核及一次管理员批准执行。亡者Java崩溃后未退出，120秒正常停服超时，模型核对同一PID832、创建时间和托管会话后另提force_stop，再备份修复。该超时保留了现场，未在Java仍存活时写世界文件。

两个`*-startup-crash-repair-validation.json`独立核对磁盘：故障标记已解除，哨兵仍在。随后模型以模拟玩家进入、Probe主线程、热点和稳定窗口验证。模拟玩家死亡残留是独立的R02，模型最终通过正常重启清理，不能将其掩盖为一次无异常修复。

### 热点取证、分批清理与未复现的负载

亡者的80架测试盔甲架同时带`mcai_slow`和`mcai_e2e_load`标记，隔离夹具给每架每tick增加受控耗时。真实Probe采样曾得到约157ms／服务端tick、10秒仅61tick，模型又读取具体对象和NBT核对身份，再按2、20、30、28清理并逐批观察。盔甲架计时从约160.94ms／tick降至0.064ms／tick；最终驻留超过60秒，完整窗口1200tick、20TPS、平均9.3158ms、p95 12.55ms、最大25.6934ms、慢tick0。spark同窗约20TPS、均值9.4364ms，作为交叉证据。

结尾分别核对临时玩家插件清单和原版list均为空，两个保留盔甲架UUID仍alive。API暂停前已执行的玩家移除／加入操作按原编号查询，恢复时没有重复创建同名玩家或重复清理已删除负载。

GTNH夹具命令遇到`Invalid ticket request`，80猪负载没有稳定建立；实际只观察到单猪约2.04ms和熔炉约1ms，整体20TPS、约11.33MSPT。模型没有夸称修好持续卡顿，也没有据大量实体假设执行全局清理；结束移除观察玩家并确认0在线。这部分结果属于“未成功构造持续卡顿”，不计入亡者式分批清理的第二次成功复现。

### 文件维护、并发冲突和精确恢复

两服均在`mcai-e2e`测试目录中维护JSON、TOML、YAML、GB18030 properties、独立NBT与拷贝区域。独立校验的最终值为：enabled=true、count=11、label=维护后中文；NBT Counter=11，Slot0 Count=4、Slot2 Count=9；properties保留GB18030和CRLF。

审核通过后、批准前，控制器在JSON加入`external_note=CONCURRENT_CHANGE_KEEP_73c1`。模型旧hash的实际操作失败后保留备份和现场，重新读取并提出新方案，再经批准执行；最终该并发字段保留。旧失败没有自动回滚或重复覆盖用户新增字段。

GTNH拷贝区域维护发现R05后，模型逐字段比对了原备份，另提方案恢复未选中记录，再继续验证。后续区块救援演练使用原始导出`fedb25087cb543079e4010bc4dab1500`，移除拷贝区块(-4,38)并检查缺失，然后原坐标恢复。目标解压NBT为188690字节、SHA256 `bf0237fae63be54aed5bfd93eaced2d71688c278e52c0153223c96b728ceef5e`，邻块(-5,38)为208435字节、SHA256 `a663c50ebea294cbac4238cb4fad4fc264b224c0237f36e2824641754ffe6d52`，均匹配演练前。恢复使用新扇区，整文件哈希改变；模型正确报告布局差异。该演练只写拷贝，真实World仅有界只读扫描。

### 调用流畅度与改进方向

统一后的cursor／query／timeout_seconds等参数在常用文件、控制台、后台结果续读中可用，大结果能外置为产物并续读，模型能回读早期上下文证据。不过维修动作仍有明显试错：把内部snapshot当成可直接申报动作、install_download填job_id而接口要求download_id、restore误带paths、region_restore误带include_related，以及把ready上限写成600。除R04外，这些错误都返回了明确路径和允许字段，未发生对应写入。

本轮还两次观察到“修正单一参数时删掉原evidence_ids”，导致再次独立审核。建议后续先改进动作说明和错误后的下一步提示：明确暂存下载编号和后台任务编号的关系、restore按整份备份恢复的范围、region_restore从导出决定关联记录；提示局部纠参保留原证据引用和其他有效字段。不要通过默默接受错参或自动附加旧证据来隐藏问题。嵌套oneOf真正选错分支的R04应单独修复。

整块NBT原文送审两次超出审核材料容量，拆批并只引用当前待改字段与必要的机器比对后才继续。现有停顿没有错误执行，但增加了管理员反馈和模型轮次。后续应明确“完整待改旧值”与“整块全部NBT原文”的区别，给大型存档维护提供可核验的字段证据和未改范围比对；本轮未提高容量、截断证据或绕过审核。

## 长上下文、断线与测试编排

本轮采用真实模型的流式主请求、独立审核和历史整理，使用272000窗口、258400触发线。审计记录中的context_compaction_request是请求次数，context_compacted才是成功压缩次数；某次请求被A重启中断后重发不能算两次成功。工具返回后估算历史短时超过窗口会先进入下一次请求前的压缩，不能拿budget.batches当作整个长任务压缩次数。

压缩过程中补充管理员约束并重启A，原任务ID保留，新增反馈持久保存，重启前216条原消息逐条哈希核对无缺失；恢复后实际摘要完成，旧原文能通过mc_context_history回读。后续几轮维修与热点诊断继续沿用同一任务。B单独停止期间双服Java仍存活，重连保持原Java PID与托管session，证明本轮观察的MC生命周期独立于B。

中途模型提供商连续502，两主任务在有限重试后保存并暂停。用户通知API恢复后，通过原群命令续接，先查询原编号状态再继续；不把外部502列为插件实现缺陷。GTNH区域恢复的最后提案在暂停前只是schema拒绝，亡者最后一批玩家命令则已经完成，恢复后分别处理，未因统一“重试”而重放修改。

测试控制器也有一次编排错误：只检查区域阶段结果文件存在，将paused误当作阶段通过，提前在停服GTNH注入-Xms12G／-Xmx10G故障。它没有改变真实World，但干扰了原阶段顺序。本轮停止后续等待控制器，保留干扰记录并明确反馈模型先结算原区域恢复、结束原批准范围，再独立提案修JVM。后续门闩校验waiting及无待批准方案，主动暂停验证还要求确实出现本阶段mc_pause调用，避免将API失败当作主动暂停成功。该问题归测试夹具，不计产品缺陷。

## 证据位置与统计口径

本地完整证据根为`runtime/two-servers-e2e-20261117/`。报告与开发索引入库；真实世界、模型请求、私有配置、证书、令牌、下载和测试JAR保留在忽略目录。

| 证据 | 用途 |
|---|---|
| manifest.json、baseline-heap-proof.json | 原ZIP来源、本轮Java／端口／BAT基线、实际10GiB |
| AstrBot插件数据的state.sqlite3、audit.jsonl、traces/ | 原任务、工具参数／结果、审核／批准、API与压缩过程 |
| host-data/state.sqlite3、backups/、jobs/ | B原操作编号、已执行步骤、备份、后台产物和原始导出 |
| 两服crash-reports及游戏logs | 真实异常和启动时序；插件控制台仍为9999行有界内存 |
| *-startup-crash-repair-validation.json、*-maintenance-validation.json | 独立磁盘修复、哨兵、并发字段、编码与NBT核验 |
| negative-zero-evidence/、schema-branch-error-minimal.json | R05原MCA与独立复现、R04最小参数差异 |
| compression-restart-*.json、b-restart-validation.json | 原文哈希、反馈保存、A恢复、B退出时MC存活 |
| gtnh-capability-timing-observed.json、ready-timing-evidence.json | R01原始失败及后续启动旁路计时 |
| current-coverage.json、current-recovery-events.json | 从本轮持久记录重算的工具覆盖与压缩事件 |

工具“调用成功”仅表示工具契约返回ok，后台操作仍须核对status、complete、退出码和实际后验。明确的拒绝、预期错误SHA、取消、版本不支持、未复现负载和API故障分别记录，不能汇成一个虚假的全通过率。

## 最终补验与收尾

- Modrinth完成spark的search／project／versions／file四分支，不安装MOD。错误SHA下载明确失败，正确材料118字节和SHA256匹配。128MiB慢下载在25296896字节时取消，终态cancelled，未完整下载。
- 亡者测试文件经停服备份、安装、内容及哈希验证后，从本次备份恢复为原先不存在；原9个测试文件及BAT逐项哈希保持。随后原BAT启动并完成本次Done、Probe主线程和15秒稳定观察。
- 控制台seq8094／8095／8096分别为21834／19794／19648字符，各自从offset12000读到complete；区分命令回显和服务端实际广播。实际广播的头、field_129和尾均正确，后续确实调用mc_pause，暂停中补充保存到pending，再沿同任务续接。
- 亡者、GTNH均归档completed；新任务用mc_history index／search／read检索并读取刚验收经验，核对当前状态，同时完成现代保存区块的方块read／search、关联记录检查、实体扫描和原始导出。该任务也验收归档。
- 独立实时验证再次核实双服实际Java路径、nogui、MaxHeapSize=10737418240及本轮BAT基线哈希。之后两服正常停止，Java及BAT启动器均退出；落盘扫描确认两个原故障实体仍在且标记解除、两个正常哨兵均保留，并发JSON字段保留、安装演练文件不存在。
- 本轮AstrBot、B、OneBot、托管终端、HTTP夹具和等待控制器已停止，原host-location.json恢复。隔离世界、备份和所有故障现场继续保留，未推送、发布或修改产品代码。

最终依据：`final-independent-live-validation.json`、`final-independent-disk-validation.json`、`cleanup-normal-server-stop.json`、`cleanup-services.json`、`final-statistics.json`、三个`*-accepted.json`及各任务原持久记录。

## 覆盖统计与未覆盖范围

| 任务 | 工具调用 | 不同工具 | 成功压缩 | 最终状态 |
|---|---:|---:|---:|---|
| 澄清占用 | 3 | 3 | 0 | 按测试要求stopped |
| 联网资料核验 | 13 | 2 | 0 | done；未绑定实例，无实例经验归档 |
| 亡者基线 | 328 | 34 | 4 | done／archive completed |
| 格雷基线 | 373 | 33 | 4 | done／archive completed |
| 经验复用核验 | 24 | 16 | 0 | done／archive completed |
| 合计 | 741 | 41（去重） | 8 | 各测试任务均已结算 |

746次API请求中，主模型597、独立审核136、上下文压缩10、验收总结3；其中包含重试和中断，不能说746次全部成功。留存744条api_end，2条请求没有配对结束留痕。8次成功压缩与10次压缩请求分开计算。27个结构化工具错误包括invalid_arguments 11、review_denied 9、precondition_failed 5、remote_error 2；另有R08的2次转换异常。大操作读取的原始B结果completed不等于模型结果映射成功。

本轮验证范围为本机Windows的GTNH1.7.10与DeceasedCraft1.20.1，以及实际所用模型提供商。未覆盖真实QQ传输、跨公网双机、所有模型适配器、CurseForge密钥接口、所有MOD依赖组合、所有存档变体或全部动作。未构造真实10GiB堆耗尽、物理内存耗尽、磁盘耗尽、断电及文件系统损坏。JVM故障为受控初始堆大于最大堆，区域缺失为隔离拷贝演练；GTNH持续卡顿夹具未建立成功。七目标Probe其他五个版本和其他发行包本轮未重新验证。

用户要求的通用目标判断、执行／审核两侧大数据上下文治理与自动恢复，已形成[独立建议方案](two-servers-improvement-plan-2026-11-17.md)，并结合RTK公开实现分析可借鉴的源头过滤及原文回读思路。方案包含问题机制、最小实现方向与跨场景验收标准；建议尚未实施。

## 工具调用统计

表中ok仅为工具层接受。后台failed、取消及版本不支持需看场景结论；直接故障注入和独立验证器调用B不计入741次。错误列包含结构化拒绝及R08转换异常。

| 工具 | 调用 | 工具层ok | 错误／拒绝／异常 | 观察到的分支 |
|---|---:|---:|---:|---|
| mc_inventory | 2 | 2 | 0 | 默认 |
| mc_verify | 5 | 5 | 0 | 默认 |
| mc_diagnostics | 4 | 4 | 0 | jvm |
| mc_search | 6 | 6 | 0 | search、open、find |
| mc_players | 19 | 19 | 0 | 默认 |
| mc_metrics | 13 | 13 | 0 | 默认 |
| mc_chunks | 15 | 15 | 0 | 默认 |
| mc_runtime | 9 | 9 | 0 | settings、datapacks、dimensions、mods、summary |
| mc_objects | 25 | 25 | 0 | 默认 |
| mc_profile | 12 | 12 | 0 | probe、spark、默认 |
| mc_inspect | 28 | 28 | 0 | entity、block |
| mc_instances | 4 | 4 | 0 | 默认 |
| mc_select_instance | 4 | 3 | 1 | 默认 |
| mc_history | 4 | 4 | 0 | index、search、read |
| mc_web | 8 | 7 | 1 | open、find、read |
| mc_download | 3 | 3 | 0 | 默认 |
| mc_status | 28 | 28 | 0 | 默认 |
| mc_files | 55 | 55 | 0 | read、tail、search、find、stat、preview_patch |
| mc_logs | 14 | 14 | 0 | 默认 |
| mc_console_read | 39 | 39 | 0 | 默认 |
| mc_console_line | 3 | 3 | 0 | 默认 |
| mc_console_send | 20 | 20 | 0 | 默认 |
| mc_exec | 53 | 51 | 2 | 默认 |
| mc_nbt | 10 | 10 | 0 | read、preview_batch、默认 |
| mc_region_nbt | 22 | 21 | 1 | select、preview_batch、read、默认 |
| mc_region_blocks | 4 | 4 | 0 | read、search |
| mc_region_check | 11 | 11 | 0 | 默认 |
| mc_region_export | 2 | 2 | 0 | 默认 |
| mc_region_scan | 4 | 4 | 0 | 默认 |
| mc_job_read | 41 | 41 | 0 | 默认 |
| mc_job_wait | 33 | 33 | 0 | 默认 |
| mc_job_cancel | 2 | 2 | 0 | 默认 |
| mc_artifact_read | 92 | 92 | 0 | 默认 |
| mc_artifact_find | 12 | 12 | 0 | 默认 |
| mc_operation_read | 49 | 47 | 2 | 默认；另见R08 |
| mc_context_history | 7 | 7 | 0 | 默认 |
| mc_propose | 64 | 43 | 21 | 默认 |
| mc_plan_finish | 9 | 8 | 1 | 默认 |
| mc_say | 1 | 1 | 0 | 默认 |
| mc_pause | 1 | 1 | 0 | 默认 |
| mc_mods | 4 | 4 | 0 | search、project、versions、file |
