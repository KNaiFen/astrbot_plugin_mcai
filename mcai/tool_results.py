"""Model output boundary. Internal tracking and recovery keep raw B results."""

import re

_ESC = r"(?:\x1b|(?<!\\)\\u001[bB])"
_ST = r"(?:\x1b\\|(?<!\\)\\u001[bB]\\\\|\x9c)"
ANSI = re.compile(
    rf"(?:{_ESC}\]|\x9d)[^\x1b\x07\x9c]*?(?:\x07|(?<!\\)\\u0007|{_ST})"
    rf"|(?:{_ESC}[PX^_]|\x90|\x98|\x9e|\x9f)[^\x1b\x9c]*?{_ST}"
    rf"|(?:{_ESC}\[|\x9b)[0-?]*[ -/]*[@-~]"
    rf"|{_ESC}[ -/]*[0-~]",
)
JOB_STATIC_FIELDS = (
    "instance",
    "task_id",
    "kind",
    "command",
    "cwd",
    "created",
    "started_at",
    "pid",
    "target_pid",
    "process_created",
    "session_id",
    "executable",
)
JOB_METADATA_NOTE = "静态元数据同前次轮询，已省略。"


def plain_output(value):
    if isinstance(value, str):
        return ANSI.sub("", value)
    if isinstance(value, list):
        return [plain_output(item) for item in value]
    if isinstance(value, dict):
        return {key: plain_output(item) for key, item in value.items()}
    return value


def model_result(name, arguments, result, operation_id=None):
    data = plain_output(result)
    if isinstance(data, dict) and data.get("error_code"):
        error = {
            "code": data["error_code"],
            "message": data.get("reason", data.get("error", "")),
            "execution_state": data["execution_state"],
        }
        if "path" in data:
            error["path"] = data["path"]
        if "error_details" in data:
            error["details"] = data["error_details"]
        details = {}
        if operation_id:
            details["operation_id"] = operation_id
        if "operation_record" in data:
            details["operation"] = data["operation_record"]
        output = {"ok": False, "data": details, "error": error}
        if data.get("load_tool"):
            output["next_call"] = {
                "name": "mc_tools",
                "arguments": {"names": [data["load_tool"]]},
            }
        if (
            operation_id
            and name != "mc_operation_read"
            and error["execution_state"] != "not_executed"
        ):
            output["next_call"] = {
                "name": "mc_operation_read",
                "arguments": {"operation_id": operation_id},
            }
        return output

    output = {"ok": True, "data": data}
    if not isinstance(data, dict):
        return output
    if name == "mc_operation_read":
        data["operation_id"] = arguments["operation_id"]
    elif operation_id:
        data["operation_id"] = operation_id
    if "next_offset" in data:
        data["complete"] = data["next_offset"] is None
    elif "next_cursor" in data:
        data.setdefault("complete", data["next_cursor"] is None)
    next_name, next_args = name, dict(arguments)
    environment = (
        {"environment": "test"} if arguments.get("environment") == "test" else {}
    )
    if {"id", "status", "items"} <= data.keys():
        data["job_id"] = data.pop("id")
        probe = (
            data.get("progress", {}).get("kind")
            if data.get("kind") == "probe"
            else None
        )
        if name in ("mc_metrics", "mc_players"):
            probe = name[3:]
        if probe in ("metrics", "players"):
            limit = 8 if probe == "metrics" else 16
            if len(data["items"]) > limit:
                data["items"] = data["items"][:limit]
                cursor = data["items"][-1]["seq"]
                data.update(cursor=cursor, next_cursor=cursor, complete=False)
        for row in data["items"]:
            body = row["body"]
            if probe == "metrics":
                for key in ("worlds", "dimensions", "slow_tick_events", "state_events"):
                    if isinstance(items := body.get(key), list) and len(items) > 8:
                        body[key] = (
                            items[-8:]
                            if key in ("slow_tick_events", "state_events")
                            else items[:8]
                        )
                        body[f"{key}_total"] = len(items)
                        data["details"] = {
                            "job_id": data["job_id"],
                            "reference": "probe-result.json",
                        }
            if body.get("kind") == "memory_jfr" and "reference" in body:
                body["message"] = (
                    "上方是内存摘要；详细分析可用 mc_artifact_read 按字段读取。"
                )
            elif {"reference", "characters", "preview"} <= body.keys():
                body["message"] = (
                    "先看overview；mc_artifact_read默认结构概览，result_path定向展开，view=value或offset读取原文。"
                )
        if data["next_cursor"] is not None:
            next_name = (
                "mc_job_wait"
                if data["status"] in ("pending", "running")
                else "mc_job_read"
            )
            next_args = {"job_id": data["job_id"], "after": data["cursor"]}
        else:
            artifact = next(
                (
                    row["body"]
                    for row in data["items"]
                    if {"reference", "characters"} <= row["body"].keys()
                ),
                None,
            )
            if artifact is None:
                return output
            next_name = "mc_artifact_read"
            next_args = {"job_id": data["job_id"], "reference": artifact["reference"]}
    elif name == "mc_console_read":
        pending = [
            {
                "name": "mc_console_line",
                "arguments": {
                    "session_id": data["session_id"],
                    "seq": row["seq"],
                    "offset": row["next_offset"],
                    **environment,
                },
            }
            for row in data["items"]
            if row.get("next_offset") is not None
        ]
        data["events_complete"] = data["next_cursor"] is None
        if data["next_cursor"] is not None:
            pending.append(
                {
                    "name": "mc_console_read",
                    "arguments": {
                        **arguments,
                        "after": data["cursor"],
                        "session_id": data["session_id"],
                    },
                }
            )
        data["pending_reads"] = pending
        data["complete"] = not pending
        if pending:
            output["next_call"] = pending[0]
        return output
    elif name == "mc_console_send":
        data["status"] = "cancelled" if data["cancelled"] else "sent"
        if "session_id" not in data:
            return output
        next_name, next_args = (
            "mc_console_read",
            {"after": data["cursor"], "session_id": data["session_id"], **environment},
        )
    elif data.get("next_offset") is not None:
        next_args["offset"] = data["next_offset"]
        if name == "mc_web" and arguments["mode"] == "open":
            next_args = {
                "mode": "read",
                "reference": data["reference"],
                "offset": data["next_offset"],
            }
    elif data.get("next_cursor") is not None:
        next_args["after"] = data["next_cursor"]
    else:
        return output
    output["next_call"] = {"name": next_name, "arguments": next_args}
    return output
