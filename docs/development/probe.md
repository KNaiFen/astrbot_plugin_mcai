# 探针构建与验证

[开发索引](README.md) · [协议](../design/probe.md)

## 构建

在源码根执行：

```powershell
.\.venv\Scripts\python.exe scripts/build_probe.py
```

脚本使用代理下载固定Temurin17.0.21+9（SHA-256校验），使用JDK21构建1.21.1；两个JDK可由 `--java17`、`--java21` 指定。默认代理 `http://127.0.0.1:7890`，可用 `--proxy` 或 `HTTPS_PROXY` 覆盖。Gradle固定8.8，Fabric Loom1.7.4，ForgeGradle6.0.36，MixinGradle0.7.38，MixinExtras0.4.1。Forge目标固定47.3.0／52.1.2，Fabric Loader0.16.14，API0.92.2／0.116.1。

构建执行clean，排除测试负载，检查产物不得包含Fixture类或spark／API类，并清理本次构建目标的旧版JAR与旧源码ZIP。各目标编译Java17／21，独立生成JAR及sources，`dist/probe/`附完整源码ZIP、LICENSE、NOTICE。源码包保留构建脚本与协议文档；游戏二进制、测试世界和缓存不分发。

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
