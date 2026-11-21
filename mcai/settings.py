"""AstrBot plugin view APIs; all B access uses the existing authenticated client."""

import asyncio
import json
import time
from contextlib import AsyncExitStack
from pathlib import Path

import aiohttp
from astrbot.api.web import error_response, file_response, json_response, request

from .astrbot_agent import AstrBotAgent
from .capabilities import detected_settings, provider_identity, test_capabilities
from .cleanup import (
    A_CATEGORIES,
    B_CATEGORIES,
    REPREVIEW,
    a_plan,
    a_protection,
    checked_path,
    clean,
    cleanup_categories,
    cleanup_scope,
    compact_database,
    confirm_cleanup,
    delete_log_archives,
    public_items,
    settled,
)
from .client import HostClient, RemoteError
from .configuration import incident_routes, powershell_path
from .model_usage import parse_prices, usage_report
from .monthly_logs import A_LOGS, archive_list
from .paths import workspace_root
from .review import digest
from .runtime_rules import change_rule, rules_status
from .storage_usage import STORAGE_TIMEOUT, a_storage
from .tracing import export_cleanup, export_diagnostics


class Settings:
    def __init__(self, plugin, rules_path, review_rules_path, summary_rules_path):
        self.plugin = plugin
        self.rules_path = rules_path
        self.review_rules_path = review_rules_path
        self.summary_rules_path = summary_rules_path
        self.worker = None
        self.retention_worker = asyncio.create_task(self.retention_loop())
        self.result = plugin.store.get("capability_test", "latest")
        for route, handler, methods in (
            ("settings", self.settings, ["GET", "POST"]),
            ("connection/test", self.connection_test, ["POST"]),
            ("host", self.host, ["GET", "POST"]),
            ("host/curseforge/test", self.curseforge, ["POST"]),
            ("capabilities", self.capabilities, ["GET", "POST"]),
            ("capabilities/cancel", self.cancel_capabilities, ["POST"]),
            ("rules", self.rules, ["GET", "POST"]),
            ("storage", self.storage, ["GET"]),
            ("storage/host", self.host_storage, ["GET"]),
            ("storage/cleanup", self.cleanup, ["GET", "POST"]),
            ("storage/vacuum", self.vacuum, ["POST"]),
            ("storage/logs", self.logs, ["GET", "POST"]),
            ("diagnostics", self.diagnostics, ["GET", "POST"]),
            ("diagnostics/outbox", self.outbox, ["POST"]),
            ("model/usage", self.model_usage, ["GET"]),
        ):
            plugin.context.register_web_api(
                "/astrbot_plugin_mcai/" + route,
                self.handler(handler),
                methods,
                "MCAI 设置与诊断",
            )
        plugin.context.register_web_api(
            "/astrbot_plugin_mcai/diagnostics/file",
            self.diagnostic_file,
            ["GET"],
            "MCAI 诊断下载",
        )

    def handler(self, callback):
        async def call():
            audit = {"endpoint": callback.__name__}
            try:
                result = await (
                    callback(audit) if callback == self.cleanup else callback()
                )
                return json_response(result)
            except TimeoutError:
                self.plugin.store.log(
                    "settings_error",
                    error="request timeout",
                    **audit,
                )
                return error_response("请求超时，请检查 B 是否在线、地址和网络连接")
            except (ValueError, KeyError, OSError, RemoteError) as exc:
                self.plugin.store.log("settings_error", error=str(exc), **audit)
                return error_response(str(exc))

        return call

    async def provider(self, identity):
        if not identity:
            raise ValueError("请在插件设置页选择明确的模型提供商")
        provider = await self.plugin.context.provider_manager.get_provider_by_id(
            identity
        )
        if provider is None:
            raise ValueError(f"模型提供商不存在：{identity}")
        return provider

    async def rules(self):
        store = self.plugin.store
        if request.method == "GET":
            return rules_status(store)
        body = await request.json()
        if not isinstance(body, dict) or not isinstance(body.get("name"), str):
            raise ValueError("请选择要操作的运行时规则文件")
        return change_rule(
            store,
            body["name"],
            body.get("action"),
            body.get("template_sha256"),
            body.get("file_sha256"),
        )

    async def storage(self):
        try:
            async with asyncio.timeout(STORAGE_TIMEOUT):
                return await asyncio.to_thread(
                    a_storage,
                    self.plugin.store.directory,
                    self.plugin.tasks.workspace.root,
                )
        except TimeoutError as exc:
            raise ValueError("A 端数据占用统计超时") from exc

    async def host_storage(self):
        async with asyncio.timeout(STORAGE_TIMEOUT):
            return await self.plugin.tasks.client.request("GET", "/storage")

    async def vacuum(self):
        tasks = self.plugin.tasks
        side = (await request.json()).get("side")
        sender = request.username
        if not sender or side not in ("a", "b"):
            raise ValueError("请登录设置页并选择需要压缩的数据库")
        if side == "b":
            return await self.maintenance_request(
                "POST",
                "/storage/vacuum",
                json={"sender": sender},
                timeout=aiohttp.ClientTimeout(total=300, connect=10),
            )
        if (
            tasks.workers
            or tasks.archive_workers
            or tasks.local_jobs.workers
            or tasks.reference_lock.locked()
            or self.plugin.ask_workers
            or (self.worker and not self.worker.done())
        ):
            raise ValueError(
                "A 端仍有任务、归档、后台工作、问答、清理或能力测试，请等待后压缩"
            )
        return compact_database(self.plugin.store, sender)

    async def logs(self):
        store = self.plugin.store
        if request.method == "GET":
            side = request.query.get("side")
            if side == "a":
                return {"archives": archive_list(store.directory, A_LOGS)}
            if side == "b":
                return await self.maintenance_request("GET", "/storage/logs")
            raise ValueError("请选择 A 或 B 的日志归档")
        body = await request.json()
        sender, side = request.username, body.get("side")
        if not sender or side not in ("a", "b"):
            raise ValueError("请登录设置页并选择 A 或 B 的日志归档")
        if side == "b":
            return await self.maintenance_request(
                "POST", "/storage/logs", json={**body, "sender": sender}
            )
        return delete_log_archives(store, A_LOGS, sender, body)

    async def maintenance_request(self, method, path, **kwargs):
        try:
            return await self.plugin.tasks.client.request(
                method, path, once=True, **kwargs
            )
        except aiohttp.ClientError as exc:
            raise ValueError("未收到 B 的维护响应，请检查连接及 B 审计日志") from exc

    async def cleanup(self, audit):
        store = self.plugin.store
        if request.method == "GET":
            return {
                "tasks": [
                    {field: row[field] for field in ("id", "name", "group", "state")}
                    for row in store.all("task")
                    if settled(row)
                ],
            }

        sender = request.username
        audit["sender"] = sender
        body = await request.json()
        if isinstance(body, dict):
            audit.update(task=body.get("task_id"), action=body.get("action"))
        action = body.get("action") if isinstance(body, dict) else None
        if not sender or action not in ("preview", "execute"):
            raise ValueError("请登录设置页，先预览再确认清理")
        if "days" in body:
            audit["days"] = body["days"]
            return await self.cleanup_batch(body, sender)
        return await self.cleanup_task(body, sender)

    async def cleanup_task(self, body, sender):
        tasks, store = self.plugin.tasks, self.plugin.store
        key, categories = cleanup_scope(body, A_CATEGORIES | B_CATEGORIES)
        action = body["action"]
        local = A_CATEGORIES.intersection(categories)
        remote = sorted(B_CATEGORIES.intersection(categories))
        request_body = {"task_id": key, "categories": remote, "sender": sender}

        async def host_cleanup(action, **fields):
            try:
                return await client.request(
                    "POST",
                    "/storage/cleanup",
                    once=True,
                    json={**request_body, "action": action, **fields},
                )
            except (aiohttp.ClientError, TimeoutError) as exc:
                raise ValueError(
                    "未收到 B 的清理响应，请检查连接和 B 审计日志后重新预览"
                ) from exc
            except RemoteError as exc:
                if body["action"] == "execute" and action == "preview":
                    raise ValueError(f"{REPREVIEW}：{exc}") from exc
                raise

        async with tasks.reference_lock, AsyncExitStack() as stack:
            workspace = tasks.workspace.root
            if remote:
                # Settings saves can replace and close the shared client mid-cleanup.
                current_client = tasks.client
                client = HostClient(
                    current_client.url, current_client.token, current_client.fingerprint
                )
                stack.push_async_callback(client.close)

            def protection():
                try:
                    return a_protection(store, key)
                except ValueError as exc:
                    if action == "execute":
                        raise ValueError(f"{REPREVIEW}：{exc}") from exc
                    raise

            if remote:
                settled_ids = protection()[3]
                b = await host_cleanup(
                    "preview",
                    settled_tasks=settled_ids if "backups" in remote else [key],
                )
            else:
                b = {"items": [], "token": None}

            def current():
                task, server_dirs, protected, settled_ids = protection()
                try:
                    items, state = a_plan(store, workspace, task, server_dirs, local)
                    if conflict := protected.intersection(
                        item["id"] for item in [*items, *b["items"]]
                    ):
                        raise ValueError(
                            "数据仍被未结算操作、待恢复审核或多轮方案引用："
                            + "、".join(sorted(conflict))
                        )
                    token = digest(
                        {
                            "task": key,
                            "sender": sender,
                            "categories": categories,
                            "state": state,
                            "a": items,
                            "b": b["token"],
                            "host": [client.url, client.fingerprint]
                            if remote
                            else None,
                        }
                    )
                    return items, token, settled_ids
                except ValueError as exc:
                    if action == "execute":
                        raise ValueError(f"{REPREVIEW}：{exc}") from exc
                    raise

            items, token, settled_ids = current()
            if action == "preview":
                return {"a": public_items(items), "b": b["items"], "token": token}
            confirm_cleanup(body, token, categories)
            if not items and not b["items"]:
                raise ValueError("没有可清理的数据，请重新预览")

            archive = None
            if any(item["kind"] != "workspace" for item in items):
                archive = await asyncio.to_thread(
                    export_cleanup,
                    store.directory,
                    checked_path(store.directory, "exports"),
                    key,
                    items,
                )
                items, token, settled_ids = current()
                confirm_cleanup(body, token, categories)
            b_result = None
            if b["items"]:
                b_result = await host_cleanup(
                    "execute",
                    token=b["token"],
                    confirm_backups=body.get("confirm_backups"),
                    settled_tasks=settled_ids if "backups" in remote else [key],
                )
            try:
                if b_result is not None:
                    items, token, _ = current()
                    confirm_cleanup(body, token, categories)
                a = clean(store, key, sender, items, archive=archive)
            except (OSError, ValueError) as exc:
                if b_result is not None:
                    raise ValueError(f"B 端已执行清理；A 端未完成：{exc}") from exc
                raise
            return {"a": a, "b": b_result["items"] if b_result else []}

    async def cleanup_batch(self, body, sender, *, automatic=False):
        store = self.plugin.store
        days = body["days"]
        if type(days) is not int or days <= 0:
            raise ValueError("清理天数必须是正整数")
        categories = cleanup_categories(
            body.get("categories"),
            (A_CATEGORIES | B_CATEGORIES) - ({"backups"} if automatic else set()),
        )
        cutoff = time.time() - days * 86400
        tasks, skipped, entries = [], [], []
        for task in store.all("task"):
            ended = task.get("settled_at")
            if (ended if ended is not None else task.get("created", 0)) >= cutoff:
                continue
            info = {"id": task["id"], "name": task["name"], "settled_at": ended}
            if not settled(task):
                skipped.append({**info, "reason": "任务未结算"})
                continue
            if ended is None:
                skipped.append({**info, "reason": "旧任务没有结算时间，请单独清理"})
                continue
            scope = {"task_id": task["id"], "categories": categories}
            try:
                preview = await self.cleanup_task(
                    {**scope, "action": "preview"}, sender
                )
            except (OSError, RemoteError, ValueError) as exc:
                skipped.append({**info, "reason": str(exc)})
                continue
            items = preview["a"] + preview["b"]
            if not items:
                skipped.append({**info, "reason": "没有可清理的数据"})
                continue
            totals, records = {}, {}
            for item in items:
                kind = item["kind"]
                totals[kind] = totals.get(kind, 0) + item["bytes"]
                if "records" in item:
                    count = records.setdefault(kind, {"count": 0, "bytes": 0})
                    count["count"] += item["records"]
                    count["bytes"] += item["record_bytes"]
            tasks.append({**info, "categories": totals, "records": records})
            entries.append((scope, preview["token"]))
        token = digest(
            {
                "sender": sender,
                "days": days,
                "categories": categories,
                "entries": entries,
                "tasks": tasks,
                "skipped": skipped,
            }
        )
        if not automatic and body["action"] == "preview":
            return {"tasks": tasks, "skipped": skipped, "token": token}
        if not automatic:
            confirm_cleanup(body, token, categories)
        completed, failed = [], []
        for row, (scope, task_token) in zip(tasks, entries, strict=True):
            try:
                result = await self.cleanup_task(
                    {
                        **scope,
                        "action": "execute",
                        "token": task_token,
                        "confirm_backups": body.get("confirm_backups"),
                    },
                    sender,
                )
            except (OSError, RemoteError, ValueError) as exc:
                failed.append({**row, "reason": str(exc)})
            else:
                completed.append(
                    {
                        **row,
                        "bytes": result["a"]["bytes"]
                        + sum(item["bytes"] for item in result["b"]),
                    }
                )
        return {"completed": completed, "skipped": skipped, "failed": failed}

    async def retain_tasks(self):
        days = self.plugin.config.get("auto_cleanup_days", 0)
        if days <= 0:
            return
        store = self.plugin.store
        day = time.strftime("%Y-%m-%d")
        if store.get("retention", "last_day") == day:
            return
        store.save("retention", "last_day", day)
        store.log("retention_cleanup_started", day=day, days=days)
        result = await self.cleanup_batch(
            {
                "days": days,
                "categories": sorted((A_CATEGORIES | B_CATEGORIES) - {"backups"}),
            },
            "自动保留期限",
            automatic=True,
        )
        store.log("retention_cleanup_completed", day=day, days=days, **result)

    async def retention_loop(self):
        while True:
            await asyncio.sleep(60)
            try:
                await self.retain_tasks()
            except (OSError, RemoteError, ValueError) as exc:
                self.plugin.store.log("retention_cleanup_failed", error=str(exc))

    async def diagnostics(self):
        if request.method == "GET":
            store = self.plugin.store
            tasks = store.all("task")
            questions = store.all("ask")
            task_names = {item["id"]: item["name"] for item in tasks}
            task_names.update({item["id"]: "只读问答" for item in questions})
            return {
                "outbox": {
                    **store.outbox_status(),
                    "items": [
                        {
                            "id": item["id"],
                            "task_name": task_names.get(item.get("task"), "故障通知"),
                            "origin": item["origin"],
                            "first_line": item["text"].partition("\n")[0],
                            "attempts": item.get(
                                "total_attempts", item.get("attempts", 0)
                            ),
                            "error": item.get("error"),
                            "retry_at": item.get("retry_at"),
                            "single_fault": item.get("single_fault", False),
                            "failed": item.get("failed", False),
                        }
                        for item in store.pending_outbox(limit=-1, include_failed=True)
                    ],
                },
                "tasks": [
                    {
                        key: item[key]
                        for key in ("id", "name", "group", "created", "state")
                    }
                    for item in tasks
                ],
                "questions": questions,
            }
        body = await request.json()
        result = await asyncio.to_thread(
            export_diagnostics,
            self.plugin.store,
            start=float(body.get("start", 0)),
            end=float(body["end"]) if body.get("end") is not None else None,
            task_ids=body.get("task_ids"),
        )
        return result

    async def outbox(self):
        body = await request.json()
        if not isinstance(body, dict):
            raise ValueError("发件箱请求须为 JSON 对象")
        key, action, sender = body.get("id"), body.get("action"), request.username
        if not sender or not isinstance(key, str) or action not in ("retry", "discard"):
            raise ValueError("请登录设置页并选择消息及操作")
        if action == "discard" and body.get("confirm") is not True:
            raise ValueError("请先确认丢弃该消息")
        store = self.plugin.store
        item = store.get("outbox", key)
        if not item or item["sent"]:
            raise ValueError("消息已结算或不存在，请刷新发件箱")
        if key in self.plugin.tasks.outbox_sending:
            raise ValueError("消息正在发送，请稍后重试操作")
        if action == "retry":
            item.pop("failed", None)
            item.pop("retry_at", None)
        else:
            item.update(sent=True, discarded=True)
        store.save("outbox", key, item)
        if action == "discard":
            store.log(
                "message_outbox_discarded",
                outbox=key,
                task=item.get("task"),
                sender=sender,
            )
        return {"ok": True}

    async def model_usage(self):
        return usage_report(
            self.plugin.store, parse_prices(self.plugin.config.get("model_prices", []))
        )

    async def diagnostic_file(self):
        filename = request.query.get("filename", "")
        if (
            Path(filename).name != filename
            or not filename.startswith("mcai-diagnostics-")
            or not filename.endswith(".zip")
        ):
            return error_response("诊断文件名无效")
        path = self.plugin.store.directory / "exports" / filename
        if not path.is_file():
            return error_response("诊断文件不存在")
        return file_response(path, filename=filename, content_type="application/zip")

    async def settings(self):
        plugin = self.plugin
        if request.method == "POST":
            body = await request.json()
            if not isinstance(body, dict):
                raise ValueError("配置请求必须是 JSON 对象")
            schema = json.loads(
                (Path(__file__).parents[1] / "_conf_schema.json").read_text(
                    encoding="utf-8"
                )
            )
            fields = {key: value for key, value in body.items() if key in schema}
            types = {"string": str, "int": int, "bool": bool, "list": list}
            for key, value in fields.items():
                if type(value) is not types[schema[key]["type"]]:
                    raise ValueError(f"{key} 类型不正确")
            if any(
                fields.get(key, 0) < 0
                for key in (
                    "task_token_limit",
                    "model_failure_pause_minutes",
                    "member_ask_cooldown_seconds",
                )
            ):
                raise ValueError(
                    "单任务 token 上限、自动暂停分钟数及问答冷却秒数不能小于 0"
                )
            if "model_prices" in fields:
                parse_prices(fields["model_prices"])
            if fields.get("host_offline_alert_minutes", 3) < 1:
                raise ValueError("B 失联告警分钟数至少为 1")
            if fields.get("auto_cleanup_days", 0) < 0:
                raise ValueError("自动清理天数不能小于 0")
            incident_routes(
                fields.get("incident_routes", plugin.config.get("incident_routes", [])),
                fields.get("group_ids", plugin.config.get("group_ids", [])),
            )
            if (
                "group_forward_threshold" in fields
                and fields["group_forward_threshold"] < 1
            ):
                raise ValueError("QQ 长回复合集门槛须为正整数")
            for key in ("provider_id", "review_provider_id"):
                if fields.get(key):
                    provider = await self.provider(fields[key])
                    if provider.provider_config.get("type") not in (
                        "openai_chat_completion",
                        "openai_responses",
                    ):
                        raise ValueError(
                            "排障与审核模型仅支持 OpenAI 兼容 Chat／Responses 提供商"
                        )
            async with plugin.tasks.create_lock:
                if (
                    not 1
                    <= fields.get("max_steps", plugin.config.get("max_steps", 40))
                    <= 200
                ):
                    raise ValueError("模型步数为 1–200")
                if (
                    plugin.tasks.workers
                    or plugin.tasks.archive_workers
                    or plugin.tasks.local_jobs.workers
                    or (self.worker and not self.worker.done())
                ):
                    raise ValueError(
                        "任务或能力测试正在运行，请暂停任务或等待操作完成后保存 A 配置"
                    )
                config = {**plugin.config, **fields}
                client = HostClient(
                    config["host_url"],
                    config["host_token"],
                    config.get("host_fingerprint", ""),
                )
                agent = AstrBotAgent(
                    plugin.context,
                    config.get("provider_id", ""),
                    config.get("max_steps", 40),
                    rules_path=self.rules_path,
                    review_rules_path=self.review_rules_path,
                    summary_rules_path=self.summary_rules_path,
                    review_provider_id=config.get("review_provider_id", ""),
                    review_reasoning_effort=config.get("review_reasoning_effort", ""),
                    reasoning_effort=config.get("reasoning_effort", ""),
                    forward_progress=config.get("forward_progress", False),
                    enable_web_search=config.get("enable_web_search", True),
                    web_search_tool_type=config.get(
                        "web_search_tool_type", "web_search"
                    ),
                    enable_alpha_search=config.get("enable_alpha_search", False),
                )
                workspace = workspace_root(config, plugin.store.directory)
                shell = config.get("workspace_powershell_path", "")
                if shell:
                    shell = str((plugin.store.directory / shell).resolve())
                shell = await asyncio.to_thread(powershell_path, shell)
                if not await plugin.config.save_config_async(fields):
                    raise ValueError("配置已被更新的保存请求替代，请重新读取设置")
                plugin.tasks.workspace.root = workspace
                plugin.tasks.workspace.powershell_path = shell
                if "curseforge_api_key" in fields:
                    plugin.tasks.downloads.config["curseforge_api_key"] = fields[
                        "curseforge_api_key"
                    ]
                await plugin.tasks.client.close()
                plugin.tasks.client, plugin.tasks.agent = client, agent
                plugin.tasks.task_token_limit = config.get("task_token_limit", 0)
                plugin.tasks.model_failure_pause_minutes = config.get(
                    "model_failure_pause_minutes", 0
                )
                return {"saved": True}
        providers = plugin.context.get_all_providers()
        return {
            "config": {
                key: value
                for key, value in plugin.config.items()
                if key not in ("host_token", "curseforge_api_key")
            },
            "host_token_configured": bool(plugin.config.get("host_token")),
            "curseforge_configured": bool(plugin.config.get("curseforge_api_key")),
            "providers": [
                {
                    "id": provider.provider_config["id"],
                    "name": provider.provider_config.get(
                        "name", provider.provider_config["id"]
                    ),
                    "model": provider.get_model(),
                    "type": provider.provider_config.get("type", ""),
                }
                for provider in providers
            ],
        }

    async def connection_test(self):
        body = await request.json()
        config = self.plugin.config
        client = HostClient(
            body.get("host_url", config["host_url"]),
            body.get("host_token") or config["host_token"],
            body.get("host_fingerprint", config.get("host_fingerprint", "")),
        )
        try:
            async with asyncio.timeout(15):
                instances = await client.request("GET", "/instances")
            return {"ok": True, "instances": len(instances)}
        finally:
            await client.close()

    async def host(self):
        async with asyncio.timeout(20):
            if request.method == "GET":
                return await self.plugin.tasks.client.request("GET", "/configuration")
            return await self.plugin.tasks.client.request(
                "PUT", "/configuration", json=await request.json()
            )

    async def curseforge(self):
        async with asyncio.timeout(100):
            result = await self.plugin.tasks.downloads.request(
                "https://api.curseforge.com/v1/games/432"
            )
            return {"ok": True, "game": result["data"]["name"]}

    async def cancel_capabilities(self):
        if self.worker and not self.worker.done():
            self.worker.cancel()
            await asyncio.gather(self.worker, return_exceptions=True)
        return {"cancelled": True}

    async def capabilities(self):
        if request.method == "GET":
            stale = False
            if self.result:
                main = await self.plugin.context.provider_manager.get_provider_by_id(
                    self.plugin.config.get("provider_id", "")
                )
                review = await self.plugin.context.provider_manager.get_provider_by_id(
                    self.plugin.config.get("review_provider_id", "")
                )
                settings = {
                    key: self.plugin.config.get(key, "")
                    for key in (
                        "provider_id",
                        "review_provider_id",
                        "reasoning_effort",
                        "review_reasoning_effort",
                    )
                }
                stale = (
                    main is None
                    or provider_identity(main, settings) != self.result.get("identity")
                    or (provider_identity(review, {}) if review is not None else None)
                    != self.result.get("review_identity")
                )
            return {
                "running": bool(self.worker and not self.worker.done()),
                "result": self.result,
                "stale": stale,
            }
        if self.worker and not self.worker.done():
            raise ValueError("能力测试已在运行")
        if self.plugin.tasks.workers:
            raise ValueError("请先暂停排障任务，再测试模型能力")
        settings = {
            key: self.plugin.config.get(key, "")
            for key in (
                "provider_id",
                "review_provider_id",
                "reasoning_effort",
                "review_reasoning_effort",
            )
        }
        main = await self.provider(settings["provider_id"])
        if main.provider_config.get("type") not in (
            "openai_chat_completion",
            "openai_responses",
        ):
            raise ValueError("排障模型仅支持 OpenAI 兼容 Chat／Responses 提供商")
        review = (
            await self.provider(settings["review_provider_id"])
            if settings["review_provider_id"]
            else None
        )

        def progress(result):
            self.result = result
            self.plugin.store.save("capability_test", "latest", result)

        async def run():
            try:
                result = await test_capabilities(
                    main, review, settings, progress, store=self.plugin.store
                )
                changes = detected_settings(result)
                await self.plugin.config.save_config_async(changes)
                agent = self.plugin.tasks.agent
                agent.enable_web_search = self.plugin.config.get(
                    "enable_web_search", True
                )
                agent.web_search_tool_type = self.plugin.config.get(
                    "web_search_tool_type", "web_search"
                )
                agent.enable_alpha_search = self.plugin.config.get(
                    "enable_alpha_search", False
                )
                agent.forward_progress = self.plugin.config.get(
                    "forward_progress", False
                )
                result["applied"] = changes
                progress(result)
            except asyncio.CancelledError:
                if self.result:
                    self.result["cancelled"] = True
                    progress(self.result)
                raise
            except Exception as exc:
                self.plugin.store.log("capability_test_error", error=str(exc))
                self.result = {
                    **(self.result or {}),
                    "error": str(exc),
                    "complete": True,
                }
                progress(self.result)

        self.result = None
        self.worker = asyncio.create_task(run())
        return {"started": True}

    async def close(self):
        self.retention_worker.cancel()
        await asyncio.gather(self.retention_worker, return_exceptions=True)
        if self.worker and not self.worker.done():
            self.worker.cancel()
            await asyncio.gather(self.worker, return_exceptions=True)
