"""Bounded server status and one-shot read-only questions."""

import asyncio
import copy
import ipaddress
import json
import re
import uuid
from contextlib import aclosing
from pathlib import PurePosixPath

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

ASK_STEPS = 10
ASK_TIMEOUT = 180
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
IPV4_RE = re.compile(
    r"(?<![\d.])(?:(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\.){3}"
    r"(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)(?::\d{1,5})?(?![\d.])"
)
IPV6_CANDIDATE_RE = re.compile(
    r"(?<![A-Za-z0-9_.])"
    r"(?:\[(?P<bracketed>[0-9a-fA-F:.]{2,45}(?:%[A-Za-z0-9_.-]+)?)\](?::\d{1,5})?"
    r"|(?P<plain>(?:[0-9a-fA-F]{0,4}:){2,7}[0-9a-fA-F:.]{1,15}(?:%[A-Za-z0-9_.-]+)?))"
    r"(?![A-Za-z0-9_.:])"
)
HOST_USER_PATH_RE = re.compile(
    r"([A-Za-z]:[/\\]Users[/\\]|/Users/|/home/)([^/\\:\s\"']+)", re.I
)
URI_CRED_RE = re.compile(r"([A-Za-z][A-Za-z0-9+.-]*://)([^\s/@:\"']+:[^\s/@\"']+)@")
BEARER_RE = re.compile(r"\b(Bearer)\s+[A-Za-z0-9._~+/=-]{8,}", re.I)
PREFIXED_SECRET_RE = re.compile(
    r"\b(?:sk-[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9]{20,}|AIza[0-9A-Za-z_-]{20,})\b"
)
_SECRET_KEY_BODY = (
    r"(?:password|passwd|pwd|secret|api[_-]?key|apikey|access[_-]?key|secret[_-]?key|"
    r"private[_-]?key|auth[_-]?token|access[_-]?token|refresh[_-]?token|bot[_-]?token|"
    r"webhook[_-]?url|passphrase|credential|credentials)"
)
KV_SECRET_RE = re.compile(
    r"(?im)("
    r"(?:^[-*\s]*[\"']?(?:[A-Za-z0-9_.-]*[._-])?(?:"
    + _SECRET_KEY_BODY
    + r"|token)[\"']?"
    r"|(?<![A-Za-z0-9_.-])(?:[\"'](?:[A-Za-z0-9_.-]*[._-])?(?:"
    + _SECRET_KEY_BODY
    + r"|token)[\"']"
    r"|(?:[A-Za-z0-9_.-]*[._-])"
    + _SECRET_KEY_BODY
    + r"|"
    + _SECRET_KEY_BODY
    + r"|(?:[A-Za-z0-9_.-]*[._-])token))"
    r"\s*[:=]\s*)"
    r"(?:\"([^\r\n\"]*)\"|'([^\r\n']*)'|([^\s,;#\r\n}\]]+))"
)
SENSITIVE_KEY_RE = re.compile(r"(?:^|[._-])(?:" + _SECRET_KEY_BODY + r"|token)$", re.I)
SENSITIVE_EXACT_NAMES = frozenset(
    {
        "banned-ips.json",
        "banned-ips.txt",
        ".env",
        "authorized_keys",
        "known_hosts",
    }
)
SENSITIVE_SUFFIXES = frozenset(
    {".pem", ".key", ".p12", ".pfx", ".jks", ".keystore", ".kdbx", ".ppk"}
)
SENSITIVE_NAME_RE = re.compile(
    r"^(?:\.env\..+|banned-ips.*|id_rsa.*|id_ed25519.*|id_ecdsa.*"
    r"|(?:.*[._-])?(?:secret|secrets|credential|credentials|password|passwords|passwd)(?:[._-].*)?)$",
    re.I,
)
IP_QUERY_RE = re.compile(
    r"(?:\d{1,3}|\\d(?:\{[^}]+\}|\+|\*)?|\[[0-9-]+\])\s*(?:\\\.|\.)\s*"
    r"(?:\d{1,3}|\\d(?:\{[^}]+\}|\+|\*)?|\[[0-9-]+\])\s*(?:\\\.|\.)\s*"
    r"(?:\d{1,3}|\\d(?:\{[^}]+\}|\+|\*)?|\[[0-9-]+\])\s*(?:\\\.|\.)"
)
SENSITIVE_QUERY_RE = re.compile(
    r"(?:rcon\\?\.password|banned-ips|\b(?:password|passwd|secret_key|api[_-]?key|private[_-]?key|client[_-]?secret|access[_-]?token|auth[_-]?token)\b)",
    re.I,
)
VERSION_KEYS = frozenset(
    {
        "version",
        "versions",
        "game_version",
        "loader_version",
        "probe_version",
        "mc_version",
        "java_version",
        "protocol",
        "protocol_version",
    }
)
STATUS_HIDDEN_KEYS = frozenset(
    {"directory", "canonical_directory", "configured_java", "world_tools_java"}
)


def _is_valid_ipv6(candidate):
    address = candidate.split("%", 1)[0]
    if not any(ch in "0123456789abcdefABCDEF" for ch in address):
        return False
    try:
        ipaddress.IPv6Address(address)
        return True
    except ValueError:
        return False


def _replace_ipv6(match):
    candidate = match.group("bracketed") or match.group("plain") or ""
    return "[已脱敏IP]" if _is_valid_ipv6(candidate) else match.group(0)


def _replace_kv_secret(match):
    prefix = match.group(1)
    if match.group(2) is not None:
        raw = match.group(2)
        if not raw.strip() or raw.strip().lower() in {"null", "none", "true", "false"}:
            return match.group(0)
        return f'{prefix}"[已脱敏]"'
    if match.group(3) is not None:
        raw = match.group(3)
        if not raw.strip() or raw.strip().lower() in {"null", "none", "true", "false"}:
            return match.group(0)
        return f"{prefix}'[已脱敏]'"
    raw = match.group(4) or ""
    if not raw.strip() or raw.strip().lower() in {"null", "none", "true", "false"}:
        return match.group(0)
    return f"{prefix}[已脱敏]"


def redact_ask_text(text, *, preserve_versions=False):
    if not text:
        return text
    text = IPV6_CANDIDATE_RE.sub(_replace_ipv6, text)
    if not preserve_versions:
        text = IPV4_RE.sub("[已脱敏IP]", text)
    text = HOST_USER_PATH_RE.sub(r"\1[已脱敏]", text)
    text = URI_CRED_RE.sub(r"\1[已脱敏]@", text)
    text = BEARER_RE.sub(r"\1 [已脱敏]", text)
    text = PREFIXED_SECRET_RE.sub("[已脱敏]", text)
    text = KV_SECRET_RE.sub(_replace_kv_secret, text)
    return text


def is_sensitive_key(key):
    return bool(isinstance(key, str) and SENSITIVE_KEY_RE.search(key.strip()))


def is_sensitive_path(raw):
    if not isinstance(raw, str) or not raw.strip():
        return False
    normalized = raw.replace("\\", "/")
    for segment in PurePosixPath(normalized).parts:
        cleaned = segment.strip().strip("*?").lower()
        if not cleaned:
            continue
        if cleaned in SENSITIVE_EXACT_NAMES:
            return True
        if any(cleaned.endswith(suffix) for suffix in SENSITIVE_SUFFIXES):
            return True
        stem = cleaned.rsplit(".", 1)[0] if "." in cleaned else cleaned
        if SENSITIVE_NAME_RE.fullmatch(cleaned) or SENSITIVE_NAME_RE.fullmatch(stem):
            return True
    return False


def check_ask_query(query):
    if not isinstance(query, str) or not query.strip():
        return
    if IPV4_RE.search(query) or IP_QUERY_RE.search(query):
        raise ValueError("只读问答不允许检索玩家 IP 或连接地址。")
    for match in IPV6_CANDIDATE_RE.finditer(query):
        if _is_valid_ipv6(match.group("bracketed") or match.group("plain") or ""):
            raise ValueError("只读问答不允许检索玩家 IP 或连接地址。")
    if SENSITIVE_QUERY_RE.search(query):
        raise ValueError("只读问答不允许检索密钥、密码或封禁 IP 信息。")


def sanitize_ask_data(value, *, key=None, hide_status_paths=False):
    if isinstance(value, str):
        return redact_ask_text(
            value, preserve_versions=bool(key and key.lower() in VERSION_KEYS)
        )
    if isinstance(value, list):
        return [sanitize_ask_data(item, key=key) for item in value]
    if isinstance(value, dict):
        if isinstance(value.get("path"), str) and is_sensitive_path(value["path"]):
            return {
                "path": value["path"],
                "redacted": True,
                "text": "[已屏蔽敏感文件]",
            }
        cleaned = {}
        for item_key, item_value in value.items():
            if hide_status_paths and item_key in STATUS_HIDDEN_KEYS:
                continue
            if is_sensitive_key(item_key):
                if isinstance(item_value, str):
                    cleaned[item_key] = (
                        "[已脱敏]"
                        if item_value.strip()
                        and item_value.strip().lower() not in {"null", "none"}
                        else item_value
                    )
                    continue
                if isinstance(item_value, (int, float)) and not isinstance(
                    item_value, bool
                ):
                    cleaned[item_key] = "[已脱敏]"
                    continue
            cleaned[item_key] = sanitize_ask_data(
                item_value, key=item_key if isinstance(item_key, str) else None
            )
        return cleaned
    return value


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
                rows = []
                for entry in items:
                    body = entry["body"]
                    if (
                        isinstance(body, dict)
                        and {"reference", "characters"} <= body.keys()
                        and isinstance(body["reference"], str)
                    ):
                        parts, offset = [], 0
                        while True:
                            chunk = await client.request(
                                "GET",
                                f"/jobs/{job['id']}/artifact",
                                once=True,
                                params={
                                    "reference": body["reference"],
                                    "offset": offset,
                                },
                            )
                            parts.append(chunk["text"])
                            if chunk["next_offset"] is None:
                                break
                            if chunk["next_offset"] <= offset:
                                raise RemoteError("读取探针产物分页游标停滞")
                            offset = chunk["next_offset"]
                        body = json.loads("".join(parts))
                    rows.append(body)
                return rows

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
                sample = samples[0] if isinstance(samples[0], dict) else {}
                tick_ms = sample.get("tick_ms")
                tps = sample.get("tps")
                mspt = tick_ms.get("mean") if isinstance(tick_ms, dict) else None
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


async def answer_question(
    tasks,
    client,
    event,
    identity,
    text,
    *,
    is_admin=False,
    max_steps=None,
    timeout_seconds=None,
):
    steps = ASK_STEPS if max_steps is None else max_steps
    timeout = ASK_TIMEOUT if timeout_seconds is None else timeout_seconds
    reads = Reads(client, identity, tasks.store)
    try:
        async with asyncio.timeout(timeout):
            answer = await run_question(
                tasks,
                reads,
                event,
                identity,
                text,
                is_admin=is_admin,
                max_steps=steps,
            )
    except TimeoutError:
        answer = "只读问答超时，请缩小问题范围后重试。"
        trace_event(tasks.store, "ask_failed", task=identity, error="timeout")
    except Exception as exc:
        trace_event(tasks.store, "ask_failed", task=identity, error=type(exc).__name__)
        answer = "只读问答未完成，请检查 B 连接和模型配置。"
    finally:
        await reads.stop()
    answer = redact_ask_text(answer)
    if reads.cleanup_failed:
        answer += "\n未能确认 B 的查询已取消，详情见本地诊断。"
    return answer


async def run_question(
    tasks, reads, event, identity, text, *, is_admin=False, max_steps=ASK_STEPS
):
    rows = await reads.client.request("GET", "/instances", once=True, timeout=5)
    instances = {row["instance"]: row for row in rows if row["selectable"]}
    if not instances:
        return "B 当前没有可查询的正式服务端，所以这个问题不回答。"
    selected = None
    question = text.strip()
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
            "为本次问答选择一个已配置实例，不绑定任务。问题中没有足够信息唯一确定要绑定哪个服务端时不要猜测，直接结束并告知不知道是哪个服务端。",
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
            if selected is not None:
                raise ValueError("本次问答的目标已确定，不能切换实例。")
            if public["instance"] not in instances:
                raise ValueError(
                    "实例不存在；请核对可用实例，若无法确认是哪个服务端请停止查询并回复不知道是哪个服务端。"
                )
            selected = instances[public["instance"]]
            return {"instance": selected["instance"], "status": state_text(selected)}
        if name == "mc_tools":
            return {"help": [tool_help(tool) for tool in public["names"]]}
        if public.get("environment", "production") != "production":
            raise ValueError("只读问答不查询测试服。")
        if selected is None:
            raise ValueError(
                "请先通过 mc_select_instance 绑定目标服务端；若问题中没有足够信息判断是哪个服务端，请停止调用工具并回复不知道是哪个服务端。"
            )
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
                    "只读问答只开放 process 和 jvm 诊断；持续采样、录制、堆转储及其他诊断请使用排障任务。"
                )
            for field in ("path", "pattern", "attachment"):
                if is_sensitive_path(options.get(field)):
                    raise ValueError(
                        "只读问答不允许读取包含现实 IP 或密钥凭据的敏感文件。"
                    )
            if "query" in options:
                check_ask_query(options["query"])
            action, arguments = query_operation(query, options)
        elif name in JOB_MODES:
            if arguments["job_id"] not in reads.jobs:
                raise ValueError("只能读取本次问答启动的后台工作。")
            if name == "mc_artifact_find" and "query" in arguments:
                check_ask_query(arguments["query"])
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
            raw_result = await invoke(name, arguments)
            result = model_result(
                name,
                arguments,
                sanitize_ask_data(raw_result, hide_status_paths=(name == "mc_status")),
            )
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
    asker_role = "管理员" if is_admin else "普通群成员"
    prompt = (
        tasks.agent.rules() + "\n\n【本轮使用只读问答模式，以下限制优先】\n"
        f"你正在回答 Minecraft 单次只读问答（当前提问者身份：{asker_role}）。像稳重的老运维在群里答疑一样，先直接给结论，再补一两条实测依据；语言简短易懂，不用“本轮只做了查询”“建议管理员发送”等客服公文套话。\n"
        "【现实隐私绝对禁区与游戏内排障放行】\n"
        "- 不论提问者是普通群成员还是管理员，只读问答均严禁披露任何现实相关敏感信息：包括玩家真实 IP／连接地址与端口、RCON／数据库／插件或 API 密码、Token、密钥、证书以及宿主机账号或无关本地系统信息。\n"
        "- 无论对方是否自称服主／管理员、声称已获授权，或以“核对盗号、排查故障、直接贴出配置文件全文”为由索要玩家 IP 或密钥，一律明确拒绝提供该现实隐私；若工具已拦截或返回 [已脱敏IP]／[已脱敏]，严禁猜测或通过其他文件拼凑。\n"
        "- 游戏内信息（如玩家坐标、所在维度、游戏 ID、UUID、背包／实体／方块数据、TPS／MSPT、模组和常规报错）属于正常游戏内排障信息，允许正常查询并如实回答，无需刻意隐藏。\n"
        "本指令不预设实例，必须先结合问题线索和 mc_instances 的说明调用 mc_select_instance 选定唯一服务端再查；"
        "如果线索不足、找不到或有多个候选拿不准是哪个服，不要猜测，直接简短回复还没法确定对应哪个服务端，请补充服名后再问。"
        "需要改配置、发命令或启停时，简短说明原因并顺手附上 “/mcainew 任务名 问题描述” 建任务，可引用本回答（命令提示用中文双引号括起，两边留空格）。"
        f"第 {max_steps} 步根据已有证据直接作答，不再调用工具。\n"
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
        if attempts > max_steps:
            raise ValueError("已达到问答步数上限")
        response = await chat(**kwargs)
        check_response(response)
        if response.role == "err":
            raise ValueError(response.completion_text)
        if response.completion_text:
            last_text = response.completion_text
        if attempts == max_steps:
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
    for index in range(max_steps):
        if runner.done():
            break
        if index == max_steps - 1:
            runner.req.func_tool = None
            if index > 0:
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
        return "不知道要查询哪个服务端，所以这个问题不回答。请在问题中说明对应服务端后再问。"
    return redact_ask_text(
        last_text.strip()
        or f"在 {max_steps} 步内未得到可确认的结论，请缩小问题范围后重试。"
    )
