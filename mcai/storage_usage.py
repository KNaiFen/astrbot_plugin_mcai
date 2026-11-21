"""Read-only disk and record counts for the settings page."""

import heapq
import os
import shutil
import sqlite3
import stat
import time
from contextlib import closing
from pathlib import Path

from .monthly_logs import archives
from .storage import Store

SCAN_SECONDS = 5
QUERY_SECONDS = 2
STORAGE_TIMEOUT = 10


def volume_path(path):
    """Return a usable path and its volume, even before the final directory exists."""
    for candidate in (path, *path.parents):
        try:
            return candidate, candidate.stat().st_dev
        except FileNotFoundError:
            if candidate == candidate.parent:
                raise


def external_backup(default, scheduled):
    if not scheduled or (path := Path(scheduled)) == default:
        return None
    try:
        probe, volume = volume_path(path)
    except OSError:
        return path, None
    return (path, probe) if volume != volume_path(default)[1] else None


def usage():
    return {"bytes": 0, "files": 0, "complete": True}


def entries(path, deadline, result):
    try:
        with os.scandir(path) as children:
            for entry in children:
                if time.monotonic() >= deadline:
                    result["complete"] = False
                    break
                try:
                    info = entry.stat(follow_symlinks=False)
                except FileNotFoundError:
                    continue
                except PermissionError:
                    result["complete"] = False
                    continue
                if stat.S_ISLNK(info.st_mode) or (
                    getattr(info, "st_file_attributes", 0)
                    & stat.FILE_ATTRIBUTE_REPARSE_POINT
                ):
                    continue
                yield entry, info
    except FileNotFoundError:
        return
    except PermissionError:
        result["complete"] = False


def tree_usage(path, deadline):
    result = usage()
    pending = [path]
    while pending:
        if time.monotonic() >= deadline:
            result["complete"] = False
            break
        for entry, info in entries(pending.pop(), deadline, result):
            if stat.S_ISDIR(info.st_mode):
                pending.append(entry.path)
            elif stat.S_ISREG(info.st_mode):
                result["bytes"] += info.st_size
                result["files"] += 1
    return result


def file_usage(path):
    result = usage()
    try:
        info = path.stat(follow_symlinks=False)
    except FileNotFoundError:
        return result
    if stat.S_ISREG(info.st_mode):
        result.update(bytes=info.st_size, files=1)
    return result


def database_usage(path):
    main = file_usage(path)
    wal = file_usage(path.with_name(path.name + "-wal"))
    return {
        "bytes": main["bytes"] + wal["bytes"],
        "files": main["files"] + wal["files"],
        "complete": True,
        "database_bytes": main["bytes"],
        "wal_bytes": wal["bytes"],
    }


def free_pages_bytes(db):
    return (
        db.execute("PRAGMA freelist_count").fetchone()[0]
        * db.execute("PRAGMA page_size").fetchone()[0]
    )


def log_usage(path):
    result = file_usage(path)
    for _, archive in archives(path):
        size = file_usage(archive)
        result["bytes"] += size["bytes"]
        result["files"] += size["files"]
    return result


def audit_usage(path, deadline):
    result = log_usage(path)
    result["lines"] = 0
    remaining = file_usage(path)["bytes"]
    if remaining:
        try:
            with path.open("rb") as stream:
                while remaining:
                    if time.monotonic() >= deadline:
                        result["complete"] = False
                        break
                    chunk = stream.read(min(remaining, 1024 * 1024))
                    if not chunk:
                        result["complete"] = False
                        break
                    remaining -= len(chunk)
                    result["lines"] += chunk.count(b"\n")
        except FileNotFoundError:
            result["complete"] = False
    return result


def a_storage(directory, workspace):
    deadline = time.monotonic() + SCAN_SECONDS
    traces = usage()
    traces["tasks"] = 0
    unassigned_archives = {
        path.name for _, path in archives(directory / "traces/unassigned.jsonl")
    }

    def trace_files():
        for entry, info in entries(directory / "traces", deadline, traces):
            if entry.name in unassigned_archives and stat.S_ISREG(info.st_mode):
                traces["bytes"] += info.st_size
                traces["files"] += 1
                continue
            if not entry.name.endswith(".jsonl") or not stat.S_ISREG(info.st_mode):
                continue
            traces["bytes"] += info.st_size
            traces["files"] += 1
            task_id = entry.name[:-6]
            if task_id != "unassigned":
                traces["tasks"] += 1
                yield info.st_size, task_id

    top = [
        {"bytes": size, "task_id": task, "name": None, "state": None}
        for size, task in heapq.nlargest(10, trace_files())
    ]
    directories = {
        name: tree_usage(path, deadline)
        for name, path in (
            ("knowledge", directory / "knowledge"),
            ("downloads", directory / "downloads"),
            ("exports", directory / "exports"),
            ("workspaces", workspace),
        )
    }
    categories = {
        "traces": traces,
        "audit": audit_usage(directory / "audit.jsonl", deadline),
        "state": database_usage(directory / "state.sqlite3"),
        **directories,
    }
    kinds = []
    complete = True
    with closing(Store(directory, read_only=True)) as store:
        categories["state"]["reclaimable_bytes"] = free_pages_bytes(store.db)
        query_deadline = time.monotonic() + QUERY_SECONDS
        store.db.set_progress_handler(lambda: time.monotonic() >= query_deadline, 1000)
        try:
            for row in top:
                task = store.db.execute(
                    """SELECT json_extract(body, '$.name'), json_extract(body, '$.state')
                    FROM records WHERE kind='task' AND id=?""",
                    (row["task_id"],),
                ).fetchone()
                if task:
                    row["name"], row["state"] = task
            for kind, count, size in store.db.execute(
                """SELECT kind, COUNT(*), SUM(length(CAST(body AS BLOB)))
                FROM records GROUP BY kind ORDER BY kind"""
            ):
                kinds.append({"kind": kind, "count": count, "bytes": size})
        except sqlite3.OperationalError as exc:
            if exc.sqlite_errorcode != sqlite3.SQLITE_INTERRUPT:
                raise
            complete = False
    return {
        "scanned_at": time.time(),
        "categories": categories,
        "largest_traces": top,
        "record_kinds": kinds,
        "records_complete": complete,
    }


def b_storage(directory, workspace, scheduled_backup_dir=None):
    deadline = time.monotonic() + SCAN_SECONDS
    backups, rows = usage(), []
    for entry, info in entries(directory / "backups", deadline, backups):
        if stat.S_ISREG(info.st_mode):
            backups["bytes"] += info.st_size
            backups["files"] += 1
        elif stat.S_ISDIR(info.st_mode):
            size = tree_usage(entry.path, deadline)
            backups["bytes"] += size["bytes"]
            backups["files"] += size["files"]
            backups["complete"] &= size["complete"]
            rows.append(
                {
                    "operation_id": entry.name,
                    "time": info.st_mtime,
                    "instance": None,
                    "task_id": None,
                    "task_status": None,
                    **size,
                }
            )

    categories = {
        "backups": backups,
        "incidents": database_usage(directory / "incidents.sqlite3"),
        "execution_log": log_usage(directory / "execution.log"),
        "downloads": tree_usage(directory / "downloads", deadline),
        "jobs": tree_usage(directory / "jobs", deadline),
        "test_servers": tree_usage(workspace, deadline),
    }
    state_path = directory / "state.sqlite3"
    categories["state"] = database_usage(state_path)
    if state_path.is_file():
        with closing(Store(directory, read_only=True)) as reader:
            categories["state"]["reclaimable_bytes"] = free_pages_bytes(reader.db)
    categories["audit"] = log_usage(directory / "audit.jsonl")
    metadata_complete = True
    states = {}
    if rows:
        with closing(Store(directory, read_only=True)) as store:
            query_deadline = time.monotonic() + QUERY_SECONDS
            store.db.set_progress_handler(
                lambda: time.monotonic() >= query_deadline, 1000
            )
            try:
                for row in rows:
                    current = store.db.execute(
                        """SELECT json_extract(body, '$.created'),
                        json_extract(body, '$.instance'), json_extract(body, '$.task_id')
                        FROM records WHERE kind='operation' AND id=?""",
                        (row["operation_id"],),
                    ).fetchone()
                    if current:
                        created, row["instance"], row["task_id"] = current
                        if created is not None:
                            row["time"] = created
                task_ids = {
                    row["task_id"] for row in rows if row["task_id"] is not None
                }
                if task_ids:
                    for task_id, status, created in store.db.execute(
                        """SELECT json_extract(body, '$.task_id'),
                        json_extract(body, '$.status'), json_extract(body, '$.created')
                        FROM records WHERE kind IN ('operation', 'background_job')"""
                    ):
                        if task_id not in task_ids or status is None:
                            continue
                        rank = (status == "running", status == "pending", created or 0)
                        if task_id not in states or rank > states[task_id][0]:
                            states[task_id] = (rank, status)
            except sqlite3.OperationalError as exc:
                if exc.sqlite_errorcode != sqlite3.SQLITE_INTERRUPT:
                    raise
                metadata_complete = False
    for row in rows:
        if row["task_id"] in states:
            row["task_status"] = states[row["task_id"]][1]
    extra = external_backup(directory / "backups", scheduled_backup_dir)
    scheduled_backups = None
    if extra:
        path, probe = extra
        size = None
        if probe is not None:
            try:
                size = tree_usage(path, deadline)
            except OSError:
                size = None
        scheduled_backups = {"path": str(path), "usage": size}
    return {
        "scanned_at": time.time(),
        "categories": categories,
        "backups": sorted(rows, key=lambda row: (-row["time"], row["operation_id"])),
        "backup_metadata_complete": metadata_complete,
        "disk_free_bytes": shutil.disk_usage(directory).free,
        "scheduled_backups": scheduled_backups,
    }
