import datetime as dt
import gzip
import hashlib
import io
import json
import os
import re
import zlib
from collections import deque
from contextlib import closing
from pathlib import Path, PureWindowsPath

from .evidence import json_size
from .paths import resolve_file
from .text_files import BOMS, patch_text

SENSITIVE_EXACT_NAMES = frozenset(
    {
        "banned-ips.json",
        "banned-ips.txt",
        ".env",
        "authorized_keys",
        "known_hosts",
    }
)
SENSITIVE_SUFFIXES = frozenset(
    {".pem", ".key", ".p12", ".pfx", ".jks", ".keystore", ".kdbx", ".ppk"}
)
SENSITIVE_NAME_RE = re.compile(
    r"^(?:\.env\..+|banned-ips.*|id_rsa.*|id_ed25519.*|id_ecdsa.*"
    r"|(?:.*[._-])?(?:secret|secrets|credential|credentials|password|passwords|passwd)(?:[._-].*)?)$",
    re.I,
)
PRIVATE_KEY_LABEL = r"(?:[A-Z0-9]+[ -])*PRIVATE KEY(?: BLOCK)?"
PRIVATE_KEY_RE = re.compile(
    rf"-{{4,5}}\s*BEGIN (?P<label>{PRIVATE_KEY_LABEL})\s*-{{4,5}}"
    r".*?(?:-{4,5}\s*END (?P=label)\s*-{4,5}|\Z)",
    re.I | re.S,
)
PRIVATE_KEY_MARKER_RE = re.compile(
    rf"-{{4,5}}\s*(BEGIN|END) {PRIVATE_KEY_LABEL}\s*-{{4,5}}", re.I
)

LOG_HEADER = re.compile(
    r"^(?P<bracket>\[)?(?:(?P<iso>\d{4}-\d\d-\d\d)[ T]|"
    r"(?P<day>\d{2})(?P<month>1[0-2]|0?[1-9])月(?P<year>\d{4}) )?"
    r"(?P<time>\d\d:\d\d:\d\d(?:[.,]\d+)?)"
    r"(?(bracket)(?=\])|(?=\s|$))"
)
NUMBER = r"-?\d+(?:\.\d+)?"
COORD_SEP = r"(?:\s*,\s*|\s+)"
LOG_TIME_UNIT = r"(?:ms|ns|ticks?|s)\b(?![ \t]*=)"
LOG_JITTER = re.compile(
    r"(?P<fixed>\b(?:error(?:[_ -]?code)?|exit[_ -]?code|code|errno|status|port)\s*(?:[=:]\s*|\s+)"
    r"(?:0x[0-9a-f]+|\d+)\b)"
    rf"|(?P<coords>\bx\s*=\s*{NUMBER}{COORD_SEP}y\s*=\s*{NUMBER}{COORD_SEP}z\s*=\s*{NUMBER}\b"
    rf"|\(\s*{NUMBER}\s*,\s*{NUMBER}\s*,\s*{NUMBER}\s*\))"
    rf"|(?P<metric>\b(?:server_tick|tick|gap_ms|mspt|tps|ping)\s*=\s*){NUMBER}(?:[ \t]*{LOG_TIME_UNIT})?\b"
    r"|(?P<worker>\bWorker-Main-)\d+\b"
    r"|(?P<uuid>\b[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}\b)"
    r"|(?P<address>\b0x[0-9a-f]+\b|@[0-9a-f]{4,}\b)"
    rf"|(?P<duration>(?<![\w.]){NUMBER}[ \t]*{LOG_TIME_UNIT})",
    re.I,
)
LOG_MAX_FILES = 256
LOG_MAX_LINES = 100_000
LOG_MAX_SCAN_BYTES = 64 * 1024 * 1024
LOG_MAX_LINE_CHARS = 120_000
LOG_MAX_EVENT_BYTES = 256_000
LOG_MAX_GROUPS = 1000
LOG_RESULT_BYTES = 4 * 1024 * 1024
LOG_LIMIT_NOTE = "日志事件或去重分组数量过多，本次扫描已达上限；以上结果为截断前统计，请缩小时间范围或文件名后分批排查。"


class _LogSourceLimit(Exception):
    pass


class _LogSnapshot(io.RawIOBase):
    def __init__(self, stream, size, scan):
        self.stream, self.remaining, self.scan = stream, size, scan

    def readable(self):
        return True

    def readinto(self, buffer):
        available = LOG_MAX_SCAN_BYTES - self.scan.get("source_bytes", 0)
        if self.remaining and not available:
            raise _LogSourceLimit
        data = self.stream.read(min(len(buffer), self.remaining, available))
        buffer[: len(data)] = data
        self.remaining -= len(data)
        self.scan["source_bytes"] = LOG_MAX_SCAN_BYTES - available + len(data)
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


def is_sensitive_path(raw):
    if not isinstance(raw, str) or not raw.strip():
        return False
    for segment in PureWindowsPath(raw).parts:
        # Check the Win32 base name, including aliases with trailing dots/spaces or ADS.
        cleaned = segment.split(":", 1)[0].strip().strip("*?").rstrip(" .").lower()
        if not cleaned:
            continue
        if cleaned in SENSITIVE_EXACT_NAMES:
            return True
        if any(cleaned.endswith(suffix) for suffix in SENSITIVE_SUFFIXES):
            return True
        stem = cleaned.rsplit(".", 1)[0] if "." in cleaned else cleaned
        if SENSITIVE_NAME_RE.fullmatch(cleaned) or SENSITIVE_NAME_RE.fullmatch(stem):
            return True
    return False


def redact_private_key_line(line, hidden):
    safe, cursor = [], 0
    for marker in PRIVATE_KEY_MARKER_RE.finditer(line):
        if marker[1].upper() == "BEGIN" and not hidden:
            safe.extend((line[cursor : marker.start()], "[已脱敏私钥]"))
            hidden = True
        elif marker[1].upper() == "END" and hidden:
            hidden = False
        else:
            continue
        cursor = marker.end()
    if not hidden:
        safe.append(line[cursor:])
    return "".join(safe) or "[已脱敏私钥]", hidden


def find_files(directory, pattern, excluded=None, *, exclude_sensitive=False):
    root = Path(directory).resolve()
    if Path(pattern).is_absolute() or ".." in Path(pattern).parts:
        raise ValueError("glob 必须位于实例目录内")
    for path in root.glob(pattern):
        if not path.is_file():
            continue
        actual = resolve_file(root, path.relative_to(root))
        if exclude_sensitive and (
            is_sensitive_path(path.relative_to(root).as_posix())
            or is_sensitive_path(actual.relative_to(root).as_posix())
        ):
            continue
        if excluded and actual.is_relative_to(Path(excluded).resolve()):
            continue
        yield actual


def file_rows(directory, args, cancelled=lambda: False):
    mode = args["mode"]
    if mode not in ("find", "search"):
        path = resolve_file(directory, args["path"])
        if args.get("exclude_sensitive") and is_sensitive_path(
            path.relative_to(directory).as_posix()
        ):
            raise ValueError("只读问答不允许读取敏感文件。")
    if mode == "find":
        for path in find_files(
            directory,
            args.get("pattern", "**/*"),
            exclude_sensitive=args.get("exclude_sensitive", False),
        ):
            yield {
                "path": path.relative_to(directory).as_posix(),
                "size": path.stat().st_size,
                "modified_ns": path.stat().st_mtime_ns,
            }
    elif mode == "stat":
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
        _, preview = patch_text(path, args)
        yield preview
    elif mode == "search":
        counts = {}
        for row in log_rows(
            directory, {**args, "pattern": args.get("pattern", "**/*")}, cancelled
        ):
            if "error" in row or row.get("partial"):
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
        if cancelled():
            return
        size = path.stat().st_size
        if size > LOG_MAX_SCAN_BYTES:
            raise ValueError("文件读取超过64MiB，请缩小文件后重试")
        scan = {}
        with (
            shared_binary(path) as source,
            io.TextIOWrapper(
                io.BufferedReader(_LogSnapshot(source, size, scan)),
                encoding=args.get("encoding", "utf-8"),
            ) as stream,
        ):
            tail = deque(maxlen=args.get("line_count", 100))
            hidden = False
            number = scanned_chars = 0
            while not cancelled():
                line = stream.readline(LOG_MAX_LINE_CHARS + 1)
                if not line:
                    break
                number += 1
                scanned_chars += len(line)
                if len(line) > LOG_MAX_LINE_CHARS:
                    raise ValueError("文件单行超过120000字符，请定向缩小文件")
                if scanned_chars > LOG_MAX_SCAN_BYTES:
                    raise ValueError("文件扫描超过64MiB字符上限，请缩小文件")
                if args.get("exclude_sensitive"):
                    line, hidden = redact_private_key_line(line, hidden)
                if number < args.get("start_line", 1):
                    continue
                if mode == "read" and number >= args.get("start_line", 1) + args.get(
                    "line_count", 100
                ):
                    break
                row = {
                    "path": args["path"],
                    "line": number,
                    "text": line.rstrip("\r\n"),
                }
                if mode == "tail":
                    tail.append(row)
                else:
                    yield row
            if mode == "tail" and not cancelled():
                yield from tail
    else:
        raise ValueError("未知文件查询模式")


def _log_rows(directory, args, cancelled, scan):
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
    scanned_bytes = 0
    for path in find_files(
        directory,
        args.get("pattern", "logs/**/*.log*"),
        exclude_sensitive=args.get("exclude_sensitive", False),
    ):
        if cancelled():
            return
        if scan["scanned_files"] >= LOG_MAX_FILES:
            scan.update(truncated_reason="scan_files", event_complete=True)
            return
        scan["scanned_files"] += 1
        stat = path.stat()
        dated = re.search(r"\d{4}-\d\d-\d\d", path.name)
        date = dated.group() if dated else None
        active_time = None
        history = deque(maxlen=before)
        remaining, emitted = 0, 0
        unknown_reported = False
        number = 0
        hidden = False
        try:
            with (
                shared_binary(path) as raw,
                io.BufferedReader(_LogSnapshot(raw, stat.st_size, scan)) as snapshot,
                io.TextIOWrapper(
                    gzip.GzipFile(fileobj=snapshot)
                    if path.suffix == ".gz"
                    else snapshot,
                    encoding=args.get("encoding", "utf-8"),
                ) as stream,
            ):
                while True:
                    if cancelled():
                        return
                    line = stream.readline(LOG_MAX_LINE_CHARS + 1)
                    if not line:
                        break
                    match = LOG_HEADER.match(line)
                    scanned_bytes += len(line.encode("utf-8"))
                    if (
                        scan["scanned_lines"] >= LOG_MAX_LINES
                        or scanned_bytes > LOG_MAX_SCAN_BYTES
                        or len(line) > LOG_MAX_LINE_CHARS
                    ):
                        scan.update(
                            truncated_reason=(
                                "scan_lines"
                                if scan["scanned_lines"] >= LOG_MAX_LINES
                                else "scan_bytes"
                                if scanned_bytes > LOG_MAX_SCAN_BYTES
                                else "line_size"
                            ),
                            event_complete=number == 0 or bool(match),
                        )
                        return
                    number += 1
                    scan["scanned_lines"] += 1
                    if args.get("exclude_sensitive"):
                        line, hidden = redact_private_key_line(line, hidden)
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
        except _LogSourceLimit:
            scan.update(truncated_reason="source_bytes", event_complete=number == 0)
            return
        except (OSError, UnicodeError, EOFError, zlib.error) as exc:
            yield {
                "path": path.relative_to(directory).as_posix(),
                "error": f"{type(exc).__name__}: {exc}",
            }


def log_scan_summary(scan, scanned_events, unique_groups_total=0, omitted_groups=0):
    return {
        "scanned_files": scan["scanned_files"],
        "scanned_events": scanned_events,
        "unique_groups_total": unique_groups_total,
        "omitted_groups": omitted_groups,
        **(
            {
                "partial": True,
                "truncated_reason": scan["truncated_reason"],
                "note": LOG_LIMIT_NOTE,
            }
            if "truncated_reason" in scan
            else {}
        ),
    }


def log_rows(directory, args, cancelled):
    scan = {"scanned_files": 0, "scanned_lines": 0}
    size = 0
    with closing(_log_rows(directory, args, cancelled, scan)) as rows:
        for row in rows:
            size += json_size(row) + 2
            if size > LOG_RESULT_BYTES:
                scan["truncated_reason"] = "result_bytes"
                break
            yield row
    if "truncated_reason" in scan:
        yield log_scan_summary(scan, scan["scanned_lines"])


def log_groups(directory, args, cancelled, artifact):
    """Group complete events using a normalized signature and retain the first original."""
    expression = re.compile(
        args["query"] if args.get("regex") else re.escape(args["query"]),
        0 if args.get("case_sensitive") else re.I,
    )
    groups, issues, event = {}, [], []
    scan = {"scanned_files": 0, "scanned_lines": 0}
    scanned_events = event_bytes = 0
    artifact_bytes = json_size({"groups": [], "issues": []})
    omitted_new_group = False

    def normalize(match):
        if match["fixed"]:
            return match[0]
        if match["metric"] or match["worker"]:
            return f"{match[match.lastgroup]}<n>"
        return f"<{match.lastgroup}>"

    def finish():
        nonlocal scanned_events, artifact_bytes, omitted_new_group
        if not event:
            return True
        scanned_events += 1
        text = "\n".join(row["text"] for row in event)
        if not expression.search(text):
            return True
        signature = LOG_JITTER.sub(normalize, LOG_HEADER.sub("<time>", text, count=1))
        key = hashlib.sha256((event[0]["path"] + "\n" + signature).encode()).hexdigest()
        first, last = event[0], event[-1]
        span = [first["line"], last["line"], first["time"]]
        end = {"line": last["line"], "time": last["time"]}
        group = groups.get(key)
        if group is None:
            if len(groups) >= LOG_MAX_GROUPS:
                scan["truncated_reason"] = "unique_groups"
                omitted_new_group = True
                return False
            candidate = {
                "group_id": key,
                "path": first["path"],
                "count": 1,
                "first": {"line": first["line"], "time": first["time"]},
                "last": end,
                "ranges": [span],
                "event": event,
            }
            added = json_size(candidate) + 2
        else:
            count = group["count"] + 1
            added = (
                json_size(span)
                + 2
                + len(str(count))
                - len(str(group["count"]))
                + json_size(end)
                - json_size(group["last"])
            )
        if artifact_bytes + added > LOG_RESULT_BYTES:
            scan["truncated_reason"] = "artifact_bytes"
            omitted_new_group = group is None
            return False
        artifact_bytes += added
        if group is None:
            groups[key] = candidate
        else:
            group.update(count=count, last=end)
            group["ranges"].append(span)
        return True

    with closing(
        _log_rows(
            directory,
            {**args, "query": "", "regex": False, "before": 0, "after": 0},
            cancelled,
            scan,
        )
    ) as source:
        for row in source:
            if "text" not in row:
                artifact_bytes += json_size(row) + 2
                if artifact_bytes > LOG_RESULT_BYTES:
                    scan["truncated_reason"] = "artifact_bytes"
                    break
                issues.append(row)
                continue
            if event and (
                row["path"] != event[-1]["path"]
                or row["line"] != event[-1]["line"] + 1
                or LOG_HEADER.match(row["text"])
            ):
                if not finish():
                    break
                event, event_bytes = [], 0
            row["matched"] = bool(expression.search(row["text"]))
            event_bytes += json_size(row) + 2
            if event_bytes > LOG_MAX_EVENT_BYTES:
                scan["truncated_reason"] = "event_size"
                break
            event.append(row)
        else:
            if not cancelled() and scan.get("event_complete", True):
                finish()
    if cancelled():
        return
    rows = list(groups.values())
    artifact.write_text(
        json.dumps({"groups": rows, "issues": issues}, ensure_ascii=False),
        encoding="utf-8",
    )
    common = sorted(range(len(rows)), key=lambda i: -rows[i]["count"])[:24]
    rare = sorted(range(len(rows)), key=lambda i: rows[i]["count"])[:16]
    selected = list(dict.fromkeys([*common, *rare]))
    unique_total = len(rows) + omitted_new_group
    omitted = unique_total - len(selected)
    summary_issues, issues_bytes = [], 0
    for issue in issues:
        issues_bytes += json_size(issue) + 2
        if issues_bytes > 6000:
            break
        summary_issues.append(issue)
    yield {
        "view": "events",
        "scanned_lines": scan["scanned_lines"],
        "matching_events": sum(row["count"] for row in rows),
        "unique_groups": len(rows),
        **log_scan_summary(scan, scanned_events, unique_total, omitted),
        "issues": summary_issues,
        **({"issue_count": len(issues)} if len(issues) > len(summary_issues) else {}),
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
        for dataset in ("region", "entities", "poi", "data", "playerdata"):
            if dataset not in folders:
                continue
            folders.remove(dataset)
            if dataset in ("data", "playerdata") and not (
                (base / "level.dat").is_file()
                or any((base / name).is_dir() for name in ("region", "entities", "poi"))
            ):
                continue
            if not any(
                path.is_file()
                and (
                    path.suffix == ".dat"
                    if dataset in ("data", "playerdata")
                    else re.fullmatch(r"r\.-?\d+\.-?\d+\.mc[ar]", path.name)
                )
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


def resolve_world_root(directory, excluded=None, *, world_path=None, dimension=None):
    """Resolve one discovered dimension directory; ambiguity is never guessed."""
    directory = Path(directory).resolve()
    worlds = discover_worlds(directory, excluded)
    if world_path is not None:
        relative = Path(world_path)
        target = (
            directory if str(relative) == "." else resolve_file(directory, relative)
        )
        worlds = [item for item in worlds if directory / item["path"] == target]
    if dimension is not None:
        value = str(dimension)
        if re.fullmatch(r"-?\d+", value):
            number = int(value)
            value = "." if number == 0 else f"DIM{number}"
        elif value in (
            "minecraft:overworld",
            "minecraft:the_nether",
            "minecraft:the_end",
        ):
            value = {
                "minecraft:overworld": ".",
                "minecraft:the_nether": "DIM-1",
                "minecraft:the_end": "DIM1",
            }[value]
        elif ":" in value:
            if not re.fullmatch(r"[a-z0-9_.-]+:[a-z0-9_./-]+", value) or any(
                part in ("", ".", "..") for part in value.replace(":", "/").split("/")
            ):
                raise ValueError("维度命名空间或路径无效")
            value = "dimensions/" + value.replace(":", "/", 1)
        elif value != "." and not re.fullmatch(r"DIM-?\d+", value):
            raise ValueError("维度须为标准资源名或数字ID")
        worlds = [item for item in worlds if item["dimension"] == value]
    if len(worlds) != 1:
        candidates = [item["path"] for item in worlds] or [
            item["path"] for item in discover_worlds(directory, excluded)
        ]
        raise ValueError(
            f"世界/维度须唯一匹配，实际{len(worlds)}个；候选：{candidates}"
        )
    return directory / worlds[0]["path"]


def resolve_region_path(
    directory,
    excluded=None,
    *,
    path=None,
    dimension=None,
    world_path=None,
    block_x=None,
    block_z=None,
    x=None,
    z=None,
    dataset="region",
    require_exists=True,
):
    if path is not None:
        target = resolve_file(directory, path)
    else:
        if dataset not in ("region", "entities", "poi"):
            raise ValueError("区域dataset须为region、entities或poi")
        if block_x is not None or block_z is not None:
            if block_x is None or block_z is None or x is not None or z is not None:
                raise ValueError("须提供一对方块坐标或一对区块坐标")
            x, z = block_x // 16, block_z // 16
        if x is None or z is None:
            raise ValueError("缺少区块或方块坐标")
        base = resolve_world_root(
            directory, excluded, world_path=world_path, dimension=dimension
        )
        target = base / dataset / f"r.{x // 32}.{z // 32}.mca"
        if (
            dataset == "region"
            and not target.exists()
            and target.with_suffix(".mcr").is_file()
        ):
            target = target.with_suffix(".mcr")
    if require_exists and not target.is_file():
        raise ValueError(f"区域文件不存在：{target}")
    return target
