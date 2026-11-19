"""Exact text patches retaining the source encoding and line endings."""

import codecs
import difflib
import hashlib
import re

BOMS = (
    (codecs.BOM_UTF32_LE, "utf-32-le"),
    (codecs.BOM_UTF32_BE, "utf-32-be"),
    (codecs.BOM_UTF8, "utf-8"),
    (codecs.BOM_UTF16_LE, "utf-16-le"),
    (codecs.BOM_UTF16_BE, "utf-16-be"),
)


def decode_text(data, encoding=None):
    for marker, codec in BOMS:
        if data.startswith(marker):
            return data[len(marker) :].decode(codec), codec, marker
    codec = codecs.lookup(encoding or "utf-8").name
    return data.decode(codec), codec, b""


def patch_text(path, arguments):
    return patch_data(path.read_bytes(), arguments, path.name)


def patch_data(data, arguments, name):
    actual = hashlib.sha256(data).hexdigest()
    if actual != arguments["sha256"].lower():
        raise ValueError("文件已变化，请重新读取并提案")
    original, codec, marker = decode_text(data, arguments.get("encoding"))
    content = original
    ending = re.search(r"\r\n|\r|\n", original)
    ending = ending.group() if ending else "\n"
    if not arguments["edits"]:
        raise ValueError("补丁不能为空")
    for edit in arguments["edits"]:
        old, new = edit["old"], edit["new"]
        if not old:
            raise ValueError("补丁原文不能为空")
        if old not in content:
            old = re.sub(r"\r\n|\r|\n", lambda _: ending, old)
        if content.count(old) != 1:
            raise ValueError("补丁原文必须唯一匹配，请补充上下文")
        new = re.sub(r"\r\n|\r|\n", lambda _: ending, new)
        content = content.replace(old, new, 1)
    updated = marker + content.encode(codec)
    if arguments.get("format"):
        from .verification import parse_document

        parse_document(updated, arguments["format"], codec)
    return updated, {
        "sha256": actual,
        "result_sha256": hashlib.sha256(updated).hexdigest(),
        "encoding": codec,
        "bom": bool(marker),
        "diff": "".join(
            difflib.unified_diff(
                original.splitlines(keepends=True),
                content.splitlines(keepends=True),
                fromfile=str(name),
                tofile=str(name),
            )
        ),
    }
