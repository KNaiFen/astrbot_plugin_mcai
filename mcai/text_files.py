"""Exact text patches retaining the source encoding and line endings."""

import codecs
import difflib
import gzip
import hashlib
import io
import json
import re
import tomllib

MAX_PATCH_TEXT_BYTES = 16 * 1024**2
PATCH_SIZE_ERROR = "文本补丁目标超过 16 MiB 上限，请缩小目标文件或改用专用工具"

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


def parse_document(data, format, encoding=None):
    if format == "nbt":
        import nbtlib

        return nbtlib.File.parse(
            io.BytesIO(gzip.decompress(data) if data.startswith(b"\x1f\x8b") else data)
        )
    text, _, _ = decode_text(data, encoding)
    if format == "json":
        return json.loads(text)
    if format == "toml":
        return tomllib.loads(text)
    if format == "yaml":
        import yaml

        try:
            return yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise ValueError(f"YAML 格式无效：{exc}") from exc
    raise ValueError("支持校验的格式为 json/toml/yaml/nbt")


def patch_text(path, arguments):
    if path.stat().st_size > MAX_PATCH_TEXT_BYTES:
        raise ValueError(PATCH_SIZE_ERROR)
    return patch_data(path.read_bytes(), arguments, path.name)


def patch_data(data, arguments, name):
    if len(data) > MAX_PATCH_TEXT_BYTES:
        raise ValueError(PATCH_SIZE_ERROR)
    actual = hashlib.sha256(data).hexdigest()
    if actual != arguments["sha256"].lower():
        raise ValueError("文件已变化，请重新读取并提案")
    original, codec, marker = decode_text(data, arguments.get("encoding"))
    content = original
    if not arguments["edits"]:
        raise ValueError("补丁不能为空")
    for edit in arguments["edits"]:
        old, new = edit["old"], edit["new"]
        if not old:
            raise ValueError("补丁原文不能为空")
        # Match logical lines while retaining the endings of this exact occurrence.
        pattern = re.compile(
            r"(?:\r\n|\r|\n)".join(
                re.escape(part) for part in re.split(r"\r\n|\r|\n", old)
            )
        )
        matches = list(pattern.finditer(content))
        if len(matches) != 1:
            raise ValueError("补丁原文必须唯一匹配，请补充上下文")
        match = matches[0]
        endings = re.findall(r"\r\n|\r|\n", match[0])
        nearby = re.search(r"\r\n|\r|\n", content[match.start() :])
        ending = endings[-1] if endings else nearby[0] if nearby else "\n"
        old_lines = re.split(r"\r\n|\r|\n", match[0])
        new_lines = re.split(r"\r\n|\r|\n", new)
        new_endings = [ending] * (len(new_lines) - 1)
        for operation, start, stop, first, last in difflib.SequenceMatcher(
            a=old_lines, b=new_lines, autojunk=False
        ).get_opcodes():
            if operation in ("equal", "replace"):
                for previous, current in zip(range(start, stop), range(first, last)):
                    if previous < len(endings) and current < len(new_endings):
                        new_endings[current] = endings[previous]
        new = "".join(
            line + (new_endings[index] if index < len(new_endings) else "")
            for index, line in enumerate(new_lines)
        )
        content = content[: match.start()] + new + content[match.end() :]
    updated = marker + content.encode("utf-8" if codec == "utf-8-sig" else codec)
    if arguments.get("format"):
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
