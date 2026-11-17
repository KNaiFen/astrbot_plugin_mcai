import copy
import json
import re
import uuid

import aiohttp
from astrbot.core.agent.hooks import BaseAgentRunHooks
from astrbot.core.agent.message import Message
from astrbot.core.agent.runners.tool_loop_agent_runner import ToolLoopAgentRunner
from astrbot.core.agent.tool import FunctionTool, ToolSet
from astrbot.core.astr_agent_context import AgentContextWrapper, AstrAgentContext
from astrbot.core.astr_agent_tool_exec import FunctionToolExecutor
from astrbot.core.platform.astr_message_event import AstrMessageEvent
from astrbot.core.platform.astrbot_message import AstrBotMessage, MessageMember
from astrbot.core.platform.message_type import MessageType
from astrbot.core.platform.platform_metadata import PlatformMetadata
from astrbot.core.provider.entities import ProviderRequest
from jsonschema import ValidationError, validate
from pydantic.dataclasses import dataclass

from .agent_runtime import (
    TASK_POLICY,
    MainProvider,
    ModelUnavailable,
    ReviewCapacityError,
    Reviewer,
    ReviewInvalidated,
    check_review_feedback,
    effort_provider,
    model_request,
    progress_provider,
    request_provider,
    response_messages,
    search_provider,
)
from .client import RemoteError
from .context_budget import context_identity, fit_history, summary_messages, tokens
from .evidence import (
    evidence_view,
    read_scope,
    result_at,
    review_evidence,
    tool_evidence,
)
from .model_budget import budget_factor, record_usage
from .plans import plan_identity
from .review import REVIEW_VERSION, digest
from .tool_arguments import argument_error, arguments_for, model_continuations
from .tool_results import model_result
from .tool_schemas import TOOLS
from .tracing import traced_provider

PROMPT = (
    """你是Minecraft服务端运维与排障助手，使用中文，主动把当前任务推进到可核实的结果。
未绑定时按mc_instances说明用mc_select_instance选择目标，模糊才追问。按目标做最小必要查询，优先已有工具、spark和服务端命令，不手写已有通信或统计能力。
工具结果统一为ok/data及可选error/next_call。ok只表示调用成功，后台进展看data.status，data.complete仅说明读取范围是否完整，不是任务完成门槛。控制台pending_reads保留未读长行与后续页，按当前决定需要选择；完整页须读完全部待办。next_call是可采用的续读参数。失败按error.path修正，保留其他有效字段及error.details.evidence中的原证据引用；unknown沿原operation_id核实，不能另生成编号重放。
诊断用mc_exec或mc_console_send，由程序审核；修改、启停和保存用mc_propose整组审核并等待一次批准。外部脚本才申报script_files/script_encoding；文件修改先停服备份，脚本backup_paths覆盖实际写入。具体格式与示例见工具和规则。
工具结果的evidence_id可在受审调用的evidence_ids引用，程序从本任务读取真实参数、结果及采集目标作为依据；按本次需要引用，不用自行转述申报。先读summary和关键结果，以find定向定位必要原文，证据够用即推进；未读部分保持未核实。历史压缩不删除原记录，不为收齐无关原文反复分页。
产物和历史默认summary，result_path定向展开JSON字段；日志默认events归组，NBT优先children/selector/nbt_path。covered_by引用本轮已读重叠范围；缺省内容不当作不存在。context_capacity表示本次未执行且可恢复：根据largest_sources收窄相关证据、补取精确原值或拆分等价步骤，自动继续审核；保留有效参数、授权约束及原操作编号，不让管理员安排分页或重述任务。
需要根据结果分批决策时，首次mc_propose同时提交首批steps和continuation的允许范围、完成条件。批准后以plan_id提交后续批次，每批独立审核，无需重复批准；可在范围内调整命令或工具。先执行一批再观察，不因缺少单脚本循环入口而暂停。达到完成条件用mc_plan_finish结束方案，再报告并请求验收。改变目标、扩大范围或修复失败后须新提案重新批准。
只有确实缺用户信息时才用mc_say合并提问并给出“/mcaisay 任务名 内容”，然后结束本轮等待；无可行路径需管理员处理才mc_pause。已明确目标继续推进，不附加无关排障、数量上限或重复确认。
根据实际结果核实效果，请管理员使用“/mcaidone 任务名”验收。面向群的命令提示都用中文双引号括起完整命令及参数，用途说明放在引号外。执行进度使用commentary，最终结论和验收请求使用final，不用mc_say代发。使用Responses时，final通道对应消息phase:final_answer。面向用户的消息先说明当前动作或结论，再给必要依据和下一步；报告聚焦目标、实际动作、结果和待验收事项，工具字段、内部审查、代码和逐条日志留在本地记录。最终答复应独立完整，长消息由程序分段发送，必要结论、提问和方案说明完整保留。使用中文纯文本，收到补充继续按当前目标调整。
"""
    + TASK_POLICY
)


def clean_arguments(arguments):
    return {
        key: value
        for key, value in arguments.items()
        if key not in ("review", "script_files", "script_encoding", "evidence_ids")
    }


def clean_history(messages, *, copy_messages=True):
    result = copy.deepcopy(messages) if copy_messages else messages
    for message in result:
        for call in message.get("tool_calls") or []:
            function = call["function"]
            arguments = json.loads(function["arguments"])
            function["arguments"] = json.dumps(
                clean_arguments(arguments), ensure_ascii=False
            )
    return result


@dataclass
class McTool(FunctionTool):
    callback: object = None

    async def call(self, context, **kwargs):
        return await self.callback(self.name, kwargs)


class McToolSet(ToolSet):
    def get_tool(self, name):
        return super().get_tool(name) or McTool(
            name=name, description="", parameters={}, callback=self.tools[0].callback
        )

    def openai_schema(self, omit_empty_parameter_field=False):
        tools = super().openai_schema(omit_empty_parameter_field)
        for tool in tools:
            tool["function"]["strict"] = False
        return tools


class ResponseMessage(Message):
    response_messages: list[dict]


def load_message(item):
    kind = ResponseMessage if "response_messages" in item else Message
    return kind.model_validate(item)


class AstrBotAgent:
    def __init__(
        self,
        context,
        provider_id,
        max_steps,
        *,
        rules_path,
        review_rules_path=None,
        summary_rules_path=None,
        review_provider_id="",
        review_reasoning_effort="",
        forward_progress=False,
        enable_web_search=True,
        web_search_tool_type="web_search",
        reasoning_effort="",
        enable_alpha_search=False,
    ):
        self.context, self.provider_id, self.max_steps = context, provider_id, max_steps
        self.rules_path = rules_path
        self.review_rules_path = review_rules_path or rules_path
        self.summary_rules_path = summary_rules_path or rules_path
        self.attempts = 3
        self.forward_progress = forward_progress
        self.enable_web_search, self.web_search_tool_type = (
            enable_web_search,
            web_search_tool_type,
        )
        if web_search_tool_type not in ("web_search", "web_search_preview"):
            raise ValueError(
                "web_search_tool_type 仅支持 web_search 或 web_search_preview"
            )
        self.reviewer = Reviewer(
            context, review_provider_id, review_reasoning_effort, self.attempts
        )
        self.runners = {}
        self.requests = {}
        self.reasoning_effort = reasoning_effort
        self.enable_alpha_search = enable_alpha_search

    def rules(self):
        return self.rules_path.read_text(encoding="utf-8-sig")

    def review_rules(self):
        return self.review_rules_path.read_text(encoding="utf-8-sig")

    def summary_rules(self):
        return self.summary_rules_path.read_text(encoding="utf-8-sig")

    def rules_hash(self):
        return digest(
            {
                "task_policy": TASK_POLICY,
                "main": self.rules(),
                "review": self.review_rules(),
            }
        )

    def stop(self, job_id):
        runner = self.runners.get(job_id)
        if runner:
            runner.request_stop()

    def steer(self, job_id):
        provider = self.requests.get(job_id)
        if provider:
            provider.input_ready.set()

    async def prepare_apply(self, tasks, job):
        try:
            await tasks.client.request("GET", f"/operations/{job['operation']}")
            return True
        except RemoteError as exc:
            if not str(exc).startswith("HTTP 404:"):
                raise
        plan = job["applied_plan"]
        reviewed = plan.get("reviewed")
        approved_hash = None
        if plan.get("plan_id") or plan.get("continuation"):
            try:
                approved = tasks.require_plan(job, plan.get("plan_id", plan["id"]))
                approved_hash = approved["identity"]
            except ValueError:
                approved_hash = "invalid"
        if (
            not reviewed
            or reviewed.get("protocol_version") != REVIEW_VERSION
            or not plan.get("prepared")
            or reviewed["arguments_hash"] != plan_identity(plan)
            or reviewed["rules_hash"] != self.rules_hash()
            or (
                plan.get("plan_id")
                and reviewed.get("approved_plan_hash") != approved_hash
            )
            or approved_hash == "invalid"
            or (
                job.get("directory") is not None
                and plan.get("expected_directory") != job["directory"]
            )
        ):
            tasks.end_plan(job, "invalidated", "方案、审核或运行规则已变化")
            job["pending"].append(
                {
                    "sender": "system",
                    "text": "原修复方案尚未审核或规则已变化，尚未执行。请补齐用途和外部脚本材料，重新提交方案等待批准。",
                }
            )
            job["operation"] = None
            job["state"] = "running"
            tasks.save(job)
            return False
        return True

    async def run(self, tasks, job):
        rules = self.rules()
        review_rules = self.review_rules()
        summary_rules = self.summary_rules()
        queued_messages = set()
        current = None

        def result_budget():
            budget = job.get("context_budget", {})
            factor = budget_factor(tasks.store, budget_provider, "main")
            available = budget.get(
                "input_limit", budget.get("limit", 272000)
            ) / factor - budget.get("overhead_tokens", 0)
            usage = job.get("context_usage")
            if usage and usage["identity"] == context_identity(
                budget_provider, system, tool_definitions
            ):
                available = max(
                    available,
                    (
                        budget["input_limit"]
                        - usage["input_tokens"]
                        - usage["output_tokens"]
                    )
                    / factor,
                )
            return max(
                128,
                int(
                    available
                    * 0.65
                    / max(1, len(job.get("open_step", {}).get("calls", [])))
                ),
            )

        def reading_view(value):
            limit = 6000
            while True:
                view = evidence_view(value, limit)
                size = tokens(
                    [{"role": "user", "content": json.dumps(view, ensure_ascii=False)}]
                )
                if limit <= 256 or size <= result_budget() * 0.75:
                    return view
                limit = max(256, limit // 2)

        approved = tasks.active_plan(job)
        if approved:
            try:
                tasks.require_plan(job, approved["snapshot"]["plan"]["id"])
                if (
                    approved["snapshot"]["plan"]["reviewed"]["rules_hash"]
                    != self.rules_hash()
                ):
                    raise ValueError("运行规则已变化，请重新提案等待批准")
            except ValueError as exc:
                tasks.end_plan(job, "invalidated", str(exc))
                job["pending"].append({"sender": "system", "text": str(exc)})
                tasks.save(job)

        def track(result):
            if isinstance(result, dict) and result.get("id"):
                if result.get("status") in ("pending", "running"):
                    job.setdefault("background", {})[result["id"]] = {
                        "cursor": result.get("cursor", 0)
                    }
                else:
                    job.setdefault("background", {}).pop(result["id"], None)

        async def remote(record, action, arguments):
            if job.get("directory") and "operation" not in record:
                arguments = {**arguments, "expected_directory": job["directory"]}
            record.setdefault("operation", uuid.uuid4().hex)
            record["remote"] = {"action": action, "arguments": arguments}
            record["state"] = "submitted"
            record["instance"] = job["instance"]
            record["directory"] = job.get("directory")
            tasks.store.save("tool_call", record["id"], record)
            result = await tasks.client.call(
                job["instance"],
                action,
                arguments,
                operation_id=record["operation"],
                task_id=job["id"],
                stopped=lambda: job["stop_requested"],
            )
            track(result)
            return result

        async def execute(record):
            if record.get("state") == "completed":
                track(record["result"])
                return record["result"]
            name, arguments = record["name"], copy.deepcopy(record["arguments"])
            if (
                job["stop_requested"]
                or job["state"] == "paused"
                or (job["state"] == "waiting" and tasks.active_plan(job))
            ):
                result = {
                    "not_executed": True,
                    "error_code": "precondition_failed",
                    "execution_state": "not_executed",
                    "reason": "任务已停止、暂停或正在等待必要补充",
                }
                record.update(state="completed", result=result)
                tasks.store.save("tool_call", record["id"], record)
                return result
            schema = next((schema for tool, _, schema in TOOLS if tool == name), None)
            if schema is None:
                result = {
                    "not_executed": True,
                    "error_code": "unknown_tool",
                    "execution_state": "not_executed",
                    "reason": f"未知工具：{name}",
                }
            else:
                try:
                    validate(arguments, schema)
                    result = await invoke(
                        record,
                        arguments_for(name, clean_arguments(arguments), internal=True),
                    )
                except ValidationError as exc:
                    exc = argument_error(exc)
                    path = list(exc.absolute_path)
                    if exc.validator == "required":
                        path.append(
                            next(
                                key
                                for key in exc.validator_value
                                if key not in exc.instance
                            )
                        )
                    elif exc.validator == "additionalProperties":
                        path.append(
                            next(
                                key
                                for key in exc.instance
                                if key not in exc.schema["properties"]
                            )
                        )
                    result = {
                        "not_executed": True,
                        "error_code": "invalid_arguments",
                        "execution_state": "not_executed",
                        "path": path,
                        "error_details": {
                            "required_fields": exc.schema.get("required", []),
                            "allowed_fields": list(exc.schema.get("properties", {})),
                            "evidence": record["arguments"].get("evidence_ids", []),
                        },
                        "reason": f"工具参数错误（{'.'.join(map(str, path)) or '参数根节点'}）：{exc.message}",
                    }
                except ReviewInvalidated as exc:
                    result = {
                        "not_executed": True,
                        "error_code": "precondition_failed",
                        "execution_state": "not_executed",
                        "reason": str(exc),
                    }
                except ModelUnavailable:
                    raise
                except RemoteError as exc:
                    tasks.log(job, "tool_error", tool=name, error=str(exc))
                    operation = (
                        exc.operation
                        if record.get("operation")
                        and exc.operation
                        and exc.operation["id"] == record["operation"]
                        else None
                    )
                    state = (
                        "failed"
                        if operation
                        else "unknown"
                        if record.get("state") == "submitted"
                        else "not_executed"
                    )
                    result = {
                        "error_code": "operation_failed"
                        if operation
                        else "remote_error",
                        "error": str(exc),
                        "execution_state": state,
                        "not_executed": state == "not_executed",
                    }
                    if operation:
                        result["operation_record"] = operation
                except (
                    ValueError,
                    OSError,
                    aiohttp.ClientError,
                    TimeoutError,
                ) as exc:
                    error = f"{type(exc).__name__}: {exc}"
                    details = {"type": type(exc).__name__}
                    network_failure = isinstance(
                        exc, (aiohttp.ClientError, TimeoutError)
                    )
                    if name == "mc_web" and network_failure:
                        details.update(
                            url=str(
                                getattr(
                                    getattr(exc, "request_info", None),
                                    "real_url",
                                    arguments.get("url", ""),
                                )
                            ),
                            timeout_seconds=30,
                        )
                        if getattr(exc, "status", None) is not None:
                            details["http_status"] = exc.status
                    if exc.__cause__ is not None:
                        details["cause"] = (
                            f"{type(exc.__cause__).__name__}: {exc.__cause__}"
                        )
                    tasks.log(
                        job, "tool_error", tool=name, error=error, details=details
                    )
                    result = {
                        "not_executed": record.get("state") != "submitted",
                        "error_code": "precondition_failed"
                        if record.get("state") != "submitted" and not network_failure
                        else "remote_error",
                        "execution_state": "not_executed"
                        if record.get("state") != "submitted"
                        else "unknown",
                        "error": error,
                        "error_details": details,
                    }
            record.update(state="completed", result=result)
            tasks.store.save("tool_call", record["id"], record)
            return result

        async def invoke(record, arguments):
            name = record["name"]
            if record.get("remote"):
                return await remote(record, **record["remote"])
            if name == "mc_instances":
                return await tasks.instances()
            if name == "mc_select_instance":
                return await tasks.select_instance(job, **arguments)
            if name == "mc_history":
                return tasks.knowledge.query(arguments, job.get("directory"))
            if name == "mc_web":
                return await tasks.web.call(job["id"], arguments)
            if name == "mc_search":
                if not self.enable_alpha_search:
                    raise ValueError("独立搜索尚未启用，请在插件设置中测试并开启")
                from .search import task_search

                selected_id = (
                    self.provider_id
                    or await self.context.get_current_chat_provider_id(job["origin"])
                )
                selected = await self.context.provider_manager.get_provider_by_id(
                    selected_id
                )
                if selected is None:
                    raise ValueError("搜索提供商不存在")
                return await task_search(tasks, job, selected, arguments, record["id"])
            if job["instance"] is None and name not in ("mc_say", "mc_pause"):
                raise ValueError(
                    "尚未确定服务端，请 mc_instances 查看并 mc_select_instance 绑定；不确定时向群里追问"
                )
            if name == "mc_plan_finish":
                return tasks.finish_plan(job, **arguments)
            approved = None
            if name == "mc_propose" and arguments.get("plan_id"):
                # A crash after queueing must recover this batch, not queue it again.
                if (
                    record.get("batch_operation")
                    and job.get("applied_plan", {}).get("id") == record["id"]
                ):
                    return {
                        "status": "queued",
                        "plan_id": arguments["plan_id"],
                        "operation_id": record["batch_operation"],
                    }
                approved = tasks.require_plan(job, arguments["plan_id"])
                if job.get("operation") or job["state"] == "applying":
                    raise ValueError("当前批次尚未结算，请先读取结果")
                if (
                    approved["snapshot"]["plan"]["reviewed"]["rules_hash"]
                    != self.rules_hash()
                ):
                    tasks.end_plan(job, "invalidated", "运行规则已变化")
                    raise ValueError("运行规则已变化，请重新提案等待批准")
            approved_hash = approved["identity"] if approved else None
            needs_review = name in ("mc_exec", "mc_propose", "mc_console_send")
            decision = record.get("decision")
            if (
                needs_review
                and decision
                and (
                    decision["rules_hash"] != self.rules_hash()
                    or decision.get("protocol_version") != REVIEW_VERSION
                    or decision["arguments_hash"] != digest(arguments)
                    or decision.get("approved_plan_hash") != approved_hash
                )
            ):
                record.pop("decision", None)
            if needs_review and "decision" not in record:
                metadata = record["review"]
                commands = (
                    [
                        step["script"]
                        for step in arguments["steps"]
                        if step["action"] == "script"
                    ]
                    if name == "mc_propose"
                    else []
                    if name == "mc_console_send"
                    else [arguments["script"]]
                )
                material = await tasks.client.call(
                    job["instance"],
                    "review_material",
                    {
                        "cwd": arguments.get("cwd", "."),
                        "script_files": metadata["script_files"],
                        "encoding": metadata.get("encoding", "utf-8-sig"),
                        "commands": commands,
                        "diagnostic": name == "mc_exec",
                        **(
                            {"steps": arguments["steps"]}
                            if name == "mc_propose"
                            else {}
                        ),
                        "download_ids": [
                            step["download_id"]
                            for step in arguments.get("steps", [])
                            if step["action"] == "install_download"
                        ],
                        "export_ids": [
                            step["export_id"]
                            for step in arguments.get("steps", [])
                            if step["action"] == "region_restore"
                        ],
                        **(
                            {"expected_directory": job["directory"]}
                            if job.get("directory")
                            else {}
                        ),
                    },
                    task_id=job["id"],
                    operation_id=record["id"],
                )
                try:
                    decision = await self.reviewer.decide(
                        tasks,
                        job,
                        record,
                        review_rules,
                        material,
                        rules_hash=self.rules_hash(),
                    )
                except ReviewCapacityError as exc:
                    job.pop("model_retry", None)
                    tasks.save(job)
                    return {
                        "not_executed": True,
                        "error_code": "context_capacity",
                        "execution_state": "not_executed",
                        "reason": str(exc),
                        "error_details": {
                            "recoverable": True,
                            "largest_sources": exc.sources,
                        },
                    }
                except ValueError as exc:
                    tasks.pause(job, str(exc))
                    raise ModelUnavailable(str(exc)) from exc
                decision["protocol_version"] = REVIEW_VERSION
                decision["arguments_hash"] = digest(arguments)
                decision["approved_plan_hash"] = approved_hash
                record["decision"] = decision
                record["checks"] = [
                    {
                        key: item[key]
                        for key in ("path", "sha256", "steps", "planned")
                        if key in item
                    }
                    for item in material["scripts"]
                    if item.get("steps")
                ]
                record["review_configuration"] = material["configuration"]
                if name == "mc_propose":
                    record["effective_steps"] = material["effective_steps"]
                tasks.store.save("tool_call", record["id"], record)
            if needs_review:
                check_review_feedback(job, record)
                if job["stop_requested"] or job["state"] == "paused":
                    raise ReviewInvalidated("任务已停止或暂停，原调用未执行。")
                if record["decision"]["decision"] == "deny":
                    return {
                        "not_executed": True,
                        "error_code": "review_denied",
                        "execution_state": "not_executed",
                        "reason": "审核未通过：" + record["decision"]["reason"][:200],
                    }
                arguments["script_hashes"] = record["checks"]
                arguments["review_configuration"] = record["review_configuration"]
            if name == "mc_propose":
                checks = arguments.pop("script_hashes")
                configuration = arguments.pop("review_configuration")
                if approved:
                    tasks.require_plan(job, arguments["plan_id"])
                    record.setdefault("batch_operation", uuid.uuid4().hex)
                    tasks.store.save("tool_call", record["id"], record)
                tasks.propose(
                    job,
                    **arguments,
                    script_hashes=checks,
                    effective_steps=record["effective_steps"],
                    review_configuration=configuration,
                    proposal_id=record["id"],
                    operation_id=record.get("batch_operation"),
                    reviewed={
                        "call_id": record["id"],
                        "protocol_version": REVIEW_VERSION,
                        "rules_hash": record["decision"]["rules_hash"],
                        "approved_plan_hash": approved_hash,
                    },
                )
                if approved:
                    return {
                        "status": "queued",
                        "plan_id": arguments["plan_id"],
                        "operation_id": record["batch_operation"],
                    }
                return {
                    "status": "awaiting_approval",
                    "plan_id": record["id"],
                    "approval_command": f"/mcaiapply {job['name']}",
                }
            if name == "mc_say":
                tasks.message(job, arguments["text"])
                queued_messages.add(arguments["text"].strip())
                if tasks.active_plan(job):
                    job["state"] = "waiting"
                    tasks.save(job)
                return {"status": "queued"}
            if name == "mc_pause":
                tasks.pause(job, arguments["reason"])
                return {
                    "status": "paused",
                    "resume_command": f"/mcairesume {job['name']}",
                }
            if name in ("mc_console_read", "mc_console_line", "mc_console_send"):
                return await remote(
                    record,
                    "console_query"
                    if name != "mc_console_send"
                    else "diagnostic_command",
                    arguments,
                )
            if name in (
                "mc_region_nbt",
                "mc_region_blocks",
                "mc_region_check",
                "mc_region_export",
                "mc_region_scan",
            ):
                mode = (
                    arguments.pop("mode")
                    if name in ("mc_region_nbt", "mc_region_blocks")
                    else name.removeprefix("mc_region_")
                )
                if name == "mc_region_blocks":
                    mode = {"read": "block", "search": "blocks"}[mode]
                return await remote(
                    record,
                    {"scan": "region_scan", "export": "region_export"}.get(
                        mode, "region_query"
                    ),
                    arguments
                    if mode in ("scan", "export")
                    else {"mode": mode, **arguments},
                )
            if name in (
                "mc_job_read",
                "mc_job_wait",
                "mc_job_cancel",
                "mc_artifact_read",
                "mc_artifact_find",
                "mc_operation_read",
                "mc_context_history",
            ):
                if name == "mc_context_history":
                    if "entry" not in arguments:
                        rows = tasks.store.events(
                            "context_index:" + job["id"], arguments.get("after", 0), 20
                        )
                        cursor = rows[-1]["seq"] if rows else arguments.get("after", 0)
                        return {
                            "items": rows,
                            "cursor": cursor,
                            "next_cursor": cursor
                            if tasks.store.events(
                                "context_index:" + job["id"], cursor, 1
                            )
                            else None,
                        }
                    rows = tasks.store.events(
                        "context:" + job["id"], arguments["entry"] - 1, 1
                    )
                    if not rows or rows[0]["seq"] != arguments["entry"]:
                        raise ValueError("历史引用不属于当前任务")
                    value = result_at(rows[0]["body"], arguments.get("result_path", []))
                    if (
                        arguments.get(
                            "view", "value" if "offset" in arguments else "summary"
                        )
                        == "summary"
                    ):
                        return {
                            "view": "summary",
                            "entry": arguments["entry"],
                            "result_path": arguments.get("result_path", []),
                            "overview": reading_view(value),
                        }
                    text = json.dumps(value, ensure_ascii=False)
                    offset = arguments.get("offset", 0)
                    end = min(len(text), offset + 12000)
                    while (
                        end - offset > 32
                        and tokens(
                            [
                                {
                                    "role": "user",
                                    "content": json.dumps(
                                        {"text": text[offset:end]}, ensure_ascii=False
                                    ),
                                }
                            ]
                        )
                        > result_budget() * 0.75
                    ):
                        end = offset + max(32, (end - offset) // 2)
                    return {
                        "text": text[offset:end],
                        "next_offset": end if len(text) > end else None,
                    }
                if name == "mc_operation_read":
                    return await remote(
                        record,
                        "repair_log",
                        {
                            **arguments,
                            "operation": arguments["operation_id"],
                            "offset": arguments.get("offset", 0),
                        },
                    )
                mode = {
                    "mc_job_read": "read",
                    "mc_job_wait": "wait",
                    "mc_job_cancel": "cancel",
                    "mc_artifact_read": "artifact",
                    "mc_artifact_find": "find",
                }[name]
                if name == "mc_artifact_read":
                    arguments.setdefault(
                        "view", "value" if "offset" in arguments else "summary"
                    )
                return await remote(record, "job", {"mode": mode, **arguments})
            if name in (
                "mc_players",
                "mc_metrics",
                "mc_objects",
                "mc_chunks",
                "mc_runtime",
                "mc_profile",
                "mc_inspect",
            ):
                return await remote(record, "probe", {"kind": name[3:], **arguments})
            if name == "mc_logs":
                arguments.setdefault("view", "events")
            return await remote(
                record,
                {
                    "mc_status": "metrics",
                    "mc_diagnostics": "diagnostics",
                    "mc_verify": "verify",
                    "mc_inventory": "inventory",
                    "mc_files": "files_query",
                    "mc_logs": "logs",
                    "mc_exec": "exec",
                    "mc_nbt": "nbt_query",
                    "mc_download": "download",
                    "mc_mods": "mods",
                }[name],
                arguments,
            )

        request_snapshot = None

        def capture(response):
            if (
                request_snapshot is not None
                and response.usage is not None
                and response.usage.input > 0
            ):
                record_usage(
                    tasks.store,
                    budget_provider,
                    "main",
                    request_snapshot["estimated_tokens"],
                    response,
                )
                job["context_usage"] = {
                    **request_snapshot,
                    "input_tokens": response.usage.input,
                    "output_tokens": response.usage.output,
                }
            if not response.tools_call_name:
                tasks.save(job)
                return
            if job.get("open_step"):
                raise RuntimeError("前一工具步骤尚未结算")
            calls = []
            for key, name, arguments in zip(
                response.tools_call_ids,
                response.tools_call_name,
                response.tools_call_args,
            ):
                record = {
                    "id": uuid.uuid4().hex,
                    "call_id": key,
                    "task": job["id"],
                    "instance": job["instance"],
                    "directory": job.get("directory"),
                    "feedback_revision": len(job.get("feedback", [])),
                    "name": name,
                    "arguments": copy.deepcopy(arguments or {}),
                    "review": {
                        "script_files": (arguments or {}).get("script_files", []),
                        "encoding": (arguments or {}).get(
                            "script_encoding", "utf-8-sig"
                        ),
                    },
                    "state": "prepared",
                }
                tasks.store.save("tool_call", record["id"], record)
                calls.append(record["id"])
            parts = []
            if response.reasoning_content is not None or response.reasoning_signature:
                parts.append(
                    {
                        "type": "think",
                        "think": response.reasoning_content or "",
                        "encrypted": response.reasoning_signature,
                    }
                )
            if response.completion_text:
                parts.append({"type": "text", "text": response.completion_text})
            job["open_step"] = {
                "calls": calls,
                "content": parts or None,
                "response_messages": response_messages(response),
            }
            tasks.save(job)

        async def dispatch(name, arguments):
            record = tasks.store.get("tool_call", current)
            if record["name"] != name:
                raise RuntimeError("工具调用身份不匹配")
            await execute(record)
            return json.dumps(visible(record), ensure_ascii=False)

        def visible(record):
            if "model_result" not in record:
                record["model_result"] = model_continuations(
                    model_result(
                        record["name"],
                        arguments_for(
                            record["name"],
                            clean_arguments(record["arguments"]),
                            internal=True,
                        ),
                        record["result"],
                        record.get("operation"),
                    )
                )
                record["model_result"]["evidence_id"] = record["id"]
                if (
                    record["name"]
                    in ("mc_artifact_read", "mc_context_history", "mc_console_line")
                    and "text" in record["result"]
                ):
                    current_source = tool_evidence(record)
                    sources = []
                    for message in job["messages"]:
                        if message["role"] != "tool" or not isinstance(
                            message.get("content"), str
                        ):
                            continue
                        match = re.search(
                            r'"evidence_id"\s*:\s*"([a-f0-9]{32})"', message["content"]
                        )
                        if match:
                            previous = tasks.store.get("tool_call", match[1])
                            if previous and previous["id"] != record["id"]:
                                previous = tool_evidence(previous)
                                if read_scope(previous) == read_scope(current_source):
                                    sources.append(previous)
                    unique = review_evidence([*sources, current_source], 12000)[-1][
                        "result"
                    ]
                    if isinstance(unique, dict) and unique.get("covered_by"):
                        record["model_result"]["data"] = unique
                original = record["model_result"]
                if (
                    tokens(
                        [
                            {
                                "role": "tool",
                                "tool_call_id": record["call_id"],
                                "content": json.dumps(original, ensure_ascii=False),
                            }
                        ]
                    )
                    > result_budget()
                ):
                    entry = tasks.store.event(
                        "context:" + job["id"],
                        {
                            "tool": record["name"],
                            "arguments": clean_arguments(record["arguments"]),
                            "result": original,
                        },
                    )
                    tasks.store.event(
                        "context_index:" + job["id"],
                        {
                            "entry": entry,
                            "evidence_id": record["id"],
                            "tool": record["name"],
                        },
                    )
                    data = original["data"]
                    metadata = (
                        {
                            key: value
                            for key, value in data.items()
                            if key
                            in (
                                "job_id",
                                "operation_id",
                                "status",
                                "plan_id",
                                "cancelled",
                                "id",
                            )
                            and isinstance(value, (str, int, bool, type(None)))
                        }
                        if isinstance(data, dict)
                        else {}
                    )
                    record["model_result"] = {
                        **original,
                        "data": {
                            **metadata,
                            "complete": False,
                            "context_entry": entry,
                            "overview": reading_view(data),
                            "message": "原始结果按预算外置，先看overview，按目标读取必要字段；勿全文分页或重跑。",
                        },
                        "next_call": {
                            "name": "mc_context_history",
                            "arguments": {"entry": entry},
                        },
                    }
                    if "error" in original:
                        record["model_result"]["error"] = {
                            **{
                                key: value
                                for key, value in original["error"].items()
                                if key in ("code", "execution_state", "path")
                            },
                            "message": f"工具失败，完整错误见mc_context_history entry={entry}",
                        }
                    if (
                        tokens(
                            [
                                {
                                    "role": "tool",
                                    "tool_call_id": record["call_id"],
                                    "content": json.dumps(
                                        record["model_result"], ensure_ascii=False
                                    ),
                                }
                            ]
                        )
                        > result_budget()
                    ):
                        record["model_result"]["data"].pop("overview", None)
                        record["model_result"]["data"]["message"] = (
                            "原文已保存，按需定向读取。"
                        )
                tasks.store.save("tool_call", record["id"], record)
            return record["model_result"]

        async def recover_step():
            step = job.get("open_step")
            if not step:
                return
            records = []
            for key in step["calls"]:
                record = tasks.store.get("tool_call", key)
                if job["state"] == "paused" and record.get("state") != "completed":
                    return
                if (
                    record.get("state") != "completed"
                    and not record.get("remote")
                    and record.get("feedback_revision") != len(job.get("feedback", []))
                ):
                    record.update(
                        state="completed",
                        result={
                            "not_executed": True,
                            "error_code": "precondition_failed",
                            "execution_state": "not_executed",
                            "reason": "收到新反馈，原工具调用已失效，等待主模型重新判断",
                        },
                    )
                    tasks.store.save("tool_call", record["id"], record)
                else:
                    await execute(record)
                record = tasks.store.get("tool_call", key)
                if record.get("state") == "completed" and "model_result" not in record:
                    visible(record)
                    record = tasks.store.get("tool_call", key)
                if (
                    record["name"] == "mc_say"
                    and record.get("result", {}).get("status") == "queued"
                    and record.get("feedback_revision") == len(job.get("feedback", []))
                ):
                    queued_messages.add(record["arguments"]["text"].strip())
                records.append(record)
                if job["state"] == "paused":
                    break
            if len(records) != len(step["calls"]):
                return
            job["messages"].append(
                {
                    "role": "assistant",
                    "content": step["content"],
                    **(
                        {"response_messages": step["response_messages"]}
                        if step.get("response_messages")
                        else {}
                    ),
                    "tool_calls": [
                        {
                            "id": item["call_id"],
                            "type": "function",
                            "function": {
                                "name": item["name"],
                                "arguments": json.dumps(
                                    clean_arguments(item["arguments"]),
                                    ensure_ascii=False,
                                ),
                            },
                        }
                        for item in records
                    ],
                }
            )
            job["messages"].extend(
                {
                    "role": "tool",
                    "tool_call_id": item["call_id"],
                    "content": json.dumps(visible(item), ensure_ascii=False),
                }
                for item in records
            )
            job.pop("open_step", None)
            tasks.save(job)

        tools = McToolSet(
            [
                McTool(
                    name=name,
                    description=description,
                    parameters=schema,
                    callback=dispatch,
                )
                for name, description, schema in TOOLS
            ]
        )
        tool_definitions = tools.openai_schema()
        message = AstrBotMessage()
        message.type, message.group_id, message.message_id = (
            MessageType.GROUP_MESSAGE,
            job["group"],
            job["id"],
        )
        message.sender, message.message, message.message_str, message.self_id = (
            MessageMember(job["admin"]),
            [],
            "",
            "mcai",
        )
        event = AstrMessageEvent(
            "", message, PlatformMetadata("mcai", "MC 排障", "mcai"), job["group"]
        )
        provider_id = (
            self.provider_id
            or await self.context.get_current_chat_provider_id(job["origin"])
        )
        provider = await self.context.provider_manager.get_provider_by_id(provider_id)
        if provider is None:
            raise ValueError(f"模型提供商不存在：{provider_id}")
        if provider.provider_config.get("type") not in (
            "openai_chat_completion",
            "openai_responses",
        ):
            raise ValueError("排障模型仅支持 OpenAI 兼容 Chat／Responses 提供商")
        provider = effort_provider(provider, self.reasoning_effort)
        budget_provider = provider
        await recover_step()
        if queued_messages:
            pending = tasks.drain(job)
            if pending:
                job["messages"].append({"role": "user", "content": pending})
            job["state"] = "waiting"
            tasks.save(job)
            return
        if (
            job["state"] == "paused"
            or job["state"] in ("applying", "waiting")
            or job["stop_requested"]
            or (job["plan"] and not job["pending"])
        ):
            return
        provider = traced_provider(provider, tasks.store, job["id"], "排障模型")
        # MCAI owns task history and archival. Disable only the native runner's
        # request-time truncation on this private view, retaining the real budget.
        provider.provider_config["max_context_tokens"] = 0
        tasks.log(
            job,
            "progress_configuration",
            forward=self.forward_progress,
        )
        job["provider_id"] = provider_id
        tasks.save(job)
        search_note = ""
        if (
            self.enable_web_search
            and provider.provider_config.get("type") == "openai_responses"
        ):
            provider = search_provider(
                provider,
                self.web_search_tool_type,
                lambda error: tasks.log(job, "web_search_unavailable", error=error),
            )
        else:
            search_note = "\n当前未启用 API 托管搜索。mc_web 只能读取已知 URL。"
            tasks.log(
                job, "web_search_unavailable", reason="配置关闭或主提供商不是 Responses"
            )
        search_note += "\n独立搜索 mc_search " + (
            "可用，可用于搜索、打开来源和页内查找。"
            if self.enable_alpha_search
            else "未启用，不能使用。"
        )
        responses = provider.provider_config.get("type") == "openai_responses"
        forward = self.forward_progress and responses
        if responses:
            provider = progress_provider(
                provider,
                lambda key, text: tasks.progress(
                    job,
                    key,
                    text,
                    forward=self.forward_progress,
                ),
            )

        async def inject(kwargs, *, force=False):
            nonlocal request_snapshot
            pending = tasks.drain(job)
            if pending:
                wrapper.messages.append(Message(role="user", content=pending))
            job["messages"] = clean_history(
                [
                    item.model_dump(mode="json")
                    for item in wrapper.messages
                    if item.role != "system"
                ],
                copy_messages=False,
            )
            tasks.save(job)
            fitted = await fit_history(
                tasks,
                job,
                budget_provider,
                job["messages"],
                system,
                tools=tool_definitions,
                force=force,
                summary_rules=summary_rules,
            )
            wrapper.messages[:] = [
                *[item for item in wrapper.messages if item.role == "system"],
                *[load_message(item) for item in fitted],
            ]
            kwargs["contexts"] = list(wrapper.messages)
            request_snapshot = {
                "identity": context_identity(budget_provider, system, tool_definitions),
                "messages": len(fitted),
                "prefix": digest(fitted),
                "estimated_tokens": tokens([{"role": "system", "content": system}])
                + tokens(
                    [
                        {
                            "role": "system",
                            "content": json.dumps(tool_definitions, ensure_ascii=False),
                        }
                    ]
                )
                + tokens(fitted),
            }

        provider = MainProvider(
            provider, tasks, job, self.attempts, capture, inject=inject
        )
        system = (
            PROMPT
            + f"\n当前任务：{job['name']}；实例：{job['instance']}。\n规则文件：\n"
            + rules
            + search_note
        )
        system += (
            "\n当前待批准方案的程序状态："
            + json.dumps(
                {
                    "awaiting_approval": bool(job.get("plan")),
                    "proposal_id": (job.get("plan") or {}).get("id"),
                    "invalidated": job.get("proposal_invalidated"),
                },
                ensure_ascii=False,
            )
            + "。新的程序失效事件优先于历史提案文字；只有mc_propose返回awaiting_approval才表示已提交待批准方案。批准命令由程序在有效方案通知中提供。"
        )
        approved = tasks.active_plan(job)
        if approved:
            snapshot = approved["snapshot"]
            plan = snapshot["plan"]
            system += "\n当前已批准的多轮方案（原文和范围不得改写）：\n" + json.dumps(
                {
                    "plan_id": plan["id"],
                    "summary": plan["summary"],
                    "continuation": plan["continuation"],
                    "instance": snapshot["instance"],
                    "directory": snapshot["directory"],
                },
                ensure_ascii=False,
            )
        system += (
            "\n本轮执行进度汇报转发已开启。按规则文件中的通道约定和中途进度说明输出，commentary 会转发到群。不要输出推理过程或逐条工具日志，也不用 mc_say 重复发送进度。"
            if forward
            else "\n本轮执行进度汇报转发已关闭，commentary 仅保存本地，不通过 mc_say 绕过开关；必要提问和最终答复照常发送到群。"
        )
        wrapper = AgentContextWrapper(
            context=AstrAgentContext(context=self.context, event=event),
            tool_call_timeout=86400,
        )
        runner = ToolLoopAgentRunner()
        runner.EMPTY_OUTPUT_RETRY_ATTEMPTS = 1

        async def reset_runner():
            await runner.reset(
                provider=provider,
                request=ProviderRequest(
                    prompt=None,
                    contexts=job["messages"],
                    system_prompt=system,
                    func_tool=tools,
                ),
                run_context=wrapper,
                tool_executor=FunctionToolExecutor(),
                agent_hooks=BaseAgentRunHooks(),
                streaming=True,
                request_max_retries=1,
            )
            wrapper.messages[:] = [
                *[item for item in wrapper.messages if item.role == "system"],
                *[load_message(item) for item in job["messages"]],
            ]

        await reset_runner()
        self.runners[job["id"]] = runner
        self.requests[job["id"]] = provider
        final_text = ""
        try:
            for _ in range(self.max_steps):
                if (
                    runner.done()
                    or queued_messages
                    or job["state"] == "paused"
                    or job["stop_requested"]
                ):
                    break
                pending = tasks.drain(job)
                if pending:
                    wrapper.messages.append(Message(role="user", content=pending))
                job["messages"] = clean_history(
                    [
                        item.model_dump(mode="json")
                        for item in wrapper.messages
                        if item.role != "system"
                    ],
                    copy_messages=False,
                )
                tasks.save(job)
                async for event in runner.step():
                    if event.type == "tool_call" and job.get("open_step"):
                        call_id = event.data["chain"].chain[0].data["id"]
                        current = next(
                            key
                            for key in job["open_step"]["calls"]
                            if tasks.store.get("tool_call", key)["call_id"] == call_id
                        )
                if job["state"] == "paused" or job["stop_requested"]:
                    break
                response = provider.last_response
                if response and response.role == "err":
                    raise ModelUnavailable(response.completion_text)
                native = response_messages(response) if response else []
                final_text = provider.final_text if response else ""
                if native:
                    index = next(
                        i
                        for i in reversed(range(len(wrapper.messages)))
                        if wrapper.messages[i].role == "assistant"
                    )
                    wrapper.messages[index] = ResponseMessage.model_validate(
                        {
                            **wrapper.messages[index].model_dump(mode="json"),
                            "response_messages": native,
                        }
                    )
                serialized = clean_history(
                    [
                        item.model_dump(mode="json")
                        for item in wrapper.messages
                        if item.role != "system"
                    ],
                    copy_messages=False,
                )
                job["messages"] = serialized
                for item in wrapper.messages:
                    if item.tool_calls:
                        for call in item.tool_calls:
                            call.function.arguments = json.dumps(
                                clean_arguments(json.loads(call.function.arguments)),
                                ensure_ascii=False,
                            )
                job.pop("open_step", None)
                tasks.save(job)
                if job["plan"] or job["state"] in ("applying", "waiting"):
                    break
                if (
                    native
                    and not response.tools_call_name
                    and all(item.get("phase") == "commentary" for item in native)
                ):
                    await reset_runner()
            else:
                if (
                    not runner.done()
                    and not queued_messages
                    and not tasks.active_plan(job)
                    and not job["pending"]
                ):
                    tasks.message(
                        job,
                        f"本轮排查已达步数上限，记录已保存。群成员可用 “/mcaisay {job['name']} 内容” 补充线索继续。",
                    )
            response = runner.get_final_llm_resp()
            if (
                response
                and final_text
                and response.role != "err"
                and final_text.strip() not in queued_messages
                and not job["plan"]
                and not job["stop_requested"]
                and job["state"] != "paused"
            ):
                if job.get("proposal_invalidated") and not job.get("plan"):
                    final_text += "\n【程序状态】原待批准方案已因补充失效，当前没有可批准方案；需要修改时须重新提案。"
                tasks.message(job, final_text)
        finally:
            self.runners.pop(job["id"], None)
            self.requests.pop(job["id"], None)
            tasks.log(
                job,
                "agent_context",
                budget=job.get("context_budget"),
                messages=len(job["messages"]),
            )

    async def summarize(self, tasks, job):
        provider_id = (
            job.get("provider_id")
            or self.provider_id
            or await self.context.get_current_chat_provider_id(job["origin"])
        )
        provider = await self.context.provider_manager.get_provider_by_id(provider_id)
        if provider is None:
            raise ValueError(f"总结模型提供商不存在：{provider_id}")
        summary_rules = self.summary_rules()
        history = clean_history(job["messages"])
        history.extend(
            {
                "role": "user",
                "content": "补充记录：" + json.dumps(item, ensure_ascii=False),
            }
            for item in [*job["feedback"], *job.get("repairs", [])]
        )
        payload = {
            "task": job["name"],
            "directory": job["directory"],
            "report": job["report"],
            "verification": "管理员已验收；具体效果以保存的反馈和工具事实为准",
        }
        system = (
            "你整理已验收的 MC 运维与排障经验，不执行工具。用中文 Markdown 分节记录：任务目标与环境、依据或故障原因、实际操作、失败尝试、备份与恢复线索、验证结果、适用条件、来源。只写事实，不臆测；日常运维无故障时不编造症状或原因，故障原因未知就写未知，不能把管理员验收当成所有推测已证实。不含审核申报或审核响应。\n"
            + TASK_POLICY
            + summary_rules
        )
        identity = digest(
            {
                "provider": context_identity(provider, system, None),
                "payload": payload,
                "history": history,
            }
        )
        prepared = tasks.store.get("archive_input", job["id"])
        if prepared and prepared["identity"] == identity:
            history = prepared["messages"]

        async def prepare(error=None):
            nonlocal history
            history = await fit_history(
                tasks,
                job,
                provider,
                history,
                system,
                archive=True,
                force=error is not None,
                payload=payload,
                summary_rules=summary_rules,
            )
            tasks.store.save(
                "archive_input", job["id"], {"identity": identity, "messages": history}
            )

        selected = traced_provider(
            request_provider(provider), tasks.store, job["id"], "验收总结"
        )

        async def summarize():
            return await selected.text_chat(
                prompt=json.dumps(
                    {**payload, "messages": summary_messages(history)},
                    ensure_ascii=False,
                ),
                contexts=[],
                func_tool=None,
                request_max_retries=1,
                system_prompt=system,
            )

        if prepared is None or prepared["identity"] != identity:
            await prepare()
        response = await model_request(
            tasks,
            job,
            "验收总结",
            summarize,
            1,
            pause_on_error=False,
            recover_context=prepare,
            check_stop=False,
            summary=True,
        )
        record_usage(
            tasks.store,
            provider,
            "archive",
            tokens(
                [
                    {"role": "system", "content": system},
                    {
                        "role": "user",
                        "content": json.dumps(
                            {**payload, "messages": summary_messages(history)},
                            ensure_ascii=False,
                        ),
                    },
                ]
            ),
            response,
        )
        return response.completion_text or ""
