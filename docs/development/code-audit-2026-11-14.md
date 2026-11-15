# 0.11.0 代码正确性审查（2026-11-14）

[开发索引](README.md) · [38 工具契约矩阵](code-audit-2026-11-14-tools.md)

后续整改见[2026-11-15修复与验证](code-audit-fixes-2026-11-15.md)。下文保留2026-11-14审查当时的缺陷行为、证据及断言方向。

## 审查结论与基线

审查对象为本地 `dev`，起始提交 `99fdba8d627583bd81a4a3588b40d40028bf39fa`，初始工作区干净。运行时实际枚举 **38 个工具、20 种方案步骤**。根目录没有 `.codegraph/`，按规则跳过，没有建立索引。

本轮确认 **11项功能缺陷（1项P1、10项P2）和1项P2工具可用性问题**。交付审查报告、隔离最小复现和证据，没有修复业务实现。两类问题分开列出；不将正常回归通过解释成没有缺陷。原始台账、分工报告、脚本、日志、HTTP 请求及 XML 保存在被忽略的 `runtime/code-audit-20261114/`，下文证据路径均相对此目录；这些本地证据不随安装包分发。

审查期间出现另一个任务对 `README.md`、`docs/development/testing.md` 的修改，未纳入本次提交。起始 README 的 Probe 0.1.0 安装文件名在同期修改中已更新，不再作为交付时的新缺陷。以下业务源码位置均基于起始提交；交付前复核源码差异。

## 已确认功能缺陷

### R01 / P1：原生 Gemini 适配把生产工具参数转换为 NULL

- **位置**：`mcai/astrbot_agent.py:77–87,701–710,728–735`，`mcai/settings.py:123–125,175–193`；基线 AstrBot `astrbot/core/agent/tool.py:249–350`，尤其292行；`gemini_source.py:257–261` 的实际调用。
- **触发**：选择设置页接受的 `googlegenai_chat_completion` 排障提供商，独立思考强度留空，进入带完整工具集的模型轮次。有效提案例子：`{"summary":"公告","steps":[{"action":"command","command":"say test"}]}`。
- **证据**：`contracts/repro_contracts.py` 使用产品 `McToolSet`、真实 AstrBot 4.29.4 提供商及 google-genai SDK，仅以 `httpx.MockTransport` 接收请求并返回受控文本。`contracts/gemini-requests.json` 是实际 SDK 发出的 HTTP 正文；主代理独立重跑结果在 `primary-contracts-repro.log:1–12`，退出0。
- **实际/应有**：38项工具确实送出，但 `mc_propose.steps.items`、`mc_nbt.nbt_path`、`mc_mods.mode` 被转为 `NULL`；`mc_region_check`、`mc_context_history` 只剩无属性的 `OBJECT`。A仍按完整 schema 要求对象、数组、字符串和分支字段。模型端与执行端不能同时满足这些冲突；应保留可调用结构，或明确拒绝暂不支持的提供商。
- **根因/范围**：`McToolSet` 只覆盖 OpenAI 输出，主提供商却不限制类型；真实 Google 转换不解析 `$ref/$defs/oneOf`，缺少 `type` 时写成 null。影响步骤、NBT路径、选择器和多种模式，足以阻断该受支持入口的主要流程。没有声称观察到外部 Gemini 服务的具体报错或模型行为。
- **漏测原因**：`tests/test_tool_contracts.py:18` 只参数化 Chat/Responses；`capabilities.py:137–150` 的平面 echo 探测不含生产引用或组合分支。Chat/Responses保留完整schema的结论本身正确。
- **最小修复/验证**：在任务私有工具边界适配该提供商，或明确限定支持范围；不修改上游，不通过删除执行约束掩盖差异。捕获真实 SDK 请求，检查步骤、NBT、枚举和根分支，并验证有效调用及结果续接。

### R02 / P2：恢复备份未处理目标类型变化，可能写错位置仍报告成功

- **位置**：`mcai/operation_context.py:900–922`，尤其908–916行，`OperationContext.apply_plan` 的 restore 分支。
- **触发**：备份原文件后，该路径被脚本或人工替换成目录；或原目录被替换成文件，再执行 `restore`。这两种目标变化均可发生在受支持的脚本修复之后。
- **证据**：`storage/repro_restore_types.py` 的真实 OperationContext/Store 复现；`storage/test_storage_repros.py` 前两项再经真实 HTTPS、辅助 worker 和临时实例验证。主代理最终复跑 `primary-storage-repro.log`：5项全部通过、12.92秒，其中两项确认本问题，两项确认R11，一项排除IntArray疑点。
- **实际/应有**：原文件 `target` 当前变目录时，`copy2(source,target)` 会生成 `target/target`，保留目录和新文件，却返回 `{"restored":...}`；反向变化对当前文件调用 `rmtree`，Windows 返回267错误。恢复应使原路径的类型与内容和备份一致。
- **根因/范围**：分支只看旧清单中的 directory 标志，未先按当前目标类型替换。影响通用备份恢复，不是NBT解析问题；备份本身尚在，不能据此声称原始备份丢失。
- **漏测原因**：现有修复测试覆盖同类型恢复、目录新增文件删除、重复备份与失败留现场，没有覆盖文件/目录互换。
- **最小修复/验证**：复用当前恢复前备份，按实际目标类型移除目标，再精确复制原类型；仍保留失败现场。HTTPS端到端验证两种互换、内容与类型、恢复前备份，以及中途失败状态。

### R03 / P2：高转义产物页被再次包装，无法按契约直接读回原文

- **位置**：`mcai/jobs.py:100–109,144–153,361–385`，`mcai/host.py:101–105`，`mcai/operation_context.py:297–298`。
- **触发**：长字段包含大量 JSON 转义字符。隔离文件一行30000个反斜杠即可；先通过 `files_query/read` 得到产物，再按原 job_id/reference 读取。
- **证据**：`contracts/test_artifact_repro.py` 通过真实HTTPS与生产worker，首次产物60046字符；连续三次读页均没有约定的 `text/next_offset`，而产生新的 result job，产物分别23999、23992、23985字符。主代理独立重跑 `primary-artifact-repro.log`：1 passed，3.18秒，退出0，累计4个job。
- **实际/应有**：应返回请求产物的一页和原文游标；实际固定12000原字符经过JSON转义超过16000结果阈值，`Jobs.result` 又转为新job。模型只能继续读包装层，原页契约被改变并新增记录。这里证明了连续三层错误包装，不宣称数学意义的无限循环。
- **根因/范围**：页长按原字符限制，返回值按二次JSON长度限制，已分页的结果再次经过相同包装。不限文件来源，也影响其他高转义长结果。
- **漏测原因**：`tests/test_tool_contracts.py:147` 使用重复中文，序列化不发生相同膨胀，普通大文本分页测试也未核对这一边界。
- **最小修复/验证**：保证分页结果满足最终序列化预算，或避免已分页产物递归包装，保持原始字符游标。通过HTTPS拼接反斜杠、引号、换行和中文的全部原文，并断言内容完全一致。

### R04 / P2：A 设置异步保存与任务启动、并发保存不互斥

- **位置**：`mcai/settings.py:138–174`，尤其171–173行；真实 AstrBot `core/config/astrbot_config.py:294–331,362–364`。
- **触发一**：保存设置通过“无worker”检查后，磁盘异步保存尚未返回时，群命令新建任务或唤醒已有任务。
- **证据一**：`main/test_settings_audit.py::test_save_a_can_replace_client_after_new_task_starts` 使用真实 AstrBotConfig，只在真实写盘线程设屏障；任务使用真实runner/HTTPS。旧任务开始生成后，保存仍成功更换 client/agent；释放生成后，原任务的 `mc_status` 被发往新URL。`main/settings-repro.log:12` 记录新URL的404与模型 `execution_state=unknown`。
- **触发二/证据**：同文件第二项让较早保存延迟、较晚保存先完成。真实配置与磁盘均为 `max_steps=42`，运行agent却被较早请求切回41，两个请求均返回 saved。两项共2 passed，8.30秒，退出0。
- **实际/应有**：检查和生效之间存在 await，任务可跨越配置边界；过期快照即使被框架拒绝提交，插件仍安装按旧快照创建的运行对象。运行中的操作应固定原环境，运行配置应对应最终已提交配置。复现只做查询，没有执行错误主机上的修改。
- **根因/范围**：设置检查、保存、生效与任务调度缺少共同串行边界；同时忽略 `save_config_async` 的提交结果。只在 await 后再查worker不足以修复并发保存覆盖。
- **漏测原因**：`tests/test_settings_search.py:389–458` 验证顺序保存和能力测试互斥，没有在异步落盘时启动任务或交错两次保存。
- **最小修复/验证**：复用任务调度的同步边界，使保存预留与任务启动协调，并仅安装当前已提交快照对应对象；不引入新配置框架。验证两个屏障场景、暂停任务续接与运行操作环境保持。

### R05 / P2：提交后的审计文件失败留下无人执行、不能结算的 pending

- **位置**：`mcai/host.py:477–503,511–524`，尤其498–500行；`mcai/storage.py:114–117`；`mcai/client.py:128–145`。
- **触发**：SQLite仍可写，但 `audit.jsonl` 单独不可写。最小请求为 status 查询，使用新的UUID与正常instance/task_id。
- **证据**：`host/test_host_audit.py::test_audit_log_failure_leaves_permanently_pending_operation` 临时把隔离审计路径设为目录，产生真实PermissionError；没有替换业务函数。主代理复跑 `primary-host-repro.log:2`：恢复日志后同编号重提仍 pending，取消仍 pending，worker_count=0，停止标志为真仍超过0.8秒。
- **实际/应有**：先保存pending，日志失败后尚未创建worker，POST返回500；重提只返回旧记录，取消只置标志，无后续推进者。0.8秒是有界观察，永久等待由上述完整路径证明，直到B重启才被结算。应明确记成未执行失败或其他可终结状态。
- **根因/范围**：非原子的持久化/审计/调度间缺少失败结算。A恢复等待不能结束，pending还会阻止实例配置切换。复现仅查询，不声称查询已有副作用。
- **漏测原因**：同编号、传输丢响应和暂时HTTP失败测试没有覆盖“DB成功、独立日志文件失败、worker未创建”的窗口。
- **最小修复/验证**：若审计失败阻止调度，结算已保存记录且明确未执行；不要默认重放副作用。验证原编号重试、取消及B重启均可解释地收尾且不重复执行。

### R06 / P2：取消尚未结算就释放实例占用

- **位置**：`mcai/tasks.py:484–503,667–710`；占用查询256–264、冲突检查207–211及288–294行。
- **触发**：暂停/等待任务仍有后台诊断，管理员中止，或运行任务中止进入finally；B取消尚未结束时新任务绑定同目录。
- **证据**：`state/test_state_audit.py` 经真实HTTPS、ConPTY及worker启动30秒诊断，只阻塞A发往B的取消调用；旧后台仍running、`cancel_pending=true`，`mc_instances`却报告 `occupied=false`，新任务选择成功。主代理独立重跑 `primary-state-repro.log` 同样成立。
- **实际/应有**：`stop`及`run`会在清理前写stopped/done，而所有冲突判断只看state；应在旧任务所属工作结算后才交接。取消失败时这个窗口还会延续。没有把只读诊断并发夸大为已造成生产写坏。
- **根因/范围**：终态转换与实例占用规则不一致，多个入口共同受影响；新任务修复只取消自己的task_id，不能保证收掉旧任务工作。
- **漏测原因**：`tests/test_task_interactions.py:131–159` 等worker结束后才断言取消；取消失败测试不检查实例占用；冲突测试覆盖活动和暂停状态。
- **最小修复/验证**：占用判定包含取消未结算，或统一延迟终态；仅删除stop的提前赋值不足。验证暂停后中止、运行中中止、验收、取消失败和重载，清理前拒绝绑定、清理后允许。

### R07 / P2：诊断根进程先退出后，后台子进程失去按任务清理能力

- **位置**：`mcai/jobs.py:21–34,246–260,309–335`，`mcai/worker.py:223–229`。
- **触发**：已接受的诊断脚本派生后台采集进程，关闭其标准流继承，然后根脚本正常退出。
- **证据**：`host/test_host_audit.py::test_detached_diagnostic_child_lives_after_success`：PowerShell调用Python派生休眠子进程。主代理复跑 `primary-host-repro.log:3`：job completed、root不存在、child仍存在、cancel仍completed、workers为空。测试finally已清理自身child。
- **实际/应有**：根退出码已非空时 `terminate_tree` 直接返回；子进程不再有可取消的任务身份。任务已完成却持续占用辅助进程共享资源。应完成清理，或把仍运行工作作为可跟踪任务返回。
- **根因/范围**：按存活根PID回收树，根先退出即失去后代。仍处于B的总Job额度内，B退出会清理；没有声称逃逸总Job或应结束MC。
- **漏测原因**：现有取消/超时/重启测试让根进程保持存活，或只核对根PID，没有覆盖成功退出根与存活后代。
- **最小修复/验证**：维持每任务的实际进程归属和清理能力，保留现有总额度；不能关闭整个共享Job来清单任务。验证根成功/失败提前退出与取消，不影响其他任务或MC。

### R08 / P2：审核API成功后的本地记录错误会触发同一请求重发

- **位置**：`mcai/agent_runtime.py:460–474,509–514`；`model_request:82–96`。
- **触发**：审核HTTP成功返回，但后续review事件/记录写失败；其他任务记录仍可写。
- **证据**：`main/test_review_logging_audit.py` 使用真实AstrBot Chat适配器及SDK，HTTP传输受控，真实SQLite触发器仅拒绝 `review:%` 事件插入。`main/review-logging-repro.log` 记录 **3次完全相同请求、3个成功HTTP响应**，最后因本地IntegrityError暂停。1 passed，15.14秒，退出0。
- **实际/应有**：成功审核响应已在追踪边界保存，独立审核闭包内的记录失败仍被 `model_request` 当成模型请求失败重试，重复消耗请求并误报审核模型未完成。应将传输/协议失败与本地持久化失败分开，后者明确停止并保留事实。
- **根因/范围**：审核响应持久化位于整个可重试调用内部。`tracing.py:151–158` 已避免追踪文件错误重发，但此路径绕过该保证；不是同一追踪函数旧问题。
- **漏测原因**：已有重试测试注入网络/模型异常，导出测试检查正常持久化；没有在成功响应后仅使review事件表写入失败。
- **最小修复/验证**：将本地持久化移出模型重试闭包或使用明确的不可重试错误分类；不得吞掉错误或把无持久审核当允许。使用相同故障断言只请求一次、无操作执行、错误明确为本地记录失败。

### R09 / P2：CLI attach 提前推进半行游标，永久漏掉行尾

- **位置**：`mcai/__main__.py:46–60`，尤其52–53行；对照 `mcai/console_buffer.py:63–70,88–101`。
- **触发**：控制台先输出未换行前缀，下一次轮询后再追加尾部。这是正常ConPTY分片，不要求故障。
- **证据**：`host/test_host_audit.py::test_attach_loses_tail_of_partially_observed_line` 的隔离服务先print HEAD、不换行，1.5秒后print TAIL；真实 `cli.control` 经HTTPS读取。`primary-host-repro.log:1`：head=true、tail=false，而缓冲tail=true。
- **实际/应有**：缓冲正确返回partial并保持cursor不变，CLI却使用entry.seq；该行完成后序号相同，被after永久跳过。应将完整行游标与已显示partial字符偏移分开，尾部显示一次。
- **根因/范围**：CLI消费者没有遵守缓冲分页协议；不扩展为模型控制台读取已经丢数据。长行next_offset及新session也未被该循环消费，静态存在同类协议缺口，但未另计独立实测问题。
- **漏测原因**：CLI测试只断言连接、输入命令和detach不关服；缓冲单测没有让实际attach读取跨轮询半行。
- **最小修复/验证**：局部修正attach消费者，使用session、完成行cursor与partial偏移；真实端到端验证跨轮询半行、长行、会话变化和不重复打印。

### R10 / P2：网页find把Unicode折叠偏移当原文偏移

- **位置**：`mcai/web.py:91–102`，尤其93、96–100行，`WebPages.call`。
- **触发**：不区分大小写查找前，原文包含casefold后长度变化的字符。页面 `"ß"*1000 + "needle" + "正文"*100`，查找needle，参数通过实际schema。
- **证据**：`integrations/repro_web_casefold.py` 经本地HTTP、真实WebPages和model_result；主代理独立重跑 `primary-web-repro.log`，退出0。`integrations/web-casefold-result.json`：原文长度1206，命中原位1000，折叠索引2000，返回offset1800、正文空、next_offset=null、ok/complete均true。
- **实际/应有**：匹配真实存在，但错误坐标截出空文；应使用原文坐标返回包含命中的上下文，offset也不能混用两种坐标。
- **根因/范围**：折叠会扩展字符，不能将折叠字符串find结果直接切原文。影响外文网页读取，未涉及生产文件修改。
- **漏测原因**：`tests/test_web_downloads.py:161–194` 的中文/ASCII关键字不改变折叠前缀长度。
- **最小修复/验证**：在原文上保留匹配位置，或建立折叠到原文坐标映射。保留当前本地HTTP复现，验证正文包含needle及非零原文offset续查。

### R11 / P2：Quilt元数据套用Fabric结构，依赖清单会错报或整次失败

- **位置**：`mcai/inventory.py:42–64,344–360`；目标依据为 `docs/design/integrations.md:62` 的明确Quilt支持，以及工具向模型暴露的组件依赖检查。
- **触发**：合法Quilt schema_version 1元数据使用字符串依赖、optional对象依赖、带独立版本的provides对象或 `minecraft.environment`。尤其字符串依赖名包含 `id`，如 `valid_lib`。
- **证据**：`storage/test_storage_repros.py` 两项Quilt复现经真实HTTPS、辅助worker和合成JAR元数据；主代理独立重跑 `primary-storage-repro.log:4–5`。三个组件返回 `errors=0/partial=false`，却漏掉必需字符串依赖、把optional记成required、忽略已提供别名，并把client环境改成 `*`；`valid_lib`用例则使整个inventory任务TypeError失败。
- **实际/应有**：列表转换只保留含 `id` 的成员，再统一用 `item["id"]` 访问；普通字符串依赖被丢弃，含id的字符串反而进入对象访问而崩溃。依赖、别名和环境应按Quilt实际结构处理；不能把合法元数据当成确定的缺依赖或完整成功清单。
- **根因/范围**：Fabric/Quilt共用解析分支，只提取quilt_loader便继续按Fabric的依赖映射、字符串provides及顶层environment解释。多个症状合并成一个格式契约根因，不按字段计数。
- **预期依据**：固定官方Quilt Loader提交 `215f55c53e219468f9b482eac8a8a6d95ed82e58` 的 `V1ModMetadataReader`，本轮另由主代理核对实际源码：字符串依赖、optional、对象provides版本及minecraft环境均有独立读取路径。准确URL和源文件SHA-256在 `storage/quilt-loader-source.json`。复现未启动Quilt游戏实例。
- **漏测原因**：`tests/test_host_inventory.py:8–104` 只有Fabric/Forge/Bukkit/数据包，损坏与未知归档测试也没有合法Quilt分支。
- **最小修复/验证**：在现有解析器内按Quilt结构读取，支持的依赖与别名保留实际语义；不能解释的组合明确标未核实，不生成确定缺失结论。两项HTTPS用例改为正确清单断言，并复核Fabric不回归，不新建后端框架。

## 已确认工具可用性问题

### U01 / P2：控制台next_call和complete未保留早页长行未读事实

位置：`mcai/tool_results.py:38–42,85–99`；`console_buffer.py:79–89,97–101`。追加15000字符长行再追加一行，`mc_console_read {after:0,limit:1}` 的第一页含 `seq=1,next_offset=12000`，但建议直接按事件游标读取第二页；第二页返回 `complete=true` 且没有next_call，第一行剩余3000字符未被建议读取。主代理在 `primary-contracts-repro.log:10–12` 独立复现。

原文仍能依据前页seq/next_offset手动调用 `mc_console_line`，因此不报内容丢失。问题是内置提示要求“读完看complete”，自动续读建议却只代表事件页完成。应明确事件分页与字符尾部的完成边界，保留未读长行的可操作指引；验证多页、多长行，而非只读单个长行。现有测试未覆盖长行与后续事件分页同时存在的建议链。

## 已复核并排除的旧线索与疑点

- **旧schema删除oneOf**：当前不存在该转换；注册与执行共用TOOLS。真实Chat/Responses请求38份schema与原定义一致、strict=false。
- **旧分支漏必填**：files.read.path、artifact.reference、mods.file两站编号、propose.command.command已在真实模型请求schema强制；不重报。
- **mc_say误报发送**：当前返回queued，平台失败不置sent；独立审核不进入主模型历史。
- **脚本只检查一次哈希**：逐步执行前复核，并按明确write/patch操作更新后续哈希，排除误报。
- **B重启unknown/failed**：机器状态failed与“状态不确定”文案有表达差异；现有failed说明允许部分效果，没有证明会自动重放或误报未执行，暂列语义核实项。
- **NBT IntArray条件比较**：真实扫描复现返回正确，nbtlib的实际布尔转换支持该路径，排除最初基于numpy直觉的疑点。
- **Quilt官方schema**：下载的schema未用all分支自身存在元schema错误，这不是本项目缺陷。最终复现以Draft7Validator实例校验检查实际用到的分支，同时独立核对官方Loader实际读取源码，未声称通过全局元schema校验。R11依据为读取实现和可达产品复现。

## 实际调用地图与测试可信度

本仓库是一个Git项目，没有Git子模块；源码分为A插件、共享Python包、B/托管与worker、Java存档辅助程序、四目标Probe、设置视图和构建脚本，上游/运行目录按忽略规则隔离。

```text
main.MCAI.commands（原生唤醒、群/管理员/引用及参数）
 → Tasks.create / feedback / approve / wake / run
 → AstrBotAgent.run → fit_history → MainProvider → 真实提供商适配器/SDK
 → capture 保存open_step/tool_call → McTool.call → jsonschema.validate
 → invoke → Reviewer.decide（独立上下文，规则/参数/脚本材料身份）
 → 提案等待管理员批准，或诊断直接提交
 → HostClient.call（先持久化的固定operation_id及remote参数）
 → HTTPS POST /operations/{id} → Host.execute / perform
 → OperationContext / Execution broker / disposable worker
 → RemoteTerminal → 独立ConPTY/PWSH/BAT/JVM，或文件/Java/下载/Probe后端
 → Store操作/后台事件/产物 → model_result → runner下一轮
 → Tasks.message持久发件箱 → deliver → MCAI.notify → 原群
 → tracing API边界 + export_diagnostics本地回放
```

入口对应开发索引中的main、astrbot_agent、agent_runtime、review、tasks、storage、host/client、operation_context、jobs、terminal/remote_terminal/console、execution/worker/memory_job、queries/world/world_tools/java、probe/mods、settings/views及build_release。38工具每个mode/action和重点嵌套对象见契约矩阵。

测试不是黑箱真实模型联调：`tests/conftest.py` 的B夹具使用真实HTTPS、ConPTY、PowerShell和worker，但BAT中的MC通常为受控Python交互进程；审核默认返回allow。`plugin_session.dispatch` 的 `/mcainew test ...` 测试简写会临时绑定实例（`test_agent_edges.py:247–257`），不能当作模型自然语言选服的证据。`local_execution` 用于在当前进程注入文件/网站失败，会替换worker；报告已逐项区分。真实适配测试使用实际框架/SDK配合受控HTTP响应，当前契约测试没有自动补齐旧review参数。

## 本轮验证记录

- Windows、Python **3.12.14**；`--require-astrbot` 实际强制 **AstrBot 4.29.4** 且零跳过。google-genai3.2.0、openai3.49.0、httpx0.28.1、jsonschema4.26.0、pytest9.2.0，见 `contracts/environment.json`。
- **完整既有回归：431 passed，0 skipped，1420.47秒，退出0**，`baseline.log/xml`。保留audioop及上游旧工具schema接口弃用警告。
- 专项既有回归：工具契约5项、任务/审核/say50项、Probe/搜索/下载/设置47项、存档43项及边界筛选41项均通过；这些与完整回归重叠，不相加为独立用例。
- 主代理独立重跑Google SDK/控制台、产物、取消占用、restore与网页复现。B日志挂起、attach半行、派生进程三个“应有行为”断言均失败，见 `primary-host-repro.log`；这是成功触发缺陷，和431项回归结果分开记录。
- 四目标Probe0.2.0，Forge/Fabric × MC1.20.1/1.21.1 × 有/无spark，**8种真实隔离安装组合全部PASS**。暂移spark的JAR已finally恢复并复核哈希；受测Probe全部class与当前构建产物相等，无Fixture或打包spark/API类。证据在 `integrations/probe-*.log`、结果JSON与 `spark-restored.json`。
- 本轮两端ZIP、四目标Probe和源码包重新构建通过。ZIP完整性、文件与当前构建源内容、必要文档链接及不含运行数据/开发规则/测试均检查通过，见 `release/package-proof.json`；源码包保留开发规则和测试，排除上游/运行数据。
- 从解压B包离线构建wheel并独立安装，空工作目录以解压A运行工具契约、追踪和导入证明 **7 passed、0 skipped、33.24秒、退出0**。`release/import-proof.json` 确认mcai及worker模块来自独立site、A入口/Agent来自解压插件，没有误用源码入口。为复用夹具仅在隔离解压目录复制测试，原始发行ZIP不含测试。证据 `wheel-build.log`、`wheel-install.log`、`release/installed-tests.log/xml`。
- Ruff检查、88个Python文件格式、设置页JS模块语法和Git空白检查通过。

主要可复现命令（项目根目录，Git Bash；Windows PYTHONPATH多路径使用分号）：

```bash
ASTRBOT_ROOT='E:/Downloads/Code/mc-astrbot-manger/runtime/code-audit-20261114/astrbot' PYTHONPATH='E:/Downloads/Code/mc-astrbot-manger/runtime/astrbot-4.29.4' .venv/Scripts/python.exe -m pytest -q --require-astrbot --junitxml=runtime/code-audit-20261114/baseline.xml
PYTHONPATH='E:/Downloads/Code/mc-astrbot-manger/runtime/astrbot-4.29.4;E:/Downloads/Code/mc-astrbot-manger/tests' .venv/Scripts/python.exe -m pytest -p conftest runtime/code-audit-20261114/host/test_host_audit.py -q -s --require-astrbot
PYTHONPATH='E:/Downloads/Code/mc-astrbot-manger/runtime/astrbot-4.29.4;E:/Downloads/Code/mc-astrbot-manger/tests' .venv/Scripts/python.exe -m pytest -p conftest runtime/code-audit-20261114/state/test_state_audit.py runtime/code-audit-20261114/contracts/test_artifact_repro.py -q -s --require-astrbot
PYTHONPATH='E:/Downloads/Code/mc-astrbot-manger/runtime/astrbot-4.29.4;E:/Downloads/Code/mc-astrbot-manger/tests' .venv/Scripts/python.exe -m pytest -p conftest runtime/code-audit-20261114/storage/test_storage_repros.py -q -s --require-astrbot
PYTHONPATH='E:/Downloads/Code/mc-astrbot-manger/runtime/astrbot-4.29.4' .venv/Scripts/python.exe -m pytest runtime/code-audit-20261114/main/test_settings_audit.py runtime/code-audit-20261114/main/test_review_logging_audit.py -q -s --require-astrbot
PYTHONPATH='E:/Downloads/Code/mc-astrbot-manger/runtime/astrbot-4.29.4' .venv/Scripts/python.exe runtime/code-audit-20261114/contracts/repro_contracts.py
.venv/Scripts/python.exe runtime/code-audit-20261114/integrations/repro_web_casefold.py
.venv/Scripts/python.exe scripts/build_release.py
```

本轮复现脚本有两种断言方向：host三项断言应有行为，因此当前退出1；其余多为确认缺陷现象的断言，退出0不代表产品已修复。初始设置复现曾误把函数写成AstrBotConfig字典项、Quilt夹具曾在官方元schema检查阶段失败；均已记入台账，未作为产品发现。

## 已完成范围与保留边界

- 完成上述主链及正常/失败/恢复分支阅读；按原编号持久化、断线核对、目录身份、热重载、批命令部分发送、审核快照与规则变化、暂停/反馈/验收归档均已沿上下游核对。
- 完成文件编码/BOM/换行、哈希补丁、备份/恢复、NBT类型/身份修改、区域坐标/压缩/MCC/关联数据和未知字段保留的代码与现有真实Java片段测试核对。
- 完成进程身份、BAT自动重启提示、独立窗口/B生命周期、共享Job额度、JVM指标单位/采集取消和控制台有界缓冲核对；没有把脚本当成OS沙箱。
- 完成Probe主线程对象读取、不主动加载区块、计数与耗时、spark有/无/失败表达、四目标接口和测试负载隔离核对。
- 完成搜索/网页、两站MOD元数据、暂存/哈希/批准安装、能力测试、A设置本地功能、API追踪/摘要/群发送/导出，以及安装构建入口核对。公共MOD API采用本地形状替身，未证明当前线上限额/策略。
- 参考本地Codex的schema规范化及search DTO，只核对相关实现，没有因其采用某结构就要求本项目照搬。
- **未做**真实QQ、计费模型、生产服/大型整合包联调；未遍历所有未来AstrBot/MC/spark版本；未重做玩家协议客户端、fixture性能负载/JFR、全部BAT包装器、整机内存耗尽/断电/物理坏盘实验。Probe真实8组合覆盖当前固定环境，不能泛化到任意模组。

交付消融复核：按根因合并，未计入风格建议、未复现竞态或已修复旧线索；保留最小复现与准确边界，没有新增审查框架、生产代码或自动修复流程。
