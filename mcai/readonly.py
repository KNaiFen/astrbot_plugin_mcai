"""Bounded server status and one-shot read-only questions."""

import asyncio
import copy
import json
import uuid
from contextlib import aclosing

import aiohttp
from astrbot.core.agent.hooks import BaseAgentRunHooks
from astrbot.core.agent.message import Message
from astrbot.core.agent.runners.tool_loop_agent_runner import ToolLoopAgentRunner
from astrbot.core.astr_agent_context import AgentContextWrapper, AstrAgentContext
from astrbot.core.astr_agent_tool_exec import FunctionToolExecutor
from astrbot.core.provider.entities import ProviderRequest
from jsonschema import ValidationError, validate

from .agent_runtime import check_response, effort_provider, request_provider
from .astrbot_agent import McTool, McToolSet
from .client import RemoteError
from .query_cli import QueryHelp, parse_query, query_operation
from .tool_arguments import arguments_for
from .tool_help import tool_help
from .tool_results import model_result
from .tool_schemas import TOOLS
from .tracing import trace_event, traced_provider

ASK_STEPS = 8
ASK_TIMEOUT = 90
ACTIVE = ("pending", "running")
BACKEND_ERRORS = (aiohttp.ClientError, TimeoutError, RemoteError, OSError)
PROBE_TOOLS = {
    "mc_players",
    "mc_metrics",
    "mc_objects",
    "mc_chunks",
    "mc_runtime",
    "mc_inspect",
}
JOB_MODES = {
    "mc_job_read": "read",
    "mc_job_wait": "wait",
    "mc_artifact_read": "artifact",
    "mc_artifact_find": "find",
}
READ_TOOLS = (
    PROBE_TOOLS
    | JOB_MODES.keys()
    | {
        "mc_instances",
        "mc_select_instance",
        "mc_history",
        "mc_knowledge",
        "mc_status",
        "mc_query",
        "mc_console_read",
        "mc_console_line",
        "mc_tools",
    }
)
BACKGROUND = {
    "probe",
    "files_query",
    "logs",
    "region_scan",
    "region_export",
    "diagnostics",
}


def state_text(row):
    running = (
        "未知" if row["state_unknown"] else "运行中" if row["running"] else "已停止"
    )
    return f"窗口{'在线' if row['window_online'] else '离线'}，MC {running}"


class Reads:
    def __init__(self, client, identity, store):
        self.client, self.identity, self.store = client, identity, store
        self.background = set()
        self.jobs = set()
        self.cleanup_failed = False

    async def call(self, instance, action, arguments):
        key = uuid.uuid4().hex
        if action in BACKGROUND:
            self.background.add(key)
        path = f"/operations/{key}"
        body = {
            "instance": instance["instance"],
            "action": action,
            "task_id": self.identity,
            "arguments": {
                **arguments,
                "expected_directory": instance["canonical_directory"],
            },
        }
        row = await self.client.request("POST", path, once=True, json=body)
        while row["status"] in ACTIVE:
            await asyncio.sleep(0.1)
            row = await self.client.request("GET", path, once=True)
        if row["status"] == "failed":
            raise RemoteError(row["error"], operation=row)
        result = row["result"]
        if isinstance(result, dict) and result.get("id") == key:
            self.jobs.add(key)
            if result["status"] not in ACTIVE:
                self.background.discard(key)
        return result

    async def stop(self):
        async def cancel(key):
            try:
                # The operation endpoint records cancellation even if submission was interrupted.
                async with asyncio.timeout(8):
                    await self.client.request(
                        "POST", f"/operations/{key}/cancel", once=True
                    )
            except BACKEND_ERRORS as exc:
                self.cleanup_failed = True
                trace_event(
                    self.store,
                    "readonly_cleanup_failed",
                    task=self.identity,
                    operation=key,
                    error=str(exc) or type(exc).__name__,
                )

        await asyncio.gather(*(cancel(key) for key in self.background))


async def server_status(client, store, identity, instance, admin):
    reads = Reads(client, identity, store)
    try:
        async with asyncio.timeout(5):
            rows = await client.request("GET", "/instances", once=True)
            if not instance:
                return (
                    "\n".join(
                        f"{row['instance']} · {(row['description'].strip().splitlines() or ['无说明'])[0][:32]} · {state_text(row)}"
                        for row in rows
                    )
                    or "B 未配置服务端。"
                )
            row = next((row for row in rows if row["instance"] == instance), None)
            if row is None:
                raise ValueError("实例不存在；用 “/mcaiserver” 查看实例 ID。")
            lines = [f"{instance}：{state_text(row)}"]
            metrics = await reads.call(row, "metrics", {"view": "summary"})
            if admin:
                lines.extend(
                    [
                        f"B 数据盘剩余：{metrics['disk_free_bytes'] / 1024**3:.1f} GiB",
                        f"窗口会话：{row['session_id'] or '无'}",
                    ]
                )
    except BACKEND_ERRORS as exc:
        return (
            f"连不上 B：{str(exc) or '请求超时'}"
            if not isinstance(exc, RemoteError) or exc.operation is None
            else f"读取 B 状态失败：{exc}"
        )

    probe = metrics["probe"]
    if not probe["available"]:
        lines.append(
            "未安装 Probe，无性能数据"
            if "未发现" in probe["reason"]
            else f"Probe 不可用：{probe['reason']}"
        )
    elif row["state_unknown"] or not row["running"]:
        lines.append("当前无法读取 Probe 玩家及性能数据。")
    else:

        async def read_probe(kind, **args):
            async with asyncio.timeout(8):
                job = await reads.call(row, "probe", {"kind": kind, **args})
                while job["status"] in ACTIVE:
                    await asyncio.sleep(0.2)
                    job = await client.request("GET", f"/jobs/{job['id']}", once=True)
                reads.background.discard(job["id"])
                if job["status"] != "completed":
                    raise RemoteError(job.get("error", "未取得 Probe 结果"))
                items = job["items"][1:]  # The first entry describes the Probe result.
                while not job["complete"]:
                    job = await client.request(
                        "GET",
                        f"/jobs/{job['id']}",
                        once=True,
                        params={"after": job["next_cursor"]},
                    )
                    items.extend(job["items"])
                return [entry["body"] for entry in items]

        try:
            players, samples = await asyncio.gather(
                read_probe("players"),
                read_probe("metrics", window_seconds=10),
                return_exceptions=True,
            )
            if isinstance(players, Exception):
                lines.append(f"在线玩家：读取失败（{str(players) or '请求超时'}）")
            else:
                lines.append(
                    f"在线玩家：{len(players)} 人"
                    + (
                        " · " + "、".join(player["name"] for player in players)
                        if players
                        else ""
                    )
                )
            if isinstance(samples, Exception):
                lines.append(f"TPS／MSPT：读取失败（{str(samples) or '请求超时'}）")
            elif samples:
                sample = samples[0]
                tps, mspt = sample.get("tps"), sample["tick_ms"].get("mean")
                lines.append(
                    f"近 10 秒：TPS {round(tps, 2) if tps is not None else '无样本'}，MSPT {round(mspt, 2) if mspt is not None else '无样本'}"
                )
            else:
                lines.append("近 10 秒：TPS／MSPT 无样本。")
        finally:
            await reads.stop()
    if reads.cleanup_failed:
        lines.append("未能确认 B 的查询已取消，详情见本地诊断。")
    return "\n".join(lines)


async def answer_question(tasks, client, event, identity, text):
    reads = Reads(client, identity, tasks.store)
    try:
        async with asyncio.timeout(ASK_TIMEOUT):
            answer = await run_question(tasks, reads, event, identity, text)
    except TimeoutError:
        answer = "只读问答超时，请缩小问题范围后重试。"
        trace_event(tasks.store, "ask_failed", task=identity, error="timeout")
    except Exception as exc:
        trace_event(tasks.store, "ask_failed", task=identity, error=type(exc).__name__)
        answer = "只读问答未完成，请检查 B 连接和模型配置。"
    finally:
        await reads.stop()
    if reads.cleanup_failed:
        answer += "\n未能确认 B 的查询已取消，详情见本地诊断。"
    return answer


async def run_question(tasks, reads, event, identity, text):
    rows = await reads.client.request("GET", "/instances", once=True, timeout=5)
    instances = {row["instance"]: row for row in rows if row["selectable"]}
    first, *rest = text.split(maxsplit=1)
    explicit = first in instances
    selected = instances[first] if explicit else None
    if explicit and not rest:
        return f"请在实例 ID 后填写问题，例如 “/mcaiask {first} 现在运行正常吗？”"
    question = rest[0] if explicit else text
    context = tasks.agent.context
    provider_id = tasks.agent.provider_id or await context.get_current_chat_provider_id(
        event.unified_msg_origin
    )
    provider = await context.provider_manager.get_provider_by_id(provider_id)
    if provider is None or provider.provider_config.get("type") not in (
        "openai_chat_completion",
        "openai_responses",
    ):
        return "请先配置支持工具调用的 OpenAI 兼容模型。"
    provider = traced_provider(
        request_provider(effort_provider(provider, tasks.agent.reasoning_effort)),
        tasks.store,
        identity,
        "只读问答",
        count_for_task=False,
    )
    contracts = {
        name: (description, schema)
        for name, description, schema in TOOLS
        if name in READ_TOOLS
    }
    for name, description in (
        ("mc_instances", "列出可查询的正式实例及说明。"),
        (
            "mc_select_instance",
            "为本次问答选择一个已配置实例，不绑定任务。存在歧义时请用户指定实例 ID。",
        ),
    ):
        contracts[name] = (description, contracts[name][1])
    _, schema = contracts["mc_tools"]
    schema = copy.deepcopy(schema)
    del schema["properties"]["workflow"], schema["anyOf"]
    schema["required"] = ["names"]
    schema["properties"]["names"]["items"]["enum"] = sorted(READ_TOOLS - {"mc_tools"})
    contracts["mc_tools"] = ("查询已开放的只读工具的用法。", schema)

    async def invoke(name, public):
        nonlocal selected
        if name not in contracts:
            raise ValueError(
                f"只读问答不允许调用 {name}；需要修改时请使用 “/mcainew 任务名 问题描述” 建立任务。"
            )
        validate(public, contracts[name][1])
        if name == "mc_instances":
            return [
                {
                    "instance": row["instance"],
                    "description": row["description"],
                    "status": state_text(row),
                }
                for row in instances.values()
            ]
        if name == "mc_select_instance":
            if explicit or selected is not None:
                raise ValueError("本次问答的目标已确定，不能切换实例。")
            if public["instance"] not in instances:
                raise ValueError("实例不存在，请用户在 “/mcaiask” 后附上实例 ID。")
            selected = instances[public["instance"]]
            return {"instance": selected["instance"], "status": state_text(selected)}
        if name == "mc_tools":
            return {"help": [tool_help(tool) for tool in public["names"]]}
        if public.get("environment", "production") != "production":
            raise ValueError("只读问答不查询测试服。")
        if selected is None:
            raise ValueError("请先确认实例；无法确定时请用户附上实例 ID。")
        arguments = arguments_for(name, public, internal=True)
        if name in ("mc_history", "mc_knowledge"):
            directory = selected["canonical_directory"]
            if arguments.get("directory", directory) != directory:
                raise ValueError("只读取本次所选实例的经验。")
            if name == "mc_knowledge":
                arguments = {**arguments, "mode": "case"}
            return tasks.knowledge.query(arguments, directory)
        if name == "mc_query":
            try:
                query, options = parse_query(arguments["argv"])
            except QueryHelp as exc:
                return {"help": str(exc)}
            if query == "mc_diagnostics" and options.get("mode") not in (
                None,
                "process",
                "jvm",
            ):
                raise ValueError(
                    "只读问答只开放 process 和 jvm 诊断；录制、类直方图和离线堆分析请使用排障任务。"
                )
            action, arguments = query_operation(query, options)
        elif name in JOB_MODES:
            if arguments["job_id"] not in reads.jobs:
                raise ValueError("只能读取本次问答启动的后台工作。")
            action, arguments = "job", {**arguments, "mode": JOB_MODES[name]}
            if name == "mc_artifact_read":
                arguments.setdefault(
                    "view", "value" if "offset" in arguments else "summary"
                )
        elif name in PROBE_TOOLS:
            action, arguments = "probe", {"kind": name[3:], **arguments}
            if arguments.get("inventory_job_id"):
                raise ValueError("只读问答不引用其他任务的磁盘清单。")
        elif name == "mc_status":
            action, arguments = "metrics", {**arguments, "view": "question"}
        else:
            action = "console_query"
        return await reads.call(selected, action, arguments)

    async def dispatch(name, arguments):
        try:
            result = model_result(name, arguments, await invoke(name, arguments))
        except (ValueError, ValidationError, *BACKEND_ERRORS) as exc:
            result = {
                "ok": False,
                "error": {
                    "message": exc.message
                    if isinstance(exc, ValidationError)
                    else str(exc) or type(exc).__name__
                },
            }
        trace_event(
            tasks.store,
            "ask_tool",
            task=identity,
            tool=name,
            arguments=arguments,
            result=result,
        )
        return json.dumps(result, ensure_ascii=False)

    tools = McToolSet(
        [
            McTool(
                name=name, description=description, parameters=schema, callback=dispatch
            )
            for name, (description, schema) in contracts.items()
        ]
    )
    prompt = (
        tasks.agent.rules() + "\n\n【本轮使用只读问答模式，以下限制优先】\n"
        "你正在处理 Minecraft 单次只读问答。用中文按证据简洁作答，避免披露敏感配置、凭据或无关私有信息。"
        "没有指定实例时根据问题与实例说明选一个；无法确定时回复请用户带实例 ID 重新提问。"
        "如果需要修改、发命令或启停，解释依据并建议用 “/mcainew 任务名 问题描述” 建任务，可引用本回答（面向群的命令提示用中文双引号括起，引号两边留空格）。"
        "第 8 步须根据已有证据作答，不再调用工具。\n"
        f"预选实例：{selected['instance'] if selected else '无'}\n"
    )
    runner = ToolLoopAgentRunner()
    runner.EMPTY_OUTPUT_RETRY_ATTEMPTS = 1
    wrapper = AgentContextWrapper(
        context=AstrAgentContext(context=context, event=event)
    )
    last_text = ""
    attempts = 0
    chat = provider.text_chat

    async def bounded_chat(**kwargs):
        nonlocal attempts, last_text
        attempts += 1
        if attempts > ASK_STEPS:
            raise ValueError("已达到问答步数上限")
        response = await chat(**kwargs)
        check_response(response)
        if response.role == "err":
            raise ValueError(response.completion_text)
        if response.completion_text:
            last_text = response.completion_text
        if attempts == ASK_STEPS:
            response.tools_call_name = response.tools_call_args = (
                response.tools_call_ids
            ) = []
        return response

    provider.text_chat = bounded_chat
    await runner.reset(
        provider=provider,
        request=ProviderRequest(
            prompt=question, contexts=[], system_prompt=prompt, func_tool=tools
        ),
        run_context=wrapper,
        tool_executor=FunctionToolExecutor(),
        agent_hooks=BaseAgentRunHooks(),
        streaming=False,
        request_max_retries=1,
    )
    for index in range(ASK_STEPS):
        if runner.done():
            break
        if index == ASK_STEPS - 1:
            runner.req.func_tool = None
            wrapper.messages.append(
                Message(
                    role="user",
                    content="请根据已有工具结果直接作答，明确仍无法核实的部分。",
                )
            )
        async with aclosing(runner.step()) as step:
            async for _ in step:
                pass
    final = runner.get_final_llm_resp()
    if final and final.role == "err" and not last_text:
        raise ValueError(final.completion_text)
    if selected is None:
        return "未能确定要查询的实例，请在 “/mcaiask” 后带上实例 ID 再问。"
    return (
        last_text.strip()
        or "在 8 步内未得到可确认的结论，请缩小问题范围或带上实例 ID 再问。"
    )
