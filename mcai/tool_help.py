"""Task-sized tool guidance, loaded with the corresponding callable contract."""

from .tool_schemas import BASE_TOOLS, TOOLS

EXAMPLES = {
    "mc_instances": {},
    "mc_select_instance": {
        "instance": "cti",
        "reason": "管理员指定的服务端名称与目录说明一致",
    },
    "mc_status": {},
    "mc_history": {"mode": "search", "query": "启动失败"},
    "mc_knowledge": {"case_id": "索引中的经验编号"},
    "mc_web": {"mode": "open", "url": "https://example.org/manual"},
    "mc_search": {"mode": "search", "query": "Minecraft watchdog server thread"},
    "mc_download": {"url": "https://example.org/mod.jar", "filename": "mod.jar"},
    "mc_workspace": {"mode": "list"},
    "mc_test_server": {"mode": "status"},
    "mc_inventory": {},
    "mc_diagnostics": {"mode": "jvm", "samples": 1},
    "mc_verify": {
        "checks": [
            {
                "kind": "ready",
                "query": "Done (",
                "cursor": 501,
                "session_id": "S",
                "timeout_seconds": 300,
            }
        ]
    },
    "mc_players": {"query": "Steve", "history": True},
    "mc_metrics": {"window_seconds": 60},
    "mc_objects": {
        "scope": "dimension",
        "dimension": "minecraft:overworld",
        "group_by": "type",
    },
    "mc_profile": {"engine": "spark", "duration_seconds": 30, "threads": "server"},
    "mc_inspect": {
        "target": "block",
        "dimension": "minecraft:overworld",
        "x": 1,
        "y": 64,
        "z": 1,
    },
    "mc_chunks": {"scope": "dimension", "dimension": "minecraft:overworld", "top": 10},
    "mc_runtime": {"section": "summary"},
    "mc_console_read": {"cursor": 501, "session_id": "S"},
    "mc_console_line": {"session_id": "S", "seq": 502, "offset": 12000},
    "mc_console_send": {"commands": ["list", "spark tps"]},
    "mc_exec": {
        "script": "Get-Content -LiteralPath './server.properties' -TotalCount 30"
    },
    "mc_job_read": {"job_id": "J", "cursor": 0},
    "mc_job_wait": {"job_id": "J", "cursor": 0},
    "mc_job_cancel": {"job_id": "J"},
    "mc_artifact_read": {
        "job_id": "J",
        "reference": "R.json",
        "result_path": ["target", "expected"],
        "view": "value",
    },
    "mc_artifact_find": {"job_id": "J", "reference": "R.json", "query": "目标文本"},
    "mc_operation_read": {"operation_id": "O", "result_path": ["operation", "status"]},
    "mc_context_history": {"entry": 1, "result_path": ["result"], "view": "summary"},
    "mc_propose": {
        "summary": "重启服务端并确认正常上线",
        "steps": [
            {"action": "start"},
            {
                "action": "verify",
                "checks": [
                    {"kind": "ready", "query": "Done (", "timeout_seconds": 300}
                ],
            },
        ],
    },
    "mc_plan_finish": {"plan_id": "P", "summary": "两批验证都通过，方案结束"},
    "mc_say": {
        "text": "麻烦发一下大概几点开始报错的，用 “/mcaisay 任务名 内容” 回复就行"
    },
    "mc_pause": {"reason": "托管窗口未打开，需要管理员在服务端目录运行mcai tm"},
    "mc_mods": {
        "source": "modrinth",
        "mode": "search",
        "query": "Lithium",
        "game_version": "1.20.1",
        "loader": "fabric",
    },
}
GUIDANCE = {
    "mc_propose": "首次提交summary与具体steps；summary发给群里管理员看，用一两句人话写清原因、目标与关键风险或备份状态即可（启动参数和只读核验证据由程序直接交给审核，不要写进summary）。需按结果分批决策时同时声明continuation.scope/completion。"
    "返回awaiting_approval后结束本轮等待程序提示批准。批准后续批仅带原plan_id、summary与steps；"
    "每批仍独立审核，原授权范围内无需再次批准。观察实际结果再续批，完成后mc_plan_finish并请求验收。"
    "文件写入、NBT修改或恢复前停服，程序按目标备份；通用script须声明全部backup_paths。"
    "NBT expected为带类型的旧SNBT，null仅用于确认新字段不存在。快照由程序插入。"
    '\n多轮首批：mc_propose {"summary":"发第一阶段维护公告（在线命令无恢复备份）","continuation":{"scope":"仅向当前实例发送已确认的两阶段维护公告","completion":"第二阶段公告已发送并核对控制台"},"steps":[{"action":"command","command":"say Maintenance phase 1"}]}'
    '\n后续批次：mc_propose {"plan_id":"P","summary":"第一阶段已发出，继续发第二阶段公告（在线命令无恢复备份）","steps":[{"action":"command","command":"say Maintenance phase 2"}]}',
    "mc_verify": "ready和text默认字面量匹配，query=Done (无需regex=true。text可直接查询目标行原文；"
    "regex=true时^/$默认针对整份文本，逐行锚定须显式使用(?m)，不要误把单行表达式当作多行验证。"
    "独立验证使用本次启动的cursor/session_id，"
    "同一提案可继承启动游标。TCP只证明本机端口连接；file验证语法，text/NBT核对目标值。"
    '\n配置解析：mc_verify {"checks":[{"kind":"file","path":"config/settings.toml","format":"toml"}]}'
    '\n端口检查：mc_verify {"checks":[{"kind":"tcp","port":25565}]}',
    "mc_query": "内存趋势用diagnostics memory-trend，按next_call静默续读。堆转储先用process或jvm核对PID与诊断盘空间，"
    "取得明确同意后用heap-dump --admin-feedback-id，顶层evidence_ids引用已结算诊断结果供审核。",
    "mc_console_send": "commands即使只有一条也用数组。已验证隔离试服的整批白名单只读命令免审，其余独立审核；status=sent只确认已发送，"
    "沿返回next_call读取实际输出，不能据此宣称命令效果已达成。修改、启停与保存提交mc_propose。",
    "mc_console_read": "session_id和cursor取本次真实返回值。pending_reads可能同时含多条长行和下一事件页；"
    "完整页需逐项续读，单条长行读完不等于整页读完。当前决定证据足够即可推进。",
    "mc_exec": "在线PowerShell诊断由独立模型审核。外部脚本才填写script_files/script_encoding；"
    "使用已有查询CLI可直接完成的查询时优先mc_query。脚本修改使用mc_propose，声明备份路径。",
    "mc_artifact_read": "先读summary，再按概览的result_path精确取值。NBT对象优先查询CLI的children/selector。"
    "文本先mc_artifact_find取得offset，再读取必要原文。covered_by表示已有上下文保留的区间。",
    "mc_chunks": "scheduled_backlog 查范围内已加载区块的待执行计划刻数量。先看积压，再用 mc_profile 定位实测耗时。",
    "mc_profile": "Probe采样实测对象及可用区块阶段的tick耗时；spark报告采样权重。解释来源、范围与窗口。"
    "每实例一次采样；若已有外部spark采样，按实际冲突处理。",
    "mc_inspect": "实体使用实际UUID，方块使用全局方块坐标。只读已加载对象；未找到UUID不能证明已删除。",
}


def tool_help(name):
    description = next(description for tool, description, _ in TOOLS if tool == name)
    return {
        "name": name,
        "description": description,
        "guidance": GUIDANCE.get(
            name, "按当前目标选择必要参数；编号、路径和坐标均取实际返回值。"
        ),
        "example": {"name": name, "arguments": EXAMPLES[name]},
    }


def tool_catalog():
    return "\n".join(
        f"- {name}：{description.split('。')[0]}"
        for name, description, _ in TOOLS
        if name not in BASE_TOOLS
    )


def resolved_query(record):
    """Keep the model call identity separate from its persisted query semantics."""
    query = record.get("query")
    return (
        (query["name"], query["arguments"])
        if query
        else (record["name"], record["arguments"])
    )
