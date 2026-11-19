"""Task-local API traces and portable diagnostics, independent of group output."""

import asyncio
import copy
import json
import logging
import math
import time
import uuid
import zipfile
from dataclasses import fields, is_dataclass
from types import SimpleNamespace

from .protocol import PRODUCT_VERSION, PROTOCOL

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
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(json_value(entry), ensure_ascii=False) + "\n")
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


def traced_provider(provider, store, task, stage):
    """Observe the SDK create boundary on a private provider/client copy."""
    selected = copy.copy(provider)
    selected.provider_config = copy.deepcopy(provider.provider_config)

    def wrap(create, transport):
        async def call(**kwargs):
            identity, started = uuid.uuid4().hex, time.monotonic()
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
                nonlocal summary_returned
                if "error" in fields:
                    for key in keys:
                        if key:
                            fields["error"] = fields["error"].replace(key, "[redacted]")
                try:
                    if kind in ("api_chunk", "api_response"):
                        data = fields["data"] = json_value(fields["data"])
                        response = data.get("response") or data
                        summary_returned = (
                            summary_returned
                            or bool(
                                data.get("type", "").startswith(
                                    "response.reasoning_summary_text."
                                )
                                and (data.get("delta") or data.get("text"))
                            )
                            or any(
                                part.get("text")
                                for item in response.get("output", [])
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
                )
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
                provider=provider.provider_config.get("id"),
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
    tasks = {item["id"]: item for item in store.all("task")}
    if requested - tasks.keys():
        raise ValueError("所选任务不存在")
    entries = []
    paths = [
        store.directory / "audit.jsonl",
        *sorted((store.directory / "traces").glob("*.jsonl")),
    ]
    for path in paths:
        if not path.exists():
            continue
        with path.open(encoding="utf-8") as stream:
            for line in stream:
                row = json.loads(line)
                if start <= row["time"] <= end and (
                    not requested
                    or row.get("task") in requested
                    or row.get("task") is None
                ):
                    entries.append(row)
    entries.sort(key=lambda row: row["time"])
    selected = requested or {row["task"] for row in entries if row.get("task") in tasks}
    records = {
        kind: [
            row
            for row in store.all(kind)
            if row.get("task") in selected or (kind == "task" and row["id"] in selected)
        ]
        for kind in ("task", "tool_call", "review", "outbox")
    }
    records["context"] = []
    for task in selected:
        cursor = 0
        while page := store.events("context:" + task, cursor):
            records["context"].extend({"task": task, **row} for row in page)
            cursor = page[-1]["seq"]
    output = store.directory / "exports"
    output.mkdir(exist_ok=True)
    path = (
        output
        / f"mcai-diagnostics-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}.zip"
    )
    manifest = {
        "version": PRODUCT_VERSION,
        "protocol": PROTOCOL,
        "start": start,
        "end": end,
        "tasks": sorted(selected),
        "entries": len(entries),
        "limitations": [
            "仅含本地已保存的记录；旧版未记录的请求、API未返回的推理和未取得的B端结果无法补回。",
            "不含完整配置、数据库、存档、备份及连续控制台日志。",
        ],
    }
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2)
        )
        archive.writestr(
            "events.jsonl",
            "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in entries),
        )
        archive.writestr(
            "records.json", json.dumps(records, ensure_ascii=False, indent=2)
        )
        timeline = [
            "# MCAI 交互时间线",
            "",
            "完整内容见 events.jsonl 和 records.json。",
            "",
        ]
        for row in entries:
            stamp = time.strftime("%Y-%m-%d %H:%M:%S %z", time.localtime(row["time"]))
            timeline.append(
                f"- {stamp} | {row.get('task') or '未关联任务'} | {row.get('kind', row.get('topic', ''))} | {row.get('stage', '')} {row.get('request_id', '')}"
            )
        archive.writestr("timeline.md", "\n".join(timeline) + "\n")
        for name in ("AGENTS.md", "REVIEW_AGENTS.md", "SUMMARY_AGENTS.md"):
            rules = store.directory / name
            if rules.exists():
                archive.write(rules, f"rules/{name}")
    return {
        "filename": path.name,
        "path": str(path),
        "entries": len(entries),
        "tasks": len(selected),
    }
