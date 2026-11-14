"""AstrBot plugin view APIs; all B access uses the existing authenticated client."""

import asyncio
import json

from astrbot.api.web import error_response, file_response, json_response, request

from .astrbot_agent import AstrBotAgent
from .capabilities import detected_settings, provider_identity, test_capabilities
from .client import HostClient, RemoteError
from .tracing import export_diagnostics


class Settings:
    def __init__(self, plugin, rules_path):
        self.plugin, self.rules_path = plugin, rules_path
        self.worker = None
        self.result = plugin.store.get("capability_test", "latest")
        for route, handler, methods in (
            ("settings", self.settings, ["GET", "POST"]),
            ("connection/test", self.connection_test, ["POST"]),
            ("host", self.host, ["GET", "POST"]),
            ("host/curseforge/test", self.curseforge, ["POST"]),
            ("capabilities", self.capabilities, ["GET", "POST"]),
            ("capabilities/cancel", self.cancel_capabilities, ["POST"]),
            ("diagnostics", self.diagnostics, ["GET", "POST"]),
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
            try:
                return json_response(await callback())
            except TimeoutError:
                self.plugin.store.log(
                    "settings_error",
                    endpoint=callback.__name__,
                    error="request timeout",
                )
                return error_response("请求超时，请检查 B 是否在线、地址和网络连接")
            except (ValueError, KeyError, OSError, RemoteError) as exc:
                self.plugin.store.log(
                    "settings_error", endpoint=callback.__name__, error=str(exc)
                )
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

    async def diagnostics(self):
        if request.method == "GET":
            return {
                "tasks": [
                    {
                        key: item[key]
                        for key in ("id", "name", "group", "created", "state")
                    }
                    for item in self.plugin.store.all("task")
                ]
            }
        body = await request.json()
        result = export_diagnostics(
            self.plugin.store,
            start=float(body.get("start", 0)),
            end=float(body["end"]) if body.get("end") is not None else None,
            task_ids=body.get("task_ids"),
        )
        return result

    async def diagnostic_file(self):
        from pathlib import Path

        filename = request.args.get("filename", "")
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
            from pathlib import Path

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
            for key in ("provider_id", "review_provider_id"):
                if fields.get(key):
                    await self.provider(fields[key])
            if (
                not 1
                <= fields.get(
                    "model_max_attempts", plugin.config.get("model_max_attempts", 3)
                )
                <= 10
                or not 1
                <= fields.get("max_steps", plugin.config.get("max_steps", 40))
                <= 200
            ):
                raise ValueError("重试次数为 1–10，模型步数为 1–200")
            if (
                plugin.tasks.workers
                or plugin.tasks.archive_workers
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
                review_provider_id=config.get("review_provider_id", ""),
                review_reasoning_effort=config.get("review_reasoning_effort", ""),
                reasoning_effort=config.get("reasoning_effort", ""),
                model_max_attempts=config.get("model_max_attempts", 3),
                forward_reasoning_summary=config.get(
                    "forward_reasoning_summary", False
                ),
                forward_reasoning_summary_body=config.get(
                    "forward_reasoning_summary_body", False
                ),
                reasoning_summary=config.get("reasoning_summary", "auto"),
                enable_web_search=config.get("enable_web_search", True),
                web_search_tool_type=config.get("web_search_tool_type", "web_search"),
                enable_alpha_search=config.get("enable_alpha_search", False),
            )
            await plugin.config.save_config_async(fields)
            await plugin.tasks.client.close()
            plugin.tasks.client, plugin.tasks.agent = client, agent
            return {"saved": True}
        providers = plugin.context.get_all_providers()
        return {
            "config": {
                key: value
                for key, value in plugin.config.items()
                if key != "host_token"
            },
            "host_token_configured": bool(plugin.config.get("host_token")),
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
            return await self.plugin.tasks.client.request(
                "POST", "/configuration/test-curseforge"
            )

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
                        "reasoning_summary",
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
                "reasoning_summary",
            )
        }
        main = await self.provider(settings["provider_id"])
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
                agent.forward_summary = self.plugin.config.get(
                    "forward_reasoning_summary", False
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
        if self.worker and not self.worker.done():
            self.worker.cancel()
            await asyncio.gather(self.worker, return_exceptions=True)
