"""One effective action list for review, approval display and execution."""

import copy
import hashlib
from pathlib import PurePosixPath

from .review import digest

FILE_ACTIONS = {
    "block_batch",
    "region_prune",
    "nbt_prune",
    "write_text",
    "patch_text",
    "nbt_set",
    "nbt_delete",
    "nbt_batch",
    "region_batch",
    "block_set",
    "region_restore",
    "region_remove",
    "region_set",
    "region_delete",
    "script",
    "restore",
    "install_download",
    "copy_test_world",
}


def effective_steps(steps, running, target_lists):
    from .verification import validate_checks

    for step in steps:
        if step["action"] == "verify":
            validate_checks(step["checks"])
    originally_running = running
    explicit = any(
        step["action"] in ("start", "stop", "restart", "force_stop") for step in steps
    )
    targets = list(dict.fromkeys(path for paths in target_lists for path in paths))
    targets = [
        path
        for path in targets
        if not any(
            path != parent and PurePosixPath(path).is_relative_to(parent)
            for parent in targets
        )
    ]
    prepared, captured = [], False
    for original, paths in zip(steps, target_lists):
        step = copy.deepcopy(original)
        kind = step["action"]
        resume_command = (
            kind == "command" and running and bool(step.get("backup_paths"))
        )
        if kind in FILE_ACTIONS or kind == "command" and step.get("backup_paths"):
            if running:
                prepared.append({"action": "stop"})
                running = False
            if not captured:
                prepared.append({"action": "snapshot", "paths": targets})
                captured = True
        online = (
            kind == "command"
            or kind == "verify"
            and any(check["kind"] == "ready" for check in step["checks"])
        )
        if online and not running:
            if not resume_command and (explicit or not originally_running):
                raise ValueError(
                    "在线命令或就绪检查前服务端未运行，请在同一方案显式添加start"
                )
            prepared.append({"action": "start"})
            running = True
        if paths:
            step["targets"] = list(paths)
        prepared.append(step)
        if kind in ("start", "restart"):
            running = True
        elif kind in ("stop", "force_stop"):
            running = False
        if kind == "copy_test_world" and originally_running and not explicit:
            # The immutable backup is enough to finish copying after production resumes.
            prepared.insert(len(prepared) - 1, {"action": "start"})
            running = True
    if originally_running and not explicit and not running:
        prepared.append({"action": "start"})
    return prepared


def execution_configuration(config, steps=(), *, diagnostic=False):
    from .configuration import RESTART_PROMPT

    keys = {"directory"}
    actions = {step["action"] for step in steps}
    defaults = {
        "stop_command": "stop",
        "stop_timeout": 120,
        "restart_prompt": RESTART_PROMPT,
        "encoding": "auto",
    }
    if actions & {"stop", "restart"}:
        keys.update(("stop_command", "stop_timeout", "restart_prompt"))
    if diagnostic or actions & {"script", "start", "restart"}:
        keys.update(("powershell_path", "java_path"))
    if actions & {"start", "restart"}:
        keys.add("encoding")
    return {key: config.get(key, defaults.get(key)) for key in sorted(keys)}


def execution_configuration_changed(reviewed, current):
    """Compare only reviewed Java path and stop command; directory identity is separate."""
    return any(
        reviewed[key] != current.get(key)
        for key in ("java_path", "stop_command")
        if key in reviewed
    )


def plan_identity(plan):
    return digest(
        {
            key: plan[key]
            for key in (
                "summary",
                "steps",
                "continuation",
                "plan_id",
                "environment",
                "trial_release",
            )
            if key in plan
        }
    )


def approval_command(job):
    return f"/mcaiapply {job['name']} {job['plan']['approval_code']}"


def schedule_time(step):
    days = step.get("weekdays")
    prefix = (
        "每周" + "、".join("一二三四五六日"[day - 1] for day in days)
        if days
        else "每天"
    )
    return f"{prefix} {step['at']}（B 本机时间）"


def approval_excerpt(text):
    lines = text.splitlines()
    if len(text) <= 600 and len(lines) <= 8:
        return text
    preview = "\n".join(lines[:8])[:600]
    sha256 = hashlib.sha256(text.encode()).hexdigest()
    return f"{preview}\n…（原文 {len(lines)} 行、{len(text)} 字符，SHA-256：{sha256}）"


ACTION_LABELS = {
    "block_batch": "批量修改方块",
    "region_prune": "批量清理区域对象",
    "nbt_prune": "批量清理 NBT",
    "write_text": "写入文件",
    "patch_text": "修改文件",
    "nbt_set": "修改 NBT",
    "nbt_delete": "删除 NBT 字段",
    "nbt_batch": "批量修改 NBT",
    "region_set": "修改区块 NBT",
    "region_delete": "删除区块 NBT",
    "region_batch": "批量修改区块 NBT",
    "block_set": "修改方块",
    "region_restore": "恢复区块",
    "region_remove": "删除区块",
}


def verify_check_text(check):
    """Format one verification check into concise Chinese for group approval."""
    kind = check["kind"]
    if kind == "ready":
        return "确认启动就绪"
    if kind == "tcp":
        return "检查本地端口连通"
    if kind == "file":
        return f"校验文件格式：{check['path']}（{check['format'].upper()}）"
    if kind == "text":
        return (
            f"确认不含指定文本：{check['path']}"
            if check.get("present") is False
            else f"核对文本：{check['path']}"
        )
    if kind == "nbt":
        return f"核对 NBT：{check['path']}"
    if kind == "region":
        return f"核对区块 NBT：{check['path']}（{check['x']}, {check['z']}）"
    return f"{kind} {check['path']}" if "path" in check else kind


def plan_text(plan):
    lines = []
    if summary := (plan.get("summary") or "").strip():
        lines.append("方案说明：" + summary)
    lines.append(
        "测试副本执行步骤：" if plan.get("environment") == "test" else "执行步骤："
    )
    labels = {"start": "启动服务端", "stop": "停止服务端", "restart": "重启服务端"}
    for index, step in enumerate(plan["steps"], 1):
        kind = step["action"]
        if kind in labels:
            detail = labels[kind]
        elif kind == "force_stop":
            target = "启动器" if step.get("target") == "launcher" else "Java"
            detail = f"强制停止服务端（结束 {target} PID {step['pid']} 及自动重启，不补做保存）"
        elif kind == "snapshot":
            detail = "备份：" + "、".join(step["paths"])
        elif kind == "schedule":
            detail = f"登记定时{'备份' if step['kind'] == 'backup' else '重启'}：{schedule_time(step)}"
            if step["kind"] == "backup":
                detail += (
                    f"；{'在线' if step['mode'] == 'online' else '停服'}备份："
                    + "、".join(step["paths"])
                    + f"；保留 {step['retain']} 份；保存至 {step['backup_directory']}"
                )
            else:
                offsets = "、".join(map(str, step["announce_minutes"]))
                detail += (
                    f"；提前 {offsets} 分钟公告" if offsets else "；不在游戏内提前公告"
                )
            detail += "；成功也通知" if step["notify_success"] else "；仅通知异常或错过"
            if step.get("replace"):
                detail += f"；替换原计划 {step['replace']}"
        elif kind == "prepare_test":
            paths = step.get("paths")
            detail = (
                "创建隔离测试副本：" + "、".join(paths)
                if paths
                else "创建隔离测试副本（按默认配置复制）"
            )
        elif kind == "copy_test_world":
            detail = "停服备份后复制测试世界：" + "、".join(step["paths"])
        elif kind == "command":
            detail = "执行控制台命令：" + step["command"]
        elif kind == "script":
            detail = "执行修复脚本；备份范围：" + "、".join(step["backup_paths"])
        elif kind == "verify":
            detail = "验证：" + "；".join(
                verify_check_text(check) for check in step["checks"]
            )
        elif kind == "restore":
            detail = f"恢复备份 {step['backup']}；覆盖：" + "、".join(
                step.get("targets", [])
            )
        elif kind == "install_download":
            detail = f"安装组件到 {step['path']}"
            if step.get("remove_paths"):
                detail += "；移除旧文件：" + "、".join(step["remove_paths"])
        else:
            label = ACTION_LABELS.get(kind, kind)
            location = (
                step.get("path")
                or step.get("dimension")
                or step.get("world_path")
                or step.get("world")
                or "冻结扫描目标"
            )
            detail = f"{label}：{location}"
            if "changes" in step:
                detail += f"，共 {len(step['changes'])} 项"
            if "scan_job_id" in step:
                detail += "；按已冻结清单"
            if "bounds" in step:
                detail += f"；范围 {step['bounds']}，匹配上限 {step['max_matches']}"
            if kind in ("region_prune", "nbt_prune"):
                for key, title in (
                    ("entity_type", "实体类型"),
                    ("name", "方块"),
                    ("legacy_id", "旧方块ID"),
                ):
                    if key in step:
                        detail += f"；{title} {step[key]}"
                field = ".".join(map(str, step.get("relative_path", []))) or "匹配对象"
                detail += (
                    f"；删除 {field}"
                    if step["op"] == "delete"
                    else f"；设置 {field} 为 {step.get('state', step.get('value'))}"
                )
                if step.get("clear_block_entity"):
                    detail += "；同时移除对应方块实体"
            if step.get("targets") and "path" not in step:
                detail += "；目标：" + "、".join(step["targets"])
            if "x" in step and "z" in step:
                detail += f"，区块 ({step['x']}, {step['z']})"
            if "block_x" in step:
                detail += (
                    f"，坐标 ({step['block_x']}, {step['block_y']}, {step['block_z']})"
                )
        lines.append(f"{index}. {approval_excerpt(detail)}")
        if kind == "script":
            lines.append("脚本摘要：" + approval_excerpt(step["script"]))
    if directory := plan.get("expected_directory"):
        lines.append("目标实例目录：" + directory)
    if plan.get("continuation"):
        lines.extend(
            (
                "允许范围：" + plan["continuation"]["scope"],
                "完成条件：" + plan["continuation"]["completion"],
            )
        )
    if any(
        step["action"] == "command" and not step.get("backup_paths")
        for step in plan["steps"]
    ):
        lines.append("在线命令无恢复备份。")
    return "\n".join(lines)
