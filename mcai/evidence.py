"""Deterministic, bounded reading views over retained original evidence."""

import hashlib
import json

import nbtlib

from .tool_help import resolved_query


def describe_tag(tag, view="value", offset=0, limit=100):
    if view == "value":
        return {"snbt": tag.snbt()}
    if isinstance(tag, nbtlib.Compound):
        keys = sorted(tag)
        total = len(keys)
        entries = ((key, tag[key]) for key in keys[offset : offset + min(limit, 100)])
    elif isinstance(tag, (nbtlib.List, nbtlib.Array)):
        total = len(tag)
        entries = (
            (i, tag[i]) for i in range(offset, min(total, offset + min(limit, 100)))
        )
    else:
        total = 1
        entries = [("value", tag)] if offset == 0 else []
    items = []
    for key, value in entries:
        item = {"key": key, "type": nbtlib.Base.get_tag(value.tag_id).__name__}
        if isinstance(value, (nbtlib.Compound, nbtlib.List, nbtlib.Array)):
            item["length"] = len(value)
        else:
            item["snbt"] = value.snbt()
        items.append(item)
    return {
        "items": items,
        "total": total,
        "next_offset": offset + len(items) if offset + len(items) < total else None,
    }


def result_at(value, path):
    for depth, key in enumerate(path):
        if isinstance(value, str):
            value = json.loads(value)
        location = json.dumps(path[: depth + 1], ensure_ascii=False)
        if isinstance(value, dict) and key not in value:
            raise ValueError(
                f"result_path={location} 缺少字段；该层可用键："
                + json.dumps(list(value)[:20], ensure_ascii=False)
            )
        if isinstance(value, list) and (
            not isinstance(key, int) or not 0 <= key < len(value)
        ):
            raise ValueError(
                f"result_path={location} 需要有效数组下标；该层长度：{len(value)}"
            )
        if not isinstance(value, (dict, list)):
            raise ValueError(
                f"result_path={location} 无法继续读取{type(value).__name__}"
            )
        value = value[key]
    return value


def tool_evidence(source):
    tool, arguments = resolved_query(source)
    return {
        "evidence_id": source["id"],
        "tool": tool,
        "arguments": {
            name: value
            for name, value in arguments.items()
            if name not in ("script_files", "script_encoding", "evidence_ids")
        },
        "instance": source.get("instance"),
        "directory": source.get("directory"),
        "result": source["result"],
    }


def read_scope(source):
    return (
        source.get("instance"),
        source.get("directory"),
        source["tool"],
        json.dumps(
            {
                key: value
                for key, value in source["arguments"].items()
                if key not in ("offset", "view")
            },
            sort_keys=True,
        ),
    )


def evidence_view(value, limit=6000):
    original = json.dumps(value, ensure_ascii=False)
    if len(original) <= limit:
        return value

    def index(item, budget, path=()):
        encoded = json.dumps(item, ensure_ascii=False)
        if len(encoded) <= budget:
            return item
        if isinstance(item, dict):
            pairs = list(item.items())
            pairs.sort(
                key=lambda pair: (
                    pair[0]
                    not in (
                        "result",
                        "data",
                        "messages",
                        "items",
                        "body",
                        "content",
                        "event",
                        "text",
                        "status",
                        "error",
                        "count",
                    )
                )
            )
        elif isinstance(item, list):
            pairs = list(enumerate(item))
        else:
            if (
                isinstance(item, str)
                and path
                and path[-1] in ("content", "text")
                and item.lstrip().startswith(("{", "["))
            ):
                try:
                    decoded = json.loads(item)
                except json.JSONDecodeError:
                    pass
                else:
                    if isinstance(decoded, (dict, list)):
                        return index(decoded, budget, path)
            if path and path[-1] == "snbt" and isinstance(item, str):
                try:
                    tag = nbtlib.parse_nbt(item)
                except nbtlib.InvalidLiteral as error:
                    return {
                        "result_path": list(path),
                        "characters": len(item),
                        "parse_error": str(error),
                    }
                return index(describe_tag(tag, "children", limit=20), budget, path)
            return {
                "result_path": list(path),
                "type": type(item).__name__,
                "characters": len(encoded),
                "preview": str(item)[: max(0, min(160, budget - 160))],
                "omitted": True,
            }
        if budget < 240:
            return {
                "result_path": list(path),
                "type": type(item).__name__,
                "length": len(pairs),
                "omitted": True,
            }
        count = min(len(pairs), max(1, budget // 240))
        chosen = pairs[:count]
        if isinstance(item, list) and 1 < count < len(pairs):
            chosen[-1] = pairs[-1]
        entries = []
        remaining = budget - 160
        for position, (key, child) in enumerate(chosen):
            allowance = max(
                64,
                remaining - 100 * (count - position - 1)
                if isinstance(item, dict)
                else (budget - 160) // max(1, count),
            )
            entry = {"key": key, "value": index(child, allowance, (*path, key))}
            entries.append(entry)
            remaining -= len(json.dumps(entry, ensure_ascii=False))
        return {
            "result_path": list(path),
            "type": type(item).__name__,
            "length": len(pairs),
            "items": entries,
            "omitted_items": len(pairs) - count,
        }

    content = index(value, max(256, limit // 2))
    if len(json.dumps(content, ensure_ascii=False)) > max(256, limit - 500):
        content = {
            "type": type(value).__name__,
            "message": "结构索引仍过大；按原工具筛选、find或result_path收窄。",
        }
    return {
        "view": "summary",
        "characters": len(original),
        "sha256": hashlib.sha256(original.encode()).hexdigest(),
        "content": content,
        "complete": False,
        "message": "有界结构视图；缺省项不能当作不存在。按result_path或原工具的目标筛选读取必要原值，勿连续分页搬运全文。",
    }


def review_evidence(sources, limit=4000):
    """Deduplicate exact evidence and text ranges with matching contents."""
    seen, ranges, result = {}, {}, []
    for source in sources:
        raw = source["result"]
        identity = hashlib.sha256(
            json.dumps(raw, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()
        target = (
            source.get("instance"),
            source.get("directory"),
            source["tool"],
            identity,
        )
        row = {**source, "result": evidence_view(raw, limit)}
        if target in seen:
            row["result"] = {"same_as": seen[target]}
        elif (
            isinstance(raw, dict)
            and "text" in raw
            and source["tool"]
            in ("mc_artifact_read", "mc_context_history", "mc_console_line")
        ):
            target = read_scope(source)
            start = source["arguments"].get("offset", 0)
            end = start + len(raw["text"])
            previous = ranges.setdefault(target, [])
            segments = [(start, end)]
            covered = []
            for left, right, key, text in previous:
                low, high = max(start, left), min(end, right)
                if (
                    low >= high
                    or raw["text"][low - start : high - start]
                    != text[low - left : high - left]
                ):
                    continue
                covered.append(key)
                segments = [
                    (a, b)
                    for low, high in segments
                    for a, b in ((low, min(high, left)), (max(low, right), high))
                    if a < b
                ]
            if covered:
                row["result"] = {
                    **{key: value for key, value in raw.items() if key != "text"},
                    "source_range": [start, end],
                    "covered_by": covered,
                    "segments": [
                        {
                            "offset": a,
                            "end": b,
                            "value": evidence_view(
                                raw["text"][a - start : b - start], limit
                            ),
                        }
                        for a, b in segments
                    ],
                }
            previous.append((start, end, source["evidence_id"], raw["text"]))
        seen[target] = source["evidence_id"]
        result.append(row)
    return result
