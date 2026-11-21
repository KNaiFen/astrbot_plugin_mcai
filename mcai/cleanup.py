"""Build and revalidate an exact list of finished-task data to remove."""

import hashlib
import json
import shutil
import sqlite3
import stat
import time
from pathlib import Path

from .monthly_logs import LOCK, archive_path, rotate, valid_month
from .paths import resolve_file
from .storage_usage import SCAN_SECONDS, database_usage

A_CATEGORIES = {"traces", "web_page", "workspace", "outbox"}
B_CATEGORIES = {"jobs", "downloads", "backups"}
REPREVIEW = "清理范围或任务状态已变化，请重新预览"
REFERENCE_FIELDS = {
    "backup",
    "source_backup",
    "operation",
    "operation_id",
    "job_id",
    "export_id",
    "download_id",
    "download_ids",
    "export_ids",
    "reference",
    "argv",
}


def cleanup_scope(body, allowed):
    if not isinstance(body, dict):
        raise ValueError("清理请求须为 JSON 对象")
    key = body.get("task_id")
    if not isinstance(key, str) or not key:
        raise ValueError("请选择要清理的任务")
    artifact_id(key)
    return key, cleanup_categories(body.get("categories"), allowed)


def cleanup_categories(categories, allowed):
    if (
        not isinstance(categories, list)
        or not categories
        or any(not isinstance(item, str) or item not in allowed for item in categories)
    ):
        raise ValueError("请选择有效的清理类别")
    return sorted(set(categories))


def artifact_id(key):
    if (
        not isinstance(key, str)
        or len(key) != 32
        or any(char not in "0123456789abcdef" for char in key)
    ):
        raise ValueError("任务或产物编号无效，拒绝清理路径")
    return key


def settled(task):
    return (
        task["state"] in ("done", "stopped")
        and not task.get("cancel_pending")
        and task.get("archive_state") not in ("pending", "ready")
        and not task.get("cleanup", {}).get("pending")
    )


def no_redirect(path):
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    if stat.S_ISLNK(info.st_mode) or (
        getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
    ):
        raise ValueError(f"清理路径包含链接或重定向：{path}")
    return info


def checked_path(root, relative):
    root = Path(root).absolute()
    path = root / relative
    for component in (*reversed(path.parents), path):
        no_redirect(component)
    if resolve_file(root, relative) != path:
        raise ValueError(f"清理路径不在指定目录内：{path}")
    return path


def path_revision(path, directory, deadline):
    info = no_redirect(path)
    if info is None:
        return None
    if not (stat.S_ISDIR if directory else stat.S_ISREG)(info.st_mode):
        raise ValueError(f"清理路径类型不正确：{path}")
    signature = hashlib.sha256()
    size = 0
    pending = [(path, info)]
    while pending:
        if time.monotonic() >= deadline:
            raise ValueError("清理路径检查超时，请缩小选择后重新预览")
        current, info = pending.pop()
        signature.update(
            json.dumps(
                [
                    current.relative_to(path).as_posix(),
                    info.st_mode,
                    info.st_size,
                    info.st_dev,
                    info.st_ino,
                    info.st_mtime_ns,
                    info.st_ctime_ns,
                ],
                ensure_ascii=True,
            ).encode()
        )
        if stat.S_ISDIR(info.st_mode):
            for child in sorted(current.iterdir(), reverse=True):
                child_info = no_redirect(child)
                if child_info is None:
                    raise ValueError(REPREVIEW)
                pending.append((child, child_info))
        elif stat.S_ISREG(info.st_mode):
            size += info.st_size
        else:
            raise ValueError(f"清理路径包含非常规文件：{current}")
    return size, signature.hexdigest()


def path_item(kind, key, root, relative, deadline, *, directory=True, **fields):
    path = checked_path(root, relative)
    revision = path_revision(path, directory, deadline)
    if revision is not None:
        size, version = revision
        return {
            "kind": kind,
            "id": key,
            "path": str(path),
            "bytes": size,
            "file": (str(root), relative, directory),
            "version": version,
            **fields,
        }


def references(value):
    if isinstance(value, dict):
        for field, item in value.items():
            if field == "backups" and isinstance(item, dict):
                yield from item
            if field in REFERENCE_FIELDS:
                for reference in item if isinstance(item, list) else [item]:
                    if isinstance(reference, str):
                        yield Path(reference).name
            yield from references(item)
    elif isinstance(value, list):
        for item in value:
            yield from references(item)


def a_protection(store, key):
    task = store.get("task", key)
    if task is None or not settled(task):
        raise ValueError("只能清理已验收或已停止，且取消、归档和清理均已结算的任务")
    protected = set()
    settled_ids = []
    server_dirs = set()
    for (body,) in store.db.execute("SELECT body FROM records WHERE kind='task'"):
        current = json.loads(body)
        if current.get("directory"):
            server_dirs.add(Path(current["directory"]))
        ended = settled(current)
        active_plan = (current.get("approved_plan") or {}).get("status") == "active"
        calls = []
        for call_id in current.get("open_step", {}).get("calls", []):
            call = store.get("tool_call", call_id)
            if call is not None and call.get("state") != "completed":
                calls.append((call_id, call))
        if ended and not (active_plan or current.get("operation") or calls):
            settled_ids.append(current["id"])
            continue
        if current["id"] == key:
            raise ValueError("任务仍有未结算操作、待恢复审核或多轮方案，不能清理")
        for field in ("plan", "applied_plan", "approved_plan", "trial", "operation"):
            protected.update(references({field: current.get(field)}))
        for call_id, call in calls:
            protected.update(references(call))
            protected.update(references(store.get("review", call_id)))
    return task, server_dirs, protected, settled_ids


def a_plan(store, workspace, task, server_dirs, categories):
    key = task["id"]
    deadline = time.monotonic() + SCAN_SECONDS
    items = []
    for kind, root, relative, directory in (
        ("traces", store.directory, f"traces/{key}.jsonl", False),
        ("workspace", task.get("workspace_root", workspace), key, True),
    ):
        if kind not in categories:
            continue
        if item := path_item(kind, key, root, relative, deadline, directory=directory):
            if kind == "workspace":
                folder = Path(item["path"])
                # A custom workspace must not be used to clean other plugin data.
                preserved = server_dirs | {
                    (store.directory / name).resolve()
                    for name in ("knowledge", "exports", "downloads", "traces")
                }
                for keep in preserved:
                    if folder.is_relative_to(keep) or keep.is_relative_to(folder):
                        raise ValueError("任务工作区与其他插件数据重叠，拒绝清理")
            items.append(item)

    for kind in ("web_page", "outbox"):
        if kind not in categories:
            continue
        sql = """SELECT id, body FROM records
                 WHERE kind=? AND json_extract(body, '$.task')=?"""
        if kind == "outbox":
            sql += """ AND (json_extract(body, '$.sent')=1 OR
                            json_extract(body, '$.failed')=1)"""
        for row_id, body in store.db.execute(sql + " ORDER BY id", (kind, key)):
            encoded = body.encode()
            items.append(
                {
                    "kind": kind,
                    "id": row_id,
                    "path": f"state.sqlite3 / {kind} / {row_id}",
                    "bytes": len(encoded),
                    "records": 1,
                    "record_bytes": len(encoded),
                    "version": hashlib.sha256(encoded).hexdigest(),
                }
            )
    state = [
        task.get(field)
        for field in ("state", "cancel_pending", "archive_state", "cleanup")
    ]
    return items, state


def b_plan(store, key, categories, uploading, preserved_paths, settled_ids):
    active = store.active("operation") + store.active("background_job")
    if any(row["task_id"] == key for row in active):
        raise ValueError("B 端任务仍有未结算操作或后台结果，不能清理")
    protected = {row["id"] for row in active}
    for row in active:
        protected.update(references(row.get("arguments")))
    pending_reviews = set()
    if "backups" in categories:
        for review in store.all("review"):
            if review["task_id"] not in settled_ids:
                pending_reviews.update(review["backups"])
    installed = set()
    related = {
        "jobs": "background_job",
        "downloads": "download",
        "backups": "operation",
    }
    operations = store.db.execute(
        """SELECT body FROM records WHERE kind='operation' AND
           (json_extract(body, '$.action')='apply_plan' OR
            json_extract(body, '$.execution_state')='unknown')"""
    )
    for (body,) in operations:
        row = json.loads(body)
        for step in row["arguments"].get("steps", []):
            if step.get("action") == "install_download":
                installed.add(step["download_id"])
        if row.get("execution_state") == "unknown":
            protected.add(row["id"])
            protected.update(references(row["arguments"]))

    deadline = time.monotonic() + SCAN_SECONDS
    items = []
    for kind in categories:
        for (body,) in store.db.execute(
            """SELECT body FROM records WHERE kind=? AND json_extract(body, '$.task_id')=?
               ORDER BY id""",
            (related[kind], key),
        ):
            row = json.loads(body)
            item_id = artifact_id(row["id"])
            if kind == "downloads" and item_id in installed:
                continue
            item = path_item(
                kind,
                item_id,
                store.directory,
                f"{kind}/{item_id}",
                deadline,
                **(
                    {"instance": row["instance"], "operation_id": item_id}
                    if kind == "backups"
                    else {}
                ),
            )
            if item:
                path = Path(item["path"])
                if any(
                    path.is_relative_to(server) or server.is_relative_to(path)
                    for server in preserved_paths
                ):
                    raise ValueError(f"清理路径与服务端或保留数据重叠：{path}")
            if not item and kind == "backups":
                continue
            if item_id in protected or kind == "downloads" and item_id in uploading:
                raise ValueError(f"B 数据仍被未结算操作引用：{item_id}")
            if kind == "backups" and item_id in pending_reviews:
                raise ValueError(f"B 备份仍被待恢复审核引用：{item_id}")
            if kind != "backups":
                encoded = body.encode()
                signature = hashlib.sha256(encoded)
                count, size = 1, len(encoded)
                if kind == "jobs":
                    for seq, event in store.db.execute(
                        "SELECT seq,body FROM events WHERE topic=? ORDER BY seq",
                        ("job:" + item_id,),
                    ):
                        encoded = event.encode()
                        signature.update(f"{seq}:{len(encoded)}:".encode())
                        signature.update(encoded)
                        count += 1
                        size += len(encoded)
                item = item or {
                    "kind": kind,
                    "id": item_id,
                    "path": f"state.sqlite3 / {related[kind]} / {item_id}",
                    "version": None,
                    "bytes": 0,
                }
                item.update(
                    file_bytes=item["bytes"],
                    bytes=item["bytes"] + size,
                    records=count,
                    record_bytes=size,
                    record=(related[kind], signature.hexdigest()),
                )
            items.append(item)
    return items


def public_items(items):
    return [
        {k: v for k, v in item.items() if k not in ("file", "version", "record")}
        for item in items
    ]


def confirm_cleanup(body, token, categories):
    if body.get("token") != token:
        raise ValueError(REPREVIEW)
    if "backups" in categories and body.get("confirm_backups") is not True:
        raise ValueError("删除 B 端备份需要单独确认")


def clean(store, key, sender, items, *, archive=None):
    # Validate the entire set before the first deletion, including nested paths.
    deadline = time.monotonic() + SCAN_SECONDS
    files = []
    for item in items:
        if "file" in item:
            root, relative, directory = item["file"]
            path = checked_path(root, relative)
            if path_revision(path, directory, deadline) != (
                item.get("file_bytes", item["bytes"]),
                item["version"],
            ):
                raise ValueError(REPREVIEW)
            files.append((root, relative, directory))
    info = public_items(items)
    size = sum(item["bytes"] for item in items)
    store.log(
        "task_cleanup", task=key, sender=sender, items=info, bytes=size, archive=archive
    )
    try:
        for root, relative, directory in files:
            path = checked_path(root, relative)
            (shutil.rmtree if directory else Path.unlink)(path)
        with store.db:
            for item in items:
                identity = item["id"]
                if "record" in item:
                    store.db.execute(
                        "DELETE FROM records WHERE kind=? AND id=?",
                        (item["record"][0], identity),
                    )
                    if item["kind"] == "jobs":
                        store.db.execute(
                            "DELETE FROM events WHERE topic=?", ("job:" + identity,)
                        )
                        store.db.execute(
                            "INSERT INTO records VALUES ('cleaned_job',?,'{}')",
                            (identity,),
                        )
                elif "file" not in item:
                    store.db.execute(
                        "DELETE FROM records WHERE kind=? AND id=?",
                        (item["kind"], identity),
                    )
    except (OSError, ValueError, sqlite3.Error) as exc:
        store.log("task_cleanup_error", task=key, sender=sender, error=str(exc))
        raise ValueError(
            f"清理中断，可能已删除部分数据；请检查审计记录并重新预览：{exc}"
        ) from exc
    store.log("task_cleanup_completed", task=key, sender=sender, bytes=size)
    return {"items": info, "bytes": size, "archive": archive}


def compact_database(store, sender):
    path = store.directory / "state.sqlite3"
    before = database_usage(path)
    store.log("database_compact_started", sender=sender, before=before)
    try:
        for statement in (
            "PRAGMA wal_checkpoint(TRUNCATE)",
            "VACUUM",
            "PRAGMA wal_checkpoint(TRUNCATE)",
        ):
            row = store.db.execute(statement).fetchone()
            if row and row[0]:
                raise ValueError("数据库仍有读取或写入，请等待后重试")
    except (sqlite3.Error, ValueError) as exc:
        store.log("database_compact_failed", sender=sender, error=str(exc))
        raise ValueError(f"数据库压缩未完成：{exc}") from exc
    after = database_usage(path)
    store.log("database_compact_completed", sender=sender, before=before, after=after)
    return {"before": before, "after": after}


def delete_log_archives(store, names, sender, body):
    label = body.get("month")
    if not valid_month(label) or body.get("confirm") is not True:
        raise ValueError("请选择月份并确认删除日志归档")
    with LOCK:
        now = time.time()
        items = []
        for name in names:
            path = checked_path(store.directory, name)
            rotate(path, now)
            archive = archive_path(path, label)
            if info := no_redirect(archive):
                if not stat.S_ISREG(info.st_mode):
                    raise ValueError("日志归档不是普通文件")
                items.append((archive, info.st_size))
        if not items:
            raise ValueError("此月份没有日志归档")
        bytes_removed = sum(size for _, size in items)
        paths = [path.relative_to(store.directory).as_posix() for path, _ in items]
        store.log(
            "log_archives_delete_started",
            sender=sender,
            month=label,
            paths=paths,
            bytes=bytes_removed,
        )
        try:
            for path, _ in items:
                path.unlink()
        except OSError as exc:
            store.log(
                "log_archives_delete_failed", sender=sender, month=label, error=str(exc)
            )
            raise ValueError(
                f"删除中断，可能已删除部分归档；请刷新列表：{exc}"
            ) from exc
        store.log(
            "log_archives_deleted",
            sender=sender,
            month=label,
            paths=paths,
            bytes=bytes_removed,
        )
        return {"paths": paths, "bytes": bytes_removed}
