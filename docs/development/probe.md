# 探针构建与验证

[开发索引](README.md) · [协议](../design/probe.md)

## 构建

在源码根执行：

```powershell
.\.venv\Scripts\python.exe scripts/build_probe.py
# 只构建 Minecraft 1.19.2 Forge
.\.venv\Scripts\python.exe scripts/build_probe.py forge1192
```

脚本使用代理下载固定Temurin17.0.21+9（SHA-256校验），用于1.19.2／1.20.1；使用JDK21构建1.21.1；两个JDK可由 `--java17`、`--java21` 指定。默认代理 `http://127.0.0.1:7890`，可用 `--proxy` 或 `HTTPS_PROXY` 覆盖。Gradle固定8.8，Fabric Loom1.7.4，ForgeGradle6.0.36，MixinGradle0.7.38，MixinExtras0.4.1。Forge目标固定43.5.0（1.19.2）／47.3.0（1.20.1）／52.1.2（1.21.1），Fabric Loader0.16.14，API0.92.2／0.116.1。

构建执行clean，排除测试负载，检查产物不得包含Fixture类或spark／API类，并清理本次构建目标的旧版JAR与旧源码ZIP。各目标编译Java17／21，独立生成JAR及sources，`dist/probe/`附完整源码ZIP、LICENSE、NOTICE。源码包保留构建脚本与协议文档；游戏二进制、测试世界和缓存不分发。

1.19.2 Forge 产物为 `dist/probe/mcai-probe-1.19.2-forge-0.2.1.jar`，沿用协议1；既有 v0.11.1 公开附件不含Probe 0.2.1及新增目标。完整发行构建会将它一并放入B包。该目标复用Forge生命周期和诊断逻辑，`game1192`适配注册表及实体世界接口，资源包格式使用9。

spark API仅作编译依赖。构建脚本通过同一代理下载官方仓库的固定快照`0.1-20260912.112908-2`，SHA-256为`e4856b0d2ba56db652ca340821a5b40ad0bdd192cf77707ba0f4557eeb5cb63d`，缓存在`runtime/probe-build/`并在每次构建校验；不把API JAR嵌入MOD。直接调用Gradle前先运行构建脚本准备依赖。来源和许可记录在Probe的NOTICE。

Forge1.21.1使用官方运行时映射，关闭reobf并移除SRG refmap；开发环境让metadata与classes共用目录，固定jopt-simple5.0.4。MixinExtras common仅用于编译／注解处理，loader组件嵌入JAR，避免Java21重复模块。安装版验证实际映射和Jar-in-Jar；Forge52.0.28实测停服后仍遗留上游非daemon线程，本轮固定52.1.2完成正常退出验收。

## 可重复验证

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

测试服务端只监听127.0.0.1随机端口，使用隔离世界，测试命令可生成、删除对象。Fixture源码仅在 `-PprobeFixture` 时编译；该负载类和配置不会进入发行JAR。普通构建含Java统计／聚合检查，真实测试覆盖负坐标、掉落物堆栈、骑乘、方块NBT、采样、重复通知、取消、未加载目标、1.21.1冻结状态。结果和日志在 `runtime/probe-build/`。

Python的HTTPS、任务去重、取消／修复协作、会话错误、分页、大字段及真实AstrBot runner由 `tests/test_probe.py`、`tests/test_agent_edges.py`验证。完整基线见[测试说明](testing.md)。

`python scripts/test_probe_host.py`在隔离Fabric1.20.1安装目录验证真实HTTPS→ConPTY→MOD，含重连去重、取消确认和停服备份修复。该脚本会修改测试实例文件，先完成安装版准备，不能指向生产实例。

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
