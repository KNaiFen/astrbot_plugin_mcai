"""Task-local API traces and portable diagnostics, independent of group output."""

import asyncio
import copy
import hashlib
import json
import logging
import math
import os
import sqlite3
import time
import uuid
import zipfile
from contextlib import ExitStack, closing
from dataclasses import fields, is_dataclass
from heapq import merge
from itertools import batched
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from .model_usage import UsageWriteError, record_request
from .monthly_logs import append as append_log
from .monthly_logs import diagnostic_sources
from .protocol import PRODUCT_VERSION, PROTOCOL
from .runtime_rules import rules_status
from .storage import Store

logger = logging.getLogger("astrbot")
SECRET_FIELDS = {
    "authorization",
    "proxy-authorization",
    "api_key",
    "x-api-key",
    "host_token",
    "cookie",
}


def json_value(value):
    if isinstance(value, asyncio.Event):
        return {"is_set": value.is_set()}
    if hasattr(value, "model_dump"):
        return json_value(value.model_dump(mode="json"))
    if hasattr(value, "openai_schema"):
        return value.openai_schema()
    if is_dataclass(value):
        return {
            field.name: json_value(getattr(value, field.name))
            for field in fields(value)
        }
    if isinstance(value, dict):
        return {
            str(key): "[redacted]"
            if str(key).lower() in SECRET_FIELDS
            else json_value(item)
            for key, item in value.items()
            if type(item).__name__ not in ("NotGiven", "Omit")
        }
    if isinstance(value, (list, tuple)):
        return [json_value(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"不能记录 API 数据类型：{type(value).__name__}")


def trace_event(store, kind, *, task=None, **fields):
    directory = store.directory / "traces"
    directory.mkdir(exist_ok=True)
    path = directory / f"{task or 'unassigned'}.jsonl"
    entry = {"time": time.time(), "kind": kind, "task": task, **fields}
    line = (json.dumps(json_value(entry), ensure_ascii=False) + "\n").encode()
    if not task:
        append_log(path, line, entry["time"])
    else:
        with path.open("ab") as stream:
            stream.write(line)
    return entry


class TraceStream:
    def __init__(self, stream, record, finish):
        self.stream, self.record, self.finish = stream, record, finish
        self.closed = False
        self.status = "incomplete"

    async def __aiter__(self):
        finish_reasons = {}
        try:
            async for event in self.stream:
                self.record("api_chunk", data=event)
                kind = getattr(event, "type", "")
                if kind in (
                    "response.completed",
                    "response.incomplete",
                    "response.failed",
                    "error",
                ):
                    self.status = "failed" if kind == "error" else kind.split(".")[1]
                    await self.close()
                for choice in getattr(event, "choices", []):
                    if choice.finish_reason is not None:
                        finish_reasons[choice.index] = choice.finish_reason
                    else:
                        finish_reasons.setdefault(choice.index, None)
                if finish_reasons:
                    self.status = (
                        "completed"
                        if all(
                            reason in ("stop", "tool_calls", "function_call")
                            for reason in finish_reasons.values()
                        )
                        else "incomplete"
                    )
                yield event
        except asyncio.CancelledError:
            self.status = "cancelled"
            raise
        except Exception as exc:
            self.status = "failed"
            self.record("api_error", error=f"{type(exc).__name__}: {exc}")
            raise
        finally:
            await self.close()

    async def close(self):
        if not self.closed:
            self.closed = True
            try:
                await self.stream.close()
            finally:
                self.finish(self.status)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.close()


def trace_calls(provider, store, task, stage, *, count_for_task=True):
    def wrap(create, transport):
        async def call(**kwargs):
            identity, started = uuid.uuid4().hex, time.monotonic()
            provider_id = provider.provider_config.get("id")
            model = kwargs.get("model") or (kwargs.get("body") or {}).get("model")
            usage = None
            reasoning = (
                kwargs.get("reasoning")
                or (kwargs.get("extra_body") or {}).get("reasoning")
                or {}
            )
            summary_requested = bool(reasoning.get("summary"))
            summary_returned = False
            # Provider keys can also appear in an exception from a remote gateway.
            keys = provider.provider_config.get("key", [])
            keys = [keys] if isinstance(keys, str) else keys

            def record(kind, **fields):
                nonlocal summary_returned, usage, model
                if "error" in fields:
                    for key in keys:
                        if key:
                            fields["error"] = fields["error"].replace(key, "[redacted]")
                try:
                    if kind in ("api_chunk", "api_response"):
                        data = fields["data"] = json_value(fields["data"])
                        response = data.get("response") or data
                        if response.get("usage") is not None:
                            usage = response["usage"]
                        model = model or response.get("model")
                        summary_returned = (
                            summary_returned
                            or bool(
                                data.get("type", "").startswith(
                                    "response.reasoning_summary_text."
                                )
                                and (data.get("delta") or data.get("text"))
                            )
                            or transport != "alpha/search"
                            and any(
                                part.get("text")
                                for item in (response.get("output") or [])
                                if item.get("type") == "reasoning"
                                for part in item.get("summary", [])
                            )
                        )
                    trace_event(
                        store,
                        kind,
                        task=task,
                        request_id=identity,
                        stage=stage,
                        **fields,
                    )
                except (OSError, TypeError, ValueError):
                    # A local trace failure must never resend a completed API request.
                    logger.exception(
                        "MCAI trace write failed task=%s request=%s kind=%s",
                        task,
                        identity,
                        kind,
                    )

            def finish(status):
                summary_status = (
                    "returned"
                    if summary_returned
                    else "not_requested"
                    if not summary_requested
                    else "not_returned"
                    if status == "completed"
                    else "interrupted"
                )
                record(
                    "api_end",
                    status=status,
                    summary_status=summary_status,
                    elapsed_seconds=time.monotonic() - started,
                    **({"usage": usage} if usage is not None else {}),
                )
                try:
                    record_request(
                        store,
                        task if count_for_task else None,
                        stage,
                        provider_id,
                        model
                        or (
                            provider.get_model()
                            if hasattr(provider, "get_model")
                            else "未提供"
                        ),
                        usage,
                    )
                except (sqlite3.Error, OSError, TypeError, ValueError) as exc:
                    record("api_usage_error", error=str(exc))
                    raise UsageWriteError(f"保存模型用量失败：{exc}") from exc
                logger.info(
                    "MCAI API %s task=%s request=%s stage=%s",
                    status,
                    task,
                    identity,
                    stage,
                )

            record(
                "api_request",
                transport=transport,
                provider=provider_id,
                parameters=kwargs,
            )
            logger.info(
                "MCAI API request task=%s request=%s stage=%s traces=%s",
                task,
                identity,
                stage,
                store.directory / "traces",
            )
            try:
                result = await create(**kwargs)
            except asyncio.CancelledError:
                finish("cancelled")
                raise
            except Exception as exc:
                record(
                    "api_error",
                    error=f"{type(exc).__name__}: {exc}",
                    status_code=getattr(exc, "status_code", None),
                )
                finish("failed")
                raise
            if kwargs.get("stream"):
                return TraceStream(result, record, finish)
            record("api_response", data=result)
            if hasattr(result, "status"):
                status = result.status or "incomplete"
            else:
                status = (
                    "incomplete"
                    if any(
                        choice.finish_reason
                        not in ("stop", "tool_calls", "function_call")
                        for choice in getattr(result, "choices", [])
                    )
                    else "completed"
                )
            finish(status)
            return result

        return call

    return wrap


def traced_provider(provider, store, task, stage, *, count_for_task=True):
    """Observe the SDK create boundary on a private provider/client copy."""
    selected = copy.copy(provider)
    selected.provider_config = copy.deepcopy(provider.provider_config)
    wrap = trace_calls(provider, store, task, stage, count_for_task=count_for_task)
    kind = selected.provider_config.get("type")
    if kind in ("openai_responses", "openai_chat_completion") and hasattr(
        provider, "client"
    ):
        client = provider.client.with_options(max_retries=0)
        if kind == "openai_responses":
            create = client.responses.create
            client.responses = SimpleNamespace(create=wrap(create, "responses"))
        else:
            create = client.chat.completions.create
            client.chat = SimpleNamespace(
                completions=SimpleNamespace(create=wrap(create, "chat"))
            )
        selected.client = client
    else:
        # Non-SDK providers expose their normalized request/response boundary.
        selected.text_chat = wrap(provider.text_chat, "provider")
    return selected


TRACE_MERGE_FAN_IN = 16


def sort_event_run(path):
    # Only clock reversals need a sort; keep the spool and sort storage on disk.
    with closing(sqlite3.connect(path.with_suffix(".sqlite3"))) as db:
        db.execute("PRAGMA temp_store=FILE")
        db.execute("CREATE TABLE events (stamp, line TEXT)")
        with path.open(encoding="utf-8") as stream, db:
            db.executemany(
                "INSERT INTO events VALUES (?, ?)",
                ((json.loads(line)["time"], line) for line in stream),
            )
        with path.open("w", encoding="utf-8", newline="\n") as stream:
            for (line,) in db.execute("SELECT line FROM events ORDER BY stamp, rowid"):
                stream.write(line)


def merge_event_runs(paths):
    with ExitStack() as stack:
        streams = [stack.enter_context(path.open(encoding="utf-8")) for path in paths]
        yield from merge(*streams, key=lambda line: json.loads(line)["time"])


def event_runs(
    directory, staging, start, end, requested, tasks, selected, *, paths=None
):
    if paths is not None:
        return filter_event_runs(
            directory, staging, start, end, requested, tasks, selected, paths, {}
        )
    with diagnostic_sources(directory, start, end) as monthly:
        paths = [
            *monthly,
            *(
                path
                for path in sorted((directory / "traces").glob("*.jsonl"))
                if path.name != "unassigned.jsonl"
            ),
        ]
        return filter_event_runs(
            directory, staging, start, end, requested, tasks, selected, paths, monthly
        )


def filter_event_runs(
    directory, staging, start, end, requested, tasks, selected, paths, monthly
):
    runs, reordered, entries = [], [], 0
    for index, path in enumerate(paths):
        if path not in monthly and not path.exists():
            continue
        run = staging / f"events-{index}.jsonl"
        previous, ordered, count, line_number = -math.inf, True, 0, 0
        with (
            ExitStack() as stack,
            run.open("w", encoding="utf-8", newline="\n") as filtered,
        ):
            if path in monthly:
                stream, remaining = monthly[path]
            else:
                stream = stack.enter_context(path.open("rb"))
                remaining = os.fstat(stream.fileno()).st_size
            while remaining != 0 and (
                line := stream.readline(-1 if remaining is None else remaining)
            ):
                if remaining is not None:
                    remaining -= len(line)
                line_number += 1
                try:
                    row = json.loads(line)
                except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                    raise ValueError(
                        f"诊断日志 {path.relative_to(directory)} 第 {line_number} 行不是完整 JSON，请重试或检查源文件"
                    ) from exc
                stamp, task = row["time"], row.get("task")
                ordered &= stamp >= previous
                previous = stamp
                if start <= stamp <= end and (
                    not requested or task in requested or task is None
                ):
                    filtered.write(json.dumps(row, ensure_ascii=False) + "\n")
                    count += 1
                    if not requested and task in tasks:
                        selected.add(task)
        if not ordered:
            reordered.append(path.relative_to(directory).as_posix())
            if count > 1:
                sort_event_run(run)
        if count:
            runs.append(run)
            entries += count
    generation = 0
    while len(runs) > TRACE_MERGE_FAN_IN:
        next_runs = []
        for index, batch in enumerate(batched(runs, TRACE_MERGE_FAN_IN)):
            run = staging / f"merge-{generation}-{index}.jsonl"
            with run.open("w", encoding="utf-8", newline="\n") as stream:
                stream.writelines(merge_event_runs(batch))
            next_runs.append(run)
            for previous_run in batch:
                previous_run.unlink()
        runs = next_runs
        generation += 1
    return runs, entries, reordered


def diagnostic_records(store, kind, selected):
    if kind == "task":
        yield from store.task_records(selected=selected)
    elif kind == "context":
        for task in selected:
            for seq, body in store.db.execute(
                "SELECT seq, body FROM events WHERE topic=? ORDER BY seq",
                ("context:" + task,),
            ):
                yield {"task": task, "seq": seq, "body": json.loads(body)}
    else:
        for (body,) in store.db.execute(
            "SELECT body FROM records WHERE kind=? ORDER BY rowid", (kind,)
        ):
            row = json.loads(body)
            if row.get("task") in selected:
                yield row


def write_diagnostic_records(archive, groups):
    with archive.open("records.json", "w", force_zip64=True) as stream:
        stream.write(b"{")
        for index, (kind, rows) in enumerate(groups):
            if index:
                stream.write(b",")
            stream.write(f'\n  "{kind}": ['.encode())
            separator = b"\n"
            for row in rows:
                stream.write(separator)
                body = json.dumps(row, ensure_ascii=False, indent=2)
                stream.write(("    " + body.replace("\n", "\n    ")).encode())
                separator = b",\n"
            stream.write(b"\n  ]" if separator == b",\n" else b"]")
        stream.write(b"\n}")


def write_archive(archive, staging, manifest, runs, groups):
    archive.writestr(
        "manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2)
    )
    timeline = staging / "timeline.md"
    with (
        archive.open("events.jsonl", "w", force_zip64=True) as events,
        timeline.open("w", encoding="utf-8", newline="\n") as markdown,
    ):
        markdown.write(
            "# MCAI 交互时间线\n\n完整内容见 events.jsonl 和 records.json。\n\n"
        )
        for line in merge_event_runs(runs):
            events.write(line.encode())
            row = json.loads(line)
            stamp = time.strftime("%Y-%m-%d %H:%M:%S %z", time.localtime(row["time"]))
            markdown.write(
                f"- {stamp} | {row.get('task') or '未关联任务'} | {row.get('kind', row.get('topic', ''))} | {row.get('stage', '')} {row.get('request_id', '')}\n"
            )
    write_diagnostic_records(archive, groups)
    archive.write(timeline, "timeline.md")


def export_cleanup(directory, output, task_id, items):
    from .cleanup import REPREVIEW, checked_path, public_items

    trace_paths = [
        checked_path(item["file"][0], item["file"][1])
        for item in items
        if item["kind"] == "traces"
    ]
    records = {
        kind: [item for item in items if item["kind"] == kind]
        for kind in ("web_page", "outbox")
    }
    path = (
        output
        / f"mcai-archive-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}.zip"
    )
    output.mkdir(exist_ok=True)
    end = time.time()
    with (
        closing(Store(directory, read_only=True)) as reader,
        TemporaryDirectory(prefix=".archive-", dir=output) as temporary,
    ):
        staging = Path(temporary)
        selected = {task_id}
        runs, entries, _ = event_runs(
            directory,
            staging,
            -math.inf,
            math.inf,
            set(),
            selected,
            set(),
            paths=trace_paths,
        )
        manifest = {
            "version": PRODUCT_VERSION,
            "protocol": PROTOCOL,
            "start": None,
            "end": end,
            "tasks": [task_id],
            "entries": entries,
            "type": "task_cleanup",
            "rules": rules_status(reader),
            "items": public_items(items),
            "limitations": ["仅归档本次选择清理的 A 端留痕与记录。"],
        }

        def selected_rows(kind):
            for item in records[kind]:
                row = reader.db.execute(
                    "SELECT body FROM records WHERE kind=? AND id=?",
                    (kind, item["id"]),
                ).fetchone()
                if (
                    row is None
                    or hashlib.sha256(row[0].encode()).hexdigest() != item["version"]
                ):
                    raise ValueError(REPREVIEW)
                yield json.loads(row[0])

        zip_path = staging / path.name
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
            write_archive(
                archive,
                staging,
                manifest,
                runs,
                ((kind, selected_rows(kind)) for kind in records),
            )
        zip_path.rename(path)
    return str(path)


def export_diagnostics(store, *, start=0, end=None, task_ids=None):
    end = time.time() if end is None else end
    if not math.isfinite(start) or not math.isfinite(end) or start > end:
        raise ValueError("开始时间不能晚于结束时间")
    if task_ids is not None and (
        not isinstance(task_ids, list)
        or any(not isinstance(key, str) for key in task_ids)
    ):
        raise ValueError("任务编号须为字符串列表")
    requested = set(task_ids or [])
    output = store.directory / "exports"
    output.mkdir(exist_ok=True)
    path = (
        output
        / f"mcai-diagnostics-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}.zip"
    )
    with (
        closing(Store(store.directory, read_only=True)) as reader,
        TemporaryDirectory(prefix=".diagnostics-", dir=output) as temporary,
    ):
        tasks = {
            key
            for (key,) in reader.db.execute("SELECT id FROM records WHERE kind='task'")
        }
        questions = {
            row[0]
            for row in reader.db.execute("SELECT id FROM records WHERE kind='ask'")
        }
        if requested - tasks - questions:
            raise ValueError("所选任务或问答不存在")
        selected = set(requested)
        staging = Path(temporary)
        runs, entries, reordered = event_runs(
            store.directory, staging, start, end, requested, tasks | questions, selected
        )
        manifest = {
            "version": PRODUCT_VERSION,
            "protocol": PROTOCOL,
            "start": start,
            "end": end,
            "tasks": sorted(selected & tasks),
            "entries": entries,
            "rules": rules_status(reader),
            "limitations": [
                "仅含本地已保存的记录；旧版未记录的请求、API未返回的推理和未取得的B端结果无法补回。",
                "不含完整配置、数据库、存档、备份及连续控制台日志。",
            ],
        }
        if selected & questions:
            manifest["questions"] = sorted(selected & questions)
        zip_path = staging / path.name
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
            write_archive(
                archive,
                staging,
                manifest,
                runs,
                (
                    (kind, diagnostic_records(reader, kind, selected))
                    for kind in ("task", "tool_call", "review", "outbox", "context")
                ),
            )
            for name in manifest["rules"]:
                rules = store.directory / name
                if rules.exists():
                    archive.write(rules, f"rules/{name}")
        zip_path.rename(path)
    return {
        "filename": path.name,
        "path": str(path),
        "entries": entries,
        "tasks": len(selected),
        **({"reordered_files": reordered} if reordered else {}),
    }
