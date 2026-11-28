import asyncio
import difflib
import hashlib
import json
import math
import re
import shutil
import sqlite3
import time
import uuid
from datetime import datetime
from pathlib import Path

import aiohttp
from astrbot.api import AstrBotConfig
from astrbot.api.event import AstrMessageEvent, MessageChain, filter
from astrbot.api.message_components import At, Node, Nodes, Plain, Reply
from astrbot.api.star import Context, Star
from astrbot.core.utils.astrbot_path import get_astrbot_data_path

from .mcai.astrbot_agent import AstrBotAgent
from .mcai.attachments import message_attachments, receive_attachments, recognize_image
from .mcai.client import HostClient, RemoteError
from .mcai.configuration import allowed_group_ids, incident_routes, powershell_path
from .mcai.downloads import Downloads
from .mcai.jobs import Jobs
from .mcai.memory_job import MemoryJob
from .mcai.model_usage import parse_prices, task_usage
from .mcai.monthly_logs import A_LOGS, rotate
from .mcai.paths import workspace_root
from .mcai.plans import approval_command, plan_sections, schedule_time
from .mcai.readonly import answer_question, server_status
from .mcai.runtime_rules import install_rules
from .mcai.storage import Store
from .mcai.tasks import (
    FORCE_ACTIONS,
    SERVER_ACTIONS,
    Tasks,
    space_commands,
)
from .mcai.tracing import trace_event
from .mcai.workspace import Workspace

COMMANDS = {
    "mcainew",
    "mcaisay",
    "mcaisaymode",
    "mcaiapply",
    "mcaistop",
    "mcaidone",
    "mcaistatus",
    "mcaihelp",
    "mcairesume",
    "mcailist",
    "mcaiplan",
    "mcaipause",
    "mcaiserver",
    "mcaiswitch",
    "mcaiask",
    "mcaischedule",
}
GROUP_MESSAGE_PART_LIMIT = 1800
DEFAULT_GROUP_FORWARD_THRESHOLD = 400
MAX_INCIDENT_NOTIFY_AGE = 1800
MAX_INCIDENT_BATCH_LINES = 8
ACK_EMOJI_ID = "476"
HELP_TEXT = (
    "MCAI 群命令指南\n"
    "说明：任务名不含空格、最多 40 字；命令与参数间留空格；有唤醒前缀限制时请带前缀（默认 / ）或 @Bot。\n"
    "\n"
    "【快速查询（不建任务）】\n"
    "• 查服务端状态（群成员，不调用模型）：\n"
    "  “/mcaiserver [实例ID]” （例： “/mcaiserver” 或 “/mcaiserver cti” ）\n"
    "• 只读 AI 问答（默认仅管理员，不改文件不发命令）：\n"
    "  “/mcaiask 问题” （例： “/mcaiask cti服现在 TPS 为什么下降了？” ）\n"
    "\n"
    "【创建任务与补充线索】\n"
    "• 创建任务（管理员）：\n"
    "  “/mcainew 任务名 问题描述” （例： “/mcainew 主城卡顿 cti服昨天更新后一直掉TPS” ）\n"
    "  也可回复/引用玩家消息后发送 “/mcainew 任务名 [补充说明]” ；任务名后的整段文字均作为内容，支持空格和换行，也可以直接附上或引用群文件和图片。\n"
    "• 补充线索／继续排查（群成员）：\n"
    "  “/mcaisay 任务名 内容” （例： “/mcaisay 主城卡顿 坐标 120 65 -300 附近复现” ）\n"
    "  支持空格、换行及附带或引用群文件和图片；任务卡住、需要补条件或继续下达方向时都可用它推进。\n"
    "• 控制成员补充（管理员）：\n"
    "  “/mcaisaymode 任务名 false” （暂停普通成员补充）\n"
    "  “/mcaisaymode 任务名 true” （恢复开启；管理员始终可用 “/mcaisay 任务名 内容” ）\n"
    "\n"
    "【查看进度、方案与定时计划】\n"
    "• 活动任务列表（群成员）： “/mcailist [页码]” （省略页码默认第 1 页）\n"
    "• 任务进度与用量（群成员）： “/mcaistatus 任务名”\n"
    "• 待批或已批方案（群成员）： “/mcaiplan 任务名”\n"
    "• 查看定时计划（群成员）： “/mcaischedule list”\n"
    "• 管理定时计划（管理员）： “/mcaischedule pause|resume|delete 编号” （编号从 list 获取）\n"
    "\n"
    "【审批与任务控制（仅管理员）】\n"
    "• 直接启停正式服：“/mcaiswitch 实例ID start|stop|restart|forcestop|forcerestart [confirm]” （强制动作先不带 confirm，按提示确认；实例 ID 用 “/mcaiserver” 查询）。\n"
    "• 批准待执行方案： “/mcaiapply 任务名 短码” （例： “/mcaiapply 主城卡顿 9F2A7C” ）\n"
    "• 暂停任务进度： “/mcaipause 任务名” （保留服务端占用与进度）\n"
    "• 续接暂停任务： “/mcairesume 任务名” （会一并读取暂停期间保存的补充）\n"
    "• 中止任务： “/mcaistop 任务名” （停止排查并释放服务端，不归档经验）\n"
    "• 验收完成： “/mcaidone 任务名” （确认已解决或确认结束并后台归档经验）\n"
    "\n"
    "【帮助】\n"
    "• 查看本帮助： “/mcaihelp”"
)


def command_typo_message(text):
    """Return a helpful correction hint for mistyped /mcai... commands, or None."""
    raw = text.strip()
    has_slash = raw.startswith("/")
    stripped = raw.removeprefix("/")
    if not stripped:
        return None
    head, *rest = stripped.split(maxsplit=1)
    tail = rest[0] if rest else ""
    if head in COMMANDS:
        if not has_slash:
            return None
        corrected = f"/{head} {tail}".strip() if tail else f"/{head}"
        return f"多输入了一个 / （或 @Bot 时无需再加 /），请发送 “{corrected}” 。"
    lower_head = head.lower()
    if lower_head == "mcai":
        if not tail:
            return (
                "请在 mcai 后直接接子命令（不加空格），例如查看帮助请发送 “/mcaihelp” ，"
                "查看服务端状态请发送 “/mcaiserver” 。"
            )
        sub, *more = tail.split(maxsplit=1)
        candidate = "mcai" + sub.lower()
        if candidate in COMMANDS:
            suggestion = f"/{candidate} {more[0]}".strip() if more else f"/{candidate}"
            return (
                f"MCAI 指令中间不加空格，你想使用的是不是 “{suggestion}” ？\n"
                "发送 “/mcaihelp” 可查看全部指令格式。"
            )
        if sub.isascii():
            close = difflib.get_close_matches(candidate, COMMANDS, n=2, cutoff=0.6)
            if close:
                guesses = " 或 ".join(f"“/{item}”" for item in close)
                return (
                    f"没有 “/{head} {sub}” 这个指令（指令名间不加空格）。"
                    f"你是不是想用 {guesses} ？发送 “/mcaihelp” 可查看全部指令。"
                )
        return (
            "请使用具体 MCAI 指令，例如查状态用 “/mcaiserver” ，建任务用 “/mcainew 任务名 问题描述” ；"
            "发送 “/mcaihelp” 可查看全部指令。"
        )
    if lower_head in COMMANDS:
        corrected = f"/{lower_head} {tail}".strip() if tail else f"/{lower_head}"
        return f"指令区分大小写，请使用全小写： “{corrected}” 。"
    matched = next(
        (
            cmd
            for cmd in sorted(COMMANDS, key=len, reverse=True)
            if lower_head.startswith(cmd)
        ),
        None,
    )
    if matched:
        after = stripped[len(matched) :]
        if matched == "mcaihelp":
            return "直接发送 “/mcaihelp” 即可查看全部命令帮助（后面无需附加字符）。"
        return (
            f"指令和参数之间需要加空格，例如 “/{matched} {after}” 。\n"
            "发送 “/mcaihelp” 可查看完整用法。"
        )
    if lower_head.startswith("mcai") and re.fullmatch(r"mcai[a-z0-9_-]*", lower_head):
        close = difflib.get_close_matches(lower_head, COMMANDS, n=2, cutoff=0.55)
        if close:
            guesses = " 或 ".join(f"“/{item}”" for item in close)
            return (
                f"没有 “/{head}” 这个指令。你是不是想用 {guesses} ？\n"
                "发送 “/mcaihelp” 可查看全部可用指令。"
            )
        return f"没有 “/{head}” 这个指令。请发送 “/mcaihelp” 查看全部可用指令。"
    return None


class McaiCommandAttemptFilter(filter.CustomFilter):
    """Match woke group messages that appear to be mistyped mcai commands."""

    def filter(self, event: AstrMessageEvent, cfg) -> bool:
        if not event.is_at_or_wake_command:
            return False
        return command_typo_message(event.get_message_str()) is not None


def message_parts(text):
    offset = 0
    while offset < len(text):
        end = min(offset + GROUP_MESSAGE_PART_LIMIT, len(text))
        if end < len(text):
            boundary = text.rfind("\n", offset, end)
            if boundary > offset:
                end = boundary + 1
        yield text[offset:end]
        offset = end


def forwarded_text(text, bot_id):
    parts = text if isinstance(text, (list, tuple)) else (text,)
    return Nodes(
        [
            Node(uin=str(bot_id), name="MCAI", content=[Plain(subpart)])
            for item in parts
            for subpart in message_parts(item)
        ]
    )


def incident_clock(stamp, poll_now):
    if type(stamp) not in (int, float):
        return ""
    try:
        if not math.isfinite(stamp):
            return ""
        local = datetime.fromtimestamp(stamp)
    except (OverflowError, OSError, ValueError):
        return ""
    return local.strftime(
        "%H:%M:%S"
        if local.date() == datetime.fromtimestamp(poll_now).date()
        else "%m-%d %H:%M:%S"
    )


def incident_line(row, poll_now):
    clock = incident_clock(row.get("time"), poll_now)
    suffix = f"（{clock}）" if clock else ""
    status = ""
    if row.get("type") not in ("alert", "schedule"):
        status = (
            "，已保留现场。"
            if row["console_status"] == "complete"
            else "，已记录事件，控制台证据不完整。"
        )
    return f"「{row['instance']}」：{row['summary']}{status}{suffix}"


class MCAI(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config

    async def initialize(self):
        config = self.config
        context = self.context
        self.store = Store(
            Path(get_astrbot_data_path()) / "plugin_data" / "astrbot_plugin_mcai"
        )
        for name in A_LOGS:
            rotate(self.store.directory / name, time.time())
        install_rules(self.store)
        powershell = config.get("workspace_powershell_path", "")
        if powershell:
            powershell = str((self.store.directory / powershell).resolve())
        powershell = await asyncio.to_thread(powershell_path, powershell)
        self.workspace_memory = MemoryJob(8192)
        rules_path = self.store.directory / "AGENTS.md"
        review_rules_path = self.store.directory / "REVIEW_AGENTS.md"
        summary_rules_path = self.store.directory / "SUMMARY_AGENTS.md"
        cyber_rules_path = self.store.directory / "CYBER_AGENTS.md"
        self.tasks = Tasks(
            self.store,
            HostClient(
                config["host_url"],
                config["host_token"],
                config.get("host_fingerprint", ""),
            ),
            AstrBotAgent(
                context,
                config.get("provider_id", ""),
                config.get("max_steps", 40),
                rules_path=rules_path,
                review_rules_path=review_rules_path,
                summary_rules_path=summary_rules_path,
                cyber_rules_path=cyber_rules_path,
                review_provider_id=config.get("review_provider_id", ""),
                review_reasoning_effort=config.get("review_reasoning_effort", ""),
                backup_provider_id=config.get("backup_provider_id", ""),
                backup_reasoning_effort=config.get("backup_reasoning_effort", ""),
                backup_review_provider_id=config.get("backup_review_provider_id", ""),
                backup_review_reasoning_effort=config.get(
                    "backup_review_reasoning_effort", ""
                ),
                backup_cooldown_minutes=config.get("backup_cooldown_minutes", 10),
                cyber_fallback_action=config.get("cyber_fallback_action", "pause"),
                cyber_provider_id=config.get("cyber_provider_id", ""),
                cyber_reasoning_effort=config.get("cyber_reasoning_effort", ""),
                cyber_backup_provider_id=config.get("cyber_backup_provider_id", ""),
                cyber_backup_reasoning_effort=config.get(
                    "cyber_backup_reasoning_effort", ""
                ),
                enable_cyber_prompt=config.get("enable_cyber_prompt", False),
                forward_progress=config.get("forward_progress", False),
                enable_web_search=config.get("enable_web_search", True),
                web_search_tool_type=config.get("web_search_tool_type", "web_search"),
                web_search_mode=config.get("web_search_mode", "cached"),
                workspace_java_path=config.get("workspace_java_path", ""),
                enable_remote_compaction=config.get("enable_remote_compaction", False),
                remote_compaction_mode=config.get(
                    "remote_compaction_mode", "compaction_trigger"
                ),
                reasoning_effort=config.get("reasoning_effort", ""),
                enable_alpha_search=config.get("enable_alpha_search", False),
            ),
            self.notify,
            task_token_limit=config.get("task_token_limit", 0),
            model_failure_pause_minutes=config.get("model_failure_pause_minutes", 0),
            local_jobs=Jobs(self.store),
            downloads=Downloads(
                self.store,
                {
                    "curseforge_api_key": config.get("curseforge_api_key", ""),
                    "download_max_bytes": 2 * 1024**3,
                },
            ),
            workspace=Workspace(
                workspace_root(config, self.store.directory),
                powershell,
                self.workspace_memory.name,
                store_dir=self.store.directory,
            ),
        )
        from .mcai.settings import Settings

        self.settings = Settings(
            self,
            rules_path,
            review_rules_path,
            summary_rules_path,
            cyber_rules_path=cyber_rules_path,
        )
        self.incident_worker = asyncio.create_task(self.deliver_incidents())
        self.ask_workers = {}
        self.ask_recent = {}
        self.ack_workers = set()

        # Providers are loaded after plugins during a cold start, but already
        # exist when a running AstrBot installs or reloads this plugin.
        if context.get_all_providers():
            await self.tasks.start()

    @filter.on_astrbot_loaded()
    async def on_astrbot_loaded(self):
        await self.tasks.start()

    async def acknowledge_message(
        self,
        event,
        identity,
        *,
        emoji_id=ACK_EMOJI_ID,
        trace_kind="ask_ack_failed",
    ):
        platform = event.get_platform_name()
        try:
            async with asyncio.timeout(3):
                if platform == "aiocqhttp":
                    message_obj = getattr(event, "message_obj", None)
                    message_id = getattr(message_obj, "message_id", None)
                    if not message_id:
                        return
                    bot = getattr(event, "bot", None)
                    if bot is None:
                        adapter = self.context.get_platform_inst(
                            event.get_platform_id()
                        )
                        bot = adapter.get_client() if adapter else None
                    if bot is None:
                        return
                    api_message_id = (
                        int(message_id)
                        if isinstance(message_id, str) and message_id.isdigit()
                        else message_id
                    )
                    self_id = getattr(message_obj, "self_id", None)
                    routing = {"self_id": self_id} if self_id else {}
                    try:
                        await bot.call_action(
                            "set_msg_emoji_like",
                            message_id=api_message_id,
                            emoji_id=emoji_id,
                            set=True,
                            **routing,
                        )
                    except Exception:
                        group_id = event.get_group_id()
                        if not group_id:
                            raise
                        api_group_id = (
                            int(group_id)
                            if isinstance(group_id, str) and group_id.isdigit()
                            else group_id
                        )
                        await bot.call_action(
                            "set_group_reaction",
                            group_id=api_group_id,
                            message_id=api_message_id,
                            code=emoji_id,
                            is_add=True,
                            **routing,
                        )
                elif platform in ("telegram", "discord"):
                    await event.react("👌")
                elif platform == "lark":
                    await event.react("OK")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            task = identity() if callable(identity) else identity
            trace_event(
                self.store,
                trace_kind,
                task=task,
                platform=platform,
                emoji_id=emoji_id,
                error=f"{type(exc).__name__}: {exc}",
            )

    async def acknowledge_ask(self, event, identity):
        await self.acknowledge_message(
            event,
            identity,
            emoji_id=ACK_EMOJI_ID,
            trace_kind="ask_ack_failed",
        )

    def acknowledge_command(self, event, trace, *, task_id=None):
        identity = task_id if task_id is not None else (lambda: trace.get("task"))
        worker = asyncio.create_task(
            self.acknowledge_message(
                event,
                identity,
                emoji_id=ACK_EMOJI_ID,
                trace_kind="command_ack_failed",
            )
        )
        self.ack_workers.add(worker)
        worker.add_done_callback(self.ack_workers.discard)

    async def ask(self, event, identity, question, *, is_admin=False):
        sender = event.get_sender_id()
        current = self.tasks.client
        client = HostClient(current.url, current.token, current.fingerprint)
        ack_task = asyncio.create_task(self.acknowledge_ask(event, identity))
        cancelled = False
        try:
            answer = await answer_question(
                self.tasks,
                client,
                event,
                identity,
                question,
                is_admin=is_admin,
                max_steps=self.config.get("ask_max_steps"),
                timeout_seconds=self.config.get("ask_timeout_seconds"),
            )
            text = space_commands("「只读问答」：" + answer)
            trace_event(self.store, "ask_answer", task=identity, reply=text)
            self.store.save(
                "outbox",
                identity,
                {
                    "id": identity,
                    "task": identity,
                    "origin": event.unified_msg_origin,
                    "text": text,
                    "mention": None,
                    "sent": False,
                },
            )
            self.tasks.wake_outbox()
        except asyncio.CancelledError:
            cancelled = True
            raise
        finally:
            if not ack_task.done() and not cancelled:
                await asyncio.wait({ack_task}, timeout=2)
            if not ack_task.done():
                ack_task.cancel()
            await asyncio.gather(ack_task, return_exceptions=True)
            await client.close()
            self.ask_workers.pop(sender, None)

    def queue_connection_alert(self, url, routes, now, state, error):
        recovered = error is None
        identity = uuid.uuid4().hex
        duration = max(0, int(now - state["since"]))
        summary = (
            f"与 B 的连接已恢复，中断约 {duration // 60} 分 {duration % 60} 秒。"
            if recovered
            else f"连不上 B：最近一次轮询错误类别为 {error}。"
        )
        origins = sorted(set(routes.values()))
        row = {
            "id": identity,
            "type": "alert",
            "reason": "connection",
            "recovered": recovered,
            "time": now,
            "since": state["since"],
            "duration_seconds": duration,
            "error_category": error or state["error_category"],
            "summary": summary,
            "origins": origins,
        }
        records = [
            ("connection_alert", identity, row),
            (
                "incident_connection",
                url,
                {}
                if recovered
                else {**state, "alerted": True, "error_category": error},
            ),
        ]
        for index, origin in enumerate(origins):
            key = f"incident-{identity}-{index}"
            records.append(
                (
                    "outbox",
                    key,
                    {
                        "id": key,
                        "task": None,
                        "origin": origin,
                        "mention": None,
                        "text": f"{summary}\n可用 “/mcainew 任务名 处理事件 {identity}” 发起排查",
                        "sent": False,
                    },
                )
            )
        self.store.save_many(*records)
        if origins:
            self.tasks.wake_outbox()

    async def poll_incidents(self, routes, *, now=None):
        client = self.tasks.client
        existing_cursor = self.store.get("incident_cursor", client.url)
        cursor = existing_cursor or {"seq": 0}
        state = self.store.get("incident_connection", client.url) or {}
        revision = self.tasks.activity_revision
        poll_now = time.time() if now is None else now
        params = {
            "active": json.dumps(self.tasks.active_instances(), ensure_ascii=False),
            "stream": "1",
        }
        if routes:
            params.update(after=cursor["seq"], stream_id=cursor.get("stream_id", ""))
            if "event_id" in cursor:
                params["event_id"] = cursor["event_id"]
        else:
            params["active_only"] = "1"
        try:
            async with asyncio.timeout(15):
                feed = await client.request(
                    "GET", "/incidents", once=True, params=params
                )
        except (
            aiohttp.ClientError,
            RuntimeError,
            OSError,
            ValueError,
            TimeoutError,
        ) as exc:
            if not routes:
                return
            if not state:
                state = {"since": poll_now, "alerted": False}
                self.store.save("incident_connection", client.url, state)
                self.store.log("incident_delivery_pending", error=str(exc))
            if (
                not state["alerted"]
                and poll_now - state["since"]
                >= self.config.get("host_offline_alert_minutes", 3) * 60
            ):
                self.queue_connection_alert(
                    client.url, routes, poll_now, state, type(exc).__name__
                )
            return
        if self.tasks.activity_revision != revision:
            await self.tasks.sync_activity(force=True)
        if not routes and (
            not isinstance(feed, dict) or not {"stream_id", "high_water"} <= feed.keys()
        ):
            return
        if routes and state:
            if state["alerted"]:
                self.queue_connection_alert(client.url, routes, poll_now, state, None)
            else:
                self.store.save("incident_connection", client.url, {})
        if not isinstance(feed, dict):
            raise ValueError("B 未返回留证流标识，请配套更新 A、B")
        items = feed["items"] if routes else []
        last = items[-1] if items else None
        initialize = existing_cursor is None and not state
        if not routes or existing_cursor is None or feed["reset"]:
            high_water = feed["high_water"]
            cursor = {"stream_id": feed["stream_id"], "seq": high_water}
            event_id = feed.get("high_water_id")
            if not event_id and last and last["seq"] == high_water:
                event_id = last["id"]
            if event_id:
                cursor["event_id"] = event_id
        elif last:
            cursor = {
                "stream_id": feed["stream_id"],
                "seq": last["seq"],
                "event_id": last["id"],
            }
        if not routes or initialize:
            if cursor != existing_cursor:
                self.store.save("incident_cursor", client.url, cursor)
            if routes:
                self.store.log(
                    "incident_cursor_initialized",
                    high_water=cursor["seq"],
                    skipped=len(items),
                )
            return

        groups = {}
        stale = []
        for row in items:
            origin = routes.get(row["instance"], routes.get("*"))
            if not origin or not row.get("notify", True):
                continue
            stamp = row.get("time")
            if type(stamp) in (int, float):
                if stamp < poll_now - MAX_INCIDENT_NOTIFY_AGE:
                    stale.append(row["seq"])
                    continue
                if existing_cursor is None and stamp < state["since"]:
                    continue
            identity = row["id"]
            if self.store.get("outbox", "incident-" + identity) or self.store.get(
                "incident_notified", identity
            ):
                continue
            groups.setdefault(origin, []).append(row)

        records = []
        for origin, batch in groups.items():
            if len(batch) == 1:
                row = batch[0]
                key = "incident-" + row["id"]
                body = incident_line(row, poll_now)
                if row.get("type") in ("alert", "schedule"):
                    body += f"\n可用 “/mcainew 任务名 处理事件 {row['id']}” 发起排查"
            else:
                digest = hashlib.sha256(",".join(row["id"] for row in batch).encode())
                key = "incident-batch-" + digest.hexdigest()[:16]
                lines = [f"收到 {len(batch)} 条服务端事件通知："]
                for row in batch[:MAX_INCIDENT_BATCH_LINES]:
                    line = incident_line(row, poll_now)
                    if row.get("type") in ("alert", "schedule"):
                        line += f"（事件 {row['id']}）"
                    lines.append("- " + line)
                if len(batch) > MAX_INCIDENT_BATCH_LINES:
                    lines.append(
                        f"… 另有 {len(batch) - MAX_INCIDENT_BATCH_LINES} 条事件，请前往 MCAI 设置页「故障与告警」查看完整记录。"
                    )
                if any(row.get("type") in ("alert", "schedule") for row in batch):
                    lines.append(
                        "\n如需排查，可用 “/mcainew 任务名 处理事件 <事件编号>” 发起任务。"
                    )
                body = "\n".join(lines)
            records.append(
                (
                    "outbox",
                    key,
                    {
                        "id": key,
                        "task": None,
                        "origin": origin,
                        "mention": None,
                        "text": body,
                        "sent": False,
                    },
                )
            )
            records.extend(
                ("incident_notified", row["id"], {"time": poll_now}) for row in batch
            )
        if records or cursor != existing_cursor:
            self.store.save_many(*records, ("incident_cursor", client.url, cursor))
        if records:
            self.tasks.wake_outbox()
        if stale:
            self.store.log(
                "incident_stale_skipped", count=len(stale), max_seq=max(stale)
            )

    async def deliver_incidents(self):
        while True:
            try:
                routes = incident_routes(
                    self.config.get("incident_routes", []),
                    self.config.get("group_ids", []),
                )
                await self.poll_incidents(routes)
            except (
                RuntimeError,
                OSError,
                ValueError,
                TimeoutError,
                sqlite3.Error,
            ) as exc:
                self.store.log("incident_delivery_pending", error=str(exc))
            await asyncio.sleep(15)

    async def manage_schedules(self, tail, is_admin, sender):
        parts = tail.split()
        client = self.tasks.client
        try:
            if parts == ["list"]:
                result = await client.request(
                    "GET", "/schedules", once=True, timeout=5, params={"health": "1"}
                )
                states = {"active": "启用", "paused": "暂停"}
                lines = []
                for row in result["items"]:
                    kind = "备份" if row["spec"]["kind"] == "backup" else "重启"
                    last = row.get("last_result", {}).get("message", "尚未执行")
                    lines.append(
                        f"{row['id']} · {row['instance']} · {kind} · {schedule_time(row['spec'])}"
                        f"\n状态：{states[row['state']]}；下次：{row['next_local'] or '—'}；上次：{last}"
                    )
                health = result["health"]
                if health["status"] != "ready":
                    lines.insert(0, "B 调度降级：" + health["error"])
                return "\n".join(lines) or "当前没有定时计划。"
            if not parts or parts[0] not in ("pause", "resume", "delete"):
                raise ValueError(
                    "用法：“/mcaischedule list” 查看定时计划，或管理员使用 “/mcaischedule pause|resume|delete 编号” （编号可从 list 获取）。"
                )
            if len(parts) != 2 or not re.fullmatch(r"[0-9a-f]{32}", parts[1]):
                raise ValueError(
                    f"请提供正确的 32 位定时计划编号（可先用 “/mcaischedule list” 查看）。\n用法：“/mcaischedule {parts[0]} 编号”"
                )
            if not is_admin:
                raise ValueError("只有管理员可暂停、恢复或删除定时计划。")
            action, key = parts
            await client.request(
                "POST",
                f"/schedules/{key}",
                once=True,
                timeout=5,
                json={"action": action, "sender": sender},
            )
            return f"计划 {key} 已{'暂停' if action == 'pause' else '恢复' if action == 'resume' else '删除'}。"
        except (aiohttp.ClientError, OSError, TimeoutError, RemoteError) as exc:
            raise ValueError(
                f"无法读取或管理 B 的定时计划：{str(exc) or type(exc).__name__}"
            ) from exc

    async def notify(self, item):
        origin, text, mention = item["origin"], item["text"], item["mention"]
        parts = item.get("parts") or [text]
        mentions = [At(qq=mention)] if mention else []
        sent = item.get("parts_sent", 0)
        chains = [mentions + [Plain(text)]]
        forwarded = item.get("forwarded")
        threshold = self.config.get(
            "group_forward_threshold", DEFAULT_GROUP_FORWARD_THRESHOLD
        )
        if (
            sent
            or len(parts) > 1
            or len(text) > min(threshold, GROUP_MESSAGE_PART_LIMIT)
        ):
            platform = self.context.get_platform_inst(origin.split(":", 1)[0])
            if (
                platform
                and platform.meta().name == "aiocqhttp"
                and (
                    sent
                    and item.get("forwarded", True)
                    or not sent
                    and (len(parts) > 1 or len(text) > threshold)
                )
            ):
                if sent:
                    chains = [mentions]
                else:
                    login = await platform.get_client().get_login_info()
                    forwarded = True
                    chains = [
                        [
                            forwarded_text(
                                parts if len(parts) > 1 else text,
                                login["user_id"],
                            )
                        ]
                    ]
                    if mentions:
                        chains.append(mentions)
            elif len(parts) > 1 or len(text) > GROUP_MESSAGE_PART_LIMIT:
                if not sent:
                    forwarded = False
                chains = [
                    [Plain(subpart)]
                    for part in parts
                    for subpart in message_parts(part)
                ]
                chains[0][:0] = mentions
                chains = chains[sent:]
        for index, chain in enumerate(chains, 1):
            result = await self.context.send_message(origin, MessageChain(chain))
            if result is False:
                raise RuntimeError("平台暂时无法发送消息")
            if index < len(chains):
                # 后续分段或 @ 失败时，重试从它开始并使用独立的发送次数。
                item.update(
                    parts_sent=sent + index,
                    attempts=1,
                    **({"forwarded": forwarded} if forwarded is not None else {}),
                )
                self.store.save("outbox", item["id"], item)

    async def collect_attachments(
        self, workspace, task, event, attachments, *, folders=None
    ):
        agent = self.tasks.agent
        cyber_failover = getattr(agent, "cyber_failover", None)
        cyber_action = getattr(
            agent,
            "cyber_fallback_action",
            self.config.get("cyber_fallback_action", "pause"),
        )
        cyber_prefix = (
            agent.cyber_prompt_prefix(store=self.store, task=task)
            if callable(getattr(agent, "cyber_prompt_prefix", None))
            else ""
        )
        job = self.tasks.jobs.get(task)
        initial_cyber = bool(
            job is not None and job.get("cyber_fallback") and cyber_action == "fallback"
        )
        image_notices = []

        async def recognize(path):
            return await recognize_image(
                self.context,
                self.store,
                task,
                event.unified_msg_origin,
                self.config.get("provider_id", ""),
                path,
                failover=getattr(agent, "main_failover", None),
                cyber_failover=cyber_failover,
                cyber_fallback_action=cyber_action,
                cyber_prompt_prefix=cyber_prefix,
                initial_cyber=initial_cyber,
                on_notice=image_notices.append,
            )

        return await receive_attachments(
            workspace,
            task,
            attachments,
            recognize,
            folders=folders,
            external_notices=image_notices,
        )

    def _group_allowed(self, event: AstrMessageEvent, group: str, trace: dict) -> bool:
        allowed = allowed_group_ids(self.config.get("group_ids"))
        if allowed and group not in allowed:
            trace_event(
                self.store,
                "command_result",
                **trace,
                status="rejected",
                reason="群不在允许范围",
            )
            event.stop_event()
            return False
        return True

    @filter.command("mcaihelp", alias=COMMANDS - {"mcaihelp"}, priority=100)
    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE, priority=100)
    async def commands(self, event: AstrMessageEvent):
        # A live install with no configured providers still needs its outbox
        # and must report configuration errors when a command arrives.
        await self.tasks.start()
        text = event.get_message_str().strip()
        if not text:
            return
        command, *arguments = text.split(maxsplit=1)
        tail = arguments[0] if arguments else ""
        command = command.removeprefix("/")
        if command not in COMMANDS:
            return
        group = event.get_group_id()
        sender = event.get_sender_id()
        admin_ids = {str(item) for item in self.config.get("admin_ids", [])}
        is_admin = event.is_admin() or sender in admin_ids
        trace = {
            "event_id": uuid.uuid4().hex,
            "task": None,
            "command": command,
            "text": text,
            "group": group,
            "sender": sender,
            "is_admin": is_admin,
            "quoted": [
                part.message_str
                for part in event.get_messages()
                if isinstance(part, Reply)
            ],
        }
        if command == "mcaiask":
            trace["task"] = "ask-" + trace["event_id"]
        trace_event(self.store, "plugin_command", **trace)
        if not self._group_allowed(event, group, trace):
            return
        status = "handled"
        send = event.send
        onebot = event.get_platform_name() == "aiocqhttp"

        async def traced_send(message):
            reply_text = message.get_plain_text()
            merged = next(
                (part for part in message.chain if isinstance(part, Nodes)), None
            )
            if merged is not None:
                reply_text = "".join(node.content[0].text for node in merged.nodes)
                # AstrBot 开启分段回复时会把 @ 移到链首，发出前恢复合集在前。
                message = message.derive(
                    sorted(message.chain, key=lambda part: isinstance(part, At))
                )
            try:
                result = await send(message)
            except Exception as exc:
                trace_event(
                    self.store,
                    "command_reply_failed",
                    **trace,
                    reply=reply_text,
                    error=f"{type(exc).__name__}: {exc}",
                )
                raise
            trace_event(
                self.store,
                "command_reply_sent",
                **trace,
                reply=reply_text,
            )
            return result

        event.send = traced_send

        def reply(text="", *, parts=None):
            formatted = [space_commands(part) for part in (parts or (text,))]
            combined = "\n\n".join(formatted) if parts else formatted[0]
            trace_event(
                self.store, "command_reply", **trace, reply=combined, status="prepared"
            )
            if onebot and (
                len(formatted) > 1
                or len(combined)
                > self.config.get(
                    "group_forward_threshold", DEFAULT_GROUP_FORWARD_THRESHOLD
                )
            ):
                settings = self.context.get_config(event.unified_msg_origin)[
                    "platform_settings"
                ]
                nodes = [settings["reply_prefix"] + formatted[0], *formatted[1:]]
                chain = [
                    forwarded_text(
                        nodes if len(nodes) > 1 else nodes[0],
                        event.get_self_id(),
                    )
                ]
                if settings["reply_with_mention"]:
                    chain.append(At(qq=sender))
                return event.chain_result(chain)
            return event.plain_result(combined)

        try:
            if command not in {
                "mcaisay",
                "mcaistatus",
                "mcaihelp",
                "mcailist",
                "mcaiplan",
                "mcaiserver",
                "mcaiask",
                "mcaischedule",
            }:
                if not is_admin:
                    status = "rejected"
                    yield reply(
                        "该指令仅管理员可用。普通成员可使用 “/mcaisay 任务名 内容” 补充线索，或 “/mcaihelp” 查看可用指令。"
                    )
                    return
            if command == "mcaihelp":
                yield reply(HELP_TEXT)
                return
            if command == "mcaischedule":
                text = await self.manage_schedules(tail, is_admin, sender)
                for part in (text,) if onebot else message_parts(text):
                    yield reply(part)
                return
            if command == "mcaiserver":
                text = await server_status(
                    self.tasks.client,
                    self.store,
                    "server-" + trace["event_id"],
                    tail.strip(),
                    is_admin,
                )
                for part in (text,) if onebot else message_parts(text):
                    yield reply(part)
                return
            if command == "mcaiswitch":
                parts = tail.split()
                if (
                    len(parts) not in (2, 3)
                    or parts[1] not in SERVER_ACTIONS
                    or (
                        len(parts) == 3
                        and (parts[1] not in FORCE_ACTIONS or parts[2] != "confirm")
                    )
                ):
                    raise ValueError(
                        "用法：“/mcaiswitch 实例ID start|stop|restart|forcestop|forcerestart [confirm]” 。"
                        "请用 “/mcaiserver” 查询实例 ID。"
                    )
                name, action = parts[:2]
                try:
                    result, control = await self.tasks.control_instance(
                        name,
                        action,
                        f"qq:{sender}",
                        origin=event.unified_msg_origin,
                        mention=sender,
                        confirm=len(parts) == 3,
                    )
                except (aiohttp.ClientError, TimeoutError, RemoteError) as exc:
                    raise ValueError(
                        f"无法读取 B 的启停状态：{str(exc) or type(exc).__name__}"
                    ) from exc
                if control is None:
                    if result.get("already_stopped"):
                        yield reply(result["message"])
                        return
                    target = (
                        "Java" if result["target"] == "java" else "start.bat 启动链"
                    )
                    previous = result.get("previous")
                    description = (
                        f"当前有正在执行的停止/重启操作（{previous}），确认后将先取消停服等待，再{SERVER_ACTIONS[action]}"
                        if previous
                        else f"{name} 将{SERVER_ACTIONS[action]}"
                    )
                    yield reply(
                        f"{description}：{target} PID {result['pid']}。"
                        "强制结束可能丢失未保存的数据。"
                        f"确认后请在 120 秒内发送 “/mcaiswitch {name} {action} confirm” 。"
                    )
                    return
                try:
                    yield reply(
                        f"{name} {SERVER_ACTIONS[action]}已提交（操作编号 {control['id']}），正在执行…"
                    )
                finally:
                    self.tasks.observe_control_later(control)
                return
            if command == "mcaiask":
                if not is_admin and not self.config.get("allow_member_ask", False):
                    raise ValueError("该指令仅管理员可用。")
                if not tail.strip():
                    raise ValueError(
                        "用法：“/mcaiask 问题”，例： “/mcaiask cti服现在 TPS 为什么下降了？” 。"
                    )
                if sender in self.ask_workers:
                    raise ValueError("你已有一条只读问答正在处理，请等结果返回。")
                if not is_admin:
                    now = time.monotonic()
                    cooldown = self.config.get("member_ask_cooldown_seconds", 300)
                    self.ask_recent = {
                        key: stamp
                        for key, stamp in self.ask_recent.items()
                        if now - stamp < cooldown
                    }
                    if sender in self.ask_recent:
                        remaining = int(cooldown - (now - self.ask_recent[sender])) + 1
                        raise ValueError(f"只读问答冷却中，请 {remaining} 秒后再试。")
                    self.ask_recent[sender] = now
                identity = trace["task"]
                self.store.save(
                    "ask",
                    identity,
                    {
                        "id": identity,
                        "name": tail.splitlines()[0][:60],
                        "group": group,
                        "created": time.time(),
                    },
                )
                self.ask_workers[sender] = asyncio.create_task(
                    self.ask(event, identity, tail.strip(), is_admin=is_admin)
                )
                return
            if command == "mcailist":
                try:
                    page = int(tail.strip() or "1")
                    if page < 1:
                        raise ValueError
                except ValueError as exc:
                    raise ValueError("用法：“/mcailist [页码]”，页码为正整数") from exc
                yield reply(self.tasks.list_tasks(group, page))
                return
            name, *arguments = tail.split(maxsplit=1) or [""]
            content = arguments[0] if arguments else ""
            attachments = (
                list(message_attachments(event, self.context, admin_ids, is_admin))
                if command in ("mcainew", "mcaisay") and name
                else []
            )
            if command == "mcainew":
                if not name:
                    raise ValueError(
                        "用法：“/mcainew 任务名 问题描述”，例： “/mcainew 主城卡顿 cti服昨天更新后掉TPS” ；也可先回复/引用玩家消息后发 “/mcainew 任务名 [补充说明]” 。"
                    )
                quoted = [
                    part for part in event.get_messages() if isinstance(part, Reply)
                ]
                quoted_text = (quoted[0].message_str or "") if quoted else ""
                quoted_origin = None
                if quoted and quoted_text:
                    quoted_sender = str(quoted[0].sender_id or "")
                    astrbot_admins = ()
                    if quoted_sender and quoted_sender not in admin_ids:
                        try:
                            astrbot_admins = self.context.get_config(
                                event.unified_msg_origin
                            ).get("admins_id", ())
                        except AttributeError:
                            astrbot_admins = ()
                    quoted_origin = {
                        "sender": quoted_sender,
                        "is_admin": bool(quoted_sender)
                        and (
                            quoted_sender in admin_ids
                            or quoted_sender in astrbot_admins
                        ),
                    }
                report = quoted_text
                if report and content.strip():
                    report += "\n\n创建者补充：\n" + content.strip()
                elif not report:
                    report = content.strip()
                if not report.strip() and not attachments:
                    raise ValueError(
                        f"请填写问题描述或附上文件/图片。\n用法：“/mcainew {name} 问题描述”，或先回复/引用一条包含问题的消息再发 “/mcainew {name}” 。"
                    )
                self.tasks.check_create(group, name)
                task = uuid.uuid4().hex if attachments else None
                workspace = self.tasks.workspace
                options, notices = {}, []
                try:
                    if task:
                        self.acknowledge_command(event, trace, task_id=task)
                        records, notices, saved = await self.collect_attachments(
                            workspace, task, event, attachments
                        )
                        if not saved and not report.strip():
                            yield reply("\n".join(notices))
                            return
                        options = {
                            "task_id": task,
                            "attachments": records,
                            "workspace_root": str(workspace.root) if saved else None,
                        }
                    if quoted_origin is not None:
                        options["quoted_origin"] = quoted_origin
                        options["admin_report"] = content.strip()
                    job = await self.tasks.create(
                        group,
                        event.unified_msg_origin,
                        name,
                        None,
                        sender,
                        report,
                        **options,
                    )
                finally:
                    if task and task not in self.tasks.jobs:
                        path = workspace.directory(task) / "attachments"
                        if path.exists():
                            shutil.rmtree(path)
                            path.parent.rmdir()
                trace["task"] = job["id"]
                if not task:
                    self.acknowledge_command(event, trace)
                if notices:
                    yield reply("\n".join(notices))
                return
            if not name:
                hints = {
                    "mcaisay": "用法：“/mcaisay 任务名 内容”，例： “/mcaisay 主城卡顿 坐标 120 65 -300 复现” ；忘记任务名可用 “/mcailist” 查看。",
                    "mcaisaymode": "用法：“/mcaisaymode 任务名 true|false”（true 开启、false 暂停普通成员补充）；忘记任务名可用 “/mcailist” 查看。",
                    "mcaiapply": "用法：“/mcaiapply 任务名 短码”，例： “/mcaiapply 主城卡顿 9F2A7C” ；忘记任务名可用 “/mcailist” 查看，查看短码可用 “/mcaiplan 任务名” 。",
                }
                raise ValueError(
                    hints.get(
                        command,
                        f"用法：“/{command} 任务名”；忘记任务名可用 “/mcailist” 查看，或发送 “/mcaihelp” 查看全部用法。",
                    )
                )
            job = self.tasks.find(group, name)
            trace["task"] = job["id"]
            if command == "mcaisay":
                if not content.strip() and not attachments:
                    raise ValueError(
                        f"用法：“/mcaisay {name} 内容”，请填写要补充的信息（也可直接附上或引用群文件、图片）。"
                    )
                self.tasks.check_feedback(job, is_admin)
                records, notices = [], []
                folders, received = [], False
                try:
                    if attachments:
                        workspace = self.tasks.workspace
                        root = str(workspace.root)
                        if job.get("workspace_root", root) != root:
                            raise ValueError(
                                "任务工作区位置已变化，请恢复本任务原工作区配置"
                            )
                        self.acknowledge_command(event, trace)
                        records, notices, saved = await self.collect_attachments(
                            workspace, job["id"], event, attachments, folders=folders
                        )
                        self.tasks.check_feedback(job, is_admin)
                        if saved:
                            job["workspace_root"] = root
                            self.tasks.save(job)
                    accepted = bool(content.strip() or records)
                    if accepted:
                        self.tasks.feedback(
                            job,
                            sender,
                            content.strip(),
                            is_admin=is_admin,
                            feedback_id=trace["event_id"],
                            attachments=records,
                        )
                    received = True
                finally:
                    if not received:
                        for folder in folders:
                            if folder.exists():
                                shutil.rmtree(folder)
                if notices:
                    yield reply("\n".join(notices))
                if accepted and job["state"] == "paused":
                    yield reply(
                        f"「{name}」：补充已保存；任务仍暂停，管理员使用 “/mcairesume {name}” 后会一起读取。"
                    )
                elif accepted and not attachments:
                    self.acknowledge_command(event, trace)
            elif command == "mcaisaymode":
                mode = content.strip().lower()
                if mode not in ("true", "false"):
                    raise ValueError(
                        f"参数应为 true 或 false（当前收到：{content.strip() or '空'}）。\n用法：“/mcaisaymode {name} true|false”；true 开启、false 暂停普通成员补充，管理员仍可补充。"
                    )
                self.tasks.set_say_mode(job, mode == "true", sender)
                yield reply(
                    f"「{name}」："
                    + (
                        f"已开启普通成员 say 接收。暂停：“/mcaisaymode {name} false”"
                        if mode == "true"
                        else f"已暂停普通成员 say 接收，管理员仍可补充。恢复：“/mcaisaymode {name} true”"
                    )
                )
            elif command == "mcaiapply":
                code = content.strip()
                self.tasks.check_approve(job, code)
                await self.tasks.wait_worker_idle(job)
                self.tasks.approve(job, sender, code)
                self.acknowledge_command(event, trace)
            elif command == "mcaistop":
                self.tasks.stop(job)
                self.acknowledge_command(event, trace)
            elif command == "mcaidone":
                self.tasks.stop(job, done=True)
                self.acknowledge_command(event, trace)
            elif command == "mcairesume":
                if job["state"] == "paused" and not job["stop_requested"]:
                    await self.tasks.wait_worker_idle(job)
                self.tasks.resume(job)
                self.acknowledge_command(event, trace)
            elif command == "mcaipause":
                self.tasks.pause_requested(job)
                self.acknowledge_command(event, trace)
            elif command == "mcaiplan":
                approved = job.get("approved_plan")
                if job["plan"]:
                    primary, extras = plan_sections(job["plan"])
                    footer = (
                        f"\n\n任务已暂停，管理员续接：“/mcairesume {name}”"
                        if job["state"] == "paused"
                        else f"\n\n管理员批准：“{approval_command(job)}”"
                    ) + f"\n需调整：“/mcaisay {name} 内容”"
                    plan_parts = [f"「{name}」：\n{primary}{footer}", *extras]
                elif approved:
                    primary, extras = plan_sections(approved["snapshot"]["plan"])
                    plan_status = {
                        "active": "执行中",
                        "completed": "已完成",
                        "failed": "执行失败",
                        "invalidated": "已失效",
                        "replaced": "已被替代",
                        "stopped": "已中止",
                    }[approved["status"]]
                    task_status = {
                        "running": "观察决策",
                        "applying": "当前批次执行中",
                        "waiting": "等待",
                        "paused": "已暂停",
                        "done": "已验收",
                        "stopped": "已中止",
                    }[job["state"]]
                    footer = (
                        f"\n\n批准人 QQ：{approved.get('approved_by', '未记录')}"
                        + f"\n方案状态：{plan_status}；任务状态：{task_status}"
                        + (
                            f"\n任务已暂停，管理员续接：“/mcairesume {name}”"
                            if job["state"] == "paused"
                            else ""
                        )
                        + (
                            f"\n方案已批准，按结果继续执行。补充：“/mcaisay {name} 内容”"
                            if self.tasks.active_plan(job)
                            else f"\n执行资格已结束。使用 “/mcaistatus {name}” 查看进度。"
                        )
                    )
                    plan_parts = [f"「{name}」：\n{primary}{footer}", *extras]
                else:
                    plan_parts = [
                        f"「{name}」：当前没有待批准方案。使用 “/mcaistatus {name}” 查看进度，或 “/mcaisay {name} 内容” 补充线索。"
                    ]
                if onebot:
                    yield reply(parts=plan_parts)
                else:
                    for part in plan_parts:
                        for chunk in message_parts(part):
                            yield reply(chunk)
            else:
                say_paused = job.get("say_paused", False)
                audience = "管理员" if say_paused else "群成员"
                state = {
                    "running": f"排查中。{audience}可用 “/mcaisay {name} 内容” 补充线索。",
                    "applying": f"修复中。{audience}可用 “/mcaisay {name} 内容” 补充，执行结束后读取。",
                    "waiting": (
                        f"等待批准。\n查看方案：“/mcaiplan {name}”\n管理员批准：“{approval_command(job)}”\n需调整：“/mcaisay {name} 内容”"
                        if job["plan"]
                        else f"等待反馈。{audience}使用 “/mcaisay {name} 内容” 继续；确认问题解决后，管理员使用 “/mcaidone {name}” 验收。"
                    ),
                    "paused": f"已暂停。{audience}可用 “/mcaisay {name} 内容” 保存补充；管理员使用 “/mcairesume {name}” 续接。",
                }
                if self.tasks.active_plan(job):
                    state.update(
                        running=f"方案已批准，正在观察结果并决策下一批。{audience}可用 “/mcaisay {name} 内容” 补充线索。",
                        applying=f"方案已批准，正在执行当前批次。{audience}可用 “/mcaisay {name} 内容” 补充，执行结束后读取。",
                        waiting=f"方案已批准，等待必要补充。{audience}使用 “/mcaisay {name} 内容” 继续。",
                    )
                if job.get("trial") and not job["plan"]:
                    state["running"] = "正在根据本轮试玩反馈继续排查。"
                    state["waiting"] = (
                        f"正式服已完成启动检查。确认后使用 “/mcaidone {name}” 验收。"
                        if job.get("trial_published")
                        else (
                            f"已按管理员要求完成试服验证，无需发布正式服。确认后使用 “/mcaidone {name}” 验收。"
                            if job.get("trial_release_waived")
                            else f"正式服尚未完成发布。{job.get('trial_question') or '等待本轮试玩反馈。'}"
                        )
                    )
                if (
                    job.get("release_checkpoint") or job.get("release_submitted")
                ) and job.get("operation"):
                    state["applying"] = (
                        f"正在核对正式服操作 {job['operation']} 的进度。"
                    )
                usage = task_usage(
                    self.store,
                    job["id"],
                    parse_prices(self.config.get("model_prices", [])),
                )
                usage_line = (
                    f"\n本任务模型请求 {usage['requests']} 次（审核 {usage['review_requests']} 次），"
                    f"输入／输出 {usage['input_tokens']}／{usage['output_tokens']} token。"
                )
                if usage["cost"]:
                    usage_line += (
                        " 已配置单价的估算费用：" + "、".join(usage["cost"]) + "。"
                    )
                cyber_active = bool(
                    job.get("cyber_fallback")
                    and self.config.get("cyber_fallback_action", "pause") == "fallback"
                    and self.config.get("cyber_provider_id", "")
                )
                if cyber_active:
                    active_cyber = bool(job.get("active_provider_cyber"))
                    cyber_provider = (
                        job.get("active_provider_id") if active_cyber else ""
                    ) or self.config.get("cyber_provider_id", "")
                    channel_label = (
                        "Cyber 退避备用模型"
                        if active_cyber and job.get("active_provider_slot") == "backup"
                        else "Cyber 退避主模型"
                        if active_cyber
                        else "Cyber 退避通道"
                    )
                    usage_line += (
                        f"\n当前模型通道：{channel_label}（{cyber_provider}）。"
                        if cyber_provider
                        else f"\n当前模型通道：{channel_label}。"
                    )
                elif (
                    not job.get("active_provider_cyber")
                    and job.get("active_provider_slot") == "backup"
                    and job.get("active_provider_id")
                ):
                    usage_line += (
                        f"\n当前模型通道：备用 API（{job['active_provider_id']}）。"
                    )
                yield reply(
                    f"「{name}」：{state.get(job['state'], job['state'])}"
                    + (
                        f"\n普通成员 say：暂停，管理员仍可补充。恢复：“/mcaisaymode {name} true”"
                        if say_paused
                        else f"\n普通成员 say：开启。管理员暂停接收：“/mcaisaymode {name} false”"
                    )
                    + usage_line
                )
        except ValueError as exc:
            status = "rejected"
            text = str(exc)
            for part in (
                message_parts(text)
                if command == "mcaiapply" and not onebot
                else (text,)
            ):
                yield reply(part)
        except Exception as exc:
            status = "failed"
            trace["error"] = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            trace_event(self.store, "command_result", **trace, status=status)
            if status != "failed":
                # yield 的回复先经过发送阶段，再终止后续处理。
                event.stop_event()

    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE, priority=90)
    @filter.custom_filter(McaiCommandAttemptFilter)
    async def command_typo_hint(self, event: AstrMessageEvent):
        text = event.get_message_str().strip()
        hint = command_typo_message(text)
        if not hint:
            return
        group = event.get_group_id()
        sender = event.get_sender_id()
        admin_ids = {str(item) for item in self.config.get("admin_ids", [])}
        trace = {
            "event_id": uuid.uuid4().hex,
            "task": None,
            "command": text.removeprefix("/").split(maxsplit=1)[0],
            "text": text,
            "group": group,
            "sender": sender,
            "is_admin": event.is_admin() or sender in admin_ids,
            "quoted": [],
        }
        trace_event(self.store, "plugin_command", **trace)
        if not self._group_allowed(event, group, trace):
            return
        try:
            formatted = space_commands(hint)
            trace_event(
                self.store, "command_reply", **trace, reply=formatted, status="prepared"
            )
            yield event.plain_result(formatted)
        finally:
            trace_event(self.store, "command_result", **trace, status="typo_hint")
            event.stop_event()

    async def terminate(self):
        self.incident_worker.cancel()
        await asyncio.gather(self.incident_worker, return_exceptions=True)
        await self.settings.close()
        questions = tuple(self.ask_workers.values())
        acks = tuple(self.ack_workers)
        for worker in (*questions, *acks):
            worker.cancel()
        await asyncio.gather(*questions, *acks, return_exceptions=True)
        await self.tasks.close()
        self.workspace_memory.close()
        self.store.close()
