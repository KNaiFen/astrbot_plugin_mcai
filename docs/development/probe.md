# 探针构建与验证

[开发索引](README.md) · [协议](../design/probe.md)

## 构建

在源码根执行：

```powershell
.\.venv\Scripts\python.exe scripts/build_probe.py
# 只构建 Minecraft 1.19.2 Forge
.\.venv\Scripts\python.exe scripts/build_probe.py forge1192
```

脚本使用代理下载固定Temurin17.0.21+9（SHA-256校验），用于1.19.2／1.20.1；使用JDK21构建1.21.1；1.16.5运行时使用Java8，1.7.10已验证Java17／21运行，由RetroFuturaGradle使用独立JDK25构建。默认代理 `http://127.0.0.1:7890`，可用 `--proxy` 或 `HTTPS_PROXY` 覆盖。Gradle固定8.8，Fabric Loom1.7.4，ForgeGradle6.0.36，MixinGradle0.7.38，MixinExtras0.4.1。Forge目标固定36.2.42（1.16.5）／43.5.0（1.19.2）／47.3.0（1.20.1）／52.1.2（1.21.1），Fabric Loader0.16.14，API0.92.2／0.116.1。

构建执行clean，排除测试负载，检查产物不得包含Fixture类或spark／API类，并清理本次构建目标的旧版JAR与旧源码ZIP。各目标编译Java17／21，独立生成JAR及sources，`dist/probe/`附完整源码ZIP、LICENSE、NOTICE。源码包保留构建脚本与协议文档；游戏二进制、测试世界和缓存不分发。

1.19.2 Forge产物为`dist/probe/mcai-probe-1.19.2-forge-0.4.0.jar`，沿用协议1；既有v0.11.1公开附件仍为旧Probe。完整本地发行构建将七目标放入B包，A／B配套升级。该目标复用Forge生命周期和诊断逻辑，`game1192`适配注册表及实体世界接口，资源包格式使用9。

spark API仅作编译依赖。构建脚本通过同一代理下载官方仓库的固定快照`0.1-20260912.112908-2`，SHA-256为`e4856b0d2ba56db652ca340821a5b40ad0bdd192cf77707ba0f4557eeb5cb63d`，缓存在`runtime/probe-build/`并在每次构建校验；不把API JAR嵌入MOD。直接调用Gradle前先运行构建脚本准备依赖。来源和许可记录在Probe的NOTICE。

Forge1.21.1使用官方运行时映射，关闭reobf并移除SRG refmap；开发环境让metadata与classes共用目录，固定jopt-simple5.0.4。MixinExtras common仅用于编译／注解处理，loader组件嵌入JAR，避免Java21重复模块。安装版验证实际映射和Jar-in-Jar；Forge52.0.28实测停服后仍遗留上游非daemon线程，本轮固定52.1.2完成正常退出验收。

## 0.14.0发行（Probe 0.4.0，2026-11-16）

本版发布七目标Probe和临时模拟玩家，保留Java8核心与协议1；新发行号同步全部Gradle／加载器元数据、能力版本及当前集成脚本。`scripts/build_release.py`完整clean构建七目标通过，两端ZIP、Probe源码ZIP和完整源码ZIP生成成功，Probe源码包补入1.7.10及共享模拟玩家验收脚本。两端与完整源码ZIP的CRC、版本、七目标JAR、测试负载排除、许可和相对文档链接检查通过，记录为`runtime/release-0.14.0-build.log`及`runtime/release-0.14.0/archive-validation.json`。

由解压B包离线构建0.14.0 wheel并安装到独立site，从空工作目录以解压A包执行现有发行代表流程：真实AstrBot v4.29.4 runner的自然语言目标／网页MOD审核安装／验收归档、HTTPS CLI、Chat／Responses一次批准三批执行。4项全部通过、零跳过（47.11秒）；56个模块路径确认A来自解压插件、B及worker来自独立site。9条警告均为上游弃用提示。证据为`runtime/release-0.14.0-installed.log`、`runtime/release-0.14.0/installed.xml`和`import-proof.json`。

新版本发行JAR另在Forge1.7.10／Java21完成`--fake-player`完整安装版流程（含spark默认／全部线程／慢tick、取消与迟到回执），Forge1.20.1完成安装版`--fake-player`；均通过并正常退出，能力文件实际报告Probe0.4.0。记录为`runtime/release-0.14.0-probe.log`。前述七目标功能与Java21有／无spark验收在相同实现的Probe0.3.0上完成，版本变更不冒充重跑全部历史压力结果。

## CatServer 1.16.5兼容修复（2026-11-16）

用户日志中的Probe0.4.0在预加载阶段被Forge版本检查拒绝：CatServer `1.16.5-1d8d6313`内置Forge36.2.39，发行元数据却把构建基线36.2.42当成最低要求。此时尚未执行Probe初始化或Mixin，Java11反射提示不是本次停服原因。最小产品修正仅将1.16.5 `mods.toml`的Forge范围从`[36.2.42,37)`改为`[36.2.39,37)`；继续在36.2.42上构建，不增加CatServer分支、禁用计时或吞掉Mixin失败。

使用官方23.05.26-1资产`CatServer-1.16.5-1d8d6313-server.jar`（SHA-256 `8edea98c597e7af44a45ef9093678c38ca3749d55a71cdff10218c1c6b946fd0`），在Windows／Temurin11.0.21隔离服运行Probe与spark1.9.1。完整有spark流程通过玩家／对象／普通方块／NBT、区块与运行时、模拟玩家多实例／跨维度／删除／区块释放／重启不恢复、对象计时、spark默认／全部线程／慢tick报告、人工占用、取消与迟到回执、大NBT输出限制及IO故障回执。无spark流程亦通过，结束恢复原spark JAR。记录为`runtime/catserver-1165-real-final.log`、`catserver-1165-present-server.log`、`catserver-1165-absent.log`及`catserver-1165-absent-validation.json`。未加载任何第三方Bukkit插件或用户ISG整合包，因此不扩展为全部混合端／整合包兼容保证。

标准Forge36.2.39／Java8对照的安装版`--fake-player --expect-spark present`通过，记录为`runtime/forge-36.2.39-compat-final.log`与`forge-36.2.39-validation.json`。首次对照因测试器使用新版`minecraft:flat`标识而生成普通地形，掉落物离开断言区块；改为1.16.5原生`flat`后，在保留旧世界现场并新建隔离世界的条件下重跑通过。CatServer首次依赖安装后的同进程EOF及一次重启读取能力文件时的Windows临时共享冲突保留在初始日志，重新独立启动后的最终完整流程通过；没有为这些现象增加产品兜底。

现有实服脚本增加`--server-jar`与`--java-home`，要求单目标`--installed`，用JAR父目录运行并以目录名保存独立报告；复用同一套验收逻辑，不另造混合端测试框架。示例：

```powershell
.\.venv\Scripts\python.exe scripts/test_probe_servers.py forge1165 --installed --server-jar runtime/probe-catserver1165/CatServer-1.16.5-1d8d6313-server.jar --java-home runtime/probe-build/jdk11 --fake-player --spark-profile --io-check --expect-spark present
```

修复构建JAR的SHA-256为`fc5a470aa9c72ed290b91827f2802d3f275880278bad5a102c6ced4f72dcd01b`。本轮仅本地修复与提交，未覆盖v0.14.0公开附件或推送main；公开原包仍有旧下限。

## 可重复验证

### 核心拆分：现有五目标回归（2026-11-15）

`common`独立以Java 8 API与Gson 2.2.4编译，通过统计与排除嵌套子调用计时检查。现有五目标clean构建通过，发行JAR合并核心class；安装版Forge1.19.2／1.20.1／1.21.1和Fabric1.20.1／1.21.1均通过`--installed --player --spark-profile --io-check --expect-spark present`，包括玩家登录与跨维度、普通方块、区块、运行时、NBT完整字段省略、对象计时、spark本地报告、占用与取消。记录为`runtime/probe-core-five-build.log`、`runtime/probe-core-five-real.log`及各隔离服日志。本次结果不扩展到尚在接入的旧版本或生产整合包。

### Forge 1.16.5 与 1.7.10 接入（2026-11-15）

新增Forge1.16.5（36.2.42／Java8／spark1.9.1）与Forge1.7.10（10.13.4.1614／lwjgl3ify3.1.0／UniMixins0.3.2／Java17）目标。两者共用Java8核心和`ProbePlatform`，旧版能力文件明确标出数据包、模拟距离、ticket等级、原生block state等不支持字段；1.7.10维度使用数字ID字符串。1.16.5安装版完整流程通过玩家、NBT、区块、对象计时、spark递归报告、人工占用、取消与迟到回执，记录为`runtime/probe-1165-real.log`、`runtime/probe-1165-fixture-real.log`及`runtime/probe-1165-host.log`。1.7.10使用RetroFuturaGradle、UniMixins早期加载接口和lwjgl3ify服务端启动方式，编译及无玩家隔离启动通过；Forge旧版客户端握手仍需使用支持FML协议1的客户端，当前普通minecraft-protocol客户端只能验证连接到play状态，不能作为玩家验收证据。1.7.10完整夹具结果保留为后续专项，未标记为全流程通过。

### 临时模拟玩家交接审查与验收（2026-11-15）

审查22:03开始的实现及暂停前修补，确认并修复：1.20.1构造参数错误、按映射前名称反射调用登录／回复、1.16.5绕开完整登录、Forge内部连接缺少版本属性、1.7.10旧Netty不接受空handler、创建失败残留活动表、缺少完整玩家tick与区块跟踪刷新、移除不关闭channel、缺少坐标边界、重复手写历史事件及查询表兜底掩盖真实登录失败。现代版本改用既有GameVersion的编译期接口；保留仅按字段类型定位channel的必要反射，没有新增通用兼容框架。

七目标均完成clean构建与安装版`--fake-player`验收：正常玩家列表、players／objects／inspect同UUID、固定小数坐标、对象计时、异维度和多个玩家、同名／非法名称／越界坐标／未知维度／重复remove错误、在线人数增减、远端区块自然加载和移除后释放、join／leave各一次、带活动玩家停服、重启无自动登录。共享检查为`scripts/probe_fake_player_checks.py`。记录：`runtime/probe-fake-review-1165-final.log`、`probe-fake-review-three-real.log`、`probe-fake-review-1211-real.log`、`probe-fake-review-1710-final.log`及`runtime/probe-build/*validation*.json`。

1.7.10 Java17完整安装版进一步通过普通查询、NBT、对象计时、spark默认／全部线程／慢tick报告解析、人工占用、取消与迟到回执。本次修正该测试的UTF-8协议读取，并为GTNH spark弱引用发送者补上UniMixins晚期保留钩子，复用现有采样生命周期。Forge1.20.1与Fabric1.21.1在保留模拟玩家时也通过完整spark联合回归，日志为`runtime/probe-fake-review-spark-real.log`。发行JAR检查不含Fixture或spark/API实现类。Java21模拟玩家验收已在下述2026-11-16专项补齐；真实FML客户端及指定GTNH整合包共存仍未扩展验收，先前接入阶段未完成的压力／夹具结果保持原有边界。

最终收尾（2026-11-16）：1.7.10另通过无spark的完整安装版与模拟玩家重启检查，之后恢复原spark JAR，日志为`runtime/probe-fake-review-1710-absent.log`。现有桥接／IO／查询／ready／清单专项为17 passed、1 skipped（40.50秒），记录为`runtime/probe-fake-review-python-final.log`。Ruff与格式检查、`git diff --check`通过。`scripts/build_release.py`重新clean构建七目标并生成两端ZIP和完整源码ZIP；逐包CRC、七目标JAR与dist一致性、无Fixture／spark实现类、源码含共享验收脚本、README与docs相对链接检查通过。消融审查删除现代登录／回复反射和三组查询兜底，复用GameVersion、原生事件及既有采样状态机，新增共享检查只服务于两个实际集成入口。

### Forge 1.7.10 Java 21专项验收（2026-11-16）

标准Forge10.13.4.1614＋lwjgl3ify3.1.0＋UniMixins0.3.2，在Windows x64的Oracle JDK21.0.7（21.0.7+8-LTS-245）上补跑完成。通过活动进程可执行路径和`jcmd <pid> VM.version`确认实际使用Java21；继续使用既有`@java9args.txt`和lwjgl3ify forgePatches启动方式。安装JAR与已构建发行JAR逐字节一致，SHA-256为`5c85a6c5949c33e9001e5b1a5dffac2e36cc5a32a42f90fb09741ff920ffe6be`。本轮无需修改产品代码。

```powershell
.\.venv\Scripts\python.exe scripts/test_probe_1710.py --java21 --fake-player --expect-spark present
# 在隔离测试服临时移出spark，运行后恢复原JAR
.\.venv\Scripts\python.exe scripts/test_probe_1710.py --java21 --fake-player --expect-spark absent
```

两套命令均正常通过并停服：模拟玩家创建／删除、players／objects／inspect同UUID、固定小数坐标、多玩家／异维度、无效输入、真实在线人数、区块加载与释放、对象计时、join／leave各一次、带活动玩家停服及重启不恢复。安装spark的组合另通过普通查询、NBT、指标、默认／全部线程／慢tick报告解析、人工占用、取消与迟到回执；无spark组合确认可选mixin不影响启动和诊断，结束已恢复原spark JAR。

独立记录为`runtime/probe-java21-present.log`、`probe-java21-absent.log`，对应`*-server.log`和`*-validation.json`保留各场景完整证据。验收限于上述固定基线；真实FML客户端登录、指定GTNH整合包及早前未完成的压力／夹具专项仍按各自范围验证。

### 0.3.0第一批：现场与运行时查询（2026-11-15）

五目标发行构建通过。隔离Forge1.20.1／Fabric1.21.1安装版在原有共存组件和spark环境中通过玩家、指标、对象、NBT、热点及新增普通方块、区块ticket、运行时版本／模组／数据包／维度／设置查询；未加载范围查询没有增加加载区块。Forge1.20.1开发测试服另通过标准Forge强加载所有者的模组ID和方块坐标检查，以及原2ms实体／1ms方块实体计时。Fixture命令仅由`-PprobeFixture`编译，发行构建检查不含Fixture类。

首轮实服暴露Forge元数据仍为旧版本，以及Fabric访问可选Forge Mixin接口会触发类型加载；已同步三个Forge元数据并将Forge所有者适配及Mixin注册移至Forge源集后完整重跑上述组合通过。Fabric运行时来源按PATH／NESTED区分，保留父组件信息。记录为`runtime/probe-030-build.log`、`probe-030-real-phase1.log`、`probe-030-fixture-phase1.log`。Python桥接、清单关联和AstrBot v4.29.4真实runner／工具契约通过情况见同目录`probe-030-python-phase1.log`。本轮扩大契约测试发现既有mc_say结果因新增evidence_id与旧精确字典断言不一致，保留失败记录`probe-030-agent-phase1.log`，未改动该无关断言；后续专项排除此场景，不冒充整套通过。当批实服组合仅覆盖上述两个安装目标，其余目标与0.3.0压力结果见第三、四批。

### 0.3.0第二批：主线程响应（2026-11-15）

17项桥接、运行时清单、真实AstrBot runner、ready与原验证回归通过、零跳过（55.36秒）。涵盖无Probe但留旧文件、冻结且可响应、Done后无响应、Done前静默、观察期卡住、回执后JVM变化、旧Probe缺能力及旧JVM能力等待更新。结果为`runtime/probe-030-python-phase2-final.log`。

五目标重新构建；Forge1.20.1／Fabric1.21.1安装版及Forge1.20.1开发服原现场查询流程再次通过，1.21.1冻结时ping正常。真实Fabric1.20.1经HTTPS／独立ConPTY／worker验证独立ready和停服备份修复方案内start→ready，结果均为`logs_and_main_thread`；B退出仍不影响托管MC。`scripts/test_probe_readiness.py`在隔离Forge1.20.1临时安装Fixture JAR，通过真实JVM的Done前阻塞、Done后阻塞、观察期阻塞、正常响应和观察期退出五场景，四个失败场景均未误报ready；结束恢复发行JAR。记录为`runtime/probe-030-host-phase2.log`、`probe-030-ready-real.log`及`runtime/probe-build/ready-validation.json`。这些集成脚本需在完整源码运行。消融审查只抽取任务与ready共用的协议交换，没有增加独立后台服务或通知渠道。

### 0.3.0第三批：spark与有界取证（2026-11-15）

五目标再次clean构建；安装与未安装spark的十种安装版组合通过玩家、普通方块／空气／越界、生命与骑乘、NBT、运行时清单、ticket传播、原对象计时及取消流程。安装组合使用原固定spark1.10.37／1.10.53／1.10.109，实际完成限时本地保存、报告编号／会话／时间核对、标准Protobuf解析、全部线程、人工前台占用、重复请求、取消与迟到结果；默认采样期间用jcmd强制GC，确认回执不会随包装器回收丢失。1.10.53／1.10.109另通过慢tick报告及微秒阈值换算。记录为`runtime/probe-030-gc-present.log`、`probe-030-<目标>-absent.log`及`probe-030-present-validation.json`／`probe-030-absent-validation.json`。

保留一项已复现外部限制：Forge1.19.2的spark1.10.37 Java引擎慢tick导出会向已关闭的线程池提交末尾tick，采样结束但没有保存报告。测试核对该失败、结束事实及随后互斥释放，不将它记作成功导出；默认及全部线程报告可用。对比三个固定JAR的TickedDataAggregator字节码，1.10.53和1.10.109已改为直接导出。Probe保持原命令接口，不修改spark采样实现，不自动换引擎或重采样。

实服发现Forge适配器忽略CommandSourceStack.source，且spark只弱引用发送者。实现使用不加入世界的请求专属接收实体，并用可选Mixin仅保留本请求的包装器到保存结果或明确结束后的保存期限。没有增加文件猜测、spark私有方法调用或全局取消。B解析保留原bytes及SHA-256，递归方法按自身权重聚合，未知组件不推断。固定格式来源及GPL-3.0文本随B保留；标准protobuf7.36.2在原辅助进程中运行，继承原共享内存额度（默认8GiB）。

NBT同步保存与复制分别记录耗时，离线快照的路径遍历、排序及SNBT生成移至IO线程。五目标均用约1.5MiB的单实体Tags验证1MiB输出上限、完整字段省略和缩小路径续读；普通方块、方块实体可用性与类型分别返回。通过损坏请求、不可写结果临时路径和异步NBT路径错误，核对read_request／write_result／compute_result阶段、身份与错误，并确认驻留请求清理。Fixture另验证Forge坐标与UUID所有者、相邻区块没有直接ticket但有效加载，以及270个110ms测试tick触发256条上限和至少14条容量淘汰。记录为`runtime/probe-030-fixture-events-final.log`；测试负载未进入发行JAR。

真实HTTPS／ConPTY／worker通过两引擎断线去重、spark修复前取消、停服备份、原窗口重启及方案内ready；真实B进程强制退出再启动，MC继续运行，原job为interrupted，同编号仅发送一次采样，原报告自然完成。记录为`runtime/probe-030-host-final.log`、`probe-030-recovery-final.log`及`runtime/probe-recovery-validation/result.json`。操作受理回执可为缓存快照，当前状态沿原job接口读取。24项Python／真实AstrBot v4.29.4契约专项通过，含272000默认预算检查，耗时65.39秒；沿用第一批记录，排除无关mc_say新增evidence_id的旧精确字典断言。Ruff及格式检查通过。消融审查保留共用交换、固定字段解析和必要接收器生命周期处理，移除附近玩家的不必要排序，未增加健康基线、审批或群指令。

```powershell
# 真实开发服务端、已知2ms实体／1ms方块实体负载
.\.venv\Scripts\python.exe scripts/test_probe_servers.py --fixture
# 发行JAR安装版
.\.venv\Scripts\python.exe scripts/setup_probe_test_servers.py
.\.venv\Scripts\python.exe scripts/test_probe_servers.py --installed
```

`--player`另通过本机协议客户端验证登录、按名称／UUID查找、负坐标位置、跨维度、离开记录。客户端依赖只装在忽略目录：

```powershell
npm install --prefix runtime/probe-client --proxy=http://127.0.0.1:7890 --no-audit --no-fund minecraft-protocol@1.62.0
.\.venv\Scripts\python.exe scripts/test_probe_servers.py --installed --player
```

模拟玩家不需要外部客户端或FML握手，可直接在隔离服验证：

```powershell
.\.venv\Scripts\python.exe scripts/test_probe_servers.py forge1165 forge1201 --installed --fake-player
.\.venv\Scripts\python.exe scripts/test_probe_1710.py --fake-player
```

测试服务端只监听127.0.0.1随机端口，使用隔离世界，测试命令可生成、删除对象。Fixture源码仅在 `-PprobeFixture` 时编译；该负载类和配置不会进入发行JAR。普通构建含Java统计／聚合检查，真实测试覆盖负坐标、掉落物堆栈、骑乘、方块NBT、采样、重复通知、取消、未加载目标、1.21.1冻结状态。结果和日志在 `runtime/probe-build/`。

Python的HTTPS、任务去重、取消／修复协作、会话错误、分页、大字段及真实AstrBot runner由 `tests/test_probe.py`、`tests/test_agent_edges.py`验证。完整基线见[测试说明](testing.md)。

`python scripts/test_probe_host.py`在隔离Fabric1.20.1安装目录验证真实HTTPS→ConPTY→MOD，含重连去重、取消确认和停服备份修复。该脚本会修改测试实例文件，先完成安装版准备，不能指向生产实例。

### 0.3.0第四批：压力与发行（2026-11-15）

完成[126个有效压力采集窗口](probe-pressure-030.md)：Forge1.20.1与Fabric1.21.1各54个，其余三目标各6个最大档冒烟；每窗口预热30秒、采集60秒。记录CPU、RSS、GC、JFR一秒平均tick耗时分布、spark逐tick滚动指标、取消延迟与普查覆盖。全部非absent窗口的running／取消监视≤2，scans／cancelled回落为0，指标／玩家／慢tick历史分别不超过300／30000／256条；30次重复ping后未出现请求记录持续累积。取消最大609ms。四并发普查上限共拒绝463次，分别为Forge1.19.2的100次、Forge1.20.1的277次、Fabric1.20.1的2次、Forge1.21.1的84次，均单独报告busy。原始结果为`runtime/probe-build/<目标>-benchmark-030.json`，JFR与spark回执保留在对应隔离目录和JSON。

最终消融后另以发行代码在Fabric1.21.1最大档普查补验一个窗口，取消109ms，scans／cancelled回落为0；记录为`runtime/probe-030-ablation-check.log`及`runtime/probe-build/fabric1211-benchmark-030-ablation.json`，未混入上述126窗口。三个Forge目标的标准强加载坐标／UUID所有者与慢tick容量夹具均通过，日志为`probe-030-fixture-events-final.log`、`probe-030-fixture-other-forge.log`。最终代码重新通过真实ready阻塞、无输出正常响应及JVM重启场景，记录为`probe-030-ready-real-final.log`；真实HTTPS的inventory→runtime同目录关联与chunks查询通过，记录为`probe-030-host-inventory-final.log`。

两端ZIP通过内容、文档相对链接、五目标10个JAR／源码JAR及许可检查；B包解压构建wheel，按固定依赖下载后离线安装，在仓库外验证CLI与protobuf7.36.2导入；精简A包由AstrBot v4.29.4真实runner通过两个提供商的工具契约。记录为`runtime/probe-030-release-check.log`。再用该独立wheel环境启动B，先完成15秒spark采样与摘要解析，再验证30秒采样中强杀／重启B后MC继续运行、任务中断、同编号不重采样、原报告自然保存，记录为`probe-030-wheel-workflow.log`。最终发行构建重新clean五目标，排除测试负载与spark实现／API类。

消融审查保留一个独立压力脚本，复用既有服务端准备与等待逻辑；恢复脚本只增加外部B解释器／工作目录参数，复用真实恢复流程验证安装包。没有新增生产性能基线、自动采样或验收门槛。生产整合包尚未提供，结论限定本文固定版本、共存组件与隔离负载；spark1.10.37慢tick导出限制见第三批。

## 0.3.0压力复现

```powershell
# 主测：每个模式三个档位，每档预热30秒、采集60秒、重复三次
.\.venv\Scripts\python.exe scripts/benchmark_probe_stress.py forge1201
.\.venv\Scripts\python.exe scripts/benchmark_probe_stress.py fabric1211
# 其余目标：最大档六模式各一次
.\.venv\Scripts\python.exe scripts/benchmark_probe_stress.py forge1192 --smoke
.\.venv\Scripts\python.exe scripts/benchmark_probe_stress.py fabric1201 --smoke
.\.venv\Scripts\python.exe scripts/benchmark_probe_stress.py forge1211 --smoke
```

脚本从已准备的`runtime/probe-installed/<目标>`复制独立隔离目录到`runtime/probe-benchmark/<目标>`，监听本机随机端口，JVM固定-Xms1G／-Xmx3G。未装Probe、空闲、每秒普查、每秒大NBT、对象计时、spark60秒六种模式保持相同外部MOD；“未装Probe”仍保留spark。预检固定spark文件及当前JVM能力，避免复制恰好处于无spark验证中的临时禁用文件。结果按mode／tier／repeat保存到`runtime/probe-build/<目标>-benchmark-030.json`，重复调用仅跳过已完成的测试窗口。

低／中／高档分别为100／1000／5000个盔甲架、32／128／512个熔炉，另有一个约1.5MiB Tags的盔甲架；每两秒改变一个已预生成远端区块的原版强加载。测试数据包只在隔离目录，结束移除；没有测试负载进入发行JAR。普查同时请求objects和chunks，超过四并发时把busy单独计入覆盖记录，不冒充已扫描；NBT超限明确核对partial和缩小路径读取。采集后重复30次ping，检查running／取消监视记录回落到当前请求数量，同时记录取消延迟与有界历史集合大小。

CPU为MC进程CPU毫秒／墙钟秒，RSS为该JVM工作集；GC保留JFR事件与时间。JFR的ServerTickTime是每秒平均tick耗时，表中分布针对这些一秒窗口，不能当作逐tick P95。spark tps原始回执另保留10秒／1分钟的逐tick min／median／P95／max；Probe的60秒滚动指标按自己的采集时间保留，窗口不混算。两个主测实例可并行，其他验证与系统后台负载会造成波动；这些对照只衡量探针自身开销，不建立生产性能门槛或修复自动验收基线。

## 2026-11-15：新增1.19.2 Forge目标

五个目标重新构建通过。新增Forge43.5.0／Java17.0.21目标在隔离安装版验证无spark与spark1.10.37两种组合，均通过玩家登录、名称／UUID、负坐标、跨维度、离开记录、指标、对象普查、方块NBT、实体／方块实体热点、重复通知、采样互斥、取消和未加载目标检查。开发服务端使用`--fixture --player`验证2ms实体／1ms方块实体计时，全部通过；重新clean构建的发行JAR不包含Fixture或spark/API类。Python探针桥接现有7项测试通过。新目标尚未验证生产整合包及相同规模性能开销，历史四目标数据不扩展到1.19.2。

## 2026-11-15：Probe 0.2.1修复MixinExtras共存

旧0.2.0 Forge包把`mixinextras-forge`限定为`[0.4.1,0.5)`；同服其他模组要求0.5.x时，Forge的Jar-in-Jar版本交集为空，产生`VERSION_RESOLUTION_FAILED`，并可能连带造成其他嵌套前置缺失。三个Forge目标统一允许`[0.4.1,)`，继续内嵌固定0.4.1，让加载器选择同服所需的新版本。Probe版本独立提升到0.2.1，协议1及A／B保持不变；Fabric目标只同步版本。

隔离Forge1.20.1安装版用旧Probe与要求0.5.4的最小嵌套依赖夹具复现相同失败；修正声明后三个Forge目标都实际加载MixinExtras0.5.4，通过玩家、指标、NBT、热点、互斥、取消及spark流程。测试基线为Forge43.5.0／47.3.0／52.1.2，不等同于完整生产整合包验收；未联调Connector或用户的全部模组。旧包复现日志为`runtime/probe-build/mixinextras-old-server.log`，修复回归记录为`runtime/probe-build/mixinextras-fixed-validation.log`。

最终0.2.1五目标发行JAR全部重新构建，并通过`--installed --player --expect-spark present`完整流程；其中三个Forge目标带0.5.4嵌套依赖夹具。1.19.2另暂移spark和夹具后复测`--expect-spark absent`，确认默认内嵌MixinExtras0.4.1与无spark场景通过，随后恢复测试MOD。最终记录为`runtime/probe-build/probe-021-validation.log`及`probe-021-forge1192-absent.log`。两端ZIP、完整源码ZIP、Probe源码ZIP及十个JAR的完整性、版本和内容检查通过；51个相对文档链接、Ruff与格式检查通过。MOD及B包不含测试夹具JAR、旧0.2.0产物或spark/API类。

可重复验证：

```powershell
.\.venv\Scripts\python.exe scripts/setup_probe_test_servers.py forge1192 forge1201 forge1211 --mixinextras-compat
.\.venv\Scripts\python.exe scripts/test_probe_servers.py forge1192 forge1201 forge1211 --installed --player
```

`--mixinextras-compat`只在隔离Forge测试服生成lowcodefml夹具，内嵌官方Maven Central的MixinExtras0.5.4，SHA-256为`7922899a121a27f63a69a9ffe57470d8719cc52d239dfa9408e15d32a7b4c264`。不传该选项重新准备测试服会移除夹具；它不进入任何发行包。消融审查只保留依赖声明修正、版本同步和复现所需的集成夹具，没有新增运行时兼容层。

## 2026-11-14：Probe 0.2.0可选spark集成

四个发行目标构建通过，分别在隔离Forge／Fabric的1.20.1及1.21.1服务端验证安装与未安装spark，共8种组合全部通过。安装版使用spark1.10.53（1.20.1）及1.10.109（1.21.1），验证平均指标、CPU比例、GC、窗口和采集时间；移除spark后验证Probe正常加载及原有玩家／对象／热点／取消等流程。测试没有安装强制spark依赖，也没有使用按TPS控制生成的专用场景。

在隔离安装目录安装或暂时移开spark后，可运行`test_probe_servers.py --installed --expect-spark present`或`absent`重现相应组合；脚本不会自动修改spark安装。最初实测记录保存在`runtime/spark-present-results.json`、`runtime/spark-absent-results.json`及对应日志。消融审查将仅用于MSPT的一次性泛型序列化方法内联后，重新构建四目标并重跑全部8种安装版组合，全部通过；最终记录为`runtime/optimization-spark-final-present.json`、`runtime/optimization-spark-final-absent.json`和`runtime/optimization-spark-final.log`。测试移开的spark JAR已恢复，运行数据不进入发行包。

## 历史实测：Probe 0.1.0

当前0.3.0压力入口为`scripts/benchmark_probe_stress.py`，下方0.1.0数字仍是历史数据。

以下四目标服内、共存和JFR数据来自Probe 0.1.0既有验证，0.8.0审查及整改没有重做同规模负载测量。原记录未单独保存测量日期，不能据此补写日期。本次源码范围过滤和取消I/O调整的构建与回归结果见[整改记录](architecture-remediation-0.8.0.md)。

四目标发行JAR在独立安装的dedicated server通过，Forge47.3.0／52.1.2、Fabric Loader0.16.14，分别使用Java17.0.21／21.0.7。真实协议客户端验证登录、名称与UUID查询、负坐标、跨维度和离开事件；对象检查包括骑乘、掉落物数量与件数、NBT和未加载位置。开发服务端另用2ms盔甲架与1ms熔炉负载验证计时归属和贡献，不将Fixture装入发行包。

共存组合均通过相同诊断流程：

| 目标 | 同服组件 |
|---|---|
| Forge1.20.1 | spark1.10.53、Observable4.4.2、FerriteCore6.0.1及Observable依赖 |
| Fabric1.20.1 | spark1.10.53、Observable4.4.2、Lithium0.11.4及Observable依赖 |
| Forge1.21.1 | spark1.10.109；Observable该版本发布为NeoForge，未用于Forge测试 |
| Fabric1.21.1 | spark1.10.109、Observable5.4.4、Lithium0.15.4及Observable依赖 |

Lithium可让空闲熔炉休眠，因此已加载方块实体可能没有tick计时行；测试给熔炉加入燃料与原料后验证实际tick。各组件下载经Modrinth官方接口并核对SHA-512，只保存在runtime；共存通过范围限定上述版本与工作负载。

在Fabric1.20.1、Java17、100个盔甲架和相同隔离世界中，分别重启进程采集12秒JFR。JFR的每秒averageTickDuration再取均值；RSS为进程驻留内存：

| 模式 | JFR平均tick耗时ms | 平均RSS MiB |
|---|---:|---:|
| 未安装探针 | 2.491 | 975.1 |
| 探针空闲 | 2.277 | 937.4 |
| 每秒一次普查 | 2.487 | 1101.7 |
| 详细采样 | 2.749 | 1073.2 |

短测包含JIT、GC和同机其他测试波动，不能由此推导固定开销比例。结果确认四种模式可运行；生产大整合包仍需自己的负载测试。复现命令为 `python scripts/benchmark_probe.py fabric1201`，在完成安装版准备且无其他进程占用该测试目录时运行。

消融审查保留现有HTTPS／后台任务／分页，只新增控制台与本地文件桥接；共享协议和统计，适配层不引入跨加载器运行框架。结果聚合、排序、序列化移到后台，取消检查每tick一次；没有增加MOD网络服务、GUI或修改入口。
