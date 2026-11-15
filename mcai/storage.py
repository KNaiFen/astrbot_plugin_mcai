import json
import sqlite3
import time
from pathlib import Path


class Store:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.directory / "state.sqlite3")
        self.db.execute("PRAGMA journal_mode=WAL")
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
                    OR json_extract(body, '$.archive_state') IN ('pending', 'ready'));
        """)

    def save(self, kind, key, body):
        with self.db:
            self.db.execute(
                "INSERT OR REPLACE INTO records VALUES (?, ?, ?)",
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

    def pending_outbox(self, limit=100):
        return [
            json.loads(row[0])
            for row in self.db.execute(
                "SELECT body FROM records WHERE kind='outbox' AND json_extract(body, '$.sent')=0 ORDER BY rowid LIMIT ?",
                (limit,),
            )
        ]

    def live_tasks(self):
        return [
            json.loads(row[0])
            for row in self.db.execute(
                """SELECT body FROM records WHERE kind='task' AND (
                json_extract(body, '$.state') NOT IN ('done', 'stopped')
                OR json_extract(body, '$.cancel_pending')=1
                OR json_extract(body, '$.archive_state') IN ('pending', 'ready')) ORDER BY rowid"""
            )
        ]

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
        with (self.directory / "audit.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def close(self):
        self.db.close()
