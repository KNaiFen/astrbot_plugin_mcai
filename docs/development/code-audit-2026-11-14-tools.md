# 38 工具逐项契约审查矩阵

[审查报告](code-audit-2026-11-14.md) · [开发索引](README.md)

基线 99fdba8 / Python 3.12.14 / AstrBot 4.29.4。枚举来自运行时导入 `mcai.tool_schemas.TOOLS`，共38项，非文档旧数量。A入口统一 `AstrBotAgent.run.execute` 227–335：完整jsonschema校验后才进入invoke；正常/恢复共用visible→model_result。Chat/Responses真实SDK请求的全部38份schema与TOOLS逐字相等（现有集成5项通过）；Google真实SDK请求另见缺陷R01。以下逐项检查字段和路由，执行效果依具体模块审查，不代表38工具每个模式均做了真实生产调用。原始请求、环境和逐项枚举证据在本地 `runtime/code-audit-20261114/contracts/`。

| # | 工具 | mode/action 与重点字段 | A→B/本地真实入口 | 结果/续读 |
|---|---|---|---|---|
|1|mc_inventory|可选baseline（已完成同目录inventory job）|inventory→OperationContext.background→inventory_rows|后台job；summary有partial/errors；next_call读事件，长行产物|
|2|mc_verify|checks:file/text/nbt/region/ready/tcp；standalone ready额外必需after|verify→background→verify_checks|后台job/逐检查记录|
|3|mc_diagnostics|process/jvm；pid/samples/interval|diagnostics→background→collect_diagnostics|后台job，原始快照可能产物|
|4|mc_search|search(query,domains)/open(reference,line)/find(reference,pattern)|A task_search→alpha_search→提供商alpha/search|output/results，任务级session；关闭时明确报错|
|5|mc_players|query/history|probe(kind=players)→run_probe|后台job|
|6|mc_metrics|window_seconds=10/60/300/history|probe(kind=metrics)→run_probe|后台job，含来源/采集时间|
|7|mc_objects|scope=loaded/dimension/player/chunks；category/type/group_by/top；分支定位字段|probe(kind=objects)→run_probe|后台job|
|8|mc_profile|同四scope；seconds/type/group_by/top|probe(kind=profile)→run_probe|后台job，可cancel|
|9|mc_inspect|entity(uuid,dimension?)/block(dimension,x,y,z)；nbt_path/offset/limit|probe(kind=inspect)→run_probe|后台job；参数位置为方块坐标|
|10|mc_instances|无参数|A Tasks.instances→GET /instances|实例数组，附任务占用|
|11|mc_select_instance|instance/reason必填|A Tasks.select_instance|状态/经验，目标目录持久化|
|12|mc_history|index(offset)/read(directory?,offset)/search(query,directory?,offset)|A Knowledge.query|text/next_offset；字符续读|
|13|mc_web|open(url)/read(reference,offset)/find(reference,query,offset)|A WebPages.call|text/reference/next_offset；open续读转read；find问题由integrations审查|
|14|mc_download|url必填；filename/sha256可选|download→background→Downloads.download|后台job，完成后job_id为安装download_id|
|15|mc_status|refresh_worlds?|metrics→local_perform|状态、进程、Java、世界和Probe能力；大结果转结果job|
|16|mc_files|find(pattern)/stat(path)/preview_patch(path,sha256,edits)/search(pattern,query,regex,case_sensitive,encoding,before,after,result)/tail(path,line_count,encoding)/read(path,start_line,line_count,encoding)|files_query→background→file_rows|后台job；逐行事件，长字段变产物|
|17|mc_logs|query必填；pattern/regex/case_sensitive/start_time/end_time/before/after/encoding|logs→background→log_rows|后台job；路径/行号/事件时间及上下文|
|18|mc_console_read|after/limit/session_id|console_query→RemoteTerminal.output→ConsoleBuffer.page|items/cursor/session/gap；事件续读优先，长行尾需另读，见U01|
|19|mc_console_line|session_id/seq必填；offset可选|console_query→RemoteTerminal.output→ConsoleBuffer.line|text/next_offset，next_call保留seq/session|
|20|mc_console_send|commands非空数组；script_files/encoding申报|独立审核→diagnostic_command→逐条console.write稳定子编号|sent/cancelled+逐条状态+控制台游标；next_call read|
|21|mc_exec|script必填；cwd/timeout/script_files/script_encoding|独立审核→exec→Jobs.execute|后台job，超时/非零明确失败|
|22|mc_nbt|read默认(path,nbt_path,selector,relative_path,view,offset,limit)/select(path,selector,...)/preview_batch(path,changes)|nbt_query→read_nbt/edit_nbt(preview)|即时结果/字符或列表next_offset；过大转结果job|
|23|mc_region_nbt|read(path,x,z,...)/select(path,x,z,nbt_path,selector,...)/preview_batch(path,changes含x/z)|region_query(mode不变)→world.read/edit|即时结果；全局区块坐标；过大转job|
|24|mc_region_blocks|get(path,block_x/y/z)/search(path,x,z,name,legacy_id,result,offset,limit)|region_query(mode=block/blocks)→world.block_query|即时/列表续读；块坐标与区块坐标分开|
|25|mc_region_check|仅path整区/或path+x+z+include_related点检；互斥oneOf|region_query(mode=check)→region_check/point_check|点检fingerprint供修改expected|
|26|mc_region_export|path/x/z必填；include_related/backup|region_export→background→export_chunk|后台job产出export_id/manifest.usable/sha256|
|27|mc_region_scan|world/dataset/entity_type/uuid/bounds/conditions/result/top|region_scan→background→world.scan|后台job，世界数据离线；bounds六个全局方块坐标|
|28|mc_job_read|job_id必填；after/limit|job(mode=read)→Jobs.page|job_id/status/items/cursor/next_cursor/complete|
|29|mc_job_wait|job_id必填；after/limit/wait_seconds|job(mode=wait)→同页有界等待|同read；运行时next_call wait，完成更多页read|
|30|mc_job_cancel|job_id必填|job(mode=cancel)→Jobs.cancel|实际job页，保留输出|
|31|mc_artifact_read|job_id/reference必填；offset|job(mode=artifact)→Jobs.artifact|text/next_offset；高转义内容再次包装问题见R03|
|32|mc_artifact_find|job_id/reference/query必填；regex/case_sensitive/offset/limit|job(mode=find)→Jobs.find|matches[].offset/end/preview、next_offset|
|33|mc_operation_read|operation_id必填；offset|repair_log(operation=operation_id)→local_perform|原operation/script_log/next_offset；模型侧operation_id校正为原编号|
|34|mc_context_history|无entry走after索引/或entry+offset读原文；oneOf|A Store.events context_index/context|索引cursor/next_cursor或text/next_offset；entry取body.entry|
|35|mc_propose|summary/steps必填；STEP_SCHEMA见下；外部script_files/script_encoding|整组独立审核→Tasks.propose→批准后apply_plan|awaiting_approval/approval_command；不在调用时执行|
|36|mc_say|text非空非纯空白|A Tasks.message发件箱|status=queued；平台发送另外记账（旧误报已修复）|
|37|mc_pause|reason非空|A Tasks.pause|status=paused/resume_command|
|38|mc_mods|source两站×search/project/versions/file/download，共10分支；各分支必需query/project_id/version_id或project_id+整数file_id|mods→Downloads.mods；download走background→Downloads.download|搜索/版本含分页；download job_id用于安装；Google mode等类型损坏见R01|

## 重要嵌套结构（逐项对照）

- `selector.by`：uuid→uuid；position→x/y/z（方块）；slot→slot；match→非空fields，每项nbt_path/value。
- `changes.op`：set必须nbt_path/expected/value；delete必须nbt_path/expected。expected允许null表示新字段不存在；region_change额外必需x/z。一次1..1000项。
- `conditions.op`：exists必须path；eq/ne/gt/ge/lt/le必须path/value。path使用NBT键/非负0基索引数组。
- `checks.kind`：file(path,format)；text(path,query)；nbt(path,nbt_path,expected)；region(path,x,z,nbt_path,expected)；ready(pattern，可选after/session/timeout/stable/forbid，standalone强制after)；tcp(port,timeout)。执行端verify_checks复用，计划内ready可继承先前start/restart游标。
- `steps.action`共20项：start/stop/restart；force_stop(pid,process_created,session_id)；command(command,backup_paths?)；write_text(path,content,encoding?)；patch_text(path,sha256,edits,encoding?,format?)；verify(checks)；nbt_batch(path,changes)；block_set(path,block_x/y/z,expected,state,remove_block_entity?)；region_remove(path,x,z,expected,include_related?)；region_restore(path,x,z,export_id,expected)；region_batch(path,changes)；nbt_set(path,nbt_path,value,expected?)；nbt_delete(path,nbt_path,expected?)；region_set(path,x,z,nbt_path,value,expected?)；region_delete(path,x,z,nbt_path,expected?)；script(script,backup_paths非空,timeout?)；restore(backup)；install_download(download_id,path,remove_paths?)。

`STEP_SCHEMA` 的准确动作数量为20：start、stop、restart、force_stop、command、write_text、patch_text、verify、nbt_batch、block_set、region_remove、region_restore、region_batch、nbt_set、nbt_delete、region_set、region_delete、script、restore、install_download。执行端required映射与这20项一致。不存在新加的隐式修复动作。

## 旧线索独立结论

- 当前无model_contract递归删oneOf路径；TOOLS直接传给McToolSet并由同一TOOLS校验。Chat/Responses真实请求全部保留分支及$defs，strict=false。
- mc_files.read.path、mc_artifact_read.reference（原mc_job artifact拆分）、mc_mods.file的各站编号、mc_propose.steps.command.command均在当前schema强制；集成测试向实际SDK请求schema逐一验证缺参不合法。
- mc_say返回queued，真实平台离线时出箱未sent，测试通过，已修复。
- job_id/operation_id/session_id/reference/cursor分工已明确，比旧线索改善；本轮仅单列复现成立的Google适配与嵌套包装问题。

## 参考Codex而未照搬

按用户要求查看本地 `.upstream/codex/codex-rs/tools/src/json_schema.rs` 21–23、82–138及`json_schema/types.rs`：其规范化明确保留oneOf/anyOf/allOf、$ref及可达$defs，缺type但有引用/组合时不转换为null。只用于检验‘转换前后语义须核对’的方法，不据此要求本项目照搬Codex结构或发明提供商API限制。
