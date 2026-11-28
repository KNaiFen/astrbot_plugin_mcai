import asyncio
import codecs
import json
import os
import re
import time
import traceback
import uuid
from itertools import islice
from pathlib import Path

import psutil

from .environment import java_environment
from .evidence import evidence_view, result_at
from .paths import resolve_file
from .plans import execution_configuration, execution_configuration_changed
from .review import validate_diagnostic_script, verify_scripts

ACTIVE = {"pending", "running"}
EXECUTE_FLUSH_INTERVAL = 0.25


def kill_tree(parent):
    try:
        children = parent.children(recursive=True)
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        children = []
    for process in [*reversed(children), parent]:
        try:
            process.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass  # A vanished or inaccessible process must not block the others.


async def terminate_tree(process):
    if process.returncode is not None:
        return
    try:
        kill_tree(psutil.Process(process.pid))
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass
    await process.wait()


class Jobs:
    def __init__(self, store, *, recover=True, batching=False):
        self.store = store
        self.workers = {}
        self.processes = {}
        self.stops = {}
        self.waiters = {}
        self.batching = batching
        self.rows = []
        self.row_characters = 0
        for job in store.active("background_job") if recover else ():
            if job["status"] in ACTIVE:
                if job.get("pid") and job.get("process_created"):
                    try:
                        parent = psutil.Process(job["pid"])
                        if parent.create_time() == job["process_created"]:
                            kill_tree(parent)
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass
                job.update(
                    status="interrupted",
                    error="MC 控制程序重启，保留已有输出；未自动重新执行",
                )
                store.save("background_job", job["id"], job)

    def directory(self, key):
        return self.store.directory / "jobs" / key

    def get(self, key):
        job = self.store.get("background_job", key)
        if job is None:
            if self.store.get("cleaned_job", key) is not None:
                raise ValueError("后台任务已清理")
            raise ValueError("后台任务不存在")
        return job

    def update(self, key, **fields):
        if self.batching:
            self.flush(key, **fields)
            return
        job = self.get(key)
        job.update(fields)
        self.store.save("background_job", key, job)
        if job["status"] not in ACTIVE:
            self.notify(key)

    def stopped(self, key):
        return self.stops[key].is_set()

    def request_stop(self, key):
        self.stops[key].set()

    async def wait_io(self, key, awaitable):
        pending = asyncio.ensure_future(awaitable)
        try:
            while not pending.done():
                if self.stopped(key):
                    await terminate_tree(self.processes[key])
                    raise asyncio.CancelledError
                await asyncio.wait({pending}, timeout=0.1)
            return await pending
        finally:
            if not pending.done():
                pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)

    def emit(self, key, row):
        encoded = json.dumps(row, ensure_ascii=False)
        if len(encoded) > 12000:
            reference = uuid.uuid4().hex + ".json"
            (self.directory(key) / reference).write_text(encoded, encoding="utf-8")
            row = {
                "reference": reference,
                "characters": len(encoded),
                "preview": encoded[:500],
                "overview": evidence_view(row, 4500),
                "message": "原文已保存；先看overview，按result_path定向读取必要字段，避免全文分页。",
                **(
                    {
                        k: row[k]
                        for k in ("path", "line", "tail_window", "tail_order")
                        if k in row
                    }
                    if row.get("tail_order") == "eof_first"
                    else {}
                ),
            }
        if self.batching:
            self.rows.append(row)
            self.row_characters += len(json.dumps(row, ensure_ascii=False))
            if len(self.rows) >= 100 or self.row_characters >= 24000:
                self.flush(key)
        else:
            self.store.event("job:" + key, row)
            self.notify(key)

    def flush(self, key, **fields):
        if self.rows or fields:
            self.store.job_batch(key, self.rows, fields)
            self.rows = []
            self.row_characters = 0
            self.notify(key)

    def notify(self, key):
        for waiter in self.waiters.get(key, ()):
            if not waiter.done():
                waiter.set_result(None)

    def page(self, key, after=0, limit=100):
        job = self.get(key)
        items, size, cursor = [], 0, after
        for item in self.store.events("job:" + key, after, min(max(limit, 1), 100)):
            encoded = json.dumps(item, ensure_ascii=False)
            if items and (
                size + len(encoded) > 14000
                or job.get("kind") == "files_query"
                and item["body"].get("tail_order") == "eof_first"
            ):
                break
            items.append(item)
            size += len(encoded)
            cursor = item["seq"]
        more = bool(self.store.events("job:" + key, cursor, 1))
        return {
            **job,
            "items": items,
            "next_cursor": cursor if more or job["status"] in ACTIVE else None,
            "cursor": cursor,
            "complete": job["status"] not in ACTIVE and not more,
        }

    async def wait(self, key, wait_seconds=10, after=0, limit=100):
        if not 0 <= wait_seconds <= 25:
            raise ValueError("后台等待秒数必须在 0 至 25 之间")
        page = self.page(key, after, limit)
        worker = self.workers.get(key)
        if (
            not wait_seconds
            or page["items"]
            or page["status"] not in ACTIVE
            or not worker
        ):
            return page
        loop = asyncio.get_running_loop()
        deadline = loop.time() + wait_seconds
        while True:
            waiters = self.waiters.setdefault(key, set())
            waiter = loop.create_future()
            waiters.add(waiter)
            try:
                done, _ = await asyncio.wait(
                    (worker, waiter),
                    timeout=max(0, deadline - loop.time()),
                    return_when=asyncio.FIRST_COMPLETED,
                )
            finally:
                waiter.cancel()
                waiters.remove(waiter)
                if not waiters:
                    del self.waiters[key]
            page = self.page(key, after, limit)
            if (
                not done
                or worker.done()
                or page["items"]
                or page["status"] not in ACTIVE
            ):
                return page

    def artifact(self, key, reference, offset=0, *, view="value", result_path=()):
        self.get(key)
        path = resolve_file(self.directory(key), reference)
        if view == "summary" or result_path:
            text = path.read_text(encoding="utf-8")
            try:
                value = json.loads(text)
            except json.JSONDecodeError:
                if result_path:
                    raise ValueError("非JSON产物不能使用result_path") from None
                value = text
            value = result_at(value, result_path)
            if view == "summary":
                return {
                    "view": "summary",
                    "result_path": list(result_path),
                    "overview": evidence_view(value, base_path=result_path),
                    "source": {"job_id": key, "reference": reference},
                }
            text = json.dumps(value, ensure_ascii=False)
            return {
                "text": text[offset : offset + 6000],
                "offset": offset,
                "next_offset": offset + 6000 if len(text) > offset + 6000 else None,
                "result_path": list(result_path),
            }
        with path.open(encoding="utf-8") as stream:
            # Character offsets are independent of Windows text mode and UTF-8 byte widths.
            for position in range(0, offset, 12000):
                stream.read(min(12000, offset - position))
            text = stream.read(12000)
            # Budget the escaped JSON, leaving room for the result envelope.
            size = 0
            for end, character in enumerate(text, 1):
                size += len(json.dumps(character, ensure_ascii=False)) - 2
                if size > 12000:
                    text = text[: end - 1]
                    more = True
                    break
            else:
                more = bool(stream.read(1))
        return {
            "text": text,
            "offset": offset,
            "next_offset": offset + len(text) if more else None,
        }

    def find(self, key, args):
        expression = re.compile(
            args["query"] if args.get("regex") else re.escape(args["query"]),
            0 if args.get("case_sensitive") else re.I,
        )
        if (
            not args["query"]
            or args.get("offset", 0) < 0
            or not 1 <= args.get("limit", 20) <= 100
        ):
            raise ValueError("产物查找需要非空 query、非负 offset 和 1 至 100 的 limit")
        matches, position = [], 0
        with resolve_file(self.directory(key), args["reference"]).open(
            encoding="utf-8"
        ) as stream:
            for line in stream:
                if position + len(line) <= args.get("offset", 0):
                    position += len(line)
                    continue
                for match in expression.finditer(
                    line, max(0, args.get("offset", 0) - position)
                ):
                    start, end = position + match.start(), position + match.end()
                    matches.append(
                        {
                            "offset": start,
                            "end": end,
                            "preview": line[
                                max(0, match.start() - 80) : match.start() + 400
                            ],
                        }
                    )
                    if len(matches) >= args.get("limit", 20):
                        return {"matches": matches, "next_offset": max(start + 1, end)}
                position += len(line)
        return {"matches": matches, "next_offset": None}

    async def start(self, operation, run):
        key = operation["id"]
        if self.store.get("background_job", key) is None:
            self.directory(key).mkdir(parents=True)
            self.stops[key] = asyncio.Event()
            self.store.save(
                "background_job",
                key,
                {
                    "id": key,
                    "instance": operation["instance"],
                    "task_id": operation["task_id"],
                    "kind": operation["action"],
                    "status": "pending",
                    "created": time.time(),
                    "progress": {},
                },
            )
            self.workers[key] = asyncio.create_task(self._run(key, run))
            self.store.log("background_started", job=key, request=operation)
        worker = self.workers.get(key)
        if worker:
            await asyncio.wait({worker}, timeout=2)
        return self.page(key)

    async def _run(self, key, run):
        try:
            self.update(key, status="running")
            await run(key)
            self.update(
                key,
                status="cancelled" if self.stopped(key) else "completed",
                ended=time.time(),
            )
        except asyncio.CancelledError:
            self.update(key, status="cancelled", ended=time.time())
            raise
        except Exception as exc:
            summary = self.get(key).get("summary", {})
            self.update(
                key,
                status="cancelled" if self.stopped(key) else "failed",
                error=f"{type(exc).__name__}: {exc}",
                ended=time.time(),
                **(
                    {"summary": {**summary, "partial": True}}
                    if "partial" in summary
                    else {}
                ),
            )
            self.store.log(
                "background_error", job=key, traceback=traceback.format_exc()
            )
        finally:
            process = self.processes.pop(key, None)
            if process:
                await terminate_tree(process)
            self.workers.pop(key, None)
            self.store.log("background_finished", job=self.get(key))

    async def cancel(self, key):
        job = self.get(key)
        if job["status"] in ACTIVE:
            self.request_stop(key)
            process = self.processes.get(key)
            if process:
                await terminate_tree(process)
            worker = self.workers.get(key)
            if worker:
                if job["kind"] in ("download", "mods"):
                    worker.cancel()
                    await asyncio.gather(worker, return_exceptions=True)
                else:
                    await worker
        return self.page(key)

    async def cancel_task(self, instance, task_id):
        for job in self.store.active("background_job", instance, task_id):
            if (
                job["instance"] == instance
                and job["task_id"] == task_id
                and job["status"] in ACTIVE
            ):
                await self.cancel(job["id"])

    async def execute(self, key, config, args):
        if self.stopped(key):
            return
        timeout = args.get("timeout", 120)
        if not 0 < timeout <= 600:
            raise ValueError("诊断脚本超时必须大于 0 且不超过 600 秒")
        cwd = (
            resolve_file(config["directory"], args["cwd"])
            if args.get("cwd") not in (None, "", ".")
            else Path(config["directory"])
        )
        await asyncio.to_thread(
            verify_scripts, config["directory"], args.get("script_hashes", [])
        )
        await asyncio.to_thread(
            validate_diagnostic_script, args["script"], config["powershell_path"]
        )
        if execution_configuration_changed(
            args.get("review_configuration", {}),
            execution_configuration(config, diagnostic=True),
        ):
            raise ValueError("审核后诊断使用的配置已变化，未执行")
        script = self.directory(key) / (
            "diagnostic.ps1" if os.name == "nt" else "diagnostic.sh"
        )
        prefix = (
            "$ErrorActionPreference = 'Stop'\n$PSNativeCommandUseErrorActionPreference = $true\n[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()\n"
            if os.name == "nt"
            else "set -e\n"
        )
        script.write_text(
            prefix + args["script"],
            encoding="utf-8-sig" if os.name == "nt" else "utf-8",
        )
        argv = (
            [
                config["powershell_path"],
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-File",
                str(script),
            ]
            if os.name == "nt"
            else ["bash", str(script)]
        )
        process = await asyncio.create_subprocess_exec(
            *argv,
            cwd=cwd,
            env=java_environment(config),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        self.processes[key] = process
        self.update(
            key,
            pid=process.pid,
            process_created=psutil.Process(process.pid).create_time(),
        )
        decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        loop = asyncio.get_running_loop()
        last_flush = None
        try:
            async with asyncio.timeout(timeout):
                with (self.directory(key) / "output.log").open("ab") as output:
                    while True:
                        read = process.stdout.read(16384)
                        if self.rows:
                            read_task = asyncio.create_task(read)
                            try:
                                done, _ = await asyncio.wait(
                                    {read_task},
                                    timeout=max(
                                        0,
                                        last_flush
                                        + EXECUTE_FLUSH_INTERVAL
                                        - loop.time(),
                                    ),
                                )
                                if not done:
                                    self.flush(key)
                                    last_flush = loop.time()
                                data = await read_task
                                read_task = None
                            finally:
                                if read_task is not None:
                                    read_task.cancel()
                                    await asyncio.gather(
                                        read_task, return_exceptions=True
                                    )
                        else:
                            data = await read
                        if not data:
                            break
                        output.write(data)
                        output.flush()
                        text = decoder.decode(data)
                        # Keep ordinary output inline in the existing result pages.
                        for offset in range(0, len(text), 2048):
                            self.emit(key, {"output": text[offset : offset + 2048]})
                            if self.batching and (
                                not self.rows
                                or last_flush is None
                                or loop.time() - last_flush >= EXECUTE_FLUSH_INTERVAL
                            ):
                                if self.rows:
                                    self.flush(key)
                                last_flush = loop.time()
                tail = decoder.decode(b"", final=True)
                if tail:
                    self.emit(key, {"output": tail})
                self.flush(key)
                code = await process.wait()
                self.update(key, exit_code=code)
                if code and not self.stopped(key):
                    raise RuntimeError(f"诊断脚本退出码 {code}，请查看任务输出")
        except (TimeoutError, asyncio.CancelledError) as exc:
            # Drain the killed child's pipe so a paused transport can also close.
            if process.returncode is None:
                drain = asyncio.create_task(process.stdout.read())
                try:
                    await terminate_tree(process)
                finally:
                    drain.cancel()
                    await asyncio.gather(drain, return_exceptions=True)
            if isinstance(exc, TimeoutError):
                raise TimeoutError(f"诊断脚本超过 {timeout} 秒，已结束进程树") from None
            raise

    async def collect(self, key, rows):
        iterator = iter(rows)
        count, errors = 0, 0
        truncation = {}
        while not self.stopped(key):
            batch = await asyncio.to_thread(lambda: list(islice(iterator, 100)))
            if not batch:
                break
            for row in batch:
                self.emit(key, row)
                count += 1
                errors += int("error" in row)
                if row.get("partial") and row.get("truncated_reason"):
                    truncation = {
                        field: row[field]
                        for field in (
                            "partial",
                            "truncated_reason",
                            "scanned_files",
                            "scanned_events",
                            "unique_groups_total",
                            "omitted_groups",
                            "matched_files",
                            "find_limit",
                            "note",
                        )
                        if field in row
                    }
            self.update(
                key,
                progress={"records": count},
                summary={"errors": errors, "partial": bool(errors), **truncation},
            )
        if hasattr(iterator, "close"):
            iterator.close()

    def result(self, operation, result):
        if (
            isinstance(result, dict)
            and result.get("id") == operation["id"]
            and self.store.get("background_job", operation["id"])
        ):
            return result
        if len(json.dumps(result, ensure_ascii=False)) <= 16000:
            return result
        key = operation["id"]
        self.directory(key).mkdir(parents=True, exist_ok=True)
        self.store.save(
            "background_job",
            key,
            {
                "id": key,
                "instance": operation["instance"],
                "task_id": operation["task_id"],
                "kind": "result",
                "status": "completed",
            },
        )
        self.emit(key, result)
        self.flush(key)
        return self.page(key)

    async def close(self):
        for key in list(self.workers):
            await self.cancel(key)
