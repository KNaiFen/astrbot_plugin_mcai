"""Shared model vocabulary; B keeps its transport and persisted operation fields."""

import re

from jsonschema import ValidationError


def argument_error(error):
    """Resolve discriminated branches before ranking errors at deeper paths."""
    if not error.context:
        return error
    choices = error.schema.get("oneOf", [])
    for key, field in error.schema.get("properties", {}).items():
        if (
            "enum" in field
            and choices
            and all(
                key in choice.get("required", [])
                and len(choice.get("properties", {}).get(key, {}).get("enum", [])) == 1
                for choice in choices
            )
            and isinstance(error.instance, dict)
            and error.instance.get(key) not in field["enum"]
        ):
            return ValidationError(
                f"{key}须为以下允许值之一：{', '.join(map(str, field['enum']))}",
                path=[*error.absolute_path, key],
                schema=error.schema,
            )
    matching = {
        index
        for index, choice in enumerate(choices)
        if isinstance(error.instance, dict)
        and all(
            error.instance.get(key) == field["enum"][0]
            for key, field in choice.get("properties", {}).items()
            if len(field.get("enum", [])) == 1
        )
    }
    candidates = [
        item for item in error.context if item.schema_path[0] in matching
    ] or error.context
    return min(
        (argument_error(item) for item in candidates),
        key=lambda item: (item.validator == "enum", -len(item.absolute_path)),
    )


COMMON = {
    "timeout": "timeout_seconds",
    "interval": "interval_seconds",
    "seconds": "duration_seconds",
}
FIELDS = {
    "mc_inventory": {"baseline": "baseline_job_id"},
    "mc_files": {"pattern": "glob", "before": "before_lines", "after": "after_lines"},
    "mc_logs": {"pattern": "glob", "before": "before_lines", "after": "after_lines"},
    "mc_search": {"pattern": "query", "line": "start_line"},
    "mc_console_read": {"after": "cursor"},
    "mc_job_read": {"after": "cursor"},
    "mc_job_wait": {"after": "cursor"},
    "mc_context_history": {"after": "cursor"},
    "mc_region_scan": {"world": "world_path"},
    "mc_objects": {"type": "object_type"},
    "mc_profile": {"type": "object_type"},
}
CHECK = {"pattern": "query", "forbid": "forbid_query", "after": "cursor", **COMMON}


def field_names(tool, context=()):
    if context and context[-1] in ("check", "standalone_check", "checks"):
        return CHECK
    return {**COMMON, **(FIELDS.get(tool, {}) if not context else {})}


def arguments_for(tool, arguments, *, internal=False, context=()):
    """Translate declared argument keys only; never alter user text or NBT keys."""
    names = dict(field_names(tool, context))
    if (tool == "mc_search" and arguments.get("mode") != "find") or (
        context and context[-1] == "checks" and arguments.get("kind") != "ready"
    ):
        names.pop("pattern", None)
    if internal:
        names = {new: old for old, new in names.items()}
    result = {}
    for key, value in arguments.items():
        target = names.get(key, key)
        if key in ("steps", "checks"):
            value = [
                arguments_for(tool, item, internal=internal, context=(*context, key))
                for item in value
            ]
        result[target] = value
    return result


def model_schema(schema, tool, context=()):
    if isinstance(schema, list):
        return [model_schema(item, tool, context) for item in schema]
    if not isinstance(schema, dict):
        return schema
    names = field_names(tool, context)
    result = {}
    for key, value in schema.items():
        if key == "$defs":
            result[key] = {
                name: model_schema(item, tool, (name,)) for name, item in value.items()
            }
        elif key == "properties":
            result[key] = {
                names.get(name, name): model_schema(item, tool, (*context, name))
                for name, item in value.items()
            }
        elif key == "required":
            result[key] = [names.get(name, name) for name in value]
        elif key == "description":
            result[key] = describe_arguments(value, names)
        else:
            result[key] = model_schema(value, tool, context)
    return result


def describe_arguments(text, names):
    for old, new in names.items():
        text = re.sub(r"(?<![A-Za-z_])" + old + r"(?![A-Za-z_])", new, text)
    return text


def model_continuations(output):
    if "next_call" in output:
        call = output["next_call"]
        call["arguments"] = arguments_for(call["name"], call["arguments"])
    data = output.get("data")
    if isinstance(data, dict):
        for call in data.get("pending_reads", []):
            call["arguments"] = arguments_for(call["name"], call["arguments"])
    return output
