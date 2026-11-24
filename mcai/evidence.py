"""Deterministic, bounded reading views over retained original evidence."""

import hashlib
import json

import nbtlib

from .tool_help import resolved_query
from .tool_results import JOB_STATIC_FIELDS

PRIMARY_VIEW_KEYS = frozenset(
    {
        "error",
        "reason",
        "result",
        "data",
        "items",
        "body",
        "content",
        "text",
        "output",
        "event",
        "groups",
        "matches",
        "lines",
        "messages",
        "diff",
        "snbt",
    }
)
SECONDARY_VIEW_KEYS = frozenset(
    {
        "status",
        "ok",
        "exit_code",
        "message",
        "count",
        "total",
        "partial",
        "truncated",
        "omitted_fulltext",
        "summary",
        "path",
    }
)
ARCHIVE_JOB_NOISE_KEYS = frozenset(
    {
        *JOB_STATIC_FIELDS,
        "id",
        "task_id",
        "next_call",
        "progress",
        "completed",
        "complete",
        "cursor",
        "next_cursor",
        "ended",
        "metadata_omitted",
        "note",
    }
)


def view_key_rank(key):
    """Order substantive payload keys ahead of metadata and arbitrary fields."""
    if key in PRIMARY_VIEW_KEYS:
        return 0
    if key in SECONDARY_VIEW_KEYS:
        return 1
    return 2


NBT_PAGE_BYTES = 120_000
NBT_SNBT_BYTES = 12_000
NBT_NOTE = "当前节点 SNBT 体积过大，已改按结构摘要与截断预览返回，请改用 view='children' 分层展开具体路径。"
NBT_CONTAINERS = (nbtlib.Compound, nbtlib.List, nbtlib.Array)


def json_size(value):
    return len(json.dumps(value, ensure_ascii=False).encode("utf-8"))


def nbt_page(entries, offset, count, *, byte_limit=NBT_PAGE_BYTES, **fields):
    items = []
    page = {"total": count, **fields, "items": items, "next_offset": None}
    remaining = byte_limit - json_size(page) - len(str(count))
    for item in entries:
        size = json_size(item) + (2 if items else 0)
        if size > remaining:
            if not items and byte_limit == NBT_PAGE_BYTES:
                raise ValueError("单条 NBT 结果超过分页上限，请缩小到更具体的路径")
            break
        items.append(item)
        remaining -= size
    end = offset + len(items)
    page["next_offset"] = end if end < count else None
    return page


def snbt_fields(tag, *, snbt=None, children=True):
    if snbt is None:
        snbt = tag.snbt()
    size = len(snbt.encode("utf-8"))
    if size <= NBT_SNBT_BYTES and json_size(snbt) - 2 <= NBT_SNBT_BYTES:
        return {"snbt": snbt}
    result = {"snbt_bytes": size, "truncated": True, "preview": snbt[:256]}
    if children:
        result["children"] = describe_tag(tag, "children", limit=20, byte_limit=16_000)
    return {**result, "next_view": "children", "note": NBT_NOTE}


def describe_tag(
    tag, view="value", offset=0, limit=100, *, byte_limit=NBT_PAGE_BYTES, **fields
):
    if view == "value":
        result = {**snbt_fields(tag), **fields}
        if json_size(result) > byte_limit:
            raise ValueError("NBT 结果超过分页上限，请缩小到更具体的路径")
        return result
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
    return nbt_page(
        (
            {
                "key": key,
                "type": nbtlib.Base.get_tag(value.tag_id).__name__,
                **(
                    {"length": len(value)}
                    if isinstance(value, NBT_CONTAINERS)
                    else snbt_fields(value, children=False)
                ),
            }
            for key, value in entries
        ),
        offset,
        total,
        byte_limit=byte_limit,
        **fields,
    )


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


def evidence_view(value, limit=6000, *, edges=0):
    original = json.dumps(value, ensure_ascii=False)
    if len(original) <= limit:
        return value

    def index(item, budget, path=()):
        encoded = json.dumps(item, ensure_ascii=False)
        if len(encoded) <= budget:
            return item
        if isinstance(item, dict):
            pairs = sorted(
                enumerate(item.items()),
                key=lambda row: (view_key_rank(row[1][0]), row[0]),
            )
            pairs = [pair for _, pair in pairs]
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

    envelope = {
        "view": "summary",
        "characters": len(original),
        "sha256": hashlib.sha256(original.encode()).hexdigest(),
        "content": None,
        "complete": False,
        "message": "有界结构视图；缺省项不能当作不存在。按result_path或原工具的目标筛选读取必要原值，勿连续分页搬运全文。",
        **({"head": original[:edges], "tail": original[-edges:]} if edges else {}),
    }
    overhead = len(json.dumps(envelope, ensure_ascii=False)) - 4
    inner_limit = max(256, limit - overhead)
    target = min(max(256, limit // 2), inner_limit) if limit >= 1200 else inner_limit
    content = index(value, target)
    if len(json.dumps(content, ensure_ascii=False)) > inner_limit:
        content = {
            "type": type(value).__name__,
            "message": "结构索引仍过大；按原工具筛选、find或result_path收窄。",
        }
    envelope["content"] = content
    return envelope


def _compact_archive_item(item):
    if (
        isinstance(item, dict)
        and "body" in item
        and set(item)
        <= {
            "seq",
            "kind",
            "ts",
            "stream",
            "body",
        }
    ):
        body = _compact_archive_value(item["body"])
        if isinstance(body, dict):
            return {"seq": item["seq"], **body} if "seq" in item else body
        return body
    return _compact_archive_value(item)


def _coalesce_archive_items(items):
    """Merge contiguous 2 KiB stdout chunks before bounded head/tail clipping."""
    merged = []
    chunks = []
    for raw in items:
        item = _compact_archive_item(raw)
        if (
            isinstance(item, dict)
            and isinstance(item.get("output"), str)
            and set(item) <= {"seq", "output"}
        ):
            chunks.append(item["output"])
            continue
        if chunks:
            merged.append({"output": "".join(chunks)})
            chunks.clear()
        merged.append(item)
    if chunks:
        merged.append({"output": "".join(chunks)})
    return merged


def _compact_archive_value(value):
    if isinstance(value, dict):
        if value.get("view") == "summary" and "content" in value and "sha256" in value:
            return _compact_archive_value(value["content"])
        is_job = any(
            key in value for key in ("job_id", "task_id", "items", "next_call")
        )
        pairs = (
            [(k, v) for k, v in value.items() if k not in ARCHIVE_JOB_NOISE_KEYS]
            if is_job
            else list(value.items())
        )
        if not pairs:
            pairs = list(value.items())
        return {
            key: (
                _coalesce_archive_items(child)
                if key == "items" and isinstance(child, list)
                else _compact_archive_value(child)
            )
            for key, child in pairs
        }
    if isinstance(value, list):
        return [_compact_archive_value(item) for item in value]
    return value


def _clip_archive_text(text, budget):
    if len(json.dumps(text, ensure_ascii=False)) <= budget:
        return text
    if budget < 16:
        return ""
    raw_limit = max(4, budget - 2)
    while raw_limit > 0:
        probe = min((raw_limit - 18) // 2, (len(text) - 1) // 2)
        if raw_limit >= 48 and probe >= 12 and len(text) > probe * 2 + 12:
            omitted = len(text) - probe * 2
            candidate = f"{text[:probe]}\n…[省略{omitted}字符]…\n{text[-probe:]}"
        else:
            candidate = text[: max(1, raw_limit - 1)] + "…"
        c_len = len(json.dumps(candidate, ensure_ascii=False))
        if c_len <= budget:
            return candidate
        raw_limit = min(raw_limit - 1, int(raw_limit * budget / max(1, c_len)) - 1)
    return ""


def archive_evidence_view(value, budget=1200):
    """Build a compact, payload-prioritized evidence slice for archive summarization."""

    def shrink(item, limit, path=()):
        if len(json.dumps(item, ensure_ascii=False)) <= limit:
            return item
        if isinstance(item, dict):
            if limit < 24:
                return {"omitted_keys": len(item)} if limit >= 18 else {}
            ranked = sorted(
                enumerate(item.items()),
                key=lambda row: (
                    view_key_rank(row[1][0]),
                    len(json.dumps(row[1][1], ensure_ascii=False)) > 160,
                    row[0],
                ),
            )
            pairs = [pair for _, pair in ranked]
            built = {}
            remaining = limit - 2
            omitted = 0
            for index, (key, child) in enumerate(pairs):
                key_encoded = json.dumps(str(key), ensure_ascii=False)
                entry_prefix = len(key_encoded) + (2 if not built else 3)
                left = len(pairs) - index - 1
                reserve = min(remaining // 3, left * 48) if left else 0
                child_budget = remaining - entry_prefix - reserve
                if child_budget < 20 and remaining - entry_prefix >= 20 and not built:
                    child_budget = remaining - entry_prefix
                if child_budget < 12:
                    if remaining - entry_prefix >= 6:
                        child_budget = remaining - entry_prefix
                    else:
                        omitted += len(pairs) - index
                        break
                projected = shrink(child, child_budget, (*path, key))
                cost = entry_prefix + len(json.dumps(projected, ensure_ascii=False))
                if cost > remaining:
                    tight = shrink(
                        child, max(12, remaining - entry_prefix), (*path, key)
                    )
                    tight_cost = entry_prefix + len(
                        json.dumps(tight, ensure_ascii=False)
                    )
                    if tight_cost <= remaining:
                        projected, cost = tight, tight_cost
                    else:
                        omitted += len(pairs) - index
                        break
                built[key] = projected
                remaining -= cost
            if (
                omitted
                and "_omitted" not in built
                and len(json.dumps({**built, "_omitted": omitted}, ensure_ascii=False))
                <= limit
            ):
                built["_omitted"] = omitted
            return built
        if isinstance(item, list):
            if not item or limit < 16:
                return []
            slots = min(len(item), max(1, (limit - 4) // 220))
            indices = list(range(slots))
            if 1 < len(indices) < len(item):
                indices[-1] = len(item) - 1
            built = []
            remaining = limit - 2
            for pos, idx in enumerate(indices):
                sep = 0 if not built else 2
                left = len(indices) - pos - 1
                child_budget = max(16, (remaining - sep) // (left + 1))
                projected = shrink(item[idx], child_budget, (*path, idx))
                cost = sep + len(json.dumps(projected, ensure_ascii=False))
                if cost > remaining:
                    projected = shrink(
                        item[idx], max(12, remaining - sep), (*path, idx)
                    )
                    cost = sep + len(json.dumps(projected, ensure_ascii=False))
                if cost > remaining:
                    break
                built.append(projected)
                remaining -= cost
            return built
        if isinstance(item, str):
            if (
                path
                and path[-1] in ("content", "text")
                and item.lstrip().startswith(("{", "["))
            ):
                try:
                    decoded = json.loads(item)
                except json.JSONDecodeError:
                    pass
                else:
                    if isinstance(decoded, (dict, list)):
                        return shrink(_compact_archive_value(decoded), limit, path)
            return _clip_archive_text(item, limit)
        raw_scalar = str(item)
        return raw_scalar[: max(0, limit - 2)] if limit > 2 else ""

    return shrink(_compact_archive_value(value), max(32, budget))


def review_evidence(sources, limit=4000, *, edges=0):
    """Deduplicate evidence and keep bounded excerpts of narrowed text."""

    def project(value, budget):
        original = json.dumps(value, ensure_ascii=False)
        if len(original) <= budget:
            return value
        text, path, metadata = value, [], None
        if isinstance(value, dict) and value.get("view") != "summary":
            for key in ("text", "value", "content"):
                if isinstance(value.get(key), str):
                    rest = {name: item for name, item in value.items() if name != key}
                    # Keep the structural view for results with substantial
                    # information outside the text field.
                    if len(json.dumps(rest, ensure_ascii=False)) <= min(
                        512, budget // 4
                    ):
                        text, path, metadata = value[key], [key], rest
                        break
        if not isinstance(text, str) or len(text) < 3:
            return evidence_view(value, budget, edges=edges)

        excerpt = {
            "view": "summary",
            "complete": False,
            "truncated": True,
            "characters": len(original),
            "sha256": hashlib.sha256(original.encode()).hexdigest(),
            "result_path": path,
            "content": metadata,
        }
        # Use the existing allowance, including JSON escapes and metadata. A
        # larger explicit text selection cannot grow the review request budget.
        low, high, best = 2, min(len(text) - 1, budget), None
        while low <= high:
            count = (low + high) // 2
            candidate = {
                **excerpt,
                "omitted_chars": len(text) - count,
                "head": text[: (count + 1) // 2],
                "tail": text[-(count // 2) :],
            }
            if len(json.dumps(candidate, ensure_ascii=False)) <= budget:
                best = candidate
                low = count + 1
            else:
                high = count - 1
        return best if best is not None else evidence_view(value, budget, edges=edges)

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
        row = {**source, "result": project(raw, limit)}
        if target in seen:
            row["result"] = {"same_as": seen[target]}
        elif (
            isinstance(raw, dict)
            and "text" in raw
            and source["tool"]
            in ("mc_artifact_read", "mc_context_history", "mc_console_line")
        ):
            scope = read_scope(source)
            start = source["arguments"].get("offset", 0)
            end = start + len(raw["text"])
            previous = ranges.setdefault(scope, [])
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
                projection = {
                    **{key: value for key, value in raw.items() if key != "text"},
                    "source_range": [start, end],
                    "covered_by": covered,
                    "segments": [
                        {"offset": a, "end": b, "value": None} for a, b in segments
                    ],
                }
                remaining = limit - len(json.dumps(projection, ensure_ascii=False))
                for index, (a, b) in enumerate(segments):
                    if remaining < 0:
                        break
                    value = project(
                        raw["text"][a - start : b - start],
                        remaining // (len(segments) - index) + len("null"),
                    )
                    projection["segments"][index]["value"] = value
                    remaining -= len(json.dumps(value, ensure_ascii=False)) - len(
                        "null"
                    )
                if remaining >= 0:
                    row["result"] = projection
            previous.append((start, end, source["evidence_id"], raw["text"]))
        seen[target] = source["evidence_id"]
        result.append(row)
    return result
