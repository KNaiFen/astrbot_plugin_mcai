"""One effective action list for review, approval display and execution."""

import copy
from pathlib import PurePosixPath

from .review import digest

FILE_ACTIONS = {
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


def plan_text(plan):
    lines = [
        "测试副本实际步骤：" if plan.get("environment") == "test" else "实际步骤："
    ]
    labels = {"start": "启动服务端", "stop": "停止服务端", "restart": "重启服务端"}
    for index, step in enumerate(plan["steps"], 1):
        kind = step["action"]
        if kind in labels:
            detail = labels[kind]
        elif kind == "force_stop":
            detail = f"强制停止服务端及其自动重启启动链，保留托管窗口；Java PID {step['pid']}，会话 {step['session_id']}"
        elif kind == "snapshot":
            detail = "备份：" + "、".join(step["paths"])
        elif kind == "prepare_test":
            detail = "创建隔离测试副本：" + "、".join(step["paths"])
        elif kind == "copy_test_world":
            detail = "停服备份后复制测试世界：" + "、".join(step["paths"])
        elif kind == "command":
            detail = "控制台：" + step["command"]
        elif kind == "script":
            detail = "执行修复脚本；备份范围：" + "、".join(step["backup_paths"])
        elif kind == "verify":
            detail = "验证：" + "；".join(
                check["kind"] + (" " + check["path"] if "path" in check else "")
                for check in step["checks"]
            )
        elif kind == "restore":
            detail = f"恢复备份 {step['backup']}；覆盖：" + "、".join(
                step.get("targets", [])
            )
        elif kind == "install_download":
            detail = f"安装下载 {step['download_id']} → {step['path']}"
            if step.get("remove_paths"):
                detail += "；移除：" + "、".join(step["remove_paths"])
        else:
            detail = f"{kind}：{step['path']}"
            if "x" in step and "z" in step:
                detail += f"，区块 {step['x']},{step['z']}"
            if "block_x" in step:
                detail += (
                    f"，方块 {step['block_x']},{step['block_y']},{step['block_z']}"
                )
        lines.append(f"{index}. {detail}")
    lines.append("方案说明：" + plan["summary"])
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
