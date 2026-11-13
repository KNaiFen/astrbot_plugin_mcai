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
