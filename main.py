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

    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE, priority=100)
    async def commands(self, event: AstrMessageEvent):
        text = event.get_message_str().strip()
        command, _, tail = text.partition(" ")
        commands = {
            "/mcainew",
            "/mcaisay",
            "/mcaiapply",
            "/mcaistop",
            "/mcaidone",
            "/mcaistatus",
            "/mcaihelp",
            "/mcairesume",
            "/mcailist",
            "/mcaiplan",
            "/mcaipause",
        }
        if command not in commands:
            return
        event.stop_event()
        group = event.get_group_id()
        if self.config.get("group_ids") and group not in {
            str(item) for item in self.config["group_ids"]
        }:
            return
        sender = event.get_sender_id()
        if command not in {
            "/mcaisay",
            "/mcaistatus",
            "/mcaihelp",
            "/mcailist",
            "/mcaiplan",
        }:
            if not event.is_admin() and sender not in {
                str(item) for item in self.config.get("admin_ids", [])
            }:
                yield event.plain_result("该指令仅管理员可用。")
                return
        try:
            if command == "/mcaihelp":
                yield event.plain_result(
                    "回复问题：/mcainew 任务名\n补充：/mcaisay 任务名 内容\n查看：/mcailist、/mcaistatus、/mcaiplan\n管理员：/mcaiapply、/mcaipause、/mcairesume、/mcaistop、/mcaidone 任务名"
                )
                return
            if command == "/mcailist":
                yield event.plain_result(
                    self.tasks.list_tasks(group, int(tail.strip() or "1"))
                )
                return
            name, _, content = tail.strip().partition(" ")
            if command == "/mcainew":
                instance, name = None, tail.strip()
                if not name:
                    raise ValueError("用法：回复问题消息后 /mcainew 任务名")
                quoted = [
                    part for part in event.get_messages() if isinstance(part, Reply)
                ]
                if not quoted or not quoted[0].message_str:
                    raise ValueError("请回复一条包含问题的消息来创建任务")
                await self.tasks.create(
                    group,
                    event.unified_msg_origin,
                    name,
                    instance,
                    sender,
                    quoted[0].message_str,
                )
                return
            job = self.tasks.find(group, name)
            if command == "/mcaisay":
                if not content.strip():
                    raise ValueError("请在任务名后填写补充信息")
                self.tasks.feedback(job, sender, content.strip())
            elif command == "/mcaiapply":
                self.tasks.approve(job)
            elif command == "/mcaistop":
                self.tasks.stop(job)
            elif command == "/mcaidone":
                self.tasks.stop(job, done=True)
            elif command == "/mcairesume":
                self.tasks.resume(job)
            elif command == "/mcaipause":
                self.tasks.pause_requested(job)
            elif command == "/mcaiplan":
                yield event.plain_result(
                    f"「{name}」"
                    + (
                        job["plan"]["summary"][:220] + f"\n批准：/mcaiapply {name}"
                        if job["plan"]
                        else "当前没有待批准方案。"
                    )
                )
            else:
                state = {
                    "running": "排查中",
                    "applying": "修复中",
                    "waiting": "等待批准" if job["plan"] else "等待反馈",
                    "paused": "已暂停，使用 /mcairesume 续接",
                }
                yield event.plain_result(
                    f"「{name}」{state.get(job['state'], job['state'])}"
                )
        except ValueError as exc:
            yield event.plain_result(str(exc))

    async def terminate(self):
        await self.settings.close()
        await self.tasks.close()
        self.store.close()
