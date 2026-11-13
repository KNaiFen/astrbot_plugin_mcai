import asyncio
import json
import re
import time
import traceback
import uuid

from .agent_runtime import RETRY_DELAYS, retryable
from .client import RemoteError
from .knowledge import Knowledge
from .review import digest
from .web import WebPages


class Tasks:
    """Durable group tasks with short notifications and one worker per task."""

    def __init__(self, store, client, agent, notify):
        self.store, self.client, self.agent, self.notify = store, client, agent, notify
        self.jobs = {job["id"]: job for job in store.live_tasks()}
        self.knowledge = Knowledge(store.directory)
        self.web = WebPages(store)
        self.archive_workers = {}
        self.create_lock = asyncio.Lock()
        self.workers = {}
        self.outbox_worker = None
        self.closing = False

    def save(self, job):
        self.store.save("task", job["id"], job)

    def log(self, job, kind, **data):
        self.store.log(kind, task=job["id"], **data)

    def find(self, group, name):
        matches = [
            job
            for job in self.jobs.values()
            if job["group"] == group
            and job["name"] == name
            and job["state"] not in ("done", "stopped")
        ]
        if not matches:
            raise ValueError("没有这个进行中的任务")
        return matches[0]

    async def start(self):
        self.outbox_worker = asyncio.create_task(self.deliver())
        for job in self.jobs.values():
            if job.get("archive_state") in ("pending", "ready"):
                self.archive_later(job)
            if job.get("cancel_pending"):
                self.wake(job)
            elif job["state"] == "running":
                job["pending"].append(
                    {
                        "sender": "system",
                        "text": "插件重启，请根据已保存的上下文和操作结果继续排查。",
                    }
                )
                self.save(job)
                self.wake(job)
            elif job["state"] == "applying":
                self.wake(job)

    def message(self, job, text, mention=None):
        text = text.strip()
        if not text:
            return
        # Full text stays in the log even when the group-facing output is capped.
        self.log(job, "group_message", text=text)
        if len(text) > 280:
            urls = list(dict.fromkeys(re.findall(r"https?://[^\s<>]+", text)))[:3]
            body = re.sub(r"https?://[^\s<>]+", "", text) if urls else text
            text = body[:280] + "…" + ("\n" + "\n".join(urls) if urls else "")
        key = uuid.uuid4().hex
        self.store.save(
            "outbox",
            key,
            {
                "id": key,
                "origin": job["origin"],
                "text": f"「{job['name']}」{text}",
                "mention": mention,
                "sent": False,
            },
        )

    def summary(self, job, identity, text):
        if job["stop_requested"] or not text.strip():
            return
        key = digest({"task": job["id"], "summary": identity})
        if self.store.get("summary", key):
            return
        self.log(job, "api_summary", identity=identity, text=text)
        offset = 0
        while offset < len(text):
            end = min(offset + 1800, len(text))
            if end < len(text):
                boundary = text.rfind("\n", offset, end)
                if boundary >= offset:
                    end = boundary + 1
            item_id = f"summary-{key}-{offset}"
            if not self.store.get("outbox", item_id):
                self.store.save(
                    "outbox",
                    item_id,
                    {
                        "id": item_id,
                        "origin": job["origin"],
                        "text": f"「{job['name']}」" + text[offset:end],
                        "mention": None,
                        "sent": False,
                        "summary_task": job["id"],
                    },
                )
            offset = end
        self.store.save("summary", key, {"id": key})

    def pause(self, job, reason):
        if job["stop_requested"] or job["state"] == "paused":
            return
        job.update(state="paused", pause_reason=reason)
        self.log(job, "task_paused", reason=reason)
        self.save(job)
        self.message(
            job,
            f"已保存进度并暂停：{reason[:100]}。使用 /mcairesume {job['name']} 续接。",
            job["admin"],
        )

    def resume(self, job):
        if job["state"] != "paused" or job["stop_requested"]:
            raise ValueError("当前任务未暂停")
        if job["id"] in self.workers:
            raise ValueError("正在保存暂停进度，请稍后续接")
        reason = job.pop("pause_reason")
        self.log(job, "task_resumed", previous_reason=reason)
        job.pop("model_retry", None)
        job["state"] = "applying" if job.get("operation") else "running"
        job["pending"].append(
            {
                "sender": "system",
                "text": "管理员要求从已保存进度继续。先核对原操作和后台任务结果。",
            }
        )
        self.save(job)
        self.message(job, "继续排查。")
        self.wake(job)

    async def deliver(self):
        delay = 1
        while True:
            failed = False
            for item in self.store.pending_outbox():
                if (
                    item.get("summary_task")
                    and self.store.get("task", item["summary_task"])["stop_requested"]
                ):
                    item.update(sent=True, discarded=True)
                    self.store.save("outbox", item["id"], item)
                    continue
                try:
                    await self.notify(item["origin"], item["text"], item["mention"])
                except Exception:
                    self.store.log(
                        "message_delivery_error", traceback=traceback.format_exc()
                    )
                    failed = True
                    break
                item["sent"] = True
                self.store.save("outbox", item["id"], item)
            delay = min(delay * 2, 15) if failed else 1
            await asyncio.sleep(delay)

    async def create(self, group, origin, name, instance, sender, report):
        async with self.create_lock:
            return await self._create(group, origin, name, instance, sender, report)

    async def _create(self, group, origin, name, instance, sender, report):
        if " " in name or len(name) > 40:
            raise ValueError("任务名请控制在 40 字内，不带空格")
        if any(
            job["group"] == group
            and job["name"] == name
            and job["state"] not in ("done", "stopped")
            for job in self.jobs.values()
        ):
            raise ValueError("任务名已存在")
        if instance is not None and any(
            job["instance"] == instance and job["state"] not in ("done", "stopped")
            for job in self.jobs.values()
        ):
            raise ValueError("该服务端已有进行中的排障任务")
        entry = None
        if instance is not None:
            entry = next(
                (
                    item
                    for item in await self.instances()
                    if item["instance"] == instance
                ),
                None,
            )
            if entry is None:
                raise ValueError("实例不存在")
        job = {
            "id": uuid.uuid4().hex,
            "group": group,
            "origin": origin,
            "name": name,
            "instance": instance,
            "admin": sender,
            "state": "running",
            "pending": [{"sender": sender, "text": report}],
            "messages": [],
            "plan": None,
            "operation": None,
            "stop_requested": False,
            "created": time.time(),
            "participants": [],
            "report": report,
            "feedback": [],
            "repair_submitted": False,
        }
        if entry:
            job["directory"] = entry["canonical_directory"]
        self.jobs[job["id"]] = job
        self.log(job, "task_created", report=report, admin=sender, instance=instance)
        self.save(job)
        self.message(job, "开始排查。")
        self.wake(job)
        return job

    async def instances(self):
        entries = await self.client.request("GET", "/instances")
        for item in entries:
            item["occupied"] = any(
                job.get("directory") == item["canonical_directory"]
                and job["state"] not in ("done", "stopped")
                for job in self.jobs.values()
            )
        return entries

    async def select_instance(self, job, instance, reason):
        async with self.create_lock:
            return await self._select_instance(job, instance, reason)

    async def _select_instance(self, job, instance, reason):
        entry = next(
            (item for item in await self.instances() if item["instance"] == instance),
            None,
        )
        if entry is None:
            raise ValueError("实例不存在，请先 mc_instances 识别目标")
        if not entry.get("selectable", True):
            raise ValueError("实例已待移除，不能绑定新任务")
        directory = entry["canonical_directory"]
        old = job.get("directory")
        changing = (old is not None and old != directory) or (
            job["instance"] is not None and job["instance"] != instance
        )
        if changing and (job.get("repair_submitted") or job.get("operation")):
            raise ValueError(
                "本任务已提交修复，不能更换服务端，请为其他服务端创建新任务"
            )
        if any(
            other["id"] != job["id"]
            and other.get("directory") == directory
            and other["state"] not in ("done", "stopped")
            for other in self.jobs.values()
        ):
            raise ValueError("该服务端已有进行中的排障任务，请向原任务补充反馈")
        if old and old != directory:
            cleanup = job.setdefault(
                "selection_cleanup",
                {
                    "instance": job["instance"],
                    "target": directory,
                    "arguments": {"mode": "cancel_task", "expected_directory": old},
                    "operation_id": uuid.uuid4().hex,
                },
            )
            if cleanup["target"] != directory:
                raise ValueError("上次目标切换尚未结算，请先继续原选择并核对清理结果")
            self.save(job)
            await self.client.call(
                cleanup["instance"],
                "job",
                cleanup["arguments"],
                operation_id=cleanup["operation_id"],
                task_id=job["id"],
            )
            job.pop("selection_cleanup")
            job["background"] = {}
            job["plan"] = None
        job.update(instance=instance, directory=directory)
        if old != directory:
            self.log(
                job,
                "instance_selected",
                instance=instance,
                directory=directory,
                reason=reason,
            )
            for previous in self.jobs.values():
                if previous.get("directory") == directory and previous.get(
                    "archive_state"
                ) in ("pending", "ready"):
                    self.archive_later(previous)
        self.save(job)
        return {
            **entry,
            "selected": True,
            "previous_directory": old,
            "old_plan_invalidated": old is not None and old != directory,
            "history": self.knowledge.context(
                directory,
                job["report"]
                + "\n"
                + "\n".join(item["text"] for item in job["feedback"]),
            ),
        }

    def archive_later(self, job):
        if job["id"] not in self.archive_workers:
            self.archive_workers[job["id"]] = asyncio.create_task(self.archive(job))

    async def archive(self, job):
        try:
            if job.get("archive_state") != "ready":
                for attempt in range(getattr(self.agent, "attempts", 3)):
                    job["archive_attempt"] = attempt + 1
                    self.save(job)
                    try:
                        text = await self.agent.summarize(self, job)
                        if not text.strip():
                            raise ValueError("验收总结返回空内容")
                        job.update(archive_state="ready", archive_text=text)
                        self.save(job)
                        break
                    except asyncio.CancelledError:
                        raise
                    except Exception as exc:
                        job["archive_error"] = f"{type(exc).__name__}: {exc}"
                        self.log(job, "archive_failed", error=job["archive_error"])
                        self.save(job)
                        if not retryable(exc) or attempt + 1 == getattr(
                            self.agent, "attempts", 3
                        ):
                            return
                        await asyncio.sleep(RETRY_DELAYS[min(attempt, 1)])
            await self.knowledge.append(job, job["archive_text"])
            job["archive_state"] = "completed"
            self.save(job)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            job["archive_error"] = f"{type(exc).__name__}: {exc}"
            self.log(
                job,
                "archive_failed",
                error=job["archive_error"],
                traceback=traceback.format_exc(),
            )
            self.save(job)
        finally:
            self.archive_workers.pop(job["id"], None)

    def feedback(self, job, sender, text):
        if job["stop_requested"] or job["state"] in ("done", "stopped"):
            raise ValueError("任务已停止接收反馈")
        job["pending"].append({"sender": sender, "time": time.time(), "text": text})
        job.setdefault("feedback", []).append({"sender": sender, "text": text})
        if sender not in job["participants"]:
            job["participants"].append(sender)
        if job["state"] != "applying":
            job["plan"] = None
        self.log(job, "feedback", sender=sender, text=text)
        self.save(job)
        if job["state"] not in ("applying", "paused"):
            self.wake(job)

    def drain(self, job):
        pending = job["pending"]
        job["pending"] = []
        return "\n".join(json.dumps(item, ensure_ascii=False) for item in pending)

    def propose(
        self,
        job,
        summary,
        steps,
        script_hashes=None,
        reviewed=None,
        launcher_identity=None,
    ):
        if job["state"] == "applying":
            raise ValueError("修复正在执行")
        if not steps:
            raise ValueError("修复步骤不能为空")
        job["plan"] = {"summary": summary, "steps": steps, "offline": True}
        if reviewed is not None:
            job["plan"].update(script_hashes=script_hashes, reviewed=reviewed)
            if launcher_identity:
                job["plan"]["launcher_identity"] = launcher_identity
        if job.get("directory"):
            job["plan"]["expected_directory"] = job["directory"]
        self.save(job)
        self.log(job, "plan", plan=job["plan"])
        unbacked = any(
            step["action"] == "command" and not step.get("backup_paths")
            for step in steps
        )
        note = "\n在线命令无恢复备份。" if unbacked else ""
        self.message(
            job,
            f"{summary[:150]}{note}\n使用 /mcaiapply {job['name']} 确认。",
            job["admin"],
        )

    def approve(self, job):
        if job["state"] == "paused":
            raise ValueError("任务已暂停，请先 /mcairesume 续接")
        if not job["plan"]:
            raise ValueError("当前没有待批准的修复方案")
        if job["state"] == "applying":
            raise ValueError("修复已在执行")
        if job["id"] in self.workers:
            raise ValueError("正在整理排查结果，请稍后再批准")
        job.update(
            state="applying",
            operation=uuid.uuid4().hex,
            applied_plan=job["plan"],
            plan=None,
        )
        self.save(job)
        self.message(job, "收到，正在执行。")
        self.wake(job)

    def stop(self, job, done=False):
        if done and job["state"] == "applying":
            raise ValueError("修复正在执行，请完成后验收，或使用 /mcaistop 中止")
        job["stop_requested"] = True
        job["cancel_pending"] = True
        job["finish_as"] = "done" if done else "stopped"
        self.agent.stop(job["id"])
        job["plan"] = None
        if job["id"] not in self.workers:
            job["state"] = "done" if done else "stopped"
        self.save(job)
        self.message(
            job,
            "已验收，任务结束。"
            if done
            else "已停止接收反馈，当前操作会在安全步骤结束后停止。",
        )
        self.wake(job)

    def pause_requested(self, job):
        if job["state"] == "applying":
            job["pause_after_operation"] = True
            self.save(job)
            self.message(job, "当前修复操作完成后暂停，进度会保留。")
        else:
            self.agent.stop(job["id"])
            self.pause(job, "管理员手动暂停")
            worker = self.workers.get(job["id"])
            if worker:
                worker.cancel()

    def list_tasks(self, group, page=1):
        if page < 1:
            raise ValueError("页码从 1 开始")
        rows = [
            item
            for item in self.jobs.values()
            if item["group"] == group and item["state"] not in ("done", "stopped")
        ]
        pages = max(1, (len(rows) + 7) // 8)
        if page > pages:
            raise ValueError(f"只有 {pages} 页任务")
        state = {
            "running": "排查中",
            "applying": "修复中",
            "waiting": "等待",
            "paused": "已暂停",
        }
        lines = [f"任务 {page}/{pages}"]
        for item in rows[(page - 1) * 8 : page * 8]:
            label = (
                "待批准"
                if item["state"] == "waiting" and item["plan"]
                else state.get(item["state"], item["state"])
            )
            lines.append(
                f"{item['name']} · {item['instance'] or '待识别'} · {label}"
                + (
                    f"：{item.get('pause_reason', '')[:32]}"
                    if item["state"] == "paused"
                    else ""
                )
            )
        return "\n".join(lines) if rows else "当前群没有活动任务。"

    def wake(self, job):
        if job["id"] not in self.workers:
            self.workers[job["id"]] = asyncio.create_task(self.run(job))

    async def run(self, job):
        try:
            if job["state"] == "applying":
                if not hasattr(
                    self.agent, "prepare_apply"
                ) or await self.agent.prepare_apply(self, job):
                    key = job["operation"]
                    job["repair_submitted"] = True
                    self.save(job)
                    try:
                        result = await self.client.call(
                            job["instance"],
                            "apply_plan",
                            job["applied_plan"],
                            operation_id=key,
                            task_id=job["id"],
                            stopped=lambda: job["stop_requested"],
                        )
                        self.log(job, "repair_result", result=result)
                        job.setdefault("repairs", []).append(
                            {"operation": key, "result": result}
                        )
                        job["pending"].append(
                            {
                                "sender": "system",
                                "text": "已批准修复的执行结果："
                                + json.dumps(result, ensure_ascii=False)
                                + "。请读取状态和日志验证，不要把进程启动直接视为故障解决。",
                            }
                        )
                    except RemoteError as exc:
                        # A definitive failed operation is investigated, not submitted again.
                        job["failed_operation"] = key
                        self.log(job, "repair_failed", operation=key, error=str(exc))
                        record = await self.client.call(
                            job["instance"],
                            "repair_log",
                            {"operation": key},
                            task_id=job["id"],
                        )
                        status = await self.client.call(
                            job["instance"], "status", task_id=job["id"]
                        )
                        job.setdefault("repairs", []).append(
                            {"operation": key, "failure": record}
                        )
                        console = await self.client.call(
                            job["instance"],
                            "console_query",
                            {"limit": 20},
                            task_id=job["id"],
                        )
                        job["pending"].append(
                            {
                                "sender": "system",
                                "text": f"上次修复失败，操作编号 {key}，原方案后续步骤已停止。保留备份和已完成修改，不自动回滚或启动。请结合下列记录、状态、控制台及相关日志继续排查；有方向则重新提案等待再次批准，没有方向则 mc_pause："
                                + json.dumps(
                                    {
                                        "repair": record,
                                        "status": status,
                                        "console": console,
                                    },
                                    ensure_ascii=False,
                                ),
                            }
                        )
                    job["operation"] = None
                    job["state"] = "running"
                    self.save(job)
                    if job.pop("pause_after_operation", False):
                        self.pause(job, "管理员要求在修复操作完成后暂停")
            while not job["stop_requested"] and job["state"] != "paused":
                job["state"] = "running"
                self.save(job)
                await self.agent.run(self, job)
                if job["state"] == "paused":
                    break
                if job["plan"] and not job["pending"]:
                    break
                if not job["pending"]:
                    background = job.setdefault("background", {})
                    while (
                        background
                        and not job["pending"]
                        and not job["stop_requested"]
                        and job["state"] != "paused"
                    ):
                        for key, state in list(background.items()):
                            result = await self.client.request(
                                "GET", f"/jobs/{key}", params={"after": state["cursor"]}
                            )
                            if result["status"] not in ("pending", "running"):
                                job["pending"].append(
                                    {
                                        "sender": "system",
                                        "text": "后台诊断任务结束："
                                        + json.dumps(result, ensure_ascii=False),
                                    }
                                )
                                background.pop(key)
                                self.save(job)
                        if not job["pending"]:
                            await asyncio.sleep(0.5)
                    if not job["pending"]:
                        break
                job["plan"] = None
            if job["state"] != "paused":
                job["state"] = (
                    job.get("finish_as", "stopped")
                    if job["stop_requested"]
                    else "waiting"
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.log(
                job, "task_error", error=str(exc), traceback=traceback.format_exc()
            )
            self.pause(job, str(exc))
        finally:
            try:
                if job["stop_requested"] and not self.closing:
                    if job["instance"] is not None:
                        request = job.setdefault(
                            "cancel_request",
                            {
                                "instance": job["instance"],
                                "operation_id": uuid.uuid4().hex,
                                "arguments": {
                                    "mode": "cancel_task",
                                    **(
                                        {"expected_directory": job["directory"]}
                                        if job.get("directory")
                                        else {}
                                    ),
                                },
                            },
                        )
                        self.save(job)
                        await self.client.call(
                            request["instance"],
                            "job",
                            request["arguments"],
                            operation_id=request["operation_id"],
                            task_id=job["id"],
                        )
                    job["background"] = {}
                    job["cancel_pending"] = False
                    job.pop("cancel_error", None)
                    job["state"] = job.get("finish_as", "stopped")
                    if (
                        job["state"] == "done"
                        and job.get("directory")
                        and hasattr(self.agent, "summarize")
                    ):
                        job.setdefault("archive_state", "pending")
                        self.archive_later(job)
            except RemoteError as exc:
                job["cancel_error"] = f"{type(exc).__name__}: {exc}"
                self.log(job, "task_cancel_failed", error=job["cancel_error"])
            finally:
                self.save(job)
                self.workers.pop(job["id"], None)

    async def close(self):
        self.closing = True
        if self.outbox_worker:
            self.outbox_worker.cancel()
        workers = [*self.workers.values(), *self.archive_workers.values()]
        for worker in workers:
            worker.cancel()
        await asyncio.gather(
            *workers,
            *([self.outbox_worker] if self.outbox_worker else []),
            return_exceptions=True,
        )
        await self.client.close()
