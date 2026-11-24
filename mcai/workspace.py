import asyncio
import codecs
import hashlib
import heapq
import json
import os
import subprocess
import sys
from fnmatch import fnmatchcase
from pathlib import Path
from urllib.parse import quote
from zipfile import ZipFile

import psutil

from .paths import resolve_file
from .review import digest, verify_scripts

JAR_TEXT_NAMES = {
    "manifest.mf",
    "plugin.yml",
    "paper-plugin.yml",
    "fabric.mod.json",
    "quilt.mod.json",
    "mods.toml",
    "neoforge.mods.toml",
}


def jar_limit(args):
    limit = args.get("limit", 50)
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("JAR 检查条数 limit 必须为 1 至 100")
    return limit


class Workspace:
    def __init__(self, root, powershell_path, process_job):
        self.root = Path(root).resolve()
        self.powershell_path = powershell_path
        self.process_job = process_job

    def directory(self, task_id):
        return self.root / task_id

    def path(self, task_id, relative="."):
        if relative == ".":
            return self.directory(task_id).resolve()
        return resolve_file(self.directory(task_id), relative)

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
            folder = self.directory(task_id)
            if folder.parent != self.root or folder.resolve() != folder:
                raise ValueError("JAR 检查只允许当前任务的工作区目录")
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
        with ZipFile(path) as jar:
            for item in jar.infolist():
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
                    filename in JAR_TEXT_NAMES or filename.endswith(".mixins.json")
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
        }

    def jar_diff(
        self, task_id, args, *, left_artifact_path=None, right_artifact_path=None
    ):
        left = self.jar_path(task_id, args.get("left_path"), left_artifact_path)
        right = self.jar_path(task_id, args.get("right_path"), right_artifact_path)
        limit = jar_limit(args)
        hashes = []
        for path in (left, right):
            index = {}
            with ZipFile(path) as jar:
                files = [item for item in jar.infolist() if not item.is_dir()]
                if sum(item.file_size for item in files) > 1024**3:
                    raise ValueError("JAR 解压后超过 1 GiB，无法逐条比较")
                for item in files:
                    if item.filename in index:
                        raise ValueError(f"JAR 包含重复条目：{item.filename[:200]}")
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

    async def javap(self, task_id, args, *, java_executable, artifact_path=None):
        path = self.jar_path(task_id, args.get("path"), artifact_path)
        java = Path(java_executable)
        javap = java.with_name("javap.exe").resolve()
        if (
            not java.is_absolute()
            or not java.is_file()
            or (
                javap.parent != java.resolve().parent
                or javap.name.lower() != "javap.exe"
                or not javap.is_file()
            )
        ):
            raise ValueError("已配置的 Java 同目录缺少 javap.exe")
        classes = args["class_names"]
        if (
            not isinstance(classes, list)
            or not 1 <= len(classes) <= 10
            or any(
                not isinstance(name, str)
                or len(name) > 240
                or not all(
                    part.replace("$", "_").isidentifier() for part in name.split(".")
                )
                for name in classes
            )
        ):
            raise ValueError("class_names 须包含 1 至 10 个 Java 二进制类名")
        entries = [name.replace(".", "/") + ".class" for name in classes]
        with ZipFile(path) as jar:
            for name, entry in zip(classes, entries, strict=True):
                if entry not in jar.NameToInfo:
                    raise ValueError(f"指定 JAR 中没有类：{name}")
        process = await asyncio.create_subprocess_exec(
            str(javap),
            "-J-Xmx128m",
            "-J-Dfile.encoding=UTF-8",
            "-J-Dstdout.encoding=UTF-8",
            "-p",
            "-c",
            "-s",
            *(f"jar:{path.resolve().as_uri()}!/{quote(entry)}" for entry in entries),
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        text, tail = "", ""
        try:
            async with asyncio.timeout(30):
                while data := await process.stdout.read(4096):
                    chunk = decoder.decode(data)
                    text = (text + chunk)[:6001]
                    tail = (tail + chunk)[-1000:]
                text = (text + decoder.decode(b"", final=True))[:6001]
                code = await process.wait()
        except TimeoutError:
            raise TimeoutError("javap 在 30 秒内未完成") from None
        finally:
            if process.returncode is None:
                process.kill()
                # Drain remaining pipe bytes before waiting for the exit.
                await process.communicate()
        if code:
            raise ValueError(f"javap 退出码 {code}：{tail.strip()}")
        output = "".join(text[:6000].splitlines(keepends=True)[:200])
        return {
            "class_names": classes,
            "text": output,
            "truncated": len(output) < len(text),
        }

    async def execute(self, jobs, key, task_id, args):
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
            env=os.environ.copy(),
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
