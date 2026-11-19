import asyncio
import codecs
import os
import subprocess
import sys
from pathlib import Path

import psutil

from .paths import resolve_file
from .review import verify_scripts


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
        return {
            "path": str(directory),
            "items": [
                {
                    "name": item.name,
                    "directory": item.is_dir(),
                    "bytes": item.stat().st_size if item.is_file() else None,
                }
                for item in sorted(directory.iterdir(), key=lambda item: item.name)
            ][:200],
        }

    def read(self, task_id, args):
        self.directory(task_id).mkdir(parents=True, exist_ok=True)
        path = self.path(task_id, args["path"])
        text = path.read_text(encoding=args.get("encoding", "utf-8"))
        offset = args.get("offset", 0)
        end = min(len(text), offset + args.get("limit", 12000))
        return {
            "path": args["path"],
            "text": text[offset:end],
            "next_offset": end if end < len(text) else None,
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
        timeout = args.get("timeout_seconds", 1800)
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
