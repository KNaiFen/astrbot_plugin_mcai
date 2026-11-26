"""Small, isolated provider capability probes. No production tools are exposed."""

import asyncio
import json
import re
import time
import uuid

from .agent_runtime import (
    compact_responses,
    compaction_rejected,
    compaction_unsupported,
    effort_provider,
    hosted_tools,
    replay_compaction,
    request_provider,
    retryable,
    search_compatible_call,
)
from .review import digest
from .search import alpha_search
from .tracing import traced_provider

IMAGE_PROBE = (
    "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAACAAAAAgCAIAAAD8GO2jAAAAN0lEQVR4n"
    "O3RMQ0AMAzEQLf8OacQ3CWbD8BHcg4Mm+7qOh340A9UiVSJVIlUiVSJVIlUiVSJMA+hxgE/8m7Sp"
    "QAAAABJRU5ErkJggg=="
)


def image_unsupported(error):
    text = str(error).lower()
    return (
        getattr(error, "status_code", None) in (400, 415, 422)
        and re.search(r"\b(?:image(?:_url|s)?|input_image|vision|multi.?modal)\b", text)
        and re.search(
            r"unsupported|not support|does not accept|only support|unknown|unrecognized|不支持",
            text,
        )
    )


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


CAPABILITY_ITEMS = frozenset(
    {
        "conversation",
        "image",
        "stream",
        "function_call",
        "reasoning_effort",
        "web_search",
        "web_search_preview",
        "alpha_search",
        "alpha_open",
        "alpha_find",
        "progress",
        "remote_compaction",
        "remote_compaction_compact",
        "review_json",
    }
)
BACKUP_CAPABILITY_ITEMS = frozenset(
    {
        "conversation",
        "image",
        "stream",
        "function_call",
        "reasoning_effort",
        "review_json",
    }
)


def _prepare_selected_provider(provider, effort):
    selected = request_provider(effort_provider(provider, effort))
    budget_field = (
        "max_output_tokens"
        if provider.provider_config.get("type") == "openai_responses"
        else "max_completion_tokens"
    )
    selected.provider_config.setdefault("custom_extra_body", {})[budget_field] = 512
    return selected


def _make_check(result, progress, providers, *, only=None):
    async def check(name, call):
        if (
            only
            and name != only
            and not (name == "alpha_search" and only in ("alpha_open", "alpha_find"))
        ):
            return None
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
                compaction_unsupported(exc) or compaction_rejected(exc)
                if name.startswith("remote_compaction")
                else image_unsupported(exc)
                if name == "image"
                else status in (400, 404, 405, 422)
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
            for provider in providers:
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

    return check


async def _run_basic_probes(selected, check, result, *, effort="", only=None):
    from astrbot.core.agent.tool import FunctionTool, ToolSet

    async def conversation():
        response = await selected.text_chat(
            prompt="请只回复 MCAI_OK。",
            contexts=[],
            func_tool=None,
            request_max_retries=1,
        )
        return response.role != "err" and "MCAI_OK" in (response.completion_text or "")

    await check(
        "reasoning_effort" if only == "reasoning_effort" else "conversation",
        conversation,
    )

    async def image():
        response = await selected.text_chat(
            prompt="这张图只有一种颜色。用一个英文单词写出你看到的颜色：red、green 或 blue。",
            image_urls=[IMAGE_PROBE],
            contexts=[],
            func_tool=None,
            request_max_retries=1,
        )
        return (
            response.role != "err"
            and (response.completion_text or "").strip().lower().rstrip(".。") == "blue"
        )

    await check("image", image)

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
    if not only and effort:
        result["items"]["reasoning_effort"] = result["items"]["conversation"].copy()


async def _run_review_probe(review, check, *, effort=""):
    async def review_json():
        if review is None:
            raise ValueError("请先选择审核模型提供商")
        if review.provider_config.get("type") not in (
            "openai_responses",
            "openai_chat_completion",
        ):
            raise ValueError("审核模型需要 OpenAI 兼容 Chat／Responses")
        provider = _prepare_selected_provider(review, effort)
        response = await provider.text_chat(
            prompt='审核无副作用的测试回显，严格返回 {"decision":"allow"}。',
            contexts=[],
            func_tool=None,
            request_max_retries=1,
        )
        return json.loads(response.completion_text) == {"decision": "allow"}

    await check("review_json", review_json)


async def test_capabilities(main, review, settings, progress, *, store=None, only=None):
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
    check = _make_check(result, progress, (main, review), only=only)
    effort = settings.get("reasoning_effort", "")
    selected = _prepare_selected_provider(main, effort)
    await _run_basic_probes(selected, check, result, effort=effort, only=only)

    if main.provider_config.get("type") == "openai_responses":

        async def native_search(kind):
            response = await search_compatible_call(
                main.client.responses.create,
                {
                    "model": main.get_model(),
                    "input": "搜索 Minecraft 官方网站，返回官网名称和一个来源链接。",
                    "tools": hosted_tools(
                        [], kind, settings.get("web_search_mode", "cached")
                    ),
                    "tool_choice": "required",
                    "max_output_tokens": 512,
                },
            )
            return any(item.type == "web_search_call" for item in response.output)

        passed = await check("web_search", lambda: native_search("web_search"))
        if only == "web_search_preview" or (
            not only
            and not passed
            and result["items"]["web_search"]["status"] == "unsupported"
        ):
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

        async def remote_compaction(mode):
            secret = uuid.uuid4().hex[:12]
            instructions = (
                "这是上下文回放测试。记住此前助手给出的测试暗号，追问时只回复该暗号。"
            )
            input = [
                {"role": "user", "content": "请提供并记住一个本次测试专用的暗号。"},
                {"role": "assistant", "content": f"本次测试暗号是 {secret}。"},
                {"role": "user", "content": "收到，请继续记住。"},
                {"role": "assistant", "content": "已记住。"},
            ]
            response = await compact_responses(
                main.client,
                mode,
                model=main.get_model(),
                instructions=instructions,
                input=input,
            )
            items = replay_compaction(response)
            if not items:
                return False
            answer = await main.client.responses.create(
                model=main.get_model(),
                instructions=instructions,
                input=[*items, {"role": "user", "content": "此前的测试暗号是什么？"}],
                store=False,
                max_output_tokens=128,
            )
            return answer.status == "completed" and secret in answer.output_text

        await check(
            "remote_compaction", lambda: remote_compaction("compaction_trigger")
        )
        if only == "remote_compaction_compact" or (
            not only and result["items"]["remote_compaction"]["status"] == "unsupported"
        ):
            await check(
                "remote_compaction_compact",
                lambda: remote_compaction("responses_compact"),
            )
    else:
        result["items"]["web_search"] = {
            "status": "unsupported",
            "error": "托管搜索需要 Responses 提供商",
        }
        result["items"]["progress"] = {
            "status": "unsupported",
            "error": "commentary 执行进度汇报需要 Responses 提供商",
        }
        result["items"][
            only if only == "remote_compaction_compact" else "remote_compaction"
        ] = {
            "status": "unsupported",
            "error": "远程压缩需要 Responses 提供商",
        }

    session_id = uuid.uuid4().hex
    search = await check(
        "alpha_search",
        lambda: alpha_search(
            main,
            session_id,
            {"mode": "search", "query": "Minecraft official website"},
            store=store,
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
                main,
                session_id,
                {"mode": "open", "reference": reference},
                store=store,
            ),
        )
        await check(
            "alpha_find",
            lambda: alpha_search(
                main,
                session_id,
                {"mode": "find", "reference": reference, "pattern": "Minecraft"},
                store=store,
            ),
        )
    elif only in ("alpha_open", "alpha_find"):
        result["items"][only] = {
            "status": "failed",
            "error": "前置 alpha/search 未取得搜索结果",
        }

    await _run_review_probe(
        review, check, effort=settings.get("review_reasoning_effort", "")
    )
    if only:
        result["items"] = {
            only: result["items"].get(
                only, {"status": "unsupported", "error": "当前提供商不支持此测试"}
            )
        }
    result["complete"] = True
    progress(result)
    return result


async def test_backup_capabilities(
    backup_main, backup_review, settings, progress, *, store=None, only=None
):
    if backup_main is None and backup_review is None:
        raise ValueError("请先选择备用排障模型或备用审核模型")
    main = None
    if backup_main is not None:
        main = request_provider(backup_main)
        if main.provider_config.get("type") in (
            "openai_responses",
            "openai_chat_completion",
        ) and hasattr(main, "client"):
            main.client = main.client.with_options(max_retries=0)
        if store is not None:
            main = traced_provider(main, store, None, "备用能力测试")
    review = None
    if backup_review is not None:
        review = request_provider(backup_review)
        if review.provider_config.get("type") in (
            "openai_responses",
            "openai_chat_completion",
        ) and hasattr(review, "client"):
            review.client = review.client.with_options(max_retries=0)
        if store is not None:
            review = traced_provider(review, store, None, "备用审核能力测试")

    review_settings = {
        "backup_review_reasoning_effort": settings.get(
            "backup_review_reasoning_effort", ""
        )
    }
    result = {
        "created": time.time(),
        "target": "backup",
        "identity": provider_identity(main, settings) if main is not None else None,
        "review_identity": provider_identity(review, review_settings)
        if review is not None
        else None,
        "items": {},
        "settings": settings,
    }
    check = _make_check(result, progress, (main, review), only=only)
    if main is not None:
        effort = settings.get("backup_reasoning_effort", "")
        selected = _prepare_selected_provider(main, effort)
        await _run_basic_probes(selected, check, result, effort=effort, only=only)
    if review is not None:
        await _run_review_probe(
            review,
            check,
            effort=settings.get("backup_review_reasoning_effort", ""),
        )
    if only:
        result["items"] = {
            only: result["items"].get(
                only, {"status": "unsupported", "error": "当前备用模型未配置此测试"}
            )
        }
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
    trigger = items.get("remote_compaction", {}).get("status")
    compact = items.get("remote_compaction_compact", {}).get("status")
    if trigger == "passed" or compact == "passed":
        changes.update(
            enable_remote_compaction=True,
            remote_compaction_mode="compaction_trigger"
            if trigger == "passed"
            else "responses_compact",
        )
    elif trigger == "unsupported" and compact in (None, "unsupported"):
        changes["enable_remote_compaction"] = False
    if items.get("progress", {}).get("status") == "unsupported":
        changes["forward_progress"] = False
    status = items.get("alpha_search", {}).get("status")
    if status == "passed":
        changes["enable_alpha_search"] = True
    elif status == "unsupported":
        changes["enable_alpha_search"] = False
    return changes
