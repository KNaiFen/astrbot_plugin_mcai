from pathlib import Path

from astrbot.api import AstrBotConfig
from astrbot.api.event import AstrMessageEvent, MessageChain, filter
from astrbot.api.message_components import At, Plain, Reply
from astrbot.api.star import Context, Star
from astrbot.core.utils.astrbot_path import get_astrbot_data_path

from .mcai.astrbot_agent import AstrBotAgent
from .mcai.client import HostClient
from .mcai.storage import Store
from .mcai.tasks import Tasks

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
        rules_path = self.store.directory / "AGENTS.md"
        if not rules_path.exists():
            rules_path.write_text(
                (Path(__file__).parent / "mcai/agent_rules.md").read_text(
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
                review_provider_id=config.get("review_provider_id", ""),
                review_reasoning_effort=config.get("review_reasoning_effort", ""),
                model_max_attempts=config.get("model_max_attempts", 3),
                forward_reasoning_summary=config.get("forward_reasoning_summary", True),
                forward_reasoning_summary_body=config.get(
                    "forward_reasoning_summary_body", False
                ),
                reasoning_summary=config.get("reasoning_summary", "auto"),
                enable_web_search=config.get("enable_web_search", True),
                web_search_tool_type=config.get("web_search_tool_type", "web_search"),
                reasoning_effort=config.get("reasoning_effort", ""),
                enable_alpha_search=config.get("enable_alpha_search", False),
            ),
            self.notify,
        )
        from .mcai.settings import Settings

        self.settings = Settings(self, rules_path)

        await self.tasks.start()

    async def notify(self, origin, text, mention):
        chain = ([At(qq=mention)] if mention else []) + [Plain(text)]
        result = await self.context.send_message(origin, MessageChain(chain))
        if result is False:
            raise RuntimeError("平台暂时无法发送消息")

    @filter.command("mcaihelp", alias=COMMANDS - {"mcaihelp"}, priority=100)
    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE, priority=100)
    async def commands(self, event: AstrMessageEvent):
        text = event.get_message_str().strip()
        command, _, tail = text.partition(" ")
        command = command.removeprefix("/")
        if command not in COMMANDS:
            return
        group = event.get_group_id()
        if self.config.get("group_ids") and group not in {
            str(item) for item in self.config["group_ids"]
        }:
            event.stop_event()
            return
        sender = event.get_sender_id()
        is_admin = event.is_admin() or sender in {
            str(item) for item in self.config.get("admin_ids", [])
        }
        try:
            if command not in {
                "mcaisay",
                "mcaistatus",
                "mcaihelp",
                "mcailist",
                "mcaiplan",
            }:
                if not is_admin:
                    yield event.plain_result("该指令仅管理员可用。")
                    return
            if command == "mcaihelp":
                yield event.plain_result(
                    "管理员创建：/mcainew 任务名 问题描述（也可引用问题，附加补充说明）\n"
                    "群成员补充：/mcaisay 任务名 内容\n"
                    "管理员控制成员补充：/mcaisaymode 任务名 false（暂停）或 true（开启）；管理员仍可补充\n"
                    "查看：/mcailist [页码]、/mcaistatus 任务名、/mcaiplan 任务名\n"
                    "管理员批准：/mcaiapply 任务名\n"
                    "管理员暂停／续接：/mcaipause 任务名、/mcairesume 任务名\n"
                    "管理员中止／验收：/mcaistop 任务名、/mcaidone 任务名"
                )
                return
            if command == "mcailist":
                yield event.plain_result(
                    self.tasks.list_tasks(group, int(tail.strip() or "1"))
                )
                return
            name, _, content = tail.strip().partition(" ")
            if command == "mcainew":
                if not name:
                    raise ValueError(
                        "用法：/mcainew 任务名 问题描述，或引用问题后 /mcainew 任务名 [补充说明]"
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
                        f"用法：/mcainew {name} 问题描述，或引用一条包含问题的消息后 /mcainew {name}"
                    )
                await self.tasks.create(
                    group,
                    event.unified_msg_origin,
                    name,
                    None,
                    sender,
                    report,
                )
                return
            if not name:
                usage = f"/{command} 任务名"
                if command == "mcaisay":
                    usage += " 内容"
                elif command == "mcaisaymode":
                    usage += " true|false"
                raise ValueError(f"用法：{usage}；忘记任务名可用 /mcailist 查看。")
            job = self.tasks.find(group, name)
            if command == "mcaisay":
                if not content.strip():
                    raise ValueError(f"用法：/mcaisay {name} 内容，请填写补充信息。")
                self.tasks.feedback(job, sender, content.strip(), is_admin=is_admin)
                if job["state"] == "paused":
                    yield event.plain_result(
                        f"「{name}」补充已保存；任务仍暂停，管理员使用 /mcairesume {name} 后会一起读取。"
                    )
            elif command == "mcaisaymode":
                mode = content.strip()
                if mode not in ("true", "false"):
                    raise ValueError(
                        f"用法：/mcaisaymode {name} true|false；true 开启、false 暂停普通成员补充，管理员仍可补充。"
                    )
                self.tasks.set_say_mode(job, mode == "true", sender)
                yield event.plain_result(
                    f"「{name}」"
                    + (
                        f"已开启普通成员 say 接收。暂停：/mcaisaymode {name} false"
                        if mode == "true"
                        else f"已暂停普通成员 say 接收，管理员仍可补充。恢复：/mcaisaymode {name} true"
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
                yield event.plain_result(
                    f"「{name}」"
                    + (
                        job["plan"]["summary"][:220]
                        + (
                            f"\n任务已暂停，管理员续接：/mcairesume {name}"
                            if job["state"] == "paused"
                            else f"\n管理员批准：/mcaiapply {name}"
                        )
                        + f"\n需调整：/mcaisay {name} 内容"
                        if job["plan"]
                        else f"当前没有待批准方案。使用 /mcaistatus {name} 查看进度，或 /mcaisay {name} 内容 补充线索。"
                    )
                )
            else:
                say_paused = job.get("say_paused", False)
                audience = "管理员" if say_paused else "群成员"
                state = {
                    "running": f"排查中。{audience}可用 /mcaisay {name} 内容 补充线索。",
                    "applying": f"修复中。{audience}可用 /mcaisay {name} 内容 补充，执行结束后读取。",
                    "waiting": (
                        f"等待批准。\n查看方案：/mcaiplan {name}\n管理员批准：/mcaiapply {name}\n需调整：/mcaisay {name} 内容"
                        if job["plan"]
                        else f"等待反馈。{audience}使用 /mcaisay {name} 内容 继续；确认问题解决后，管理员使用 /mcaidone {name} 验收。"
                    ),
                    "paused": f"已暂停。{audience}可用 /mcaisay {name} 内容 保存补充；管理员使用 /mcairesume {name} 续接。",
                }
                yield event.plain_result(
                    f"「{name}」{state.get(job['state'], job['state'])}"
                    + (
                        f"\n普通成员 say：暂停，管理员仍可补充。恢复：/mcaisaymode {name} true"
                        if say_paused
                        else f"\n普通成员 say：开启。管理员暂停接收：/mcaisaymode {name} false"
                    )
                )
        except ValueError as exc:
            yield event.plain_result(str(exc))
        finally:
            # yield 的回复先经过发送阶段，再终止后续处理。
            event.stop_event()

    async def terminate(self):
        await self.settings.close()
        await self.tasks.close()
        self.store.close()
