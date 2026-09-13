"""One SQLite file for conversations, provider history, and turn measurements."""
import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path

from .config import ROOT


@contextmanager
def connect():
    path = Path(os.getenv("AGENT_DB_PATH", str(ROOT / "chat.sqlite3")))
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    try:
        with db:
            db.execute("PRAGMA foreign_keys = ON")
            yield db
    finally:
        db.close()


def initialize():
    with connect() as db:
        db.executescript('''
        CREATE TABLE IF NOT EXISTS conversations (
            id TEXT PRIMARY KEY, title TEXT NOT NULL, history TEXT NOT NULL DEFAULT '[]');
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY, conversation_id TEXT REFERENCES conversations(id) ON DELETE CASCADE,
            payload TEXT NOT NULL);
        ''')


def create():
    item = {"id": uuid.uuid4().hex, "title": "New conversation"}
    with connect() as db:
        db.execute("INSERT INTO conversations(id,title) VALUES(:id,:title)", item)
    return item


def listing():
    with connect() as db:
        return [dict(row) for row in db.execute("SELECT id,title FROM conversations ORDER BY rowid DESC")]


def get(cid):
    with connect() as db:
        row = db.execute("SELECT * FROM conversations WHERE id=?", (cid,)).fetchone()
        if row is None:
            return None
        return {"id": row["id"], "title": row["title"], "history": json.loads(row["history"]),
                "messages": [json.loads(r[0]) for r in db.execute(
                    "SELECT payload FROM messages WHERE conversation_id=? ORDER BY id", (cid,))]}


def save(cid, user, assistant, history):
    with connect() as db:
        db.executemany("INSERT INTO messages(conversation_id,payload) VALUES(?,?)",
                       [(cid, json.dumps(m)) for m in (user, assistant)])
        db.execute("UPDATE conversations SET history=?, title=CASE WHEN title='New conversation' THEN ? ELSE title END WHERE id=?",
                   (json.dumps(history), user["content"][:60], cid))


def delete(cid):
    with connect() as db:
        db.execute("DELETE FROM conversations WHERE id=?", (cid,))
