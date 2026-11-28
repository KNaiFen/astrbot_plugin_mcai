import asyncio
import codecs
import hashlib
import heapq
import json
import os
import re
import shutil
import subprocess
import sys
from contextlib import ExitStack, asynccontextmanager
from copy import copy
from fnmatch import fnmatchcase
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import quote
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

import psutil

from .paths import resolve_file
from .review import digest, verify_scripts
from .workspace_jar import (
    JAR_BYTES,
    JAR_ENTRIES,
    MIB,
    NESTED_BYTES,
    SIGNATURE,
    binary_entry,
    checked_entries,
    class_names,
    clean_manifest,
    entry_name,
    find_entry,
    is_text,
    open_jar,
    open_nested,
    search_jar,
)
from .workspace_tools import (
    WorkspaceTools,
    classpath,
    jdk_executables,
    run_java_tool,
    sha256,
)

JAR_TEXT_NAMES = {
    "manifest.mf",
    "plugin.yml",
    "paper-plugin.yml",
    "fabric.mod.json",
    "quilt.mod.json",
    "mods.toml",
    "neoforge.mods.toml",
    "accesstransformer.cfg",
    "mcmod.info",
    "pack.mcmeta",
}


def jar_limit(args, default=50):
    limit = args.get("limit", default)
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("JAR 检查条数 limit 必须为 1 至 100")
    return limit


def javap_methods(text, query):
    result = []
    separator = (
        r"(?m)(?=^Classfile )"
        if re.search(r"(?m)^Classfile ", text)
        else r"(?m)(?<=^\})\n"
    )
    for block in re.split(separator, text):
        lines = block.splitlines(keepends=True)
        opening = next(
            (
                i
                for i, line in enumerate(lines)
                if not line.startswith(" ") and line.rstrip().endswith("{")
            ),
            None,
        )
        if opening is None:
            continue
        pool = next(
            (i for i in range(opening) if lines[i].startswith("Constant pool:")),
            opening,
        )
        result.extend(lines[:pool])
        result.append(lines[opening])
        closing = next(
            (i for i in range(opening + 1, len(lines)) if lines[i].rstrip() == "}"),
            len(lines),
        )
        starts = [
            i
            for i in range(opening + 1, closing)
            if re.match(r"^  \S.*;\s*$", lines[i])
        ]
        for start, end in zip(starts, [*starts[1:], closing]):
            name = re.search(r"([^\s(]+)\(", lines[start])
            if name and query in name[1].rsplit(".", 1)[-1]:
                result.extend(lines[start:end])
        result.append("}\n")
    return "".join(result)


class Workspace:
    def __init__(self, root, powershell_path, process_job, *, store_dir=None):
        self.root = Path(root).resolve()
        self.powershell_path = powershell_path
        self.process_job = process_job
        self.tools = WorkspaceTools(
            (Path(store_dir) if store_dir is not None else self.root.parent)
            / "tools/workspace",
            process_job,
        )

    def directory(self, task_id):
        return self.root / task_id

    def path(self, task_id, relative="."):
        directory = self.directory(task_id)
        if directory.parent != self.root or directory.resolve() != directory:
            raise ValueError("文件路径必须位于当前任务工作区内")
        if relative == ".":
            return directory
        return resolve_file(directory, relative)

    def list(self, task_id, args):
        self.directory(task_id).mkdir(parents=True, exist_ok=True)
        directory = self.path(task_id, args.get("path", "."))
        if not directory.is_dir():
            raise ValueError("工作区路径不是目录")
        after = args.get("after", "")
        page = heapq.nsmallest(
            201,
            (item for item in directory.iterdir() if item.name > after),
            key=lambda item: item.name,
        )
        return {
            "path": str(directory),
            "items": [
                {
                    "name": item.name,
                    "directory": item.is_dir(),
                    "bytes": item.stat().st_size if item.is_file() else None,
                }
                for item in page[:200]
            ],
            "next_cursor": page[199].name if len(page) > 200 else None,
        }

    def read(self, task_id, args):
        self.directory(task_id).mkdir(parents=True, exist_ok=True)
        path = self.path(task_id, args["path"])
        encoding = args.get("encoding", "utf-8")
        offset = args.get("offset", 0)
        with path.open(encoding=encoding) as stream:
            info = os.fstat(stream.fileno())
            revision = digest(
                [str(path), encoding, info.st_ino, info.st_size, info.st_mtime_ns]
            )
            if "cursor" in args:
                if "offset" in args:
                    raise ValueError("cursor 和 offset 只能指定一个")
                stamp, separator, position = args["cursor"].partition(":")
                if (
                    not separator
                    or stamp != revision
                    or len(position) > 64
                    or not position.isascii()
                    or not position.isdecimal()
                ):
                    raise ValueError("工作区文件或编码已变化，或游标无效，请重新读取")
                stream.seek(int(position))
            else:
                while offset:
                    skipped = stream.read(min(12000, offset))
                    if not skipped:
                        break
                    offset -= len(skipped)
            text = stream.read(args.get("limit", 12000))
            position = stream.tell()
            more = bool(stream.read(1))
            current = path.stat()
            if (info.st_ino, info.st_size, info.st_mtime_ns) != (
                current.st_ino,
                current.st_size,
                current.st_mtime_ns,
            ):
                raise ValueError("读取期间工作区文件已变化，请重新读取")
        result = {
            "path": args["path"],
            "text": text,
            "next_cursor": f"{revision}:{position}" if more else None,
        }
        if "cursor" not in args:
            result["next_offset"] = args.get("offset", 0) + len(text) if more else None
        return result

    def jar_path(self, task_id, path, artifact_path):
        # artifact_path is supplied by the caller only after Downloads.verify.
        if artifact_path is not None:
            if path is not None:
                raise ValueError("工作区路径和已校验制品只能指定一个")
            target = Path(artifact_path)
        else:
            if not isinstance(path, str) or not path:
                raise ValueError("请指定当前任务工作区内的 .jar 文件")
            target = self.path(task_id, path)
            if target.suffix.lower() != ".jar":
                raise ValueError("请指定当前任务工作区内的 .jar 文件")
        if not target.is_file():
            raise ValueError("指定的 JAR 文件不存在")
        return target

    def jar_entries(self, task_id, args, *, artifact_path=None):
        path = self.jar_path(task_id, args.get("path"), artifact_path)
        limit = jar_limit(args)
        preview = args.get("preview", False)
        preview_limit = args.get("preview_limit", 2000)
        if type(preview_limit) is not int or not 1 <= preview_limit <= 4000:
            raise ValueError("JAR 文本预览 preview_limit 必须为 1 至 4000 字符")
        entries, matches, budget = [], 0, 7000
        with open_jar(path, args.get("nested_jar")) as (jar, items):
            names = [item.filename for item in items if not item.is_dir()]
            signatures = [name for name in names if SIGNATURE.fullmatch(name)]
            nested = [name for name in names if name.lower().endswith(".jar")]
            signature_entries, nested_jars = [], []
            metadata_budget = 2500
            for candidates, rows in (
                (signatures, signature_entries),
                (nested, nested_jars),
            ):
                for name in candidates:
                    size = len(json.dumps(name, ensure_ascii=False)) + 2
                    if len(rows) < 50 and size <= metadata_budget:
                        rows.append(name)
                        metadata_budget -= size
                        budget -= size
            for item in items:
                name = item.filename
                if (
                    item.is_dir()
                    or not name.startswith(args.get("prefix", ""))
                    or not fnmatchcase(name, args.get("glob", "*"))
                    or args.get("contains", "") not in name
                ):
                    continue
                matches += 1
                if len(entries) >= limit or len(name) > budget:
                    continue
                row = {"name": name, "bytes": item.file_size}
                filename = name.rsplit("/", 1)[-1].lower()
                if preview and (
                    filename in JAR_TEXT_NAMES
                    or filename.endswith((".mixins.json", ".accesswidener"))
                ):
                    with jar.open(item) as stream:
                        # Do not read an entire large entry for a preview.
                        source = stream.read(preview_limit * 4 + 1)
                    text = codecs.getincrementaldecoder("utf-8-sig")(
                        errors="replace"
                    ).decode(source, final=len(source) == item.file_size)
                    row.update(
                        text=text[:preview_limit],
                        text_truncated=len(text) > preview_limit
                        or len(source) < item.file_size,
                    )
                size = len(json.dumps(row, ensure_ascii=False))
                if size > budget and "text" in row:
                    del row["text"]
                    row["text_truncated"] = True
                    size = len(json.dumps(row, ensure_ascii=False))
                if size <= budget:
                    budget -= size + 2
                    entries.append(row)
        return {
            "entries": entries,
            "matched": matches,
            "truncated": len(entries) < matches,
            "signed": bool(signatures),
            "signature_entries": signature_entries,
            "nested_jars": nested_jars,
            "total_entries": len(names),
            **(
                {"metadata_truncated": True}
                if len(signature_entries) < len(signatures)
                or len(nested_jars) < len(nested)
                else {}
            ),
        }

    def jar_read(self, task_id, args, *, artifact_path=None):
        path = self.jar_path(task_id, args.get("path"), artifact_path)
        name = args["entry"]
        limit, offset = args.get("limit", 12000), args.get("offset", 0)
        if not 1 <= limit <= 24000 or offset < 0:
            raise ValueError("limit 必须为 1 至 24000，offset 不得为负")
        with open_jar(path, args.get("nested_jar")) as (jar, _):
            item = find_entry(jar, name)
            error = f"JAR 条目是二进制文件：{name}；类文件请改用 decompile 或 javap"
            if binary_entry(name):
                raise ValueError(error)
            if item.file_size > 8 * MIB:
                raise ValueError(f"JAR 文本条目超过 8 MiB：{name}")
            text = jar.read(item).decode(args.get("encoding", "utf-8-sig"), "replace")
            if not is_text(text):
                raise ValueError(error)
        end = offset + limit
        return {
            "entry": name,
            "text": text[offset:end],
            "bytes": item.file_size,
            "next_offset": end if end < len(text) else None,
            "truncated": end < len(text),
        }

    def jar_search(self, task_id, args, *, artifact_path=None):
        path = self.jar_path(task_id, args.get("path"), artifact_path)
        return search_jar(path, args, jar_limit(args, 30))

    def jar_diff(
        self, task_id, args, *, left_artifact_path=None, right_artifact_path=None
    ):
        left = self.jar_path(task_id, args.get("left_path"), left_artifact_path)
        right = self.jar_path(task_id, args.get("right_path"), right_artifact_path)
        with ZipFile(left) as original, ZipFile(right) as updated:
            return self._jar_diff(original, updated, jar_limit(args))

    @staticmethod
    def _jar_diff(left, right, limit):
        hashes = []
        for jar in (left, right):
            index = {}
            for item in checked_entries(jar):
                if item.is_dir():
                    continue
                with jar.open(item) as stream:
                    index[item.filename] = hashlib.file_digest(
                        stream, "sha256"
                    ).hexdigest()
            hashes.append(index)
        left_hashes, right_hashes = hashes
        changes = {"added": [], "removed": [], "changed": []}
        counts = dict.fromkeys((*changes, "unchanged"), 0)
        budget = 7000
        for name in sorted(left_hashes.keys() | right_hashes.keys()):
            old, new = left_hashes.get(name), right_hashes.get(name)
            if old == new:
                counts["unchanged"] += 1
                continue
            group = "added" if old is None else "removed" if new is None else "changed"
            counts[group] += 1
            row = {"name": name, "left_sha256": old, "right_sha256": new}
            size = len(json.dumps(row, ensure_ascii=False)) + 2
            if len(changes[group]) < limit and size <= budget:
                changes[group].append(row)
                budget -= size
        return {
            **changes,
            "unchanged": counts["unchanged"],
            "counts": counts,
            "truncated": any(
                len(rows) < counts[group] for group, rows in changes.items()
            ),
        }

    @asynccontextmanager
    async def java_jar(self, task_id, path, nested, classes):
        entries = [name.replace(".", "/") + ".class" for name in classes]

        def validate(copy_path=None):
            with open_jar(path, nested) as (jar, _):
                for name, entry in zip(classes, entries, strict=True):
                    if entry not in jar.NameToInfo:
                        raise ValueError(f"指定 JAR 中没有类：{name}")
                if copy_path is not None:
                    jar.fp.seek(0)
                    with copy_path.open("wb") as output:
                        shutil.copyfileobj(jar.fp, output)

        if nested is None and path.suffix.lower() == ".jar":
            await asyncio.to_thread(validate)
            yield path, entries
            return
        folder = self.path(task_id)
        folder.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(dir=folder, prefix="java-jar-") as temporary:
            copy_path = Path(temporary) / "input.jar"
            await asyncio.to_thread(validate, copy_path)
            yield copy_path, entries

    async def javap(self, task_id, args, *, java_executable, artifact_path=None):
        path = self.jar_path(task_id, args.get("path"), artifact_path)
        jdk = jdk_executables(str(java_executable), required=("java", "javap"))
        classes = class_names(args)
        nested = args.get("nested_jar")
        verbose = args.get("verbose", False)
        key = digest([await asyncio.to_thread(sha256, path), nested, classes, verbose])[
            :16
        ]
        relative = f"_javap/{key}.txt"
        target = self.path(task_id, relative)
        marker = "\n[javap 输出超过 2 MiB，已截断]\n"
        if target.is_file():
            text = target.read_text(encoding="utf-8")
        else:
            async with self.java_jar(task_id, path, nested, classes) as (
                source,
                entries,
            ):
                text, capped = await run_java_tool(
                    [
                        jdk["javap"],
                        "-J-Xmx128m",
                        "-J-Dfile.encoding=UTF-8",
                        "-J-Dstdout.encoding=UTF-8",
                        "-J-Dstderr.encoding=UTF-8",
                        *(["-v"] if verbose else []),
                        "-p",
                        "-c",
                        "-s",
                        *(
                            f"jar:{source.as_uri()}!/{quote(entry)}"
                            for entry in entries
                        ),
                    ],
                    self.process_job,
                    30,
                    "javap",
                )
            text = text.replace("\r\n", "\n")
            encoded = text.encode("utf-8")
            if capped or len(encoded) > 2 * MIB:
                text = (
                    encoded[: 2 * MIB - len(marker.encode("utf-8"))].decode(
                        "utf-8", "ignore"
                    )
                    + marker
                )
            target.parent.mkdir(parents=True, exist_ok=True)
            with TemporaryDirectory(dir=target.parent, prefix="javap-") as temporary:
                partial = Path(temporary) / "output.txt"
                partial.write_text(text, encoding="utf-8", newline="\n")
                partial.replace(target)
        text = text.replace("\r\n", "\n")
        filtered = javap_methods(text, args["method"]) if args.get("method") else text
        output = "".join(filtered[:6000].splitlines(keepends=True)[:200])
        return {
            "class_names": classes,
            "text": output,
            "truncated": len(output) < len(filtered) or text.endswith(marker),
            "output_path": relative,
            "total_lines": len(text.splitlines()),
            "total_chars": len(text),
        }

    def mapping_file(self, task_id, args, artifact):
        path = (
            Path(artifact)
            if artifact is not None
            else self.path(task_id, args["mapping_path"])
        )
        if not path.is_file():
            raise ValueError("指定的映射文件不存在")
        if path.stat().st_size > 128 * MIB:
            raise ValueError("映射文件超过 128 MiB")
        return path

    async def mapping_command(self, jdk, jars, helper, command, timeout):
        if self.process_job is None:
            raise ValueError("A 工作区缺少辅助进程资源组")
        raw, large = await run_java_tool(
            [
                jdk["java"],
                "-Xmx512m",
                "-Dfile.encoding=UTF-8",
                "-Dstderr.encoding=UTF-8",
                "-cp",
                classpath([helper, *jars[1:]]),
                "WorkspaceTool",
                *command,
            ],
            self.process_job,
            timeout,
            "A 端映射工具",
        )
        if large:
            raise ValueError("A 端映射工具输出超过 2 MiB")
        return json.loads(raw)

    async def mapping_lookup(
        self, task_id, args, *, java_path="", mapping_artifact_path=None
    ):
        mapping = self.mapping_file(task_id, args, mapping_artifact_path)
        query = args["query"]
        if not query.strip():
            raise ValueError("query 必须是非空字符串")
        jdk = await asyncio.to_thread(jdk_executables, java_path)
        jars, helper = await self.tools.prepare(jdk)
        return await self.mapping_command(
            jdk,
            jars,
            helper,
            [
                "lookup",
                mapping,
                query,
                args.get("kind", "all"),
                args.get("namespace", ""),
                args.get("target_namespace", ""),
                jar_limit(args, 30),
            ],
            60,
        )

    async def decompile(
        self,
        task_id,
        args,
        *,
        java_path="",
        artifact_path=None,
        mapping_artifact_path=None,
    ):
        if self.process_job is None:
            raise ValueError("A 工作区缺少辅助进程资源组")
        path = self.jar_path(task_id, args.get("path"), artifact_path)
        names, nested = class_names(args), args.get("nested_jar")
        timeout = args.get("timeout", args.get("timeout_seconds", 60))
        if not 1 <= timeout <= 120:
            raise ValueError("timeout_seconds 必须为 1 至 120")
        mapping = (
            self.mapping_file(task_id, args, mapping_artifact_path)
            if "mapping_path" in args or mapping_artifact_path is not None
            else None
        )
        source_ns, target_ns = args.get("mapping_from", ""), args.get("mapping_to", "")
        if mapping is None and (source_ns or target_ns):
            raise ValueError("mapping_from 与 mapping_to 须与映射文件一起使用")
        key = digest(
            [
                await asyncio.to_thread(sha256, path),
                nested,
                await asyncio.to_thread(sha256, mapping) if mapping else None,
                source_ns,
                target_ns,
            ]
        )[:16]
        relative = f"_decompiled/{key}"
        folder = self.path(task_id, relative)
        metadata, symbols_path = {}, None
        folder.mkdir(parents=True, exist_ok=True)
        async with self.java_jar(task_id, path, nested, names) as (source, _):
            with TemporaryDirectory(dir=folder, prefix="decompile-") as temporary:
                build = Path(temporary)
                if mapping is not None:
                    remapped = self.path(task_id, f"_remapped/{key}.jar")
                    selection = digest(names)[:16]
                    symbols_path = f"{relative}/runtime-symbols-{selection}.txt"
                    symbols = self.path(task_id, symbols_path)
                    index = self.path(
                        task_id, f"{relative}/runtime-symbols-{selection}.json"
                    )
                    if remapped.is_file() and symbols.is_file() and index.is_file():
                        metadata = json.loads(index.read_text(encoding="utf-8"))
                    else:
                        jdk = await asyncio.to_thread(jdk_executables, java_path)
                        jars, helper = await self.tools.prepare(jdk)
                        pending_jar = (
                            remapped if remapped.is_file() else build / "remapped.jar"
                        )
                        pending_symbols = build / "symbols.txt"
                        metadata = await self.mapping_command(
                            jdk,
                            jars,
                            helper,
                            [
                                "remap",
                                mapping,
                                source_ns,
                                target_ns,
                                source,
                                pending_jar,
                                pending_symbols,
                                *names,
                            ],
                            timeout,
                        )
                        if pending_jar != remapped:
                            remapped.parent.mkdir(parents=True, exist_ok=True)
                            pending_jar.replace(remapped)
                        pending_symbols.replace(symbols)
                        pending_index = build / "symbols.json"
                        pending_index.write_text(json.dumps(metadata), encoding="utf-8")
                        pending_index.replace(index)
                    source = remapped
                readable = [
                    metadata["classes"][name.replace(".", "/")]
                    if metadata
                    else name.replace(".", "/")
                    for name in names
                ]
                with ZipFile(source) as jar:
                    entries = checked_entries(jar)
                    roots = []
                    for name in readable:
                        entry_name(name)
                        roots.append(
                            min(
                                (
                                    root
                                    for root in readable
                                    if name.startswith(root + "$")
                                ),
                                key=len,
                                default=name,
                            )
                        )
                    outputs = [
                        self.path(task_id, f"{relative}/{root}.java") for root in roots
                    ]
                    cached = [output.is_file() for output in outputs]
                    missing = {
                        root
                        for root, found in zip(roots, cached, strict=True)
                        if not found
                    }
                    if missing:
                        selection_jar = build / "selected.jar"
                        with ZipFile(selection_jar, "w", ZIP_DEFLATED) as selected:
                            for item in entries:
                                name = item.filename
                                if name.endswith(".class") and any(
                                    name == root + ".class"
                                    or name.startswith(root + "$")
                                    for root in missing
                                ):
                                    entry_name(name)
                                    with (
                                        jar.open(item) as data,
                                        selected.open(name, "w") as out,
                                    ):
                                        shutil.copyfileobj(data, out)
                if missing:
                    jdk = await asyncio.to_thread(jdk_executables, java_path)
                    jars, _ = await self.tools.prepare(jdk, helper=False)
                    destination = build / "source"
                    destination.mkdir()
                    log, _ = await run_java_tool(
                        [
                            jdk["java"],
                            "-Xmx512m",
                            "-Dfile.encoding=UTF-8",
                            "-Dstdout.encoding=UTF-8",
                            "-Dstderr.encoding=UTF-8",
                            "-jar",
                            jars[0],
                            "--silent",
                            "--folder",
                            f"-e={source}",
                            selection_jar,
                            destination,
                        ],
                        self.process_job,
                        timeout,
                        "A 端 Vineflower 反编译",
                    )
                    for name in sorted(missing):
                        output = self.path(task_id, f"{relative}/{name}.java")
                        generated = resolve_file(destination, name + ".java")
                        if not generated.is_file():
                            raise ValueError(
                                f"Vineflower 未生成 {name}.java：{log[-1000:].strip()}"
                            )
                        output.parent.mkdir(parents=True, exist_ok=True)
                        generated.replace(output)
        files, budget = [], 4000
        for name, output, found in zip(names, outputs, cached, strict=True):
            text = output.read_text(encoding="utf-8")
            preview = text[:budget]
            budget -= len(preview)
            row = {
                "class_name": name,
                "output_path": output.relative_to(self.directory(task_id)).as_posix(),
                "lines": len(text.splitlines()),
                "chars": len(text),
                "sha256": sha256(output),
                "cached": found,
                "preview": preview,
                "preview_truncated": len(preview) < len(text),
            }
            files.append(row)
        result = {"files": files}
        if symbols_path is not None:
            with symbols.open(encoding="utf-8") as stream:
                preview = stream.read(1800)
            result.update(
                remapped=True,
                mapping_from=metadata["mapping_from"],
                mapping_to=metadata["mapping_to"],
                runtime_symbols_path=symbols_path,
                runtime_symbols_preview=preview,
            )
        return result

    def jar_patch(self, task_id, args, *, source_artifact_path=None):
        source = self.jar_path(task_id, args.get("source_path"), source_artifact_path)
        relative = entry_name(args["output_path"])
        output = self.path(task_id, relative)
        if output == source or output.suffix.lower() != ".jar":
            raise ValueError("output_path 须是与源文件不同的工作区 .jar 路径")
        strip = args.get("strip_signatures", False)
        replacements, removals = {}, set()
        for row in args.get("replace_entries", []):
            name = entry_name(row["entry"])
            if name in replacements:
                raise ValueError(f"补丁指定了重复条目：{name}")
            target = self.path(task_id, row["file"])
            if not target.is_file():
                raise ValueError(f"补丁替换文件不存在：{row['file']}")
            replacements[name] = target
        for raw in args.get("remove_entries", []):
            name = entry_name(raw)
            if name in replacements or name in removals:
                raise ValueError(f"补丁指定了重复条目：{name}")
            removals.add(name)
        if not (replacements or removals or strip):
            raise ValueError("jar_patch 须指定替换、移除或 strip_signatures=true")
        if any(SIGNATURE.fullmatch(name) for name in replacements):
            raise ValueError("jar_patch 不允许写入签名条目")

        def write_patch(jar, items, partial, files, removed, signatures, *, clean):
            omitted = removed | set(signatures) | files.keys()
            kept = {
                item.filename: item for item in items if item.filename not in omitted
            }
            if (
                len(kept) + len(files) > JAR_ENTRIES
                or sum(item.file_size for item in kept.values())
                + sum(p.stat().st_size for p in files.values())
                > JAR_BYTES
            ):
                raise ValueError("修补后 JAR 条目总数或解压后大小超过上限")
            with ZipFile(partial, "w", ZIP_DEFLATED) as patched:
                patched.comment = jar.comment
                for name in sorted(kept.keys() | files.keys()):
                    if name in jar.NameToInfo:
                        item = copy(jar.getinfo(name))
                    else:
                        item = ZipInfo(name)
                        item.compress_type = ZIP_DEFLATED
                    with (
                        files[name].open("rb")
                        if name in files
                        else jar.open(name) as stream
                    ):
                        if clean and name.upper() == "META-INF/MANIFEST.MF":
                            manifest = stream.read(8 * MIB + 1)
                            if len(manifest) > 8 * MIB:
                                raise ValueError("JAR MANIFEST.MF 超过 8 MiB")
                            patched.writestr(item, clean_manifest(manifest))
                        else:
                            with patched.open(item, "w") as destination:
                                shutil.copyfileobj(stream, destination)
            with ZipFile(partial) as patched:
                checked_entries(patched)
                if bad := patched.testzip():
                    raise ValueError(f"修补后 JAR 条目校验失败：{bad}")
                return self._jar_diff(jar, patched, jar_limit({}))

        nested = args.get("nested_jar")
        with open_jar(source) as (jar, items), ExitStack() as stack:
            signed = [
                item.filename for item in items if SIGNATURE.fullmatch(item.filename)
            ]
            stripped = signed.copy()
            if nested is not None:
                inner = stack.enter_context(open_nested(jar, nested))
                inner_items = checked_entries(
                    inner,
                    bytes_left=JAR_BYTES - sum(item.file_size for item in items),
                    entries_left=JAR_ENTRIES - len(items),
                )
                inner_signed = [
                    item.filename
                    for item in inner_items
                    if SIGNATURE.fullmatch(item.filename)
                ]
                stripped.extend(f"{nested}!/{name}" for name in inner_signed)
            if stripped and not strip:
                raise ValueError(
                    f"源 JAR 包含签名条目：{', '.join(stripped)[:1000]}。"
                    "请明确指定 strip_signatures=true，或改用独立的 Mixin 补丁 MOD"
                )
            output.parent.mkdir(parents=True, exist_ok=True)
            temporary = Path(
                stack.enter_context(
                    TemporaryDirectory(dir=output.parent, prefix="patch-")
                )
            )
            result = {"output_path": relative, "signatures_stripped": stripped}
            if nested is not None:
                nested_path = temporary / "nested.jar"
                nested_diff = write_patch(
                    inner,
                    inner_items,
                    nested_path,
                    replacements,
                    removals,
                    inner_signed,
                    clean=bool(inner_signed),
                )
                if nested_path.stat().st_size > NESTED_BYTES:
                    raise ValueError(f"修补后嵌套 JAR 超过 64 MiB：{nested}")
                result.update(
                    nested_jar=nested,
                    nested_sha256=sha256(nested_path),
                    nested_diff=nested_diff,
                )
                replacements, removals = {nested: nested_path}, set()
            partial = temporary / "output.jar"
            result["diff"] = write_patch(
                jar,
                items,
                partial,
                replacements,
                removals,
                signed,
                clean=bool(signed) if nested is not None else strip,
            )
            if nested is not None:
                with open_jar(partial, nested):
                    pass  # Recheck combined archive limits after the replacement.
            result.update(sha256=sha256(partial), bytes=partial.stat().st_size)
            partial.replace(output)
        return result

    async def execute(self, jobs, key, task_id, args, *, java_path=""):
        if not self.powershell_path:
            raise ValueError("A 工作区命令需要 PowerShell 7.3+，请安装 pwsh.exe")
        directory = self.directory(task_id)
        directory.mkdir(parents=True, exist_ok=True)
        cwd = self.path(task_id, args.get("cwd", "."))
        if not cwd.is_dir():
            raise ValueError("工作区 cwd 不是目录")
        await asyncio.to_thread(verify_scripts, directory, args["script_hashes"])
        script = jobs.directory(key) / "workspace.ps1"
        script.write_text(
            "$ErrorActionPreference = 'Stop'\n"
            "$PSNativeCommandUseErrorActionPreference = $true\n"
            "[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()\n"
            + args["script"],
            encoding="utf-8-sig",
        )
        if self.process_job is None:
            raise ValueError("A 工作区缺少辅助进程资源组")
        process = await asyncio.create_subprocess_exec(
            # The Windows venv redirector creates a distinct Job Object per launch.
            # This worker uses only the standard library and can join the shared job directly.
            sys._base_executable,
            str(Path(__file__).with_name("workspace_worker.py")),
            self.process_job,
            self.powershell_path,
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-File",
            str(script),
            cwd=str(cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=await asyncio.to_thread(self.tools.exec_environment, java_path),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        jobs.processes[key] = process
        jobs.update(
            key,
            pid=process.pid,
            process_created=await asyncio.to_thread(
                psutil.Process(process.pid).create_time
            ),
        )
        decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        timeout = args.get("timeout", args.get("timeout_seconds", 1800))
        try:
            async with asyncio.timeout(timeout):
                while data := await process.stdout.read(4096):
                    if jobs.stopped(key):
                        break
                    text = decoder.decode(data)
                    if text:
                        jobs.emit(key, {"output": text})
                tail = decoder.decode(b"", final=True)
                if tail:
                    jobs.emit(key, {"output": tail})
                code = await process.wait()
                jobs.update(key, exit_code=code)
                jobs.flush(key)
                if code and not jobs.stopped(key):
                    raise RuntimeError(f"A 工作区命令退出码 {code}，请读取后台输出")
        except TimeoutError:
            from .jobs import terminate_tree

            await terminate_tree(process)
            raise TimeoutError(f"A 工作区命令超过 {timeout} 秒，已结束进程树") from None
