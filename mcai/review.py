"""Read exact review inputs on B, and verify the same scripts before execution."""

import ast
import base64
import difflib
import hashlib
import json
import re
import shutil
import subprocess
from collections import Counter, deque
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path

from .paths import resolve_file

REVIEW_VERSION = 7
REVIEW_FRAME_BYTES = 5 * 1024**2
REVIEW_DIFF_LIMIT = 4 * 1024**2
FULLTEXT_THRESHOLD = 4096
SCRIPT_SUFFIXES = (".ps1", ".bat", ".cmd", ".py")
CONTENT_NOTE = "非脚本文件内容过大，已保留摘要、前后预览、精确 diff 与校验哈希；请优先核对 diff、effective_steps 与字节/哈希校验。"

DESTRUCTIVE_COMMANDS = frozenset(
    {
        "stop-computer",
        "restart-computer",
        "format-volume",
        "clear-disk",
        "initialize-disk",
        "remove-partition",
        "set-partition",
        "reset-physicaldisk",
        "disable-bitlocker",
        "shutdown",
        "shutdown.exe",
        "diskpart",
        "diskpart.exe",
        "format",
        "format.com",
        "bcdedit",
        "bcdedit.exe",
        "vssadmin",
        "vssadmin.exe",
    }
)
DYNAMIC_EXECUTION_COMMANDS = frozenset({"invoke-expression", "iex"})
DIAGNOSTIC_DISALLOWED_COMMANDS = frozenset({"add-type", "invoke-command", "icm"})
# PowerShell ConsoleHost matches these prefixes in order, rather than using
# the cmdlet parameter binder's unique-prefix rule.
POWERSHELL_CLI_OPTIONS = (
    ("configurationname", "config", True),
    ("configurationfile", "configurationf", True),
    ("commandwithargs", "commandwithargs", True),
    ("commandwithargs", "cwa", True),
    ("command", "c", True),
    ("file", "f", True),
    ("executionpolicy", "ex", True),
    ("executionpolicy", "ep", True),
    ("encodedcommand", "e", True),
    ("encodedcommand", "ec", True),
    ("encodedarguments", "encodeda", True),
    ("encodedarguments", "ea", True),
    ("inputformat", "inp", True),
    ("inputformat", "if", True),
    ("outputformat", "o", True),
    ("outputformat", "of", True),
    ("windowstyle", "w", True),
    ("workingdirectory", "wo", True),
    ("workingdirectory", "wd", True),
    ("settingsfile", "settings", True),
    ("custompipename", "cus", True),
    ("noprofileloadtime", "noprofileloadtime", False),
    ("noprofile", "nop", False),
    ("nologo", "nol", False),
    ("noexit", "noe", False),
    ("noninteractive", "noni", False),
    ("interactive", "i", False),
    ("sta", "sta", False),
    ("mta", "mta", False),
)
CONSOLE_DISALLOWED_COMMANDS = frozenset(
    {
        "stop",
        "restart",
        "end",
        "reload",
        "op",
        "deop",
        "ban",
        "ban-ip",
        "pardon",
        "pardon-ip",
        "kick",
        "whitelist",
        "save-all",
        "save-off",
        "save-on",
        "setblock",
        "fill",
        "clone",
        "kill",
        "summon",
        "give",
        "clear",
        "tp",
        "teleport",
        "spreadplayers",
        "weather",
        "setworldspawn",
        "spawnpoint",
        "defaultgamemode",
        "gamemode",
        "difficulty",
        "advancement",
        "recipe",
        "effect",
        "enchant",
        "experience",
        "xp",
        "loot",
        "place",
        "schedule",
        "function",
        "bossbar",
        "team",
    }
)
CONSOLE_READONLY_SUBCOMMANDS = {
    "forceload": frozenset({"query"}),
    "data": frozenset({"get"}),
    "time": frozenset({"query"}),
    "tick": frozenset({"query"}),
    "datapack": frozenset({"list"}),
    "worldborder": frozenset({"get"}),
}
TEST_READONLY_CONSOLE_COMMAND = re.compile(
    r"/?(?:list|tps|(?:forge|neoforge) tps|tick query|datapack list|"
    r"scoreboard objectives list|time query (?:daytime|gametime|day)|"
    r"forceload query(?: -?\d+ -?\d+)?|"
    r"scoreboard players (?:list(?: [A-Za-z0-9_.#+-]{1,64})?|"
    r"get [A-Za-z0-9_.#+-]{1,64} [A-Za-z0-9_.#+-]{1,64})|"
    r"data get (?:block -?\d+ -?\d+ -?\d+|"
    r"entity (?:[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}|[A-Za-z0-9_]{1,16}))"
    r"(?: [A-Za-z0-9_.]{1,128})?)",
    re.IGNORECASE | re.ASCII,
)


def shell_invocation(words):
    """Return a literal shell entry point, or mark an indeterminate invocation."""
    name = words[0].replace("\\", "/").split("/")[-1].lower()
    if name in ("cmd", "cmd.exe"):
        for index, word in enumerate(words[1:], 1):
            if word is None:
                return "unresolved", None
            if word.lower() in ("/c", "/k"):
                arguments = words[index + 1 :]
                if not arguments or any(word is None for word in arguments):
                    return "unresolved", None
                return ".bat", (
                    arguments[0]
                    if len(arguments) == 1
                    else subprocess.list2cmdline(arguments)
                )
        return "unresolved", None
    index = 1
    while index < len(words):
        word = words[index]
        if word is None:
            return "unresolved", None
        if not word.startswith(("-", "/", "–", "—", "―")):
            return "file", word
        key = word.lstrip("-/–—―").lower()
        option = next(
            (
                (full, takes_value)
                for full, minimum, takes_value in POWERSHELL_CLI_OPTIONS
                if (full.startswith(key) and key.startswith(minimum)) or key == minimum
            ),
            None,
        )
        if option is None:
            return "unresolved", None
        full, takes_value = option
        index += 1
        if full == "encodedcommand":
            return "encoded", None
        if full in ("command", "commandwithargs", "file"):
            arguments = words[index:]
            if not arguments or arguments[0] in (None, "-"):
                return "unresolved", None
            if full == "file":
                return "file", arguments[0]
            if any(word is None for word in arguments):
                return "unresolved", None
            return ".ps1", (
                arguments[0] if full == "commandwithargs" else " ".join(arguments)
            )
        if takes_value:
            if index >= len(words) or words[index] is None:
                return "unresolved", None
            index += 1
    return "unresolved", None


def validate_script_command(words, source, *, diagnostic=False):
    if not words or not words[0]:
        return
    if words[0] == "__unsafe_ast__":
        raise ValueError(f"脚本包含禁止使用的动态执行语法：{source}")
    name = words[0].replace("\\", "/").split("/")[-1].lower()
    if name in DESTRUCTIVE_COMMANDS:
        raise ValueError(f"脚本包含禁止使用的宿主机或磁盘破坏命令：{name}")
    if name in DYNAMIC_EXECUTION_COMMANDS:
        raise ValueError(f"脚本包含禁止使用的动态执行命令：{name}")
    if diagnostic and name in DIAGNOSTIC_DISALLOWED_COMMANDS:
        raise ValueError(f"在线诊断脚本不允许调用高危命令：{name}")
    if name in ("pwsh", "pwsh.exe", "powershell", "powershell.exe"):
        if shell_invocation(words)[0] == "encoded":
            raise ValueError("脚本禁止使用混淆编码参数 -EncodedCommand")


def validate_diagnostic_script(source, powershell_path):
    with powershell_parser(powershell_path) as parse:
        pending = deque([(source, "powershell")])
        seen = set()
        while pending:
            text, language = pending.popleft()
            if (text, language) in seen:
                continue
            seen.add((text, language))
            for command in script_commands(text, language, parse, None):
                words = command["words"]
                validate_script_command(words, command["source"], diagnostic=True)
                if not words or not words[0]:
                    continue
                name = Path(words[0]).name.lower()
                if name in (
                    "pwsh",
                    "pwsh.exe",
                    "powershell",
                    "powershell.exe",
                    "cmd",
                    "cmd.exe",
                ):
                    kind, argument = shell_invocation(words)
                    if kind in (".ps1", ".bat"):
                        pending.append(
                            (argument, "bat" if kind == ".bat" else "powershell")
                        )


def _check_console_command_tokens(tokens, raw):
    if not tokens:
        return
    head = tokens[0].lstrip("/").split(":")[-1].lower()
    if head in CONSOLE_DISALLOWED_COMMANDS:
        raise ValueError(
            f"mc_console_send 仅用于在线诊断，不允许执行管理或修改命令（{head}）；请改用 mc_propose 提交方案并等待管理员批准。"
        )
    if head in CONSOLE_READONLY_SUBCOMMANDS:
        sub = tokens[1].lower() if len(tokens) > 1 else ""
        if sub not in CONSOLE_READONLY_SUBCOMMANDS[head]:
            raise ValueError(
                f"mc_console_send 对 {head} 仅开放只读查询，不允许修改操作（{raw.strip()}）；请改用 mc_propose。"
            )
    if head == "gamerule" and len(tokens) > 2:
        raise ValueError(
            "mc_console_send 仅允许查询 gamerule，修改游戏规则请改用 mc_propose。"
        )
    if head == "banlist" and len(tokens) > 1 and tokens[1].lower() == "ips":
        raise ValueError("在线诊断不允许通过 banlist ips 查询玩家 IP。")
    if head == "execute":
        index = 1
        while index < len(tokens):
            token = tokens[index].lower()
            if (
                token in ("if", "unless")
                and index + 4 < len(tokens)
                and tokens[index + 1].lower() == "score"
            ):
                # Targets and objective names may themselves be run/store/if.
                index += 6 if tokens[index + 4].lower() == "matches" else 7
                continue
            if (
                token == "store"
                and index + 1 < len(tokens)
                and tokens[index + 1].lower() in ("result", "success")
            ):
                raise ValueError(
                    "mc_console_send 不允许 execute store 写入；请改用 mc_propose。"
                )
            if token == "run" and index + 1 < len(tokens):
                _check_console_command_tokens(tokens[index + 1 :], raw)
            index += 1


def validate_diagnostic_console_commands(commands):
    for command in commands:
        if not isinstance(command, str) or not command.strip():
            continue
        _check_console_command_tokens(command.strip().split(), command)


def is_test_readonly_console_commands(commands) -> bool:
    return (
        isinstance(commands, (list, tuple))
        and bool(commands)
        and all(
            isinstance(command, str)
            and TEST_READONLY_CONSOLE_COMMAND.fullmatch(command)
            and not {"execute", "function"}.intersection(command.lower().split(" "))
            for command in commands
        )
    )


def digest(value):
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def non_script_files(material):
    scripts = {row["path"].casefold() for row in material.get("scripts", [])}
    for index, row in enumerate(material.get("files", [])):
        path = row["path"]
        if (
            Path(path).suffix.lower() not in SCRIPT_SUFFIXES
            and path.casefold() not in scripts
        ):
            yield index, row


def review_file_previews(material, preview=800):
    for index, row in non_script_files(material):
        projected = dict(row)
        for field in ("old_content", "content"):
            key = f"{field}_preview"
            if (
                isinstance(text := row.get(field), str)
                and len(text) > FULLTEXT_THRESHOLD
            ):
                projected.pop(field)
                projected[key] = {"head": text[:preview], "tail": text[-preview:]}
                projected.update(omitted_fulltext=True, content_note=CONTENT_NOTE)
            elif key in row:
                projected[key] = {
                    "head": row[key]["head"][:preview],
                    "tail": row[key]["tail"][-preview:],
                }
        if projected != row:
            yield index, projected


def bound_review_material(material):
    from .evidence import json_size

    size = json_size(material)
    if size <= REVIEW_FRAME_BYTES:
        return material
    files = list(material["files"])
    replacements = sorted(
        (
            (json_size(files[i]) - json_size(row), i, row)
            for i, row in review_file_previews(material)
        ),
        key=lambda edit: (-edit[0], edit[1]),
    )
    for saved, i, row in replacements:
        files[i] = row
        size -= saved
        if size <= REVIEW_FRAME_BYTES:
            return {**material, "files": files}

    for i, row in non_script_files({**material, "files": files}):
        if "diff" in row and json_size(diff := row["diff"]) >= REVIEW_DIFF_LIMIT:
            limited = {key: value for key, value in row.items() if key != "diff"}
            limited.update(
                diff_preview={"head": diff[:800], "tail": diff[-800:]},
                diff_truncated=True,
                diff_sha256=hashlib.sha256(diff.encode("utf-8")).hexdigest(),
                diff_note="完整 diff 超过通信预算，此处仅保留头尾，不能作为精确差异。",
            )
            files[i] = limited
            size -= json_size(row) - json_size(limited)
            if size <= REVIEW_FRAME_BYTES:
                return {**material, "files": files}
    raise ValueError(
        "审核材料超过 5 MiB 通信预算，完整步骤、脚本和精确差异已保留，请缩小本批操作范围。"
    )


@contextmanager
def powershell_parser(executable):
    process = None
    reader = ThreadPoolExecutor(max_workers=1)

    def parse(source, script_root):
        nonlocal process
        if process is None:
            if not executable:
                raise ValueError("审核脚本需要已验证的PowerShell 7")
            parser_source = (
                Path(__file__)
                .with_name("review_parser.ps1")
                .read_text(encoding="utf-8-sig")
            )
            process = subprocess.Popen(
                [
                    executable,
                    "-NoLogo",
                    "-NoProfile",
                    "-NonInteractive",
                    "-EncodedCommand",
                    base64.b64encode(parser_source.encode("utf-16-le")).decode("ascii"),
                ],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                encoding="utf-8",
            )
        process.stdin.write(
            json.dumps(
                {
                    "source": source,
                    "script_root": str(script_root)
                    if script_root is not None
                    else None,
                },
                ensure_ascii=False,
            )
            + "\n"
        )
        process.stdin.flush()
        line = reader.submit(process.stdout.readline).result(timeout=30)
        if not line:
            raise ValueError("PowerShell审核解析失败：" + process.stderr.read())
        result = json.loads(line)
        if result["errors"]:
            raise ValueError("PowerShell脚本语法错误：" + "；".join(result["errors"]))
        return result["commands"]

    try:
        yield parse
    finally:
        if process is not None:
            if process.poll() is None:
                process.kill()
            process.wait()
            process.stdin.close()
            process.stdout.close()
            process.stderr.close()
        reader.shutdown()


def cmd_commands(source, *, split_commands=True):
    """Tokenize literal CMD commands; apostrophes and backslashes are ordinary."""
    commands = []
    for line in re.sub(r"\^\r?\n", "", source).splitlines():
        line = line.strip().removeprefix("@")
        if not line or line.lower().startswith(("rem ", "::")):
            continue
        words, word = [], []
        quoted, started, start, index = False, False, 0, 0
        while index <= len(line):
            char = line[index] if index < len(line) else None
            if char == "^" and not quoted and index + 1 < len(line):
                index += 1
                word.append(line[index])
                started = True
            elif char == '"':
                quoted = not quoted
                started = True
            elif char is None or (
                not quoted and (char.isspace() or split_commands and char in "&|")
            ):
                if started:
                    words.append("".join(word))
                    word, started = [], False
                if char is None or split_commands and char in "&|":
                    if words:
                        words[0] = words[0].removeprefix("@")
                        if words[0].lower() == "call":
                            words = words[1:]
                        commands.append(
                            {"words": words, "source": line[start:index].strip()}
                        )
                    words, start = [], index + 1
            else:
                word.append(char)
                started = True
            index += 1
    return commands


def script_commands(source, language, parse, root):
    if language == "powershell":
        return parse(source, root)
    if language == "python":
        commands = []
        for node in ast.walk(ast.parse(source)):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            name = ast.unparse(node.func)
            argument = node.args[0]
            if name in (
                "subprocess.run",
                "subprocess.Popen",
                "subprocess.call",
                "subprocess.check_call",
                "subprocess.check_output",
            ):
                words = (
                    [
                        item.value
                        if isinstance(item, ast.Constant)
                        and isinstance(item.value, str)
                        else None
                        for item in argument.elts
                    ]
                    if isinstance(argument, (ast.List, ast.Tuple))
                    else [
                        word
                        for command in cmd_commands(
                            argument.value, split_commands=False
                        )
                        for word in command["words"]
                    ]
                    if isinstance(argument, ast.Constant)
                    and isinstance(argument.value, str)
                    else [None]
                )
            elif name == "runpy.run_path":
                words = [
                    argument.value
                    if isinstance(argument, ast.Constant)
                    and isinstance(argument.value, str)
                    else None
                ]
            elif name == "os.system":
                words = [
                    "cmd",
                    "/c",
                    argument.value
                    if isinstance(argument, ast.Constant)
                    and isinstance(argument.value, str)
                    else None,
                ]
            else:
                continue
            commands.append(
                {"words": words, "source": ast.get_source_segment(source, node)}
            )
        return commands
    return cmd_commands(source)


def review_material(
    directory, args, *, steps=(), restorations=None, restore_checks=None
):
    from .configuration import bat_codepage
    from .text_files import decode_text

    directory = Path(directory)
    cwd = (
        resolve_file(directory, args["cwd"])
        if args.get("cwd") not in (None, "", ".")
        else directory
    )
    byte_cache = {}
    hash_cache = {}

    def read_bytes(path):
        path = Path(path)
        if path not in byte_cache:
            byte_cache[path] = path.read_bytes()
        return byte_cache[path]

    def fingerprint(data):
        if data not in hash_cache:
            hash_cache[data] = hashlib.sha256(data).hexdigest()
        return hash_cache[data]

    file_info, planned, contexts, final_view = file_material(
        directory,
        steps,
        restorations or {},
        restore_checks or {},
        read_bytes,
        fingerprint,
        args.get("encoding", "utf-8-sig"),
        args.get("launcher_encoding", "auto"),
    )
    declared = {}
    for raw in args.get("script_files", []):
        declared.setdefault(resolve_file(directory, raw), raw)
    planned_paths = {path for path, _ in planned}
    files, unresolved, loaded, parsed, recorded, commands_cache = (
        [],
        [],
        set(),
        set(),
        {},
        {},
    )
    pending = deque()

    def record_script(
        path, data, planned_version, source_path, *, step=None, launcher=False
    ):
        identity = (path, data, planned_version)
        if identity in recorded:
            item = recorded[identity]
        else:
            item = {"path": path.relative_to(directory).as_posix()}
            try:
                if planned_version and (path, data) in planned:
                    item["content"] = planned[path, data]
                else:
                    encoding = args.get("encoding", "utf-8-sig")
                    if path.suffix.lower() in (".bat", ".cmd"):
                        page = bat_codepage(
                            source_path, args.get("launcher_encoding", "auto"), data
                        )
                        encoding = "utf-8-sig" if page == 65001 else f"cp{page}"
                    item["content"] = decode_text(data, encoding)[0]
            except UnicodeDecodeError as exc:
                item["encoding_error"] = str(exc)
            files.append(item)
            recorded[identity] = item
        if step is not None:
            item["sha256"] = fingerprint(data)
            if step not in item.setdefault("steps", []):
                item["steps"].append(step)
        if planned_version:
            item["planned"] = True
        if launcher:
            item["launcher"] = True
        return item.get("content")

    def read_script(path, *, context=None, step=None, launcher=False):
        identity = (path, id(context))
        if identity in loaded:
            return
        loaded.add(identity)
        if context is None:
            if path.exists():
                record_script(path, read_bytes(path), False, path, launcher=launcher)
            elif (
                not any(view(path)[0] is not None for _, _, view, _ in contexts)
                and final_view(path)[0] is None
            ):
                if path in declared:
                    raw = declared[path]
                    if cwd != directory:
                        try:
                            candidate = resolve_file(cwd, raw)
                        except ValueError:
                            candidate = None
                        if candidate is not None and (
                            candidate.exists()
                            or final_view(candidate)[0] is not None
                            or any(
                                view(candidate)[0] is not None
                                for _, _, view, _ in contexts
                            )
                        ):
                            relative = candidate.relative_to(directory).as_posix()
                            raise FileNotFoundError(
                                f"script_files 按实例根目录解析，不随 cwd 变化；{raw} 在实例根目录不存在，请改填 {relative}，勿用原参数重试。"
                            )
                    raise FileNotFoundError(
                        f"script_files 按实例根目录解析（不随 cwd 变化），文件不存在：{raw}；请核对实例内路径并修改参数后再调用，不要原样重发。"
                    )
                raise FileNotFoundError(str(path))
            return
        data, source_path, planned_version, expected = context(path)
        if data is None:
            raise FileNotFoundError(f"该步骤执行时脚本不存在：{path}")
        if expected is not None and fingerprint(data) != expected:
            raise ValueError(f"备份脚本与记录指纹不一致：{path}")
        content = record_script(
            path, data, planned_version, source_path, step=step, launcher=launcher
        )
        if content is None:
            raise ValueError(f"执行脚本解码失败，请填写script_encoding：{path}")
        pending.append(
            (content, path.suffix.lower(), path.parent, False, context, step)
        )

    if not steps:
        contexts = [
            ("inline", command, final_view, 0) for command in args.get("commands", [])
        ]
    for path in declared:
        read_script(path)
    for kind, value, context, step in contexts:
        if kind == "file":
            path = resolve_file(directory, value)
            read_script(path, context=context, step=step, launcher=True)
        else:
            pending.append((value, ".ps1", None, True, context, step))
    with powershell_parser(
        args.get("powershell_path") or shutil.which("pwsh.exe")
    ) as parse:
        while pending:
            source, suffix, root, top, context, step = pending.popleft()
            identity = (source, suffix, str(root), top, id(context))
            if identity in parsed:
                continue
            parsed.add(identity)
            unresolved_before = len(unresolved)
            language = (
                "python"
                if suffix == ".py"
                else "bat"
                if suffix in (".bat", ".cmd")
                else "powershell"
            )
            cache_key = (source, language, str(root))
            if cache_key not in commands_cache:
                commands_cache[cache_key] = script_commands(
                    source, language, parse, root
                )
            for command in commands_cache[cache_key]:
                words = command["words"]
                validate_script_command(
                    words,
                    command["source"],
                    diagnostic=bool(args.get("diagnostic")),
                )
                if not words or not words[0]:
                    unresolved.append(command["source"])
                    continue
                name = Path(words[0]).name.lower()
                if name in (
                    "set-location",
                    "cd",
                    "chdir",
                    "push-location",
                    "pushd",
                    "pop-location",
                    "popd",
                ):
                    unresolved.append(
                        "工作目录变化，后续相对脚本需结合原文核实：" + command["source"]
                    )
                reference = (
                    words[0]
                    if Path(name).suffix in (".ps1", ".bat", ".cmd", ".py")
                    else None
                )
                if name in (
                    "pwsh",
                    "pwsh.exe",
                    "powershell",
                    "powershell.exe",
                    "cmd",
                    "cmd.exe",
                ):
                    kind, argument = shell_invocation(words)
                    if kind == "file":
                        reference = argument
                    elif kind in (".ps1", ".bat"):
                        pending.append((argument, kind, None, top, context, step))
                    else:
                        unresolved.append(command["source"])
                elif re.fullmatch(r"(?:python(?:\d+(?:\.\d+)*)?|py)(?:\.exe)?", name):
                    options = iter(words[1:])
                    for word in options:
                        if word is None:
                            unresolved.append(command["source"])
                            break
                        if word in ("-X", "-W", "-Q", "--check-hash-based-pycs"):
                            if next(options, "") is None:
                                unresolved.append(command["source"])
                                break
                            continue
                        if word == "--":
                            script = next(options, "-")
                            if script is None:
                                unresolved.append(command["source"])
                            elif script != "-":
                                reference = script
                            break
                        if word == "-c":
                            source_arg = next(options, None)
                            if source_arg is not None:
                                pending.append(
                                    (source_arg, ".py", None, top, context, step)
                                )
                            break
                        if word in ("-m", "-"):
                            break
                        if not word.startswith("-"):
                            reference = word
                            break
                if reference is None:
                    continue
                if root is not None:
                    reference = re.sub(
                        r"%~dp0", lambda _: str(root) + "/", reference, flags=re.I
                    )
                if any(character in reference for character in ("*", "?", "$", "%")):
                    unresolved.append(command["source"])
                    continue
                path = resolve_file(directory, cwd / reference)
                if (
                    top
                    and path not in declared
                    and path not in planned_paths
                    and not context(path)[2]
                ):
                    expected = path.relative_to(directory).as_posix()
                    raise ValueError(
                        f"未提供外部脚本审核材料：{reference}；请填写 script_files（实例根目录相对路径：{expected}，不随 cwd 变化）"
                    )
                try:
                    read_script(path, context=context, step=step)
                except FileNotFoundError:
                    if top:
                        raise
                    unresolved.append("未读取外部脚本（不存在）：" + str(path))
            if len(unresolved) != unresolved_before:
                for path in declared:
                    read_script(path, context=context, step=step)
    return {
        "directory": str(directory),
        "cwd": str(cwd),
        "scripts": files,
        "files": file_info,
        "unresolved_references": list(dict.fromkeys(unresolved)),
    }


def file_material(
    directory,
    steps,
    restorations,
    restore_checks,
    read_bytes,
    fingerprint,
    script_encoding="utf-8-sig",
    launcher_encoding="auto",
):
    from .configuration import bat_codepage
    from .text_files import decode_text, patch_data

    directory = Path(directory)
    files, planned, contexts, contents, restored = [], {}, [], {}, []

    def view():
        memory, roots = dict(contents), list(restored)

        def read_version(path):
            if path in memory:
                return memory[path], path, True, None
            for target, source, info in reversed(roots):
                if path == target or path.is_relative_to(target):
                    if not info["existed"]:
                        return None, path, True, None
                    relative = (
                        path.relative_to(target).as_posix()
                        if info["directory"]
                        else "."
                    )
                    source_path = source / relative if info["directory"] else source
                    data = read_bytes(source_path) if source_path.exists() else None
                    expected = info["hashes"].get(relative)
                    if data is not None and expected is None:
                        raise ValueError(f"备份目录内容与记录指纹不一致：{path}")
                    return data, source_path, True, expected
            return (read_bytes(path) if path.exists() else None), path, False, None

        return read_version

    def describe(path, data, encoding=None):
        item = {
            "path": path.relative_to(directory).as_posix(),
            "existed": data is not None,
        }
        if data is not None:
            item["bytes"] = len(data)
            try:
                item["content"] = decode_text(data, encoding)[0]
            except UnicodeDecodeError as exc:
                item["encoding_error"] = str(exc)
            else:
                if (
                    len(item["content"]) > FULLTEXT_THRESHOLD
                    and path.suffix.lower() not in SCRIPT_SUFFIXES
                ):
                    item["content_sha256"] = fingerprint(data)
        return item

    text_suffixes = (
        *SCRIPT_SUFFIXES,
        ".txt",
        ".json",
        ".toml",
        ".yaml",
        ".yml",
        ".properties",
        ".cfg",
        ".conf",
        ".ini",
    )
    for index, step in enumerate(steps):
        kind = step["action"]
        if kind in ("write_text", "patch_text"):
            path = resolve_file(directory, step["path"])
            old = view()(path)[0]
            item = describe(path, old, step.get("encoding"))
            item["step"] = index
            if kind == "write_text":
                updated = step["content"].encode(step.get("encoding", "utf-8"))
            else:
                if old is None:
                    raise ValueError(f"补丁文件不存在：{step['path']}")
                updated, preview = patch_data(old, step, path.name)
                item["diff"] = preview["diff"]
            content = decode_text(updated, step.get("encoding"))[0]
            if "content" in item and "diff" not in item:
                item["diff"] = "".join(
                    difflib.unified_diff(
                        item["content"].splitlines(keepends=True),
                        content.splitlines(keepends=True),
                        fromfile=step["path"],
                        tofile=step["path"],
                    )
                )
            files.append(item)
            contents[path] = updated
            if path.suffix.lower() in SCRIPT_SUFFIXES:
                planned[path, updated] = content
        elif kind == "restore":
            source, manifest = restorations[step["backup"]]
            for relative, info in manifest["files"].items():
                path = resolve_file(directory, relative)
                checked = restore_checks[step["backup"]][relative]
                item = {
                    "path": relative,
                    "backup": step["backup"],
                    "step": index,
                    **{key: value for key, value in checked.items() if key != "hashes"},
                }
                files.append(item)
                members = checked.get("hashes", {})
                item["file_count"] = len(members)
                if info["existed"] and info["directory"]:
                    item["structure"] = {
                        "file_types": dict(
                            sorted(
                                Counter(
                                    Path(name).suffix.lower() or "(无扩展名)"
                                    for name in members
                                ).items()
                            )
                        ),
                        "top_level_directories": sorted(
                            {
                                Path(name).parts[0]
                                for name in members
                                if len(Path(name).parts) > 1
                            }
                        ),
                        "directory_count": len(
                            {
                                parent
                                for name in members
                                for parent in Path(name).parents
                                if parent != Path(".")
                            }
                        ),
                    }
                for member, expected in members.items():
                    target = path / member if info["directory"] else path
                    if target.suffix.lower() not in text_suffixes:
                        continue
                    text = (
                        item
                        if not info["directory"]
                        else {
                            "path": target.relative_to(directory).as_posix(),
                            "backup": step["backup"],
                            "step": index,
                        }
                    )
                    origin = source / "files" / relative
                    if info["directory"]:
                        origin /= member
                    data = read_bytes(origin)
                    encoding = (
                        script_encoding
                        if target.suffix.lower() in (".ps1", ".py")
                        else None
                    )
                    if target.suffix.lower() in (".bat", ".cmd"):
                        page = bat_codepage(origin, launcher_encoding, data)
                        encoding = "utf-8-sig" if page == 65001 else f"cp{page}"
                    text.update(describe(target, data, encoding))
                    if fingerprint(data) != expected:
                        raise ValueError(f"备份内容与记录指纹不一致：{text['path']}")
                    text["content_source"] = (
                        "备份中将恢复的旧内容，不是生成备份时的新方案"
                    )
                    current = describe(target, view()(target)[0], encoding)
                    if "content" in text and (
                        "content" in current or not current["existed"]
                    ):
                        text["diff"] = "".join(
                            difflib.unified_diff(
                                current.get("content", "").splitlines(keepends=True),
                                text["content"].splitlines(keepends=True),
                                fromfile=text["path"],
                                tofile=text["path"] + " (备份)",
                            )
                        )
                    text["current"] = {
                        key: value for key, value in current.items() if key != "content"
                    }
                    if info["directory"]:
                        files.append(text)
                    if target.suffix.lower() in SCRIPT_SUFFIXES and "content" in text:
                        planned[target, data] = text["content"]
                for cached in list(contents):
                    if cached == path or cached.is_relative_to(path):
                        del contents[cached]
                restored.append((path, source / "files" / relative, checked))
        elif kind in ("start", "restart"):
            contexts.append(("file", "start.bat", view(), index))
        elif kind == "script":
            contexts.append(("inline", step["script"], view(), index))
    return files, planned, contexts, view()


def verify_scripts(directory, checks, *, step=None, initial=False):
    for item in checks:
        if initial and item.get("planned"):
            continue
        if step is not None and "steps" in item and step not in item["steps"]:
            continue
        path = resolve_file(directory, item["path"])
        actual = (
            hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None
        )
        if actual != item["sha256"]:
            raise ValueError(
                f"审核后脚本已变化，未执行，请重新审阅和提案：{item['path']}"
            )
