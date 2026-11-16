"""Compact settled conversation groups, retaining the original evidence in SQLite."""

import json

from astrbot.core.agent.context.token_counter import EstimateTokenCounter
from astrbot.core.agent.message import Message

from .agent_runtime import TASK_POLICY, model_request, request_provider
from .review import digest
from .tracing import traced_provider

SUMMARY_PREFIX = "已结算历史摘要（原始证据可用 mc_context_history entry="
SUMMARY_PROMPT = (
    """压缩已结算的 Minecraft 运维与排障对话，为继续当前任务生成简洁、结构化的交接摘要，只输出摘要。
保留任务目标、实例与目录、用户约束和明确批准的范围；区分消息来源、未核实陈述、已知事实和推测。
保留关键证据及引用、已完成和失败的尝试、结果未知的操作、操作编号、后台编号、备份路径，以及尚未完成的查询、测试、清理和待确认事项。
合并重复日志和中间过程，突出最新结果和具体下一步。既有历史摘要仍是任务上下文，保留其仍有效的事实和原始证据引用。
latest_user 是原样保留的最新用户消息，仅用于理解当前目标。审核材料不属于主对话，不增加授权，不把计划写成已执行，不建议重放结果未知的操作。用中文记录。
"""
    + TASK_POLICY
)


def tokens(messages):
    return EstimateTokenCounter().count_tokens(
        [Message.model_validate(item) for item in messages]
    )


def summary_messages(messages):
    """Project readable evidence without altering native replay or stored originals."""
    result = []
    for message in messages:
        item = {
            key: value
            for key, value in message.items()
            if key in ("role", "content", "tool_calls", "tool_call_id", "name")
        }
        if isinstance(item.get("content"), list):
            item["content"] = [
                part for part in item["content"] if part["type"] != "think"
            ]
        result.append(item)
    return result


def context_identity(provider, system, tools):
    config = provider.provider_config
    return digest(
        {
            "provider": config.get("id"),
            "model": getattr(provider, "model_name", config.get("model")),
            "parameters": config.get("custom_extra_body", {}),
            "system": system,
            "tools": tools,
        }
    )


async def fit_history(
    tasks,
    job,
    provider,
    messages,
    system,
    *,
    tools=None,
    archive=False,
    force=False,
    payload=None,
):
    limit = provider.provider_config.get("max_context_tokens", 0) or 272000
    trigger = int(limit * 0.95)
    overhead = tokens([{"role": "system", "content": system}])
    if tools is not None:
        overhead += tokens(
            [{"role": "system", "content": json.dumps(tools, ensure_ascii=False)}]
        )
    extra = provider.provider_config.get("custom_extra_body", {})
    output_budget = max(
        extra.get("max_output_tokens") or 0,
        extra.get("max_completion_tokens") or 0,
        extra.get("max_tokens") or 0,
    )
    input_limit = limit - output_budget
    summary_overhead = tokens([{"role": "system", "content": SUMMARY_PROMPT}])
    summary_budget = min(trigger, input_limit) - summary_overhead
    if overhead >= input_limit or summary_budget <= 0:
        raise ValueError("模型上下文不足以容纳提示和已配置输出额度，请调整模型配置")
    identity = context_identity(provider, system, tools)

    def estimate(history):
        if payload is not None:
            text = json.dumps(
                {**payload, "messages": summary_messages(history)}, ensure_ascii=False
            )
            return overhead + tokens([{"role": "user", "content": text}])
        return overhead + tokens(history)

    def measure(history):
        estimated = estimate(history)
        usage = job.get("context_usage") if not archive else None
        if usage and usage["identity"] == identity:
            length = usage["messages"]
            if (
                len(history) > length
                and history[length]["role"] == "assistant"
                and digest(history[:length]) == usage["prefix"]
            ):
                used = (
                    usage["input_tokens"]
                    + usage["output_tokens"]
                    + tokens(history[length + 1 :])
                )
                return estimated, max(estimated, used), "api_usage+estimate"
        return estimated, estimated, "estimate"

    estimated, used, source = measure(messages)
    batches = 0

    def save_budget():
        job["context_budget"] = {
            "estimated_tokens": estimated,
            "used_tokens": used,
            "count_source": source,
            "trigger_tokens": trigger,
            "limit": limit,
            "batches": batches,
            "task_bytes": len(json.dumps(job, ensure_ascii=False).encode("utf-8")),
        }
        tasks.save(job)

    save_budget()
    while force or used >= trigger or used > input_limit:
        previous_tokens = used
        if not messages:
            raise ValueError("没有可压缩的历史，请检查模型容量和请求提示")
        starts = [
            0,
            *[i for i in range(1, len(messages)) if messages[i]["role"] != "tool"],
        ]
        groups = [
            list(range(start, end))
            for start, end in zip(starts, [*starts[1:], len(messages)])
        ]
        protected = set()
        last_user = next(
            (
                i
                for i in reversed(range(len(messages)))
                if messages[i]["role"] == "user"
                and not str(messages[i].get("content", "")).startswith(SUMMARY_PREFIX)
            ),
            None,
        )
        if last_user is not None:
            protected.add(last_user)
        last_assistant = None
        for group in groups:
            first = messages[group[0]]
            calls = {call["id"] for call in first.get("tool_calls") or []}
            replies = {
                messages[i]["tool_call_id"]
                for i in group
                if messages[i]["role"] == "tool"
            }
            if calls != replies:
                protected.update(group)
            elif first["role"] == "assistant":
                last_assistant = group
        if last_assistant is not None:
            protected.update(last_assistant)
        if estimate([messages[i] for i in sorted(protected)]) > input_limit:
            raise ValueError(
                "受保护的最新用户消息和完整交互组已超过请求预算；原文保留，请通过证据引用和分页缩小结果"
            )
        eligible = [group for group in groups if not protected.intersection(group)]
        only_checkpoints = all(
            str(messages[group[0]].get("content", "")).startswith(SUMMARY_PREFIX)
            for group in eligible
        )
        if (not eligible or only_checkpoints) and not force and used <= input_limit:
            # The trigger must not repeatedly summarize the same checkpoint.
            break
        if not eligible:
            raise ValueError(
                "仅剩受保护的用户消息或完整交互组，无法容纳请求；原文保留，请通过证据引用和分页缩小结果"
            )

        latest_user = (
            summary_messages([messages[last_user]])[0]
            if last_user is not None
            else None
        )

        def render(selected):
            original = [messages[i] for group in selected for i in group]
            return json.dumps(
                {"latest_user": latest_user, "messages": summary_messages(original)},
                ensure_ascii=False,
            )

        selected = []
        size = tokens([{"role": "user", "content": render([])}])
        for group in eligible:
            group_size = (
                tokens(
                    [
                        {
                            "role": "user",
                            "content": json.dumps(
                                summary_messages([messages[i] for i in group]),
                                ensure_ascii=False,
                            ),
                        }
                    ]
                )
                + 1
            )
            if size + group_size > summary_budget:
                break
            selected.append(group)
            size += group_size
        prompt = render(selected)
        while (
            selected and tokens([{"role": "user", "content": prompt}]) > summary_budget
        ):
            selected.pop()
            prompt = render(selected)
        if not selected:
            raise ValueError(
                "单个已结算交互组超过摘要请求预算；原文保留，请通过证据引用和分页缩小结果"
            )

        async def shrink(error):
            nonlocal selected, prompt
            if len(selected) == 1:
                raise ValueError(
                    "单个已结算交互组仍超过服务商上下文窗口，原文保留"
                ) from error
            before = len(selected)
            selected = selected[: len(selected) // 2]
            prompt = render(selected)
            tasks.log(
                job,
                "context_compaction_retry",
                before_groups=before,
                groups=len(selected),
                reason=str(error),
            )

        async def summarize():
            tasks.log(
                job,
                "context_compaction_request",
                limit=limit,
                trigger_tokens=trigger,
                used_tokens=used,
                count_source=source,
                groups=len(selected),
                input_tokens=summary_overhead
                + tokens([{"role": "user", "content": prompt}]),
                reason="context_length_exceeded" if force else "threshold",
            )
            return await traced_provider(
                request_provider(provider), tasks.store, job["id"], "上下文压缩"
            ).text_chat(
                prompt=prompt,
                contexts=[],
                func_tool=None,
                request_max_retries=1,
                system_prompt=SUMMARY_PROMPT,
            )

        response = await model_request(
            tasks,
            job,
            "上下文压缩",
            summarize,
            1 if archive else 3,
            pause_on_error=not archive,
            recover_context=shrink,
            check_stop=not archive,
        )
        text = (response.completion_text or "").strip()
        raw = response.raw_completion
        if not text or (
            raw is not None
            and (
                getattr(raw, "status", None) in ("incomplete", "failed", "cancelled")
                or any(
                    choice.finish_reason == "length"
                    for choice in getattr(raw, "choices", [])
                )
            )
        ):
            raise ValueError("上下文压缩未返回完整的非空摘要，原记录保留")

        selected_indices = {i for group in selected for i in group}
        original = [
            message for i, message in enumerate(messages) if i in selected_indices
        ]
        seq = tasks.store.event("context:" + job["id"], {"messages": original})
        tasks.store.event(
            "context_index:" + job["id"],
            {
                "entry": seq,
                "characters": len(
                    json.dumps({"messages": original}, ensure_ascii=False)
                ),
            },
        )
        checkpoint = {
            "role": "user",
            "content": f"{SUMMARY_PREFIX}{seq} 按字符续读）：\n{text}",
        }
        checkpoint["content"] += "\n持久任务事实：" + json.dumps(
            {
                "instance": job.get("instance"),
                "directory": job.get("directory"),
                "operation": job.get("operation"),
                "failed_operation": job.get("failed_operation"),
                "background": job.get("background", {}),
                "repair_operations": [
                    item["operation"] for item in job.get("repairs", [])
                ],
            },
            ensure_ascii=False,
        )
        updated = [
            checkpoint,
            *[
                message
                for i, message in enumerate(messages)
                if i not in selected_indices
            ],
        ]
        if estimate(updated) >= previous_tokens:
            raise ValueError(
                "事实摘要未缩减上下文，原证据已保存，请缩小查询或调整模型容量"
            )
        messages = updated
        job.pop("context_usage", None)
        job["messages"] = messages
        batches += 1
        estimated, used, source = measure(messages)
        save_budget()
        tasks.log(
            job,
            "context_compacted",
            entry=seq,
            before_tokens=previous_tokens,
            used_tokens=used,
            preserved_messages=len(messages) - 1,
        )
        force = False

    return messages
