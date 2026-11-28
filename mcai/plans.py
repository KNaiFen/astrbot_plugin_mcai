"""One effective action list for review, approval display and execution."""

import copy
import hashlib
import re
from pathlib import PurePosixPath
from posixpath import normpath

import nbtlib

from .review import digest, is_safe_test_console_commands

INITIAL_REPORT_FEEDBACK_ID = "report"
FILE_ACTIONS = {
    "block_batch",
    "region_prune",
    "nbt_prune",
    "write_text",
    "patch_text",
    "delete_path",
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
TEST_DIRECT_CONFIG_SUFFIXES = frozenset(
    {
        ".properties",
        ".toml",
        ".yml",
        ".yaml",
        ".json",
        ".json5",
        ".cfg",
        ".conf",
        ".ini",
        ".snbt",
    }
)


def is_test_direct_plan(steps, dependencies, target_lists=None):
    if dependencies.get("known") is not True or not steps:
        return False
    launch_paths = {PurePosixPath(path.casefold()) for path in dependencies["paths"]}
    for index, step in enumerate(steps):
        action = step["action"]
        path = PurePosixPath(
            normpath(step.get("path", "").replace("\\", "/")).casefold()
        )
        if action in ("write_text", "patch_text"):
            if (
                path.suffix not in TEST_DIRECT_CONFIG_SUFFIXES
                and path.as_posix() != "eula.txt"
            ):
                return False
        elif action == "command":
            if not is_safe_test_console_commands([step["command"]]):
                return False
        elif action not in (
            FILE_ACTIONS
            - {
                "script",
                "restore",
                "install_download",
                "copy_test_world",
                "region_restore",
            }
            | {"start", "restart", "stop", "force_stop", "verify"}
        ):
            return False
        paths = (
            [PurePosixPath(name.casefold()) for name in target_lists[index]]
            if target_lists is not None
            else [path]
            if "path" in step
            else []
        )
        if any(
            item.is_absolute()
            or ".." in item.parts
            or any(dep.is_relative_to(item) for dep in launch_paths)
            for item in paths
        ):
            return False
    return True


def validate_checks(checks):
    for index, check in enumerate(checks):
        if not check.get("regex"):
            continue
        for field in (
            ("pattern", "forbid")
            if check["kind"] == "ready"
            else ("query",)
            if check["kind"] == "text"
            else ()
        ):
            if field in check:
                try:
                    re.compile(check[field])
                except re.error as exc:
                    raise ValueError(
                        f"checks[{index}].{field} 正则无效：{exc}"
                    ) from exc


def effective_steps(steps, running, target_lists, *, skip_backup=False):
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
            if not captured and not skip_backup:
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
    return {
        **{key: config.get(key, defaults.get(key)) for key in sorted(keys)},
        "is_test": bool(config.get("is_test", False)),
    }


def execution_configuration_changed(reviewed, current):
    """Compare the reviewed settings that must remain fixed until execution."""
    return any(
        reviewed[key] != current.get(key)
        for key in ("java_path", "stop_command", "is_test")
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
                "test_direct",
                "auto_approved",
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
    "delete_path": "删除路径",
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


def _stage_line(text):
    cleaned = text.strip()
    for prefix in ("- ", "• ", "* "):
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix) :].strip()
            break
    return approval_excerpt(cleaned) if cleaned else ""


def plan_sections(plan):
    meta = []
    if directory := plan.get("expected_directory"):
        meta.append("目标实例目录：" + directory)
    if summary := (plan.get("summary") or "").strip():
        meta.append("方案说明：" + summary)
    continuation = plan.get("continuation")
    base_heading = (
        "测试副本执行步骤" if plan.get("environment") == "test" else "执行步骤"
    )
    step_lines = [
        f"{base_heading}（本批实际执行）：" if continuation else f"{base_heading}："
    ]
    labels = {"start": "启动服务端", "stop": "停止服务端", "restart": "重启服务端"}
    script_total = sum(1 for step in plan["steps"] if step["action"] == "script")
    script_index = 0
    scripts = []
    for step in plan["steps"]:
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
            script_index += 1
            backup_scope = "、".join(step["backup_paths"])
            detail = (
                f"执行修复脚本 {script_index}；备份范围：{backup_scope}"
                if script_total > 1
                else f"执行修复脚本；备份范围：{backup_scope}"
            )
            script_header = (
                f"脚本摘要 {script_index}（备份范围：{backup_scope}）："
                if script_total > 1
                else "脚本摘要："
            )
            scripts.append(f"{script_header}\n{approval_excerpt(step['script'])}")
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
                x1, y1, z1, x2, y2, z2 = step["bounds"]
                detail += (
                    f"；坐标范围 ({x1}, {y1}, {z1}) 至 ({x2}, {y2}, {z2})，"
                    f"匹配上限 {step['max_matches']}"
                )
            if kind in ("region_prune", "nbt_prune"):
                for key, title in (
                    ("entity_type", "实体类型"),
                    ("name", "方块"),
                    ("legacy_id", "旧方块ID"),
                ):
                    if key in step:
                        detail += f"；{title} {step[key]}"
                field = ".".join(map(str, step.get("relative_path", []))) or "匹配对象"
                if step["op"] == "delete":
                    detail += f"；删除 {field}"
                elif "state" in step:
                    state = step["state"]
                    if isinstance(state, str):
                        state = nbtlib.parse_nbt(state)
                    name = state.get("Name") if isinstance(state, dict) else None
                    if name == "minecraft:air":
                        detail += "；设为空气（minecraft:air）"
                    else:
                        detail += f"；设为 {name}" if name else "；设置方块状态"
                else:
                    detail += f"；设置 {field} 为 {step.get('value')}"
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
        step_lines.append(f"- {approval_excerpt(detail)}")
    if any(
        step["action"] == "command" and not step.get("backup_paths")
        for step in plan["steps"]
    ):
        step_lines.append(
            "在线命令无单独撤回（必要时可停服恢复本批备份）。"
            if any(step["action"] == "snapshot" for step in plan["steps"])
            else "在线命令无恢复备份。"
        )
    sections = []
    if meta:
        sections.append("\n".join(meta))
    sections.append("\n".join(step_lines))
    stages = [
        line
        for item in (continuation or {}).get("planned_stages") or ()
        if isinstance(item, str) and (line := _stage_line(item))
    ]
    if stages:
        sections.append(
            "\n".join(
                ["后续规划（按实测动态推进）：", *(f"- {stage}" for stage in stages)]
            )
        )
    primary = "\n\n".join(sections)
    extras = []
    if scripts:
        extras.append("\n\n".join(scripts))
    if continuation:
        extras.append(
            f"允许范围：{continuation['scope']}\n\n"
            f"完成条件：{continuation['completion']}"
        )
    return primary, extras


def plan_text(plan):
    primary, extras = plan_sections(plan)
    return "\n\n".join((primary, *extras))
