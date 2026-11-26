import json
import sqlite3
import time
from pathlib import Path

from .monthly_logs import append as append_log


class Store:
    def __init__(self, directory, *, read_only=False):
        self.directory = Path(directory)
        if read_only:
            path = (self.directory / "state.sqlite3").resolve()
            self.db = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
            self.db.execute("PRAGMA busy_timeout=5000")
            return
        self.directory.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.directory / "state.sqlite3", timeout=5)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=NORMAL")
        self.db.execute("PRAGMA busy_timeout=5000")
        index = self.db.execute(
            "SELECT sql FROM sqlite_master WHERE type='index' AND name='live_tasks'"
        ).fetchone()
        if index and "$.cleanup.pending" not in index[0]:
            self.db.execute("DROP INDEX live_tasks")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS records (
                kind TEXT, id TEXT, body TEXT NOT NULL,
                PRIMARY KEY(kind, id)
            );
            CREATE TABLE IF NOT EXISTS events (
                seq INTEGER PRIMARY KEY AUTOINCREMENT,
                topic TEXT NOT NULL, body TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS event_topic ON events(topic, seq);
            CREATE INDEX IF NOT EXISTS active_records ON records(
                kind, json_extract(body, '$.instance'), json_extract(body, '$.task_id')
            ) WHERE json_extract(body, '$.status') IN ('pending', 'running');
            CREATE INDEX IF NOT EXISTS unsent_outbox ON records(kind)
                WHERE kind='outbox' AND json_extract(body, '$.sent')=0;
            CREATE INDEX IF NOT EXISTS live_tasks ON records(kind)
                WHERE kind='task' AND (json_extract(body, '$.state') NOT IN ('done', 'stopped')
                    OR json_extract(body, '$.cancel_pending')=1
                    OR json_extract(body, '$.cleanup.pending')=1
                    OR json_extract(body, '$.archive_state') IN ('pending', 'ready'));
        """)

    def save(self, kind, key, body):
        self.save_many((kind, key, body))

    def save_many(self, *records):
        with self.db:
            for kind, key, body in records:
                self.db.execute(
                    "INSERT INTO records VALUES (?, ?, ?) ON CONFLICT(kind,id) DO UPDATE SET body=excluded.body"
                    if kind == "outbox"
                    else "INSERT OR REPLACE INTO records VALUES (?, ?, ?)",
                    (kind, key, json.dumps(body, ensure_ascii=False)),
                )

    def get(self, kind, key):
        row = self.db.execute(
            "SELECT body FROM records WHERE kind=? AND id=?", (kind, key)
        ).fetchone()
        return json.loads(row[0]) if row else None

    def all(self, kind):
        return [
            json.loads(row[0])
            for row in self.db.execute(
                "SELECT body FROM records WHERE kind=? ORDER BY rowid", (kind,)
            )
        ]

    def task_records(self, *, active=False, selected=None):
        # A single read sees both parts at the same revision even during export.
        sql = """
            SELECT task.body, history.body FROM records AS task
            LEFT JOIN records AS history
                ON history.kind='task_messages' AND history.id=task.id
            WHERE task.kind='task'
        """
        if active:
            sql += """ AND (
                json_extract(task.body, '$.state') NOT IN ('done', 'stopped')
                OR json_extract(task.body, '$.cancel_pending')=1
                OR json_extract(task.body, '$.cleanup.pending')=1
                OR json_extract(task.body, '$.archive_state') IN ('pending', 'ready'))"""
        params = ()
        if selected is not None:
            sql += " AND task.id IN (SELECT value FROM json_each(?))"
            params = (json.dumps(list(selected)),)
        for body, history in self.db.execute(sql + " ORDER BY task.rowid", params):
            task = json.loads(body)
            if history is not None:
                task["messages"] = json.loads(history)
            yield task

    def event(self, topic, body):
        with self.db:
            cursor = self.db.execute(
                "INSERT INTO events(topic, body) VALUES (?, ?)",
                (topic, json.dumps(body, ensure_ascii=False)),
            )
        return cursor.lastrowid

    def active(self, kind, instance=None, task_id=None):
        sql = "SELECT body FROM records WHERE kind=? AND json_extract(body, '$.status') IN ('pending', 'running')"
        params = [kind]
        for field, value in (("instance", instance), ("task_id", task_id)):
            if value is not None:
                sql += f" AND json_extract(body, '$.{field}')=?"
                params.append(value)
        return [json.loads(row[0]) for row in self.db.execute(sql, params)]

    def pending_outbox(self, limit=100, *, now=None, include_failed=False):
        return [
            json.loads(row[0])
            for row in self.db.execute(
                """SELECT body FROM records
                WHERE kind='outbox' AND json_extract(body, '$.sent')=0
                AND (? OR COALESCE(json_extract(body, '$.failed'),0)=0)
                AND (? IS NULL OR COALESCE(json_extract(body, '$.retry_at'), 0)<=?)
                AND (? IS NULL OR json_extract(body, '$.single_fault')=1 OR rowid IN (
                    SELECT MIN(rowid) FROM records
                    WHERE kind='outbox' AND json_extract(body, '$.sent')=0
                    AND COALESCE(json_extract(body, '$.failed'),0)=0
                    AND COALESCE(json_extract(body, '$.single_fault'),0)=0
                    GROUP BY json_extract(body, '$.origin')))
                ORDER BY rowid LIMIT ?""",
                (include_failed, now, now, now, limit),
            )
        ]

    def outbox_probe(self, item):
        row = self.db.execute(
            """SELECT body FROM records
            WHERE kind='outbox' AND json_extract(body, '$.sent')=0
            AND COALESCE(json_extract(body, '$.failed'),0)=0
            AND COALESCE(json_extract(body, '$.single_fault'),0)=0
            AND json_extract(body, '$.origin')=?
            AND rowid > (SELECT rowid FROM records WHERE kind='outbox' AND id=?)
            ORDER BY rowid LIMIT 1""",
            (item["origin"], item["id"]),
        ).fetchone()
        return json.loads(row[0]) if row else None

    def outbox_status(self):
        row = self.db.execute(
            """SELECT COUNT(*) OVER (), json_extract(body, '$.error')
            FROM records WHERE kind='outbox' AND json_extract(body, '$.sent')=0
            ORDER BY json_extract(body, '$.error_at') DESC, rowid DESC LIMIT 1"""
        ).fetchone()
        count, error = row if row else (0, None)
        return {"pending": count, "latest_error": error}

    def live_tasks(self):
        return list(self.task_records(active=True))

    def job_batch(self, key, rows, fields):
        job = self.get("background_job", key)
        job.update(fields)
        with self.db:
            self.db.executemany(
                "INSERT INTO events(topic, body) VALUES (?, ?)",
                [("job:" + key, json.dumps(row, ensure_ascii=False)) for row in rows],
            )
            self.db.execute(
                "UPDATE records SET body=? WHERE kind='background_job' AND id=?",
                (json.dumps(job, ensure_ascii=False), key),
            )

    def events(self, topic, after=0, limit=200):
        return [
            {"seq": row[0], "body": json.loads(row[1])}
            for row in self.db.execute(
                "SELECT seq, body FROM events WHERE topic=? AND seq>? ORDER BY seq LIMIT ?",
                (topic, after, limit),
            )
        ]

    def log(self, topic, **fields):
        entry = {"time": time.time(), "topic": topic, **fields}
        append_log(
            self.directory / "audit.jsonl",
            (json.dumps(entry, ensure_ascii=False) + "\n").encode(),
            entry["time"],
        )

    def close(self):
        self.db.close()
