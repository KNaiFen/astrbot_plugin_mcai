"""Compact settled conversation groups, retaining the original evidence in SQLite."""

import json

from astrbot.core.agent.context.token_counter import EstimateTokenCounter
from astrbot.core.agent.message import Message

from .agent_runtime import model_request, request_provider


def tokens(messages):
    return EstimateTokenCounter().count_tokens(
        [Message.model_validate(item) for item in messages]
    )


async def fit_history(
    tasks, job, provider, messages, system, *, tools=None, archive=False
):
    limit = provider.provider_config.get("max_context_tokens", 0) or 32768
    overhead = tokens([{"role": "system", "content": system}])
    if tools is not None:
        overhead += len(json.dumps(tools, ensure_ascii=False)) // 2
    budget = int(limit * 0.7) - overhead
    if budget < 2000:
        raise ValueError(
            "模型上下文容量不足以容纳规则和工具，请调整 max_context_tokens 或选择更大模型"
        )
    while tokens(messages) > budget:
        previous_tokens = tokens(messages)
        # A tool-call assistant and all its replies form one indivisible group.
        boundaries = [
            i for i in range(1, len(messages)) if messages[i]["role"] != "tool"
        ]
        boundaries.append(len(messages))
        split = 0
        for end in boundaries:
            if tokens(messages[:end]) > int(limit * 0.65):
                break
            split = end
        if not split:
            raise ValueError(
                "单个未压缩对话组超过上下文预算，请从原始工具记录缩小结果后继续"
            )
        original = messages[:split]
        prompt = json.dumps(original, ensure_ascii=False)

        async def summarize():
            return await request_provider(provider).text_chat(
                prompt=prompt,
                contexts=[],
                func_tool=None,
                request_max_retries=1,
                system_prompt="压缩已结算的 Minecraft 排障对话。只保留已知事实、证据、失败尝试、明确结论和仍待验证的问题，保留目录、操作编号、后台编号、备份及引用。审核材料不属于主对话。不得推测或增加授权。用中文简明记录，最多1500字。",
            )

        if archive:
            response = await summarize()
            if response.role == "err":
                raise RuntimeError(response.completion_text)
        else:
            response = await model_request(tasks, job, "上下文压缩", summarize, 3)
        text = response.completion_text
        if not text or len(text) > 6000:
            raise ValueError("上下文压缩未返回预算内的事实摘要，原记录保留")
        seq = tasks.store.event("context:" + job["id"], {"messages": original})
        tasks.store.event(
            "context_index:" + job["id"], {"entry": seq, "characters": len(prompt)}
        )
        checkpoint = {
            "role": "user",
            "content": f"已结算历史摘要（原始证据可用 mc_job history entry={seq} 按字符续读）：\n{text}",
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
        messages = [checkpoint, *messages[split:]]
        if tokens(messages) >= previous_tokens:
            raise ValueError(
                "事实摘要未缩减上下文，原证据已保存，请缩小查询或调整模型容量"
            )
        job["messages"] = messages
        tasks.save(job)
    job["context_budget"] = {
        "estimated_tokens": tokens(messages) + overhead,
        "limit": limit,
        "task_bytes": len(json.dumps(job, ensure_ascii=False).encode("utf-8")),
    }
    tasks.save(job)
    return messages
