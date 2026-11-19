"""Small, isolated provider capability probes. No production tools are exposed."""

import asyncio
import json
import re
import time
import uuid

from .agent_runtime import (
    effort_provider,
    request_provider,
    retryable,
)
from .review import digest
from .search import alpha_search
from .tracing import traced_provider


def provider_identity(provider, settings):
    config = provider.provider_config
    return digest(
        {
            "id": config["id"],
            "model": provider.get_model(),
            "config": config,
            "settings": settings,
        }
    )


async def test_capabilities(main, review, settings, progress, *, store=None):
    from astrbot.core.agent.tool import FunctionTool, ToolSet

    main = request_provider(main)
    if main.provider_config.get("type") in (
        "openai_responses",
        "openai_chat_completion",
    ):
        main.client = main.client.with_options(max_retries=0)
    if store is not None:
        main = traced_provider(main, store, None, "能力测试")
        if review is not None:
            review = traced_provider(review, store, None, "审核能力测试")

    result = {
        "created": time.time(),
        "identity": provider_identity(main, settings),
        "review_identity": provider_identity(review, {})
        if review is not None
        else None,
        "items": {},
        "settings": settings,
    }

    async def check(name, call):
        result["items"][name] = {"status": "testing"}
        progress(result)
        try:
            async with asyncio.timeout(60):
                value = await call()
            result["items"][name] = {"status": "passed" if value else "unobserved"}
            return value
        except Exception as exc:
            status = getattr(exc, "status_code", None)
            unsupported = (
                status in (400, 404, 405, 422)
                and not retryable(exc)
                and bool(
                    re.search(
                        r"unsupported|not supported|unknown (?:parameter|tool)|unrecognized|not found|method not allowed",
                        str(exc),
                        re.I,
                    )
                )
                and not bool(
                    re.search(
                        r"model.*(?:not found|does not exist)|invalid.*(?:key|token)",
                        str(exc),
                        re.I,
                    )
                )
            )
            message = str(exc)
            for provider in (main, review):
                if provider is not None:
                    keys = provider.provider_config.get("key", [])
                    for key in [keys] if isinstance(keys, str) else keys:
                        if key:
                            message = message.replace(key, "[密钥]")
            result["items"][name] = {
                "status": "unsupported" if unsupported else "failed",
                "error": message[:400],
            }
            return None
        finally:
            progress(result)

    selected = request_provider(
        effort_provider(main, settings.get("reasoning_effort", ""))
    )
    budget_field = (
        "max_output_tokens"
        if main.provider_config.get("type") == "openai_responses"
        else "max_completion_tokens"
    )
    selected.provider_config.setdefault("custom_extra_body", {})[budget_field] = 512

    async def conversation():
        response = await selected.text_chat(
            prompt="请只回复 MCAI_OK。",
            contexts=[],
            func_tool=None,
            request_max_retries=1,
        )
        return response.role != "err" and "MCAI_OK" in (response.completion_text or "")

    await check("conversation", conversation)

    async def streaming():
        complete = None
        async for response in selected.text_chat_stream(
            prompt="请只回复 MCAI_OK。",
            contexts=[],
            func_tool=None,
            request_max_retries=1,
        ):
            if not response.is_chunk:
                complete = response
        return (
            complete is not None
            and complete.role != "err"
            and bool(complete.completion_text)
        )

    await check("stream", streaming)

    async def function_call():
        class EchoTools(ToolSet):
            def openai_schema(self, *args, **kwargs):
                tools = super().openai_schema(*args, **kwargs)
                for tool in tools:
                    tool["function"]["strict"] = True
                return tools

        tools = EchoTools(
            [
                FunctionTool(
                    name="mcai_echo",
                    description="测试用回显，没有副作用",
                    parameters={
                        "type": "object",
                        "properties": {"text": {"type": "string"}},
                        "required": ["text"],
                        "additionalProperties": False,
                    },
                )
            ]
        )
        response = await selected.text_chat(
            prompt="调用 mcai_echo，text 填 MCAI_OK。",
            contexts=[],
            func_tool=tools,
            tool_choice="required",
            request_max_retries=1,
        )
        if response.tools_call_name != ["mcai_echo"] or response.tools_call_args != [
            {"text": "MCAI_OK"}
        ]:
            return False
        history = [
            {
                "role": "assistant",
                "content": response.completion_text or "",
                "tool_calls": [
                    item.model_dump(mode="json", exclude_none=True)
                    for item in response.to_openai_tool_calls_model()
                ],
            },
            {
                "role": "tool",
                "tool_call_id": response.tools_call_ids[0],
                "content": "MCAI_OK",
            },
        ]
        continued = await selected.text_chat(
            prompt="根据回显只回复 MCAI_OK。",
            contexts=history,
            func_tool=None,
            request_max_retries=1,
        )
        return continued.role != "err" and "MCAI_OK" in (
            continued.completion_text or ""
        )

    await check("function_call", function_call)
    if settings.get("reasoning_effort"):
        result["items"]["reasoning_effort"] = result["items"]["conversation"].copy()

    if main.provider_config.get("type") == "openai_responses":

        async def native_search(kind):
            response = await main.client.responses.create(
                model=main.get_model(),
                input="搜索 Minecraft 官方网站，返回官网名称和一个来源链接。",
                tools=[{"type": kind}],
                tool_choice="required",
                max_output_tokens=512,
            )
            return any(item.type == "web_search_call" for item in response.output)

        passed = await check("web_search", lambda: native_search("web_search"))
        if not passed and result["items"]["web_search"]["status"] == "unsupported":
            await check(
                "web_search_preview", lambda: native_search("web_search_preview")
            )

        async def progress_update():
            response = await selected.text_chat(
                prompt="先使用 assistant 的 commentary 阶段用一句简短中文说明正在核对计算，再计算 17*23，使用 final_answer 阶段报告结果。",
                contexts=[],
                func_tool=None,
                request_max_retries=1,
            )
            return any(
                item.type == "message"
                and getattr(item, "phase", None) == "commentary"
                and any(
                    part.type == "output_text" and part.text for part in item.content
                )
                for item in response.raw_completion.output
            )

        await check("progress", progress_update)
    else:
        result["items"]["web_search"] = {
            "status": "unsupported",
            "error": "托管搜索需要 Responses 提供商",
        }
        result["items"]["progress"] = {
            "status": "unsupported",
            "error": "commentary 执行进度汇报需要 Responses 提供商",
        }

    session_id = uuid.uuid4().hex
    search = await check(
        "alpha_search",
        lambda: alpha_search(
            main, session_id, {"mode": "search", "query": "Minecraft official website"}
        ),
    )
    if search:
        reference = next(
            (
                item.get("ref_id")
                for item in search.get("results", [])
                if item.get("ref_id")
            ),
            "https://www.minecraft.net/",
        )
        await check(
            "alpha_open",
            lambda: alpha_search(
                main, session_id, {"mode": "open", "reference": reference}
            ),
        )
        await check(
            "alpha_find",
            lambda: alpha_search(
                main,
                session_id,
                {"mode": "find", "reference": reference, "pattern": "Minecraft"},
            ),
        )

    async def review_json():
        if review is None:
            raise ValueError("请先选择审核模型提供商")
        if review.provider_config.get("type") not in (
            "openai_responses",
            "openai_chat_completion",
        ):
            raise ValueError("审核模型需要 OpenAI 兼容 Chat／Responses")
        provider = request_provider(
            effort_provider(review, settings.get("review_reasoning_effort", ""))
        )
        provider.provider_config.setdefault("custom_extra_body", {})[
            "max_output_tokens"
            if review.provider_config.get("type") == "openai_responses"
            else "max_completion_tokens"
        ] = 512
        response = await provider.text_chat(
            prompt='审核无副作用的测试回显，严格返回 {"decision":"allow"}。',
            contexts=[],
            func_tool=None,
            request_max_retries=1,
        )
        return json.loads(response.completion_text) == {"decision": "allow"}

    await check("review_json", review_json)
    result["complete"] = True
    progress(result)
    return result


def detected_settings(result):
    changes = {}
    items = result["items"]
    native = items.get("web_search", {}).get("status")
    preview = items.get("web_search_preview", {}).get("status")
    if native == "passed" or preview == "passed":
        changes.update(
            enable_web_search=True,
            web_search_tool_type="web_search"
            if native == "passed"
            else "web_search_preview",
        )
    elif native == "unsupported" and preview in (None, "unsupported"):
        changes["enable_web_search"] = False
    if items.get("progress", {}).get("status") == "unsupported":
        changes["forward_progress"] = False
    status = items.get("alpha_search", {}).get("status")
    if status == "passed":
        changes["enable_alpha_search"] = True
    elif status == "unsupported":
        changes["enable_alpha_search"] = False
    return changes
