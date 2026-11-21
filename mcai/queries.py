import datetime as dt
import gzip
import hashlib
import io
import json
import os
import re
from collections import deque
from pathlib import Path

from .paths import resolve_file
from .text_files import BOMS, patch_text

LOG_HEADER = re.compile(
    r"^(?P<bracket>\[)?(?:(?P<iso>\d{4}-\d\d-\d\d)[ T]|"
    r"(?P<day>\d{2})(?P<month>1[0-2]|0?[1-9])月(?P<year>\d{4}) )?"
    r"(?P<time>\d\d:\d\d:\d\d(?:[.,]\d+)?)"
    r"(?(bracket)(?=\])|(?=\s|$))"
)


class _LogSnapshot(io.RawIOBase):
    def __init__(self, stream, size):
        self.stream, self.remaining = stream, size

    def readable(self):
        return True

    def readinto(self, buffer):
        data = self.stream.read(min(len(buffer), self.remaining))
        buffer[: len(data)] = data
        self.remaining -= len(data)
        return len(data)


def shared_binary(path):
    if os.name != "nt":
        return path.open("rb")
    import ctypes
    import msvcrt
    from ctypes import wintypes

    create = ctypes.WinDLL("kernel32", use_last_error=True).CreateFileW
    create.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    create.restype = wintypes.HANDLE
    handle = create(str(path), 0x80000000, 7, None, 3, 0x08000000, None)
    if handle == wintypes.HANDLE(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    return os.fdopen(msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY), "rb")


def find_files(directory, pattern, excluded=None):
    root = Path(directory).resolve()
    if Path(pattern).is_absolute() or ".." in Path(pattern).parts:
        raise ValueError("glob 必须位于实例目录内")
    for path in root.glob(pattern):
        if not path.is_file():
            continue
        actual = resolve_file(root, path.relative_to(root))
        if excluded and actual.is_relative_to(Path(excluded).resolve()):
            continue
        yield actual


def file_rows(directory, args):
    mode = args["mode"]
    if mode == "find":
        for path in find_files(directory, args.get("pattern", "**/*")):
            yield {
                "path": path.relative_to(directory).as_posix(),
                "size": path.stat().st_size,
                "modified_ns": path.stat().st_mtime_ns,
            }
    elif mode == "stat":
        path = resolve_file(directory, args["path"])
        before = path.stat()
        with shared_binary(path) as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        if (before.st_size, before.st_mtime_ns) != (
            path.stat().st_size,
            path.stat().st_mtime_ns,
        ):
            raise ValueError("读取期间文件变化，请重新查询")
        with shared_binary(path) as stream:
            prefix = stream.read(4)
        yield {
            "path": args["path"],
            "size": before.st_size,
            "modified_ns": before.st_mtime_ns,
            "sha256": digest,
            "bom": next(
                (codec for marker, codec in BOMS if prefix.startswith(marker)), None
            ),
        }
    elif mode == "preview_patch":
        _, preview = patch_text(resolve_file(directory, args["path"]), args)
        yield preview
    elif mode == "search":
        counts = {}
        for row in log_rows(
            directory, {**args, "pattern": args.get("pattern", "**/*")}, lambda: False
        ):
            if "error" in row:
                yield row
            elif args.get("result", "lines") == "lines":
                yield row
            elif row.get("matched"):
                counts[row["path"]] = counts.get(row["path"], 0) + 1
        for name, count in counts.items():
            yield {
                "path": name,
                **({"count": count} if args["result"] == "count" else {}),
            }
    elif mode in ("read", "tail"):
        path = resolve_file(directory, args["path"])
        with io.TextIOWrapper(
            shared_binary(path), encoding=args.get("encoding", "utf-8")
        ) as stream:
            lines = enumerate(stream, 1)
            if mode == "tail":
                lines = deque(lines, maxlen=args.get("line_count", 100))
            for number, line in lines:
                if number < args.get("start_line", 1):
                    continue
                if mode == "read" and number >= args.get("start_line", 1) + args.get(
                    "line_count", 100
                ):
                    break
                yield {
                    "path": args["path"],
                    "line": number,
                    "text": line.rstrip("\r\n"),
                }
    else:
        raise ValueError("未知文件查询模式")


def log_rows(directory, args, cancelled):
    expression = re.compile(
        args["query"] if args.get("regex") else re.escape(args["query"]),
        0 if args.get("case_sensitive") else re.I,
    )
    start = (
        dt.datetime.fromisoformat(args["start_time"])
        if args.get("start_time")
        else None
    )
    end = dt.datetime.fromisoformat(args["end_time"]) if args.get("end_time") else None
    if start and start.tzinfo:
        start = start.astimezone().replace(tzinfo=None)
    if end and end.tzinfo:
        end = end.astimezone().replace(tzinfo=None)
    before, after = args.get("before", 3), args.get("after", 8)
    for path in find_files(directory, args.get("pattern", "logs/**/*.log*")):
        if cancelled():
            return
        stat = path.stat()
        dated = re.search(r"\d{4}-\d\d-\d\d", path.name)
        date = dated.group() if dated else None
        active_time = None
        history = deque(maxlen=before)
        remaining, emitted = 0, 0
        unknown_reported = False
        try:
            with (
                shared_binary(path) as raw,
                io.BufferedReader(_LogSnapshot(raw, stat.st_size)) as snapshot,
                io.TextIOWrapper(
                    gzip.GzipFile(fileobj=snapshot)
                    if path.suffix == ".gz"
                    else snapshot,
                    encoding=args.get("encoding", "utf-8"),
                ) as stream,
            ):
                number = 0
                while line := stream.readline():
                    number += 1
                    if cancelled():
                        return
                    match = LOG_HEADER.match(line)
                    if match:
                        line_date = match["iso"] or (
                            f"{match['year']}-{int(match['month']):02d}-{match['day']}"
                            if match["year"]
                            else date
                        )
                        active_time = None
                        if line_date:
                            try:
                                active_time = dt.datetime.fromisoformat(
                                    f"{line_date}T{match['time'].replace(',', '.')}"
                                )
                            except ValueError:
                                # A malformed log header starts an event with unknown time.
                                pass
                    inside = (not start and not end) or (
                        active_time is not None
                        and (start is None or active_time >= start)
                        and (end is None or active_time <= end)
                    )
                    matched = inside and bool(expression.search(line))
                    if (
                        (start or end)
                        and active_time is None
                        and not unknown_reported
                        and expression.search(line)
                    ):
                        yield {
                            "path": path.relative_to(directory).as_posix(),
                            "time_unknown": True,
                            "message": "发现匹配文本，但日志日期未知，无法确定是否位于请求的时间范围",
                        }
                        unknown_reported = True
                    row = {
                        "path": path.relative_to(directory).as_posix(),
                        "line": number,
                        "time": active_time.isoformat() if active_time else None,
                        "text": line.rstrip("\r\n"),
                        "matched": matched,
                    }
                    if matched:
                        for previous in history:
                            if previous["line"] > emitted:
                                yield previous
                                emitted = previous["line"]
                        remaining = after + 1
                    if remaining:
                        if number > emitted:
                            yield row
                            emitted = number
                        remaining -= 1
                    history.append(row)
            current = path.stat()
            if (current.st_size, current.st_mtime_ns, current.st_ino) != (
                stat.st_size,
                stat.st_mtime_ns,
                stat.st_ino,
            ):
                yield {
                    "path": path.relative_to(directory).as_posix(),
                    "source_changed": True,
                    "message": "查询期间源日志发生追加或轮转，结果只代表本次读取",
                }
        except (OSError, UnicodeError, EOFError) as exc:
            yield {
                "path": path.relative_to(directory).as_posix(),
                "error": f"{type(exc).__name__}: {exc}",
            }


def log_groups(directory, args, cancelled, artifact):
    """Group complete multiline events; only occurrence timestamps are normalized."""
    expression = re.compile(
        args["query"] if args.get("regex") else re.escape(args["query"]),
        0 if args.get("case_sensitive") else re.I,
    )
    groups, issues, event = {}, [], []
    scanned = 0

    def finish():
        if not event:
            return
        text = "\n".join(row["text"] for row in event)
        if not expression.search(text):
            return
        signature = LOG_HEADER.sub("<time>", text, count=1)
        key = hashlib.sha256((event[0]["path"] + "\n" + signature).encode()).hexdigest()
        first, last = event[0], event[-1]
        if key in groups:
            groups[key]["count"] += 1
            groups[key]["last"] = {"line": last["line"], "time": last["time"]}
            groups[key]["ranges"].append([first["line"], last["line"], first["time"]])
        else:
            groups[key] = {
                "group_id": key,
                "path": first["path"],
                "count": 1,
                "first": {"line": first["line"], "time": first["time"]},
                "last": {"line": last["line"], "time": last["time"]},
                "ranges": [[first["line"], last["line"], first["time"]]],
                "event": event.copy(),
            }

    for row in log_rows(
        directory,
        {**args, "query": "", "regex": False, "before": 0, "after": 0},
        cancelled,
    ):
        if "text" not in row:
            issues.append(row)
            continue
        scanned += 1
        row["matched"] = bool(expression.search(row["text"]))
        if event and (
            row["path"] != event[-1]["path"]
            or row["line"] != event[-1]["line"] + 1
            or LOG_HEADER.match(row["text"])
        ):
            finish()
            event = []
        event.append(row)
    finish()
    rows = list(groups.values())
    artifact.write_text(
        json.dumps({"groups": rows, "issues": issues}, ensure_ascii=False),
        encoding="utf-8",
    )
    common = sorted(range(len(rows)), key=lambda i: -rows[i]["count"])[:24]
    rare = sorted(range(len(rows)), key=lambda i: rows[i]["count"])[:16]
    selected = list(dict.fromkeys([*common, *rare]))
    yield {
        "view": "events",
        "scanned_lines": scanned,
        "matching_events": sum(row["count"] for row in rows),
        "unique_groups": len(rows),
        "omitted_groups": len(rows) - len(selected),
        "issues": issues,
        "reference": artifact.name,
        "message": "按完整日志事件归组，保留UUID、坐标、路径及代表原文。未展示组在reference中按result_path定向读取；原始时间范围与查询条件仍适用。",
    }
    for i in selected:
        yield {
            **{key: value for key, value in rows[i].items() if key != "ranges"},
            "reference": artifact.name,
            "result_path": ["groups", i],
        }


def discover_worlds(directory, excluded=None):
    directory = Path(directory).resolve()
    found = {}
    excluded = Path(excluded).resolve() if excluded else None
    for parent, folders, _ in os.walk(directory):
        base = Path(parent)
        folders[:] = [
            name
            for name in folders
            if name not in (".git", ".mcai-probe")
            and name not in ("backups", "backup", "logs", "libraries", "mods")
            and (
                excluded is None or not (base / name).resolve().is_relative_to(excluded)
            )
        ]
        for dataset in ("region", "entities", "poi"):
            if dataset not in folders:
                continue
            folders.remove(dataset)
            if not any(
                path.is_file() and re.fullmatch(r"r\.-?\d+\.-?\d+\.mc[ar]", path.name)
                for path in (base / dataset).iterdir()
            ):
                continue
            folder = base
            relative = folder.relative_to(directory).as_posix()
            if relative not in found:
                world = folder
                while world != directory and not (world / "level.dat").exists():
                    world = world.parent
                found[relative] = {
                    "world": world.relative_to(directory).as_posix(),
                    "dimension": folder.relative_to(world).as_posix(),
                    "path": relative,
                    "datasets": [],
                }
            if dataset not in found[relative]["datasets"]:
                found[relative]["datasets"].append(dataset)
            if len(found) > 256:
                raise ValueError(
                    "发现超过 256 个世界目录，请移出备份目录并缩小实例范围"
                )
    return sorted(found.values(), key=lambda item: item["path"])
