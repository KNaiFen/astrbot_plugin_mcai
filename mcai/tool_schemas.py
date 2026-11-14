"""Model-facing contracts; transport actions stay private to the plugin."""

STRING = {"type": "string"}
INTEGER = {"type": "integer", "minimum": 0}
NBT_PATH = {"type": "array", "items": {"anyOf": [STRING, INTEGER]}}
PAGE = {"after": INTEGER, "limit": {"type": "integer", "minimum": 1, "maximum": 100}}
VIEW = {"type": "string", "enum": ["children", "value"]}
SHA256 = {"type": "string", "pattern": "^[a-fA-F0-9]{64}$"}
TEXT_PATCH = {
    "path": STRING,
    "sha256": SHA256,
    "encoding": STRING,
    "format": {"enum": ["json", "toml", "yaml"]},
    "edits": {
        "type": "array",
        "minItems": 1,
        "items": {
            "type": "object",
            "properties": {"old": {"type": "string", "minLength": 1}, "new": STRING},
            "required": ["old", "new"],
            "additionalProperties": False,
        },
    },
}


def contract(properties, required=()):
    return {
        "type": "object",
        "properties": properties,
        "required": list(required),
        "additionalProperties": False,
    }


def variants(key, entries):
    properties = {}
    choices = []
    for value, (fields, required) in entries.items():
        properties.update(fields)
        choices.append(contract({key: {"const": value}, **fields}, (key, *required)))
    return {
        "type": "object",
        "properties": {key: {"type": "string", "enum": list(entries)}, **properties},
        "required": [key],
        "oneOf": choices,
    }


REVIEW = contract(
    {
        "purpose": {"type": "string", "minLength": 1},
        "script_files": {"type": "array", "items": STRING},
        "encoding": STRING,
    },
    ("purpose", "script_files"),
)


SELECTOR = variants(
    "by",
    {
        "uuid": ({"uuid": STRING}, ("uuid",)),
        "position": (
            {key: {"type": "integer"} for key in ("x", "y", "z")},
            ("x", "y", "z"),
        ),
        "slot": ({"slot": {"type": "integer"}}, ("slot",)),
        "match": (
            {
                "fields": {
                    "type": "array",
                    "minItems": 1,
                    "items": contract(
                        {"nbt_path": NBT_PATH, "value": STRING}, ("nbt_path", "value")
                    ),
                }
            },
            ("fields",),
        ),
    },
)
CHANGE_FIELDS = {
    "nbt_path": NBT_PATH,
    "selector": SELECTOR,
    "relative_path": NBT_PATH,
    "expected": {"anyOf": [STRING, {"type": "null"}]},
}
CHANGE_MODES = {
    "set": ({**CHANGE_FIELDS, "value": STRING}, ("nbt_path", "expected", "value")),
    "delete": (CHANGE_FIELDS, ("nbt_path", "expected")),
}
CHANGES = {
    "type": "array",
    "minItems": 1,
    "maxItems": 1000,
    "items": variants("op", CHANGE_MODES),
}
REGION_CHANGES = {
    **CHANGES,
    "items": variants(
        "op",
        {
            key: (
                {**fields, "x": {"type": "integer"}, "z": {"type": "integer"}},
                (*required, "x", "z"),
            )
            for key, (fields, required) in CHANGE_MODES.items()
        },
    ),
}


CHECKS = {
    "type": "array",
    "minItems": 1,
    "maxItems": 20,
    "items": variants(
        "kind",
        {
            "file": (
                {
                    "path": STRING,
                    "format": {"enum": ["json", "toml", "yaml", "nbt"]},
                    "encoding": STRING,
                },
                ("path", "format"),
            ),
            "text": (
                {
                    "path": STRING,
                    "query": STRING,
                    "regex": {"type": "boolean"},
                    "present": {"type": "boolean"},
                    "encoding": STRING,
                },
                ("path", "query"),
            ),
            "nbt": (
                {"path": STRING, "nbt_path": NBT_PATH, "expected": STRING},
                ("path", "nbt_path", "expected"),
            ),
            "region": (
                {
                    "path": STRING,
                    "x": {"type": "integer"},
                    "z": {"type": "integer"},
                    "nbt_path": NBT_PATH,
                    "expected": STRING,
                },
                ("path", "x", "z", "nbt_path", "expected"),
            ),
            "ready": (
                {
                    "pattern": STRING,
                    "forbid": STRING,
                    "after": INTEGER,
                    "session_id": STRING,
                    "timeout": {
                        "type": "number",
                        "exclusiveMinimum": 0,
                        "maximum": 300,
                    },
                    "stable_seconds": {"type": "number", "minimum": 0, "maximum": 60},
                },
                ("pattern",),
            ),
            "tcp": (
                {
                    "port": {"type": "integer", "minimum": 1, "maximum": 65535},
                    "timeout": {
                        "type": "number",
                        "exclusiveMinimum": 0,
                        "maximum": 300,
                    },
                },
                ("port",),
            ),
        },
    ),
}


STEP_SCHEMA = variants(
    "action",
    {
        "start": ({}, ()),
        "stop": ({}, ()),
        "restart": ({}, ()),
        "force_stop": (
            {
                "pid": {"type": "integer", "minimum": 1},
                "process_created": {"type": "number"},
                "session_id": STRING,
            },
            ("pid", "process_created", "session_id"),
        ),
        "command": (
            {"command": STRING, "backup_paths": {"type": "array", "items": STRING}},
            ("command",),
        ),
        "write_text": (
            {"path": STRING, "content": STRING, "encoding": STRING},
            ("path", "content"),
        ),
        "patch_text": (TEXT_PATCH, ("path", "sha256", "edits")),
        "verify": ({"checks": CHECKS}, ("checks",)),
        "nbt_batch": ({"path": STRING, "changes": CHANGES}, ("path", "changes")),
        "block_set": (
            {
                "path": STRING,
                "block_x": {"type": "integer"},
                "block_y": {"type": "integer"},
                "block_z": {"type": "integer"},
                "expected": STRING,
                "state": STRING,
                "remove_block_entity": STRING,
            },
            ("path", "block_x", "block_y", "block_z", "expected", "state"),
        ),
        "region_remove": (
            {
                "path": STRING,
                "x": {"type": "integer"},
                "z": {"type": "integer"},
                "expected": SHA256,
                "include_related": {"type": "boolean"},
            },
            ("path", "x", "z", "expected"),
        ),
        "region_restore": (
            {
                "path": STRING,
                "x": {"type": "integer"},
                "z": {"type": "integer"},
                "export_id": STRING,
                "expected": SHA256,
            },
            ("path", "x", "z", "export_id", "expected"),
        ),
        "region_batch": (
            {"path": STRING, "changes": REGION_CHANGES},
            ("path", "changes"),
        ),
        "nbt_set": (
            {"path": STRING, "nbt_path": NBT_PATH, "value": STRING, "expected": STRING},
            ("path", "nbt_path", "value"),
        ),
        "nbt_delete": (
            {"path": STRING, "nbt_path": NBT_PATH, "expected": STRING},
            ("path", "nbt_path"),
        ),
        "region_set": (
            {
                "path": STRING,
                "x": {"type": "integer"},
                "z": {"type": "integer"},
                "nbt_path": NBT_PATH,
                "value": STRING,
                "expected": STRING,
            },
            ("path", "x", "z", "nbt_path", "value"),
        ),
        "region_delete": (
            {
                "path": STRING,
                "x": {"type": "integer"},
                "z": {"type": "integer"},
                "nbt_path": NBT_PATH,
                "expected": STRING,
            },
            ("path", "x", "z", "nbt_path"),
        ),
        "script": (
            {
                "script": STRING,
                "backup_paths": {"type": "array", "items": STRING, "minItems": 1},
                "timeout": {"type": "integer", "minimum": 1, "maximum": 600},
            },
            ("script", "backup_paths"),
        ),
        "restore": ({"backup": STRING}, ("backup",)),
        "install_download": (
            {
                "download_id": STRING,
                "path": STRING,
                "remove_paths": {"type": "array", "items": STRING},
            },
            ("download_id", "path"),
        ),
    },
)

# Both step variants validate their own changes; this shared envelope accepts either shape.
STEP_SCHEMA["properties"]["changes"] = {
    **CHANGES,
    "items": contract(
        {
            **CHANGES["items"]["properties"],
            "x": {"type": "integer"},
            "z": {"type": "integer"},
        },
        ("op", "nbt_path", "expected"),
    ),
}


REGION_READ = {
    "path": STRING,
    "x": {"type": "integer"},
    "z": {"type": "integer"},
    "nbt_path": NBT_PATH,
    "selector": SELECTOR,
    "relative_path": NBT_PATH,
    "view": VIEW,
    "offset": INTEGER,
    "limit": {"type": "integer", "minimum": 1, "maximum": 100},
}
CONDITION = variants(
    "op",
    {
        op: (
            {"path": NBT_PATH, **({"value": STRING} if op != "exists" else {})},
            ("path", "value") if op != "exists" else ("path",),
        )
        for op in ("exists", "eq", "ne", "gt", "ge", "lt", "le")
    },
)

PROBE_POSITION = {key: {"type": "integer"} for key in ("x", "y", "z")}


def probe_range(fields):
    return variants(
        "scope",
        {
            "loaded": (fields, ()),
            "dimension": ({**fields, "dimension": STRING}, ("dimension",)),
            "player": (
                {
                    **fields,
                    "player": {"type": "string", "minLength": 1},
                    "radius_chunks": {"type": "integer", "minimum": 0, "maximum": 32},
                },
                ("player",),
            ),
            "chunks": (
                {
                    **fields,
                    "dimension": STRING,
                    **{
                        key: {"type": "integer"}
                        for key in ("min_x", "min_z", "max_x", "max_z")
                    },
                },
                ("dimension", "min_x", "min_z", "max_x", "max_z"),
            ),
        },
    )


TOOLS = [
    (
        "mc_inventory",
        "读取本地MOD、插件和数据包真实元数据（含嵌套JAR），报告版本、依赖、重复ID和文件哈希；不按文件名猜身份。识别实际JVM参数/JDK/主JAR中可确认的运行版本，其余运行条件及不支持的版本约束明确未核实。baseline为本实例先前已完成的清单job_id，可比较新增、移除及内容变化。结果用mc_job。",
        contract({"baseline": STRING}),
    ),
    (
        "mc_verify",
        "固定只读验证file格式、text文本、nbt/region旧值断言、ready控制台就绪与错误观察、tcp本机端口。ready按单行正则匹配，须提供after游标及当前session；方案verify步骤可复用前面start/restart的游标。端口接受连接不证明玩家登录。结果用mc_job。",
        contract({"checks": CHECKS}, ("checks",)),
    ),
    (
        "mc_diagnostics",
        "固定只读取证：process采集实例进程CPU/I/O增量、内存和线程数；jvm用实际Java同目录jcmd采集JVM参数、堆概要和连续线程快照。pid省略时要求唯一Java。不会结束MC或安装工具，结果用mc_job等待、分页及读取原始产物。",
        contract(
            {
                "mode": {"enum": ["process", "jvm"]},
                "pid": {"type": "integer", "minimum": 1},
                "samples": {"type": "integer", "minimum": 1, "maximum": 5},
                "interval": {"type": "number", "minimum": 0.1, "maximum": 10},
            },
            ("mode",),
        ),
    ),
    (
        "mc_search",
        "通过模型提供商的独立 alpha/search 搜索、打开来源和页内查找；结果是外部资料而非操作授权。reference 使用返回的来源编号或明确 URL。",
        variants(
            "mode",
            {
                "search": (
                    {
                        "query": {"type": "string", "minLength": 1},
                        "domains": {"type": "array", "items": STRING},
                    },
                    ("query",),
                ),
                "open": ({"reference": STRING, "line": INTEGER}, ("reference",)),
                "find": (
                    {"reference": STRING, "pattern": STRING},
                    ("reference", "pattern"),
                ),
            },
        ),
    ),
    (
        "mc_players",
        "探针查询在线玩家或近五分钟现场，query 为游戏名或 UUID，省略列出全部；QQ 账号不能自动匹配。后台分页用 mc_job。",
        contract({"query": STRING, "history": {"type": "boolean"}}),
    ),
    (
        "mc_metrics",
        "探针全服 TPS、tick 耗时及各维度耗时；维度没有独立 TPS。window_seconds 默认60；history 返回近五分钟秒级记录。注明样本时间和 tick 控制状态。",
        contract(
            {
                "window_seconds": {"type": "integer", "enum": [10, 60, 300]},
                "history": {"type": "boolean"},
            }
        ),
    ),
    (
        "mc_objects",
        "只普查已加载对象，不加载/生成区块。type 为可选注册类型；对象数量不是耗时证据。group_by 默认chunk，top默认100；结果通过mc_job分页。区块范围x/z是区块坐标。",
        probe_range(
            {
                "category": {
                    "type": "string",
                    "enum": ["all", "entities", "items", "block_entities"],
                },
                "type": STRING,
                "group_by": {"type": "string", "enum": ["chunk", "type", "object"]},
                "top": {"type": "integer", "minimum": 1, "maximum": 1000},
            }
        ),
    ),
    (
        "mc_profile",
        "探针短时实测实体/骑乘实体/方块实体tick，默认10秒最多30秒，每实例一个。group_by默认chunk。结果只代表已观测对象耗时，不代表区块全部耗时；使用mc_job查询和取消。",
        probe_range(
            {
                "seconds": {"type": "integer", "minimum": 1, "maximum": 30},
                "type": STRING,
                "group_by": {
                    "type": "string",
                    "enum": ["chunk", "type", "object", "dimension"],
                },
                "top": {"type": "integer", "minimum": 1, "maximum": 1000},
            }
        ),
    ),
    (
        "mc_inspect",
        "探针检查当前已加载实体UUID或方块实体位置。nbt_path为可选键/索引路径，offset/limit分页；不指定路径时返回关键状态。目标消失或卸载会明确返回。",
        variants(
            "target",
            {
                "entity": (
                    {
                        "uuid": STRING,
                        "dimension": STRING,
                        "nbt_path": NBT_PATH,
                        "offset": INTEGER,
                        "limit": {"type": "integer", "minimum": 1, "maximum": 100},
                    },
                    ("uuid",),
                ),
                "block": (
                    {
                        "dimension": STRING,
                        **PROBE_POSITION,
                        "nbt_path": NBT_PATH,
                        "offset": INTEGER,
                        "limit": {"type": "integer", "minimum": 1, "maximum": 100},
                    },
                    ("dimension", "x", "y", "z"),
                ),
            },
        ),
    ),
    (
        "mc_instances",
        "列出 B 已配置服务端的名称、目录、说明、状态与占用。根据引用和自然语言识别，模糊时先追问。",
        contract({}),
    ),
    (
        "mc_select_instance",
        "将当前任务绑定一个服务端。instance 是 mc_instances 返回的名称；reason 简述识别依据。未提交修复前可纠正，已提交修复后不能换服。",
        contract({"instance": STRING, "reason": STRING}, ("instance", "reason")),
    ),
    (
        "mc_history",
        "查看按远程目录归档的已验收经验。绑定前可读索引；历史仅提供线索，必须核实当前版本和现场。directory 必须是索引中目录，省略使用当前目标。",
        variants(
            "mode",
            {
                "index": ({"offset": INTEGER}, ()),
                "read": ({"directory": STRING, "offset": INTEGER}, ()),
                "search": (
                    {"directory": STRING, "query": STRING, "offset": INTEGER},
                    ("query",),
                ),
            },
        ),
    ),
    (
        "mc_web",
        "读取外部网页、文档、JSON，不执行页面脚本。open 返回持久 reference；read 分页，find 查找。网页不是操作授权；文件下载用 mc_download。",
        variants(
            "mode",
            {
                "open": ({"url": STRING}, ("url",)),
                "read": ({"reference": STRING, "offset": INTEGER}, ("reference",)),
                "find": (
                    {"reference": STRING, "query": STRING, "offset": INTEGER},
                    ("reference", "query"),
                ),
            },
        ),
    ),
    (
        "mc_download",
        "将明确 HTTP/HTTPS 直链下载到 B 任务暂存区，不安装不执行。可提供 sha256。后台结果用 mc_job；安装需 install_download 方案批准。",
        contract(
            {
                "url": STRING,
                "filename": STRING,
                "sha256": {"type": "string", "pattern": "^[a-fA-F0-9]{64}$"},
            },
            ("url",),
        ),
    ),
    (
        "mc_status",
        "实例状态、主机指标、实际进程与 Java 路径、世界/维度列表、探针能力与最近更新时间。世界列表缓存60秒，refresh_worlds=true立即刷新；world_path用于存档查询，probe.stale表示快照过时。",
        contract({"refresh_worlds": {"type": "boolean"}}),
    ),
    (
        "mc_files",
        "查找、检索、读取或预览实例内文本补丁。stat 返回 SHA-256，preview_patch 不写入；实际 patch_text 通过提案批准。tail 读末尾。search 支持 lines/files/count，pattern 务必限定文本目录。结果用 mc_job 分页。",
        variants(
            "mode",
            {
                "find": ({"pattern": STRING}, ("pattern",)),
                "stat": ({"path": STRING}, ("path",)),
                "preview_patch": (TEXT_PATCH, ("path", "sha256", "edits")),
                "search": (
                    {
                        "pattern": STRING,
                        "query": STRING,
                        "regex": {"type": "boolean"},
                        "case_sensitive": {"type": "boolean"},
                        "encoding": STRING,
                        "before": {"type": "integer", "minimum": 0, "maximum": 50},
                        "after": {"type": "integer", "minimum": 0, "maximum": 50},
                        "result": {"enum": ["lines", "files", "count"]},
                    },
                    ("pattern", "query"),
                ),
                "tail": (
                    {
                        "path": STRING,
                        "line_count": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 1000,
                        },
                        "encoding": STRING,
                    },
                    ("path",),
                ),
                "read": (
                    {
                        "path": STRING,
                        "start_line": {"type": "integer", "minimum": 1},
                        "line_count": {"type": "integer", "minimum": 1},
                        "encoding": STRING,
                    },
                    ("path",),
                ),
            },
        ),
    ),
    (
        "mc_logs",
        "搜索普通或 gzip 日志，返回文件/行号/事件时间/调用栈上下文。时间为实例本地时间 ISO 格式，无日期的 latest.log 时间未知；后台任务使用 mc_job 续读。",
        contract(
            {
                "query": STRING,
                "pattern": STRING,
                "regex": {"type": "boolean"},
                "case_sensitive": {"type": "boolean"},
                "start_time": STRING,
                "end_time": STRING,
                "before": {"type": "integer", "minimum": 0, "maximum": 50},
                "after": {"type": "integer", "minimum": 0, "maximum": 50},
                "encoding": STRING,
            },
            ("query",),
        ),
    ),
    (
        "mc_console",
        "读取当前托管窗口最近9999行缓冲或发送纯诊断命令。缓冲有会话编号和淘汰提示，更早内容查MC日志。修改实体、强制保存、启停必须先 mc_propose。",
        variants(
            "mode",
            {
                "read": ({**PAGE, "session_id": STRING}, ()),
                "line": (
                    {"session_id": STRING, "seq": INTEGER, "offset": INTEGER},
                    ("session_id", "seq"),
                ),
                "command": (
                    {"command": STRING, "review": REVIEW},
                    ("command", "review"),
                ),
            },
        ),
    ),
    (
        "mc_exec",
        "在线执行诊断 PowerShell，不停服。仅诊断，不能修改生产数据；cwd 为实例内子目录；返回后台任务与输出，超时默认120秒。",
        contract(
            {
                "script": STRING,
                "cwd": STRING,
                "timeout": {"type": "number", "exclusiveMinimum": 0, "maximum": 600},
                "review": REVIEW,
            },
            ("script", "review"),
        ),
    ),
    (
        "mc_nbt",
        "独立NBT读取，select按UUID/方块实体位置/Slot/字段匹配返回实际路径和SNBT；relative_path选中对象内字段。preview_batch预览changes，不写入。实际nbt_batch须提案，各修改expected是带类型旧值，null仅用于确认新字段不存在。删除对象不依赖旧下标。结果可分页。",
        contract(
            {
                "path": STRING,
                "mode": {"enum": ["read", "select", "preview_batch"]},
                "selector": SELECTOR,
                "relative_path": NBT_PATH,
                "changes": CHANGES,
                "nbt_path": NBT_PATH,
                "view": VIEW,
                "offset": INTEGER,
                "limit": {"type": "integer", "minimum": 1, "maximum": 100},
            },
            ("path",),
        ),
    ),
    (
        "mc_region",
        "查询已保存数据，不代表实时现场。read/select读NBT，preview_batch预览；region_batch每项需区块x/z和expected。block按方块坐标读状态／方块实体，blocks按区块统计／检索；block_set须提案并给expected/state完整SNBT，换类型须明确remove_block_entity旧SNBT。check检查区域或指定区块并给fingerprint，export导出原始记录（可从backup）；region_restore/remove须提案并用当前指纹。scan的bounds为方块[minX,minY,minZ,maxX,maxY,maxZ]，实体按三维、区块按水平相交筛选。后台分页用mc_job。",
        variants(
            "mode",
            {
                "read": (REGION_READ, ("path", "x", "z")),
                "block": (
                    {
                        "path": STRING,
                        "block_x": {"type": "integer"},
                        "block_y": {"type": "integer"},
                        "block_z": {"type": "integer"},
                    },
                    ("path", "block_x", "block_y", "block_z"),
                ),
                "blocks": (
                    {
                        "path": STRING,
                        "x": {"type": "integer"},
                        "z": {"type": "integer"},
                        "name": STRING,
                        "legacy_id": {"type": "integer", "minimum": 0, "maximum": 4095},
                        "result": {"enum": ["list", "by_state"]},
                        "offset": INTEGER,
                        "limit": {"type": "integer", "minimum": 1, "maximum": 100},
                    },
                    ("path", "x", "z"),
                ),
                "check": (
                    {
                        "path": STRING,
                        "x": {"type": "integer"},
                        "z": {"type": "integer"},
                        "include_related": {"type": "boolean"},
                    },
                    ("path",),
                ),
                "export": (
                    {
                        "path": STRING,
                        "x": {"type": "integer"},
                        "z": {"type": "integer"},
                        "include_related": {"type": "boolean"},
                        "backup": STRING,
                    },
                    ("path", "x", "z"),
                ),
                "select": (REGION_READ, ("path", "x", "z", "nbt_path", "selector")),
                "preview_batch": (
                    {"path": STRING, "changes": REGION_CHANGES},
                    ("path", "changes"),
                ),
                "scan": (
                    {
                        "world": STRING,
                        "dataset": {
                            "type": "string",
                            "enum": ["entities", "block_entities", "chunks", "poi"],
                        },
                        "entity_type": STRING,
                        "uuid": STRING,
                        "bounds": {
                            "type": "array",
                            "items": {"type": "number"},
                            "minItems": 6,
                            "maxItems": 6,
                        },
                        "conditions": {"type": "array", "items": CONDITION},
                        "result": {
                            "type": "string",
                            "enum": ["list", "by_type", "by_chunk", "top_chunks"],
                        },
                        "top": {"type": "integer", "minimum": 1, "maximum": 100},
                    },
                    (),
                ),
            },
        ),
    ),
    (
        "mc_job",
        "查询后台任务/修复记录。read 用 after 游标续读，artifact 用 reference/offset 读取长字段；cancel 中止任务。",
        variants(
            "mode",
            {
                "read": ({"job_id": STRING, **PAGE}, ("job_id",)),
                "wait": (
                    {
                        "job_id": STRING,
                        **PAGE,
                        "wait_seconds": {"type": "number", "minimum": 0, "maximum": 25},
                    },
                    ("job_id",),
                ),
                "find": (
                    {
                        "job_id": STRING,
                        "reference": STRING,
                        "query": {"type": "string", "minLength": 1},
                        "regex": {"type": "boolean"},
                        "case_sensitive": {"type": "boolean"},
                        "offset": INTEGER,
                        "limit": {"type": "integer", "minimum": 1, "maximum": 100},
                    },
                    ("job_id", "reference", "query"),
                ),
                "artifact": (
                    {"job_id": STRING, "reference": STRING, "offset": INTEGER},
                    ("job_id", "reference"),
                ),
                "cancel": ({"job_id": STRING}, ("job_id",)),
                "repair": ({"operation": STRING, "offset": INTEGER}, ("operation",)),
                "history": (
                    {
                        "entry": {"type": "integer", "minimum": 1},
                        "offset": INTEGER,
                        "after": INTEGER,
                    },
                    (),
                ),
            },
        ),
    ),
    (
        "mc_propose",
        "提出一组运维或故障修复步骤等待管理员确认。文件修改自动停服备份；command 可在线执行，不填 backup_paths 时无恢复备份，summary 必须简短说明。脚本修改仍需声明备份路径。",
        contract(
            {
                "summary": STRING,
                "steps": {"type": "array", "minItems": 1, "items": STEP_SCHEMA},
                "review": REVIEW,
            },
            ("summary", "steps", "review"),
        ),
    ),
    (
        "mc_say",
        "只发送简短提问或关键结论，不发送常规进度。",
        contract({"text": STRING}, ("text",)),
    ),
    (
        "mc_pause",
        "无可行方向且需管理员处理后才能继续时硬暂停，等待 /mcairesume。仅等待玩家补充时用 mc_say 提问并结束本轮，/mcaisay 会自动继续。",
        contract({"reason": {"type": "string", "minLength": 1}}, ("reason",)),
    ),
]

mod_choices = []
for source in ("modrinth", "curseforge"):
    identifiers = (
        {"version_id": STRING}
        if source == "modrinth"
        else {"project_id": STRING, "file_id": {"type": "integer", "minimum": 1}}
    )
    for mode in ("search", "project", "versions", "file", "download"):
        fields = {"source": {"const": source}, "mode": {"const": mode}}
        required = ["source", "mode"]
        if mode == "search":
            fields["query"] = STRING
            required.append("query")
        elif mode in ("project", "versions"):
            fields["project_id"] = STRING
            required.append("project_id")
        else:
            fields.update(identifiers)
            required.extend(identifiers)
        if mode in ("search", "versions"):
            fields.update(
                game_version=STRING,
                loader={"enum": ["forge", "fabric", "quilt", "neoforge"]},
                offset=INTEGER,
            )
        if mode == "download" and source == "modrinth":
            fields["filename"] = STRING
        mod_choices.append(contract(fields, required))
TOOLS.append(
    (
        "mc_mods",
        "通过 Modrinth 或 CurseForge 官方 API 搜索项目、project 查看说明、versions 筛选版本、file 查看文件及依赖、download 暂存明确选定文件。先核实 MC/加载器，不默认最新版，不自动安装可选依赖。CurseForge project_id 用字符串。",
        {
            "type": "object",
            "properties": {
                key: value
                for choice in mod_choices
                for key, value in choice["properties"].items()
                if key not in ("source", "mode")
            }
            | {
                "source": {"enum": ["modrinth", "curseforge"]},
                "mode": {"enum": ["search", "project", "versions", "file", "download"]},
            },
            "required": ["source", "mode"],
            "oneOf": mod_choices,
        },
    )
)


def model_contract(value):
    """The union properties describe all parameters; native validation keeps oneOf."""
    if isinstance(value, dict):
        return {
            key: model_contract(item) for key, item in value.items() if key != "oneOf"
        }
    if isinstance(value, (list, tuple)):
        return [model_contract(item) for item in value]
    return value


MODEL_TOOLS = [
    (name, description, model_contract(schema)) for name, description, schema in TOOLS
]
