# 0.14.2 上下文压缩与模型请求审查

[开发索引](README.md) · [状态与恢复](../design/storage-and-recovery.md)

日期：2026-11-16。审查基线：`c45c910df1f7f91d02d1663a4fad31b357c87aa6`，已发布插件0.14.2；固定AstrBot v4.29.4、Windows／Python3.12。

本轮检查压缩投影、预算、分组、检查点、主模型／审核／验收请求、SDK包装、重试、反馈取消与API留痕。使用真实AstrBot适配器、原生runner、SQLite和隔离HTTPS实例，HTTP模型响应由MockTransport控制。原始复现运行审查基线，未调用真实计费模型或生产服务端；后续本地整改另列。

## 结论

确认6类缺陷和1处传输耦合风险，其中F01、F02优先修复。11个不同场景复现故障或记录了实际请求参数。复现用例的断言检查当前错误行为，结果表示缺陷已证实。

后续确认：用户明确压缩期间的say应等待压缩完成，再进入下一次主模型输入。F04已按此规则修正结论。F01—F07的本地整改见文末；以下问题描述和11项负向复现均保留审查基线语义，源码链接用于定位对应入口。

| 编号 | 优先级 | 问题 | 已验证的直接后果 |
|---|---|---|---|
| F01 | P1 | 完成状态校验只覆盖压缩，其他请求入口缺失 | 不完整主响应执行工具；不完整审核被接受；不完整经验被标记归档完成 |
| F02 | P1 | Responses的明确refusal被接纳为摘要 | 拒绝文本成为检查点并替换活动历史中的事实 |
| F03 | P2 | SDK浅拷贝与资源方法绑定的客户端不一致 | 选中第二个Key，真实HTTP请求仍使用第一个Key |
| F04 | P2／本地已修复 | 压缩结束后未先合入新say | 等待压缩后，多调用一次旧输入提供商接口 |
| F05 | P2 | 归档请求包装异常时丢失HTTP状态 | 永久403被重复请求3次 |
| F06 | P2／风险 | 主模型传输方式与群进度转发耦合 | 关闭转发即使用非流式；Chat主链始终非流式 |
| F07 | P2 | API留痕把消费者提前结束误记为不完整 | 已收到response.completed，api_end仍记录incomplete |

## F01：主模型、审核、验收缺少完成状态检查

位置：

- [完整流收集](../../mcai/agent_runtime.py)只检查是否收到`is_chunk=False`，不核对原始响应状态。
- [主模型结果接纳](../../mcai/agent_runtime.py)随后调用capture，后者在[保存工具步骤](../../mcai/astrbot_agent.py)时不检查完成状态。
- [审核请求](../../mcai/agent_runtime.py)校验JSON形状和decision，未核对Responses的status或Chat的finish_reason。
- [验收总结](../../mcai/astrbot_agent.py)直接返回completion_text；[归档](../../mcai/tasks.py#L366)只检查非空，随后写入经验并设置completed。

复现：

1. Responses返回`status=incomplete`、`incomplete_details.reason=max_output_tokens`，其中`mc_status`工具项仍是`status=in_progress`。转发关闭和开启两种路径均实际执行了该调用，记录为completed，任务回到waiting。
2. Chat返回`finish_reason=length`且包含可解析的`mc_status`调用，同样被执行。
3. 两种适配器均在不完整响应中返回合法`{"decision":"allow"}`，审核器均返回allow。
4. Responses返回带部分经验文本的incomplete，最终`archive_state=completed`，部分文本已保存为经验。

影响：请求尚未完整结束的结果进入工具执行、审核判定或持久经验。压缩入口已有的完整性约束未覆盖其余入口。

最小修复方向：在capture、审核decision和归档ready之前统一核对完成状态；Responses要求completed，Chat按请求用途接受stop／tool_calls等合法结束原因。未完成响应保留留痕，进入明确的重试或暂停路径；验收归档仅保存完整总结。

证据：`results/main_*.json`、`review_*.json`、`archive_incomplete.json`。

## F02：拒绝答复可替换历史摘要

位置：[压缩响应验证](../../mcai/context_budget.py)只检查非空、完成状态和缩减效果。[写入检查点](../../mcai/context_budget.py)使用completion_text。固定AstrBot的Responses解析器会将`content.type=refusal`中的文字也放入completion_text。

复现：API返回completed，消息内容只有`{"type":"refusal","refusal":"抱歉，我无法提供这份摘要。"}`。当前实现接受该结果，归档9条旧消息，将拒绝文本写成检查点。原12条消息变成4条活动消息，其中包含1条拒绝检查点和3条保留原文。

影响：SQLite原文仍可回读，但后续主模型收到的摘要没有被压缩部分的任务事实、证据和未完成事项。

最小修复方向：在归档及替换前检查原始响应中的明确refusal标记，拒绝将其作为事实摘要。沿用已有失败保留原文的机制。

证据：`results/refusal_and_trace.json`。

## F03：多Key选择与真实请求不一致

本项目复用AstrBot所用的官方SDK，没有维护SDK源码分支。这里的私有客户端指任务级实例或视图，用于隔离超时、思考强度、重试和API留痕；问题发生在实例复制与方法绑定这一层。

位置：[traced_provider](../../mcai/tracing.py)浅拷贝SDK客户端，但封装的create方法绑定在原客户端资源上。原生提供商在每次调用中选择Key，写入的是外层`self.client.api_key`；真实create读取的却是内层客户端。

复现：使用两个测试Key，固定提供商选择第二个。Chat和Responses均出现：外层SDK属性已变成第二个Key，MockTransport收到的Authorization仍对应第一个Key。复现记录仅保存布尔结果，不记录真实凭据。

影响：多Key配置中的选择失效；实际被绑定的Key不可用时，重试可能持续请求同一个不可用Key。tracing、progress、search多层包装还会扩大对不同客户端对象的引用关系。

最小修复方向：让任务私有SDK客户端及其资源方法绑定到同一个真实客户端；追踪、进度和搜索包装围绕该私有实例组合，确保api_key及timeout的修改作用于实际发送请求的实例，并保持共享提供商隔离。

证据：`results/key_openai_chat_completion.json`、`key_openai_responses.json`。

## F04：压缩结束后未先合入新say（本地已修复）

审查基线中，[MainProvider.request](../../mcai/agent_runtime.py)在创建operation／incoming等待任务之前先await inject；[inject](../../mcai/astrbot_agent.py)包含fit_history。此时[feedback](../../mcai/tasks.py#L406)已保存pending并设置input_ready，旧实现缺少准备结束后的反馈合入检查。当前通过[prepare](../../mcai/agent_runtime.py)统一准备与补救入口。

复现：将首次压缩流阻塞，提交新补充。旧压缩没有被取消，新补充停留在pending；释放压缩后，提供商调用边界先收到不含新补充的参数，随后又收到包含新补充的参数，观察值为`[false,true]`。本例在提供商方法边界采集参数，未发送真实模型HTTP请求。

按用户确认，等待当前压缩完成是预期行为。缺陷是完成后未先合入pending，产生旧输入的额外提供商调用。新补充已经持久保存，本例未丢失消息。

本地修复：准备阶段结束后检查新反馈，先合入摘要和保留原文并重新核算预算；超限补救压缩也等待完成，再以新输入发起主请求。压缩期间的say不取消摘要，管理员停止／暂停仍沿原有路径处理。正向回归为`test_say_during_compaction_waits_and_joins_next_model_input`的initial和context_recovery两个场景。

证据：`results/steer_during_compaction.json`。

## F05：归档重试丢失永久错误分类

位置：[model_request的pause_on_error=False分支](../../mcai/agent_runtime.py)将原始错误转换成仅含字符串的ValueError；[归档外层重试](../../mcai/tasks.py#L374)再次调用retryable，已无法读取HTTP状态。

复现：验收接口固定返回HTTP403、错误正文为Access denied／forbidden。内部单次请求正确结束，外层看到ValueError后将其当成未知可重试异常，同一403共请求3次，归档保持pending。

影响：永久HTTP错误失去结构化分类，产生无效等待和重复请求；结果取决于错误正文能否碰巧匹配正则。

最小修复方向：向外层保留原始异常及HTTP状态，或在同一请求边界完成分类与重试；按状态判断永久错误。

证据：`results/archive_403.json`。

## F06：主模型流式与转发开关耦合

位置：[主请求stream选择](../../mcai/astrbot_agent.py)为`self.forward_progress and responses`，[runner配置](../../mcai/astrbot_agent.py)直接使用该值。

复现：相同Responses提供商下，关闭群进度转发时HTTP请求`stream=false`，开启时为true；复现提供商配置的读取超时为120秒，两种路径均沿用120秒。Chat主请求在该条件下始终非流式。压缩请求的300秒设置独立于这些入口。

影响：群消息展示开关改变了网络传输行为；服务商需要长时间生成完整答案时，非流式路径仍面临等待完整响应的超时风险。本项确认了请求参数和配置耦合，未联调真实慢服务商的耗时。

最小修复方向：将API流式接收与群进度转发分开，展示开关只控制消息转发；各类模型请求的超时范围明确记录。

证据：`results/main_openai_responses_False.json`、`main_openai_responses_True.json`及源码条件。

## F07：成功的流式响应被误记为incomplete

位置：[TraceStream](../../mcai/tracing.py)仅在异步迭代器自然耗尽时将状态改为completed。固定AstrBot的Responses解析器收到终结事件即返回，追踪生成器随后关闭，保留初始incomplete状态。

复现：同一请求的API片段已记录`response.completed`，业务层已完成检查点保存，`api_end.status`却为incomplete。

影响：业务成功与诊断状态互相矛盾，容易将正常结束判断为断流。该问题涉及留痕判定，独立的api_error仍应按其实际错误分析。

最小修复方向：用协议终结事件或Chat结束原因确定响应完成状态，并显式关闭流；区分已收到终结结果与消费者自然耗尽。

证据：`results/refusal_and_trace.json`。

## 复现记录与覆盖边界

证据目录：被忽略的`runtime/audit-context-20261116/`。

- `test_reproductions.py`：复用现有真实runner／HTTPS夹具的定向复现。
- `reproductions.xml`／`.log`：首批9项中8项观察到目标缺陷；补充消息用例的合成窗口小于工具提示开销，调整为65536后复核。
- `recheck.xml`／`.log`：补充消息复核与两个适配器的多Key复现，共3项确认。
- `audit-evidence.json`：按场景最后一次结果合并，去重11项、零跳过，并保存结构化观察值。

复现上述审查基线时，在固定开发环境中将仓库根、AstrBot v4.29.4和仓库tests目录加入PYTHONPATH，以`-p conftest`加载既有夹具后，可运行。该命令只用于审查基线；修复后应运行tests中的正向回归，旧负向断言不再成立：

```text
.venv/Scripts/python.exe -m pytest -p conftest runtime/audit-context-20261116/test_reproductions.py --require-astrbot -q
```

本轮沿调用链核对了95%触发、可读投影、完整工具分组、最新消息保护、API用量前缀、原文先归档、连续检查点、上下文超限缩批，以及恢复时沿用原编号。300秒是网络操作超时，持续返回数据的流可以超过300秒。上述既有设计继续作为修复约束。

## 本地整改

| 编号 | 当前实现 | 正向回归 |
|---|---|---|
| F01 | model_request在主结果接纳与验收归档前统一核对完成状态；审核在解析和保存decision前调用同一检查。主请求允许完整工具结束，摘要要求正常文本结束 | `test_incomplete_main_response_never_prepares_or_executes_tools`、`test_incomplete_review_cannot_allow_operation`、`test_archive_requires_complete_summary_and_preserves_error_status` |
| F02 | 明确refusal作为摘要请求失败，停止无效重试；不替换活动历史或写入经验 | `test_explicit_refusal_keeps_raw_history_and_trace_completes`及归档拒绝场景 |
| F03 | 使用官方SDK的with_options建立真实任务私有客户端，再从该实例取得bound create；search／progress复用同一私有实例。禁用SDK重试，共享资源、Key和配置保持原样 | `test_private_sdk_key_routes_through_all_wrappers_without_mutating_shared_client`覆盖Chat／Responses及组合包装；压缩测试核对300秒超时与共享配置 |
| F04 | 压缩完成后先合入say、重新核算预算，再开始下一主请求；阈值与超限补救入口一致 | `test_say_during_compaction_waits_and_joins_next_model_input` |
| F05 | 向外包装异常时保留cause，归档外层沿原因读取原HTTP状态；403只请求一次，503按既有预算重试 | `test_archive_requires_complete_summary_and_preserves_error_status` |
| F06 | Chat／Responses主链独立启用流式；群开关只控制commentary转发；保留服务商明确不支持stream时的兼容分支 | 主完整性场景、客户端路由场景、`api_compatibility.py`的unsupported_stream场景 |
| F07 | 收到Responses终结事件时即结算并关闭底层流；Chat依据各choice结束原因判定，继续读取usage尾片段；每请求只留一条api_end。非流式响应也按status／finish_reason记录 | 拒绝摘要、主／审核完整性、客户端路由与`test_tracing.py` |

消融审查：完成性共用一个检查入口，错误分类复用既有重试边界，客户端直接使用官方SDK现有复制方法；保留95%触发、300秒压缩网络操作超时、完整分组、SQLite检查点和原操作编号。不增加配置、协议、数据库表或SDK源码分支。

验证：Windows／Python3.12／AstrBot v4.29.4／SDK 3.49.0下，共享流程119项及最终23项专项复核全部通过，合并去重120个场景、零跳过；SDK 1.78.0复跑同组23项全部通过。证据为`runtime/request-fixes-*.xml`／`.log`及`request-fixes-validation.json`，范围和限制见[测试说明](testing.md#当前验证)。本地F01—F07均已修复，尚未发版；真实服务商耗时与摘要质量仍未联调。

## 协议依据

- [OpenAI Responses流式事件](https://developers.openai.com/api/reference/resources/responses/streaming-events)：completed、incomplete、failed为不同终结结果。
- [OpenAI Chat流式事件](https://developers.openai.com/api/reference/resources/chat/subresources/completions/streaming-events)：finish_reason区分stop、length、tool_calls等；usage尾片段的choices可为空。
- [OpenAI Python SDK](https://developers.openai.com/api/reference/python)：按请求覆盖timeout／max_retries；具体适配行为以本轮固定AstrBot及已安装SDK复现为准。
