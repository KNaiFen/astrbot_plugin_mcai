"""Serialize log writers, monthly gzip rotation and archive maintenance."""

import gzip
import json
import shutil
import time
import uuid
from contextlib import ExitStack, contextmanager
from threading import RLock

from .queries import shared_binary

LOCK = RLock()
A_LOGS = ("audit.jsonl", "traces/unassigned.jsonl")
B_LOGS = ("audit.jsonl", "execution.log")


def month(stamp):
    return time.strftime("%Y%m", time.localtime(stamp))


def valid_month(value):
    return (
        isinstance(value, str)
        and len(value) == 6
        and value.isascii()
        and value.isdecimal()
        and "01" <= value[4:] <= "12"
    )


def archive_path(path, label):
    return path.with_name(f"{path.stem}-{label}{path.suffix}.gz")


def archives(path):
    suffix = path.suffix + ".gz"
    prefix = path.stem + "-"
    for entry in sorted(path.parent.glob(f"{prefix}*{suffix}")):
        label = entry.name[len(prefix) : -len(suffix)]
        if valid_month(label):
            yield label, entry


def rotate(path, stamp):
    with LOCK:
        if not path.exists():
            return
        previous = month(path.stat().st_mtime)
        if previous >= month(stamp):
            return
        targets = {}
        try:
            extension = path.suffix
            with ExitStack() as streams, path.open("rb") as source:
                for line in source:
                    label = previous
                    if extension == ".jsonl":
                        # A pre-upgrade file can contain more than one month.
                        try:
                            label = month(json.loads(line)["time"])
                        except (ValueError, TypeError, KeyError):
                            pass  # Preserve invalid legacy lines for diagnosis.
                    if label not in targets:
                        target = archive_path(path, label)
                        temporary = target.with_suffix(".gz.tmp")
                        if target.exists():
                            shutil.copyfile(target, temporary)
                        else:
                            temporary.write_bytes(b"")
                        targets[label] = (
                            target,
                            temporary,
                            streams.enter_context(gzip.open(temporary, "ab")),
                        )
                    targets[label][2].write(line)
            for target, temporary, _ in targets.values():
                temporary.replace(target)
            # Existing diagnostic readers may still have the old file open on Windows.
            retired = path.with_name(f".{path.name}.{uuid.uuid4().hex}.rotated")
            path.replace(retired)
            retired.unlink()
        finally:
            for _, temporary, _ in targets.values():
                temporary.unlink(missing_ok=True)


def append(path, data, stamp):
    with LOCK:
        rotate(path, stamp)
        path.parent.mkdir(exist_ok=True)
        with path.open("ab") as stream:
            stream.write(data)


@contextmanager
def diagnostic_sources(directory, start, end):
    """Pin open handles before releasing the rotation lock."""
    with ExitStack() as stack:
        sources = {}
        with LOCK:
            for name in A_LOGS:
                active = directory / name
                for path in [
                    *(
                        p
                        for label, p in archives(active)
                        if month(start) <= label <= month(end)
                    ),
                    active,
                ]:
                    if path.is_file():
                        raw = stack.enter_context(shared_binary(path))
                        sources[path] = (
                            raw
                            if path == active
                            else stack.enter_context(gzip.GzipFile(fileobj=raw)),
                            path.stat().st_size if path == active else None,
                        )
        yield sources


def archive_list(directory, names):
    with LOCK:
        return [
            {
                "month": label,
                "path": entry.relative_to(directory).as_posix(),
                "bytes": entry.stat().st_size,
            }
            for name in names
            for label, entry in archives(directory / name)
        ]
