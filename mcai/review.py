"""Read exact review inputs on B, and verify the same scripts before execution."""

import hashlib
import json
import re
from pathlib import Path

from .paths import resolve_file


def digest(value):
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def review_material(directory, args):
    directory = Path(directory)
    cwd = (
        resolve_file(directory, args["cwd"])
        if args.get("cwd") not in (None, "", ".")
        else directory
    )
    files = []
    for relative in args.get("script_files", []):
        path = resolve_file(directory, relative)
        data = path.read_bytes()
        files.append(
            {
                "path": path.relative_to(directory).as_posix(),
                "sha256": hashlib.sha256(data).hexdigest(),
                "content": data.decode(args.get("encoding", "utf-8-sig")),
            }
        )
    # Recognize literal script paths, including common quoted launcher arguments.
    # Dynamic paths still need to be explained to the reviewer; this is not a shell parser.
    pattern = r"""["']([^"'\r\n]+\.(?:ps1|bat|cmd|py))["']|(?<![\w])([^\s;|&<>"']+\.(?:ps1|bat|cmd|py))(?=$|[\s;|&])"""
    declared = {resolve_file(directory, item["path"]) for item in files}
    for command in args.get("commands", []):
        for quoted, plain in re.findall(pattern, command, re.I):
            candidate = quoted or plain
            path = resolve_file(directory, cwd / candidate)
            if path not in declared:
                raise ValueError(
                    f"未提供外部脚本审核材料：{candidate}；请填写 review.script_files"
                )
    return {
        "directory": str(directory),
        "cwd": str(cwd),
        "scripts": files,
    }


def verify_scripts(directory, checks):
    for item in checks:
        path = resolve_file(directory, item["path"])
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != item["sha256"]:
            raise ValueError(
                f"审核后脚本已变化，未执行，请重新审阅和提案：{item['path']}"
            )
