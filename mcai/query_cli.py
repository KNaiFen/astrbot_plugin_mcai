"""One argument grammar for model queries and the installed MCAI CLI."""

import argparse
import json

from jsonschema import validate

from .tool_arguments import arguments_for
from .tool_schemas import QUERY_TOOLS

QUERY_COMMANDS = {
    "files": "mc_files",
    "logs": "mc_logs",
    "nbt": "mc_nbt",
    "region-nbt": "mc_region_nbt",
    "region-blocks": "mc_region_blocks",
    "region-check": "mc_region_check",
    "region-export": "mc_region_export",
    "region-scan": "mc_region_scan",
    "diagnostics": "mc_diagnostics",
    "incidents": "mc_incidents",
}
EXAMPLES = {
    "incidents": [
        ["incidents", "list"],
        ["incidents", "console", "--id", "实际故障编号", "--query", "Exception"],
        [
            "incidents",
            "file",
            "--id",
            "实际故障编号",
            "--attachment",
            "详情返回的附件编号",
            "--tail",
        ],
    ],
    "files": [
        ["files", "read", "--path", "server.properties", "--line-count", "30"],
        ["files", "search", "--glob", "config/**/*.toml", "--query", "timeout"],
    ],
    "logs": [["logs", "search", "--query", "Exception", "--glob", "logs/**/*.log*"]],
    "nbt": [
        [
            "nbt",
            "read",
            "--path",
            "level.dat",
            "--nbt-path",
            '["Data"]',
            "--view",
            "children",
        ],
        [
            "nbt",
            "select",
            "--path",
            "playerdata/player.dat",
            "--nbt-path",
            '["Inventory"]',
            "--selector",
            '{"by":"slot","slot":0}',
            "--relative-path",
            '["id"]',
        ],
    ],
    "region-nbt": [
        [
            "region-nbt",
            "read",
            "--path",
            "world/region/r.0.0.mca",
            "--x",
            "0",
            "--z",
            "0",
            "--view",
            "children",
        ]
    ],
    "region-blocks": [
        [
            "region-blocks",
            "read",
            "--path",
            "world/region/r.0.0.mca",
            "--block-x",
            "1",
            "--block-y",
            "64",
            "--block-z",
            "1",
        ]
    ],
    "region-check": [
        [
            "region-check",
            "--path",
            "world/region/r.0.0.mca",
            "--x",
            "0",
            "--z",
            "0",
            "--include-related",
        ]
    ],
    "region-export": [
        ["region-export", "--path", "world/region/r.0.0.mca", "--x", "0", "--z", "0"]
    ],
    "region-scan": [
        [
            "region-scan",
            "--world-path",
            "world",
            "--dataset",
            "entities",
            "--bounds",
            "[0,0,0,31,255,31]",
            "--result",
            "by_type",
        ]
    ],
    "diagnostics": [
        ["diagnostics", "jvm", "--samples", "1"],
        ["diagnostics", "memory-jfr", "--duration-seconds", "25"],
        ["diagnostics", "class-histogram", "--top", "20"],
        ["diagnostics", "hprof-summary", "--path", "dumps/capture.hprof"],
    ],
}
GUIDANCE = {
    "nbt": "nbt-path/relative-path是JSON键或下标数组。selector按uuid、position、slot或match定位对象。"
    '先children看结构，再select定向取值。value/expected使用带类型SNBT，如1b、2L、"文字"；expected=null只表示已核实字段不存在。preview-batch不写入。',
    "region-nbt": "x/z是全局区块坐标。read/select读取磁盘存档；preview-batch只预览changes。实际region_batch须提案。",
    "region-blocks": "read的block-x/y/z是全局方块坐标；search的x/z是全局区块坐标。磁盘数据不代表未保存的服内现场。",
    "region-scan": "bounds为全局方块[minX,minY,minZ,maxX,maxY,maxZ]；先限定必要范围。计数不代表实测耗时。",
    "logs": "默认view=events返回完整多行异常归组、次数、代表栈及罕见组。先据此选择，再用view=value读必要原文；时间按实例本地ISO格式。",
    "diagnostics": "process采集CPU/I/O增量、内存和线程；jvm还采集实际JDK的参数、堆概要和线程快照。"
    "memory-jfr默认25秒（10至60），不查老对象GC Root；class-histogram可能暂停JVM；hprof-summary仅分析已有实例或任务范围内的文件。"
    "在线模式省略pid需唯一Java，采集绑定实例会话和进程创建时间。",
}
GUIDANCE["nbt"] += (
    '\nselector格式：{"by":"uuid","uuid":"实际UUID"}；'
    '{"by":"position","x":1,"y":64,"z":1}；{"by":"slot","slot":0}；'
    '{"by":"match","fields":[{"nbt_path":["id"],"value":"\\"minecraft:stone\\""}]}。'
    "\nchanges是数组，每项op为set/delete；nbt_path指向目标，可带selector/relative_path。"
    "set需要expected和value，delete需要expected。"
    '例如[{"op":"set","nbt_path":["Target","Count"],"expected":"1L","value":"2L"}]。'
)
GUIDANCE["region-nbt"] += (
    "\n" + GUIDANCE["nbt"] + "\npreview-batch的changes每项还需x/z全局区块坐标。"
)
GUIDANCE["region-scan"] += (
    '\nconditions为数组，例如[{"op":"eq","path":["id"],"value":"\\"minecraft:cow\\""}]。'
    "op支持exists/eq/ne/gt/ge/lt/le；exists只需path，其余还需带类型SNBT字符串value。"
)
EXAMPLES["files"].append(
    [
        "files",
        "preview-patch",
        "--path",
        "config/settings.toml",
        "--sha256",
        "a" * 64,
        "--edits",
        '[{"old":"timeout=30","new":"timeout=60"}]',
    ]
)
EXAMPLES["nbt"].append(
    [
        "nbt",
        "preview-batch",
        "--path",
        "test.nbt",
        "--changes",
        '[{"op":"set","nbt_path":["Count"],"expected":"1L","value":"2L"}]',
    ]
)
EXAMPLES["region-nbt"].append(
    [
        "region-nbt",
        "preview-batch",
        "--path",
        "world/region/r.0.0.mca",
        "--changes",
        '[{"op":"set","x":0,"z":0,"nbt_path":["Marker"],"expected":null,"value":"1b"}]',
    ]
)


class QueryHelp(Exception):
    pass


class QueryError(ValueError):
    pass


class QueryParser(argparse.ArgumentParser):
    def __init__(self, *args, **kwargs):
        super().__init__(
            *args, allow_abbrev=False, argument_default=argparse.SUPPRESS, **kwargs
        )

    def print_help(self, file=None):
        raise QueryHelp(self.format_help())

    def error(self, message):
        raise QueryError(
            f"{message}\n{self.format_usage().strip()}；用该子命令 --help 查看参数与示例。"
        )


def parser():
    root = QueryParser(
        prog="mcai query <instance>",
        description="查询当前实例。AI使用mc_query的argv，无需填实例或安装路径。",
        epilog="参数采用独立字符串；路径含空格也只占一个参数。数组/对象参数是JSON字符串。"
        "后台结果沿next_call读取；job_id和operation_id取实际返回值，不重发采集。",
    )
    groups = root.add_subparsers(dest="_command", required=True)
    for command, name in QUERY_COMMANDS.items():
        description, schema = QUERY_TOOLS[name]
        examples = "\n".join(
            "mc_query " + json.dumps({"argv": value}, ensure_ascii=False)
            for value in EXAMPLES[command]
        )
        epilog = (
            GUIDANCE.get(command, "")
            + "\n调用示例（替换实际路径、坐标和编号）：\n"
            + examples
        )
        group = groups.add_parser(
            command,
            description=description,
            help=description.split("。")[0],
            epilog=epilog,
            formatter_class=argparse.RawDescriptionHelpFormatter,
        )
        group.set_defaults(_tool=name)
        modes = schema.get("properties", {}).get("mode", {}).get("enum", [])
        if name == "mc_logs":
            modes = ["search"]
        branches = group.add_subparsers(dest="_mode", required=True) if modes else None
        for mode in modes or [None]:
            target = (
                branches.add_parser(
                    mode.replace("_", "-"),
                    description=description,
                    epilog=epilog,
                    formatter_class=argparse.RawDescriptionHelpFormatter,
                )
                if branches
                else group
            )
            fields = dict(schema.get("properties", {}))
            required = set(schema.get("required", []))
            choices = schema.get("oneOf", [])
            if mode and choices:
                choice = next(
                    item
                    for item in choices
                    if item["properties"]["mode"]["enum"] == [mode]
                )
                fields = {
                    key: value or fields[key]
                    for key, value in choice["properties"].items()
                }
                required = set(choice["required"])
            elif choices:
                for choice in choices:
                    fields.update(choice["properties"])
                required = set.intersection(
                    *(set(choice.get("required", [])) for choice in choices)
                )
            for key, field in fields.items():
                if key == "mode":
                    continue
                options = {
                    "dest": key,
                    "required": key in required,
                    "help": field.get("description", key),
                }
                kind = field.get("type")
                if kind == "boolean":
                    options["action"] = argparse.BooleanOptionalAction
                else:
                    if kind == "integer":
                        options["type"] = int
                    elif kind == "number":
                        options["type"] = float
                    elif (
                        "$ref" in field
                        or kind in ("array", "object")
                        or "anyOf" in field
                    ):
                        options.update(type=json.loads, metavar="JSON")
                    if "enum" in field:
                        options["choices"] = field["enum"]
                target.add_argument("--" + key.replace("_", "-"), **options)
    return root


def parse_query(argv):
    arguments = vars(parser().parse_args(argv))
    name = arguments.pop("_tool")
    arguments.pop("_command")
    mode = arguments.pop("_mode", None)
    if mode is not None and name != "mc_logs":
        arguments["mode"] = mode.replace("-", "_")
    validate(arguments, QUERY_TOOLS[name][1])
    return name, arguments


def query_argv(name, arguments):
    """Render continuation arguments using the same CLI vocabulary."""
    command = next(command for command, tool in QUERY_COMMANDS.items() if tool == name)
    argv = [command]
    if "mode" in arguments:
        argv.append(arguments["mode"].replace("_", "-"))
    elif name == "mc_logs":
        argv.append("search")
    elif name == "mc_nbt":
        argv.append("read")
    for key, value in arguments.items():
        if key == "mode":
            continue
        option = "--" + key.replace("_", "-")
        if isinstance(value, bool):
            argv.append(option if value else "--no-" + key.replace("_", "-"))
        else:
            argv.extend(
                [
                    option,
                    json.dumps(value, ensure_ascii=False)
                    if isinstance(value, (dict, list)) or value is None
                    else str(value),
                ]
            )
    return argv


def query_operation(name, arguments):
    arguments = arguments_for(name, arguments, internal=True)
    action = {
        "mc_files": "files_query",
        "mc_logs": "logs",
        "mc_nbt": "nbt_query",
        "mc_diagnostics": "diagnostics",
        "mc_incidents": "incidents",
        "mc_region_scan": "region_scan",
        "mc_region_export": "region_export",
    }.get(name, "region_query")
    if name == "mc_logs":
        arguments.setdefault("view", "events")
    if action == "region_query":
        mode = arguments.pop("mode", name.removeprefix("mc_region_"))
        if name == "mc_region_blocks":
            mode = {"read": "block", "search": "blocks"}[mode]
        arguments["mode"] = mode
    return action, arguments
