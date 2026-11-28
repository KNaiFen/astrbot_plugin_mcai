# 探针构建与验证

[开发索引](README.md) · [协议](../design/probe.md)

## 构建

凡 Probe 源码、协议或编译依赖有更新，必须先执行 `.\.venv\Scripts\python.exe scripts/release.py bump-probe <版本>` 推进 Probe 版本号再重编全部 8 个目标，禁止不同构建复用同一版本号；`scripts/verify.py --mode static` 会自动核对全仓 Probe 版本号一致性。

在源码根执行：

```powershell
.\.venv\Scripts\python.exe scripts/build_probe.py
# 只构建 Minecraft 1.19.2 Forge
.\.venv\Scripts\python.exe scripts/build_probe.py forge1192
```

脚本使用代理下载固定Temurin17.0.21+9（SHA-256校验），用于1.19.2／1.20.1；使用JDK21构建1.21.1；1.16.5运行时使用Java8，1.7.10已验证Java17／21运行，由RetroFuturaGradle使用独立JDK25构建。默认代理 `http://127.0.0.1:7890`，可用 `--proxy` 或 `HTTPS_PROXY` 覆盖。主构建使用 Gradle 8.8，Forge 1.7.10 使用 Gradle 9.2.0；Fabric Loom 1.7.4，ForgeGradle6.0.36，MixinGradle0.7.38，ModDevGradle2.0.148，MixinExtras0.4.1。Forge目标固定36.2.42（1.16.5）／43.5.0（1.19.2）／47.3.0（1.20.1）／52.1.2（1.21.1），NeoForge基线21.1.247，Fabric Loader0.16.14，API0.92.2／0.116.1。

构建执行clean，排除测试负载，检查产物不得包含Fixture类或spark／API类，并清理本次构建目标的旧版JAR与旧源码ZIP。各目标独立生成 JAR 和 sources，运行时 Java 要求见安装表，`dist/probe/`附完整源码ZIP、LICENSE、NOTICE。源码包保留构建脚本与协议文档；游戏二进制、测试世界和缓存不分发。

spark API仅作编译依赖。构建脚本通过同一代理下载官方仓库的固定快照`0.1-20260912.112908-2`，SHA-256为`e4856b0d2ba56db652ca340821a5b40ad0bdd192cf77707ba0f4557eeb5cb63d`，缓存在`runtime/probe-build/`并在每次构建校验；不把API JAR嵌入MOD。直接调用Gradle前先运行构建脚本准备依赖。来源和许可记录在Probe的NOTICE。

Forge1.21.1使用官方运行时映射，关闭reobf并移除SRG refmap；开发环境让metadata与classes共用目录，固定jopt-simple5.0.4。MixinExtras common仅用于编译／注解处理，loader组件嵌入JAR，避免Java21重复模块。安装版验证实际映射和Jar-in-Jar；Forge 52.0.28 曾在停服后遗留上游非 daemon 线程，构建基线 52.1.2 已通过正常退出验收。

## 可重复验证

先在隔离目录准备测试服；只测单个目标时，给构建、准备和检查脚本传入同一个目标名。被测版本的历史数据见完整源码中的 `docs/development/records/probe-validation.md`。

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

模拟玩家不需要外部客户端或 FML 握手。无目标参数的 `test_probe_servers.py` 运行七个较新的目标；需显式指定 `forge1710` 才验证 1.7.10：

```powershell
.\.venv\Scripts\python.exe scripts/test_probe_servers.py --installed --fake-player
.\.venv\Scripts\python.exe scripts/test_probe_servers.py forge1710 --fake-player
```

1.7.10 目标默认验证 spark，将 `runtime/probe-build/spark-gtnh-0.0.16.jar` 放入隔离服 `mods/`，并在该隔离服的 `config/config.json` 设置 `"backgroundProfiler": false`，让采样从空闲开始；纯 Probe 环境可加 `--expect-spark absent`，换用 Java 21 可加 `--java21`。模拟玩家回归保留原命令、区块跟踪、死亡、踢出和重进检查，并验证旁观能力、毒伤对照、移动时新旧区块变化、跨维传送、拉杆和定期右键停止。临时存档检查涵盖 `save-all`、删除、停服与已有 UUID 存档的字节一致性。

测试服务端只监听127.0.0.1随机端口，使用隔离世界，测试命令可生成、删除对象。Fixture源码仅在 `-PprobeFixture` 时编译；该负载类和配置不会进入发行JAR。普通构建含Java统计／聚合检查，真实测试覆盖负坐标、掉落物堆栈、骑乘、方块NBT、采样、重复通知、取消、未加载目标、1.21.1冻结状态。结果和日志在 `runtime/probe-build/`。

加 `--chunk-diagnostics` 可用同一套安装版脚本检查熔岩流动、现代版侦测器红石时钟、阶段耗时、主动查询前后的已加载区块数，以及同一 UUID 移动跨区后的计时合并。该场景通过原版指令布置，在指定目标区块之外放置模拟玩家保持邻区运行，无需安装 Fixture。

`test_probe_servers.py --memory-check` 在隔离服检查原生 heap、阶段计时、瞬态实体、在线方块和中断部分结果；现代版触发一次测试 GC。用 Fabric 1.21.1 的 `--fixture --memory-check --many-loaded` 进一步在拍内触发 GC 并在数千已加载区块、目标2 TPS时验证小范围查询。`test_probe_host.py --memory-check` 则通过真实 HTTPS 和托管窗口录制 `memory_jfr`、读取类直方图。不要将测试命令用于生产目录。

Python的HTTPS、任务去重、取消／修复协作、会话错误、分页、大字段及真实AstrBot runner由 `tests/test_probe.py`、`tests/test_agent_edges.py`验证。完整基线见[测试说明](testing.md)。

`python scripts/test_probe_host.py` 在隔离 Fabric 1.20.1 安装目录验证真实 HTTPS→ConPTY→MOD，含重连去重、取消确认和停服备份修复；加 `--recovery` 验证强杀／重启 B 时原 MC 进程与采样重连不重采。核心 Java 校验 `CoreChecks` 可随时由 `python scripts/verify.py --mode static` 单独执行。该脚本会修改测试实例文件，先完成安装版准备，不能指向生产实例。
