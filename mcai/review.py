"""Read exact review inputs on B, and verify the same scripts before execution."""

import ast
import base64
import difflib
import hashlib
import json
import re
import shlex
import shutil
import subprocess
from collections import Counter, deque
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path

from .paths import resolve_file

REVIEW_VERSION = 5


def digest(value):
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


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
                        word.strip('"')
                        for word in shlex.split(argument.value, posix=False)
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
    commands = []
    for line in source.replace("^\n", "").splitlines():
        line = line.strip().removeprefix("@")
        if not line or line.lower().startswith(("rem ", "::")):
            continue
        words = [word.strip('"') for word in shlex.split(line, posix=False)]
        if words and words[0].lower() == "call":
            words = words[1:]
        commands.append({"words": words, "source": line})
    return commands


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
    declared = dict.fromkeys(
        resolve_file(directory, path) for path in args.get("script_files", [])
    )
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
                if not words or words[0] is None:
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
                    options = [
                        word.lower() if isinstance(word, str) else None
                        for word in words
                    ]
                    for option in ("-file", "-f", "/c", "/k", "-command", "-c"):
                        if option not in options:
                            continue
                        index = options.index(option) + 1
                        argument = words[index] if index < len(words) else None
                        if option in ("-file", "-f"):
                            reference = argument
                        elif argument is not None:
                            if name.startswith("cmd"):
                                if any(word is None for word in words[index:]):
                                    unresolved.append(command["source"])
                                    break
                                argument = subprocess.list2cmdline(words[index:])
                            pending.append(
                                (
                                    argument,
                                    ".bat" if name.startswith("cmd") else ".ps1",
                                    None,
                                    top,
                                    context,
                                    step,
                                )
                            )
                        if argument is None:
                            unresolved.append(command["source"])
                        break
                    if any(
                        option in options
                        for option in ("-encodedcommand", "-enc", "-e")
                    ):
                        unresolved.append(command["source"])
                elif re.fullmatch(r"(?:python(?:\d+(?:\.\d+)*)?|py)(?:\.exe)?", name):
                    for index, word in enumerate(words[1:], 1):
                        if word is None:
                            unresolved.append(command["source"])
                            break
                        if word in ("-c", "-m"):
                            if (
                                word == "-c"
                                and index + 1 < len(words)
                                and words[index + 1] is not None
                            ):
                                pending.append(
                                    (words[index + 1], ".py", None, top, context, step)
                                )
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
                    raise ValueError(
                        f"未提供外部脚本审核材料：{reference}；请填写 script_files"
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
        return item

    script_suffixes = (".ps1", ".bat", ".cmd", ".py")
    text_suffixes = (
        *script_suffixes,
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
            if path.suffix.lower() in script_suffixes:
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
                    if target.suffix.lower() in script_suffixes and "content" in text:
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
