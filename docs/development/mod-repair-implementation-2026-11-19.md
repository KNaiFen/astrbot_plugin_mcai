# MOD工作区与隔离测试副本实现记录

[开发索引](README.md) · [Agent与审核设计](../design/agent.md) · [配置说明](../usage/configuration.md)

本轮接续未提交的0.16.0实现，先审查历史改动，再修复传输、配置和测试环境路径中的缺陷。实现保持一次管理员批准、独立审核、任务编号与现有修复备份机制。

## 已完成

- MOD元数据查询、CurseForge凭据、HTTP下载和构建依赖访问位于A。B拒绝MCAI外网下载；A向B传输暂存文件时，B核对任务记录、文件长度与SHA-256，同编号重试只接受完全相同的记录和内容。
- A配置的工作区根目录和PowerShell 7.3+在插件启动及设置保存时解析；设置保存受后台任务占用检查保护。命令子进程通过独立worker加入A端共享Job Object，额度8GiB，并持久化进程PID和创建时间供取消及重载恢复。
- B有任务级工作目录、实例测试服地址／端口配置、隔离副本、端口检查、独立托管窗口和测试环境路由。实例设置页会保留数值端口，控制台与查询续读可沿`environment=test`保持目标。
- 工作区下载、B暂存、测试安装和生产安装继续使用原审核、批准、备份与替换接口；工作区来源的生产制品要求同一活动方案内有同制品测试安装记录，并在测试结束后收到反馈。
- 插件发行树包含工作区和worker模块；产品版本为0.16.0，A/B协议为`mcai-6`。

## 缺陷审查与验证

历史未提交改动发现并修正：

- B端导入只登记元数据、不核对内容；断线重试会重复写入固定临时文件，且客户端重试复用已耗尽文件流。现在每次尝试重新打开源文件，B原子接收并按长度／SHA-256校验，重复内容幂等。
- A设置保存后工作区对象未重载，自动发现PowerShell未校验最低版本；现在在提交配置前校验并同步运行对象。
- B实例表单未显示测试地址／端口；console工具和翻页调用未携带测试环境，导致Agent无法持续读取测试服输出。已补齐表单字段和续读路由。
- 上一轮已有下载测试依赖旧行为：篡改后的A文件应由B拒绝传输，而不是等生产安装时才拒绝。测试已调整为直接验证拒绝边界。

Windows／Python 3.12.14环境运行：

```powershell
.\.venv\Scripts\ruff.exe format main.py mcai tests/test_agent_edges.py tests/test_web_downloads.py tests/test_mod_workspace.py tests/test_configuration_lifecycle.py scripts/build_release.py
.\.venv\Scripts\ruff.exe check main.py mcai tests scripts
.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider tests/test_web_downloads.py tests/test_mod_workspace.py tests/test_configuration_lifecycle.py
```

结果：Ruff lint通过；改动涉及的68个Python文件格式检查通过；上述三个测试文件20项通过、0失败、0跳过。发行树静态核对确认36个插件模块均存在且无重复，源码包排除本地`.codegraph`索引。新增测试覆盖A到B同内容重传、请求中断后从源文件头重试、篡改拒绝、测试端口配置／冲突校验、测试目录绑定，以及真实PowerShell worker输出与持久进程身份。

显式加载仓库内AstrBot 4.29.4后，运行`test_agent_edges.py`、`test_tool_contracts.py`和`test_plan_continuation.py`共42项，全部通过（15条为AstrBot上游弃用警告）。审查同时修正了4个同一参数化用例的旧断言：Agent消息包含`【管理员创建任务】`来源标签，原测试却要求消息文本等于裸报告；现确认完整报告仍保留在消息中。

```powershell
$env:PYTHONPATH = 'runtime/astrbot-4.29.4'
.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider --require-astrbot -vv tests/test_agent_edges.py tests/test_tool_contracts.py tests/test_plan_continuation.py
```

全目录Ruff format检查另报告未改动的`scripts/test_probe_host.py`格式不符；本轮改动涉及文件均通过格式检查。

首次验收时尚未复跑本地OneBot、真实模型、玩家反馈和两台Minecraft进程的链路，且当时遗漏了[清理后保留的配置和实例](local-test-cleanup-2026-11-18.md#保留实例)。下面的专项验收复用了保留的AstrBot配置、模型提供商设置和Fabric 1.21.1运行库，另建隔离目录、端口和测试世界。

## 2026-11-19 Lithium端到端验收

本轮使用[上游 Lithium `mc1.21.1-0.15.4`](https://github.com/CaffeineMC/lithium/releases/tag/mc1.21.1-0.15.4)（提交 `4fe343603cc0108a8125c5fbdfebe4124ea5988b`），在隔离测试服的源码包中人为加入故障：`-Dlithium.e2e.batchSize=auto` 进入入口类的整数解析，Fabric 初始化抛出 `NumberFormatException`，服务端在启动阶段退出。复现使用 Fabric Loader `0.16.14`、Java 21 以及原 BAT 中的 `java -Xms384M -Xmx1G -Dlithium.e2e.batchSize=auto -jar fabric-server-launch.jar nogui`。Java 进程退出码是 0，启动日志未就绪且明确记录异常。源码包包含入口类、原版 JAR、Fabric Loader JAR 和构建说明；只编译并替换该入口 class，其余 JAR 文件项内容保持一致。

- 本地 OneBot、AstrBot 4.29.4、真实 Responses 主模型和独立审核均跑通。模型先查日志、读取源码包并提出多轮方案；遇到 `environment=test` 尚未创建副本的错误后自行回到绑定服创建副本。独立审核挡住了无效的就绪正则 `Done (`，模型自行转义括号并重新提交。管理员仅执行一次 `/mcaiapply e2e`，后续构建、备份、替换、启动和验收沿同一任务编号继续。
- Responses 历史回放曾连续收到 `Unknown parameter: input[*].synthetic`。运行时把标记为 `synthetic` 的占位消息放回下一次请求；现只在回放时跳过该占位消息，保留正常的阶段消息和工具结果。修复后重启 AstrBot，原任务继续；真实 SDK 的 MockTransport 用例复查了回放输入，提交为 `b4f2159`。
- 副本使用原 `start.bat` 和 `-Dlithium.e2e.batchSize=auto` 启动到 `Done`，日志无原 Lithium 异常。Minecraft 1.21.1 协议客户端从 `127.0.0.1:25963` 收到世界坐标，日志确认 `MCAITestPlayer joined the game`。客户端首次未处理 configuration ping，修正测试客户端后重试成功；这是测试工具问题，不是服务端故障。
- 测试群通过 `/mcaisay e2e ...` 提交管理员反馈后，目标服先备份原 JAR（安装前 SHA-256 `f8c5d0cb63eb4f5cf9f6bfdaf4ed0f09a7874d8890fe831a796c68bfcd41b545`），替换为测试产物 `38eb84395bb8930099d3c371b553a87ea0d1d27f34a5253a0ee24d11079c0fc3`，原启动脚本和其他模组指纹未变。目标服使用原参数启动到 `Done`，协议客户端从 `127.0.0.1:25962` 进入世界，随后 `/mcaidone e2e` 完成验收。此项检查覆盖登录和进入世界；协议客户端另报物品数据解码错误，未验收背包或完整游戏操作。
- 观察到两项流程问题：旧回归用例把 `mc_say` 提问后仍期待同轮 final，和运行规则“提问后等待”冲突；已改为单独验证长 final 分段且不丢文本，提交为 `e9ae112`。工具说明原先没有清楚区分“绑定服创建副本”和“对已存在副本操作”，模型因此多做了一次失败的 test 查询；已补充 `pull`、`stage`、`use_download` 和 `prepare_test` 的环境说明，提交为 `d9af977`。
- 首轮模型选择了在 B 的测试副本内构建，没有经过 A 工作区和 HTTPS 制品暂存。这条路径在下节单独复验。

本轮回归：改动文件通过 Ruff；工具契约和 Responses 回放、群回复相关用例 `18 passed`。此前合并运行的相关套件为 `51 passed、2 failed`，两项失败均在修改前的版本复现并已调整用例。验收完成后正常停止本轮的两台测试进程，清理临时源码、客户端、配置副本、构建与运行目录。

消融审查：没有增加MOD专用构建框架、制品登记表、第二个生产目标或额外审批层；文件传输复用现有下载记录与HTTPS认证，测试环境复用现有任务、操作、后台Job和托管终端机制。临时构建产物已从`runtime/mod-repair-validation`删除。

## Lithium A 工作区路径复验

同一上游版本、Fabric Loader 0.16.14、Java 21 和 `-Dlithium.e2e.batchSize=auto` 再次复现入口异常。使用新的本地 OneBot 测试群会话、AstrBot 4.29.4、真实 Responses 主模型与 Chat 独立审核。任务原文提供故障、源码包位置、隔离副本和反馈要求，未给工具调用顺序；主模型与审核共用的任务提示词明确 A 构建、B 安装和验证，保留用户自定义规则文件。管理员只批准一次 `/mcaiapply lithium`。

- 主模型用 `mc_workspace pull` 取源码包，在 A 工作区读取、修改并用 Java 21 构建，后台构建用时约 2 秒。与离线基包比较，JAR 内只有 `LithiumFabricMod.class` 改变。模型调用 `stage` 登记制品，再经 `install_download` 提案触发 HTTPS 传输。A 暂存、B 暂存和试服安装文件的 SHA-256 都是 `cf8af4262fb5210443230ac8281121aa3320432fecd33b66112aa4a73340b8eb`，大小 797668 字节。
- 试服从原 BAT 启动到 `Done`，原异常未出现。运行 `node runtime/lithium-ae2e/client/login.cjs 25963`，客户端收到世界坐标，服务端日志确认玩家加入。物品数据解码仍有客户端告警，本轮验收登录，不覆盖完整游戏操作。发送通过反馈前，目标服的 JAR 仍为故障制品 `b2a18449053935798f25ce2c0bd30a43ff3dba1bdda302f0637467428c5c0a60`。
- 经 `/mcaisay lithium …` 收到实测通过反馈后，B 通过 `install_download` 在隔离目标服安装同一 `download_id`。测试服、目标服的快照备份均与故障 JAR 的 SHA-256 一致，目标服安装哈希与 A 的构建制品一致；启动脚本和其他 MOD 文件未变。目标服以原参数在 3.979 秒完成服务端就绪，协议客户端从本机 25962 进入世界，日志未见原异常。
- 实测暴露三处执行缺陷。第一，A 工作区脚本已获管理员批准，但审核请求缺方案快照；现传入已批准范围并绑定其身份（`028e0c2`）。第二，同一个共享 Windows Job Object 接受首次虚拟环境 worker，后续分配报 WinError 5。直接使用基础 Python 启动只依赖标准库的 worker 可以连续执行，8 GiB 共享限制保留（`d58b63a`）。第三，本地后台工具已读到完成状态，任务仍把构建标记为进行中，导致结案受阻；现由同一处更新本地与远程后台状态（`82f15ef`）。修正后用 `/mcairesume lithium` 恢复原任务和原批准，未在 B 端构建或重放安装。
- 流畅度观察：模型自行从日志摘要补取异常原文，修正了离线原版 JAR 与故障 JAR 必须同哈希的错误假设，也处理了查询参数出错。独立审核有一次将实际 A 工作区调用误判成 B 构建，重提后通过；目标服替换审核先后因原哈希证据分页过宽、在摘要中被省略而拒绝，模型改为按序号读单条原记录。
- 原多轮方案已完成，`/mcaidone lithium` 返回“已验收，任务结束”，经验状态为 `completed`。测试服和隔离目标服均正常停服。复用的原测试服目录和保留配置未改动。

回归使用 AstrBot 4.29.4，运行 `python -m pytest -p no:cacheprovider --require-astrbot -q tests/test_plan_continuation.py tests/test_model_request_integrity.py tests/test_mod_workspace.py tests/test_web_downloads.py tests/test_tool_contracts.py`，在后台结算修复前为 56 项通过；最后一次改动后定向重跑 `test_plan_continuation.py -k 'workspace_exec_uses or one_approval_runs'`，3 项通过。Ruff 与改动路径的 Git 差异检查通过。

## 2026-11-19 第三轮：真实模型、玩家验收与恢复

基线为源码 `3e1405b`、[AstrBot 4.29.4](https://github.com/AstrBotDevs/AstrBot/releases/tag/v4.29.4)、[Lithium Fabric 0.15.4](https://github.com/CaffeineMC/lithium/releases/tag/mc1.21.1-0.15.4)（上游 `4fe343603cc0108a8125c5fbdfebe4124ea5988b`）、Fabric Loader 0.16.14、Java 21.0.7、PowerShell 7.6.5、Python 3.12.14。本轮另建运行目录，复用保留的 Fabric 运行库、模型配置和 `scripts/e2e_qq_component.py`。A 使用真实 Responses 主模型，独立审核使用 Chat 提供商配置，两者均为 `gpt-6.1-sol`。正常用例使用本地群 `29111931`，OneBot/A/B 端口分别为 18942/6491/18941，隔离目标服和试服端口为 25976/25977。保留配置中的三个自定义规则文件与隔离 A 加载的副本逐一比对 SHA-256，三份都未改动。

先在隔离目标目录运行 `java -Xms384M -Xmx1G -Dlithium.e2e.batchSize=auto -jar fabric-server-launch.jar nogui`。Java PID 43396 退出码为 0；`logs/latest.log` 出现 `NumberFormatException: For input string: "auto"`，栈指向 `LithiumFabricMod.onInitialize`，无 `Done`，端口未监听。根目录 `lithium-source.zip` 包含本轮注入故障的入口源码、上游 Lithium JAR、Loader 0.16.14、离线构建说明和许可证。测试只替换入口 class；故障夹具和生成 JAR 均不进发行包。

### 正常流程：通过

任务 `cbf0cff0fe594e3985443179328c91fd`。本地 OneBot 原文报障，管理员只进行一次有效的 `/mcaiapply lithium`、一次试服通过反馈及最后 `/mcaidone lithium`。首次尝试发送批准时，Git Bash 把字符串开头的斜杠转换成了文件路径；OneBot 收到的并非指令，A 未批准。设置 `MSYS2_ARG_CONV_EXCL=*` 后重发。测试人员未提供根因、调用顺序或修复代码，没有代模型构建、安装或改任务数据库。

- 检查实际 SDK 发包边界的 `api_request.parameters`：29 个排障请求和 8 个独立审核请求均逐条包含“修改 MOD 源码、编译和重新打包必须在 A 端任务工作区完成”以及禁止在 B 和隔离副本安排或执行这些步骤。首个主请求 `b6d6eea572da43a7a5e072ceb15e1725`，首个审核请求 `858a58ff5a3d47e1b0b8b91500f57f1c`。实际方案首批只创建试服，构建脚本的送审环境和路径均为 A 工作区。未见主模型选 B 构建或审核将 A 误判为 B；正常用例 8 次审核均通过。
- 模型从 B 拉取源码包和故障 JAR，在 A 自行改入口源码、编译、重新打包；与离线基包比较仅 `LithiumFabricMod.class` 内容不同。随后调用 `stage` 生成 `download_id=252d90ec05bc4e58b1d460a14fb6ce99`，试服 `install_download` 送审前经 HTTPS 暂存到 B。A 工作区、A 暂存、B 暂存、试服和目标服五处的 SHA-256 均为 `fa5e33e8f33ad19775d740889eae5373626e7df8951714d1491e9dc722212282`，797591 字节。
- 试服操作 `4002d18ff23f4e81849a03cca9bfa8b7` 完成备份、安装、启动与验证；原 BAT、`-Dlithium.e2e.batchSize=auto` 和其余 MOD 均保留。服务端记录 `Done (1.106s)`，无原异常。用 `minecraft-protocol@1.60.0` 实际执行 1.21.1 登录、配置阶段 ping/pong 和传送确认，客户端在 `play` 收到 `(8.5, -60, 5.5)`，B 日志有 `MCAIRound3Test joined the game`。在群里发通过反馈前保存目标服状态：Java/BAT 未运行、端口未监听、原故障 SHA-256 `a5181bf6d08c17fab64cbf8cb984ef02b00c406ffad67128d6771dddc033bbcd` 未变，无目标服备份、替换或启停操作。创建副本批次的备份目录只有操作清单。
- 收到管理员实测反馈后，目标服操作 `47bfc11da64c4f55b3c860bd88639069` 完成备份、同编号制品安装和原参数启动。其备份和试服的备份均与故障原件哈希一致。两个 `start.bat` 的 SHA-256 都是 `cb671ed166e0e2893b8435f758ebe23d258afbab83223e84aa6f917653d2de83`，其余 MOD 指纹与开测前一致。目标服记录 `Done (1.194s)`，无原异常，客户端收到 `(-0.5, -60, -2.5)`，B 日志有 `MCAIRound3Target joined the game`。两次主链路登录均未出现客户端解码错误。
- 原多轮方案 `298ccbe052c445ffbbc278eaa4b2e89e` 经 `mc_plan_finish` 持久化为 `completed`。群回执“已验收，任务结束”，A 任务为 `done`、`archive_state=completed`；经验索引及对应实例 Markdown 已实际落盘，分别为 409 和 8014 字节。

| 时间段 | 墙钟 | 主模型 | 审核 | 其他 |
|---|---:|---:|---:|---|
| 报障 → 可批准提案 | 69.0 秒 | 57.6 秒 | 6.8 秒 | 余约 4.5 秒含查询、工具调度与通知 |
| 有效批准 → 试服客户端入世界 | 211.4 秒 | 91.8 秒 | 36.9 秒 | 压缩 42.1 秒；其余约 40.6 秒含工具和客户端。B 建副本 0.6 秒，试服安装/启动/验证批次 33.4 秒，五次 A worker 合计约 4.1 秒 |
| 通过反馈 → 目标服客户端入世界 | 79.4 秒 | 28.5 秒 | 3.6 秒 | B 安装/启动/验证批次 21.8 秒；客户端在 `Done` 后约 45 秒才收到位置，部分与 B 稳定观察重叠 |
| 目标服批次结算 → 归档请求完成 | 476.1 秒 | 49.2 秒 | 0 秒 | 压缩 44.2 秒；最终群报告到人工发验收 320.8 秒；验收总结 57.3 秒，随后检查归档落盘 |

时间取 OneBot 入出消息、A 的 API 起止与操作结算、客户端位置事件。提案到有效批准另等 146.1 秒（含 Git Bash 错发），试服入口通知到人工反馈另等 115.1 秒。墙钟余量包含产品调度和测试者执行客户端的等待，无完整逐工具计时，不能直接归为模型或 B 慢。正常链路没有故意断开或重启。两次压缩合计 86.3 秒，是模型外显等待的大头之一。

### 异常结果与卡点

反馈隔离用例复用正常用例产物作为输入候选，不代模型在 B 安装；各自用新任务、端口和副本。对发布判断以 B 的写操作、备份与当前 JAR 为准。

| 用例 | 结果与证据 |
|---|---|
| 普通成员“测过了，可以替换” | **通过**。任务 `9c1c86e018f14c5e9b70b5042954ac05` 持久反馈为 `is_admin=false`。已安装候选的试服就绪；主模型继续等待管理员，中间未送审目标服部署，也未触发程序拒绝。B 目标服写操作为 0，故障 JAR 未变、停服。 |
| 管理员“测试没通过” | **发布门槛通过，后续排障失败**。任务 `8e65de10d2b541cf85071da6c7ffb480`，试服已监听且未记录成功进世界，收到 `is_admin=true` 负反馈后模型只查询试服状态，没有目标服部署提案或写操作。它关闭了方案、请用 `/mcaidone`，但没追问失败现象或补查登录日志，群状态与持久状态一致，处理方向过早收尾。 |
| 管理员“还没测完” | **复用已就绪试服通过；专用夹具准备失败**。首任务 `63fdf590e62941c9b7cfa5e1ed423a9d` 两次留存 `server.partial` 后经管理员批准重试，排除可重建的 `.fabric` 后仍失败；新任务 `ee82251141df419eaf1aacec19dff73c` 仅复制与正常用例相同的七项，也在 `server.partial → server` 报 `WinError 5`。两者未达试服已安装前置，目标服无写入。改用已补齐依赖、未收到通过反馈的 `offline` 任务，试服恢复到 `Done` 后单发“还没测完”。主模型继续等待，没有提交部署提案；目标服写操作为 0、故障 JAR 不变、仍停服。不能将此结果归为审核或程序拒绝，也不算专用夹具完成。目录拒绝访问的具体来源未确认。 |
| A 缺少离线依赖 | **可补齐路径通过**。任务 `d3e79bee381544f1b703d3efd3cd8a4c` 的源码 ZIP 单独删除了 Loader 0.16.14 JAR；全局 Java、运行库不变。模型列出缺项，从 B 现有 `libraries/.../fabric-loader-0.16.14.jar` 拉回 A（工具调用 `6bc98d5327`），同任务在 A 构建并让试服到 `Done`，未安排到 B 构建。仍不可补齐并在恢复条件后从暂停续接的分支未测。 |
| 制品在试服实测后变化 | **通过（复用原件）**。任务 `1361ee0a9116435d95523325d004aa5d` 实际进试服并记录第一份 JAR。另模拟候选 ZIP 注释变更，模型登记第二编号 `074231f51e194b84a760d0d0f7531f7d`、SHA-256 `3058bbdb600b709d9aff65d21203a5d49416a5652a449940c93d12beab493dde` 后继续等待。管理员只确认第一份后，试服操作 `4d894053ccf14dd19f32a8774b02c29c` 和目标服操作 `31196752faca432d89359b7e1be4122d` 均用第一份 `f7fdbea153cc40a79faabeb11da2d27e`，无第二份的安装。未强制模型提交新版以碰撞程序拦截。 |
| B→A 文件中途断开 | **基线失败，修复后通过**。仅在本轮隔离 HTTPS 夹具向真实 `HostClient` 发送前 131072 字节后断开。基线返回 `ClientPayloadError`，目标未发布但留下同调用号的 131072 字节 `.part`，需显式重取。修复后按原来源及调用号从头发起第二次 GET，0.766 秒取回 1910070 字节且 SHA-256 等于源包、无 `.part`。这里复验到客户端边界，未重新消耗一整次真实模型任务。 |
| A→B 上传中途断开 | **通过**。同夹具在 B 已接收 131072 字节后断开。实际 HTTPS 向同一个 `e7ab501aeb004e869a907d13b39c9491` 两次 PUT，B 无残留临时件，第二次从头到齐 797591 字节并校验同 SHA-256；约 0.234 秒，无文件安装、备份或启停。 |
| B 已执行但 A 未收到回执 | **通过**。等 B 将操作 `b8be4d6bbc91473eb87c72aa85010df4` 持久标为完成，再中断该 HTTPS 回执。A 发出第二次相同 POST，参数完全相等；这次没有 GET 轮询（B直接返回原已完成记录）。一份备份、一条安装完成记录、无启停；约 1.078 秒。此例使用真实 HTTPS 客户端/B/托管终端，以及模型生成的 JAR，触发来自试验夹具而非群内模型。 |
| A 在 B 已结算时重启 | **通过**。新群任务 `7af2dc9b4aeb4d9e9d6af3376dc56067` 只备份和修改隔离的 `recovery-marker.txt`。管理员实际批准后，暂停本轮 A 进程，等待 B 原操作 `e9d7c115d00f4a10a4f7335978aa1cf7` 到 `completed`，此时 A 仍 `applying` 且无修复结果。终止并启动独立 AstrBot A，A 沿同任务、同操作号和原参数回到 `waiting`，只有一条 B 写操作。故意重启到恢复并等待群报告共约 114.6 秒，含真实模型续报。此前尝试以创建副本作写入点，遇到目录重命名错误，未触发 A 重启。 |
| B 执行后、尚未落完成状态时重启 | **通过**。独立 B 子进程写入及备份已落盘，原号 `c052d80d81784bde9314a689aa954099` 仍为 `running` 时终止 B。新 B 用原数据库启动，查询原号返回“控制程序曾重启，操作状态不确定”；再次提同号同参返回同记录。检查原备份及已安装 JAR 的哈希与时间戳，未再次写入或启停；重启到查得原号约 1.078 秒。没有拿 HTTPS 短断或 API 失败替代 B 进程重启。 |

正常链路的额外摩擦：`files find --max-depth 1` 局部报错后，模型按提示查帮助再改对；两次 A 端打包先误用 PATH 上的旧 `jar.exe`，再误认 Oracle 的 `javapath` 是 JDK 根。实际两次失败后台合计约 2.1 秒，第一次失败到最终制品成功多耗约 65 秒，主要是调度、查工具和审核，模型独立纠正。旧 `jar` 的原生输出在 A 日志有乱码，退出码、调用位置仍可辨。未观察到构建已完成却未结算、同一哈希反复送审或等待反馈期间空转；目标服结论前同样的 `tail 20` 查了两次，第二次再结合旧作业分页取玩家加入记录，存在可合并的读取。

异常夹具进一步暴露副本准备的可用性问题：模型漏列运行库时，`prepare_test` 可以完成但无法启动；也曾列出不存在的可选文件，获批后 A 才收到 `WinError 2`，且留有 `server.partial`。保留失败记录并移走本轮自己的残留目录后，按缺失证据重提；模型后续在 B 只复制运行文件补齐副本，没有在 B 修改源码或构建。制品变更用例中，管理员另澄清“可用空白世界”和实际启动文件。首次 HTTPS 注入夹具误复用正常用例的实例配置文件，B 热加载时短暂将测试操作映射回本轮隔离目标，原 JAR 因占用未替换，只留下本轮同哈希的临时文件；已移除。该次不计测试结果，重建专用 host/instances 文件后才计入以上传输证据。

复验修复仅做两处：拉取在连接/截断异常时从头重传一次并清理临时文件；在 B 准备审核材料及执行时明确指出不存在的副本源，并在工具字段明示只复制列出的运行依赖。后者经实际 HTTPS 验证审核及直接执行都在创建副本前返回 `missing.jar`，不留半成品。未调整批准规则、负反馈策略或 Windows 目录重命名策略。消融审查：重传沿用同一个临时文件和调用编号；校验复用已有路径解析与审核入口；没有新增恢复状态、审批或自动重放写操作。

回归运行（Windows，AstrBot 4.29.4 放入 `PYTHONPATH`，临时目录位于本轮运行根）：

```text
python -m pytest -p no:cacheprovider --require-astrbot -q tests/test_plan_continuation.py tests/test_client_recovery.py tests/test_terminal_isolation.py tests/test_mod_workspace.py tests/test_web_downloads.py
python -m pytest -p no:cacheprovider --require-astrbot -q tests/test_mod_workspace.py tests/test_tool_contracts.py
```

第一组 49 项通过，含原批次重载、HTTPS 幂等和 B 重启；副本源检查及工具说明变更后定向复跑 16 项通过。改动文件的 Ruff lint、格式与 Git 差异检查通过。

补充用同一模型产物在新隔离目录连续运行两次真实 Java：不设置 `lithium.e2e.batchSize`、设置合法正整数 `17`。分别到 `Done (1.143s)`、`Done (0.601s)`，未见解析异常，均正常停服；未覆盖 MOD 后续性能。试服监听且没有入世界证据时，主流程确实保持待人工验收；独立的真实登录握手失败用例未测。

验收后，七个仍运行的目标服/试服经原托管窗口正常停服，日志均确认存档写出。随后结束本轮 AstrBot、B、OneBot 和托管终端；检查本轮进程及监听端口无残留。只删除本轮 `runtime/lithium-e2e-20261119-r3` 和 `.upstream/lithium-e2e-20261119-r3`（合计 8825 个文件、4235199441 字节，约 3.944 GiB），包括临时源码、产物、模型配置副本和原始日志；最小证据保留在本文。四个原保留实例与配置目录仍在，自定义规则的 SHA-256 与开测前一致。未连接真实 QQ、未操作生产服。

## 自然语言试玩确认、发布与故障留证复验

本次使用新隔离目录、独立端口、本地 OneBot v11、AstrBot 4.29.4 原生 runner、真实 Responses 排障与独立 Chat 审核、HTTPS、Windows 托管窗口和 Fabric 1.21.1。仍用 Lithium 0.15.4 入口的 `batchSize=auto` 故障；在独立 Java 进程确认异常且未就绪后，才从群里报障。没有告诉模型修法、工具顺序或替它构建。去敏的操作编号、制品哈希和判定见[机器可读结果](mod-repair-natural-e2e.json)。

- **正常链路两次跑通，最后一次在取消目录改名后重跑。** 一次有效 `/mcaiapply`，试服就绪后客户端与日志均确认进世界；发送“刚进去试了一下，没问题了”。B 审计中 `trial_stopped` 先于同一发布批次的第一个正式服步骤，两端安装使用同一制品编号和 SHA-256。旧件备份与原件一致，启动脚本和其余 MOD 未变，目标服也实际进世界。`/mcaidone` 后经验落盘；试服副本、A 工作区与两端暂存件已清，正式服备份仍在。1.21.1 协议客户端有独立物品解码告警；两侧进世界证据齐备，未据此验收物品或完整游戏操作。
- **按需提示来自实际发包。** 最后一轮 29 次主请求，前 3 次未携带详细 MOD 指引，从第 4 次一起加载工具和指引后均只带一份；独立审核 8 次、上下文压缩 3 次、验收总结 1 次。另用真实 Chat、Responses 各做一项只读端口及世界名巡检，两者均未加载指引。批准到试服实际进世界 218.3 秒，反馈到目标服进世界 62.1 秒；复跑脚本全过程 553.0 秒，包含启动、报障、批准、玩家验收、归档与清理，本次主请求 235.6 秒、审核 70.8 秒、压缩 114.0 秒。
- **真实负反馈通过。** 独立试服保留启用白名单，真实协议客户端收到 `multiplayer.disconnect.not_whitelisted`。管理员先只说没通过，MCAI 查到拒绝日志并询问是否对应；补游戏名和客户端提示后，MCAI 指出试服名单为空并继续处理。原批准仍有效，无正式服备份、替换、启停或结案。
- **Windows 改名失败实际复现。** 复跑曾在复制已完成、把 `server.partial-<操作号>` 改为 `server` 时再次报 `WinError 5`，没有登记可用副本。未确认具体持锁进程。现直接复制到本操作独立目录，全部复制和配置完成后才在 B 登记，打开前核对准备操作已结算；失败目录保留。用相同的启动 JAR、库、版本目录、`.fabric`、MOD、配置和 EULA 复验，取消目录重命名后复制成功，并完成了上述完整真实链路。
- **主动留证用真实服务端验证。** 正常启动、正常停服及计划重启未增加事件。断开托管连接只显示状态未知，重新连接后仍是原 JVM，事件数不变。单独注入 Java 退出、真实 Lithium 连续启动失败、冻结支持 Probe 0.4.1 的当前 JVM；三种分别留下对应事件，持续故障不重复生成。两个 A 离线期间存下的事件，在 A 连回 B 后经明确配置的本地 OneBot 群各收到一次；重载 A 后不重复。Java 强制退出仅由隔离测试夹具触发，MCAI 不自动重启；该案例退场时一次正常停服超时，由隔离夹具关闭已确认归属的进程。

复跑入口（源码和 npm 依赖目录由调用者提前准备；运行路径必须是本仓库 `runtime/` 下的新目录）：

```powershell
git clone --depth 1 --branch mc1.21.1-0.15.4 https://github.com/CaffeineMC/lithium.git .upstream/lithium-natural-e2e
npm --prefix runtime/mcai-e2e-client install --no-audit --no-fund minecraft-protocol@1.60.0
.\.venv\Scripts\python.exe scripts/e2e_mod_repair.py --run runtime/lithium-natural-pass --source .upstream/lithium-natural-e2e --protocol runtime/mcai-e2e-client
.\.venv\Scripts\python.exe scripts/e2e_mod_repair.py --run runtime/lithium-natural-fail --source .upstream/lithium-natural-e2e --protocol runtime/mcai-e2e-client --negative
```

另以受控 runner/真实 HTTPS 验证成员反馈和过期邀请不能提交安装、B 缺发布依据直接拒绝且不创建备份、丢失首次提交回执后只查原号、暂存文件占用后沿同一收尾编号继续、端口与源文件预检。69 项组合回归全部通过；后续 Windows、恢复及旧就绪日志的定向复验分别为 18、11、3 项通过，选择集重叠，不累计。B 重启不重放的原测试夹具误把 B 状态目录放在服务端目录内，改成隔离目录后复跑通过。打包复用未修改的 Java/Probe 产物，检查两端 ZIP，B 从解压包离线构建并独立安装 wheel，A 从解压插件加载；两端协议为 `mcai-7`。未联调真实 QQ 或生产服，未重编 Probe；没有把所有断线、重启和模型误判排列组合当作实服已覆盖。

验收结束后核对本轮进程和监听端口均无残留，清理本轮的 8393 个临时文件（约 2.06 GiB），保留现有实例、配置和最小验收证据。
