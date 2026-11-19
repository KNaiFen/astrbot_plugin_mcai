"""Compact settled conversation groups, retaining the original evidence in SQLite."""

import json
import math

from .agent_runtime import TASK_POLICY, collect_stream, model_request, request_provider
from .model_budget import budget_factor, estimated_input, record_usage, tokens
from .review import digest
from .tracing import traced_provider

SUMMARY_PREFIX = "已结算历史摘要（原始证据可用 mc_context_history entry="
SUMMARY_TIMEOUT = 300
SUMMARY_PROMPT = (
    """压缩已结算的 Minecraft 运维与排障对话，为继续当前任务生成简洁、结构化的交接摘要，只输出摘要。
保留任务目标、实例与目录、用户约束和明确批准的范围；区分消息来源、未核实陈述、已知事实和推测。
保留关键证据及引用、已完成和失败的尝试、结果未知的操作、操作编号、后台编号、备份路径，以及尚未完成的查询、测试、清理和待确认事项。
合并重复日志和中间过程，突出最新结果和具体下一步。既有历史摘要仍是任务上下文，保留其仍有效的事实和原始证据引用。
明确交接当前阶段目标、决定下一步缺的关键事实及已满足的完成条件；已结算过程不改写成待办，无关未知项不升级成前置任务，用户硬性约束仍保留。
最新用户消息由主对话原样保留，本请求只总结给出的旧历史，不猜测新指令。审核材料不属于主对话，不增加授权，不把计划写成已执行，不建议重放结果未知的操作。用中文记录。
task_context是程序提供的任务来源与边界，messages仅是本次选中的旧历史批次。批内未出现某条任务、授权或证据，不代表整个任务缺少它；勿生成“从未提供原任务／没有管理员要求”等全局否定，也勿要求重述仍由主对话保留的指令。只记录本批已见事实和确有证据的缺口。
max_characters是本次摘要正文的目标字符预算。优先保留目标、硬约束、已满足条件、操作状态和关键证据引用；重复日志、完整脚本及大原值用引用代替，不复述过程或反复解释同一限制。
已完成的旧阶段只保留一句结果与一个原证据入口；不重复其进程身份、查询编号、完整动作链或层层历史摘要入口。当前阶段保留会改变下一步的事实与引用；仅结果未知或仍在执行的操作需要完整编号与状态。通用规则不逐条抄回摘要，不把本批没有新增批准当作新的待办。
"""
    + TASK_POLICY
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
    summary_rules="",
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
    summary_system = SUMMARY_PROMPT + (
        "\n角色规则：\n" + summary_rules if summary_rules else ""
    )
    summary_overhead = tokens([{"role": "system", "content": summary_system}])
    summary_output = output_budget or min(8192, max(1, limit // 10))
    factor = budget_factor(tasks.store, provider, "compaction")
    summary_budget = (
        int(min(trigger, limit - summary_output) / factor) - summary_overhead
    )
    if overhead >= input_limit or summary_budget <= 0:
        raise ValueError("模型上下文不足以容纳提示和已配置输出额度，请调整模型配置")
    identity = context_identity(provider, system, tools)
    purpose = "archive" if archive else "main"

    def estimate(history):
        if payload is not None:
            text = json.dumps(
                {**payload, "messages": summary_messages(history)}, ensure_ascii=False
            )
            raw = overhead + tokens([{"role": "user", "content": text}])
        else:
            raw = overhead + tokens(history)
        return estimated_input(tasks.store, provider, purpose, raw)

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
                    + estimated_input(
                        tasks.store, provider, purpose, tokens(history[length + 1 :])
                    )
                )
                return estimated, max(estimated, used), "api_usage+estimate"
        return estimated, estimated, "estimate"

    estimated, used, source = measure(messages)
    batches = 0

    def save_budget():
        job["archive_context_budget" if archive else "context_budget"] = {
            "estimated_tokens": estimated,
            "used_tokens": used,
            "count_source": source,
            "trigger_tokens": trigger,
            "limit": limit,
            "input_limit": input_limit,
            "overhead_tokens": overhead,
            "batches": batches,
            "task_bytes": len(json.dumps(job, ensure_ascii=False).encode("utf-8")),
        }
        tasks.save(job)

    def capacity_error(detail, required):
        suggested = int((required + output_budget) / 0.9) + 1
        return ValueError(
            f"{detail}；当前配置窗口{limit} tokens，所需输入约{required} tokens，"
            f"另预留输出{output_budget} tokens。原文和原操作编号保留。"
            f"请先确认服务商和模型支持的容量，在AstrBot提供商模型配置中将"
            f"max_context_tokens调至至少{suggested}，保存后使用“/mcairesume {job['name']}”续接；"
            "若模型不支持更大窗口，请保留当前任务证据，另建范围更小的任务。"
            "仅重复续接或要求群用户修改已返回结果不能解除此限制"
        )

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
        protected_size = estimate([messages[i] for i in sorted(protected)])
        if protected_size > input_limit:
            raise capacity_error(
                "受保护的最新用户消息和完整交互组已超过请求预算", protected_size
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
            raise capacity_error("仅剩受保护的用户消息或完整交互组，无法容纳请求", used)

        summary_target = min(summary_output, max(256, (input_limit - overhead) // 10))

        def render(selected):
            original = [messages[i] for group in selected for i in group]
            content = summary_messages(original)
            return json.dumps(
                {
                    "task_context": {
                        "name": job["name"],
                        "creator": {"sender": job["admin"], "is_admin": True},
                        "instance": job.get("instance"),
                        "directory": job.get("directory"),
                    },
                    "max_characters": min(
                        summary_target,
                        max(256, len(json.dumps(content, ensure_ascii=False)) // 4),
                    ),
                    "messages": content,
                },
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
        if not selected or (
            not only_checkpoints
            and all(
                str(messages[group[0]].get("content", "")).startswith(SUMMARY_PREFIX)
                for group in selected
            )
        ):
            raise capacity_error(
                "下一个已结算交互组超过摘要请求预算",
                size + group_size + summary_overhead,
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

        summary_provider = request_provider(provider)
        if not output_budget:
            field = (
                "max_output_tokens"
                if provider.provider_config["type"] == "openai_responses"
                else "max_tokens"
            )
            summary_provider.provider_config.setdefault("custom_extra_body", {})[
                field
            ] = summary_output
        if hasattr(summary_provider, "client"):
            summary_provider.client = summary_provider.client.with_options(
                timeout=SUMMARY_TIMEOUT, max_retries=0
            )
        summary_provider = traced_provider(
            summary_provider, tasks.store, job["id"], "上下文压缩"
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
                stream=True,
                timeout_seconds=SUMMARY_TIMEOUT,
                input_tokens=math.ceil(
                    factor
                    * (summary_overhead + tokens([{"role": "user", "content": prompt}]))
                ),
                summary_count_source="character_benchmark+api_usage",
                output_tokens=summary_output,
                reason="context_length_exceeded" if force else "threshold",
            )
            return await collect_stream(
                summary_provider,
                prompt=prompt,
                contexts=[],
                func_tool=None,
                request_max_retries=1,
                system_prompt=summary_system,
            )

        for reduction_attempt in range(2):
            response = await model_request(
                tasks,
                job,
                "上下文压缩",
                summarize,
                1 if archive else 3,
                pause_on_error=not archive,
                recover_context=shrink,
                check_stop=not archive,
                summary=True,
            )
            record_usage(
                tasks.store,
                provider,
                "compaction",
                summary_overhead + tokens([{"role": "user", "content": prompt}]),
                response,
            )
            factor = budget_factor(tasks.store, provider, "compaction")
            summary_budget = (
                int(min(trigger, limit - summary_output) / factor) - summary_overhead
            )
            text = (response.completion_text or "").strip()
            if not text:
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
            if estimate(updated) < previous_tokens:
                break
            if reduction_attempt:
                raise ValueError("事实摘要两次未缩减上下文，原记录和操作状态保留")
            summary_target = max(128, summary_target // 2)
            prompt = render(selected)
            tasks.log(job, "context_compaction_retry", reason="summary_did_not_shrink")
        messages = updated
        if not archive:
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
