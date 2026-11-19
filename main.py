import asyncio
import uuid
from pathlib import Path

from astrbot.api import AstrBotConfig
from astrbot.api.event import AstrMessageEvent, MessageChain, filter
from astrbot.api.message_components import At, Node, Nodes, Plain, Reply
from astrbot.api.star import Context, Star
from astrbot.core.utils.astrbot_path import get_astrbot_data_path

from .mcai.astrbot_agent import AstrBotAgent
from .mcai.client import HostClient, RemoteError
from .mcai.configuration import incident_routes, powershell_path
from .mcai.downloads import Downloads
from .mcai.jobs import Jobs
from .mcai.memory_job import MemoryJob
from .mcai.paths import workspace_root
from .mcai.storage import Store
from .mcai.tasks import Tasks, plan_text
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
}
GROUP_MESSAGE_PART_LIMIT = 1800
DEFAULT_GROUP_FORWARD_THRESHOLD = 400


def message_parts(text):
    offset = 0
    while offset < len(text):
        end = min(offset + GROUP_MESSAGE_PART_LIMIT, len(text))
        if end < len(text):
            boundary = text.rfind("\n", offset, end)
            if boundary >= offset:
                end = boundary + 1
        yield text[offset:end]
        offset = end


def forwarded_text(text, bot_id):
    return Nodes(
        [
            Node(uin=str(bot_id), name="MCAI", content=[Plain(part)])
            for part in message_parts(text)
        ]
    )


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
        powershell = config.get("workspace_powershell_path", "")
        if powershell:
            powershell = str((self.store.directory / powershell).resolve())
        powershell = await asyncio.to_thread(powershell_path, powershell)
        self.workspace_memory = MemoryJob(8192)
        rules_path = self.store.directory / "AGENTS.md"
        review_rules_path = self.store.directory / "REVIEW_AGENTS.md"
        summary_rules_path = self.store.directory / "SUMMARY_AGENTS.md"
        for target, source in (
            (rules_path, "agent_rules.md"),
            (review_rules_path, "review_rules.md"),
            (summary_rules_path, "summary_rules.md"),
        ):
            if not target.exists():
                target.write_text(
                    (Path(__file__).parent / "mcai" / source).read_text(
                        encoding="utf-8"
                    ),
                    encoding="utf-8",
                )
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
                review_provider_id=config.get("review_provider_id", ""),
                review_reasoning_effort=config.get("review_reasoning_effort", ""),
                forward_progress=config.get("forward_progress", False),
                enable_web_search=config.get("enable_web_search", True),
                web_search_tool_type=config.get("web_search_tool_type", "web_search"),
                reasoning_effort=config.get("reasoning_effort", ""),
                enable_alpha_search=config.get("enable_alpha_search", False),
            ),
            self.notify,
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
            ),
        )
        from .mcai.settings import Settings

        self.settings = Settings(
            self, rules_path, review_rules_path, summary_rules_path
        )
        self.incident_worker = asyncio.create_task(self.deliver_incidents())

        # Providers are loaded after plugins during a cold start, but already
        # exist when a running AstrBot installs or reloads this plugin.
        if context.get_all_providers():
            await self.tasks.start()

    @filter.on_astrbot_loaded()
    async def on_astrbot_loaded(self):
        await self.tasks.start()

    async def deliver_incidents(self):
        while True:
            try:
                routes = incident_routes(
                    self.config.get("incident_routes", []),
                    self.config.get("group_ids", []),
                )
                if routes:
                    client = self.tasks.client
                    cursor = self.store.get("incident_cursor", client.url) or {"seq": 0}
                    async with asyncio.timeout(15):
                        rows = await client.request(
                            "GET", "/incidents", params={"after": cursor["seq"]}
                        )
                    for row in rows:
                        origin = routes.get(row["instance"])
                        if origin and not self.context.get_platform_inst(
                            origin.split(":", 1)[0]
                        ):
                            break
                        if origin:
                            key = "incident-" + row["id"]
                            if not self.store.get("outbox", key):
                                self.store.save(
                                    "outbox",
                                    key,
                                    {
                                        "id": key,
                                        "task": None,
                                        "origin": origin,
                                        "mention": None,
                                        "text": (
                                            f"「{row['instance']}」：{row['summary']}，"
                                            + (
                                                "已保留现场。"
                                                if row["console_status"] == "complete"
                                                else "已记录事件，控制台证据不完整。"
                                            )
                                        ),
                                        "sent": False,
                                    },
                                )
                        self.store.save(
                            "incident_cursor", client.url, {"seq": row["seq"]}
                        )
            except (RemoteError, OSError, ValueError, TimeoutError) as exc:
                self.store.log("incident_delivery_pending", error=str(exc))
            await asyncio.sleep(15)

    async def notify(self, item):
        origin, text, mention = item["origin"], item["text"], item["mention"]
        mentions = [At(qq=mention)] if mention else []
        sent = item.get("parts_sent", 0)
        chains = [mentions + [Plain(text)]]
        threshold = self.config.get(
            "group_forward_threshold", DEFAULT_GROUP_FORWARD_THRESHOLD
        )
        if sent or len(text) > min(threshold, GROUP_MESSAGE_PART_LIMIT):
            platform = self.context.get_platform_inst(origin.split(":", 1)[0])
            if platform and platform.meta().name == "aiocqhttp":
                if sent:
                    chains = [mentions]
                elif len(text) > threshold:
                    login = await platform.get_client().get_login_info()
                    chains = [[forwarded_text(text, login["user_id"])]]
                    if mentions:
                        chains.append(mentions)
            elif len(text) > GROUP_MESSAGE_PART_LIMIT:
                chains = [[Plain(part)] for part in message_parts(text)]
                chains[0][:0] = mentions
                chains = chains[sent:]
        for index, chain in enumerate(chains, 1):
            result = await self.context.send_message(origin, MessageChain(chain))
            if result is False:
                raise RuntimeError("平台暂时无法发送消息")
            if index < len(chains):
                # 后续分段或 @ 失败时，重试从它开始并使用独立的发送次数。
                item.update(parts_sent=sent + index, attempts=1)
                self.store.save("outbox", item["id"], item)

    @filter.command("mcaihelp", alias=COMMANDS - {"mcaihelp"}, priority=100)
    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE, priority=100)
    async def commands(self, event: AstrMessageEvent):
        # A live install with no configured providers still needs its outbox
        # and must report configuration errors when a command arrives.
        await self.tasks.start()
        text = event.get_message_str().strip()
        command, *arguments = text.split(maxsplit=1)
        tail = arguments[0] if arguments else ""
        command = command.removeprefix("/")
        if command not in COMMANDS:
            return
        group = event.get_group_id()
        sender = event.get_sender_id()
        is_admin = event.is_admin() or sender in {
            str(item) for item in self.config.get("admin_ids", [])
        }
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
        trace_event(self.store, "plugin_command", **trace)
        if self.config.get("group_ids") and group not in {
            str(item) for item in self.config["group_ids"]
        }:
            trace_event(
                self.store,
                "command_result",
                **trace,
                status="rejected",
                reason="群不在允许范围",
            )
            event.stop_event()
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

        def reply(text):
            trace_event(
                self.store, "command_reply", **trace, reply=text, status="prepared"
            )
            if onebot and len(text) > self.config.get(
                "group_forward_threshold", DEFAULT_GROUP_FORWARD_THRESHOLD
            ):
                settings = self.context.get_config(event.unified_msg_origin)[
                    "platform_settings"
                ]
                chain = [
                    forwarded_text(settings["reply_prefix"] + text, event.get_self_id())
                ]
                if settings["reply_with_mention"]:
                    chain.append(At(qq=sender))
                return event.chain_result(chain)
            return event.plain_result(text)

        try:
            if command not in {
                "mcaisay",
                "mcaistatus",
                "mcaihelp",
                "mcailist",
                "mcaiplan",
            }:
                if not is_admin:
                    status = "rejected"
                    yield reply("该指令仅管理员可用。")
                    return
            if command == "mcaihelp":
                yield reply(
                    "管理员创建：“/mcainew 任务名 问题描述”（也可引用问题，附加补充说明）\n"
                    "群成员补充：“/mcaisay 任务名 内容”\n"
                    "创建和补充均将任务名后的整段文字作为内容，支持空格和换行。\n"
                    "管理员控制成员补充：“/mcaisaymode 任务名 false”（暂停）或 “/mcaisaymode 任务名 true”（开启）；管理员仍可补充\n"
                    "查看：“/mcailist [页码]”、“/mcaistatus 任务名”、“/mcaiplan 任务名”\n"
                    "管理员批准：“/mcaiapply 任务名”\n"
                    "管理员暂停／续接：“/mcaipause 任务名”、“/mcairesume 任务名”\n"
                    "管理员中止／验收：“/mcaistop 任务名”、“/mcaidone 任务名”"
                )
                return
            if command == "mcailist":
                yield reply(self.tasks.list_tasks(group, int(tail.strip() or "1")))
                return
            name, *arguments = tail.split(maxsplit=1) or [""]
            content = arguments[0] if arguments else ""
            if command == "mcainew":
                if not name:
                    raise ValueError(
                        "用法：“/mcainew 任务名 问题描述”，或引用问题后 “/mcainew 任务名 [补充说明]”"
                    )
                quoted = [
                    part for part in event.get_messages() if isinstance(part, Reply)
                ]
                report = quoted[0].message_str if quoted else ""
                if report and content.strip():
                    report += "\n\n创建者补充：\n" + content.strip()
                elif not report:
                    report = content.strip()
                if not report.strip():
                    raise ValueError(
                        f"用法：“/mcainew {name} 问题描述”，或引用一条包含问题的消息后 “/mcainew {name}”"
                    )
                job = await self.tasks.create(
                    group,
                    event.unified_msg_origin,
                    name,
                    None,
                    sender,
                    report,
                )
                trace["task"] = job["id"]
                return
            if not name:
                usage = f"/{command} 任务名"
                if command == "mcaisay":
                    usage += " 内容"
                elif command == "mcaisaymode":
                    usage += " true|false"
                raise ValueError(f"用法：“{usage}”；忘记任务名可用 “/mcailist” 查看。")
            job = self.tasks.find(group, name)
            trace["task"] = job["id"]
            if command == "mcaisay":
                if not content.strip():
                    raise ValueError(f"用法：“/mcaisay {name} 内容”，请填写补充信息。")
                self.tasks.feedback(
                    job,
                    sender,
                    content.strip(),
                    is_admin=is_admin,
                    feedback_id=trace["event_id"],
                )
                if job["state"] == "paused":
                    yield reply(
                        f"「{name}」：补充已保存；任务仍暂停，管理员使用 “/mcairesume {name}” 后会一起读取。"
                    )
            elif command == "mcaisaymode":
                mode = content.strip()
                if mode not in ("true", "false"):
                    raise ValueError(
                        f"用法：“/mcaisaymode {name} true|false”；true 开启、false 暂停普通成员补充，管理员仍可补充。"
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
                self.tasks.approve(job)
            elif command == "mcaistop":
                self.tasks.stop(job)
            elif command == "mcaidone":
                self.tasks.stop(job, done=True)
            elif command == "mcairesume":
                self.tasks.resume(job)
            elif command == "mcaipause":
                self.tasks.pause_requested(job)
            elif command == "mcaiplan":
                text = (
                    plan_text(job["plan"])
                    + (
                        f"\n任务已暂停，管理员续接：“/mcairesume {name}”"
                        if job["state"] == "paused"
                        else f"\n管理员批准：“/mcaiapply {name}”"
                    )
                    + f"\n需调整：“/mcaisay {name} 内容”"
                    if job["plan"]
                    else f"当前没有待批准方案。使用 “/mcaistatus {name}” 查看进度，或 “/mcaisay {name} 内容” 补充线索。"
                )
                approved = job.get("approved_plan")
                if not job["plan"] and approved:
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
                    text = (
                        plan_text(approved["snapshot"]["plan"])
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
                text = f"「{name}」：{text}"
                if onebot:
                    yield reply(text)
                else:
                    for part in message_parts(text):
                        yield reply(part)
            else:
                say_paused = job.get("say_paused", False)
                audience = "管理员" if say_paused else "群成员"
                state = {
                    "running": f"排查中。{audience}可用 “/mcaisay {name} 内容” 补充线索。",
                    "applying": f"修复中。{audience}可用 “/mcaisay {name} 内容” 补充，执行结束后读取。",
                    "waiting": (
                        f"等待批准。\n查看方案：“/mcaiplan {name}”\n管理员批准：“/mcaiapply {name}”\n需调整：“/mcaisay {name} 内容”"
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
                if job.get("trial"):
                    state["running"] = "正在根据本轮试玩反馈继续排查。"
                    state["waiting"] = (
                        f"正式服已完成启动检查。确认后使用 “/mcaidone {name}” 验收。"
                        if job.get("trial_published")
                        else f"正式服尚未完成发布。{job.get('trial_question') or '等待本轮试玩反馈。'}"
                    )
                if job.get("release_submitted") and job.get("operation"):
                    state["applying"] = (
                        f"正在核对正式服操作 {job['operation']} 的进度。"
                    )
                yield reply(
                    f"「{name}」：{state.get(job['state'], job['state'])}"
                    + (
                        f"\n普通成员 say：暂停，管理员仍可补充。恢复：“/mcaisaymode {name} true”"
                        if say_paused
                        else f"\n普通成员 say：开启。管理员暂停接收：“/mcaisaymode {name} false”"
                    )
                )
        except ValueError as exc:
            status = "rejected"
            yield reply(str(exc))
        except Exception as exc:
            status = "failed"
            trace["error"] = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            trace_event(self.store, "command_result", **trace, status=status)
            # yield 的回复先经过发送阶段，再终止后续处理。
            event.stop_event()

    async def terminate(self):
        self.incident_worker.cancel()
        await asyncio.gather(self.incident_worker, return_exceptions=True)
        await self.settings.close()
        await self.tasks.close()
        self.workspace_memory.close()
        self.store.close()
